# 攻击区怪物门控 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自动打怪只在「攻击区内有怪」时放技能，无怪停手且任务继续运行；攻击区锚定角色本人（OCR 名字牌），不再是画面中心的固定矩形。

**Architecture:** 三层，边界清楚、各自可独立测试。`src/detect/ocr_engine.py` 只管 OCR 单例与结果解析；`src/detect/anchor.py` 只回答「角色名字牌在哪」（OCR 函数注入，可离线测）；`src/task/farm_logic.py` 只做纯几何/时间判定（攻击区、锚点过期）；`src/task/MapleFarmTask.py` 只负责接线。

**Tech Stack:** Python 3.12（嵌入式）、onnxocr（OpenVINO）、OpenVino YOLOv8、unittest、PySide6/qfluentwidgets（GUI 配置项）。

**Spec:** `docs/superpowers/specs/2026-08-06-attack-zone-mob-gating-design.md`

## Global Constraints

- Python 解释器**只用** `H:\ok-mxd\data\apps\ok-ww\python\python.exe`；**禁止 pip install**（环境无 pytest，测试框架是 `unittest`）
- 所有命令在仓库根目录 `H:\ok-mxd\ok-mxd` 下执行
- 测试命令：`PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.<module> -v`
- 全量回归：`PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover tests -v`
- 挂机分辨率锁死 **2560x1440**（主循环有帧尺寸守卫），像素常量按此标定，不做缩放换算
- 配置键、日志、注释一律中文，与既有代码保持一致
- **不要运行 `main_debug.py`** —— 它启动时会清空 `screenshots/`（含测试用的 `test_frames`）
- `dataset/images/` 在 `.gitignore` 里，**不入库**；依赖它的测试必须在数据缺失时 skip 而不是 fail
- 每个任务结束时提交；提交信息用英文，结尾加：
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## 实现前必读的两个既有缺陷

两处都是本次实现过程中**实测发现**的既有问题，任务 1 和任务 5 会顺手修掉。若不想改，删掉对应步骤即可，不影响主功能。

**缺陷 A（任务 1 修）：`src/detect/potions.py:62-66` 解析 OCR 结果时多迭代了一层。**
onnxocr 的 `ocr()` 返回 `[[line, line, ...]]`，代码却直接 `for line in ocr_fn(crop)`，于是 `line` 拿到的是整个行列表。实测证据：喂一张含 2 行文本的图，`read_slot_count` 抛 `TypeError: expected string or bytes-like object, got 'list'`；只有 0/1 行时走 `IndexError` 分支被吞掉返回 `None`。
**注意分寸**：修好解析**不等于**药水读数就能用 —— 存档帧里药水格 ROI 本身 OCR 就是 0 行检出。修复的实际价值是消掉一条崩溃路径。`tests/test_potions.py:48` 的 skip 保持原样。

**缺陷 B（任务 5 修）：检测模式在无怪时会以 10Hz 重复检测。**
`src/task/MapleFarmTask.py:160-165` 只在**真的攻击了**才更新 `self._last_attack`，无怪时时间戳不动，于是下一个 0.1s 触发又跑一次 `find_mobs()`。加上本次要引入的 OCR（最坏 235ms），无怪时会持续压主循环。修法：用独立的 `_last_detect` 时间戳给整个检测周期节流。

---

### Task 1: OCR 引擎与结果解析（`ocr_engine.py`）

**Files:**
- Create: `src/detect/ocr_engine.py`
- Modify: `src/detect/potions.py:13-22`（删 `_ocr_instance`/`_get_ocr`）、`:59-71`（改用 `read_texts`）、`:74-76`（`prewarm` 改为再导出）
- Test: `tests/test_ocr_engine.py`

**Interfaces:**
- Produces:
  - `ocr_engine.get_ocr() -> ONNXPaddleOcr`（惰性单例，全项目共用一个模型实例）
  - `ocr_engine.prewarm() -> None`
  - `ocr_engine.TextHit(text: str, conf: float, x0: int, y0: int, x1: int, y1: int)`，带 `cx`/`cy`/`width` 三个 property
  - `ocr_engine.read_texts(image, ocr_fn=None) -> list[TextHit]`，`ocr_fn` 用于注入假 OCR 做离线测试
- Consumes: 无

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_ocr_engine.py`：

```python
import unittest

from src.detect import ocr_engine

# onnxocr 的真实返回形状:外层比直觉多包一层 [[ [多边形, (文本, 置信度)], ... ]]
# 实测样本(2026-08-06,map1_frame_0000 名字牌 ROI):
NESTED = [[
    [[[67.0, 10.0], [196.0, 10.0], [196.0, 43.0], [67.0, 43.0]], ('Yufeng咕咕', 0.996)],
    [[[10.0, 50.0], [180.0, 50.0], [180.0, 80.0], [10.0, 80.0]], ('新手冒险家勋章', 0.981)],
]]
FLAT = NESTED[0]


class TestReadTexts(unittest.TestCase):

    def test_nested_shape(self):
        hits = ocr_engine.read_texts(None, ocr_fn=lambda img: NESTED)
        self.assertEqual([h.text for h in hits], ['Yufeng咕咕', '新手冒险家勋章'])

    def test_flat_shape(self):
        """有的调用方已经拆过一层,两种形状都要吃下,不许再出现 potions 那种 TypeError。"""
        hits = ocr_engine.read_texts(None, ocr_fn=lambda img: FLAT)
        self.assertEqual([h.text for h in hits], ['Yufeng咕咕', '新手冒险家勋章'])

    def test_empty_inputs(self):
        for empty in ([[]], [], None):
            self.assertEqual(ocr_engine.read_texts(None, ocr_fn=lambda img: empty), [])

    def test_geometry(self):
        hit = ocr_engine.read_texts(None, ocr_fn=lambda img: NESTED)[0]
        self.assertEqual((hit.x0, hit.y0, hit.x1, hit.y1), (67, 10, 196, 43))
        self.assertEqual(hit.width, 129)
        self.assertEqual(hit.cx, 131.5)
        self.assertEqual(hit.cy, 26.5)

    def test_junk_lines_ignored(self):
        junk = [['not a line'], [[[0, 0]], ('缺置信度',)], None]
        self.assertEqual(ocr_engine.read_texts(None, ocr_fn=lambda img: junk), [])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_ocr_engine -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'src.detect.ocr_engine'`

- [ ] **Step 3: 实现 `src/detect/ocr_engine.py`**

```python
"""OCR 单例与结果解析。detect 下各模块共用一个模型实例,避免重复加载。"""
from collections import namedtuple

