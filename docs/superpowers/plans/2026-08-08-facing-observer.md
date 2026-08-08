# 朝向观测器（只读）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在决策日志里把角色的**真实朝向**（模板匹配读出）与**信念朝向**（`_facing`）并排写出来，不改变任何决策行为，从而第一次拿到「信念与现实的分叉率」这个数字。

**Architecture:** 三层，边界与现有 `anchor.py` / `bars.py` 一致。`src/detect/facing.py` 做 CV（裁 ROI、双向 `matchTemplate`、按阈值出朝向或弃权）；`src/task/farm_logic.py` 加一个纯判定函数（走动确认，用来无循环论证地标定模板朝向）；`MapleFarmTask` 只负责接线与写日志。观测结果**永不写回 `_facing`**，不参与任何决策。

**Tech Stack:** Python 3.11（嵌入式），OpenCV（`cv2.matchTemplate` / `TM_CCOEFF_NORMED`），NumPy，unittest。

**上游 spec:** `docs/superpowers/specs/2026-08-08-facing-observer-design.md`（判据、ROI 几何、阈值全部出自这里，实现时不要自行改动）

## Global Constraints

- **Python 只能用** `H:\ok-mxd\data\apps\ok-ww\python\python.exe`，**禁止 `pip install`**
- **测试命令**：`PYTHONUTF8=1 <python> -m unittest discover -s tests`（AGENTS.md:334 是合入门）。**不是 pytest**，嵌入式 python 没装
- **当前基线：`Ran 334 tests, OK (skipped=4)`**。任何任务结束时必须仍然全绿，且总数只增不减
- **跑测试前必须恢复测试帧**（每次跑 GUI 都会把它删掉，会造成 30+ 个与本改动无关的假失败）：
  ```bash
  mkdir -p screenshots/test_frames && cp ../_frames_backup/training_ground_full_2560x1440.png screenshots/test_frames/
  ```
- **`src/detect/*` 与 `src/task/farm_logic.py` 不参与热重载**（`ok/gui/tasks/TaskManger.py` 只重载任务模块自身，不递归依赖）。改了必须**重启 GUI**，否则新任务代码 + 旧依赖 = `AttributeError`。2026-08-08 10:23 已经踩过一次
- **禁止绝对路径**（AGENTS.md §11）。所有路径相对仓库根 `H:\ok-mxd\ok-mxd`
- **阈值 `0.70` / `0.20` 与 ROI 几何照抄 spec §3.2，不许调**。它们来自 2026-08-07 附录 A 的 24 帧实测（命中最低 0.78 vs 弃权最高 0.45，裕度很大）
- **观测结果不得写回 `_facing`，不得参与任何决策分支。** 这是本设计的核心约束，Task 5 的 `test_observation_never_writes_facing` 专门守着它
- 中文注释/日志，与现有代码风格一致

---

### Task 1: `farm_logic.walk_confirmed` —— 无循环论证地确定朝向

模板自带一个朝向，`s > s_flip` 只说明「与模板同向」。要换算成 L/R 就必须知道模板本身朝哪边，而**不能用 `_facing` 标定**（那正是被检验的对象）。改用位移观测：寻怪时是长按方向键连续走，如果 `body_x` 真的沿按键方向移动了，角色必定面朝那边。

**Files:**
- Modify: `src/task/farm_logic.py`（在 `knockback_debounced` 之后新增）
- Test: `tests/test_farm_logic.py`

**Interfaces:**
- Consumes: 无
- Produces: `farm_logic.walk_confirmed(seek_dir, body_x_start, body_x_now, min_dx) -> bool`
  - `seek_dir`: `'left'` / `'right'` / `None`
  - `body_x_start`: 本次长按按下那一拍的 `body_x`（float），`None` = 没记上
  - `body_x_now`: 当前拍的 `body_x`（float）
  - `min_dx`: 位移阈值（float，像素）

- [ ] **Step 1: 写失败的测试**

加到 `tests/test_farm_logic.py` 的 `TestFarmLogic` 类里：

```python
    def test_walk_confirmed(self):
        # 按右键且真的往右走够了 → 确认朝右
        self.assertTrue(fl.walk_confirmed('right', 1000.0, 1045.0, 40))
        # 位移不够 → 不确认(可能只是锚点抖动)
        self.assertFalse(fl.walk_confirmed('right', 1000.0, 1030.0, 40))
        # 按右键却往左动 = 撞墙/锚点跳变,绝不能据此标定
        self.assertFalse(fl.walk_confirmed('right', 1000.0, 955.0, 40))
        # 按左键且真的往左走够了
        self.assertTrue(fl.walk_confirmed('left', 1000.0, 955.0, 40))
        self.assertFalse(fl.walk_confirmed('left', 1000.0, 1045.0, 40))
        # 没在寻怪 / 没记起点 → 一律不确认
        self.assertFalse(fl.walk_confirmed(None, 1000.0, 1045.0, 40))
        self.assertFalse(fl.walk_confirmed('right', None, 1045.0, 40))
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_logic -v 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: module 'src.task.farm_logic' has no attribute 'walk_confirmed'`

- [ ] **Step 3: 写最小实现**

加到 `src/task/farm_logic.py`（放在 `knockback_debounced` 之后）：

```python
def walk_confirmed(seek_dir, body_x_start, body_x_now, min_dx):
    """走动确认:角色真的沿按键方向走了 min_dx 像素以上 → 它必定面朝那边。

    这是给朝向模板采集用的**位移观测**,不是信念。用 `_facing` 去标定模板等于
    循环论证——模板正是用来检验 `_facing` 的(见 spec §3.3)。

    反向位移(按右键却往左动)一律不确认:那是撞墙、被击退、或锚点跳变,
    据此标定会把模板朝向记反,后面所有观测全错。
    seek_dir 为 None(没在寻怪)或 body_x_start 为 None(没记上起点)→ 不确认。
    """
    if seek_dir not in ('left', 'right') or body_x_start is None:
        return False
    dx = body_x_now - body_x_start
    return dx >= min_dx if seek_dir == 'right' else -dx >= min_dx
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_logic -v 2>&1 | tail -5
```

Expected: OK

- [ ] **Step 5: 全量回归**

```bash
mkdir -p screenshots/test_frames && cp ../_frames_backup/training_ground_full_2560x1440.png screenshots/test_frames/
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
```

Expected: `Ran 341 tests, OK (skipped=4)`（334 + 本次新增，允许总数更大）

- [ ] **Step 6: 提交**

