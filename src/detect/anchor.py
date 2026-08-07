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
TEMPLATE_SPLITS = 2        # 竖切片数:怪的名字牌盖左半,右半片照样命中

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


def _matches(text, target):
    """完全匹配,或被遮挡后只剩尾巴的部分匹配。

    只认后缀:遮挡源(自己的宠物牌、相邻玩家牌子)压在名字前半,OCR 只读出尾巴
    (实测 'ng咕咕')——用它当近似锚点,好过战斗中连续多帧被挡满 10s 直接退化到
    画面中心。尾巴太短(<半长)信息量不够,容易撞上别的同尾缀玩家,仍然丢弃。
    粘连文本(如 '小白雪人ifeng咕咕')比 target 长,不可能是它的后缀,天然被排除。
    """
    text = text.strip()
    if text == target:
        return True
    min_len = max(3, len(target) // 2)
    return len(text) >= min_len and target.endswith(text)


def _scan(frame, name, boxes, ocr_fn):
    """在给定小块里找匹配 name 的框(完全匹配优先,详见 _matches),返回全帧坐标的 AnchorHit 或 None。"""
    target = (name or '').strip()
    if not target:
        return None
    for (x0, y0, x1, y1) in boxes:
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        for hit in read_texts(crop, ocr_fn=ocr_fn):
            if _matches(hit.text, target):
                return AnchorHit(x0 + hit.cx, y0 + hit.cy, hit.width, hit.text)
    return None


def find_in_region(frame, name, region, ocr_fn=None):
    """慢通道:在搜索区内分块扫描。实测中位 118ms、最大 235ms(12 块)。"""
    return _scan(frame, name, tiles(region), ocr_fn)


def find_in_window(frame, name, center, half_w, half_h, ocr_fn=None):
    """快通道:只看上次锚点周围的小窗。窗口会被裁到帧内。"""
    h, w = frame.shape[:2]
    cx, cy = center
    box = (max(0, int(cx - half_w)), max(0, int(cy - half_h)),
           min(w, int(cx + half_w)), min(h, int(cy + half_h)))
    return _scan(frame, name, [box], ocr_fn)


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


def split_match(frame, template, center, half_w, half_h, threshold, splits=TEMPLATE_SPLITS):
    """模板分片匹配:白字二值化帧 vs 二值模板,竖切 splits 片各自
    cv2.matchTemplate(TM_SQDIFF_NORMED)(不用 mask 参数:masked 归一化在
    全黑窗口会产出 inf/NaN,minMaxLoc 结果直接不可用;二值图上黑对黑本来就差 0,
    黑底部分自动不参与),取分数最好(最小)的一片。
    怪的名字牌盖住一片,另一片照样命中,定位返回整牌中心。
    分数超 threshold(0=完全一致)→ 无命中;窗口内放不下模板 → 无命中。
    空白片(没有白字形)跳过;全黑窗口平方差归一化会除 0 得 inf,靠
    `not (score <= threshold)` 一并拒绝(inf/NaN 都不放行)。"""
    h, w = frame.shape[:2]
    cx, cy = center
    x0, y0 = max(0, int(cx - half_w)), max(0, int(cy - half_h))
    x1, y1 = min(w, int(cx + half_w)), min(h, int(cy + half_h))
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
    # 片命中位置回推整模板左上角:模板中心 = 片偏移 - 片起点 + 半模板宽
    return AnchorHit(x0 + lx - best_xs + tw / 2.0, y0 + ly + th / 2.0, tw, '')


def save_template(template, path):
    """模板持久化。存 0/255 二值图,load 回来直接可用。"""
    cv2.imwrite(path, template)


def load_template(path):
    """读回持久化模板;文件缺失/损坏 → None。"""
    return cv2.imread(path, cv2.IMREAD_GRAYSCALE)
