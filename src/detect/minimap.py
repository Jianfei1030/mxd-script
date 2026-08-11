"""小地图感知(纯函数 + 纯状态类):黄点质心、坐标变换、标定、地形分。

坐标系约定(spec §2):
- 底图坐标:minimap/<地图名>/底图.png 的像素坐标(122×94)
- 面板坐标:整帧内小地图面板地图区的像素坐标(2560×1440 校准)
- map_xy = (panel_xy - offset) / scale
"""
import json
import os

import cv2
import numpy as np

YELLOW_HSV_LO = (20, 180, 180)   # 黄点 HSV 下限(标定后可调)
YELLOW_HSV_HI = (40, 255, 255)
MIN_DOT_AREA = 3                 # 黄点连通域最小面积:去噪
MAX_DOT_AREA = 60                # 最大面积:大块黄是地图装饰
CALIBRATE_MIN_SCORE = 0.5        # 标定相似度(带对比度门禁)最低分,低于=面板/缩放不对
TERRAIN_MIN_SCORE = 0.3          # 巡逻期地形分底线,连续低于=换图/异常
TERRAIN_PIX_TOL = 30             # 地形逐像素色差容忍(通道最大差):渲染抖动/抗锯齿余量
CALIBRATE_SCALES = (0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)  # 标定候选缩放档


def find_yellow_dots(panel_bgr):
    """面板地图区(BGR)→ 黄点列表 [(cx, cy, area), ...],亚像素质心;无 → []。"""
    hsv = cv2.cvtColor(panel_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, YELLOW_HSV_LO, YELLOW_HSV_HI)
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    dots = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if MIN_DOT_AREA <= area <= MAX_DOT_AREA:
            cx, cy = centroids[i]
            dots.append((float(cx), float(cy), area))
    return dots


def crop_panel(frame, meta):
    """整帧 → 面板地图区。meta['panel_roi']=(x, y, w, h)。"""
    x, y, w, h = meta['panel_roi']
    return frame[y:y + h, x:x + w]


def panel_to_map(point, meta):
    """面板坐标 → 底图坐标(浮点)。"""
    return ((point[0] - meta['offset_x']) / meta['scale'],
            (point[1] - meta['offset_y']) / meta['scale'])


def map_to_panel(point, meta):
    """底图坐标 → 面板坐标(浮点)。"""
    return (point[0] * meta['scale'] + meta['offset_x'],
            point[1] * meta['scale'] + meta['offset_y'])


def _masked_score(panel_bgr, base_rgba):
    """底图(alpha 为 mask)对面板的匹配相似度 → (score 0~1, loc)。
    TM_SQDIFF_NORMED(0=完全一致)取最佳位置,再乘对比度门禁:
    稀疏 mask 下 CCORR 在纯色/近纯色背景上归一化相关分虚高(评审铁证:
    垃圾面板也能拿 0.74),门禁要求匹配区像素 std ≥ 模板 std 的一半,
    uniform 背景 std≈0 → 相似度压到 ~0,假标定进不来。"""
    if base_rgba.shape[0] > panel_bgr.shape[0] or base_rgba.shape[1] > panel_bgr.shape[1]:
        return 0.0, None
    template = base_rgba[:, :, :3]
    mask = base_rgba[:, :, 3] > 0
    res = cv2.matchTemplate(panel_bgr, template, cv2.TM_SQDIFF_NORMED,
                            mask=base_rgba[:, :, 3])
    min_val, _max, min_loc, _mx = cv2.minMaxLoc(res)
    x, y = min_loc
    th, tw = template.shape[:2]
    region = panel_bgr[y:y + th, x:x + tw]
    t_std = float(template[mask].std())
    r_std = float(region[mask].std())
    contrast = 1.0 if t_std < 1e-6 else min(1.0, r_std / (0.5 * t_std + 1e-6))
    return float(max(0.0, 1.0 - min_val)) * contrast, min_loc


def calibrate(panel_bgr, base_rgba):
    """首跑标定:在候选缩放档里找底图对面板的最佳 masked 匹配。
    成功 → meta dict(含 panel_roi=None,由调用方补);分数不足 → None。"""
    best = None  # (score, scale, loc, template_wh)
    for scale in CALIBRATE_SCALES:
        h, w = base_rgba.shape[:2]
        resized = cv2.resize(base_rgba, (max(1, int(w * scale)), max(1, int(h * scale))),
                             interpolation=cv2.INTER_NEAREST)
        score, loc = _masked_score(panel_bgr, resized)
        if loc is not None and (best is None or score > best[0]):
            best = (score, scale, loc)
    if best is None or best[0] < CALIBRATE_MIN_SCORE:
        return None
    score, scale, loc = best
    return {'scale': float(scale), 'offset_x': float(loc[0]), 'offset_y': float(loc[1]),
            'match_score': score, 'search_range': 8}


def terrain_match_score(panel_bgr, base_rgba, meta):
    """换图判别(评审 2 修订):底图地形像素里"颜色对得上"的比例(0~1)。
    逐像素取通道最大差,≤ TERRAIN_PIX_TOL 记为对得上,返回占比;
    纯色背景/另一张图 → 占比≈0。旧实现用 1-平均差/765(理论最大),
    自然色差撑不满量程,错误地形也稳定 0.6~0.8,阈值形同虚设——
    归一化必须落在差异的真实分布范围内,不能除以理论上限。"""
    h, w = base_rgba.shape[:2]
    tw, th = int(w * meta['scale']), int(h * meta['scale'])
    ox, oy = int(meta['offset_x']), int(meta['offset_y'])
    if oy + th > panel_bgr.shape[0] or ox + tw > panel_bgr.shape[1]:
        return 0.0
    region = panel_bgr[oy:oy + th, ox:ox + tw]
    resized = cv2.resize(base_rgba, (tw, th), interpolation=cv2.INTER_NEAREST)
    mask = resized[:, :, 3] > 0
    if not mask.any():
        return 0.0
    diff = np.abs(region.astype(np.int16) - resized[:, :, :3].astype(np.int16)).max(axis=2)
    return float(((diff <= TERRAIN_PIX_TOL) & mask).sum() / mask.sum())