```bash
git add src/task/farm_logic.py tests/test_farm_logic.py
git commit -m "feat: farm_logic.walk_confirmed —— 用位移观测确认朝向,给模板采集标定用

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `facing.decide` —— 判定逻辑（纯函数，不碰帧）

**Files:**
- Create: `src/detect/facing.py`
- Test: `tests/test_facing.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - 常量 `FACING_SCORE_MIN = 0.70`、`FACING_MARGIN_MIN = 0.20`
  - `facing.decide(s, s_flip, template_facing) -> 'LEFT' | 'RIGHT' | None`
    - `s`: 模板原图的最大匹配分（float）
    - `s_flip`: 模板水平镜像的最大匹配分（float）
    - `template_facing`: 模板自身的朝向，`'LEFT'` 或 `'RIGHT'`
    - 返回 `None` = 弃权

- [ ] **Step 1: 写失败的测试**

新建 `tests/test_facing.py`：

```python
import unittest

from src.detect import facing


class TestFacingDecide(unittest.TestCase):
    """判据照抄 2026-08-07 附录 A:max(s,s_flip) >= 0.70 且 |s-s_flip| >= 0.20。

    不测阈值的精确边界:0.70/0.20 在 IEEE754 下的边界断言会随字面量写法漂移
    (2026-08-07 spec §7.1 已经在 hp_drop 上踩过同样的坑)。只测明确在两侧的值。
    """

    def test_same_direction_as_template(self):
        # 附录 A 的典型命中:胜出分 0.88、差值 0.41
        self.assertEqual(facing.decide(0.88, 0.47, 'RIGHT'), 'RIGHT')
        self.assertEqual(facing.decide(0.88, 0.47, 'LEFT'), 'LEFT')

    def test_opposite_direction_to_template(self):
        self.assertEqual(facing.decide(0.47, 0.88, 'RIGHT'), 'LEFT')
        self.assertEqual(facing.decide(0.47, 0.88, 'LEFT'), 'RIGHT')

    def test_abstain_when_score_too_low(self):
        """两边都不像:宠物挡住/切边。附录 A 的 4 个弃权帧就长这样(最高 0.45)。"""
        self.assertIsNone(facing.decide(0.45, 0.40, 'RIGHT'))

    def test_abstain_when_margin_too_small(self):
        """分高但两边差不多:分不出朝向,宁可不答也不答错。"""
        self.assertIsNone(facing.decide(0.85, 0.80, 'RIGHT'))

    def test_abstain_on_bad_template_facing(self):
        """模板朝向未知/非法 → 弃权,不猜。"""
        self.assertIsNone(facing.decide(0.88, 0.47, None))
        self.assertIsNone(facing.decide(0.88, 0.47, 'UP'))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_facing -v 2>&1 | tail -20
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.detect.facing'`

- [ ] **Step 3: 写最小实现**

新建 `src/detect/facing.py`：

```python
"""角色朝向观测:用头+肩模板与其水平镜像各匹配一次,谁分高就朝哪边。

只读观测器 —— 结果只进日志,不写回 `_facing`、不参与任何决策(spec §3.4)。
造它的原因见 spec §1:`_facing` 是纯信念,项目在它上面改了四轮,三条记为无效、
一条实测有害,共同点是没有尺子。

可行性与阈值出自 2026-08-07 附录 A 的 24 帧实测:20/24 命中、0 误判、4 弃权
(弃权全是宠物「小白雪人」挡住或角色被 ROI 切边),胜出分中位 0.883、差值中位
0.411,命中帧胜出分最低 0.78 而弃权帧最高 0.45 —— 裕度很大,阈值不要动。
弃权是这个仪器最值钱的性质:宁可不答,不许答错。
"""

FACING_SCORE_MIN = 0.70   # 胜出分下界:低于此说明两边都不像(挡住/切边)
FACING_MARGIN_MIN = 0.20  # 两分差值下界:低于此说明分不出朝向


def decide(s, s_flip, template_facing):
    """(模板分, 镜像分, 模板自身朝向) → 'LEFT' / 'RIGHT' / None(弃权)。

    s > s_flip → 与模板同向;否则反向。模板朝向未知/非法一律弃权,不猜。
    """
    if template_facing not in ('LEFT', 'RIGHT'):
        return None
    if max(s, s_flip) < FACING_SCORE_MIN:
        return None
    if abs(s - s_flip) < FACING_MARGIN_MIN:
        return None
    same = s > s_flip
    if same:
        return template_facing
    return 'RIGHT' if template_facing == 'LEFT' else 'LEFT'
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_facing -v 2>&1 | tail -5
```

Expected: OK（5 个用例）

- [ ] **Step 5: 提交**

```bash
git add src/detect/facing.py tests/test_facing.py
git commit -m "feat: facing.decide —— 朝向判定纯函数,阈值照抄附录 A

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: ROI 裁剪与双向匹配（碰帧的部分）

**Files:**
- Modify: `src/detect/facing.py`
- Test: `tests/test_facing.py`

**Interfaces:**
- Consumes: `facing.decide`（Task 2）
- Produces:
  - 常量 `ROI_HALF_W = 90`、`ROI_TOP_DY = 160`、`ROI_BOTTOM_DY = 20`
  - `facing.roi_box(frame_shape, anchor_obj) -> (x0, y0, x1, y1) | None`
  - `facing.crop_roi(frame, anchor_obj) -> np.ndarray(灰度) | None`
  - `facing.scores(roi_gray, template) -> (s, s_flip)`
  - `facing.observe(frame, anchor_obj, template, template_facing) -> (朝向, s, s_flip)`
    朝向为 `'LEFT'`/`'RIGHT'`/`None`；无法计算时返回 `(None, 0.0, 0.0)`

ROI 几何照抄 spec §3.2 / 附录 A.1：`x ∈ [a.x−90, a.x+90]`，`y ∈ [a.y−160, a.y−20]`，即 180×140。

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_facing.py`：

