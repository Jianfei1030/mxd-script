# 小地图路线巡逻 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 借鉴 MapleStoryAutoLevelUp 的颜色路线图机制,为 ok-mxd 实现多平台地图自动巡逻打怪:小地图黄点管走、屏幕锚点管上下,首发地图东部岩山5。

**Architecture:** 感知层 `src/detect/minimap.py`(黄点质心/坐标变换/标定/跟踪守卫) + 决策层 `src/task/route_logic.py`(路线数据/状态机/录制操作层,全部纯逻辑可单测) + 集成层 `MapleFarmTask`(移动模式=路线巡逻时空闲拍驱动,战斗/守护现有逻辑零改动) + 工具层 `scripts/route_recorder.py`(走一遍录路线)。

**Tech Stack:** Python 3.12 / OpenCV(numpy) / pynput(已在 requirements,录制器键盘监听) / unittest / WGC 抓帧(scripts/capture_frame.py build_capture)。

**Spec:** `docs/superpowers/specs/2026-08-11-minimap-route-patrol-design.md`(五关验收判据在 §8,决策记录在 §0)

## Global Constraints

- **纯逻辑铁律(AGENTS.md §11.2)**:决策/感知逻辑只放 `src/task/route_logic.py` 与 `src/detect/minimap.py`,全纯函数/纯类;每个新增函数必须同步 unittest,离线可跑
- **禁止绝对路径(§11.1)**:代码里不得出现 `H:/` 等;项目根用 `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 推导
- **测试命令**:`$env:PYTHONUTF8=1; python -m unittest tests.test_<name> -v`;提交前全量单测 + 编译检查(§11.6)
- **存档帧缺失显式 skip**(§11.4):`@unittest.skipUnless(...)`
- **配置键全中文**,新增键同步进 `DEFAULT_CONFIG` + `CONFIG_GROUPS` + `config_description`(test_config_groups 强制每个键恰好分组一次)
- **commit 风格**:`feat:`/`fix:`/`docs:`/`test:` 前缀,结尾 `Co-Authored-By: Claude <noreply@anthropic.com>`
- **实机关卡(M0/M1/M2/M3/M4 验收步)**前必须:单测全绿 + 编译检查过;GUI 停掉(WGC 冲突);游戏窗口 2560×1440
- **小地图约定**:面板固定左上角、约定缩放档、保持展开;校验失败报错停任务,不猜
- 资产目录 `minimap/<地图名>/` 入库(tracked);存档帧放 `minimap/<地图名>/archive/`

---

## 文件地图

| 文件 | 责任 | 新建/修改 |
|---|---|---|
| `src/detect/minimap.py` | 感知:黄点检测/质心/坐标变换/标定/地形分/DotTracker 跟踪守卫 | 新建(Task 1-2) |
| `src/task/route_logic.py` | 路线数据(色表/加载/最近色/分段) + PatrolMachine 状态机 + 录制操作层(action_for_keys/RouteOps) | 新建(Task 3-4-8-11-13) |
| `src/task/MapleFarmTask.py` | 配置键/分组 + 巡逻拍接入 + overlay 巡逻绘制 | 修改(Task 7-9-10-12-14) |
| `config.py` | 游戏按键加上移键/下移键/跳跃键 | 修改(Task 7) |
| `scripts/route_recorder.py` | 录制器(WGC+pynput+着色+分段+存档帧+抖动统计) | 新建(Task 5) |
| `tests/test_minimap.py` | 感知单测(全合成) | 新建(Task 1-2) |
| `tests/test_route_logic.py` | 路线/状态机/录制层单测(全合成) | 新建(Task 3-4-8-11-13) |
| `tests/test_minimap_offline.py` | 存档帧回放(skipUnless) | 新建(Task 6) |
| `tests/test_config_groups.py` | 组顺序断言加「巡逻」组 | 修改(Task 7) |
| `minimap/东部岩山5.png` → `minimap/东部岩山5/底图.png` | 资产目录化 | git mv(Task 1) |

---

## M0 感知地基 + 录制器(验收关卡 1)

### Task 1: minimap.py 感知纯函数 + 资产目录化

**Files:**
- Create: `src/detect/minimap.py`
- Test: `tests/test_minimap.py`
- Asset: `git mv minimap/东部岩山5.png minimap/东部岩山5/底图.png`

**Interfaces:**
- Produces(后续 Task 全部依赖):
  - `imread_unicode(path, flags=cv2.IMREAD_UNCHANGED) -> img | None` / `imwrite_unicode(path, img) -> None`(**中文路径 IO 助手**:cv2.imread/imwrite 在 Windows 非 ASCII 路径下失效——读侧 `cv2.imdecode(np.fromfile(...))`(模式出自 `ok/device/capture_methods/image.py:30`),写侧 `cv2.imencode(...).tobytes()` + Python `open(path,'wb')`;全特性图像 IO 统一走这两个助手)
  - `find_yellow_dots(panel_bgr) -> list[tuple[float, float, int]]` # (cx, cy, area),亚像素质心
  - `crop_panel(frame, meta) -> img` / `panel_to_map(point, meta) -> (float, float)` / `map_to_panel(point, meta) -> (float, float)`
  - `calibrate(panel_bgr, base_rgba) -> dict | None` / `terrain_match_score(panel_bgr, base_rgba, meta) -> float`
  - `load_map_meta(map_dir) -> dict | None` / `save_map_meta(map_dir, meta) -> None` / `load_base_map(map_dir) -> BGRA ndarray`
  - meta dict 键:`panel_roi=(x,y,w,h)`(帧像素,2560×1440 校准) / `scale`(面板像素/底图像素) / `offset_x` / `offset_y` / `search_range`(默认 8) / `match_score`

- [ ] **Step 1: 资产目录化**

```bash
git mv minimap/东部岩山5.png minimap/东部岩山5/底图.png
git commit -m "chore: 小地图资产目录化——minimap/<地图名>/底图.png"
```

- [ ] **Step 2: 写失败测试 `tests/test_minimap.py`**

```python
import os
import unittest

import cv2
import numpy as np

from src.detect import minimap


def make_base(h=94, w=122):
    """合成底图(BGRA):透明背景 + 两块棕色地形 + 一条灰绳。"""
    img = np.zeros((h, w, 4), np.uint8)
    img[80:90, 5:60] = (30, 80, 150, 255)   # BGR 棕 + 不透明
    img[40:46, 40:110] = (30, 80, 150, 255)
    img[46:80, 70:73] = (127, 127, 127, 255)
    return img


def make_panel(base, scale=2.0, offset=(7, 11), bg=(40, 30, 20), pad=60):
    """把底图按 scale 放大、贴到深色面板 offset 处,模拟游戏内小地图。"""
    h, w = base.shape[:2]
    big = cv2.resize(base, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_NEAREST)
    ph, pw = int(h * scale) + pad, int(w * scale) + pad
    panel = np.full((ph, pw, 3), bg, np.uint8)
    ox, oy = offset
    for y in range(big.shape[0]):
        for x in range(big.shape[1]):
            if big[y, x, 3] > 0:
                panel[oy + y, ox + x] = big[y, x, :3]
    return panel


class TestYellowDots(unittest.TestCase):

    def test_finds_two_dots_with_subpixel_centroid(self):
        panel = np.zeros((100, 100, 3), np.uint8)
        cv2.circle(panel, (20, 30), 2, (0, 255, 255), -1)   # BGR 黄
        cv2.circle(panel, (70, 60), 3, (0, 255, 255), -1)
        dots = minimap.find_yellow_dots(panel)
        self.assertEqual(len(dots), 2)
        cx, cy, area = min(dots)  # 最左那颗
        self.assertAlmostEqual(cx, 20, delta=1.0)
        self.assertAlmostEqual(cy, 30, delta=1.0)
        self.assertGreaterEqual(area, minimap.MIN_DOT_AREA)

    def test_rejects_oversize_yellow_blob_and_noise(self):
        panel = np.zeros((100, 100, 3), np.uint8)
        cv2.rectangle(panel, (10, 10), (50, 50), (0, 255, 255), -1)  # 大块黄=装饰
        panel[80, 80] = (0, 255, 255)                                # 单像素噪声
        self.assertEqual(minimap.find_yellow_dots(panel), [])


class TestTransform(unittest.TestCase):

    def test_roundtrip(self):
        meta = {'scale': 2.0, 'offset_x': 7.0, 'offset_y': 11.0}
        p = (50.0, 60.0)
        self.assertEqual(minimap.map_to_panel(minimap.panel_to_map(p, meta), meta), p)

    def test_panel_to_map_values(self):
        meta = {'scale': 2.0, 'offset_x': 7.0, 'offset_y': 11.0}
        self.assertEqual(minimap.panel_to_map((27.0, 31.0), meta), (10.0, 10.0))


class TestCalibrate(unittest.TestCase):

    def test_recovers_scale_and_offset(self):
        base = make_base()
        panel = make_panel(base, scale=2.0, offset=(7, 11))
        meta = minimap.calibrate(panel, base)
        self.assertIsNotNone(meta)
        self.assertAlmostEqual(meta['scale'], 2.0, delta=0.1)
        self.assertAlmostEqual(meta['offset_x'], 7.0, delta=2.0)
        self.assertAlmostEqual(meta['offset_y'], 11.0, delta=2.0)
        self.assertGreater(meta['match_score'], minimap.CALIBRATE_MIN_SCORE)

    def test_returns_none_on_garbage_panel(self):
        base = make_base()
        panel = np.full((200, 260, 3), (40, 30, 20), np.uint8)  # 纯背景
        self.assertIsNone(minimap.calibrate(panel, base))


class TestTerrainScore(unittest.TestCase):

    def test_same_terrain_scores_high_scrambled_low(self):
        base = make_base()
        panel = make_panel(base, scale=2.0, offset=(7, 11))
        meta = minimap.calibrate(panel, base)
        self.assertGreater(minimap.terrain_match_score(panel, base, meta), 0.6)
        blank = np.full_like(panel, (40, 30, 20))
        self.assertLess(minimap.terrain_match_score(blank, base, meta), minimap.TERRAIN_MIN_SCORE)