def load_base_map(map_dir):
    """读 minimap/<地图名>/底图.png(BGRA);不存在 → None。
    必须走 imread_unicode:cv2.imread 在 Windows 中文路径下静默返 None(预检铁证)。"""
    path = os.path.join(map_dir, '底图.png')
    if not os.path.exists(path):
        return None
    return imread_unicode(path)


def imread_unicode(path, flags=cv2.IMREAD_UNCHANGED):
    """中文路径安全的 imread(模式出自 ok/device/capture_methods/image.py:30)。"""
    if not os.path.exists(path):
        return None
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), flags)


def imwrite_unicode(path, img):
    """中文路径安全的 imwrite:imencode 到内存,再用 Python open 写盘
    (open() 中文路径已实测正常;cv2.imwrite 直接抛异常)。"""
    ext = os.path.splitext(path)[1] or '.png'
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise ValueError(f'imencode 失败: {path}')
    with open(path, 'wb') as f:
        f.write(buf.tobytes())


def load_map_meta(map_dir):
    """读 map_meta.json;不存在 → None。panel_roi 读成 tuple。"""
    path = os.path.join(map_dir, 'map_meta.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        meta = json.load(f)
    if 'panel_roi' in meta:
        meta['panel_roi'] = tuple(meta['panel_roi'])
    return meta


def save_map_meta(map_dir, meta):
    """写 map_meta.json(UTF-8,中文键名安全)。"""
    path = os.path.join(map_dir, 'map_meta.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


class DotTracker:
    """黄点跟踪(spec §2.3):最近邻 + 跳变守卫 + 指令-位移一致性。纯状态类。
    跳变守卫随拍间隔自适应(评审 3):上限 = base + per_sec × dt。
    固定上限是拍脑袋——它隐式假设了调用频率;巡逻拍节奏 ~10Hz(远小于 1s),
    base=4 格盖击退瞬移,per_sec=12 格/秒盖行走(M0 用实走速度标定终值)。"""

    def __init__(self, jump_guard_base=4.0, jump_guard_per_sec=12.0,
                 cmd_mismatch_limit=3.0, cmd_min_move=1.0):
        self.jump_guard_base = jump_guard_base        # 瞬时位移余量(底图格):击退/首拍
        self.jump_guard_per_sec = jump_guard_per_sec  # 行走速度上限(底图格/秒)
        self.cmd_mismatch_limit = cmd_mismatch_limit  # 持续按键无位移判异常的秒数
        self.cmd_min_move = cmd_min_move              # 该窗口内应有的最小位移(底图格)
        self.pos = None                         # (mx, my) 底图坐标
        self._last_update_t = None              # 上次 update 时刻(dt 自适应守卫用)
        self._cmd_anchor = None                 # (pos, t) 指令一致性窗口起算点

    def acquire(self, dots_before, dots_after, meta, min_panel_move=2.0):
        """移动捕获:对比走动前后两帧,位移最大的点=自己。返回底图坐标或 None。"""
        best, best_d = None, min_panel_move
        for d in dots_after:
            if not dots_before:
                break
            dmin = min(abs(d[0] - b[0]) + abs(d[1] - b[1]) for b in dots_before)
            if dmin > best_d:
                best, best_d = d, dmin
        if best is None:
            return None
        self.pos = panel_to_map((best[0], best[1]), meta)
        return self.pos

    def update(self, dots, meta, now, cmd_dir=None):
        """每帧更新。返回 (pos|None, status);status ∈ ok/lost/suspect/mismatch。"""
        dt = 0.0 if self._last_update_t is None else max(0.0, now - self._last_update_t)
        self._last_update_t = now
        jump_limit = self.jump_guard_base + self.jump_guard_per_sec * dt
        status = 'ok'
        if self.pos is not None:
            if not dots:
                status, pos = 'lost', None
            else:
                cand = min(dots, key=lambda d: abs(d[0] - self.pos[0] * meta['scale'] - meta['offset_x'])
                                             + abs(d[1] - self.pos[1] * meta['scale'] - meta['offset_y']))
                cand_map = panel_to_map((cand[0], cand[1]), meta)
                jump = abs(cand_map[0] - self.pos[0]) + abs(cand_map[1] - self.pos[1])
                if jump > jump_limit:
                    status, pos = 'suspect', self.pos   # 拒采,保持旧位置
                else:
                    self.pos = cand_map
                    pos = cand_map
        else:
            pos = None
            status = 'lost'
        # 指令-位移一致性:持续按键期间位移方向/量级不符 → mismatch(内部计时窗口)
        if cmd_dir in ('left', 'right') and status == 'ok' and self.pos is not None:
            if self._cmd_anchor is None:
                self._cmd_anchor = (self.pos, now)
            elif now - self._cmd_anchor[1] >= self.cmd_mismatch_limit:
                dx = self.pos[0] - self._cmd_anchor[0][0]
                moved = dx < -self.cmd_min_move if cmd_dir == 'left' else dx > self.cmd_min_move
                if not moved:
                    status = 'mismatch'
                self._cmd_anchor = (self.pos, now)
        else:
            self._cmd_anchor = None
        return pos, status