```python
import numpy as np

from src.detect import anchor


class TestFacingRoi(unittest.TestCase):

    def _frame(self, h=1440, w=2560):
        return np.zeros((h, w, 3), dtype=np.uint8)

    def test_roi_box_geometry(self):
        """照抄附录 A.1:x ±90,y 从 a.y-160 到 a.y-20,共 180x140。"""
        a = anchor.Anchor(1280.0, 880.0, 130)
        box = facing.roi_box(self._frame().shape, a)
        self.assertEqual(box, (1190, 720, 1370, 860))
        x0, y0, x1, y1 = box
        self.assertEqual((x1 - x0, y1 - y0), (180, 140))

    def test_roi_box_none_when_clipped_at_edge(self):
        """角色贴屏幕边缘 → ROI 会被切,宁可不观测也不要半张脸(附录 A 的 #0
        就是切边弃权)。返回 None,不抛。"""
        self.assertIsNone(facing.roi_box(self._frame().shape,
                                         anchor.Anchor(20.0, 880.0, 130)))
        self.assertIsNone(facing.roi_box(self._frame().shape,
                                         anchor.Anchor(1280.0, 100.0, 130)))

    def test_crop_roi_returns_grayscale(self):
        a = anchor.Anchor(1280.0, 880.0, 130)
        roi = facing.crop_roi(self._frame(), a)
        self.assertEqual(roi.shape, (140, 180))   # 灰度,无通道维

    def test_scores_detects_mirror(self):
        """构造一个左右不对称的图案:原图应当明显赢过镜像。"""
        roi = np.zeros((140, 180), dtype=np.uint8)
        roi[40:100, 60:70] = 255      # 竖条偏左
        roi[40:50, 60:120] = 255      # 顶部横条向右伸 = 左右不对称
        tmpl = roi[35:105, 55:125].copy()
        s, s_flip = facing.scores(roi, tmpl)
        self.assertGreater(s, 0.9)
        self.assertGreater(s - s_flip, facing.FACING_MARGIN_MIN)

    def test_observe_end_to_end(self):
        roi_src = np.zeros((1440, 2560, 3), dtype=np.uint8)
        a = anchor.Anchor(1280.0, 880.0, 130)
        # 在 ROI 位置画同一个不对称图案
        roi_src[760:820, 1250:1260] = 255
        roi_src[760:770, 1250:1310] = 255
        tmpl = facing.crop_roi(roi_src, a)[35:105, 55:125].copy()
        got, s, s_flip = facing.observe(roi_src, a, tmpl, 'RIGHT')
        self.assertEqual(got, 'RIGHT')
        self.assertGreater(s, s_flip)

    def test_observe_abstains_without_template(self):
        a = anchor.Anchor(1280.0, 880.0, 130)
        self.assertEqual(facing.observe(self._frame(), a, None, 'RIGHT'),
                         (None, 0.0, 0.0))

    def test_observe_abstains_at_edge(self):
        a = anchor.Anchor(20.0, 880.0, 130)
        tmpl = np.zeros((70, 70), dtype=np.uint8)
        self.assertEqual(facing.observe(self._frame(), a, tmpl, 'RIGHT'),
                         (None, 0.0, 0.0))

    def test_observe_abstains_when_template_larger_than_roi(self):
        """模板比 ROI 大 → matchTemplate 会抛,必须提前挡住。"""
        a = anchor.Anchor(1280.0, 880.0, 130)
        tmpl = np.zeros((200, 200), dtype=np.uint8)
        self.assertEqual(facing.observe(self._frame(), a, tmpl, 'RIGHT'),
                         (None, 0.0, 0.0))
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_facing -v 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: module 'src.detect.facing' has no attribute 'roi_box'`

- [ ] **Step 3: 写最小实现**

在 `src/detect/facing.py` 顶部加 import，并追加实现：

```python
import cv2
import numpy as np

ROI_HALF_W = 90     # ROI 半宽:x ∈ [a.x-90, a.x+90]
ROI_TOP_DY = 160    # ROI 上沿:a.y - 160(名字牌画在脚下,角色在牌子上方)
ROI_BOTTOM_DY = 20  # ROI 下沿:a.y - 20(把名字牌本身排除掉)


def roi_box(frame_shape, anchor_obj):
    """朝向 ROI (x0, y0, x1, y1),照抄附录 A.1 的 180x140。

    被画面边缘切到 → 返回 None。宁可不观测,也不要拿半张角色去匹配:
    附录 A 的 #0 弃权帧就是切边造成的,而切了边的 ROI 会让分数不可比。
    """
    h, w = frame_shape[:2]
    x0 = int(anchor_obj.x) - ROI_HALF_W
    x1 = int(anchor_obj.x) + ROI_HALF_W
    y0 = int(anchor_obj.y) - ROI_TOP_DY
    y1 = int(anchor_obj.y) - ROI_BOTTOM_DY
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    return x0, y0, x1, y1


def crop_roi(frame, anchor_obj):
    """按 roi_box 裁出灰度 ROI;越界 → None。"""
    box = roi_box(frame.shape, anchor_obj)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    return cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)


def scores(roi_gray, template):
    """(模板分, 镜像分):各跑一次 TM_CCOEFF_NORMED 取最大值。

    镜像用 cv2.flip(template, 1) —— 角色朝向翻转在图像上就是水平镜像,
    所以同一个模板能同时当两个方向的判据,不需要两套模板(附录 A.1)。
    """
    s = float(cv2.matchTemplate(roi_gray, template, cv2.TM_CCOEFF_NORMED).max())
    flipped = cv2.flip(template, 1)
    s_flip = float(cv2.matchTemplate(roi_gray, flipped, cv2.TM_CCOEFF_NORMED).max())
    return s, s_flip


def observe(frame, anchor_obj, template, template_facing):
    """一次朝向观测 → (朝向, s, s_flip)。朝向为 None 表示弃权。

    没模板 / ROI 越界 / 模板比 ROI 大 → (None, 0.0, 0.0)。
    调用方必须保证 anchor_obj 是**本拍真命中**的(source in window/region/template):
    cached/fallback 的锚点会让 ROI 整体错位,裁出来是草地和宠物脸(附录 A.3)。
    """
    if template is None:
        return None, 0.0, 0.0
    roi = crop_roi(frame, anchor_obj)
    if roi is None:
        return None, 0.0, 0.0
    if roi.shape[0] < template.shape[0] or roi.shape[1] < template.shape[1]:
        return None, 0.0, 0.0
    s, s_flip = scores(roi, template)
    return decide(s, s_flip, template_facing), s, s_flip
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_facing -v 2>&1 | tail -5
```

Expected: OK（13 个用例）

- [ ] **Step 5: 全量回归**

```bash
mkdir -p screenshots/test_frames && cp ../_frames_backup/training_ground_full_2560x1440.png screenshots/test_frames/
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
```

Expected: OK，总数 ≥ 354

- [ ] **Step 6: 提交**

