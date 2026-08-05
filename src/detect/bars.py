"""HP/MP/EXP 条读取。ROI 为帧比例坐标,2560x1440 校准(见计划 Global Constraints)。"""
import cv2

HP_BAR = (943 / 2560, 1406 / 1440, 1139 / 2560, 1432 / 1440)
MP_BAR = (1145 / 2560, 1406 / 1440, 1342 / 2560, 1432 / 1440)
EXP_BAR = (1357 / 2560, 1406 / 1440, 1571 / 2560, 1432 / 1440)

RED = {'b': (0, 90), 'g': (0, 90), 'r': (150, 255)}
BLUE = {'b': (150, 255), 'g': (80, 255), 'r': (0, 100)}
# EXP 填充色有 r 206→147 的色相渐变,r 下限必须放到 120,否则掩码在渐变尾部断裂;
# 灰槽 (177,177,177) 被 b≤110 挡住不会误计(2026-08-05 像素级实测)
YELLOW = {'b': (0, 110), 'g': (170, 255), 'r': (120, 255)}


def _roi_pixels(frame, fractions):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = fractions
    return int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)


def read_bar_percent(frame, roi_fractions, color_range):
    """按列填充率:一列中 >=50% 像素落在颜色区间内记为已填充。"""
    x1, y1, x2, y2 = _roi_pixels(frame, roi_fractions)
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return 0.0
    lower = (color_range['b'][0], color_range['g'][0], color_range['r'][0])
    upper = (color_range['b'][1], color_range['g'][1], color_range['r'][1])
    mask = cv2.inRange(roi, lower, upper)
    filled_cols = ((mask > 0).sum(axis=0) >= roi.shape[0] * 0.5).sum()
    return float(filled_cols) / mask.shape[1]


def read_hp(frame):
    return read_bar_percent(frame, HP_BAR, RED)


def read_mp(frame):
    return read_bar_percent(frame, MP_BAR, BLUE)


def read_exp(frame):
    return read_bar_percent(frame, EXP_BAR, YELLOW)