_ocr_instance = None


def get_ocr():
    """惰性创建 onnxocr 实例(离线直读,不走框架 executor)。"""
    global _ocr_instance
    if _ocr_instance is None:
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        _ocr_instance = ONNXPaddleOcr(use_angle_cls=False, use_det=True, use_rec=True, use_openvino=True)
    return _ocr_instance


def prewarm():
    """任务启用时预热模型(加载秒级),避免首次调用卡住 10Hz 触发循环。"""
    get_ocr()


class TextHit(namedtuple('TextHit', 'text conf x0 y0 x1 y1')):
    """一条 OCR 文本及其外接框(像素,相对送进去的那张图)。"""

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2

    @property
    def width(self):
        return self.x1 - self.x0


def _is_line(item):
    """一行 OCR 结果形如 [四点多边形, (文本, 置信度)]。"""
    return (isinstance(item, (list, tuple)) and len(item) == 2
            and isinstance(item[1], (list, tuple)) and len(item[1]) == 2
            and isinstance(item[1][0], str))


def read_texts(image, ocr_fn=None):
    """跑 OCR 并拍平成 [TextHit]。

    onnxocr 的 ocr() 返回 [[line, line, ...]] —— 比直觉多包一层。这里两种形状都吃,
    免得调用方各自踩坑(potions.py 曾因此在 2 行以上时抛 TypeError)。
    ocr_fn 可注入,离线测试不加载模型。
    """
    if ocr_fn is None:
        ocr_fn = lambda img: get_ocr().ocr(img)
    lines = []
    for item in ocr_fn(image) or []:
        if _is_line(item):
            lines.append(item)
        elif isinstance(item, (list, tuple)):
            lines.extend(x for x in item if _is_line(x))
    hits = []
    for poly, (text, conf) in lines:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        hits.append(TextHit(text, float(conf), int(min(xs)), int(min(ys)),
                            int(max(xs)), int(max(ys))))
    return hits
```

- [ ] **Step 4: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_ocr_engine -v
```
Expected: PASS（5 个测试）

- [ ] **Step 5: 让 `potions.py` 改用它（修缺陷 A）**

把 `src/detect/potions.py` 顶部的 `_ocr_instance` / `_get_ocr()` 整段删掉，改成从 `ocr_engine` 导入；`read_slot_count` 的解析循环换成 `read_texts`：

```python
"""快捷栏药水数量读取。格位为帧比例坐标,2560x1440 校准。"""
import re

import cv2

from src.detect.ocr_engine import prewarm, read_texts  # noqa: F401  prewarm 对外再导出

SLOT_ORIGIN = (1746 / 2560, 1171 / 1440)
```

`read_slot_count` 尾部改为：

```python
    # ocr_fn 为 None 时 read_texts 内部退回共享单例,这里原样透传即可
    for hit in read_texts(crop, ocr_fn=ocr_fn):
        count = parse_count(hit.text)
        if count is not None:
            return count
    return None
```

（把原来 `if ocr_fn is None: ocr_fn = lambda ...` 那两行和 `texts = []` 那段 try/except 循环整个删掉。文件末尾的 `prewarm` 函数体也删掉——现在由 Step 5 顶部的导入提供同名符号，`MapleFarmTask.on_create` 里的 `potions.prewarm()` 调用不用改。）

- [ ] **Step 6: 跑全量回归，确认没打破既有测试**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover tests -v
```
Expected: PASS（`tests/test_potions.py:48` 的 `TestReadSlotCountRealFrame` 仍是 skip，不要去掉那个 skip）

- [ ] **Step 7: 提交**

```bash
git add src/detect/ocr_engine.py src/detect/potions.py tests/test_ocr_engine.py
git commit -m "$(cat <<'EOF'
feat: shared OCR engine with correct result parsing

onnxocr returns [[line, ...]] but potions.read_slot_count iterated the
outer wrapper, raising TypeError on 2+ detected lines and silently
returning None otherwise. read_texts() now flattens both shapes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 名字牌锚点识别（`anchor.py`）

**Files:**
- Create: `src/detect/anchor.py`
- Test: `tests/test_anchor.py`

**Interfaces:**
- Consumes: `ocr_engine.read_texts(image, ocr_fn=None) -> list[TextHit]`
- Produces:
  - `anchor.Anchor(x: float, y: float, width: int)` —— 名字牌中心与框宽（全帧坐标）
  - `anchor.search_region(frame_w, frame_h, width_ratio, height_ratio) -> (x0, y0, x1, y1)`
  - `anchor.tiles(region, tile_w=640, tile_h=240, overlap=200) -> list[(x0, y0, x1, y1)]`
  - `anchor.find_in_region(frame, name, region, ocr_fn=None) -> Anchor | None`
  - `anchor.find_in_window(frame, name, center, half_w, half_h, ocr_fn=None) -> Anchor | None`
  - `anchor.body_center(anchor_obj, offset_px) -> (x, y)`
  - 常量 `TILE_W=640`、`TILE_H=240`、`TILE_OVERLAP=200`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_anchor.py`：

```python
import unittest

