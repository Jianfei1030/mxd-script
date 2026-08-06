"""角色名字牌锚点识别。

怀旧服把角色名渲染在角色脚下(白字 + 半透明底框),用它当"角色在哪"的锚点,
比给 YOLO 加 player 类别省事,也不会把长得一样的别的玩家认成自己。

实测结论(2026-08-06,详见 spec §3,勿再重复踩):
- 2560 宽的整图/宽带送 OCR 会被检测模型按最长边缩到 ~960,31px 的字被压到 ~12px 漏检
  → 必须切成 640x240 的小块
- 名字牌宽约 130px,块重叠必须大于它,否则骑在边界上被两侧切断
- 宠物名字牌会遮挡角色名(只剩 'ng咕咕'),邻近玩家的牌子会粘连成 '小白雪人ifeng咕咕'
  → 只收"文本恰好等于角色名"的框,截断/粘连一律丢弃,靠调用方的沿用+回退兜底
- 名字牌模板匹配不可行:底框半透明,模板会把地图背景一起吃进去
"""
from collections import namedtuple

from src.detect.ocr_engine import read_texts

TILE_W = 640
TILE_H = 240
TILE_OVERLAP = 200  # 必须 > 名字牌宽度(实测 ~130px)

Anchor = namedtuple('Anchor', 'x y width')


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


def _scan(frame, name, boxes, ocr_fn):
    """在给定小块里找"文本恰好等于 name"的框,返回全帧坐标的 Anchor 或 None。"""
    target = (name or '').strip()
    if not target:
        return None
    for (x0, y0, x1, y1) in boxes:
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        for hit in read_texts(crop, ocr_fn=ocr_fn):
            if hit.text.strip() == target:
                return Anchor(x0 + hit.cx, y0 + hit.cy, hit.width)
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
