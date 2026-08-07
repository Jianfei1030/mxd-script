# 有向攻击区 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「能不能打到」从「要不要转向」里分出来——保留对称区当接敌区管转向/寻怪，新增面朝侧半区当攻击区，只管按不按攻击键，消灭「怪在背侧且转向被冷却挡住时照样按攻击键」的确定性挥空。

**Architecture:** 新增纯函数 `farm_logic.facing_half_zone(zone, body_x, facing)` 把已算好的对称 zone 切成面朝侧半区。`MapleFarmTask._detect_and_act` 多算一路信号 `_last_attack_present`（独立去抖），**只有** `_do_attack` 改读它；`_last_mob_present` 保持原名原义，继续驱动转向/寻怪分支、坐椅、忙判定、走位。`attack_turn_direction` 一个字不改。

**Tech Stack:** Python 3.12（嵌入式 `H:\ok-mxd\data\apps\ok-ww\python\python.exe`）、unittest、OpenCV、PySide6/qfluentwidgets（overlay 绘制）

**Spec:** `docs/superpowers/specs/2026-08-07-directional-attack-zone-design.md`

## Global Constraints

- **Python 只用** `H:\ok-mxd\data\apps\ok-ww\python\python.exe`，**禁止 pip install**
- **禁止 hard code 绝对路径**（AGENTS.md §11.1）：`C:/` `D:/` `H:/` `/Users/` `AppData` 一律不许出现在 `src/` `scripts/` `tests/` 的代码里；项目根用 `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 推导。注释/文档里的示例路径不在此限
- **新增/修改纯逻辑必须同步加 unittest**（AGENTS.md §11.2），合入前全量单测必须绿
- **新特性必须带 E2E 截图 + 视觉验收**（AGENTS.md §11.3）——本计划 Task 5
- **跑测试前必须确认** `screenshots/test_frames/` 是**目录**且含 `training_ground_full_2560x1440.png`。每次跑 GUI 都会把它清掉，从 `H:\ok-mxd\_frames_backup\` 拷回。若它变成了一个截图**文件**，先删掉再重建目录，否则 30+ 用例假失败
- **改了 `farm_logic.py` 必须重启 GUI**：框架热重载只 reload 任务模块自身，不递归依赖
- **离线测试几何前提**：`DEFAULT_CONFIG['角色名']` 是空串 → `_resolve_anchor` 直接回退画面中心，锚点恒为 `(1280, 720)`、身体 `(1280, 630)`、接敌区（默认宽 600 高 200）`x∈[980,1580] y∈[530,730]`。测试里 patch `find_in_region` 是**无效的**（走不到那条通道）
- **群体模式必须逐键等同于改动前行为**——这是安全退路，Task 4 有专门用例守它

**全量单测命令**（AGENTS.md §11.6，本机没有 `.venv-warrior`，用嵌入式 python）：

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest \
  tests.test_farm_logic tests.test_warrior_debug_offline tests.test_farm_task_offline \
  tests.test_bars tests.test_guards tests.test_calibrate_offline tests.test_anchor_offline \
  tests.test_potions tests.test_anchor tests.test_ocr_engine
```

**编译检查**：

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('编译 OK')"
```

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| `src/task/farm_logic.py` | 修改 | 加纯函数 `facing_half_zone`。这个模块只做纯几何/时间判定，不碰帧、不碰按键 |
| `src/task/MapleFarmTask.py` | 修改 | 接线：配置项、状态、第二路去抖、`_do_attack` 换信号、overlay 画两个框、决策日志加字段 |
| `tests/test_farm_logic.py` | 修改 | `facing_half_zone` 纯函数单测 |
| `tests/test_farm_task_offline.py` | 修改 | 接线与回归用例 |

不新建文件：改动量小且全部落在既有职责边界内，新建模块只会让「攻击区几何」这一件事散在两处。

---

### Task 1: `facing_half_zone` 纯函数

**Files:**
- Modify: `src/task/farm_logic.py`（在 `attack_zone` 之后、`point_in_zone` 之前插入，让三个 zone 相关函数挨在一起）
- Test: `tests/test_farm_logic.py`

**Interfaces:**
- Consumes: 无
- Produces: `farm_logic.facing_half_zone(zone, body_x, facing) -> tuple[float, float, float, float]`
  - `zone`：已算好的对称区 `(x0, y0, x1, y1)`
  - `body_x`：身体中心 x
  - `facing`：`'LEFT'` / `'RIGHT'` / `None` / 任意其它值
  - 返回：同为 `(x0, y0, x1, y1)`，y 恒等于输入的 y

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_farm_logic.py` 末尾（`if __name__ == '__main__':` 之前）：

