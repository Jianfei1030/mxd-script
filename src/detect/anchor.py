"""角色名字牌锚点识别。

怀旧服把角色名渲染在角色脚下(白字 + 半透明底框),用它当"角色在哪"的锚点,
比给 YOLO 加 player 类别省事,也不会把长得一样的别的玩家认成自己。

实测结论(2026-08-06,详见 spec §3,勿再重复踩):
- 2560 宽的整图/宽带送 OCR 会被检测模型按最长边缩到 ~960,31px 的字被压到 ~12px 漏检
  → 必须切成 640x240 的小块
- 名字牌宽约 130px,块重叠必须大于它,否则骑在边界上被两侧切断
- 宠物名字牌会遮挡角色名(只剩 'ng咕咕'),邻近玩家的牌子会粘连成 '小白雪人ifeng咕咕'
  → 完全匹配优先;剩尾巴且过半长的部分匹配也收(战斗中持续被挡,总比 10s+ 后
  退化到"屏幕中心 x + 最后已知层高 y"强,中心点会因此右偏,可接受);粘连文本比全名长,
  天然不会被当成后缀收下(详见 _matches,及 2026-08-06 第二轮"被打后打怪异常"复查)
- 模板分片匹配(参考 MapleStoryAutoLevelUp 的 nametag split_width 方案):
  曾判定"模板匹配不可行——底框半透明,模板会把地图背景一起吃进去";
  参考项目用白字二值化(只留 150-255 的白字形,半透明底框与背景被阈值滤掉)解决——
  模板只含文字本身,背景怎么变都不影响匹配。模板再竖切 2 片分开匹配
  (TM_SQDIFF_NORMED,mask=片本身只比白字形像素):怪的名字牌盖住左半,
  右半片照样完美命中,定位返回整牌中心(详见 split_match / capture_template)
- 暗底验证(2026-08-10):名字牌有深色半透明底框(亮度<100 占 ~40%),
  白字叠加其上(亮度>150 占 ~35%)。纯白字模板匹配会误中云/天空(同为亮白色);
  解法是先照常模板匹配,命中后再验证命中位置周围是否有暗底——
  云/天空命中点无暗底,被拒绝;验证只查一个 ROI,开销微秒级。
  宠物遮挡时暗底框仍完整,验证不受影响;TEMPLATE_SPLITS=4 覆盖更多遮挡组合。
"""
import cv2
import numpy as np
from collections import namedtuple

from src.detect.ocr_engine import read_texts

TILE_W = 640
TILE_H = 240
TILE_OVERLAP = 200  # 必须 > 名字牌宽度(实测 ~130px)

WHITE_LOW = 150            # 白字二值化下界:只留白字形(255),其余归 0
TEMPLATE_MIN_WHITE = 10    # 模板/分片的最少白像素:全黑(黑帧/空片)没有可比的字形
TEMPLATE_SPLITS = 4        # 竖切片数:4片覆盖"端侧+大+模+型"各1字,宠物盖1-2字时其他片仍命中

# 暗底验证参数(2026-08-10 实测名字牌特征:暗底 ~40%,白字 ~35%)
DARK_BG_THRESH = 100       # 暗底阈值:亮度<100 的像素视为暗底
DARK_BG_MIN_RATIO = 0.30   # 命中位置周围暗底最小占比:名字牌 ~40%,低于此可能是云/天空
DARK_BG_VERIFY_PAD_X = 120 # 验证区域半宽(像素):名字牌宽 ~130-220,取框中心 ±120
DARK_BG_VERIFY_HALF_H = 35 # 验证区域半高(像素):名字牌高 ~40-60,取框中心 ±35

# OCR 预处理开关:名字牌是白字+黑描边+半透明底框,DB 检测器对高对比描边文字
# 的边缘响应不稳,容易漏检小字(2026-08-08 实测:不配合模板匹配几乎找不到名字)。
# 灰度 → CLAHE 增强局部对比 → 反转(白字变黑字、亮背景变暗),det 检测更稳。
# 改 False 即回滚到原始彩色图直送 OCR,不依赖任何任务配置。
OCR_PREPROCESS_ENABLED = True