class TestMetaIO(unittest.TestCase):

    def test_save_and_load(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            meta = {'panel_roi': (10, 100, 270, 190), 'scale': 2.0,
                    'offset_x': 7.0, 'offset_y': 11.0, 'search_range': 8, 'match_score': 0.8}
            minimap.save_map_meta(d, meta)
            loaded = minimap.load_map_meta(d)
            self.assertEqual(loaded['scale'], 2.0)
            self.assertEqual(tuple(loaded['panel_roi']), (10, 100, 270, 190))
            self.assertEqual(loaded['search_range'], 8)

    def test_load_missing_returns_none(self):
        self.assertIsNone(minimap.load_map_meta('不存在的目录'))


class TestUnicodeIO(unittest.TestCase):
    """中文路径回归(预检铁证:cv2.imread/imwrite 在 Windows 非 ASCII 路径下失效,
    imread 静默返 None、imwrite 抛异常;沙箱合成测试全 ASCII 没覆盖到)。"""

    def test_write_then_read_base_map_in_chinese_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, '东部岩山5')
            os.makedirs(sub)
            img = make_base()
            minimap.imwrite_unicode(os.path.join(sub, '底图.png'), img)
            loaded = minimap.load_base_map(sub)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.shape, img.shape)

    def test_meta_roundtrip_in_chinese_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, '中文目录')
            os.makedirs(sub)
            meta = {'panel_roi': (10, 100, 270, 190), 'scale': 2.0,
                    'offset_x': 7.0, 'offset_y': 11.0, 'search_range': 8}
            minimap.save_map_meta(sub, meta)
            self.assertEqual(minimap.load_map_meta(sub)['scale'], 2.0)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 3: 跑测试确认失败**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_minimap -v`
Expected: FAIL `ModuleNotFoundError: No module named 'src.detect.minimap'`

- [ ] **Step 4: 实现 `src/detect/minimap.py`**

```python
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
```

- [ ] **Step 5: 跑测试确认通过**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_minimap -v`
Expected: PASS(11 个用例)

- [ ] **Step 6: Commit**

```bash
git add src/detect/minimap.py tests/test_minimap.py
git commit -m "feat: 小地图感知纯函数——黄点质心/坐标变换/标定/地形分(spec §2)"
```

---

### Task 2: DotTracker 黄点跟踪 + 连续性守卫

**Files:**
- Modify: `src/detect/minimap.py`(追加类)
- Test: `tests/test_minimap.py`(追加 TestDotTracker)

**Interfaces:**
- Consumes: Task 1 的 `panel_to_map` / meta
- Produces:
  - `DotTracker(jump_guard_base=4.0, jump_guard_per_sec=12.0, cmd_mismatch_limit=3.0, cmd_min_move=1.0)`
  - `.pos` → `(mx, my) | None`(底图坐标)
  - `acquire(dots_before, dots_after, meta, min_panel_move=2.0) -> (mx, my) | None` — 移动捕获:位移最大的点=自己
  - `update(dots, meta, now, cmd_dir=None) -> ((mx, my) | None, status)`;status ∈ `'ok' | 'lost' | 'suspect' | 'mismatch'`;cmd_dir ∈ `'left' | 'right' | None`
  - 语义(spec §2.3):`'suspect'`=跳变守卫拒采(保持旧 pos);`'mismatch'`=持续按键 cmd_mismatch_limit 秒位移方向不符/为零(内部计时);`'lost'`=本拍无黄点

- [ ] **Step 1: 追加失败测试**

```python
class TestDotTracker(unittest.TestCase):

    def setUp(self):
        self.meta = {'scale': 1.0, 'offset_x': 0.0, 'offset_y': 0.0}

    def test_acquire_picks_the_moving_dot(self):
        before = [(10.0, 10.0, 8), (50.0, 50.0, 8)]   # 左=NPC 静止
        after = [(10.0, 10.0, 8), (58.0, 50.0, 8)]    # 右=自己动了 8px
        t = minimap.DotTracker()
        pos = t.acquire(before, after, self.meta)
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos[0], 58.0, delta=0.5)

    def test_acquire_returns_none_when_nothing_moved(self):
        dots = [(10.0, 10.0, 8), (50.0, 50.0, 8)]
        t = minimap.DotTracker()
        self.assertIsNone(t.acquire(dots, dots, self.meta))

    def test_update_nearest_neighbor(self):
        t = minimap.DotTracker()
        t.pos = (50.0, 50.0)
        pos, status = t.update([(10.0, 10.0, 8), (52.0, 51.0, 8)], self.meta, 100.0)
        self.assertEqual(status, 'ok')
        self.assertAlmostEqual(pos[0], 52.0, delta=0.5)

    def test_jump_guard_rejects_far_jump_and_keeps_pos(self):
        t = minimap.DotTracker()  # dt=0 → 上限 = base 4 格
        t.pos = (50.0, 50.0)
        pos, status = t.update([(90.0, 50.0, 8)], self.meta, 100.0)  # 跳 40px=NPC 认错
        self.assertEqual(status, 'suspect')
        self.assertEqual(t.pos, (50.0, 50.0))  # 不采信

    def test_jump_guard_scales_with_dt(self):
        # 评审 3:固定 8 格在慢拍节奏下会误杀正常行走——上限必须随拍间隔自适应
        t = minimap.DotTracker()  # base 4 + 12 格/秒
        t.pos = (50.0, 50.0)
        _, s1 = t.update([(60.0, 50.0, 8)], self.meta, 100.0)  # dt=0 → 上限 4,10px 拒采
        self.assertEqual(s1, 'suspect')
        _, s2 = t.update([(60.0, 50.0, 8)], self.meta, 101.0)  # dt=1s → 上限 16,10px 放行
        self.assertEqual(s2, 'ok')

    def test_lost_when_no_dots(self):
        t = minimap.DotTracker()
        t.pos = (50.0, 50.0)
        pos, status = t.update([], self.meta, 100.0)
        self.assertEqual(status, 'lost')
        self.assertIsNone(pos)

    def test_mismatch_when_cmd_held_but_no_movement(self):
        t = minimap.DotTracker(cmd_mismatch_limit=3.0)
        t.pos = (50.0, 50.0)
        _, s1 = t.update([(50.0, 50.0, 8)], self.meta, 100.0, cmd_dir='right')
        _, s2 = t.update([(50.3, 50.0, 8)], self.meta, 103.5, cmd_dir='right')
        self.assertEqual(s1, 'ok')
        self.assertEqual(s2, 'mismatch')  # 按右 3.5s 只动了 0.3px

    def test_no_mismatch_when_moving_with_cmd(self):
        t = minimap.DotTracker(cmd_mismatch_limit=3.0)
        t.pos = (50.0, 50.0)
        t.update([(50.0, 50.0, 8)], self.meta, 100.0, cmd_dir='right')
        _, status = t.update([(62.0, 50.0, 8)], self.meta, 103.5, cmd_dir='right')
        self.assertEqual(status, 'ok')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_minimap.TestDotTracker -v`
Expected: FAIL `AttributeError: ... 'minimap' has no attribute 'DotTracker'`

- [ ] **Step 3: minimap.py 追加 DotTracker**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_minimap -v`
Expected: PASS(19 用例)

- [ ] **Step 5: Commit**

```bash
git add src/detect/minimap.py tests/test_minimap.py
git commit -m "feat: DotTracker 黄点跟踪——移动捕获/最近邻/跳变守卫/指令一致性(spec §2.3)"
```

---

### Task 3: route_logic.py 路线数据层(色表/加载/最近色/分段)

**Files:**
- Create: `src/task/route_logic.py`
- Test: `tests/test_route_logic.py`

**Interfaces:**
- Produces:
  - `COLOR_COMMANDS: dict[tuple[int,int,int], str]`(RGB → `"左/右 上/下 动作"`,spec §3 十色)
  - `COMMAND_COLORS: dict[str, tuple[int,int,int]]`(反向映射,录制器用)
  - `CLIMB_COMMANDS = {'none up none', 'none down none'}` / `GOAL_COMMAND = 'none none goal'` / `WALK_COMMANDS = {'left none none', 'right none none'}`
  - `load_routes(map_dir) -> (segments, unknown)`;segments=`list[dict[(x,y), command]]`(按 route1→routeN 文件名序);unknown=`list[(file, (x,y), rgb)]` 涂错色报告
  - `nearest_command(segment, pos, search_range=8) -> {'command', 'pixel', 'distance'} | None`
  - `advance_segment(idx, n_segments, command) -> int`(goal→(idx+1)%n,其他→idx)

- [ ] **Step 1: 写失败测试**

```python
import os
import tempfile
import unittest

import cv2
import numpy as np

from src.task import route_logic as rl


class TestColorTable(unittest.TestCase):

    def test_ten_colors_and_reverse_mapping(self):
        self.assertEqual(len(rl.COLOR_COMMANDS), 10)
        self.assertEqual(rl.COLOR_COMMANDS[(255, 0, 0)], 'left none none')
        self.assertEqual(rl.COLOR_COMMANDS[(255, 255, 0)], 'none none goal')
        self.assertEqual(rl.COMMAND_COLORS['none up none'], (127, 127, 127))


class TestLoadRoutes(unittest.TestCase):

    def _write_route(self, path, pixels):
        img = np.zeros((94, 122, 4), np.uint8)
        for (x, y, rgb) in pixels:
            img[y, x] = (rgb[2], rgb[1], rgb[0], 255)
        cv2.imwrite(path, img)

    def test_loads_segments_in_order_and_reports_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            self._write_route(os.path.join(d, 'route1.png'),
                              [(5, 5, (255, 0, 0)), (6, 5, (255, 0, 0))])
            self._write_route(os.path.join(d, 'route2.png'),
                              [(9, 9, (255, 255, 0)), (3, 3, (1, 2, 3))])  # 1,2,3=涂错
            segments, unknown = rl.load_routes(d)
            self.assertEqual(len(segments), 2)
            self.assertEqual(segments[0][(5, 5)], 'left none none')
            self.assertEqual(segments[1][(9, 9)], 'none none goal')
            self.assertEqual(len(unknown), 1)
            self.assertEqual(unknown[0][2], (1, 2, 3))

    def test_missing_dir_returns_empty(self):
        self.assertEqual(rl.load_routes('不存在的目录'), ([], []))


class TestNearestCommand(unittest.TestCase):

    def setUp(self):
        self.seg = {(10, 10): 'left none none', (20, 20): 'none up none', (90, 90): 'none none goal'}

    def test_picks_manhattan_nearest(self):
        hit = rl.nearest_command(self.seg, (12, 11), search_range=8)
        self.assertEqual(hit['command'], 'left none none')
        self.assertEqual(hit['pixel'], (10, 10))
        self.assertEqual(hit['distance'], 3)

    def test_out_of_range_returns_none(self):
        self.assertIsNone(rl.nearest_command(self.seg, (50, 50), search_range=8))

    def test_boundary_is_inclusive(self):
        hit = rl.nearest_command(self.seg, (18, 20), search_range=8)
        self.assertEqual(hit['command'], 'none up none')


class TestAdvanceSegment(unittest.TestCase):

    def test_goal_cycles(self):
        self.assertEqual(rl.advance_segment(0, 2, 'none none goal'), 1)
        self.assertEqual(rl.advance_segment(1, 2, 'none none goal'), 0)

    def test_non_goal_keeps(self):
        self.assertEqual(rl.advance_segment(1, 2, 'left none none'), 1)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_route_logic -v`
Expected: FAIL `ModuleNotFoundError: No module named 'src.task.route_logic'`

- [ ] **Step 3: 实现 `src/task/route_logic.py`**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_route_logic -v`
Expected: PASS(8 用例)

- [ ] **Step 5: Commit**

