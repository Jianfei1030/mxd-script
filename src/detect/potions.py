"""快捷栏药水数量读取。格位为帧比例坐标,2560x1440 校准。"""
import re

import cv2

from src.detect.ocr_engine import prewarm, read_texts  # noqa: F401  prewarm 对外再导出

SLOT_ORIGIN = (1746 / 2560, 1171 / 1440)
SLOT_SIZE = (67 / 2560, 65 / 1440)
SLOT_KEYS = [
    ['shift', 'insert', 'home', 'pageup'],
    ['ctrl', 'delete', 'end', 'pagedown'],
]


def parse_count(text):
    if not text:
        return None
    m = re.search(r'(\d{1,4})', text)
    return int(m.group(1)) if m else None


def slot_roi(frame, slot_key):
    """返回格子下半部(数字区域)的像素 (x, y, w, h)。未知键位返回 None。"""
    h, w = frame.shape[:2]
    col = row = None
    for r, row_keys in enumerate(SLOT_KEYS):
        if slot_key in row_keys:
            row, col = r, row_keys.index(slot_key)
            break
    if row is None:
        return None  # 非快捷栏键:读不了数量,交给"喝药无效"兜底,不许 raise 崩任务
    x = SLOT_ORIGIN[0] + col * SLOT_SIZE[0]
    y = SLOT_ORIGIN[1] + row * SLOT_SIZE[1]
    return (int(x * w), int((y + SLOT_SIZE[1] * 0.55) * h),
            int(SLOT_SIZE[0] * w), int(SLOT_SIZE[1] * 0.45 * h))


def read_slot_count(frame, slot_key, ocr_fn=None):
    """读格子里的数量。返回 int 或 None(读不出/空槽/未知键)。"""
    roi = slot_roi(frame, slot_key)
    if roi is None:
        return None
    x, y, w, h = roi
    crop = frame[y:y + h, x:x + w]
    if crop.size == 0:
        return None
    # 67x29 小号描边数字,PaddleOCR det 在小图上易漏检,放大 3 倍再送
    crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    # ocr_fn 为 None 时 read_texts 内部退回共享单例,这里原样透传即可
    for hit in read_texts(crop, ocr_fn=ocr_fn):
        count = parse_count(hit.text)
        if count is not None:
            return count
    return None