import numpy as np

from src.detect import anchor

NAME = 'Yufeng咕咕'


def fake_ocr(texts_per_call):
    """按调用次序依次返回各次的文本列表。每个文本给一个固定的局部框 (10,20)-(140,55)。"""
    calls = {'n': 0}

    def _fn(image):
        i = calls['n']
        calls['n'] += 1
        texts = texts_per_call[i] if i < len(texts_per_call) else []
        return [[[[[10.0, 20.0], [140.0, 20.0], [140.0, 55.0], [10.0, 55.0]], (t, 0.99)]
                 for t in texts]]

    _fn.calls = calls
    return _fn


class TestSearchRegion(unittest.TestCase):

    def test_centered_on_frame(self):
        self.assertEqual(anchor.search_region(2560, 1440, 0.30, 0.30), (896, 504, 1664, 936))

    def test_excludes_known_decoys(self):
        """右侧组队列表(x≈2303,y≈1032)与左下状态栏(x≈732,y≈1421)都写着同一个角色名,
        必须落在搜索区外,否则锚点会跳到 HUD 上。"""
        x0, y0, x1, y1 = anchor.search_region(2560, 1440, 0.30, 0.30)
        self.assertFalse(x0 <= 2303 <= x1 and y0 <= 1032 <= y1)
        self.assertFalse(x0 <= 732 <= x1 and y0 <= 1421 <= y1)


class TestTiles(unittest.TestCase):

    def test_overlap_exceeds_name_tag_width(self):
        """名字牌实测宽约 130px。相邻块重叠必须大于它,否则牌子骑边界会被两侧切断
        (实测:重叠 60px 时 40 帧里漏检 9 帧)。"""
        got = anchor.tiles((0, 0, 2000, 240))
        self.assertGreater(len(got), 1)
        overlap = got[0][2] - got[1][0]
        self.assertGreaterEqual(overlap, 130)

    def test_covers_region_edges(self):
        got = anchor.tiles((896, 504, 1664, 936))
        self.assertEqual(min(t[0] for t in got), 896)
        self.assertEqual(max(t[2] for t in got), 1664)
        self.assertEqual(min(t[1] for t in got), 504)
        self.assertEqual(max(t[3] for t in got), 936)

    def test_terminates_when_overlap_ge_tile(self):
        """重叠 >= 块宽会让步长变成 0,必须有下限保护,不能死循环。"""
        got = anchor.tiles((0, 0, 1000, 100), tile_w=200, tile_h=100, overlap=500)
        self.assertLess(len(got), 2000)


class TestFindInWindow(unittest.TestCase):

    def setUp(self):
        self.frame = np.zeros((1440, 2560, 3), np.uint8)

    def test_translates_to_frame_coordinates(self):
        fn = fake_ocr([[NAME]])
        got = anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80, ocr_fn=fn)
        # 窗口原点 (1300-240, 880-80) = (1060, 800);局部框中心 (75, 37.5)
        self.assertEqual((got.x, got.y), (1135.0, 837.5))
        self.assertEqual(got.width, 130)

    def test_rejects_merged_text(self):
        """与邻牌粘连(实测 '小白雪人ifeng咕咕' 宽 212px)会把锚点带偏 100-200px,必须丢弃。"""
        fn = fake_ocr([['小白雪人ifeng咕咕']])
        self.assertIsNone(anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80, ocr_fn=fn))

    def test_rejects_truncated_text(self):
        """被宠物牌遮挡后只剩尾巴(实测 'ng咕咕'),中心右偏,同样丢弃。"""
        fn = fake_ocr([['ng咕咕']])
        self.assertIsNone(anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80, ocr_fn=fn))

    def test_ignores_surrounding_whitespace(self):
        fn = fake_ocr([['  ' + NAME + ' ']])
        self.assertIsNotNone(anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80, ocr_fn=fn))

    def test_clamps_window_to_frame(self):
        """角色贴边时窗口会越界,裁剪不许产生空图或负坐标。"""
        fn = fake_ocr([[NAME]])
        got = anchor.find_in_window(self.frame, NAME, (30, 20), 240, 80, ocr_fn=fn)
        self.assertIsNotNone(got)


class TestFindInRegion(unittest.TestCase):

    def setUp(self):
        self.frame = np.zeros((1440, 2560, 3), np.uint8)
        self.region = (896, 504, 1664, 936)

    def test_returns_first_match_with_global_coordinates(self):
        """第 3 块才命中,坐标必须按第 3 块的原点平移。"""
        boxes = anchor.tiles(self.region)
        self.assertGreaterEqual(len(boxes), 3)
        fn = fake_ocr([[], [], [NAME]])
        got = anchor.find_in_region(self.frame, NAME, self.region, ocr_fn=fn)
        x0, y0 = boxes[2][0], boxes[2][1]
        self.assertEqual((got.x, got.y), (x0 + 75.0, y0 + 37.5))

    def test_returns_none_when_absent(self):
        fn = fake_ocr([])
        self.assertIsNone(anchor.find_in_region(self.frame, NAME, self.region, ocr_fn=fn))


class TestBodyCenter(unittest.TestCase):

    def test_moves_up_from_name_tag(self):
        """名字牌画在角色脚下,身体在它上方(y 更小)。"""
        got = anchor.body_center(anchor.Anchor(1300.0, 880.0, 128), 90)
        self.assertEqual(got, (1300.0, 790.0))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_anchor -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'src.detect.anchor'`

- [ ] **Step 3: 实现 `src/detect/anchor.py`**

```python
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


