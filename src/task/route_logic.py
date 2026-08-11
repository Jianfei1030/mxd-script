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


# ---------- 录制操作层(spec §5;键位为自定义,MSALU 无撤销/放弃段参考实现) ----------

def action_for_keys(pressed):
    """物理按键规范名集合 → 命令字符串;无可涂动作 → None。
    规范名:left/right/up/down/space(跳)/f2(goal)。脚本层负责真实键位→规范名。"""
    if 'f2' in pressed:
        return GOAL_COMMAND
    if 'space' in pressed:
        if 'left' in pressed:
            return 'left none jump'
        if 'right' in pressed:
            return 'right none jump'
        if 'down' in pressed:
            return 'none down jump'
        return 'none none jump'
    if 'up' in pressed:
        return 'none up none'
    if 'down' in pressed:
        return 'none down none'
    if 'left' in pressed:
        return 'left none none'
    if 'right' in pressed:
        return 'right none none'
    return None


def blob_ready(now, last_blob, cooldown=0.7):
    """blob 落笔冷却(spec §5 防连涂)。"""
    return now - last_blob >= cooldown


class RouteOps:
    """路线层操作栈:每笔入栈,撤销=弹栈+清空+重放;clear=放弃当前段(不删已落盘文件)。"""

    def __init__(self, shape):
        h, w = shape
        self.layer = np.zeros((h, w, 4), np.uint8)  # BGRA 透明路线层
        self.ops = []

    def _paint(self, op):
        kind = op['type']
        color_bgr = COMMAND_COLORS[op['command']][::-1]
        if kind == 'line':
            cv2.line(self.layer, op['p0'], op['p1'], (*color_bgr, 255), 1)
        else:  # blob / goal 同画圆点
            cv2.circle(self.layer, op['center'], op.get('radius', 2), (*color_bgr, 255), -1)

    def _repaint(self):
        self.layer[:] = 0
        for op in self.ops:
            self._paint(op)

    def draw_line(self, p0, p1, command):
        op = {'type': 'line', 'p0': (int(p0[0]), int(p0[1])),
              'p1': (int(p1[0]), int(p1[1])), 'command': command}
        self.ops.append(op)
        self._paint(op)

    def draw_blob(self, center, command, radius=2):
        op = {'type': 'blob', 'center': (int(center[0]), int(center[1])),
              'radius': radius, 'command': command}
        self.ops.append(op)
        self._paint(op)

    def undo(self):
        """弹栈 + 整层重放;栈空 no-op。goal 落笔可撤销,但已保存的 routeN 文件不回滚。"""
        if not self.ops:
            return
        self.ops.pop()
        self._repaint()

    def clear(self):
        """F4 放弃当前段:清空路线层与栈,不动已保存文件。"""
        self.ops = []
        self._repaint()

    def save(self, path):
        minimap.imwrite_unicode(path, self.layer)  # cv2.imwrite 中文路径抛异常