Anchor = namedtuple('Anchor', 'x y width')
# 与 Anchor 同字段 + text:OCR 完整命中的文本,任务据此决定是否裁模板
# (部分匹配 'ng咕咕' 是名字牌被挡的产物,裁出来是残缺牌子,不配当模板)
AnchorHit = namedtuple('AnchorHit', 'x y width text')


def search_region(frame_w, frame_h, width_ratio, height_ratio, center_y_ratio=0.55):
    """角色名字牌的搜索区 (x0, y0, x1, y1)。

    相机跟随角色,角色恒在画面中部;限定中央区还天然排除了两个同名干扰源——
    右侧组队列表(x≈2303, y≈1032)与左下角状态栏(x≈732, y≈1421),它们写着同一个角色名。

    纵向中心默认 0.55 而不是 0.5:名字牌画在角色**脚下**,相机对准的却是身体,
    牌子因此系统性地偏在画面中心下方(实测 40 帧 y ∈ [738, 888],中心 813 > 720)。
    默认值配合 0.30 比例正好等于 spec §3.1 实测基线所用的区域(x 0.35-0.65 / y 0.40-0.70),
    基线数据(中位 118ms、干净命中 22/40)才对得上;改动此默认值等于换了区域,基线必须重测。
    """
    half_w = frame_w * width_ratio / 2
    half_h = frame_h * height_ratio / 2
    cx, cy = frame_w / 2, frame_h * center_y_ratio
    return int(cx - half_w), int(cy - half_h), int(cx + half_w), int(cy + half_h)


def tiles(region, tile_w=TILE_W, tile_h=TILE_H, overlap=TILE_OVERLAP):
    """把区域切成带重叠的小块,返回 [(x0, y0, x1, y1)]。"""
    x0, y0, x1, y1 = region
    step_x = max(1, tile_w - overlap)  # 重叠 >= 块宽时步长会变 0,这里兜底防死循环
    step_y = max(1, tile_h - overlap)
    out = []
    y = y0
    while y < y1:
        ty1 = min(y + tile_h, y1)
        x = x0
        while x < x1:
            tx1 = min(x + tile_w, x1)
            out.append((x, y, tx1, ty1))
            if tx1 >= x1:
                break
            x += step_x
        if ty1 >= y1:
            break
        y += step_y
    return out