```python
class TestFacingHalfZone(unittest.TestCase):
    """有向攻击区 = 对称接敌区的面朝侧一半。

    接收「已算好的 zone」而不是 (center, width, height):调用方本来就有 zone,
    传它进去保证接敌区与攻击区严格同源,y 范围一定一致,不会因为两处各算一次而漂移。
    """

    ZONE = (880.0, 530.0, 1680.0, 730.0)   # 宽 800 高 200,身体在正中
    BODY_X = 1280.0

    def test_right_keeps_right_half(self):
        self.assertEqual(fl.facing_half_zone(self.ZONE, self.BODY_X, 'RIGHT'),
                         (1280.0, 530.0, 1680.0, 730.0))

    def test_left_keeps_left_half(self):
        self.assertEqual(fl.facing_half_zone(self.ZONE, self.BODY_X, 'LEFT'),
                         (880.0, 530.0, 1280.0, 730.0))

    def test_unknown_facing_returns_full_zone(self):
        """朝向未知 → 整个接敌区(spec §4.3)。

        不制造新的挂死风险:若改成"不知道朝向就不打",一旦转向键长期送不出去
        (窗口失焦),_facing 会一直是 None,角色就永远不攻击。回退成对称区
        最坏也只是保持改动前的表现。
        """
        self.assertEqual(fl.facing_half_zone(self.ZONE, self.BODY_X, None), self.ZONE)

    def test_invalid_facing_returns_full_zone(self):
        """非法朝向值不许抛——朝向是别处写进来的字符串,这里只做几何。"""
        for bad in ('UP', '', 'left', 0):
            self.assertEqual(fl.facing_half_zone(self.ZONE, self.BODY_X, bad), self.ZONE)

    def test_y_range_never_changes(self):
        for facing in ('LEFT', 'RIGHT', None, 'UP'):
            _, y0, _, y1 = fl.facing_half_zone(self.ZONE, self.BODY_X, facing)
            self.assertEqual((y0, y1), (530.0, 730.0))

    def test_body_outside_zone_degenerates_not_raises(self):
        """锚点外推/回退可能让 body_x 落到 zone 外。不许抛;
        退化成空矩形(x0 >= x1)即可,point_in_zone 天然判否。"""
        z = fl.facing_half_zone(self.ZONE, 100.0, 'LEFT')   # 身体在区左外侧
        self.assertEqual(z[1], 530.0)
        self.assertEqual(z[3], 730.0)
        self.assertFalse(fl.point_in_zone((1000.0, 630.0), z))

    def test_boundary_point_on_body_belongs_to_both_facings(self):
        """正压在身上的怪(x == body_x)两个朝向都算命中:
        这种怪的左右判定纯是噪声,与 farm_logic._on_side 的既有约定一致。"""
        for facing in ('LEFT', 'RIGHT'):
            z = fl.facing_half_zone(self.ZONE, self.BODY_X, facing)
            self.assertTrue(fl.point_in_zone((self.BODY_X, 630.0), z))
```

（该文件顶部已有 `from src.task import farm_logic as fl`，`fl` 别名可直接用。）

- [ ] **Step 2: 跑测试确认失败**

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_logic.TestFacingHalfZone -v
```

Expected: FAIL，`AttributeError: module 'src.task.farm_logic' has no attribute 'facing_half_zone'`

- [ ] **Step 3: 实现**

在 `src/task/farm_logic.py` 的 `attack_zone`（`:46`）之后插入：

```python
def facing_half_zone(zone, body_x, facing):
    """有向攻击区 = 对称接敌区 zone 的面朝侧一半 (x0, y0, x1, y1)。

    为什么要分两个区(spec §2):对称区在同时干两件事——决定「要不要转向」
    (必须看左右两侧,不看背后就不知道有没有值得转过去的怪)和决定「能不能打」
    (有向技能只有面朝侧的怪打得到)。魔法箭/近战是面朝向直线技能,
    拿对称区判「能不能打」会在「怪在背侧 + 转向被冷却挡住」时按出空技能。

    朝向未知/非法 → 原样返回整个 zone,退化成改动前行为(不制造挂死风险,
    见 spec §4.3)。y 范围任何分支下都不变——攻击区与接敌区必须严格同源。
    body_x 落在 zone 外(锚点外推/回退)时返回退化空矩形,不抛。
    """
    x0, y0, x1, y1 = zone
    if facing == 'RIGHT':
        return max(x0, body_x), y0, x1, y1
    if facing == 'LEFT':
        return x0, y0, min(x1, body_x), y1
    return zone
```

- [ ] **Step 4: 跑测试确认通过**

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_logic.TestFacingHalfZone -v
```