```bash
git add src/detect/facing.py tests/test_facing.py
git commit -m "feat: facing ROI 裁剪与双向 matchTemplate

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: 模板子框标定 + 采集函数

spec §3.3 明确写了：**头+肩子框在 ROI 内的偏移，附录 A 没有记下来**（A.1 只写了「58×66」，没给坐标）。不许凭空猜一个数——A.3 的教训正是 ROI 取错整个实验作废。本任务先用真帧把它定出来，再写采集函数。

**Files:**
- Create: `scripts/calibrate_facing_template.py`
- Modify: `src/detect/facing.py`
- Test: `tests/test_facing.py`

**Interfaces:**
- Consumes: `facing.crop_roi`（Task 3）
- Produces:
  - 常量 `TEMPLATE_W = 58`、`TEMPLATE_H = 66`、`TEMPLATE_DX`、`TEMPLATE_DY`（本任务定出来的值）
  - `facing.capture(frame, anchor_obj) -> np.ndarray | None`

- [ ] **Step 1: 写标定脚本**

新建 `scripts/calibrate_facing_template.py`：

```python
# -*- coding: utf-8 -*-
"""定出头+肩子框在朝向 ROI 内的偏移(spec §3.3:附录 A 没记下来,必须重定)。

用法:
    python scripts/calibrate_facing_template.py <帧图路径> <角色名>

做三件事:
1. 用真的锚点 OCR 在帧里找到角色名字牌
2. 按 facing.roi_box 裁出 180x140 的 ROI
3. 放大 4 倍 + 每 10 原始像素画一条网格线,存成 PNG

然后人工看图,读出头+肩(58x66)左上角在 ROI 内的坐标,填进
src/detect/facing.py 的 TEMPLATE_DX / TEMPLATE_DY。
"""
import sys

import cv2

from src.detect import anchor, facing

SCALE = 4
GRID = 10


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    frame = cv2.imread(sys.argv[1])
    if frame is None:
        print('读不出帧图: %s' % sys.argv[1])
        return 2
    name = sys.argv[2]
    h, w = frame.shape[:2]
    region = anchor.search_region(w, h, 0.30, 0.30, 0.55)
    hit = anchor.find_in_region(frame, name, region)
    if hit is None:
        print('锚点没命中。确认角色名对、且这一帧里名字牌没被挡')
        return 1
    print('锚点: x=%.0f y=%.0f width=%d text=%r' % (hit.x, hit.y, hit.width, hit.text))
    roi = facing.crop_roi(frame, hit)
    if roi is None:
        print('ROI 越界(角色贴边),换一帧')
        return 1

    big = cv2.resize(roi, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_NEAREST)
    big = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
    for x in range(0, roi.shape[1], GRID):
        cv2.line(big, (x * SCALE, 0), (x * SCALE, big.shape[0]), (0, 128, 255), 1)
        cv2.putText(big, str(x), (x * SCALE + 2, 12),
                    cv2.FONT_HERSHEY_PLAIN, 0.7, (0, 200, 255), 1)
    for y in range(0, roi.shape[0], GRID):
        cv2.line(big, (0, y * SCALE), (big.shape[1], y * SCALE), (0, 128, 255), 1)
        cv2.putText(big, str(y), (2, y * SCALE + 12),
                    cv2.FONT_HERSHEY_PLAIN, 0.7, (0, 200, 255), 1)

    out = 'screenshots/facing_roi_calib.png'
    cv2.imwrite(out, big)
    print('已存 %s(放大 %dx,网格 %d 原始像素)' % (out, SCALE, GRID))
    print('看图读出头+肩 58x66 的左上角坐标,填进 facing.TEMPLATE_DX / TEMPLATE_DY')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: 跑标定脚本**

```bash
mkdir -p screenshots/test_frames && cp ../_frames_backup/training_ground_full_2560x1440.png screenshots/test_frames/
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" scripts/calibrate_facing_template.py screenshots/test_frames/training_ground_full_2560x1440.png "Yufeng咕咕"
```

看 `screenshots/facing_roi_calib.png`，读出头+肩 58×66 的左上角坐标。

**若锚点没命中**（存档帧里名字牌被挡或角色名不同）：用 GUI 现场截一张干净帧（角色站定、宠物不挡），存到 `screenshots/` 下再跑一次。**不要跳过这一步去猜偏移。**

- [ ] **Step 3: 写失败的测试**

追加到 `tests/test_facing.py`：

```python
class TestFacingCapture(unittest.TestCase):

    def test_capture_shape(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        a = anchor.Anchor(1280.0, 880.0, 130)
        tmpl = facing.capture(frame, a)
        self.assertEqual(tmpl.shape, (facing.TEMPLATE_H, facing.TEMPLATE_W))

    def test_capture_none_at_edge(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        self.assertIsNone(facing.capture(frame, anchor.Anchor(20.0, 880.0, 130)))

    def test_capture_subbox_fits_in_roi(self):
        """标定出来的偏移必须让 58x66 完整落在 180x140 里,否则裁出来会缺角。"""
        self.assertLessEqual(facing.TEMPLATE_DX + facing.TEMPLATE_W, 2 * facing.ROI_HALF_W)
        self.assertLessEqual(facing.TEMPLATE_DY + facing.TEMPLATE_H,
                             facing.ROI_TOP_DY - facing.ROI_BOTTOM_DY)

    def test_captured_template_matches_its_own_roi(self):
        """自洽:从某帧采的模板,拿回同一帧匹配必须高分且明显胜过镜像。"""
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        a = anchor.Anchor(1280.0, 880.0, 130)
        x0, y0, _, _ = facing.roi_box(frame.shape, a)
        # 在子框位置画不对称图案
        px = x0 + facing.TEMPLATE_DX
        py = y0 + facing.TEMPLATE_DY
        frame[py + 10:py + 50, px + 5:px + 15] = 255
        frame[py + 10:py + 20, px + 5:px + 45] = 255
        tmpl = facing.capture(frame, a)
        got, s, s_flip = facing.observe(frame, a, tmpl, 'RIGHT')
        self.assertEqual(got, 'RIGHT')
        self.assertGreater(s, 0.9)
```

- [ ] **Step 4: 跑测试确认失败**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_facing -v 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: module 'src.detect.facing' has no attribute 'capture'`

- [ ] **Step 5: 写实现**

在 `src/detect/facing.py` 追加（`<标定值>` 换成 Step 2 读出来的数，并在注释里记下是怎么定的）：

```python
TEMPLATE_W = 58   # 头+肩模板宽(附录 A.1)
TEMPLATE_H = 66   # 头+肩模板高(附录 A.1)
# 子框在 ROI 内的左上角偏移。附录 A 只记了 58x66 没记坐标,这两个数是
# 2026-08-08 用 scripts/calibrate_facing_template.py 在真帧上目视标定的
# (放大 4x + 10px 网格,对准头顶与肩线)。换角色/换分辨率必须重标。
TEMPLATE_DX = <标定值>
TEMPLATE_DY = <标定值>