def search_region(frame_w, frame_h, width_ratio, height_ratio):
    """以画面中心为心的搜索区 (x0, y0, x1, y1)。

    相机跟随角色,角色恒在画面中部;限定中央区还天然排除了两个同名干扰源——
    右侧组队列表(x≈2303)与左下角状态栏(x≈732),它们写着同一个角色名。
    """
    half_w = frame_w * width_ratio / 2
    half_h = frame_h * height_ratio / 2
    cx, cy = frame_w / 2, frame_h / 2
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

    offset_px 必须由 scripts/calibrate_attack_zone.py 实测标定;
    目测得过 82px 与 98px 两个不一致的值,默认 90 只是占位。
    """
    return anchor_obj.x, anchor_obj.y - offset_px
```

- [ ] **Step 4: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_anchor -v
```
Expected: PASS（13 个测试）

- [ ] **Step 5: 提交**

```bash
git add src/detect/anchor.py tests/test_anchor.py
git commit -m "$(cat <<'EOF'
feat: character anchor via name-tag OCR

Tiled OCR over the screen-centre region, accepting only text that exactly
equals the configured character name. Truncated (pet occlusion) and merged
(neighbour tag) reads are dropped - measured to shift the anchor 100-200px.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 40 帧真机回归（判据 A-D）

**Files:**
- Create: `tests/test_anchor_offline.py`

**Interfaces:**
- Consumes: `anchor.find_in_region`、`anchor.search_region`（Task 2）
- Produces: 无（纯验证）

判据取自 spec §7.2，**事先写死，不许跑完再按结果调**。数据源 `dataset/images/train` 未入库（`.gitignore`），缺失时整个测试 skip。

- [ ] **Step 1: 写测试**

创建 `tests/test_anchor_offline.py`：

```python
"""名字牌锚点的真机回归。数据源 dataset/images/train 未入库,缺失则 skip。