Expected: PASS，7 个用例

- [ ] **Step 5: 提交**

```bash
git add src/task/farm_logic.py tests/test_farm_logic.py
git commit -m "feat: farm_logic.facing_half_zone 有向攻击区纯函数

对称接敌区切出面朝侧一半。朝向未知/非法原样返回整区(不制造挂死风险),
y 范围恒等于输入(攻击区与接敌区严格同源),body_x 在区外时退化成空矩形不抛。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: 配置项 `攻击区形状`

**Files:**
- Modify: `src/task/MapleFarmTask.py`（`DEFAULT_CONFIG` `:18-63`、`config_type` 注册 `:101-102`、说明文案 dict `:106` 附近）
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: 无
- Produces: `DEFAULT_CONFIG['攻击区形状']`，取值 `'单体(面朝)'`（默认）或 `'群体(对称)'`

本任务只加配置，不改行为——单独成任务是因为它可以被独立 review（默认值选错是个单独的、可以否决的决定），且 Task 3 需要它已存在。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_farm_task_offline.py` 末尾（`if __name__ == '__main__':` 之前）：

```python
class TestAttackZoneShapeConfig(unittest.TestCase):
    """攻击区形状配置项。群体(对称)是安全退路,必须逐键等同于改动前行为。"""

    def test_default_is_directional(self):
        """默认单体:用户技能是魔法箭(面朝向直线),对称区从建模上就错。"""
        self.assertEqual(DEFAULT_CONFIG['攻击区形状'], '单体(面朝)')

    def test_registered_as_drop_down(self):
        """GUI 里必须是下拉,不能是自由文本框——手打错一个字就静默退回对称区。"""
        task = make_task()
        task.config_type = {}
        MapleFarmTask._register_config_types(task)
        self.assertEqual(task.config_type['攻击区形状'],
                         {'type': 'drop_down', 'options': ['单体(面朝)', '群体(对称)']})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline.TestAttackZoneShapeConfig -v
```

Expected: FAIL — `KeyError: '攻击区形状'`，以及 `AttributeError: ... has no attribute '_register_config_types'`

- [ ] **Step 3: 实现**

3a. `DEFAULT_CONFIG` 里，在 `'攻击区宽(像素)': 600,` 那一行**之前**插入：

```python
    '攻击区形状': '单体(面朝)',
```

3b. 把 `:101-102` 那两行 `config_type` 注册抽成方法（测试要能单独调它），在类里新增：

```python
    def _register_config_types(self):
        """GUI 控件类型注册。抽成方法是为了能离线断言注册内容——
        这几个键写成自由文本框的话,用户手打错一个字会静默退回默认分支。"""
        self.config_type['攻击模式'] = {'type': 'drop_down', 'options': ['定频', '检测']}
        self.config_type['朝向'] = {'type': 'drop_down', 'options': ['自动', '左', '右']}
        self.config_type['攻击区形状'] = {'type': 'drop_down',
                                          'options': ['单体(面朝)', '群体(对称)']}
```

然后把原来 `:101-102` 那两行替换成 `self._register_config_types()`。

3c. 说明文案 dict 里（`'攻击区宽(像素)'` 那条附近）加一条：

```python
            '攻击区形状': '单体(面朝):只打面朝侧半区,射程 = 攻击区宽的一半。魔法箭/近战这类面朝向技能选它——对称区会在「怪在背侧且转向还在冷却」时按出空技能。群体(对称):打整个攻击区,行为等同于此功能上线前,作为安全退路保留',
```

- [ ] **Step 4: 跑测试确认通过**

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline.TestAttackZoneShapeConfig -v
```

Expected: PASS，2 个用例

- [ ] **Step 5: 跑全量单测确认没碰坏别的**

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest \
  tests.test_farm_logic tests.test_warrior_debug_offline tests.test_farm_task_offline \
  tests.test_bars tests.test_guards tests.test_calibrate_offline tests.test_anchor_offline \
  tests.test_potions tests.test_anchor tests.test_ocr_engine 2>&1 | tail -4
```

Expected: `OK (skipped=2)`

- [ ] **Step 6: 提交**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 加 攻击区形状 配置(单体(面朝)/群体(对称)),默认单体

config_type 注册抽成 _register_config_types() 以便离线断言:这几个键写成
自由文本框的话,用户手打错一个字会静默退回默认分支。本提交只加配置不改行为。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: 第二路信号 `_last_attack_present` + `_do_attack` 换信号

这是本计划的核心任务，也是 §1 那个 bug 真正消失的地方。