def capture(frame, anchor_obj):
    """从本帧裁出头+肩模板(灰度 58x66);ROI 越界 → None。

    只取头+肩是附录 A.3 的实测结论:拿盾、挥杖等不同动画姿态照样 0.82-0.89
    命中 —— 头部在各动画帧间足够稳定,不需要一整套姿态模板库。
    调用方必须保证这一拍是 OCR 完整命中(见 spec §3.3 的采集四道门)。
    """
    roi = crop_roi(frame, anchor_obj)
    if roi is None:
        return None
    return roi[TEMPLATE_DY:TEMPLATE_DY + TEMPLATE_H,
               TEMPLATE_DX:TEMPLATE_DX + TEMPLATE_W].copy()
```

- [ ] **Step 6: 跑测试确认通过 + 全量回归**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_facing -v 2>&1 | tail -5
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
```

Expected: 两条都 OK

- [ ] **Step 7: 提交**

```bash
git add src/detect/facing.py tests/test_facing.py scripts/calibrate_facing_template.py
git commit -m "feat: 头+肩模板采集 + 子框偏移标定脚本

附录 A 只记了 58x66 没记坐标,用 calibrate_facing_template.py 在真帧上
目视标定(放大 4x + 10px 网格)。换角色/换分辨率必须重标。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: 接线到 `MapleFarmTask`（只读，不碰决策）

**Files:**
- Modify: `src/task/MapleFarmTask.py`
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: `facing.observe`、`facing.capture`（Task 3/4）、`farm_logic.walk_confirmed`（Task 1）
- Produces: 决策日志新字段 `实测=` / `分值=`，以及分歧时的独立日志行

新增常量、状态、配置：

| 项 | 值 | 位置 |
|---|---|---|
| `FACING_TEMPLATE_DIR` | `'screenshots/facing_templates'` | 常量区 |
| `FACING_CAPTURE_MIN_DX` | `40` | 常量区 |
| `_facing_template` | `None` | `_reset_state()` |
| `_facing_template_dir` | `None` | `_reset_state()` |
| `_seek_start_body_x` | `None` | `_reset_state()` |
| `朝向观测开关` | `False` | `DEFAULT_CONFIG` |

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_farm_task_offline.py`（沿用该文件既有的任务构造 helper；几何前提照 memory：`角色名` 为空串时锚点回退画面中心 (1280,720)、身体 (1280,630)）：

```python
class TestFacingObserver(unittest.TestCase):
    """朝向观测器是只读的:它绝不能改变任何决策。"""

    def test_observer_off_by_default(self):
        task = make_task()
        self.assertFalse(task.config['朝向观测开关'])

    def test_no_observation_when_switch_off(self):
        task = make_task()
        task.config['朝向观测开关'] = False
        with patch('src.detect.facing.observe') as m:
            task._detect_and_act(_synthetic_frame(), 100.0, task.config, KEYS)
        m.assert_not_called()

    def test_no_observation_on_cached_anchor(self):
        """cached/fallback 的锚点会让 ROI 整体错位(附录 A.3),不许观测。"""
        task = make_task()
        task.config['朝向观测开关'] = True
        task._facing_template = np.zeros((66, 58), dtype=np.uint8)
        task._facing_template_dir = 'RIGHT'
        with patch.object(task, '_resolve_anchor',
                          return_value=(anchor.Anchor(1280.0, 720.0, 130), 'cached')), \
             patch('src.detect.facing.observe') as m:
            task._detect_and_act(_synthetic_frame(), 100.0, task.config, KEYS)
        m.assert_not_called()

    def test_observation_never_writes_facing(self):
        """本设计的核心约束:观测结果只进日志,永不写回 _facing。"""
        task = make_task()
        task.config['朝向观测开关'] = True
        task._facing = 'LEFT'
        task._facing_template = np.zeros((66, 58), dtype=np.uint8)
        task._facing_template_dir = 'RIGHT'
        with patch.object(task, '_resolve_anchor',
                          return_value=(anchor.Anchor(1280.0, 720.0, 130), 'window')), \
             patch('src.detect.facing.observe', return_value=('RIGHT', 0.88, 0.47)):
            task._detect_and_act(_synthetic_frame(), 100.0, task.config, KEYS)
        self.assertEqual(task._facing, 'LEFT')   # 观测说 RIGHT,信念不许被改

    def test_observation_exception_does_not_propagate(self):
        """观测器不能把挂机搞崩(与 YOLO/模板匹配同样处理)。"""
        task = make_task()
        task.config['朝向观测开关'] = True
        task._facing_template = np.zeros((66, 58), dtype=np.uint8)
        task._facing_template_dir = 'RIGHT'
        with patch.object(task, '_resolve_anchor',
                          return_value=(anchor.Anchor(1280.0, 720.0, 130), 'window')), \
             patch('src.detect.facing.observe', side_effect=RuntimeError('boom')):
            task._detect_and_act(_synthetic_frame(), 100.0, task.config, KEYS)   # 不抛即通过

    def test_template_captured_only_after_confirmed_walk(self):
        """位移没确认之前不许采模板 —— 采错方向后面所有观测全错。"""
        task = make_task()
        task.config['朝向观测开关'] = True
        task._seek_key = '右移键'
        task._seek_dir = 'right'
        task._seek_start_body_x = 1000.0
        with patch('src.detect.facing.capture') as m:
            task._maybe_capture_facing_template(_synthetic_frame(),
                                                anchor.Anchor(1010.0, 720.0, 130),
                                                'window', 'Yufeng咕咕')
        m.assert_not_called()      # 只走了 10px < 40

    def test_template_captured_records_direction(self):
        task = make_task()
        task.config['朝向观测开关'] = True
        task._seek_key = '右移键'
        task._seek_dir = 'right'
        task._seek_start_body_x = 1000.0
        hit = anchor.AnchorHit(1100.0, 720.0, 130, 'Yufeng咕咕')
        with patch('src.detect.facing.capture',
                   return_value=np.ones((66, 58), dtype=np.uint8)), \
             patch('src.detect.facing.save_template'):
            task._maybe_capture_facing_template(_synthetic_frame(), hit, 'window', 'Yufeng咕咕')
        self.assertEqual(task._facing_template_dir, 'RIGHT')
        self.assertIsNotNone(task._facing_template)

    def test_template_not_captured_on_partial_ocr(self):
        """部分匹配 'ng咕咕' 的框中心系统性右偏(附录 A.3),裁出来是草地和宠物脸。"""
        task = make_task()
        task.config['朝向观测开关'] = True
        task._seek_key = '右移键'
        task._seek_dir = 'right'
        task._seek_start_body_x = 1000.0
        hit = anchor.AnchorHit(1100.0, 720.0, 130, 'ng咕咕')
        with patch('src.detect.facing.capture') as m:
            task._maybe_capture_facing_template(_synthetic_frame(), hit, 'window', 'Yufeng咕咕')
        m.assert_not_called()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: 'MapleFarmTask' object has no attribute '_maybe_capture_facing_template'`

