"""名字牌锚点识别。OCR 函数以参数注入,可离线单测。

只回答「角色名字牌在哪」,不知道攻击区、不知道朝向。
攻击区/朝向判定在 farm_logic,接线在任务层。
"""
import cv2

# 快通道:上次锚点周围小窗(attack-zone spec §4.2)
WINDOW_W = 480
WINDOW_H = 160

# 慢通道:中央区分块扫描(attack-zone spec §3.1 实测 12 块中位 118ms)
CENTER_X_RATIO = 0.35
CENTER_Y_RATIO = 0.40
CENTER_W_RATIO = 0.30
CENTER_H_RATIO = 0.30
BLOCK_W = 640
BLOCK_H = 240
BLOCK_OVERLAP = 200

_ocr_instance = None


def _get_ocr():
    """惰性创建 onnxocr 实例(离线直读,不走框架 executor)。"""
    global _ocr_instance
    if _ocr_instance is None:
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        _ocr_instance = ONNXPaddleOcr(use_angle_cls=False, use_det=True, use_rec=True, use_openvino=True)
    return _ocr_instance


def _ocr_texts(crop, ocr_fn):
    """对裁剪图跑 OCR,返回 [(box4点, text), ...];OCR 异常时返回 []。"""
    try:
        lines = ocr_fn(crop) or []
    except Exception:
        return []
    result = []
    for line in lines:
        try:
            text = line[1][0] if isinstance(line[1], (tuple, list)) else str(line[1])
            result.append((line[0], str(text)))
        except (TypeError, IndexError):
            continue
    return result


def _box_center(box):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _match_in_crop(crop, target, ocr_fn):
    """在裁剪图里找文本 strip 后完全等于 target 的框,返回 (cx, cy)(图内坐标)或 None。
    完全匹配判据(attack-zone spec §4.3):粘连(更长)/截断(更短)一律丢弃。"""
    for box, text in _ocr_texts(crop, ocr_fn):
        if text.strip() == target:
            return _box_center(box)
    return None


def _scan_window(frame, prev_anchor, target, ocr_fn):
    """快通道:上次锚点周围 ±WINDOW_W/2 × ±WINDOW_H/2 小窗。"""
    h, w = frame.shape[:2]
    px, py = prev_anchor
    x0 = max(0, int(px - WINDOW_W / 2))
    y0 = max(0, int(py - WINDOW_H / 2))
    x1 = min(w, x0 + WINDOW_W)
    y1 = min(h, y0 + WINDOW_H)
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    hit = _match_in_crop(crop, target, ocr_fn)
    if hit is None:
        return None
    return hit[0] + x0, hit[1] + y0


def _center_blocks(frame):
    """慢通道的中央区分块 ROI 列表 [(x, y, w, h), ...],步进 = 块尺寸 - 重叠。"""
    h, w = frame.shape[:2]
    x0 = int(CENTER_X_RATIO * w)
    y0 = int(CENTER_Y_RATIO * h)
    x1 = int((CENTER_X_RATIO + CENTER_W_RATIO) * w)
    y1 = int((CENTER_Y_RATIO + CENTER_H_RATIO) * h)
    blocks = []
    step_x = BLOCK_W - BLOCK_OVERLAP
    step_y = BLOCK_H - BLOCK_OVERLAP
    for bx in range(x0, x1, step_x):
        for by in range(y0, y1, step_y):
            x = min(bx, x1 - BLOCK_W)
            y = min(by, y1 - BLOCK_H)
            blocks.append((x, y, BLOCK_W, BLOCK_H))
    return blocks


def _scan_center_region(frame, target, ocr_fn):
    """慢通道:中央区分块扫描,返回匹配框的 (cx, cy) 或 None。"""
    h, w = frame.shape[:2]
    for x, y, bw, bh in _center_blocks(frame):
        x = max(0, min(x, w - bw))
        y = max(0, min(y, h - bh))
        crop = frame[y:y + bh, x:x + bw]
        if crop.size == 0:
            continue
        hit = _match_in_crop(crop, target, ocr_fn)
        if hit is not None:
            return hit[0] + x, hit[1] + y
    return None


def find_anchor(frame, character_name, prev_anchor=None, ocr_fn=None):
    """返回角色名字牌中心 (cx, cy) 或 None。
    快通道(小窗)优先;失败走慢通道(中央区分块)。角色名留空 → None(不 OCR)。"""
    target = (character_name or '').strip()
    if not target:
        return None
    if ocr_fn is None:
        ocr_fn = lambda img: _get_ocr().ocr(img)
    if prev_anchor is not None:
        hit = _scan_window(frame, prev_anchor, target, ocr_fn)
        if hit is not None:
            return hit
    return _scan_center_region(frame, target, ocr_fn)


def prewarm():
    """任务启用时预热 OCR 模型,避免首次调用卡触发循环。"""
    _get_ocr()