**Files:**
- Modify: `src/task/MapleFarmTask.py`（`_reset_state` `:155` 附近、`_detect_and_act` `:414-435`、`_do_attack` `:544-559`）
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: `farm_logic.facing_half_zone`（Task 1）、`DEFAULT_CONFIG['攻击区形状']`（Task 2）
- Produces: `self._last_attack_present`（`True`/`False`/`None`）、`self._last_attack_seen`（float 或 `None`）。**只有 `_do_attack` 读 `_last_attack_present`**；`_last_mob_present` 的语义与四个消费者一个都不变

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_farm_task_offline.py` 末尾：

```python
class TestDirectionalAttackZone(unittest.TestCase):
    """有向攻击区:「能不能打到」与「要不要转向」分开判(spec §4)。

    几何:角色名为空 → 锚点回退画面中心 (1280, 720) → 身体 (1280, 630);
    默认 攻击区宽=600 高=200 → 接敌区 x∈[980,1580] y∈[530,730]。
    面朝右的攻击区 = x∈[1280,1580];面朝左 = x∈[980,1280]。
    怪框 (x, y, w, h) 的中心 = (x + w/2, y + h/2)。
    """

    LEFT_MOB = dict(x=1020, y=605, width=60, height=50)    # 中心 (1050, 630) 在左半区
    RIGHT_MOB = dict(x=1450, y=605, width=60, height=50)   # 中心 (1480, 630) 在右半区

    @staticmethod
    def _attacked(task, keys):
        return call(keys['攻击键']) in task.send_key.call_args_list

    def _run(self, task, mob):
        task.find_mobs = MagicMock(return_value=[MagicMock(**mob)])
        run_with_frame(task)

    def test_directional_attacks_mob_on_facing_side(self):
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        self._run(task, self.RIGHT_MOB)
        self.assertTrue(task._last_attack_present)
        self.assertTrue(self._attacked(task, KEYS))

    def test_directional_does_not_attack_mob_behind_while_turn_on_cooldown(self):
        """核心回归(spec §1):面朝右、怪只在左、转向冷却未过 → 一定不按攻击键。

        改动前:mob_present 来自对称区 → True → _do_attack 照按 → 面朝右打左边的怪。
        转向冷却 1.5s 比攻击间隔还长,这个窗口一点都不罕见。
        """
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        task._last_turn = 99.9          # run_with_frame 默认 now=100.0,即 0.1s 前刚转过向
        self._run(task, self.LEFT_MOB)
        self.assertTrue(task._last_mob_present)      # 接敌区有怪:不寻怪、不坐椅
        self.assertFalse(task._last_attack_present)  # 攻击区没怪
        self.assertFalse(self._attacked(task, KEYS))

    def test_turn_this_tick_still_no_attack_until_next_tick(self):
        """冷却已过 → 本拍转向,但本拍仍不攻击;下一拍朝向已对才攻击。

        攻击区用的是本拍转向「之前」的朝向——用转向后的新 _facing 立刻判定,
        等于又一次相信"我按了键所以已经转过去了"这个盲写信念,而那正是
        这一系列 bug 的来源(spec §5.1)。
        """
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        task._last_turn = 0.0           # 哨兵:冷却天然放行
        self._run(task, self.LEFT_MOB)
        self.assertIn(call(KEYS['左移键'], down_time=TURN_TAP_SECONDS),
                      task.send_key.call_args_list)
        self.assertFalse(self._attacked(task, KEYS))
        self.assertEqual(task._facing, 'LEFT')

        task.send_key.reset_mock()
        task._last_attack = 0.0         # 放行攻击间隔
        task._last_detect = 0.0         # 放行检测拍
        self._run(task, self.LEFT_MOB)
        self.assertTrue(self._attacked(task, KEYS))

    def test_unknown_facing_falls_back_to_symmetric(self):
        """朝向未知 → 攻击区 = 整个接敌区(spec §4.3),不制造挂死风险。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = None
        self._run(task, self.LEFT_MOB)
        self.assertTrue(task._last_attack_present)

    def test_aoe_shape_is_key_for_key_identical_to_symmetric(self):
        """群体(对称)必须逐键等同于改动前:安全退路。"""
        task = make_task(**{'攻击模式': '检测', '攻击区形状': '群体(对称)'})
        task._facing = 'RIGHT'
        task._last_turn = 99.9
        self._run(task, self.LEFT_MOB)
        self.assertTrue(task._last_attack_present)
        self.assertTrue(self._attacked(task, KEYS))

    def test_mob_behind_does_not_trigger_seek(self):
        """怪在背侧走「转向」分支而不是「寻怪」分支——接敌区仍然有怪。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        task._last_turn = 99.9
        self._run(task, self.LEFT_MOB)
        self.assertIsNone(task._seek_dir)

    def test_sit_still_driven_by_engage_zone(self):
        """坐椅/走位/忙判定问的是「附近有没有怪」,不是「打不打得到」——
        怪在背侧(打不到但就在旁边)时不许坐下。直接把 _last_mob_present
        换成有向的会一起改坏这三者,本例守住其中最容易观察的坐椅。"""
        task = make_task(**{'攻击模式': '检测', '坐椅开关': True, '坐椅延迟(秒)': 0.0})
        task._facing = 'RIGHT'
        task._last_turn = 99.9
        self._run(task, self.LEFT_MOB)
        self.assertFalse(task._last_attack_present)   # 确实打不到
        self.assertNotIn(call(KEYS['椅子键(可留空)']), task.send_key.call_args_list)
        self.assertTrue(task._last_busy > 0)          # 但算「忙」,走位倒计时重算

    def test_attack_debounce_is_independent(self):
        """攻击区自己一路去抖:漏检一拍,丢怪保持 内仍算能打
        (YOLO 单帧 recall 0.886,且角色自己的攻击特效会遮挡目标)。"""
        task = make_task(**{'攻击模式': '检测', '丢怪保持(秒)': 1.0})
        task._facing = 'RIGHT'
        self._run(task, self.RIGHT_MOB)
        self.assertTrue(task._last_attack_present)
        task.find_mobs = MagicMock(return_value=[])      # 这一拍漏检
        task._last_detect = 0.0
        run_with_frame(task, now=100.5)                  # 0.5s 后,仍在 1.0s 保持内
        self.assertTrue(task._last_attack_present)