def _enhance_for_ocr(img):
    """OCR 前置预处理:白字黑描边小字 → 高对比黑字白底。

    名字牌是白字(255)+黑描边(0)+半透明底框,直接送 DB 检测器时描边与底框
    会被一起当成文字边缘,小字(31px)容易漏检。处理链:
      1. 灰度化
      2. CLAHE 增强局部对比度(描边与文字本体对比拉满,背景亮度不均被抑制)
      3. 反转 → 白字变黑字、深色背景变浅,贴合 DB 训练分布(黑字浅底)
    尺寸不变,OCR 命中框坐标仍可直接换算回全帧坐标。
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    inverted = cv2.bitwise_not(enhanced)
    return cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)


def _matches(text, target):
    """完全匹配,或被遮挡/粘连后只剩部分文本的匹配。

    场景(实测 2026-08-10):
    - 怪/邻玩家牌压名字前半 → OCR 读出尾巴 'ng咕咕' → target.endswith(text)
    - 白色雪人宠物挡名字右侧 → OCR 读出前缀 '端侧大' 甚至只剩 '端侧' → target.startswith(text)
    - 名字牌与下方 CV 标签粘连 → OCR 读出 '端侧大模型CV' → text.startswith(target)
    三者任一满足即收,好过退化到画面中心。半长 = len(target)//2,下限 2
    (被挡剩 2 字 '端侧' 也算锚点)。太短(<半长)信息量不够,容易撞上别的
    同字玩家,仍然丢弃。完全无关的粘连(如 '小白雪人ifeng咕咕')与 target
    无公共前后缀,天然被排除。
    """
    text = text.strip()
    if text == target:
        return True
    min_len = max(2, len(target) // 2)
    return (len(text) >= min_len and (target.endswith(text) or target.startswith(text))
            or len(target) >= min_len and (text.startswith(target) or text.endswith(target)))


def _scan(frame, name, boxes, ocr_fn):
    """在给定小块里找匹配 name 的框(完全匹配优先,详见 _matches),返回全帧坐标的 AnchorHit 或 None。"""
    target = (name or '').strip()
    if not target:
        return None
    for (x0, y0, x1, y1) in boxes:
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        if OCR_PREPROCESS_ENABLED:
            crop = _enhance_for_ocr(crop)
        for hit in read_texts(crop, ocr_fn=ocr_fn):
            if _matches(hit.text, target):
                return AnchorHit(x0 + hit.cx, y0 + hit.cy, hit.width, hit.text)
    return None


def find_in_region(frame, name, region, ocr_fn=None):
    """慢通道:在搜索区内分块扫描。实测中位 118ms、最大 235ms(12 块)。"""
    return _scan(frame, name, tiles(region), ocr_fn)


def find_in_window(frame, name, center, half_w, half_h, ocr_fn=None, clamp_region=None):
    """快通道:只看上次锚点附近的小窗。窗口先裁到帧内,再裁到 clamp_region 内
    (蓝框=锚点搜索区,快通道 OCR 不许超出它);两者交集为空 → 无命中。"""
    h, w = frame.shape[:2]
    cx, cy = center
    x0, y0 = max(0, int(cx - half_w)), max(0, int(cy - half_h))
    x1, y1 = min(w, int(cx + half_w)), min(h, int(cy + half_h))
    if clamp_region is not None:
        x0, y0 = max(x0, int(clamp_region[0])), max(y0, int(clamp_region[1]))
        x1, y1 = min(x1, int(clamp_region[2])), min(y1, int(clamp_region[3]))
    if x1 <= x0 or y1 <= y0:
        return None
    return _scan(frame, name, [(x0, y0, x1, y1)], ocr_fn)


def body_center(anchor_obj, offset_px):
    """名字牌中心 → 角色身体中心。名字牌在脚下,所以身体在它上方。

    offset_px 已由 scripts/calibrate_attack_zone.py 实测标定:几何中心偏移 ≈83px,
    默认 90 落在角色轮廓内(肩/手高度),有意保留,不再是占位值(详见 spec §3.5)。
    """
    return anchor_obj.x, anchor_obj.y - offset_px


def _to_white_binary(img):
    """白字二值化:只留亮白像素(150-255),其余归 0。

    名字牌是白字+黑描边+半透明底框,直接拿原始像素当模板会把地图背景一起吃进去
    (曾据此判定模板匹配不可行);阈值到白字形后,模板只含文字本身,背景无论怎么变
    都不影响匹配(参考项目 MapleStoryAutoLevelUp 的 white_mask 模式)。
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.inRange(blur, WHITE_LOW, 255)


def has_dark_background(frame, hit, thresh=DARK_BG_THRESH,
                        min_ratio=DARK_BG_MIN_RATIO,
                        pad_x=None, half_h=DARK_BG_VERIFY_HALF_H):
    """验证模板匹配命中位置周围是否有暗底(名字牌的半透明底框)。

    名字牌是白字+暗色半透明底框(暗底占 ~40%);云/天空是纯亮色,命中点周围
    无暗底。模板匹配命中后再做此验证,把误中的云/天空拒绝掉。

    Args:
        frame: BGR 图像
        hit: AnchorHit 模板匹配命中
        thresh: 暗底亮度阈值
        min_ratio: 暗底最小占比,低于此视为无暗底(云/天空)
        pad_x: 验证区域半宽(像素)。None 时按名字牌宽度推导
               (hit.width*0.6,下限 60)——固定 240 会把周围亮背景带进来
               稀释暗底占比(实测 frame_0256: 240 宽 29.1% 被拒,
               名字牌宽 0.6 倍 94 后 30%+ 通过)。
        half_h: 验证区域半高(像素)
    Returns:
        bool 命中位置周围是否有暗底
    """
    if pad_x is None:
        pad_x = max(int(hit.width * 0.6), 60)
    h, w = frame.shape[:2]
    x0 = max(0, int(hit.x - pad_x))
    x1 = min(w, int(hit.x + pad_x))
    y0 = max(0, int(hit.y - half_h))
    y1 = min(h, int(hit.y + half_h))
    if x1 <= x0 or y1 <= y0:
        return False
    gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    return np.mean(gray < thresh) >= min_ratio