判据来自 spec §7.2,基线为 2026-08-06 实测(40 帧):
干净锚点 22/40、y ∈ [738, 888]、扫描中位 118ms / 最大 235ms。
"""
import glob
import os
import time
import unittest

import cv2

from src.detect import anchor

DATASET = os.path.join('dataset', 'images', 'train')
NAME = os.environ.get('OK_MXD_CHAR_NAME', 'Yufeng咕咕')
FRAME_COUNT = 40


def frame_files():
    return sorted(glob.glob(os.path.join(DATASET, '*.png')))[:FRAME_COUNT]


@unittest.skipUnless(len(frame_files()) >= FRAME_COUNT,
                     f'需要 {FRAME_COUNT} 张 {DATASET} 帧(未入库)')
class TestAnchorOnRealFrames(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.results = []
        for path in frame_files():
            frame = cv2.imread(path)
            h, w = frame.shape[:2]
            region = anchor.search_region(w, h, 0.30, 0.30)
            start = time.time()
            hit = anchor.find_in_region(frame, NAME, region)
            cls.results.append((os.path.basename(path), hit, (time.time() - start) * 1000))

    def test_a_clean_hit_rate(self):
        """判据 A:干净锚点命中 >= 20/40(实测基线 22/40)。"""
        hits = [r for r in self.results if r[1] is not None]
        self.assertGreaterEqual(len(hits), 20, f'只命中 {len(hits)}/{len(self.results)}')

    def test_b_anchor_y_in_expected_band(self):
        """判据 B:命中帧的锚点 y 全部落在 [700, 950](实测 738-888)。"""
        for name, hit, _ in self.results:
            if hit is not None:
                self.assertTrue(700 <= hit.y <= 950, f'{name} 锚点 y={hit.y} 越界')

    def test_c_no_merged_boxes(self):
        """判据 C:不许返回粘连框(宽 > 160px)。干净名字牌实测 120-130px。"""
        for name, hit, _ in self.results:
            if hit is not None:
                self.assertLessEqual(hit.width, 160, f'{name} 框宽 {hit.width} 像粘连')

    def test_d_scan_latency(self):
        """判据 D:单帧扫描 <= 400ms(实测中位 118、最大 235)。"""
        worst = max(r[2] for r in self.results)
        self.assertLessEqual(worst, 400, f'最慢 {worst:.0f}ms')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 运行**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_anchor_offline -v
```
Expected: 4 个测试 PASS（首次会加载 OCR 模型，整体约 10-15s）。若 `dataset/images/train` 不在本机，Expected: 全部 skip。

**若判据 A 不过**：不要放宽判据。先用 `scripts/calibrate_attack_zone.py`（Task 6）看图确认角色名配置对不对、角色是否落在中央区外；确认是设计问题再回来改 spec。

- [ ] **Step 3: 提交**

```bash
git add tests/test_anchor_offline.py
git commit -m "$(cat <<'EOF'
test: anchor regression over 40 real frames

Criteria fixed in advance (spec 7.2): >=20/40 clean hits, anchor y within
[700,950], no merged boxes wider than 160px, scan under 400ms.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 攻击区与锚点时效的纯逻辑

**Files:**
- Modify: `src/task/farm_logic.py`（在 `should_attack` 之后追加）
- Test: `tests/test_farm_logic.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `farm_logic.attack_zone(center: tuple, width: float, height: float) -> (x0, y0, x1, y1)`
  - `farm_logic.point_in_zone(point: tuple, zone: tuple) -> bool`
  - `farm_logic.mob_in_zone(mob_centers: list[tuple], zone: tuple) -> bool`
  - `farm_logic.anchor_expired(now: float, anchor_time: float | None, ttl: float) -> bool`
  - `farm_logic.should_rescan_anchor(now: float, last_scan: float, interval: float) -> bool`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_farm_logic.py`（保持文件既有风格，import 已存在则不重复加）：

```python
class TestAttackZone(unittest.TestCase):

    def test_zone_centered(self):
        self.assertEqual(farm_logic.attack_zone((1280, 630), 600, 200),
                         (980.0, 530.0, 1580.0, 730.0))

    def test_point_inside(self):
        zone = farm_logic.attack_zone((1280, 630), 600, 200)
        self.assertTrue(farm_logic.point_in_zone((1280, 630), zone))

    def test_point_on_edge_counts_as_inside(self):
        zone = farm_logic.attack_zone((1280, 630), 600, 200)
        self.assertTrue(farm_logic.point_in_zone((980.0, 530.0), zone))
        self.assertTrue(farm_logic.point_in_zone((1580.0, 730.0), zone))

    def test_point_outside(self):
        zone = farm_logic.attack_zone((1280, 630), 600, 200)
        self.assertFalse(farm_logic.point_in_zone((1581.0, 630), zone))
        self.assertFalse(farm_logic.point_in_zone((1280, 529.0), zone))

    def test_mob_in_zone_any(self):
        zone = farm_logic.attack_zone((1280, 630), 600, 200)
        self.assertTrue(farm_logic.mob_in_zone([(100, 100), (1300, 640)], zone))

    def test_mob_in_zone_none(self):
        zone = farm_logic.attack_zone((1280, 630), 600, 200)
        self.assertFalse(farm_logic.mob_in_zone([(100, 100), (2400, 1300)], zone))

    def test_no_mobs(self):
        zone = farm_logic.attack_zone((1280, 630), 600, 200)
        self.assertFalse(farm_logic.mob_in_zone([], zone))


class TestAnchorTiming(unittest.TestCase):

    def test_never_acquired_counts_as_expired(self):
        self.assertTrue(farm_logic.anchor_expired(100.0, None, 10))

    def test_fresh_anchor(self):
        self.assertFalse(farm_logic.anchor_expired(105.0, 100.0, 10))

    def test_expired_anchor(self):
        self.assertTrue(farm_logic.anchor_expired(111.0, 100.0, 10))

    def test_rescan_throttle(self):
        self.assertFalse(farm_logic.should_rescan_anchor(101.0, 100.0, 2))
        self.assertTrue(farm_logic.should_rescan_anchor(102.0, 100.0, 2))
```

- [ ] **Step 2: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_logic -v
```
Expected: FAIL —— `AttributeError: module 'src.task.farm_logic' has no attribute 'attack_zone'`

- [ ] **Step 3: 实现**

追加到 `src/task/farm_logic.py`：

```python
def attack_zone(center, width, height):
    """以 center 为心的攻击区 (x0, y0, x1, y1)。左右对称,不分朝向。"""
    cx, cy = center
    return cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2


def point_in_zone(point, zone):
    x, y = point
    x0, y0, x1, y1 = zone
    return x0 <= x <= x1 and y0 <= y <= y1


def mob_in_zone(mob_centers, zone):
    """怪物检测框中心落入攻击区即算可攻击。"""
    return any(point_in_zone(c, zone) for c in mob_centers)


def anchor_expired(now, anchor_time, ttl):
    """锚点是否过期。从没拿到过锚点(None)同样算过期。"""
    return anchor_time is None or now - anchor_time > ttl


def should_rescan_anchor(now, last_scan, interval):
    return now - last_scan >= interval
```

- [ ] **Step 4: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_logic -v
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/task/farm_logic.py tests/test_farm_logic.py
git commit -m "$(cat <<'EOF'
feat: attack-zone and anchor-timing pure logic

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 接线到 `MapleFarmTask`（含缺陷 B）

**Files:**
- Modify: `src/task/MapleFarmTask.py:13-32`（配置）、`:39-46`（`__init__`）、`:48-60`（`_reset_state`）、`:67-70`（`on_create`）、`:72-83`（删 `_mob_in_attack_zone`）、`:159-168`（攻击分支）
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: `anchor.search_region/find_in_region/find_in_window/body_center/Anchor`、`farm_logic.attack_zone/mob_in_zone/anchor_expired/should_rescan_anchor`、`ocr_engine.prewarm`、`BaseMapleTask.find_mobs(frame) -> list[Box]`（`Box` 有 `.x/.y/.width/.height`）
- Produces: `MapleFarmTask._resolve_anchor(frame, now, cfg) -> (anchor.Anchor, str)`，第二个返回值是来源标签 `'window' | 'region' | 'cached' | 'fallback'`（供日志与标定脚本用）

- [ ] **Step 1: 写失败的测试**

改 `tests/test_farm_task_offline.py`。先在 `make_task()` 里加一行默认桩（放在 `task.get_global_config = ...` 之前），避免检测模式下真去调 YOLO：

```python
    task.find_mobs = MagicMock(return_value=[])
```

把既有的 `test_full_hp_attacks_only` 改成显式定频（它测的是"满血只攻击"，与检测无关）：

```python
    def test_full_hp_attacks_only(self):
        task = make_task(**{'攻击模式': '定频'})
        run_with_frame(task)
        self.assertIn(call('shift'), task.send_key.call_args_list)
        task.stop_farming.assert_not_called()
```

既有的三个检测模式测试（`test_detect_mode_attacks_when_mob_in_zone` / `_idles_when_no_mob` / `_idles_when_mob_outside_zone`）保留，但要按新的默认攻击区核对坐标：`角色名` 留空 → 锚点 = 屏幕中心 (1280, 720) → 身体中心 (1280, 630) → 攻击区 x[980,1580]、y[530,730]。原用例的怪中心 (1230, 725) 仍在区内、(40, 35) 仍在区外，断言不用改。

再追加：

```python
class TestDetectModeAnchor(unittest.TestCase):

    def test_no_char_name_uses_screen_centre(self):
        """角色名留空 → 不跑 OCR,直接用屏幕中心当锚点。"""
        task = make_task(**{'攻击模式': '检测', '角色名': ''})
        with patch('src.task.MapleFarmTask.anchor.find_in_region') as scan:
            run_with_frame(task)
            scan.assert_not_called()

    def test_no_mob_does_not_stop_task(self):
        """用户明确要求:没怪只停手,任务继续跑。"""
        task = make_task(**{'攻击模式': '检测'})
        task.find_mobs = MagicMock(return_value=[])
        run_with_frame(task)
        task.send_key.assert_not_called()
        task.stop_farming.assert_not_called()

    def test_detection_is_throttled_when_idle(self):
        """无怪时不许每个 0.1s 触发都重跑检测(缺陷 B)。同一时刻连跑 5 次,只应检测 1 次。"""
        task = make_task(**{'攻击模式': '检测'})
        task.find_mobs = MagicMock(return_value=[])
        for _ in range(5):
            run_with_frame(task)
        self.assertEqual(task.find_mobs.call_count, 1)

    def test_anchor_from_window_then_cached(self):
        """快通道命中后记住锚点;下一拍快通道失灵且慢通道被节流时,沿用上次锚点。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        hit = MapleAnchor(1400.0, 900.0, 128)
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=hit), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            run_with_frame(task)
        self.assertEqual(task._anchor, (1400.0, 900.0))

    def test_expired_anchor_falls_back_to_centre(self):
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕', '锚点保鲜(秒)': 5})
        task._anchor = (400.0, 400.0)
        task._anchor_time = 90.0  # run_with_frame 把 time.time() 固定在 100.0,已超 5s
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, source = task._resolve_anchor(cv2.imread(FRAME), 100.0, task.config)
        self.assertEqual(source, 'fallback')
        self.assertEqual((got.x, got.y), (1280.0, 720.0))