```

`KEYS` / `make_task` / `run_with_frame` / `TURN_TAP_SECONDS` / `call` 都是该测试文件里已有的（文件顶部已导入）。

- [ ] **Step 2: 跑测试确认失败**

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline.TestDirectionalAttackZone -v
```

Expected: FAIL，`AttributeError: 'MapleFarmTask' object has no attribute '_last_attack_present'`

- [ ] **Step 3: 实现**

3a. `_reset_state()` 里，在 `self._last_mob_seen = None` 那一行**之后**插入：

```python
        self._last_attack_present = None  # 有向攻击区内有没有怪(去抖后);只有 _do_attack 读它
        self._last_attack_seen = None     # 上次有向攻击区内真检测到怪的时刻;None=从未见过(去抖用)
```

3b. `_detect_and_act` 里，在 `zone = farm_logic.attack_zone(...)`（`:416`）之后插入：

```python
        # 有向攻击区 = 接敌区的面朝侧一半(spec §4)。zone 从此是「接敌区」:
        # 管转向/寻怪/坐椅/走位;attack_area 管「能不能打」,只喂 _do_attack。
        # 用的是本拍转向「之前」的 self._facing——此处 facing_before 还没赋值,
        # 但同值。拿转向后的新朝向立刻判定等于又一次相信盲写信念(spec §5.1)。
        attack_area = (zone if cfg.get('攻击区形状') == '群体(对称)'
                       else farm_logic.facing_half_zone(zone, body[0], self._facing))
```

3c. 在 `self._last_mob_present = mob_present`（`:433`）之后插入第二路去抖：

```python
        raw_attack = farm_logic.mob_in_zone(centres, attack_area)
        if raw_attack:
            self._last_attack_seen = now
        self._last_attack_present = farm_logic.mob_present_debounced(
            raw_attack, now, self._last_attack_seen, cfg['丢怪保持(秒)'])
```

3d. `_do_attack`（`:557`）把

```python
        if self._last_mob_present and farm_logic.should_attack(
```

改成

```python
        if self._last_attack_present and farm_logic.should_attack(
```

3e. `_do_attack` 的 docstring 第一行改成：

```python
        """攻击:检测模式且最近一次检测拍「有向攻击区」内有怪 → 按 攻击间隔 轻点攻击键。
```

3f. `_detect_and_act` 的 docstring 里 `按"_last_mob_present"以 攻击间隔 轻点` 改成 `按"_last_attack_present"以 攻击间隔 轻点`。

**不要动**：`:529` 坐椅、`:753` 忙判定、`:765` 走位——这三处继续用 `_last_mob_present`。

- [ ] **Step 4: 跑测试确认通过**

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline.TestDirectionalAttackZone -v
```

Expected: PASS，8 个用例

- [ ] **Step 5: 跑全量单测**

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest \
  tests.test_farm_logic tests.test_warrior_debug_offline tests.test_farm_task_offline \
  tests.test_bars tests.test_guards tests.test_calibrate_offline tests.test_anchor_offline \
  tests.test_potions tests.test_anchor tests.test_ocr_engine 2>&1 | tail -6
```