- [ ] **Step 3: 写实现**

3a. `src/task/MapleFarmTask.py:11` 的 import 行加 `facing`。现状是：

```python
from src.detect import anchor, bars, guards, ocr_engine, potions
```

改成（**注意保留 `ocr_engine`**）：

```python
from src.detect import anchor, bars, facing, guards, ocr_engine, potions
```

`os` 与 `time` 已在文件顶部导入（`MapleFarmTask.py:1-2`），不需要再加。

3b. 常量区（`TURN_TAP_SECONDS` 之后）：

```python
FACING_TEMPLATE_DIR = 'screenshots/facing_templates'  # 朝向模板持久化目录(灰度头+肩)
FACING_CAPTURE_MIN_DX = 40   # 采朝向模板要求的最小确认位移(像素):角色真走了这么远,朝向才是观测出来的而不是猜的
```

3c. `DEFAULT_CONFIG` 加一项（放在 `决策日志开关` 之前）：

```python
    '朝向观测开关': False,
```

3d. 配置说明（`决策日志开关` 说明之前）：

```python
            '朝向观测开关': '只读排查用:每个锚点真命中的检测拍,用模板匹配读出角色**真实**朝向,与信念朝向一起写进决策日志(字段 实测= / 分值=),不一致时另写一行「朝向分歧」。它不改变任何决策,纯粹是尺子——_facing 是纯信念,项目在它上面改过四轮却一直没有直接证据。开着会在没模板时先等一次寻怪走动来采模板(要求沿按键方向真走够 40px,避免用信念标定模板)。需要同时开 决策日志开关。排完记得关',
```

3e. `_reset_state()` 加三个状态：

```python
        self._facing_template = None      # 朝向模板(灰度 58x66);None=还没采到
        self._facing_template_dir = None  # 模板自身朝向 'LEFT'/'RIGHT';None=未知
        self._seek_start_body_x = None    # 本次寻怪长按起点的 body_x,走动确认用
```

3f. `_do_seek_move` 里记录长按起点。找到这一段：

```python
            self.send_key_down(keys[key])
            self._seek_key = key
```

改成：

```python
            if self._seek_key != key:
                # 换向/首次按下:重记起点,走动确认要从这一刻起算
                self._seek_start_body_x = self._last_body_x
            self.send_key_down(keys[key])
            self._seek_key = key
```

并在 `_release_seek_key()` 里清掉：`self._seek_start_body_x = None`。

`_last_body_x` 由 `_detect_and_act` 每拍写入（3h）。

3g. 新方法（放在 `_capture_nametag_template` 之后）：

```python
    def _maybe_capture_facing_template(self, frame, hit, source, name):
        """采朝向模板:只在「寻怪长按 + 位移已确认 + OCR 完整命中 + 还没模板」时采。

        模板自带朝向,而 `s > s_flip` 只说明「与模板同向」——要换算成 L/R 就必须
        知道模板本身朝哪边。**不能用 `_facing` 标定**(那正是被检验的对象,循环论证),
        所以改用位移观测:寻怪是长按方向键连续走,角色真的沿按键方向走了
        FACING_CAPTURE_MIN_DX 像素,它就必定面朝那边(见 farm_logic.walk_confirmed)。

        OCR 完整命中这道门与 _capture_nametag_template 同源:部分匹配 'ng咕咕' 的
        框中心系统性右偏,裁出来的 ROI 是草地和宠物脸(附录 A.3,第一次实验因此作废)。
        """
        if self._facing_template is not None:
            return
        if source not in ('window', 'region'):
            return
        if (getattr(hit, 'text', '') or '').strip() != name:
            return
        if not farm_logic.walk_confirmed(self._seek_dir, self._seek_start_body_x,
                                         anchor.body_center(hit, self.config['名字牌到身体偏移(像素)'])[0],
                                         FACING_CAPTURE_MIN_DX):
            return
        tmpl = facing.capture(frame, hit)
        if tmpl is None:
            return
        self._facing_template = tmpl
        self._facing_template_dir = 'LEFT' if self._seek_dir == 'left' else 'RIGHT'
        self.log_info(f'朝向模板已采集 方向={self._facing_template_dir} '
                      f'(寻怪走动确认 ≥{FACING_CAPTURE_MIN_DX}px)')
        try:
            os.makedirs(FACING_TEMPLATE_DIR, exist_ok=True)
            suffix = 'L' if self._facing_template_dir == 'LEFT' else 'R'
            anchor.save_template(tmpl, os.path.join(
                FACING_TEMPLATE_DIR, f'{name}_{suffix}.png'))
        except Exception as e:
            self.log_error(f'朝向模板落盘失败(不影响本次运行): {e!r}')

    def _observe_facing(self, frame, hit, source):
        """一次只读朝向观测 → (朝向, s, s_flip)。任何失败都返回 (None, 0.0, 0.0)。

        **结果绝不写回 `_facing`、绝不参与决策**(spec §3.4)——观测器自己都还没被
        验证过,先让它证明自己看得准。异常一律吞掉,观测器不能把挂机搞崩。
        """
        if not self.config.get('朝向观测开关'):
            return None, 0.0, 0.0
        if source not in ('window', 'region', 'template'):
            return None, 0.0, 0.0   # cached/fallback 的锚点会让 ROI 整体错位
        if self._facing_template is None:
            return None, 0.0, 0.0
        try:
            return facing.observe(frame, hit, self._facing_template,
                                  self._facing_template_dir)
        except Exception as e:
            self._log_detect_error(time.time(), '朝向观测', e)
            return None, 0.0, 0.0
```

3h. `_detect_and_act` 开头，锚点解析之后、`body` 之后立刻接上（**不要放到任何决策分支里**）：