```

文件顶部补 import：

```python
from src.detect.anchor import Anchor as MapleAnchor
```

- [ ] **Step 2: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v
```
Expected: FAIL（`KeyError: '角色名'` 或 `AttributeError: _resolve_anchor`）

- [ ] **Step 3: 改配置与状态**

`src/task/MapleFarmTask.py` 顶部 import 补：

```python
from src.detect import anchor, bars, guards, ocr_engine, potions
```
（原来的 `from src.detect import bars, guards, potions` 整行替换）

`DEFAULT_CONFIG` 里删掉 `'攻击区宽'`、`'攻击区高'`、`'攻击区中心X'`、`'攻击区中心Y'` 四行，`'攻击模式'` 改默认值并追加新键：

```python
    '攻击模式': '检测',
    '角色名': '',
    '攻击区宽(像素)': 600,
    '攻击区高(像素)': 200,
    '名字牌到身体偏移(像素)': 90,
    '锚点搜索区宽(比例)': 0.30,
    '锚点搜索区高(比例)': 0.30,
    '锚点刷新间隔(秒)': 2,
    '锚点保鲜(秒)': 10,
```

在 `CALIBRATED_SIZE` 下面加模块常量：

```python
FAST_HALF_W = 240        # 快通道搜索窗半宽(像素)
FAST_HALF_H = 80         # 快通道搜索窗半高
FALLBACK_WARN_INTERVAL = 60   # 回退屏幕中心的告警最小间隔(秒),防刷屏
```

`__init__` 里 `self.default_config.update(DEFAULT_CONFIG)` 之后加：

```python
        self.config_type['攻击模式'] = {'type': 'drop_down', 'options': ['定频', '检测']}
        self.config_description.update({
            '角色名': '检测模式用它 OCR 定位角色(名字牌)。留空则攻击区锚在画面中心',
            '攻击区宽(像素)': '2560x1440 下标定。用 scripts/calibrate_attack_zone.py 看图调',
            '名字牌到身体偏移(像素)': '名字牌在角色脚下,该值是牌子中心到身体中心的距离',
        })
```

`_reset_state` 里追加：

```python
        self._anchor = None            # (x, y) 名字牌中心,全帧坐标
        self._anchor_time = None
        self._last_anchor_scan = 0.0
        self._last_detect = 0.0
        self._last_fallback_warn = 0.0
```

`on_create` 追加 OCR 预热（检测模式且配了角色名时）：

```python
    def on_create(self):
        super().on_create()
        if self.config.get('药水耗尽保护'):
            potions.prewarm()
        if self.config.get('攻击模式') == '检测' and (self.config.get('角色名') or '').strip():
            ocr_engine.prewarm()
```

- [ ] **Step 4: 用 `_resolve_anchor` 替换 `_mob_in_attack_zone`**

删掉 `_mob_in_attack_zone` 静态方法整段（原 `:72-83`），换成：

```python
    def _resolve_anchor(self, frame, now, cfg):
        """按四级阶梯拿角色锚点,返回 (Anchor, 来源标签)。任何一级都不停任务。

        快通道(上次锚点附近小窗) → 慢通道(中央区分块,节流) → 沿用上次 → 回退屏幕中心。
        """
        h, w = frame.shape[:2]
        centre = anchor.Anchor(w / 2.0, h / 2.0, 0)
        name = (cfg['角色名'] or '').strip()
        if not name:
            return centre, 'fallback'

        if self._anchor is not None:
            hit = anchor.find_in_window(frame, name, self._anchor, FAST_HALF_W, FAST_HALF_H)
            if hit is not None:
                self._anchor, self._anchor_time = (hit.x, hit.y), now
                return hit, 'window'

        if farm_logic.should_rescan_anchor(now, self._last_anchor_scan, cfg['锚点刷新间隔(秒)']):
            self._last_anchor_scan = now
            region = anchor.search_region(w, h, cfg['锚点搜索区宽(比例)'], cfg['锚点搜索区高(比例)'])
            hit = anchor.find_in_region(frame, name, region)
            if hit is not None:
                self._anchor, self._anchor_time = (hit.x, hit.y), now
                return hit, 'region'

        if not farm_logic.anchor_expired(now, self._anchor_time, cfg['锚点保鲜(秒)']):
            return anchor.Anchor(self._anchor[0], self._anchor[1], 0), 'cached'

        if now - self._last_fallback_warn >= FALLBACK_WARN_INTERVAL:
            self._last_fallback_warn = now
            self.log_warning(f'{cfg["锚点保鲜(秒)"]}s 未定位到角色「{name}」,攻击区暂锚在画面中心')
        return centre, 'fallback'
```