Expected: `OK (skipped=2)`

**若有既有用例转红**：先判断是「行为真的坏了」还是「老断言被绑死在对称区上」。默认单体后，凡是「面朝某侧 + 怪在另一侧 + 断言按了攻击键」的老用例都会失败——那类用例应改成显式传 `'攻击区形状': '群体(对称)'`（它们测的是改动前的语义），而不是放宽断言。**不许为了让测试变绿而删断言。**

- [ ] **Step 6: 提交**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 有向攻击区——「能不能打到」与「要不要转向」分开判

_do_attack 改读新的 _last_attack_present(有向攻击区,独立去抖);
_last_mob_present 保持原名原义,继续驱动转向/寻怪分支、坐椅、忙判定、走位——
那三者问的是「附近有没有怪」,不是「打不打得到」,直接替换会一起改坏。

修掉的 bug:面朝右、怪只在左、转向被 转向冷却 挡住时,改动前照样按攻击键
= 确定性挥空,与朝向信念无关。攻击区用本拍转向「之前」的朝向,所以转向后
要等下一拍才攻击——用转向后的新 _facing 立刻判定等于又一次相信盲写信念。

attack_turn_direction 一个字没动,不重踩已验证失败的方案。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: 可观测性——overlay 画两个框 + 决策日志加字段

**Files:**
- Modify: `src/task/MapleFarmTask.py`（`_draw_debug` `:364-398`、`_detect_and_act` 调用处 `:435`、`_log_decision` `:481-495`、调用处 `:477`）
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: `self._last_attack_present`、`attack_area`（Task 3）
- Produces: `_draw_debug(cfg, body, zone, attack_area, mobs, mob_present, attack_present)`；决策日志行新增 `可打区内=M` 与 `可打=Y/-` 两个字段

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_farm_task_offline.py` 末尾：

```python
class TestDirectionalDecisionLog(unittest.TestCase):
    """决策日志要能回答「有向区到底生效没有」——这是实弹判据 A 的唯一数据源。"""

    @staticmethod
    def _lines(task):
        return [c.args[0] for c in task.log_debug.call_args_list
                if c.args and str(c.args[0]).startswith('决策')]

    def test_logs_attack_zone_count_and_flag(self):
        task = make_task(**{'攻击模式': '检测', '决策日志开关': True})
        task._facing = 'RIGHT'
        task._last_turn = 99.9
        task.find_mobs = MagicMock(return_value=[
            MagicMock(x=1020, y=605, width=60, height=50),   # 中心 1050,接敌区内、攻击区外
            MagicMock(x=1450, y=605, width=60, height=50),   # 中心 1480,两个区都在内
        ])
        run_with_frame(task)
        line = self._lines(task)[0]
        self.assertIn('区内=2', line)
        self.assertIn('可打区内=1', line)
        self.assertIn('可打=True', line)

    def test_attack_count_never_exceeds_engage_count(self):
        """单体模式下 可打区内 <= 区内 必须恒成立(判据 A 的几何自洽检查)。"""
        task = make_task(**{'攻击模式': '检测', '决策日志开关': True})
        for facing in ('LEFT', 'RIGHT', None):
            task._facing = facing
            task._last_detect = 0.0
            task.find_mobs = MagicMock(return_value=[
                MagicMock(x=1020, y=605, width=60, height=50),
                MagicMock(x=1450, y=605, width=60, height=50),
            ])
            run_with_frame(task)
        for line in self._lines(task):
            engage = int(re.search(r'区内=(\d+)', line).group(1))
            attack = int(re.search(r'可打区内=(\d+)', line).group(1))
            self.assertLessEqual(attack, engage, line)
```

若 `tests/test_farm_task_offline.py` 顶部还没 `import re`，加上。

- [ ] **Step 2: 跑测试确认失败**

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline.TestDirectionalDecisionLog -v
```

Expected: FAIL，日志行里没有 `可打区内=`

- [ ] **Step 3: 实现**

3a. `_log_decision` 签名加两个参数，改成：

```python
    def _log_decision(self, source, anchor_hit, body, zone, attack_area, centres,
                      raw_present, mob_present, attack_present, facing_before, turn):
```

在方法体里 `left = sum(...)` 之后插入：

```python
        attack_in = [x for x, y in centres
                     if farm_logic.point_in_zone((x, y), attack_area)]
```

日志字符串里，`f'实测有怪={raw_present} 有怪={mob_present} '` 这一行**之后**插入一行：

```python
            f'可打区内={len(attack_in)} 可打={attack_present} '
```

3b. 调用处（`:477`）改成：