```bash
git add src/task/route_logic.py tests/test_route_logic.py
git commit -m "feat: 路线数据层——十色命令表/透明层路线加载/最近色搜索/goal 轮转(spec §3)"
```

---

### Task 4: 录制操作层(按键→命令/操作栈/冷却)

**Files:**
- Modify: `src/task/route_logic.py`(追加)
- Test: `tests/test_route_logic.py`(追加 TestRecorderOps)

**Interfaces:**
- Produces:
  - `action_for_keys(pressed: set[str]) -> str | None`;pressed 用规范名 `{'left','right','up','down','space','f2'}`(脚本层负责把真实键位映射到规范名);返回命令字符串或 None
  - `blob_ready(now, last_blob, cooldown=0.7) -> bool`
  - `RouteOps(shape)` 操作栈(spec §5):`.layer`(BGRA) / `draw_line(p0, p1, command)` / `draw_blob(center, command, radius=2)` / `undo()` / `clear()` / `save(path)`;undo=弹栈+整层重放,栈空 no-op;clear 不删已落盘文件

- [ ] **Step 1: 追加失败测试**

```python
class TestActionForKeys(unittest.TestCase):

    def test_walk_and_jump_and_climb_and_goal(self):
        self.assertEqual(rl.action_for_keys({'left'}), 'left none none')
        self.assertEqual(rl.action_for_keys({'right'}), 'right none none')
        self.assertEqual(rl.action_for_keys({'space'}), 'none none jump')
        self.assertEqual(rl.action_for_keys({'space', 'left'}), 'left none jump')
        self.assertEqual(rl.action_for_keys({'space', 'down'}), 'none down jump')
        self.assertEqual(rl.action_for_keys({'up'}), 'none up none')
        self.assertEqual(rl.action_for_keys({'down'}), 'none down none')
        self.assertEqual(rl.action_for_keys({'f2'}), 'none none goal')
        self.assertIsNone(rl.action_for_keys(set()))


class TestBlobCooldown(unittest.TestCase):

    def test_ready_after_cooldown(self):
        self.assertTrue(rl.blob_ready(10.0, 9.2, 0.7))
        self.assertFalse(rl.blob_ready(10.0, 9.5, 0.7))


class TestRouteOps(unittest.TestCase):

    def test_draw_line_blob_undo_replays_stack(self):
        ops = rl.RouteOps((94, 122))
        ops.draw_line((5, 5), (15, 5), 'left none none')
        ops.draw_blob((20, 20), 'none none goal')
        self.assertGreater(len(ops.ops), 0)
        alpha_before = int(ops.layer[:, :, 3].sum())
        self.assertGreater(alpha_before, 0)
        ops.undo()  # 撤销 blob → 只剩 line
        self.assertEqual(len(ops.ops), 1)
        self.assertLess(int(ops.layer[:, :, 3].sum()), alpha_before)
        ops.undo()
        ops.undo()  # 栈空 no-op 不炸
        self.assertEqual(int(ops.layer[:, :, 3].sum()), 0)

    def test_clear_keeps_saved_files_untouched(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ops = rl.RouteOps((94, 122))
            ops.draw_blob((20, 20), 'none none goal')
            path = os.path.join(d, 'route1.png')
            ops.save(path)
            ops.clear()
            self.assertEqual(int(ops.layer[:, :, 3].sum()), 0)
            self.assertTrue(os.path.exists(path))  # F4 不删已落盘文件(spec §5)

    def test_save_writes_bgra_png(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ops = rl.RouteOps((94, 122))
            ops.draw_line((5, 5), (15, 5), 'left none none')
            path = os.path.join(d, 'route1.png')
            ops.save(path)
            img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            self.assertEqual(img.shape, (94, 122, 4))
            self.assertEqual(tuple(int(v) for v in img[5, 5][:3]), (0, 0, 255))  # BGR 红

    def test_save_and_load_routes_in_chinese_dir(self):
        """中文路径回归:RouteOps.save(写) + load_routes(读)全链路。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, '东部岩山5')
            os.makedirs(sub)
            ops = rl.RouteOps((94, 122))
            ops.draw_blob((20, 20), 'none none goal')
            ops.save(os.path.join(sub, 'route1.png'))
            segments, unknown = rl.load_routes(sub)
            self.assertEqual(len(segments), 1)
            self.assertEqual(segments[0][(20, 20)], 'none none goal')
            self.assertEqual(unknown, [])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_route_logic.TestActionForKeys tests.test_route_logic.TestBlobCooldown tests.test_route_logic.TestRouteOps -v`
Expected: FAIL `AttributeError: ... 'route_logic' has no attribute 'action_for_keys'`