- [ ] **Step 5: 改攻击分支（含缺陷 B 的节流修复）**

把原 `:159-168` 的第 4 步整段替换为：

```python
        # 4. 攻击
        if cfg['攻击模式'] == '检测':
            # 节流用独立的 _last_detect:无怪时不更新 _last_attack,否则 10Hz 每拍都要跑
            # 一遍 OCR + YOLO(旧代码的行为)
            if farm_logic.should_attack(now, self._last_detect, cfg['攻击间隔(秒)']):
                self._last_detect = now
                anchor_hit, source = self._resolve_anchor(frame, now, cfg)
                body = anchor.body_center(anchor_hit, cfg['名字牌到身体偏移(像素)'])
                zone = farm_logic.attack_zone(body, cfg['攻击区宽(像素)'], cfg['攻击区高(像素)'])
                centres = [(m.x + m.width / 2, m.y + m.height / 2) for m in self.find_mobs(frame)]
                if farm_logic.mob_in_zone(centres, zone):
                    self.send_key(keys['攻击键'])
                    self._last_attack = now
        elif farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)']):
            self.send_key(keys['攻击键'])
            self._last_attack = now
```

- [ ] **Step 6: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v
```
Expected: PASS（含新增 5 个）

- [ ] **Step 7: 全量回归**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover tests -v
```
Expected: PASS，无 ERROR。（`configs/MapleFarmTask.json` 里残留的旧比例键无害，框架按 `default_config` 取值，不要手改那个文件——它是运行时生成的。）

- [ ] **Step 8: 提交**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "$(cat <<'EOF'
feat: gate attacks on mobs inside a character-anchored zone

Detect mode is now the default and the attack zone follows the character
via the name-tag anchor, falling back to screen centre when the anchor
goes stale. No-mob means hold fire - the task keeps running.

Also fixes detection re-running at 10Hz while idle: the previous code only
advanced _last_attack when it actually attacked.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 标定工具

**Files:**
- Create: `scripts/calibrate_attack_zone.py`

**Interfaces:**
- Consumes: `anchor.search_region/find_in_region/body_center`、`farm_logic.attack_zone/point_in_zone`、`src.OpenVinoYolo8Detect.OpenVinoYolo8Detect(weights=..., model_h=1280, model_w=1280).detect(image, threshold=0.5, label=0) -> list[Box]`
- Produces: 一张标注 PNG（默认写到 `screenshots/calibrate_attack_zone.png`）

这是给人看的工具，不写自动化测试；验收方式是 Step 3 的肉眼检查。

- [ ] **Step 1: 实现**

创建 `scripts/calibrate_attack_zone.py`：

```python
"""攻击区标定:把锚点、身体中心、攻击区、怪框画到一张图上,肉眼调参数。

用法(仓库根目录):
  "H:/ok-mxd/data/apps/ok-ww/python/python.exe" scripts/calibrate_attack_zone.py \
      --frame screenshots/test_frames/training_ground_full_2560x1440.png \
      --name Yufeng咕咕 --width 600 --height 200 --offset 90

看图调三个参数:
  --offset  名字牌到身体中心的距离(青色竖线的长度)
  --width/--height  攻击区(黄框)。目标是刚好覆盖你打得到的范围
调好后把值填进 GUI 的「攻击区宽/高(像素)」「名字牌到身体偏移(像素)」。
"""
import argparse
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.detect import anchor  # noqa: E402
from src.task import farm_logic  # noqa: E402

WEIGHTS = os.path.join('assets', 'mob_model', 'mob.onnx')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--frame', required=True)
    p.add_argument('--name', default='')
    p.add_argument('--width', type=float, default=600)
    p.add_argument('--height', type=float, default=200)
    p.add_argument('--offset', type=float, default=90)
    p.add_argument('--region-w', type=float, default=0.30)
    p.add_argument('--region-h', type=float, default=0.30)
    p.add_argument('--out', default=os.path.join('screenshots', 'calibrate_attack_zone.png'))
    args = p.parse_args()

    frame = cv2.imread(args.frame)
    if frame is None:
        raise SystemExit(f'读不到帧: {args.frame}')
    h, w = frame.shape[:2]
    canvas = frame.copy()

    region = anchor.search_region(w, h, args.region_w, args.region_h)
    cv2.rectangle(canvas, (region[0], region[1]), (region[2], region[3]), (255, 128, 0), 2)
    cv2.putText(canvas, 'search region', (region[0] + 6, region[1] + 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 128, 0), 2)

    hit = anchor.find_in_region(frame, args.name, region) if args.name.strip() else None
    if hit is None:
        print(f'未定位到角色名「{args.name}」,退回画面中心')
        hit = anchor.Anchor(w / 2.0, h / 2.0, 0)
    else:
        print(f'锚点 x={hit.x:.0f} y={hit.y:.0f} 框宽={hit.width}')
        cv2.rectangle(canvas, (int(hit.x - hit.width / 2), int(hit.y - 20)),
                      (int(hit.x + hit.width / 2), int(hit.y + 20)), (0, 0, 255), 2)

    body = anchor.body_center(hit, args.offset)
    cv2.line(canvas, (int(hit.x), int(hit.y)), (int(body[0]), int(body[1])), (255, 255, 0), 2)
    cv2.circle(canvas, (int(body[0]), int(body[1])), 6, (255, 255, 0), -1)

    zone = farm_logic.attack_zone(body, args.width, args.height)
    cv2.rectangle(canvas, (int(zone[0]), int(zone[1])), (int(zone[2]), int(zone[3])), (0, 255, 255), 3)

    from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect
    boxes = OpenVinoYolo8Detect(weights=WEIGHTS, model_h=1280, model_w=1280).detect(
        frame, threshold=0.5, label=0)
    inside = 0
    for b in boxes:
        centre = (b.x + b.width / 2, b.y + b.height / 2)
        hot = farm_logic.point_in_zone(centre, zone)
        inside += hot
        colour = (0, 255, 0) if hot else (128, 128, 128)
        cv2.rectangle(canvas, (b.x, b.y), (b.x + b.width, b.y + b.height), colour, 2)
        cv2.circle(canvas, (int(centre[0]), int(centre[1])), 4, colour, -1)
    print(f'怪 {len(boxes)} 只,区内 {inside} 只')

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    cv2.imwrite(args.out, canvas)
    print('已写出', args.out)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 在存档帧上跑一次**

```bash
cd H:/ok-mxd/ok-mxd && PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" scripts/calibrate_attack_zone.py --frame screenshots/test_frames/training_ground_full_2560x1440.png --name "Yufeng咕咕"
```
Expected: 打印锚点坐标与「怪 N 只，区内 M 只」，写出 `screenshots/calibrate_attack_zone.png`

- [ ] **Step 3: 看图核对（这是本任务的验收）**

打开输出的 PNG，确认：红框套住的是**角色本人的名字牌**（不是宠物「小白雪人」、不是别的玩家）；青色竖线的顶端落在角色身体上 —— 若明显偏高/偏低，调 `--offset` 重跑，把最终值记下来填进 GUI。

- [ ] **Step 4: 提交**

```bash
git add scripts/calibrate_attack_zone.py
git commit -m "$(cat <<'EOF'
feat: attack-zone calibration script