```python
            self._log_decision(source, anchor_hit, body, zone, attack_area, centres,
                               raw_present, mob_present, self._last_attack_present,
                               facing_before, turn)
```

3c. `_draw_debug` 签名改成：

```python
    def _draw_debug(self, cfg, body, zone, attack_area, mobs, mob_present, attack_present):
```

docstring 第一行改成：

```python
        """画玩家框(绿)/接敌区框(细,蓝=无怪红=有怪)/攻击区框(粗,同色)/怪物框(黄)+脚底点(青)。
```

方法体里 `zone_color = ...` 之后加：

```python
        ax0, ay0, ax1, ay1 = attack_area
        attack_color = ZONE_HOT_COLOR if attack_present else ZONE_IDLE_COLOR
```

`paint()` 内部，把原来那段攻击区绘制

```python
            painter.setPen(QPen(zone_color, 3))
            painter.drawRect(rect(zx0, zy0, zx1 - zx0, zy1 - zy0))
            painter.drawText(rect(zx0, zy0 - 20, 100, 20), '攻击区')
```

替换成

```python
            # 接敌区:细线,管转向/寻怪。攻击区:粗线,管按不按攻击键——
            # 单体模式下它只占接敌区的面朝侧一半,视觉验收就看这个(判据 D)
            painter.setPen(QPen(zone_color, 1))
            painter.drawRect(rect(zx0, zy0, zx1 - zx0, zy1 - zy0))
            painter.drawText(rect(zx0, zy0 - 20, 100, 20), '接敌区')

            painter.setPen(QPen(attack_color, 4))
            painter.drawRect(rect(ax0, ay0, ax1 - ax0, ay1 - ay0))
            painter.drawText(rect(ax0, ay1 + 4, 100, 20), '攻击区')
```

3d. `_draw_debug` 调用处（`:435`）改成：

```python
            self._draw_debug(cfg, body=body, zone=zone, attack_area=attack_area,
                             mobs=mobs, mob_present=mob_present,
                             attack_present=self._last_attack_present)
```

**注意**：`drawRect` 收 `QRectF`、`drawPoint` 收 `QPointF`。这个仓库踩过一次——`dfcd08e fix: 调试 overlay 怪物框不显示——drawPoint 误传 QRectF`，代码全对、单测全绿，框就是画不出来。所以本任务必须走 Task 5 的截图验收。