```python
        anchor_hit, source = self._resolve_anchor(frame, now, cfg)
        body = anchor.body_center(anchor_hit, cfg['名字牌到身体偏移(像素)'])
        self._last_body_x = body[0]          # 走动确认要用
        if cfg.get('朝向观测开关'):
            self._maybe_capture_facing_template(
                frame, anchor_hit, source, (cfg['角色名'] or '').strip())
        observed, obs_s, obs_flip = self._observe_facing(frame, anchor_hit, source)
```

并在 `_reset_state()` 里加 `self._last_body_x = None`。

3i. `_log_decision` 签名加三个参数 `observed, obs_s, obs_flip`，末尾追加字段，并在分歧时另写一行。改 `_log_decision` 的 `self.log_debug(...)` 那一段：

```python
        self.log_debug(
            f'决策 src={source} body_x={body[0]:.0f} anchor_y={anchor_hit.y:.0f} '
            f'怪={len(centres)} 区内={len(in_zone)}(左{left}/右{len(in_zone) - left}) '
            f'实测有怪={raw_present} 有怪={mob_present} '
            f'可打区内={len(attack_in)} 可打={attack_present} '
            f'朝向={facing_before or "-"}→{self._facing or "-"} '
            f'转向={turn or "-"} 寻怪={self._seek_dir or "-"} '
            f'可发键={self._key_sendable()} '
            f'实测={_FACING_SHORT.get(observed, "?")} '
            f'分值={max(obs_s, obs_flip):.2f}/{abs(obs_s - obs_flip):.2f}')
        # 分歧单独写一行,方便 grep 「朝向分歧」。三个「距上次」是判据 D 的数据源:
        # 用来判断分叉集中在施法窗、硬直窗,还是均匀分布。
        # 注意 _last_turn 在受击时被重置为 0.0 哨兵,那之后「距上次转向」会显示成
        # 一个巨大的假值(spec §4),判据 D 只按「距上次攻击」分桶,不受影响。
        if observed is not None and facing_before in ('LEFT', 'RIGHT') \
                and observed != facing_before:
            now = time.time()
            self.log_debug(
                f'朝向分歧 信念={facing_before} 实测={observed} '
                f'分值={max(obs_s, obs_flip):.2f}/{abs(obs_s - obs_flip):.2f} '
                f'距上次攻击={now - self._last_attack:.2f}s '
                f'距上次受击={now - self._last_hit:.2f}s '
                f'距上次转向={now - self._last_turn:.2f}s')
```

在模块常量区加：

```python
_FACING_SHORT = {'LEFT': 'L', 'RIGHT': 'R'}   # 决策行里 实测= 字段的短写
```

并把 `_detect_and_act` 末尾的调用改成传入这三个值：

```python
        if cfg.get('决策日志开关'):
            self._log_decision(source, anchor_hit, body, zone, attack_area, centres,
                               raw_present, mob_present, self._last_attack_present,
                               facing_before, turn, observed, obs_s, obs_flip)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v 2>&1 | tail -10
```

Expected: OK

- [ ] **Step 5: 全量回归**

```bash
mkdir -p screenshots/test_frames && cp ../_frames_backup/training_ground_full_2560x1440.png screenshots/test_frames/
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
```

Expected: OK，总数 ≥ 362

- [ ] **Step 6: 提交**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 朝向观测器接线(只读,默认关)

观测结果只进决策日志,永不写回 _facing、不参与任何决策 —— 有专门的
断言守着。模板只在「寻怪长按 + 沿按键方向真走够 40px + OCR 完整命中」
时采,避免用信念标定模板造成循环论证。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: 判据计算脚本

spec §5.4 的四条判据必须能一条命令算出来，否则「事先写死」等于没写。

**Files:**
- Create: `scripts/analyze_facing.py`

**Interfaces:**
- Consumes: Task 5 写出的日志字段
- Produces: 判据 A/B/C/D 的判定输出，退出码 0=全过 / 1=有不过

- [ ] **Step 1: 写脚本**

新建 `scripts/analyze_facing.py`：

```python
# -*- coding: utf-8 -*-
"""朝向观测器判据 A/B/C/D(2026-08-08-facing-observer-design.md §5.4)。

判据在 spec 里事先写死,本脚本只是把它算出来,不许在这里改通过线。

用法: python scripts/analyze_facing.py [起始时间 HH:MM:SS]
"""
import re
import sys
from collections import Counter

LOG = 'logs/ok-script.log'
TS = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d{3})')
DEC = re.compile(r'决策 src=(\S+) .*?朝向=(\S+)→(\S+) 转向=(\S+) 寻怪=\S+ '
                 r'可发键=\w+ 实测=(\S+) 分值=')
DIV = re.compile(r'朝向分歧 信念=(\S+) 实测=(\S+) 分值=\S+ 距上次攻击=([\d.]+)s')
FRESH = ('window', 'region', 'template')


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else '00:00:00'
    fresh = answered = 0
    belief_known_and_answered = 0
    prev = None            # (实测, 有没有发过方向键)
    flips = pairs = 0
    divergences = []
    for line in open(LOG, encoding='utf-8', errors='replace'):
        m = TS.match(line)
        if not m or m.group(1)[11:] < start:
            continue
        d = DIV.search(line)
        if d:
            divergences.append(float(d.group(3)))
            continue
        d = DEC.search(line)
        if not d:
            continue
        src, f0, _f1, turn, obs = d.groups()
        if src not in FRESH:
            prev = None
            continue
        fresh += 1
        if obs in ('L', 'R'):
            answered += 1
            if f0 in ('LEFT', 'RIGHT'):
                belief_known_and_answered += 1
            if prev is not None and prev[1] is False:
                pairs += 1
                if prev[0] != obs:
                    flips += 1
            prev = (obs, turn != '-')
        else:
            prev = None

    print('锚点真命中 %d 拍,其中观测给出答案 %d 拍' % (fresh, answered))
    ok = []

    def chk(name, passed, got, want):
        ok.append(passed)
        print('  [%s] %-22s 实测 %-14s 通过线 %s'
              % ('通过' if passed else '不过', name, got, want))

    a = 100.0 * answered / fresh if fresh else 0.0
    chk('A 仪器可用率', a >= 50.0, '%.1f%%' % a, '>= 50%')

    b = 100.0 * flips / pairs if pairs else 0.0
    chk('B 无随机噪声', b <= 5.0, '%.1f%% (n=%d)' % (b, pairs), '<= 5%')

    c = (100.0 * len(divergences) / belief_known_and_answered
         if belief_known_and_answered else 0.0)
    print('  [--] C 分叉率(主结果)      实测 %.1f%% (%d/%d)'
          % (c, len(divergences), belief_known_and_answered))
    if c >= 10.0:
        verdict = '>= 10% → 吞键推论坐实,做动画忙窗'
    elif c < 3.0:
        verdict = '< 3% → 吞键推论证伪,动画忙窗不做,回 Phase 1'
    else:
        verdict = '3-10% 灰区 → 看判据 D 裁决'
    print('       决策线: %s' % verdict)

    # D:按「距上次攻击」分桶,施法窗 [0,1.0s) vs 其余
    if divergences:
        inside = sum(1 for x in divergences if x < 1.0)
        outside = len(divergences) - inside
        print('  [--] D 时间相关性          施法窗内 %d / 窗外 %d' % (inside, outside))
        if outside:
            print('       窗内:窗外 = %.2f (>= 2.0 → 吞键机制坐实)'
                  % (inside / outside))
        else:
            print('       全部落在施法窗内 → 吞键机制坐实')

    if not all(ok):
        print('\nA 或 B 不过 —— C/D 的数字不许解读,先修仪器')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: 用现有日志冒烟（应当报「仪器不可用」）**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" scripts/analyze_facing.py
```