Draws the search region, name-tag anchor, body centre, attack zone and
detected mobs onto one frame so the pixel parameters can be eyeballed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 文档与实弹验收

**Files:**
- Modify: `README.md:38`、`README.md:52`（现在描述的是比例制攻击区，已过时）
- Modify: `docs/superpowers/specs/2026-08-06-attack-zone-mob-gating-design.md`（回填实测值）

**Interfaces:**
- Consumes: Task 5 的配置键名、Task 6 的脚本用法
- Produces: 无

- [ ] **Step 1: 更新 README**

把 `README.md:38` 那条替换为：

```markdown
- 检测模式默认开启，攻击区锚定角色本人：需要在任务配置里填「角色名」（与游戏内完全一致），程序用 OCR 找角色脚下的名字牌定位。留空则攻击区锚在画面中心。
- 攻击区用像素标定：`scripts/calibrate_attack_zone.py --frame <截图> --name <角色名>` 会输出一张标注图，看图调「攻击区宽/高(像素)」与「名字牌到身体偏移(像素)」。
```

把 `README.md:52` 的排障条目替换为：

```markdown
3. **检测模式不攻击** → 按顺序查：①「角色名」是否与游戏内完全一致；②跑一次标定脚本看红框有没有套住自己的名字牌；③日志里若反复出现「未定位到角色」，说明角色不在画面中央搜索区内（贴地图边缘站桩会这样），可调大「锚点搜索区宽/高(比例)」；④攻击区是否太小。
```

- [ ] **Step 2: 回填 spec 里的待验证项**

把 spec §3.4 里已经由 Task 6 标定出来的值填回去（`名字牌到身体偏移`、`攻击区宽/高` 的实测值），并把 §4.2 里标着「耗时未实测」的快通道补上实测数字。**只填真跑出来的数**，没测的继续标着待验证。

- [ ] **Step 3: 提交文档**

```bash
git add README.md docs/superpowers/specs/2026-08-06-attack-zone-mob-gating-design.md
git commit -m "$(cat <<'EOF'
docs: attack-zone calibration workflow and measured values

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: 实弹验收（需要人操作，agent 跑不了）**

前置：**管理员提权**运行（PyDirect 按键必须提权，见上游 spec）、游戏前台、分辨率 2560x1440、任务配置里已填「角色名」。

逐条核对 spec §7.3 的判据，**每条都要有证据，不许凭感觉**：

- **E**：站在无怪处挂机 60s，`logs/ok-mxd.log` 里攻击键发送次数 = 0
- **F**：怪进入攻击区后 3s 内发出攻击键
- **G**：标定图上锚点红框套住角色本人
- **H**：开检测模式挂机 10 分钟，喝药行为与定频模式无差异（确认 OCR 阻塞没拖慢保命）

E/F/G/H 全过之前，不得声称功能可用。任何一条不过，回到对应任务修，不要放宽判据。

---

## 计划自查

**规格覆盖**：spec §4.1 判定链 → Task 5；§4.2 四级阶梯 → Task 5 `_resolve_anchor`；§4.3 收货判据 → Task 2 `_scan` + Task 2 的拒收测试；§4.4 攻击区 → Task 4 + Task 5；§4.5 配置变更 → Task 5 Step 3；§4.6 性能预算 → Task 3 判据 D + Task 7 判据 H；§5 代码结构 → Task 1/2/4/5/6 逐文件对应；§6 标定工具 → Task 6；§7.1 离线单测 → Task 2/4/5；§7.2 帧回归 → Task 3；§7.3 实弹 → Task 7 Step 4；§8 不做项 → 计划中无对应任务（正确）。

**类型一致性**：`anchor.Anchor` 三字段 `(x, y, width)` 贯穿 Task 2/5/6；`body_center` 收 `Anchor` 返回 `(x, y)` 二元组，`attack_zone` 收 `(x, y)` 返回四元组，`mob_in_zone` 收中心点列表 —— 调用链在 Task 5 Step 5 里闭合。`self._anchor` 存的是 `(x, y)` 二元组（不是 `Anchor`），Task 5 里从缓存重建 `Anchor` 时 `width` 补 0，因为宽度只在识别当次有意义。