- [ ] **Step 3: route_logic.py 追加实现**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_route_logic -v`
Expected: PASS(14 用例)

- [ ] **Step 5: Commit**

```bash
git add src/task/route_logic.py tests/test_route_logic.py
git commit -m "feat: 录制操作层——按键→命令映射/操作栈撤销重放/blob 冷却(spec §5)"
```

---

### Task 5: 录制器 scripts/route_recorder.py + 实机验收(关卡 1)

**Files:**
- Create: `scripts/route_recorder.py`
- Uses: `scripts/capture_frame.py:build_capture()` / `src.detect.minimap` / `src.task.route_logic`

**Interfaces:**
- Consumes: Task 1-4 全部接口
- Produces(供 Task 6 与实机):
  - `minimap/<地图名>/map_meta.json`(含 panel_roi)
  - `minimap/<地图名>/route1.png`(及 route2...)
  - `minimap/<地图名>/archive/panel_000.png ... panel_019.png`(20 帧面板裁剪存档)
  - `minimap/<地图名>/jitter_stats.json`(`{'std': float, 'p95': float, 'n': int}`,静止期质心抖动)

- [ ] **Step 1: 写脚本(工具脚本,无单测;纯逻辑已在 Task 1-4 测完)**

```python
"""路线录制器(spec §5):手动走一遍,按键着色,录出 route*.png。
用法: python scripts/route_recorder.py <地图名>
流程: 标定(首跑)→ 移动捕获 → 录制(F2 存段/F3 撤销/F4 放弃段/ESC 退出)。
前置: 停 GUI(WGC 冲突,AGENTS.md §1.4);游戏窗口前台 2560×1440;小地图展开+约定缩放。"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from pynput import keyboard

from scripts.capture_frame import build_capture
from src.detect import minimap
from src.task import route_logic as rl

DEFAULT_PANEL_ROI = (10, 100, 270, 190)   # 面板地图区粗裁(2560×1440 实测训练场截图),CLI 可改
ARCHIVE_FRAMES = 20                        # 存档帧数(离线测试用)
BLOB_COOLDOWN = 0.7

# 真实键位 → 规范名(与 config.py 游戏按键默认一致;用户改过键位需同步)
KEY_MAP = {
    keyboard.Key.left: 'left', keyboard.Key.right: 'right',
    keyboard.Key.up: 'up', keyboard.Key.down: 'down',
    keyboard.Key.alt_l: 'space', keyboard.Key.alt_r: 'space',
    keyboard.Key.f2: 'f2', keyboard.Key.f3: 'f3', keyboard.Key.f4: 'f4',
    keyboard.Key.esc: 'esc',
}


class Recorder:
    def __init__(self, map_dir, panel_roi):
        self.map_dir = map_dir
        self.base = minimap.load_base_map(map_dir)
        assert self.base is not None, f'底图缺失: {map_dir}/底图.png'
        self.panel_roi = panel_roi
        self.meta = minimap.load_map_meta(map_dir)
        self.pressed = set()
        self.tracker = minimap.DotTracker()
        self.ops = rl.RouteOps(self.base.shape[:2])
        self.seg_idx = 0
        self.last_pos = None
        self.last_dot_time = 0.0
        self.last_blob = 0.0
        self.jitter = []            # 静止期(无方向键)质心样本,抖动统计
        self.archive = []           # 存档帧
        self.quit = False

    def on_key(self, key, down):
        name = KEY_MAP.get(key) if isinstance(key, keyboard.Key) else None
        if name is None:
            return
        if down:
            self.pressed.add(name)
            if name == 'f3':
                self.ops.undo()
            elif name == 'f4':
                self.ops.clear()
            elif name == 'esc':
                self.quit = True
        else:
            self.pressed.discard(name)

    def calibrate_once(self, frame):
        """首跑标定 → map_meta.json;已有 meta 直接复用但打印匹配分。"""
        panel = frame[self.panel_roi[1]:self.panel_roi[1] + self.panel_roi[3],
                      self.panel_roi[0]:self.panel_roi[0] + self.panel_roi[2]]
        if self.meta is None:
            meta = minimap.calibrate(panel, self.base)
            assert meta is not None, '标定失败:面板折叠/缩放不对/底图不匹配,检查小地图'
            meta['panel_roi'] = self.panel_roi
            minimap.save_map_meta(self.map_dir, meta)
            self.meta = meta
        self.meta['panel_roi'] = self.panel_roi
        print(f"[标定] scale={self.meta['scale']:.2f} offset=({self.meta['offset_x']:.0f},"
              f"{self.meta['offset_y']:.0f}) score={self.meta.get('match_score', 0):.2f}")

    def acquire_once(self, cap):
        """移动捕获:提示用户左右走两步,取位移最大的黄点(spec §2.3)。"""
        print('[捕获] 请在游戏里左右走动两步(3 秒)...')
        before, after = [], []
        t0 = time.time()
        while time.time() - t0 < 3.0:
            frame = cap.get_frame()
            if frame is None:
                continue
            panel = minimap.crop_panel(frame, self.meta)
            dots = minimap.find_yellow_dots(panel)
            if time.time() - t0 < 1.0:
                before.append(dots)
            elif time.time() - t0 > 2.0:
                after.append(dots)
        if before and after:
            pos = self.tracker.acquire(before[-1], after[0], self.meta)
            print(f'[捕获] 自己={pos}')
            return pos is not None
        return False

    def step(self, frame, now):
        panel = minimap.crop_panel(frame, self.meta)
        if len(self.archive) < ARCHIVE_FRAMES and now - self.last_dot_time > 0.5:
            self.archive.append(panel.copy())
        dots = minimap.find_yellow_dots(panel)
        pos, status = self.tracker.update(dots, self.meta, now)
        if pos is not None:
            self.last_dot_time = now
            if not (self.pressed & {'left', 'right', 'up', 'down'}):
                self.jitter.append(pos)
            action = rl.action_for_keys(self.pressed)
            if action is not None:
                if action in rl.WALK_COMMANDS:
                    # 走色画线;黄点丢失超 0.5s 断线不连(spec §5 防垃圾长线)
                    if self.last_pos is not None and now - self.last_dot_time < 0.5:
                        self.ops.draw_line(self.last_pos, pos, action)
                elif rl.blob_ready(now, self.last_blob, BLOB_COOLDOWN):
                    self.ops.draw_blob(pos, action)
                    self.last_blob = now
                if action == rl.GOAL_COMMAND:
                    path = os.path.join(self.map_dir, f'route{self.seg_idx + 1}.png')
                    self.ops.save(path)
                    print(f'[保存] {path}')
                    self.seg_idx += 1
                    self.ops.clear()
            self.last_pos = pos
        else:
            self.last_pos = None  # 丢失断线
        self.show(panel, pos, status)

    def show(self, panel, pos, status):
        base_bgr = self.base[:, :, :3].copy()       # 底图 BGRA → BGR
        layer = self.ops.layer
        over = cv2.addWeighted(base_bgr, 0.5, layer[:, :, :3], 0.5, 0)
        over[layer[:, :, 3] > 0] = layer[layer[:, :, 3] > 0][:, :3]
        if pos is not None:
            cv2.drawMarker(over, (int(pos[0]), int(pos[1])), (0, 255, 255),
                           cv2.MARKER_CROSS, 6, 1)
        big = cv2.resize(over, (over.shape[1] * 6, over.shape[0] * 6),
                         interpolation=cv2.INTER_NEAREST)
        cv2.putText(big, f'seg{self.seg_idx + 1} {status} F2=存段 F3=撤销 F4=放弃 ESC=退',
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.imshow('route_recorder', big)
        cv2.waitKey(1)

    def finish(self):
        """存档帧 + 抖动统计 + 路线校验报告(涂错色)。"""
        arch_dir = os.path.join(self.map_dir, 'archive')
        os.makedirs(arch_dir, exist_ok=True)
        for i, p in enumerate(self.archive):
            minimap.imwrite_unicode(os.path.join(arch_dir, f'panel_{i:03d}.png'), p)
        if len(self.jitter) >= 10:
            arr = np.array(self.jitter)
            dev = np.abs(arr - arr.mean(axis=0)).sum(axis=1)
            stats = {'std': float(dev.std()), 'p95': float(np.percentile(dev, 95)),
                     'n': int(len(dev))}
            with open(os.path.join(self.map_dir, 'jitter_stats.json'), 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            print(f'[抖动] {stats}')
        _segs, unknown = rl.load_routes(self.map_dir)
        if unknown:
            print(f'[校验] {len(unknown)} 个像素不在色表(涂错/抗锯齿),前 5 个: {unknown[:5]}')


if __name__ == '__main__':
    map_name = sys.argv[1] if len(sys.argv) > 1 else '东部岩山5'
    map_dir = os.path.join('minimap', map_name)
    ev, win, cap = build_capture()
    rec = Recorder(map_dir, DEFAULT_PANEL_ROI)
    listener = keyboard.Listener(on_press=lambda k: rec.on_key(k, True),
                                 on_release=lambda k: rec.on_key(k, False))
    listener.start()
    try:
        frame = cap.get_frame()
        rec.calibrate_once(frame)
        rec.acquire_once(cap)
        print('[录制] 开始走动吧')
        while not rec.quit:
            frame = cap.get_frame()
            if frame is not None:
                rec.step(frame, time.time())
            time.sleep(0.1)
    finally:
        rec.finish()
        listener.stop()
        ev.set()
        cv2.destroyAllWindows()
```

- [ ] **Step 2: 编译检查 + 全量单测**

Run: `$env:PYTHONUTF8=1; python -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`
Run: `$env:PYTHONUTF8=1; python -m unittest discover -s tests`
Expected: 编译 OK;单测全绿(允许显式 skip)

- [ ] **Step 3: Commit(实机前)**

```bash
git add scripts/route_recorder.py
git commit -m "feat: 路线录制器——标定/移动捕获/按键着色/分段/撤销/存档帧/抖动统计(spec §5)"
```

- [ ] **Step 4: 实机验收(关卡 1,手动)**

前置:停 GUI;游戏在东部岩山5;小地图展开+约定缩放。
Run: `python scripts/route_recorder.py 东部岩山5`
操作:沿巡逻路线走一遍(含上下绳子的位置按上/下),走完按 F2 存段,ESC 退出。
**判据(写死)**:① route1.png 轨迹线与实际走位肉眼吻合 ② goal/爬色点位置正确 ③ `[校验]` 无涂错色报告(有则重涂) ④ `jitter_stats.json` 落账 ⑤ `archive/` 20 帧齐。不通过 → 排查标定/缩放档,重录。
录完把资产入库:

```bash
git add minimap/东部岩山5/
git commit -m "chore: 东部岩山5 路线资产——route1.png + map_meta.json + 存档帧 + 抖动统计(关卡1)"
```

---

### Task 6: 存档帧离线回放测试

**Files:**
- Create: `tests/test_minimap_offline.py`

**Interfaces:**
- Consumes: `minimap/<地图名>/archive/*.png`(Task 5 产出)、`load_map_meta`、`find_yellow_dots`
- Produces: 无(测试)

- [ ] **Step 1: 写测试(存档帧缺失显式 skip,§11.4)**

```python
"""存档帧回放(§11.4:帧缺失显式 skip)。帧由 route_recorder 实机录制。"""
import glob
import os
import unittest

from src.detect import minimap

MAP_DIR = os.path.join('minimap', '东部岩山5')
FRAMES = sorted(glob.glob(os.path.join(MAP_DIR, 'archive', 'panel_*.png')))


@unittest.skipUnless(len(FRAMES) >= 20 and minimap.load_map_meta(MAP_DIR) is not None,
                     '存档帧/map_meta 缺失(未实机录制)')
class TestMinimapOffline(unittest.TestCase):

    def test_dots_detected_in_most_frames(self):
        hits = 0
        for f in FRAMES:
            panel = minimap.imread_unicode(f)  # 存档帧路径含中文,cv2.imread 会静默返 None
            if panel is not None and minimap.find_yellow_dots(panel):
                hits += 1
        self.assertGreaterEqual(hits / len(FRAMES), 0.8,
                                f'黄点检出率 {hits}/{len(FRAMES)} 过低')

    def test_positions_within_map_bounds(self):
        meta = minimap.load_map_meta(MAP_DIR)
        base = minimap.load_base_map(MAP_DIR)
        h, w = base.shape[:2]
        for f in FRAMES:
            panel = minimap.imread_unicode(f)
            if panel is None:
                continue
            for cx, cy, _a in minimap.find_yellow_dots(panel):
                mx, my = minimap.panel_to_map((cx, cy), meta)
                self.assertTrue(-5 <= mx <= w + 5 and -5 <= my <= h + 5,
                                f'{f} 黄点变换后越界: ({mx:.1f}, {my:.1f})')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_minimap_offline -v`
Expected: 已录存档帧 → PASS;未录 → SKIP(`skipped '存档帧/map_meta 缺失(未实机录制)'`)

- [ ] **Step 3: Commit**

```bash
git add tests/test_minimap_offline.py
git commit -m "test: 小地图存档帧离线回放——黄点检出率≥80%/变换不出界(§11.4 skip)"
```

---

## M1 单层巡逻(验收关卡 2)

### Task 7: 配置接入(键位/移动模式/巡逻地图/分组)

**Files:**
- Modify: `config.py`(key_config_option 加三键)
- Modify: `src/task/MapleFarmTask.py`(DEFAULT_CONFIG/CONFIG_GROUPS/config_type/config_description)
- Test: `tests/test_config_groups.py`(组顺序断言更新)

**Interfaces:**
- Produces:
  - 游戏按键新键:`'上移键'='up'` / `'下移键'='down'` / `'跳跃键'='alt'`(run() 里 `keys['上移键']` 等可用)
  - DEFAULT_CONFIG 新键:`'移动模式': '站桩'` / `'巡逻地图': '东部岩山5'`;`config_type['移动模式']` 下拉 `['站桩', '路线巡逻']`
  - CONFIG_GROUPS 新组 `('巡逻', ['移动模式', '巡逻地图'])` 插在 `'寻怪'` 组后

- [ ] **Step 1: 改失败测试(组顺序)**

`tests/test_config_groups.py` 的 `test_group_order_visible_groups_keeps_definition_order` 期望列表改为:

```python
        self.assertEqual(groups, ['攻击', '拾取', '保命与药水', '走位与朝向', '寻怪', '巡逻',
                                  '角色定位', '战斗细节', '挂机辅助', '调试'])
```

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_config_groups -v`
Expected: FAIL(组顺序不符 + 「有键未分组」)

- [ ] **Step 2: 实现配置**

`config.py` key_config_option dict 中 `'右移键': 'right',` 后追加:

```python
    '上移键': 'up',
    '下移键': 'down',
    '跳跃键': 'alt',
```

`MapleFarmTask.py`:
- DEFAULT_CONFIG 追加 `'移动模式': '站桩', '巡逻地图': '东部岩山5',`
- CONFIG_GROUPS 在 `('寻怪', [...])` 后插入 `('巡逻', ['移动模式', '巡逻地图']),`
- `self.config_type['攻击模式']` 那两行旁加:

```python
        self.config_type['移动模式'] = {'type': 'drop_down', 'options': ['站桩', '路线巡逻']}
```

- `self.config_description.update({...})` 内加:

```python
            '移动模式': '站桩=原地打怪;路线巡逻=沿 minimap/<巡逻地图>/route*.png 走,怪进攻击区停下打',
            '巡逻地图': 'minimap/ 下的资产目录名(含底图.png/route*.png/map_meta.json),用 route_recorder 录制',
```

- [ ] **Step 3: 跑测试确认通过**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_config_groups -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add config.py src/task/MapleFarmTask.py tests/test_config_groups.py
git commit -m "feat: 巡逻配置接入——上移/下移/跳跃键 + 移动模式/巡逻地图 + 「巡逻」配置组"
```

---

### Task 8: PatrolMachine 状态机(FOLLOW/COMBAT/goal/RECOVER 骨架)

**Files:**
- Modify: `src/task/route_logic.py`(追加 PatrolMachine + PatrolOutput)
- Test: `tests/test_route_logic.py`(追加 TestPatrolMachine)

**Interfaces:**
- Consumes: Task 3 的 `nearest_command` 结果 / `CLIMB_COMMANDS` / `GOAL_COMMAND` / `advance_segment`
- Produces(Task 9/12/13 依赖):
  - `PatrolOutput = collections.namedtuple('PatrolOutput', ['state', 'held', 'taps', 'stop', 'note'])`;`held` = frozenset,元素 ∈ `{'left','right','up','down'}`;`taps` = tuple,元素 ∈ `{'jump'}`;`stop: bool`;`note: str`
  - `PatrolMachine(stuck_timeout=60.0, recover_timeout=10.0, jump_cooldown=0.5)`,字段 `.state` / `.seg_idx`
  - `tick(now, pos, nearest, mob_in_zone, anchor_y, alarm=None) -> PatrolOutput`;`pos=(mx,my)|None`;`alarm ∈ {None,'lost','suspect','mismatch'}`(Task 13 接线,本任务只认值)
  - 本任务范围:FOLLOW(走/跳/停) / COMBAT(让路) / goal 轮转 / RECOVER(进出+超时 stop) / 60s 卡死 / alarm→RECOVER。CLIMB 分支留 `NotImplementedError` 之外的空转(M2 Task 11 填)

- [ ] **Step 1: 追加失败测试**

```python
from src.task.route_logic import PatrolMachine as PM


def nearest(cmd, pixel=(10, 10), dist=0):
    return {'command': cmd, 'pixel': pixel, 'distance': dist}


class TestPatrolMachine(unittest.TestCase):

    def test_follow_walks_left(self):
        m = PM()
        out = m.tick(100.0, (12, 10), nearest('left none none'), False, 500.0)
        self.assertEqual(out.state, 'FOLLOW')
        self.assertEqual(out.held, frozenset({'left'}))
        self.assertFalse(out.stop)

    def test_follow_jump_blob_taps_once_with_cooldown(self):
        m = PM()
        out1 = m.tick(100.0, (10, 10), nearest('left none jump'), False, 500.0)
        out2 = m.tick(100.2, (10, 10), nearest('left none jump'), False, 500.0)  # 同一 blob 冷却内
        self.assertEqual(out1.taps, ('jump',))
        self.assertEqual(out1.held, frozenset({'left'}))
        self.assertEqual(out2.taps, ())

    def test_zone_mob_enters_combat_and_releases_keys(self):
        m = PM()
        m.tick(100.0, (12, 10), nearest('left none none'), False, 500.0)
        out = m.tick(100.5, (12, 10), nearest('left none none'), True, 500.0)
        self.assertEqual(out.state, 'COMBAT')
        self.assertEqual(out.held, frozenset())
        back = m.tick(103.0, (12, 10), nearest('left none none'), False, 500.0)
        self.assertEqual(back.state, 'FOLLOW')
        self.assertEqual(back.held, frozenset({'left'}))

    def test_goal_advances_segment_and_stays_follow(self):
        m = PM()
        out = m.tick(100.0, (10, 10), nearest('none none goal'), False, 500.0)
        self.assertEqual(out.state, 'FOLLOW')  # goal=FOLLOW 自环,不进 RECOVER(spec 评审 4)
        self.assertEqual(m.seg_idx, 1)

    def test_alarm_enters_recover_and_recovers(self):
        m = PM()
        out = m.tick(100.0, None, None, False, 500.0, alarm='lost')
        self.assertEqual(out.state, 'RECOVER')
        back = m.tick(101.0, (12, 10), nearest('left none none'), False, 500.0)
        self.assertEqual(back.state, 'FOLLOW')

    def test_recover_timeout_stops(self):
        m = PM(recover_timeout=10.0)
        m.tick(100.0, None, None, False, 500.0, alarm='lost')
        out = m.tick(111.0, None, None, False, 500.0)
        self.assertTrue(out.stop)

    def test_stuck_60s_enters_recover(self):
        m = PM(stuck_timeout=60.0)
        m.tick(100.0, (10, 10), nearest('left none none'), False, 500.0)
        out = m.tick(161.0, (10, 10), nearest('left none none'), False, 500.0)  # 61s 没挪窝
        self.assertEqual(out.state, 'RECOVER')

    def test_climb_color_no_crash_before_m2(self):
        # M1 路线无爬色;若意外出现,保持 FOLLOW 不崩溃(M2 Task 11 才接管)
        m = PM()
        out = m.tick(100.0, (10, 10), nearest('none up none'), False, 500.0)
        self.assertEqual(out.state, 'FOLLOW')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_route_logic.TestPatrolMachine -v`
Expected: FAIL `ImportError: cannot import name 'PatrolMachine'`

- [ ] **Step 3: route_logic.py 追加 PatrolMachine**

```python
from collections import namedtuple

PatrolOutput = namedtuple('PatrolOutput', ['state', 'held', 'taps', 'stop', 'note'])


class PatrolMachine:
    """巡逻状态机(spec §4):FOLLOW/COMBAT/CLIMB/RECOVER。纯逻辑——
    tick 只返回按键意图(held/taps),IO 由调用方执行并做差分。
    CLIMB 子阶段在 M2 Task 11 实现;此前爬色不接管。"""

    FOLLOW, COMBAT, CLIMB, RECOVER = 'FOLLOW', 'COMBAT', 'CLIMB', 'RECOVER'

    def __init__(self, stuck_timeout=60.0, recover_timeout=10.0, jump_cooldown=0.5):
        self.state = self.FOLLOW
        self.seg_idx = 0
        self.stuck_timeout = stuck_timeout
        self.recover_timeout = recover_timeout
        self.jump_cooldown = jump_cooldown
        self._last_jump = None        # (pixel, t) 同一跳色 blob 冷却
        self._recover_since = None
        self._last_move = None        # (pos, t) 卡死检测:位置+最后移动时刻

    def _output(self, held=frozenset(), taps=(), stop=False, note=''):
        return PatrolOutput(self.state, frozenset(held), tuple(taps), stop, note)

    def _enter_recover(self, now, note):
        if self.state != self.RECOVER:
            self.state = self.RECOVER
            self._recover_since = now
        return self._output(note=note)

    def tick(self, now, pos, nearest, mob_in_zone, anchor_y, alarm=None):
        # 卡死检测(60s 无位移,spec §6 最后兜底;RECOVER 中不累计)
        if pos is not None and self.state != self.RECOVER:
            if self._last_move is None or (abs(pos[0] - self._last_move[0][0])
                                           + abs(pos[1] - self._last_move[0][1])) > 1:
                self._last_move = (pos, now)
            elif now - self._last_move[1] > self.stuck_timeout:
                return self._enter_recover(now, 'stuck60')
        # 跟踪层告警(§2.3;超时换算在调用方)
        if alarm in ('lost', 'suspect', 'mismatch'):
            return self._enter_recover(now, alarm)

        if self.state == self.RECOVER:
            if pos is not None and nearest is not None:
                self.state = self.FOLLOW
                self._recover_since = None
                self._last_move = (pos, now)
            elif now - self._recover_since > self.recover_timeout:
                return self._output(stop=True, note='recover_timeout')
            else:
                # 定向恢复:左右交替小步走,重新捕获黄点/找回路线
                held = {'left'} if int(now * 2) % 2 == 0 else {'right'}
                return self._output(held=held, note='recovering')

        if self.state == self.COMBAT:
            if not mob_in_zone:
                self.state = self.FOLLOW
            else:
                return self._output(note='combat')

        # FOLLOW(及刚从 COMBAT 落回)
        if mob_in_zone:
            self.state = self.COMBAT
            return self._output(note='engage')
        if nearest is None:
            return self._output(note='no_route_pixel')
        cmd = nearest['command']
        if cmd == GOAL_COMMAND:
            self.seg_idx = advance_segment(self.seg_idx, 2, cmd)  # 段数由调用方校准(下步)
            return self._output(note='goal')
        if cmd == STOP_COMMAND:
            return self._output(note='stop_point')
        if cmd in CLIMB_COMMANDS:
            return self._output(note='climb_color_pending_m2')  # M2 Task 11 接管
        left_right, _up_down, action = cmd.split()
        held = set()
        if left_right in ('left', 'right'):
            held.add(left_right)
        taps = []
        if action == 'jump':
            last = self._last_jump
            if last is None or last[0] != nearest['pixel'] or now - last[1] >= self.jump_cooldown:
                taps.append('jump')
                self._last_jump = (nearest['pixel'], now)
        return self._output(held=held, taps=taps, note=cmd)
```

- [ ] **Step 4: 跑测试确认通过 + 修正段数问题**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_route_logic.TestPatrolMachine -v`
Expected: PASS(8 用例)。注意 `advance_segment(self.seg_idx, 2, cmd)` 里的字面量 `2` 是占位——goal 测试用例段数为 2 恰好正确;Task 9 集成时改为 `PatrolMachine(n_segments)` 构造参数。本步顺手改掉:构造加 `n_segments=2`,`advance_segment(self.seg_idx, self.n_segments, cmd)`,测试补 `PM(n_segments=2)`。

- [ ] **Step 5: Commit**

```bash
git add src/task/route_logic.py tests/test_route_logic.py
git commit -m "feat: PatrolMachine 状态机骨架——FOLLOW/COMBAT/goal 轮转/RECOVER+60s 卡死(spec §4)"
```

---

### Task 9: MapleFarmTask 巡逻拍接入(移动权仲裁 + 移动捕获启动)

**Files:**
- Modify: `src/task/MapleFarmTask.py`(init/run/_draw_debug 旁的私有方法)
- Test: `tests/test_farm_task_offline.py`(追加巡逻用例,mock keys)

**Interfaces:**
- Consumes: Task 1-3(minimap/route_logic)、Task 7(配置)、Task 8(PatrolMachine/PatrolOutput)
- Produces(Task 10/12/14 依赖):
  - `MapleFarmTask.MINIMAP_DIR = 'minimap'`
  - `self._patrol` → `None | {'meta','base','segments','tracker','machine','held':set,'seg_files':int}`
  - `_patrol_enabled(cfg) -> bool` / `_patrol_ensure_loaded(cfg) -> bool` / `_patrol_tick(now, frame, cfg, keys) -> None` / `_patrol_release_all(keys) -> None` / `_patrol_acquire_step(now, frame, keys) -> bool`(移动捕获三步,True=完成)
  - 按键差分约定:held 元素 `'left'|'right'|'up'|'down'` → `keys['左移键'/'右移键'/'上移键'/'下移键']`;taps `'jump'` → `send_key(keys['跳跃键'])`

- [ ] **Step 1: 写失败测试(offline,mock send_key 系列;参照文件内既有 run_with_frame 模式)**

```python
class TestPatrolTick(unittest.TestCase):
    """巡逻拍:空闲时按最近色驱动方向键;有怪让路;资源缺失停任务(§11.4 不依赖真帧)。"""

    def _task(self, segments):
        from src.task.MapleFarmTask import MapleFarmTask, DEFAULT_CONFIG
        from src.task.route_logic import PatrolMachine
        from src.detect.minimap import DotTracker
        task = MapleFarmTask.__new__(MapleFarmTask)  # 离线:不触发 on_create
        task.config = {**DEFAULT_CONFIG, '移动模式': '路线巡逻', '巡逻地图': '测试图'}
        task._patrol = {'meta': {'scale': 1.0, 'offset_x': 0.0, 'offset_y': 0.0,
                                 'panel_roi': (0, 0, 122, 94), 'search_range': 8},
                        'base': None, 'segments': segments,
                        'tracker': DotTracker(), 'machine': PatrolMachine(),
                        'held': set(), 'seg_files': len(segments), 'acquired': True}
        task._seek_dir = None
        task._last_mob_present = False
        task._detect_attacking = False
        return task

    def test_idle_drives_direction_key(self):
        import numpy as np
        from unittest.mock import patch
        task = self._task([{(10, 10): 'left none none'}])
        task._patrol['tracker'].pos = (12.0, 10.0)
        frame = np.zeros((94, 122, 3), np.uint8)
        cv2_circle = __import__('cv2').circle
        cv2_circle(frame, (12, 10), 2, (0, 255, 255), -1)
        with patch.object(task, 'send_key_down') as down, patch.object(task, 'send_key_up') as up:
            task._patrol_tick(100.0, frame, task.config,
                              {'左移键': 'left', '右移键': 'right', '上移键': 'up',
                               '下移键': 'down', '跳跃键': 'alt'})
        down.assert_called_once_with('left')
        up.assert_not_called()

    def test_mob_in_zone_releases_held_keys(self):
        import numpy as np
        from unittest.mock import patch
        task = self._task([{(10, 10): 'left none none'}])
        task._patrol['tracker'].pos = (12.0, 10.0)
        task._patrol['held'] = {'left'}
        task._last_mob_present = True
        frame = np.zeros((94, 122, 3), np.uint8)
        __import__('cv2').circle(frame, (12, 10), 2, (0, 255, 255), -1)
        with patch.object(task, 'send_key_down') as down, patch.object(task, 'send_key_up') as up:
            task._patrol_tick(100.0, frame, task.config,
                              {'左移键': 'left', '右移键': 'right', '上移键': 'up',
                               '下移键': 'down', '跳跃键': 'alt'})
        down.assert_not_called()
        up.assert_called_once_with('left')

    def test_missing_assets_stops_farming(self):
        from unittest.mock import patch
        task = self._task([])
        task._patrol = None
        with patch.object(task, 'stop_farming') as stop, \
             patch('src.detect.minimap.load_map_meta', return_value=None), \
             patch('src.detect.minimap.load_base_map', return_value=None):
            ok = task._patrol_ensure_loaded(task.config)
        self.assertFalse(ok)
        stop.assert_called_once()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_farm_task_offline.TestPatrolTick -v`
Expected: FAIL(`AttributeError: ... no attribute '_patrol_tick'`)

- [ ] **Step 3: 实现(MapleFarmTask.py)**

`__init__` 里加 `self._patrol = None`。类常量加 `MINIMAP_DIR = 'minimap'`。追加方法:

```python
    # ---------- 路线巡逻(spec §1 移动权仲裁:空闲才驱动,战斗让路) ----------

    def _patrol_enabled(self, cfg):
        return cfg.get('移动模式') == '路线巡逻'

    def _patrol_ensure_loaded(self, cfg):
        """懒加载路线资产 + 启动校验(spec §6):缺资产/校验不过 → 停任务,返回 False。"""
        if self._patrol is not None:
            return True
        from src.detect import minimap
        from src.task import route_logic as rl
        map_dir = os.path.join(self.MINIMAP_DIR, cfg.get('巡逻地图', '').strip())
        meta = minimap.load_map_meta(map_dir)
        base = minimap.load_base_map(map_dir)
        segments, unknown = rl.load_routes(map_dir)
        if meta is None or base is None or not segments:
            self.stop_farming(f'路线资产缺失/未标定: {map_dir}(先跑 route_recorder 录制)')
            return False
        self._patrol = {'meta': meta, 'base': base, 'segments': segments,
                        'tracker': minimap.DotTracker(),
                        'machine': rl.PatrolMachine(n_segments=len(segments)),
                        'held': set(), 'seg_files': len(segments),
                        'acquired': False, 'acquire_step': 0,
                        'acquire_dots': [[], []], 'acquire_t0': 0.0,
                        'alarm_since': {}, 'lost_since': None}
        return True

    def _patrol_release_all(self, keys):
        """F9 暂停/战斗接管/停止前:巡逻按住的方向键全松(参照 _seek_key 的松键纪律)。"""
        if not self._patrol:
            return
        key_of = {'left': '左移键', 'right': '右移键', 'up': '上移键', 'down': '下移键'}
        for d in self._patrol['held']:
            self.send_key_up(keys[key_of[d]])
        self._patrol['held'] = set()

    def _patrol_acquire_step(self, now, frame, keys):
        """启动移动捕获(spec §2.3):左走0.4s→右走0.4s,动的黄点=自己。完成 → True。"""
        from src.detect import minimap
        p = self._patrol
        panel = minimap.crop_panel(frame, p['meta'])
        dots = minimap.find_yellow_dots(panel)
        if p['acquire_step'] == 0:
            p['acquire_t0'] = now
            p['acquire_step'] = 1
            self.send_key_down(keys['左移键'])
        elif p['acquire_step'] == 1:
            p['acquire_dots'][0].append(dots)
            if now - p['acquire_t0'] > 0.4:
                self.send_key_up(keys['左移键'])
                self.send_key_down(keys['右移键'])
                p['acquire_step'] = 2
                p['acquire_t0'] = now
        elif p['acquire_step'] == 2:
            p['acquire_dots'][1].append(dots)
            if now - p['acquire_t0'] > 0.4:
                self.send_key_up(keys['右移键'])
                p['acquire_step'] = 3
        else:
            before = p['acquire_dots'][0][-1] if p['acquire_dots'][0] else []
            after = p['acquire_dots'][1][-1] if p['acquire_dots'][1] else []
            pos = p['tracker'].acquire(before, after, p['meta'])
            if pos is None:
                p['acquire_step'] = 0  # 没捕到:重来一轮
                return False
            p['acquired'] = True
            return True
        return False

    def _patrol_tick(self, now, frame, cfg, keys):
        """每空闲拍:感知 → 跟踪 → 状态机 → 按键差分。COMBAT 语义由现有攻击逻辑实现,
        本函数只负责巡逻侧松键(spec §4:怪进攻击区 → machine COMBAT → held=∅)。"""
        from src.detect import minimap
        from src.task import route_logic as rl
        p = self._patrol
        if not p['acquired']:
            if self._patrol_acquire_step(now, frame, keys):
                self.log_info('巡逻移动捕获完成,开始沿线巡逻')
            return
        panel = minimap.crop_panel(frame, p['meta'])
        dots = minimap.find_yellow_dots(panel)
        cmd_dir = next((d for d in ('left', 'right') if d in p['held']), None)
        pos, status = p['tracker'].update(dots, p['meta'], now, cmd_dir=cmd_dir)
        # 跟踪告警超时换算(spec §2.3/§6):suspect 1s、lost 2s、mismatch 立即
        alarm = None
        if status == 'mismatch':
            alarm = 'mismatch'
        elif status in ('suspect', 'lost'):
            limit = 1.0 if status == 'suspect' else 2.0
            since = p['alarm_since'].get(status)
            if since is None:
                p['alarm_since'][status] = now
            elif now - since > limit:
                alarm = status
        else:
            p['alarm_since'] = {}
        seg = p['segments'][p['machine'].seg_idx] if p['segments'] else {}
        nearest = rl.nearest_command(seg, pos, p['meta'].get('search_range', 8)) if pos else None
        anchor_y = self._anchor[1] if self._anchor is not None else None
        out = p['machine'].tick(now, pos, nearest, bool(self._last_mob_present),
                                anchor_y, alarm=alarm)
        if out.stop:
            self._patrol_release_all(keys)
            self.stop_farming(f'巡逻放弃:{out.note}')
            return
        key_of = {'left': '左移键', 'right': '右移键', 'up': '上移键', 'down': '下移键'}
        for d in p['held'] - out.held:
            self.send_key_up(keys[key_of[d]])
        for d in out.held - p['held']:
            self.send_key_down(keys[key_of[d]])
        for t in out.taps:
            if t == 'jump':
                self.send_key(keys['跳跃键'])
        p['held'] = set(out.held)
        p['last_output'] = out
```

`run()` 接入(检测模式分支,`self._do_seek_move(cfg, keys)` 之后):

```python
            # 4.4 路线巡逻(spec §1):移动模式=路线巡逻时,寻怪/走位整体旁路,
            # 空闲拍由巡逻驱动;战斗(attack/seek 逻辑)原样优先
            if self._patrol_enabled(cfg):
                if self._seek_key is not None:  # 巡逻下不该有寻怪长按,防御性松掉
                    self.send_key_up(keys[self._seek_key])
                    self._seek_key = None
                if self._patrol is not None or self._patrol_ensure_loaded(cfg):
                    if not self._last_mob_present and self._seek_dir is None:
                        self._patrol_tick(now, frame, cfg, keys)
                    elif self._patrol:
                        self._patrol_release_all(keys)
```

并将 `self._do_seek_move(cfg, keys)` 调用改为巡逻时跳过:

```python
            self._do_attack(cfg, keys, now)
            if not self._patrol_enabled(cfg):
                self._do_seek_move(cfg, keys)
```

4.5 防挂机走位条件改为 `if not self._patrol_enabled(cfg) and cfg['走位开关'] and ...`。

同时 F9 暂停处(run() 开头附近 `self._seek_key` 松键逻辑旁)加 `self._patrol_release_all(keys)`——注意 keys 在该处可得;若不可得则在 `_clear_debug`/on_pause 类钩子里处理,实现时以现有 `_seek_key` 松键点为锚。

- [ ] **Step 4: 跑测试确认通过**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_farm_task_offline.TestPatrolTick -v`
Expected: PASS(3 用例)

- [ ] **Step 5: 全量单测 + 编译检查**

Run: `$env:PYTHONUTF8=1; python -m unittest discover -s tests` + §11.6 编译检查
Expected: 全绿(允许既有红 test_b_anchor_y_in_expected_band,§11.7)

- [ ] **Step 6: Commit**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 巡逻拍接入 run()——空闲驱动/战斗让路/启动移动捕获/寻怪走位旁路(spec §1)"
```

---

### Task 10: overlay 巡逻绘制 + 实机验收(关卡 2)

**Files:**
- Modify: `src/task/MapleFarmTask.py`(_draw_debug)
- Evidence: `screenshots/e2e/route_patrol/`

**Interfaces:**
- Consumes: Task 9 的 `self._patrol`(含 `last_output`)
- Produces: overlay 元素(面板 ROI 框/黄点十字/状态+命令文本),开关键 `'显示巡逻状态'`(DEFAULT_CONFIG 加,'调试'组)

- [ ] **Step 1: 实现绘制(_draw_debug 内追加,沿用现有 painter 模式)**

```python
        # 巡逻状态(spec §7):面板 ROI 框 + 黄点十字 + 状态/命令文本;不开巡逻模式不画
        if c.get('显示巡逻状态') and self._patrol is not None:
            from src.detect import minimap as mm
            p = self._patrol
            rx, ry, rw, rh = p['meta']['panel_roi']
            painter.setPen(QPen(PATROL_COLOR, 2))
            painter.drawRect(rect(rx, ry, rw, rh))
            if p['tracker'].pos is not None:
                px, py = mm.map_to_panel(p['tracker'].pos, p['meta'])
                painter.drawLine(QPointF((rx + px - 5) * ratio, (ry + py) * ratio),
                                 QPointF((rx + px + 5) * ratio, (ry + py) * ratio))
                painter.drawLine(QPointF((rx + px) * ratio, (ry + py - 5) * ratio),
                                 QPointF((rx + px) * ratio, (ry + py + 5) * ratio))
            out = p.get('last_output')
            if out is not None:
                painter.drawText(rect(rx, ry + rh + 6, 400, 24),
                                 f'巡逻 {out.state} {out.note}')
```

DEFAULT_CONFIG 加 `'显示巡逻状态': True`,CONFIG_GROUPS '调试' 组尾部加 `'显示巡逻状态'`,config_description 加说明;PATROL_COLOR 沿用文件内颜色常量风格定义(如 `QColor(255, 200, 0)`)。

- [ ] **Step 2: 单测 + 编译检查 + 组覆盖测试**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_config_groups tests.test_farm_task_offline -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/task/MapleFarmTask.py
git commit -m "feat: overlay 巡逻状态绘制——面板框/黄点十字/状态命令文本(spec §7)"
```

- [ ] **Step 4: 实机验收(关卡 2,手动)**

前置:route1.png **只含平层走/跳色**(若已涂爬色,本期先重录平层段);GUI 管理员启动;「启用标记框」开;移动模式=路线巡逻;巡逻地图=东部岩山5。
**判据(写死)**:① 移动捕获完成(日志「开始沿线巡逻」) ② 沿路线循环 ≥3 圈无卡死(卡死=同一小地图位置 60s 无位移) ③ 怪进攻击区停下打、区清继续走 ④ overlay 面板框/十字/状态正确 ⑤ E2E 截图存 `screenshots/e2e/route_patrol/` 并视觉验收。
通过后:

```bash
git add screenshots/e2e/route_patrol/
git commit -m "test: 路线巡逻关卡2 E2E 截图——单层 ≥3 圈/战斗让路/overlay 状态"
```

---

## M2 上下层 CLIMB(验收关卡 3)

### Task 11: CLIMB 四子阶段纯逻辑

**Files:**
- Modify: `src/task/route_logic.py`(PatrolMachine 填 CLIMB)
- Test: `tests/test_route_logic.py`(追加 TestPatrolClimb)

**Interfaces:**
- Consumes: Task 8 PatrolMachine
- Produces: PatrolMachine 构造参数追加 `climb_align_px=1, climb_align_ticks=3, climb_align_timeout=4.0, climb_verify_window=1.5, climb_max_retries=4, climb_min_dy=3.0`;`tick` 的 `anchor_y` 参数生效(降级:anchor_y=None 时用 pos 的 my)
- 语义(spec §4,评审 1/3):CLIMB **不被 mob_in_zone 打断**;对位=软目标(滞回 climb_align_ticks 拍,超时 climb_align_timeout 直接试爬);爬=按住 up/down + dy 验证;重试=朝梯子 tap + 再按,≤climb_max_retries;退出=最近色非爬色;4 次失败 → RECOVER

- [ ] **Step 1: 追加失败测试**

```python
class TestPatrolClimb(unittest.TestCase):

    def _m(self, **kw):
        return PM(**kw)

    def test_enter_climb_aligns_then_holds_up(self):
        m = self._m()
        m.tick(100.0, (20, 50), nearest('left none none'), False, 500.0)
        out = m.tick(100.5, (13, 50), nearest('none up none', pixel=(10, 40), dist=4), False, 500.0)
        self.assertEqual(out.state, 'CLIMB')
        self.assertEqual(out.held, frozenset({'left'}))   # 对位:朝梯子列走
        # 连续 3 拍 |dx|<=1 → 开爬
        for i in range(3):
            out = m.tick(101.0 + i * 0.1, (10, 50), nearest('none up none', pixel=(10, 40)), False, 498.0 - i * 2)
        self.assertEqual(out.held, frozenset({'up'}))
        # 怪进攻击区不打断 CLIMB(spec 评审 1)
        out2 = m.tick(101.5, (10, 45), nearest('none up none', pixel=(10, 40)), True, 492.0)
        self.assertEqual(out2.state, 'CLIMB')

    def test_align_timeout_falls_through_to_climb(self):
        m = self._m(climb_align_timeout=4.0)
        m.tick(100.0, (20, 50), nearest('none up none', pixel=(10, 40)), False, 500.0)
        out = m.tick(104.5, (19, 50), nearest('none up none', pixel=(10, 40)), False, 500.0)  # 4s 对位没收敛
        self.assertEqual(out.held, frozenset({'up'}))  # 直接试爬(spec 评审 3)

    def test_climb_verified_by_anchor_y_and_exits_on_walk_color(self):
        m = self._m()
        m.tick(100.0, (10, 50), nearest('none up none', pixel=(10, 40)), False, 500.0)
        m.tick(100.1, (10, 50), nearest('none up none', pixel=(10, 40)), False, 500.0)
        m.tick(100.2, (10, 50), nearest('none up none', pixel=(10, 40)), False, 500.0)
        out = m.tick(100.3, (10, 50), nearest('none up none', pixel=(10, 40)), False, 500.0)
        self.assertEqual(out.held, frozenset({'up'}))
        # 爬动中(anchor_y 持续变小)直到最近色变走色 → 退出 FOLLOW
        out = m.tick(102.0, (10, 38), nearest('left none none', pixel=(8, 38)), False, 470.0)
        self.assertEqual(out.state, 'FOLLOW')

    def test_no_progress_retries_then_recovers(self):
        m = self._m(climb_verify_window=1.5, climb_max_retries=4)
        # 入口拍即对位(评审 4):前置 3 拍恰好完成转换(100.0/100.1/100.2 命中 1/2/3 → 开爬)。
        # 评审 5:旧入口实现(入口拍空走)会把循环第一拍消耗在"开爬"上,循环 4 拍只攒 3 次重试
        m.tick(100.0, (10, 50), nearest('none up none', pixel=(10, 40)), False, 500.0)
        m.tick(100.1, (10, 50), nearest('none up none', pixel=(10, 40)), False, 500.0)
        m.tick(100.2, (10, 50), nearest('none up none', pixel=(10, 40)), False, 500.0)
        t = 100.3
        for i in range(4):  # 每窗 1.5s 无位移 → tap 重试
            out = m.tick(t + 1.6, (10, 50), nearest('none up none', pixel=(10, 40)), False, 500.0)
            t += 1.6
        out = m.tick(t + 1.6, (10, 50), nearest('none up none', pixel=(10, 40)), False, 500.0)
        self.assertEqual(out.state, 'RECOVER')  # 4 次全失败
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_route_logic.TestPatrolClimb -v`
Expected: FAIL(CLIMB 分支未实现,`state` 仍是 FOLLOW)

- [ ] **Step 3: 实现(PatrolMachine 填 CLIMB 分支,替换 `climb_color_pending_m2` 行)**

```python
        # __init__ 追加:
        self.climb_align_px = climb_align_px
        self.climb_align_ticks = climb_align_ticks
        self.climb_align_timeout = climb_align_timeout
        self.climb_verify_window = climb_verify_window
        self.climb_max_retries = climb_max_retries
        self.climb_min_dy = climb_min_dy
        self._climb = None  # {'target':px,'dir':'up'|'down','sub':'align'|'climb',
                            #  'since':t,'align_hits':int,'retries':int,'y0':float,'retry_tap':bool}
```

`tick` 中 CLIMB 块置于 mob_in_zone 判断**之前**(评审 1:怪不打断)、RECOVER 之后(跟踪告警仍可打断);子阶段步进抽成 `_climb_step`,FOLLOW 入口**委托同一段逻辑**——进入拍即对位(评审 4:旧实现入口拍 held=空集,白空走一拍);`_climb_step` 退出时返回 None,tick 落回本拍 FOLLOW 流程:

```python
        if self.state == self.CLIMB:
            out = self._climb_step(now, pos, nearest, anchor_y)
            if out is not None:
                return out
            # 返回 None = 已退 CLIMB(最近色变回走色),落回下面 FOLLOW 流程

    def _climb_step(self, now, pos, nearest, anchor_y):
        """CLIMB 子阶段步进 → PatrolOutput;退出 CLIMB 时返回 None(调用方落回 FOLLOW)。"""
        c = self._climb
        cur_y = anchor_y if anchor_y is not None else (pos[1] if pos else None)
        if nearest is None or nearest['command'] not in CLIMB_COMMANDS:
            self._climb = None
            self.state = self.FOLLOW
            return None
        if c['sub'] == 'align':
            dx = pos[0] - c['target'][0] if pos else 999
            if pos is not None and abs(dx) <= self.climb_align_px:
                c['align_hits'] += 1
            else:
                c['align_hits'] = 0
            if c['align_hits'] >= self.climb_align_ticks or \
                    now - c['since'] > self.climb_align_timeout:
                c['sub'] = 'climb'
                c['since'] = now
                c['y0'] = cur_y
                return self._output(held={c['dir']}, note='climb_start')
            step = 'left' if dx > 0 else 'right'
            return self._output(held={step}, note=f"align dx={dx:.1f}")
        # climb 子阶段:验证爬动
        progressed = (cur_y is not None and c['y0'] is not None
                      and ((c['dir'] == 'up' and cur_y < c['y0'] - self.climb_min_dy)
                           or (c['dir'] == 'down' and cur_y > c['y0'] + self.climb_min_dy)))
        if progressed:
            c['y0'] = cur_y
            c['since'] = now
            return self._output(held={c['dir']}, note='climbing')
        if now - c['since'] > self.climb_verify_window:
            c['retries'] += 1
            if c['retries'] > self.climb_max_retries:
                self._climb = None
                return self._enter_recover(now, 'climb_failed')
            # 朝梯子方向 tap 一小步,再按爬键(下拍生效);此处直接给 tap 意图
            step = 'left' if pos and pos[0] > c['target'][0] else 'right'
            c['since'] = now
            c['y0'] = cur_y
            return self._output(held={step}, note=f"climb_retry{c['retries']}")
        return self._output(held={c['dir']}, note='climb_wait')
```

FOLLOW 的 `cmd in CLIMB_COMMANDS` 分支改为进入并**当拍对位**:

```python
        if cmd in CLIMB_COMMANDS:
            _lr, ud, _act = cmd.split()
            self.state = self.CLIMB
            self._climb = {'target': nearest['pixel'], 'dir': ud, 'sub': 'align',
                           'since': now, 'align_hits': 0, 'retries': 0, 'y0': None}
            return self._climb_step(now, pos, nearest, anchor_y)  # 进入拍即对位(评审 4)
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `$env:PYTHONUTF8=1; python -m unittest tests.test_route_logic -v`
Expected: PASS(全部,含 Task 8 的 `test_climb_color_no_crash_before_m2`——该用例现在断言会失败,因为爬色已接管;**把该用例删除**)

- [ ] **Step 5: Commit**

```bash
git add src/task/route_logic.py tests/test_route_logic.py
git commit -m "feat: CLIMB 四子阶段——软对位+超时试爬/锚点y验证/tap重试/怪不打断(spec §4)"
```

---

### Task 12: CLIMB 实机验收(关卡 3)

**Files:**
- Modify: 无代码(接入已在 Task 9/11 完成;若实机暴露参数问题,只调 PatrolMachine 默认参数)
- Evidence: `minimap/东部岩山5/route*.png`(重录含爬色)、`screenshots/e2e/route_patrol/`

- [ ] **Step 1: 单测全绿 + 编译检查(铁律门槛)**

- [ ] **Step 2: 重录路线(含爬色)**

Run: `python scripts/route_recorder.py 东部岩山5` — 在平层走色基础上,走到绳子/梯子处按「上」录爬色(远离传送门,spec §6 录制规范),F2 存段。

- [ ] **Step 3: 实机跑巡逻**

**判据(写死)**:走到→对位→爬上→继续走 全流程 **3/3 次成功**;overlay 可见 `CLIMB align/climbing` 状态;失败时观察 tap 重试行为是否符合预期。顺带记录:对位阈值/验证窗/重试次数是否要调(调则改 PatrolMachine 默认值 + 补单测锁行为)。

- [ ] **Step 4: Commit**

```bash
git add minimap/东部岩山5/ screenshots/e2e/route_patrol/
git commit -m "test: 关卡3 上下层 E2E——爬色路线 + 3/3 全流程截图证据"
```

---

## M3 守护加固(验收关卡 4)

### Task 13: RECOVER 全接线 + 三档卡死

**Files:**
- Modify: `src/task/MapleFarmTask.py`(_patrol_tick 告警接线已在 Task 9;本任务补 60s 卡死与恢复表现)
- Modify: `src/task/route_logic.py`(RECOVER 细节,如需)
- Test: `tests/test_route_logic.py` / `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: Task 2(DotTracker status)、Task 8/11(PatrolMachine)
- Produces: `_patrol_tick` 完整告警语义:suspect>1s / lost>2s / mismatch 立即 / machine 内部 60s 卡死 → RECOVER;RECOVER 10s → stop_farming

- [ ] **Step 1: 失败测试(offline:三档告警各进 RECOVER;恢复回 FOLLOW;超时停任务)**

```python
class TestPatrolAlarms(unittest.TestCase):

    def _task(self):
        # 与 Task 9 _task 相同,外加 tracker 预设 pos
        ...

    def test_suspect_1s_enters_recover(self):
        # tracker 返 suspect 连续超 1s → machine alarm='suspect' → RECOVER
        ...

    def test_lost_2s_enters_recover(self): ...

    def test_mismatch_immediate_recover(self): ...

    def test_recover_timeout_stops_farming(self):
        # RECOVER 超 10s → stop_farming 被调
        ...
```

(测试骨架如上,实现时按 Task 9 TestPatrolTick 的 `_task` 工厂复用展开,每个用例断言 machine.state 或 stop_farming 调用。)

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现(基本已在 Task 9 完成;补齐缺口:alarm 后 alarm_since 复位、RECOVER 中 held 差分正确性)**

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

- [ ] **Step 5: Commit**

```bash
git add src/task/MapleFarmTask.py src/task/route_logic.py tests/
git commit -m "feat: 巡逻三档卡死/跟踪告警全接线——suspect1s/lost2s/mismatch 即入 RECOVER(spec §6)"
```

---

### Task 14: 意外换图守护 + 启动校验 + 实机验收(关卡 4)

**Files:**
- Modify: `src/task/MapleFarmTask.py`(_patrol_tick 低频校验)
- Test: `tests/test_farm_task_offline.py`(追加)

**Interfaces:**
- Consumes: Task 1 `terrain_match_score` / `TERRAIN_MIN_SCORE`
- Produces: `_patrol` 字段 `'terrain_bad': int` / `'terrain_check_t': float`;校验节奏 1.5s;连续 2 次 < TERRAIN_MIN_SCORE → stop_farming('检测到换图/小地图异常')

- [ ] **Step 1: 失败测试**

```python
class TestTerrainGuard(unittest.TestCase):

    def test_two_consecutive_low_scores_stop(self):
        # terrain_match_score 连续 2 次 < TERRAIN_MIN_SCORE → stop_farming
        task = ...  # TestPatrolTick._task 变体
        with patch('src.detect.minimap.terrain_match_score', return_value=0.1), \
             patch.object(task, 'stop_farming') as stop:
            task._patrol_tick(100.0, frame, task.config, KEYS)
            task._patrol_tick(101.6, frame, task.config, KEYS)   # 1.5s 后第二次
        stop.assert_called_once()

    def test_single_low_then_recovers_no_stop(self):
        with patch('src.detect.minimap.terrain_match_score', side_effect=[0.1, 0.9]), \
             patch.object(task, 'stop_farming') as stop:
            ...两次 tick...
        stop.assert_not_called()
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现(_patrol_tick 内,tracker 更新后加低频校验;首次 tick 必校=启动校验)**

```python
        # 意外换图守护(spec §6):1.5s 一次地形分;连续 2 次低分停任务;首次必校(启动校验)
        if p['base'] is not None and now - p.get('terrain_check_t', 0) > 1.5:
            p['terrain_check_t'] = now
            score = minimap.terrain_match_score(panel, p['base'], p['meta'])
            if score < minimap.TERRAIN_MIN_SCORE:
                p['terrain_bad'] = p.get('terrain_bad', 0) + 1
                if p['terrain_bad'] >= 2:
                    self._patrol_release_all(keys)
                    self.stop_farming(f'检测到换图/小地图异常(地形分 {score:.2f})')
                    return
            else:
                p['terrain_bad'] = 0
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归 + 编译检查**

- [ ] **Step 5: Commit**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 意外换图守护——1.5s 地形分校验,连续 2 次低分停任务;首次 tick 即启动校验(spec §6)"
```

- [ ] **Step 6: 实机验收(关卡 4,手动)**

**判据(写死)**:① 手动制造换图(按传送门出图一次)→ 任务 10s 内停止报警 ② 手动制造卡死(找个角落让角色顶墙走 60s+,或直接等三档卡死)→ 进 RECOVER,恢复不了则 10s 停任务 ③ 弹窗/掉线(既有守护)不受影响。截图存 `screenshots/e2e/route_patrol/`。

```bash
git add screenshots/e2e/route_patrol/
git commit -m "test: 关卡4 守护 E2E——换图 10s 停任务/卡死 RECOVER 截图证据"
```

---

## M4 实机验收(关卡 5)

### Task 15: 30 分钟长跑 + 验收记录

- [ ] **Step 1: 前置全绿确认(单测/编译/既有红仅 §11.7 那条)**

- [ ] **Step 2: 实机 30 分钟连续挂机(完整路线含上下层)**

**判据(写死)**:30 分钟无人工干预;无停任务;无漂移(路线始终找得回,黄点不认错);经验持续增长(经验停滞守护不触发)。
**数据留痕**:全程决策日志开(`决策日志开关=true`),日志关键段贴进 spec;抖动/重试/RECOVER 次数统计。

- [ ] **Step 3: 验收记录写进 spec**

在 `docs/superpowers/specs/2026-08-11-minimap-route-patrol-design.md` 末节追加「验收记录(2026-08-XX)」:五关逐项打勾 + 参数终值(对位/验证窗/重试/J 值等) + 已知边界。

```bash
git add docs/superpowers/specs/2026-08-11-minimap-route-patrol-design.md
git commit -m "docs: 路线巡逻五关验收记录——30min 无干预通过,参数终值落账"
```

---

## Self-Review 记录(计划完成后自查)

- **Spec 覆盖**:§0 决策→T7/T9;§2 感知→T1/T2;§3 路线数据→T3;§4 状态机→T8/T11;§5 录制器→T4/T5;§6 守护→T13/T14;§7 测试→贯穿;§8 五关→T5/T10/T12/T14/T15。无缺口。
- **占位符扫描**:T13 Step1 用例骨架标了 `...`——执行时按 T9 `_task` 工厂展开,属"重复代码不复制"的例外(同一文件内工厂);其余步骤均含完整代码。
- **类型一致**:`PatrolMachine(n_segments)`(T8 Step4 修正)↔ T9 `_patrol_ensure_loaded` 调用一致;`PatrolOutput.held` 元素 ∈ {'left','right','up','down'} ↔ T9 `key_of` 映射一致;`DotTracker.update` status 四值 ↔ T9 告警换算一致。
- **已知先后手**:T11 删除 T8 的 `test_climb_color_no_crash_before_m2`(爬色接管后语义过期),已在 T11 Step4 写明。

## 评审修订记录(2026-08-11,计划评审 5 条)

1. **calibrate() 判别力(严重)**:`_masked_score` 由 TM_CCORR_NORMED 改为 **TM_SQDIFF_NORMED + 对比度门禁**(匹配区 std ≥ 模板 std/2,uniform 背景压到 ~0)——旧实现稀疏 mask 下垃圾面板也能拿 0.74,打穿 spec §2.1"校验失败报错停任务"
2. **terrain_match_score() 判别力(严重)**:由 `1-平均差/765` 改为**逐像素色差容忍占比**(通道最大差 ≤ TERRAIN_PIX_TOL=30 的像素比例)——旧实现量程撑不满,错误地形也有 0.6~0.8,阈值形同虚设,打穿 spec §6 换图守护
3. **jump_guard 与拍节奏冲突(中)**:固定 8 格改为 **base 4 格 + 12 格/秒 × dt 自适应**(隐式频率假设消除;测试补 `test_jump_guard_scales_with_dt`);spec §2.3/§4 参数行同步修订
4. **CLIMB 入口空走一拍(中)**:子阶段步进抽成 `_climb_step`,FOLLOW 入口委托同一段逻辑,**进入拍即对位**;退出返回 None 落回本拍 FOLLOW
5. **重试计数少一拍(中)**:与第 4 条联动——入口拍即对位后前置 3 拍恰好完成转换,测试原样通过;测试内加拍数注释固化
6. 附带修复:`TestNearestCommand` 类定义缺右括号(SyntaxError)

## 评审修订记录(2026-08-11,预检 1 条)

7. **中文路径 cv2 IO 失效(实施预检铁证)**:cv2.imread(中文路径)静默返 None、cv2.imwrite 抛异常(OpenCV-Windows 经典缺陷,系统/venv 双环境复现;沙箱合成测试全 ASCII 未覆盖)。修法:`minimap.py` 加公开助手 **`imread_unicode`(imdecode+np.fromfile,模式出自 `ok/device/capture_methods/image.py:30`)** 与 **`imwrite_unicode`(imencode→bytes→Python `open('wb')`,open() 中文路径已实测正常)**;load_base_map/load_routes/RouteOps.save/录制器 finish()/test_minimap_offline 全部改走助手。回归测试:Task 1 `TestUnicodeIO`(中文子目录,助手+load_base_map+meta 读写)、Task 4 中文路径用例(RouteOps.save→load_routes 回读全链路)