def capture_template(frame, anchor_obj, pad=12, half_h=18):
    """OCR 完整命中时,以命中框为中心裁名字牌区域 → 白字二值化模板。

    没有白字(黑帧/OCR 误报)→ 返回 None,不存垃圾。模板由任务持久化到
    screenshots/nametag_templates/,下次启动直接加载,不用等第一次完整命中。
    """
    h, w = frame.shape[:2]
    x0 = max(0, int(anchor_obj.x - anchor_obj.width / 2) - pad)
    y0 = max(0, int(anchor_obj.y) - half_h)
    x1 = min(w, int(anchor_obj.x + anchor_obj.width / 2) + pad)
    y1 = min(h, int(anchor_obj.y) + half_h)
    if x1 <= x0 or y1 <= y0:
        return None
    tmpl = _to_white_binary(frame[y0:y1, x0:x1])
    if np.count_nonzero(tmpl) < TEMPLATE_MIN_WHITE:
        return None
    return tmpl


def split_match(frame, template, center, half_w, half_h, threshold, splits=TEMPLATE_SPLITS,
                verify_dark=False, clamp_region=None):
    """模板分片匹配:白字二值化帧 vs 二值模板,竖切 splits 片各自
    cv2.matchTemplate(TM_SQDIFF_NORMED)(不用 mask 参数:masked 归一化在
    全黑窗口会产出 inf/NaN,minMaxLoc 结果直接不可用;二值图上黑对黑本来就差 0,
    黑底部分自动不参与),取分数最好(最小)的一片。
    怪的名字牌盖住一片,另一片照样命中,定位返回整牌中心。
    分数超 threshold(0=完全一致)→ 无命中;窗口内放不下模板 → 无命中。
    空白片(没有白字形)跳过;全黑窗口平方差归一化会除 0 得 inf,靠
    `not (score <= threshold)` 一并拒绝(inf/NaN 都不放行)。
    verify_dark=True 时,命中后再验证位置周围有暗底(名字牌特征),
    云/天空误匹配(无暗底)被拒绝。
    clamp_region=(x0,y0,x1,y1) 时窗口先裁到帧内再裁到它(蓝框=锚点搜索区,
    模板匹配不许越界);两窗交集为空 → 无命中。"""
    h, w = frame.shape[:2]
    cx, cy = center
    x0, y0 = max(0, int(cx - half_w)), max(0, int(cy - half_h))
    x1, y1 = min(w, int(cx + half_w)), min(h, int(cy + half_h))
    if clamp_region is not None:
        x0, y0 = max(x0, int(clamp_region[0])), max(y0, int(clamp_region[1]))
        x1, y1 = min(x1, int(clamp_region[2])), min(y1, int(clamp_region[3]))
    if x1 <= x0 or y1 <= y0:
        return None
    roi = _to_white_binary(frame[y0:y1, x0:x1])
    th, tw = template.shape[:2]
    if roi.shape[0] < th or roi.shape[1] < tw:
        return None
    best_score, best_loc, best_xs = None, None, None
    for i in range(splits):
        xs = i * tw // splits
        xe = tw if i == splits - 1 else (i + 1) * tw // splits
        piece = template[:, xs:xe]
        if np.count_nonzero(piece) < TEMPLATE_MIN_WHITE:
            continue
        res = cv2.matchTemplate(roi, piece, cv2.TM_SQDIFF_NORMED)
        _, _, (lx, ly), _ = cv2.minMaxLoc(res)
        score = float(res[ly, lx])
        if best_score is None or score < best_score:
            best_score, best_loc, best_xs = score, (lx, ly), xs
    if best_score is None or not (best_score <= threshold):
        return None
    lx, ly = best_loc
    hit = AnchorHit(x0 + lx - best_xs + tw / 2.0, y0 + ly + th / 2.0, tw, '')
    if verify_dark and not has_dark_background(frame, hit):
        return None
    return hit


def save_template(template, path):
    """模板持久化。存 0/255 二值图,load 回来直接可用。"""
    cv2.imwrite(path, template)


def load_template(path):
    """读回持久化模板;文件缺失/损坏 → None。"""
    return cv2.imread(path, cv2.IMREAD_GRAYSCALE)
