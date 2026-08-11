"""路线数据 + 巡逻决策 + 录制操作层(纯逻辑,spec §3/§4/§5;§11.2 可离线单测)。

坐标系:底图像素坐标(见 src/detect/minimap.py 约定)。
命令字符串格式:"<左/右/none> <上/下/none> <动作/none>",与 MSALU 一致。
"""
import glob
import os

import cv2
import numpy as np

from src.detect import minimap  # imread_unicode/imwrite_unicode:中文路径 IO(预检铁证)

# 颜色命令表(spec §3):RGB → "左/右 上/下 动作"。战士裁剪版,无传送色。
COLOR_COMMANDS = {
    (255, 0, 0): 'left none none',
    (0, 0, 255): 'right none none',
    (255, 127, 0): 'left none jump',
    (0, 255, 255): 'right none jump',
    (255, 0, 255): 'none none jump',
    (127, 255, 0): 'none down jump',
    (127, 127, 127): 'none up none',
    (255, 255, 127): 'none down none',
    (0, 255, 127): 'stop stop stop',
    (255, 255, 0): 'none none goal',
}
COMMAND_COLORS = {v: k for k, v in COLOR_COMMANDS.items()}
CLIMB_COMMANDS = {'none up none', 'none down none'}
WALK_COMMANDS = {'left none none', 'right none none'}
GOAL_COMMAND = 'none none goal'
STOP_COMMAND = 'stop stop stop'


def load_routes(map_dir):
    """读 minimap/<地图名>/route*.png → (segments, unknown)。
    只认 alpha>0 且在色表中的像素;涂错色收进 unknown 供录制校验报告。"""
    segments, unknown = [], []
    for f in sorted(glob.glob(os.path.join(map_dir, 'route*.png'))):
        img = minimap.imread_unicode(f)  # cv2.imread 中文路径静默返 None
        if img is None or img.ndim != 3 or img.shape[2] != 4:
            continue
        seg = {}
        ys, xs = np.nonzero(img[:, :, 3])
        for y, x in zip(ys.tolist(), xs.tolist()):
            b, g, r = (int(v) for v in img[y, x, :3])
            cmd = COLOR_COMMANDS.get((r, g, b))
            if cmd is None:
                unknown.append((f, (x, y), (r, g, b)))
            else:
                seg[(x, y)] = cmd
        segments.append(seg)
    return segments, unknown


def nearest_command(segment, pos, search_range=8):
    """段内找距 pos 曼哈顿距离最近(≤search_range)的命令像素;无 → None。"""
    best, best_d = None, search_range
    for (x, y), cmd in segment.items():
        d = abs(x - pos[0]) + abs(y - pos[1])
        if d <= best_d:
            best, best_d = (x, y, cmd), d
    if best is None:
        return None
    return {'command': best[2], 'pixel': (best[0], best[1]), 'distance': int(best_d)}


def advance_segment(idx, n_segments, command):
    """goal → 下一段(取模循环);其他命令 → 不变。"""
    if command == GOAL_COMMAND and n_segments > 0:
        return (idx + 1) % n_segments
    return idx