Expected: 跑通不抛。因为现有日志里还没有 `实测=` 字段，`A 仪器可用率` 会是 0% 并判「不过」——**这正是期望结果**，证明脚本不会把没有数据当成通过。

- [ ] **Step 3: 提交**

```bash
git add scripts/analyze_facing.py
git commit -m "feat: 朝向观测器判据 A/B/C/D 计算脚本

判据在 spec §5.4 事先写死,本脚本只负责算,通过线不许在这里改。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: 实弹跑一轮并出结论

**Files:** 无代码改动（只产出数据与结论）

- [ ] **Step 1: 重启 GUI**

`src/detect/facing.py` 与 `farm_logic.py` **不参与热重载**（只重载任务模块自身，不递归依赖）。必须**完全重启 GUI**，否则新任务代码 + 旧依赖 = `AttributeError`。2026-08-08 10:23 踩过一次。

需要**管理员提权**（PyDirect 要求）+ 游戏前台 + 2560×1440。

- [ ] **Step 2: 开配置**

在 **GUI 面板里**改（`Config` 只在构造时读一次 JSON，运行中改文件无效，而且下次 GUI 存配置会覆盖掉）：

- `决策日志开关` = 开
- `朝向观测开关` = 开

- [ ] **Step 3: 挂 ≥20 分钟**

先确认模板采到了：`grep 朝向模板已采集 logs/ok-script.log`。没采到说明这段时间没触发寻怪走动，继续挂或换个怪密度低一点的位置（寻怪实测占 20–35% 的拍）。

- [ ] **Step 4: 算判据**

```bash
PYTHONUTF8=1 "/h/ok-mxd/data/apps/ok-ww/python/python.exe" scripts/analyze_facing.py <开观测的时刻 HH:MM:SS>
```

- [ ] **Step 5: 按 spec §5.4 的决策线走**

- **A 或 B 不过** → 仪器不可用，先修（模板质量 / 标定偏移 / ROI）。**C/D 的数字不许解读，不许据此下任何结论。**
- **C ≥ 10%** → 吞键推论坐实 → 下一步做「动画忙窗」（spec §6），本观测器转为它的验收仪器
- **C < 3%** → 吞键推论**证伪** → 动画忙窗**不做**。只修 spec §2.3 那个已坐实的独立洞（受击清空 `_facing` → 有向攻击区退化成对称区），然后回 Phase 1 重查症状
- **C 在 3–10%** → 看判据 D：施法窗内的分叉率 ≥ 窗外 2 倍 → 做忙窗；均匀分布 → 不是施法吞键，回 Phase 1

- [ ] **Step 6: 把结论写回 spec 与项目记忆**

在 spec 末尾加一节「§8 实测结果（YYYY-MM-DD）」，记下四条判据的实际数字与据此做出的决定。项目记忆 `ok-mxd-project.md` 加一条，格式与既有的「已验证有效 / 已验证无效，别再试」一致。

- [ ] **Step 7: 关掉观测开关**

排完把 `朝向观测开关` 关回去（它每个真命中拍都跑两次 `matchTemplate`，虽是亚毫秒，但决策日志会写得很密）。

---

## Self-Review

**Spec coverage:**

| spec 章节 | 由哪个 Task 实现 |
|---|---|
| §3.1 边界（三层文件划分） | Task 2/3（`src/detect/facing.py`）、Task 1（`farm_logic`）、Task 5（接线） |
| §3.2 观测判据（ROI、双向匹配、阈值） | Task 2（`decide`）、Task 3（`roi_box`/`crop_roi`/`scores`/`observe`） |
| §3.3 模板采集（走动确认、四道门、落盘、子框偏移待标定） | Task 1（`walk_confirmed`）、Task 4（标定 + `capture`）、Task 5（四道门 + 落盘） |
| §3.4 接入点（真命中才观测、不参与决策、异常吞掉） | Task 5 |
| §3.5 配置 `朝向观测开关` | Task 5 |
| §4 可观测性（`实测=`/`分值=`、分歧行、三个「距上次」） | Task 5 |
| §5.1 纯函数单测 | Task 1、Task 2 |
| §5.2 CV 层回归（合成图 + 存档帧） | Task 3、Task 4 |
| §5.3 任务级离线测试 | Task 5 |
| §5.4 实弹判据 A/B/C/D | Task 6（算）、Task 7（跑 + 决策） |
| §6 动画忙窗 | 本计划**不实现**，Task 7 Step 5 决定做不做 |
| §7 明确不做 | 全程遵守；Task 5 有「观测不写回 `_facing`」的断言守着 |

**类型一致性检查：** `decide(s, s_flip, template_facing)` 在 Task 2 定义，Task 3 的 `observe` 调用一致；`observe` 返回三元组 `(朝向, s, s_flip)`，Task 5 的 `_observe_facing` 与 `_log_decision` 按三元组解包一致；`walk_confirmed(seek_dir, body_x_start, body_x_now, min_dx)` 在 Task 1 定义，Task 5 按位置传参一致；`capture(frame, anchor_obj)` 在 Task 4 定义，Task 5 调用一致。

**已知需要实现者判断的一处：** Task 4 Step 2 的标定要看图填数，无法在计划里预先写死具体值——这是 spec §3.3 明确要求的（附录 A 没记坐标，不许猜）。Task 4 Step 3 的 `test_capture_subbox_fits_in_roi` 会挡住明显不合理的填值。