- [ ] **Step 4: 跑测试确认通过**

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline.TestDirectionalDecisionLog -v
```

Expected: PASS，2 个用例

- [ ] **Step 5: 全量单测 + 编译检查**

```bash
export PYTHONUTF8=1
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest \
  tests.test_farm_logic tests.test_warrior_debug_offline tests.test_farm_task_offline \
  tests.test_bars tests.test_guards tests.test_calibrate_offline tests.test_anchor_offline \
  tests.test_potions tests.test_anchor tests.test_ocr_engine 2>&1 | tail -4
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('编译 OK')"
```

Expected: `OK (skipped=2)` + `编译 OK`

- [ ] **Step 6: 提交**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: overlay 画接敌区+攻击区两个框,决策日志加 可打区内/可打

overlay:接敌区细线、攻击区粗线,单体模式下后者只占面朝侧一半——这是
E2E 视觉验收(判据 D)要看的东西。
日志:加 可打区内=M 可打=Y/-,实弹判据 A(可打区内 <= 区内 恒成立、
可打/有怪 比值落在 0.3-0.8)靠它算。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: E2E 截图 + 视觉验收（AGENTS.md §11.3 硬门槛）

**Files:**
- Create: `screenshots/e2e/directional_attack_zone/overlay_<YYYYMMDD>.png`（注意 `screenshots/` 在 `.gitignore` 里，截图**不入库**，验收结论写进本计划的勾选项与 spec）
- 用到: `scripts/_e2e_capture.py`

**Interfaces:**
- Consumes: Task 4 的 overlay
- Produces: 视觉验收结论（PASS/FAIL）

**这一步不是可选的。** Task 4 画的是两个矩形，单测能断言 `facing_half_zone` 返回的元组对，**断言不了 painter 真的把粗框画在了面朝那一侧**。这正是 `dfcd08e` 那个 bug 的同类风险，而且这次画两个框还带朝向，画错的方式更多。

本特性的 E2E 比 AGENTS.md §11.7 那次重：那次验的是「GUI 能启动、任务能注册」，不需要游戏；**这次要看 overlay 上的攻击区，必须有真实帧**（锚点 OCR + YOLO 都得跑起来），所以游戏得开着、且 2560×1440。

- [ ] **Step 1: 起 GUI（需管理员）**

停掉占用 WGC 的旧 GUI，然后以**管理员**启动 `main_debug.py`。记下 PID。

游戏窗口要在 2560×1440、角色站在有怪的地图里。

- [ ] **Step 2: 打开功能**

GUI 里：`攻击模式` = `检测`、`攻击区形状` = `单体(面朝)`、`角色名` 填 `Yufeng咕咕`、打开 `启用标记框`、启用 MapleFarmTask。

- [ ] **Step 3: 截图**

```bash
"/h/ok-mxd/data/apps/ok-ww/python/python.exe" scripts/_e2e_capture.py <pid> screenshots/e2e/directional_attack_zone/overlay_20260807.png
```

分别截**面朝左**和**面朝右**各一张（等角色自然转向，或手动走一步），文件名加 `_left` / `_right`。两张都要。

- [ ] **Step 4: 视觉验收**

把两张图交给视觉验收（本会话里直接读图即可）。**通过判据，全部满足才算 PASS：**

1. 画面上有**两个矩形**：一个细线、一个粗线
2. 粗框（攻击区）**只覆盖角色的一侧**，不是左右对称
3. 粗框所在那一侧**与角色精灵的面朝方向一致**（看靴子尖朝向与刘海覆盖侧）
4. 粗框与细框的 **y 范围完全一致**（上下边对齐）
5. 粗框宽度约等于细框的一半
6. `_left` 与 `_right` 两张图里，粗框分别在细框的左半和右半

任一条不满足 → FAIL，回 Task 4 修，不许带病进 Task 6。

- [ ] **Step 5: 记录结论**

把 PASS/FAIL 与截图路径写进本文件本任务下方，并同步到 spec `§7.3 判据 D`。

---

### Task 6: 实弹验证（判据 A / B / C）

**Files:**
- 数据源: `logs/ok-script.log`
- Produces: 判据 A/B/C 的实测结论，写进 spec §7.3

前置：Task 5 判据 D 已 PASS。

- [ ] **Step 1: 判据 A —— 有向区确实生效**

开 `决策日志开关` + `攻击区形状=单体(面朝)`，挂机 10 分钟。

```bash
grep -c '决策' logs/ok-script.log
grep -oE '区内=[0-9]+ .*可打区内=[0-9]+' logs/ok-script.log | head
```

判据（事先写死）：
- `可打区内 > 区内` 的行数必须为 **0**
- `可打=True` 的拍数 ÷ `有怪=True` 的拍数 落在 **0.3–0.8**

比值 = 1.0 → 有向区没生效（或形状配成了群体）。**A 不过则 B/C 无意义，先修。**

- [ ] **Step 2: 判据 B —— 不变差**

同一地图、同一时段，`攻击区形状` 单体/群体**交替各跑 3 轮 × 10 分钟**，记每轮每分钟经验增长。

通过线：**单体组中位数 ≥ 群体组中位数 × 0.9**。

低于 0.9 → 射程估计错（半宽 < 魔法箭真实射程）。**先用 `scripts/calibrate_attack_zone.py` 标定再调 `攻击区宽(像素)` 重测，不许直接回滚了事** —— 回滚只是把挥空重新藏起来。

（0.9 是事先约定的通过线，不是效果预测。经验噪声大，交替 3 轮取中位是为了压掉刷新率波动。）

- [ ] **Step 3: 判据 C —— 症状消失**

同一批日志里，`受击` 之后 3 秒内的拍，`可打=True` 的占比应**低于**全局 `可打=True` 占比——即受击后确实进入了「不乱打、先转向」的状态。

并由用户主观确认：不再出现「背对怪挥空」。

- [ ] **Step 4: 把 A/B/C 实测数值写进 spec §7.3**

包括不通过的项。**未全部通过前，不得声称此 bug 已修复。**

- [ ] **Step 5: 提交验收记录**

```bash
git add docs/superpowers/specs/2026-08-07-directional-attack-zone-design.md docs/superpowers/plans/2026-08-07-directional-attack-zone.md
git commit -m "docs: 有向攻击区 E2E + 实弹验收结论

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## 收尾:旧 spec 的处置

判据 A/B/C 出结果后，回头处置 `docs/superpowers/specs/2026-08-07-facing-reassert-on-hit-design.md`：

- 若 C 通过（症状消失）→ 在该 spec 顶部标「**已撤销**：被上游 `cf4ee6f` + 有向攻击区共同覆盖」，保留附录 A 的 24 帧模板匹配实测数据
- 若 C 不通过 → 说明朝向信念错本身仍在造成可观测损失，按该 spec 的 §4（受击后重申朝向）重新评估，**但行号需按合并后代码全部重校**
