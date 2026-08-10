# 群攻 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接敌区内怪数达到阈值时，改按独立的群攻键（前后双向命中），且那一拍不转向、不按单体攻击键。

**Architecture:** 计数区复用现有「接敌区」（对称 `攻击区宽×攻击区高`，判定点=框中心），不新增区、不新增射程参数。转向门与攻击门共用一个 `_aoe_ready(cfg, keys, now)` 判据方法，保证「同一拍不转向 ⟺ 同一拍真发群攻」。群攻发出时同时推进 `_last_attack`，防止 `攻击间隔(秒)` 被调到低于群攻施法时长（约 1 秒）时，单体攻击键落在自己的群攻施法中间把它打断。

**Tech Stack:** Python 3 / OpenCV / PySide6(Qt overlay) / unittest（纯 stdlib，无 pytest）

**Spec:** `docs/superpowers/specs/2026-08-09-aoe-attack-design.md`

## Global Constraints

- **禁止 hard code 本地路径**（AGENTS.md §11.1）：`src/` `scripts/` `tests/` 不许出现 `C:/` `H:/` `/Users/` `AppData` 等绝对路径。
- **新增/修改纯逻辑必须同步加 unittest**（AGENTS.md §11.2），覆盖正常/边界/异常路径。
- **测试框架是 `unittest`，不是 pytest。** 运行命令一律：
  `$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest <模块或用例> -v`
- **注释用中文，与文件既有风格一致**；解释「为什么」而不是「做了什么」，引用实测数据/spec 章节。
- **代码注释里不写全角标点以外的特殊字符**，沿用文件既有写法（半角逗号 `,` 常见于本仓库注释，保持一致即可）。
- **热重载注意**：改了 `farm_logic.py` / `config.py` 必须重启 GUI（`importlib.reload` 不递归依赖）。
- **提交信息格式**：`<type>: <中文一句话>`，正文说明「为什么」。type 用 `feat` / `fix` / `docs` / `test`。
- **不许改** `decision_log_line` / `divergence_log_line` 的字段格式（两个 analyze 脚本的正则 + 绑定测试吃它）。

### 本次涉及的几何前提（写测试必须知道）

`DEFAULT_CONFIG['角色名']` 是**空串**，`_resolve_anchor()` 在 `:410-412` 直接 `return centre, 'fallback'` —— **`anchor.find_in_region` 根本不会被调用**。所以本计划的测试**不 patch 锚点**，走的是回退路径：

- 锚点 = 画面中心 `(2560/2, 1440/2) = (1280, 720)`
- 身体中心 = `(1280, 720 - 90) = (1280, 630)`（`名字牌到身体偏移(像素)=90`）
- 接敌区（默认 `攻击区宽=600`、`攻击区高=200`）：`x ∈ [980, 1580]`，`y ∈ [530, 730]`
- 怪的判定点是 **bbox 中心** `(x + w/2, y + h/2)`

> 仓库里既有用例（如 `test_detect_mode_turns_then_attacks_when_mob_behind`）patch 了 `find_in_region` 并在注释里写「名字牌 (1280,800) → 身体 (1280,710)」，**那个注释是错的** —— 空 `角色名` 下 patch 不生效，实际仍走上面的回退几何。它们能过是因为怪的中心 y 恰好同时落在两套 y 范围里。本计划不沿用那个写法，也不顺手去修既有用例（超出本次范围）。

### 本次会用到的既有配置默认值（**不要按记忆写**）

| 键 | 默认值 | 在测试里的后果 |
|---|---|---|
| `攻击间隔(秒)` | **1.5** | 两拍相隔必须 ≥ 1.5 单体才会再发键；要更短的节拍就在用例里显式覆盖 |
| `转向冷却(秒)` | 1.5 | `_last_turn` 初值 0.0 是哨兵，首拍必放行 |
| `丢怪保持(秒)` | 1.0 | 攻击信号的去抖窗 |
| `硬直抑制窗(秒)` | 0.0 | 默认关闭，不干扰用例；要测抑制得显式打开 |

> 用户实机把 `攻击间隔(秒)` 调到了 0.7（见 `2026-08-07-directional-attack-zone-design.md` §3.1 的实跑配置），spec 的部分论证按 0.7 叙述。**默认配置是 1.5**，写测试和写 GUI 文案时一律以默认值为准。

### 新配置键一览（后续任务都会用到）

| 键 | 位置 | 默认 |
|---|---|---|
| `群攻键(可留空)` | `config.py` 全局「游戏按键」 | `''` |
| `群攻怪数阈值` | `MapleFarmTask.DEFAULT_CONFIG` | `3` |
| `群攻间隔(秒)` | `MapleFarmTask.DEFAULT_CONFIG` | `2.0` |

### 新增状态一览

| 状态 | 初值 | 含义 |
|---|---|---|
| `self._last_aoe` | `0.0` | 上次按下群攻键的时刻；`0.0` 哨兵 = 从未群攻，天然放行节拍 |
| `self._last_zone_count` | `0` | 最近一次检测拍**接敌区内怪数**；`0` = 还没检测过 |

> **为什么存计数而不是布尔**（spec §3.5 同步已更新）：少一个要同步的状态；阈值在 `_aoe_ready` 里**用时现读**，GUI 改 `群攻怪数阈值` 立刻生效，不用等下一个检测拍；日志行也正好要这个计数。

---

### Task 1: 纯函数 `crowd_present`

**Files:**
- Modify: `src/task/farm_logic.py`（追加到文件末尾）
- Test: `tests/test_farm_logic.py`

**Interfaces:**
- Consumes: 无
- Produces: `farm_logic.crowd_present(mob_count: int, threshold: int) -> bool`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_farm_logic.py` 的 `TestFarmLogic` 类里（放在类的最后一个测试方法之后）：

```python
    def test_crowd_present(self):
        # 等于阈值算命中:阈值语义是「达到就用群攻」,与 should_attack 的 >= 同口径
        self.assertTrue(fl.crowd_present(3, 3))
        self.assertTrue(fl.crowd_present(4, 3))
        self.assertFalse(fl.crowd_present(2, 3))
        self.assertFalse(fl.crowd_present(0, 3))
        # 阈值 <= 0 = 功能关闭,不许因为「0 只怪 >= 0」而恒真
        self.assertFalse(fl.crowd_present(5, 0))
        self.assertFalse(fl.crowd_present(5, -1))
        self.assertFalse(fl.crowd_present(0, 0))
```

- [ ] **Step 2: 跑测试确认它失败**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_logic.TestFarmLogic.test_crowd_present -v
```

Expected: FAIL —— `AttributeError: module 'src.task.farm_logic' has no attribute 'crowd_present'`

- [ ] **Step 3: 写实现**

追加到 `src/task/farm_logic.py` 末尾：

```python
def crowd_present(mob_count, threshold):
    """接敌区内怪数达到阈值 → 该用群攻(前后双向命中,不需要朝向)。

    计数用**原始**区内怪数,不做去抖:YOLO 单帧 recall 0.886,4 只可能读成 3 只,
    但那只会晚一个检测拍放群攻;反过来加保持窗会在怪清光后仍按旧计数
    多放一发空群攻,浪费的是蓝。与 丢怪保持/寻怪保持 取舍方向不同,是因为那两处
    的失败代价是「停手/停步」,这里只是「晚一拍」(spec §3.10)。

    threshold <= 0 视为功能关闭,恒 False —— 否则 0 只怪 >= 0 会恒真,
    没绑群攻键时每拍都判成「该群攻」。边界取 >=(等于阈值算命中),与
    should_attack / turn_allowed 同口径。
    """
    return threshold > 0 and mob_count >= threshold
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_logic -v
```

Expected: PASS（`test_farm_logic` 整模块全绿）

- [ ] **Step 5: 提交**

```bash
git add src/task/farm_logic.py tests/test_farm_logic.py
git commit -m "feat: farm_logic 新增 crowd_present——接敌区怪数达阈值判据

阈值 <= 0 显式关闭(否则 0 只怪 >= 0 恒真);计数不去抖,漏检一拍
只是晚一个检测拍放群攻,而保持窗会在怪清光后多放一发空群攻。"
```

---

### Task 2: 三个配置键

**Files:**
- Modify: `config.py:9-23`（全局「游戏按键」）
- Modify: `src/task/MapleFarmTask.py`（`DEFAULT_CONFIG` 与 `config_description`）
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: 无
- Produces: 配置键 `群攻键(可留空)`（全局按键，默认 `''`）、`群攻怪数阈值`（默认 `3`）、`群攻间隔(秒)`（默认 `2.0`）

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_farm_task_offline.py` 末尾（文件级新类）：

```python
class TestAoeConfig(unittest.TestCase):
    """群攻的三个配置键:默认值 + 「留空=关闭」约定 + 说明文案。"""

    def test_task_defaults(self):
        self.assertEqual(DEFAULT_CONFIG['群攻怪数阈值'], 3)
        self.assertEqual(DEFAULT_CONFIG['群攻间隔(秒)'], 2.0)

    def test_global_key_defaults_to_empty(self):
        """群攻键默认留空 = 功能关闭,与 椅子键(可留空) 同一约定。"""
        from config import key_config_option
        self.assertEqual(key_config_option.default_config['群攻键(可留空)'], '')

    def test_global_key_has_description(self):
        """GUI 上没有说明的按键槽等于没有:用户不知道该往里填什么。"""
        from config import key_config_option
        self.assertIn('群攻键(可留空)', key_config_option.config_description)
```

`ConfigOption` 的属性名已核对：`ok/util/config.py:14-15` 里 `self.default_config = default or {}`、`self.config_description = config_description or {}`。

> 两个任务配置键的说明文案不在这里断言：`config_description` 是在框架 `__init__` 里 `update` 上去的，而 `make_task` 走的是 `__new__` 绕过 `__init__`（见 `tests/test_farm_task_offline.py:23`），离线拿不到。文案的正确性靠 Step 3 的代码审查保证。

- [ ] **Step 2: 跑测试确认它失败**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline.TestAoeConfig -v
```

Expected: FAIL —— `KeyError: '群攻怪数阈值'`

- [ ] **Step 3: 写实现（三处）**

**3a. `config.py`** —— 在 `'椅子键(可留空)': '',` 之后加一行，并补说明：

```python
key_config_option = ConfigOption('游戏按键', {
    '攻击键': 'ctrl',
    '血药键': 'home',
    '蓝药键': 'insert',
    '回城卷键(可留空)': '',
    '拾取键': 'z',
    '宠物食物键(可留空)': '',
    '椅子键(可留空)': '',
    '群攻键(可留空)': '',
    '左移键': 'left',
    '右移键': 'right',
}, description='冒险岛游戏内按键,与游戏内键盘设置保持一致', config_description={
    '回城卷键(可留空)': '低血保命用。留空则低血时只停止任务不逃跑',
    '宠物食物键(可留空)': '喂宠物用。先在游戏内把宠物食物拖到快捷键,再填对应按键;留空则不喂',
    '椅子键(可留空)': '坐椅用(检测模式没怪时自动坐椅子回血蓝)。先在游戏内把椅子拖到快捷键,再填对应按键;留空则不坐',
    '群攻键(可留空)': '群攻(前后双向命中)技能键。接敌区内怪数达到「群攻怪数阈值」时改按它,那一拍不转向也不按单体攻击键。留空 = 功能关闭',
}, show_at_tab=True, icon=FluentIcon.GAME)
```

**3b. `src/task/MapleFarmTask.py` 的 `DEFAULT_CONFIG`** —— 在 `'攻击区高(像素)': 200,` 之后加两行：

```python
    '攻击区高(像素)': 200,
    '群攻怪数阈值': 3,
    '群攻间隔(秒)': 2.0,
```

**3c. 同文件 `config_description`** —— 在 `'攻击区宽(像素)'` 那条之后插入两条：

```python
            '群攻怪数阈值': '接敌区内怪数达到此值就改用群攻(前后双向命中),那一拍不转向、也不按单体攻击键。需要先在设置页「游戏按键」绑定「群攻键(可留空)」,留空则本项无效。默认 3 的依据:2026-08-07 实测 800x200 接敌区里平均区内怪 0.36 只、有怪帧仅 28%、两侧都有仅 6%——阈值设 2 会让「一左一右两只」这种常见局面天天触发群攻,而那种局面转向一次就够。3 是「确实被围住了」的起点。实跑后按决策日志里的 区内=N 分布回调',
            '群攻间隔(秒)': '两次群攻的最小间隔,与「攻击间隔(秒)」各走各的。不共用是因为群攻耗蓝通常是单体的数倍,跟着单体节拍走会瞬间空蓝,还会把喝蓝逻辑一起拖抖。群攻发出时会顺带把单体攻击的节拍也推后一个「攻击间隔」:群攻施法约 1 秒,「攻击间隔(秒)」若调到比它短(默认 1.5 不会,实机常调到 0.7),不推后的话单体攻击键会落在自己的群攻施法中间把它打断',
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline.TestAoeConfig -v
```

Expected: PASS（3 个用例）

- [ ] **Step 5: 提交**

```bash
git add config.py src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 群攻三个配置键——群攻键(可留空)/群攻怪数阈值/群攻间隔(秒)

按键沿用「留空=功能关闭」约定(同 椅子键/宠物食物键),不另设开关。
阈值默认 3:实测接敌区平均 0.36 只、两侧都有仅 6%,设 2 会让
「一左一右两只」这种转向一次就够的局面天天触发群攻。"
```

---

### Task 3: `_aoe_ready` 判据 + 区内计数状态

**Files:**
- Modify: `src/task/MapleFarmTask.py` —— `_reset_state()`（约 `:212`）、`_detect_and_act()`（约 `:584`，插在 `self._detect_attacking = ...` 之后）、`_log_decision()`（约 `:740`，改签名收 `in_zone`）、新增方法 `_aoe_ready`
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: `farm_logic.crowd_present(mob_count, threshold)`（Task 1）；配置键（Task 2）
- Produces:
  - `self._last_aoe: float`、`self._last_zone_count: int`（状态）
  - `MapleFarmTask._aoe_ready(self, cfg, keys, now) -> bool`
  - `_log_decision(self, source, anchor_hit, body, zone, attack_area, centres, in_zone, mobs, raw_present, mob_present, attack_present, facing_before, turn, observed, obs_s, obs_flip)` —— **新增第 7 个位置参数 `in_zone`**

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_farm_task_offline.py` 末尾。**这段公共夹具后续 Task 4/5/6 都要用，一次写好：**

```python
AOE_KEYS = {**KEYS, '群攻键(可留空)': 'f'}


def _aoe_mob(cx, cy=650):
    """按中心点造怪:width=60 / height=50 → bbox 左上角 (cx-30, cy-25)。
    cy=650 落在接敌区纵向范围 y∈[530,730] 内(锚点走画面中心回退,见计划开头
    的几何前提:角色名为空 → _resolve_anchor 直接返回画面中心)。"""
    return MagicMock(x=cx - 30, y=cy - 25, width=60, height=50)


def _aoe_task(**cfg_overrides):
    """检测模式 + 绑好群攻键 + 关走位(走位有独立 120s 节奏,会给按键序列加噪声)。"""
    task = make_task(**{'攻击模式': '检测', '走位开关': False, **cfg_overrides})
    task.get_global_config = MagicMock(return_value=dict(AOE_KEYS))
    return task


def _run_with_mobs(task, mobs, now=100.0):
    """跑一拍。锚点走回退路径(角色名为空)→ 身体 (1280,630)、
    接敌区 x∈[980,1580] y∈[530,730]。不 patch find_in_region:
    空 角色名 下它压根不会被调用,patch 了只会给读代码的人错误暗示。"""
    task.find_mobs = MagicMock(return_value=mobs)
    run_with_frame(task, now=now)


def _sent(task):
    """本次 run 里真正送出去的按键名(丢掉 down_time 等 kwargs)。"""
    return [c.args[0] for c in task.send_key.call_args_list if c.args]


class TestAoeReady(unittest.TestCase):
    """群攻判据 _aoe_ready:转向门与攻击门的唯一事实源(spec §3.4)。"""

    def test_zone_count_snapshot(self):
        """检测拍把接敌区内怪数记进 _last_zone_count(原始计数,不去抖)。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        self.assertEqual(task._last_zone_count, 3)

    def test_zone_count_excludes_mobs_outside_zone(self):
        """区外的怪不计数:接敌区 x∈[980,1580],2000 与 500 都在区外。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(2000), _aoe_mob(500)])
        self.assertEqual(task._last_zone_count, 1)

    def test_ready_when_count_reaches_threshold(self):
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        # 时点取 102.0 而非 100.0:Task 4 落地后,跑完的 now=100.0 那一拍已真发群攻
        # (_last_aoe=100.0),同一时刻判「就绪」会被群攻间隔门拦住;等一个间隔再断言。
        # (计划原写 100.0——那是 Task 3 阶段 _do_attack 还没群攻分支时才成立的前提。)
        self.assertTrue(task._aoe_ready(task.config, dict(AOE_KEYS), 102.0))

    def test_not_ready_below_threshold(self):
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230)])
        self.assertFalse(task._aoe_ready(task.config, dict(AOE_KEYS), 100.0))

    def test_not_ready_when_key_unbound(self):
        """群攻键留空 = 功能关闭,计数够也不 ready。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        self.assertFalse(task._aoe_ready(task.config, dict(KEYS), 100.0))

    def test_not_ready_within_interval(self):
        """群攻节拍未到:上次群攻 100.0,群攻间隔 2.0 → 101.0 不放行,102.0 放行。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        task._last_aoe = 100.0
        self.assertFalse(task._aoe_ready(task.config, dict(AOE_KEYS), 101.0))
        self.assertTrue(task._aoe_ready(task.config, dict(AOE_KEYS), 102.0))

    def test_not_ready_in_fixed_rate_mode(self):
        """定频模式没有找怪信息,群攻整段不适用。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        task.config['攻击模式'] = '定频'
        self.assertFalse(task._aoe_ready(task.config, dict(AOE_KEYS), 100.0))

    def test_not_ready_while_stunned(self):
        """硬直抑制窗内不发任何技能键,群攻同样受它管。"""
        task = _aoe_task(**{'硬直抑制窗(秒)': 0.8})
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        task._last_hit = 99.9
        self.assertFalse(task._aoe_ready(task.config, dict(AOE_KEYS), 100.0))
```

- [ ] **Step 2: 跑测试确认它失败**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline.TestAoeReady -v
```

Expected: FAIL —— unittest 按方法名字母序跑，第一个红的是 `test_not_ready_below_threshold`，报 `AttributeError: 'MapleFarmTask' object has no attribute '_aoe_ready'`；`test_zone_count_snapshot` 则报 `... no attribute '_last_zone_count'`。8 个用例应当**全红**。

- [ ] **Step 3: 写实现（四处）**

**3a. `_reset_state()`** —— 在 `self._last_turn = 0.0` 那一行**之前**插入两行（挨着其他 `_last_*` 节拍状态）：

```python
        self._last_aoe = 0.0          # 上次按下群攻键的时刻;0.0 哨兵=从未群攻,天然放行节拍
        self._last_zone_count = 0     # 最近一次检测拍接敌区内怪数(群攻判据用);0=还没检测过
```

**3b. 新增方法 `_aoe_ready`** —— 放在 `_do_attack` 之前（`_mark_busy` 之后）：

```python
    def _aoe_ready(self, cfg, keys, now):
        """本拍要不要放群攻 —— 转向门(_detect_and_act)与攻击门(_do_attack)的
        唯一判据,两处必须调同一个方法。

        分头写就会出现「以为要群攻所以没转向、结果群攻没发」的两头落空拍:
        那一拍既不转向也不输出,比不做这个功能还差(spec §3.4)。

        同一 tick 内 run() 的顺序是 _detect_and_act → _do_attack,期间没有任何
        代码写 _last_aoe / _last_zone_count / _last_hit,所以两次求值必然同值。
        改动这三个状态的写入位置前,先确认这个前提还成立。

        群攻键留空 = 功能关闭(同 椅子键(可留空) 的约定);阈值在这里现读,
        GUI 里改 群攻怪数阈值 立刻生效,不用等下一个检测拍。
        """
        return bool(
            cfg['攻击模式'] == '检测'
            and keys.get('群攻键(可留空)', '')
            and farm_logic.crowd_present(self._last_zone_count,
                                         cfg['群攻怪数阈值'])
            and farm_logic.should_attack(now, self._last_aoe, cfg['群攻间隔(秒)'])
            and not farm_logic.stun_suppressed(
                now, self._last_hit, cfg['硬直抑制窗(秒)']))
```

**3c. `_detect_and_act()`** —— 在 `self._detect_attacking = farm_logic.mob_present_debounced(...)` 那两行**之后**、`facing_before, turn = belief_before_obs, None` 之前插入：

```python
        # 群攻计数:接敌区内怪数(原始值,不去抖,见 farm_logic.crowd_present)。
        # 这一份 in_zone 同时喂给决策日志——同一个数算两遍是将来漂移的种子。
        in_zone = [x for x, y in centres if farm_logic.point_in_zone((x, y), zone)]
        self._last_zone_count = len(in_zone)
```

同函数末尾把 `in_zone` 传给日志（`_log_decision` 调用处，`centres` 之后加一个参数）：

```python
        if cfg.get('决策日志开关'):
            self._log_decision(source, anchor_hit, body, zone, attack_area, centres,
                               in_zone, mobs,
                               raw_present, mob_present, self._last_attack_present,
                               facing_before, turn, observed, obs_s, obs_flip)
```

**3d. `_log_decision()`** —— 签名加 `in_zone`（放在 `centres` 之后），并**删掉**函数体里自己重算 `in_zone` 的那一行：

```python
    def _log_decision(self, source, anchor_hit, body, zone, attack_area, centres, in_zone,
                      mobs, raw_present, mob_present, attack_present, facing_before, turn,
                      observed, obs_s, obs_flip):
```

函数体里删掉这一行（`in_zone` 现在由调用方传入，与群攻计数同源）：

```python
        in_zone = [x for x, y in centres if farm_logic.point_in_zone((x, y), zone)]   # ← 删掉
```

其余一个字不改（`left = sum(...)` 起照旧）。

- [ ] **Step 4: 跑测试确认通过**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline -v
```

Expected: PASS —— `TestAoeReady` 8 个用例全绿，**且既有用例一个都没红**（`_log_decision` 改了签名，若有别的调用点会在这里暴露）。

- [ ] **Step 5: 提交**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 群攻判据 _aoe_ready + 接敌区计数快照

转向门与攻击门共用同一个判据方法:分头写会出现「以为要群攻所以
没转向、结果群攻没发」的两头落空拍,那一拍既不转向也不输出。
存计数而不是布尔,是为了让阈值在用时现读(GUI 改立刻生效),
顺便让决策日志和群攻共用同一份 in_zone,不再各算一遍。"
```

---

### Task 4: `_do_attack` 群攻分支 + 触发日志

**Files:**
- Modify: `src/task/MapleFarmTask.py` —— 模块级新增 `aoe_log_line()`（放在 `template_captured_line` 之后）、`_do_attack()`（约 `:827`）
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: `self._aoe_ready(cfg, keys, now)`（Task 3）
- Produces: `aoe_log_line(count: int, threshold: int) -> str`，格式固定为 `群攻 区内={count} 阈值={threshold}`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_farm_task_offline.py` 末尾：

```python
class TestAoeAttack(unittest.TestCase):
    """群攻按键路径:优先、二选一、节拍、日志(spec §3.5/§3.7/§4)。"""

    def test_fires_aoe_and_skips_single_attack(self):
        """区内 3 只 → 按群攻键,且本拍不按单体攻击键(二选一)。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        sent = _sent(task)
        self.assertIn('f', sent)
        self.assertNotIn('shift', sent)

    def test_single_attack_below_threshold(self):
        """区内 2 只 → 原样走单体,不按群攻键。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1230), _aoe_mob(1530)])
        sent = _sent(task)
        self.assertIn('shift', sent)
        self.assertNotIn('f', sent)

    def test_unbound_key_behaves_as_before(self):
        """群攻键留空 → 与改动前逐键一致:照常单体输出,不出现任何新键。"""
        task = make_task(**{'攻击模式': '检测', '走位开关': False})  # KEYS 无群攻键
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        sent = _sent(task)
        self.assertIn('shift', sent)
        self.assertNotIn('f', sent)
        self.assertTrue(set(sent) <= set(KEYS.values()) - {''},
                        f'出现了 KEYS 之外的按键: {sent}')

    def test_aoe_pushes_single_attack_cadence(self):
        """群攻发出时同时推进 _last_attack(spec §3.7)。

        鉴别力在「实现漏写 self._last_attack = now」那一档:漏写时 _last_attack
        停在 0.0 哨兵,第二拍 100.3 - 0.0 >= 攻击间隔(1.5) 会补发单体攻击键,
        正好落在自己的群攻施法中间。注意本用例在**实现之前**是绿的
        (那时第一拍走单体路径,同样把 _last_attack 推到 100.0)——它是回归守卫,
        不是 red-first 用例。"""
        task = _aoe_task()
        mobs = [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)]
        _run_with_mobs(task, mobs, now=100.0)
        self.assertEqual(task._last_aoe, 100.0)     # 这一拍真发了群攻(这条实现前会红)
        self.assertEqual(task._last_attack, 100.0)  # 单体节拍被一起推进
        task.send_key.reset_mock()
        _run_with_mobs(task, mobs, now=100.3)   # 未满 攻击间隔 1.5
        self.assertNotIn('shift', _sent(task))

    def test_single_resumes_while_aoe_on_cooldown(self):
        """群攻节拍未到但攻击间隔已过 → 照常单体输出(不整段停手)。

        攻击间隔显式设 0.7 而不是吃默认值:默认 1.5 与 群攻间隔 2.0 太近,
        留给「群攻还冷着、单体已放行」的窗口只有 0.5 秒,用例会贴着边界走。"""
        task = _aoe_task(**{'攻击间隔(秒)': 0.7})
        mobs = [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)]
        _run_with_mobs(task, mobs, now=100.0)   # 这一拍放群攻
        task.send_key.reset_mock()
        _run_with_mobs(task, mobs, now=101.0)   # 群攻间隔 2.0 未到,攻击间隔 0.7 已过
        sent = _sent(task)
        self.assertIn('shift', sent)
        self.assertNotIn('f', sent)

    def test_no_aoe_in_fixed_rate_mode(self):
        """定频模式:照常按单体攻击键,不按群攻键。"""
        task = _aoe_task(**{'攻击模式': '定频'})
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        sent = _sent(task)
        self.assertIn('shift', sent)
        self.assertNotIn('f', sent)

    def test_no_aoe_while_stunned(self):
        """硬直抑制窗内:群攻键和单体攻击键都不按。"""
        task = _aoe_task(**{'硬直抑制窗(秒)': 0.8})
        task._last_hit = 99.9
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)],
                       now=100.0)
        sent = _sent(task)
        self.assertNotIn('f', sent)
        self.assertNotIn('shift', sent)

    def test_logs_aoe_line(self):
        """决策日志开着时,每次真按下群攻键写一行 群攻 区内=N 阈值=M(N >= M)。"""
        task = _aoe_task(**{'决策日志开关': True})
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        lines = [c.args[0] for c in task.log_debug.call_args_list if c.args]
        aoe_lines = [ln for ln in lines if ln.startswith('群攻 ')]
        self.assertEqual(len(aoe_lines), 1, f'期望一行群攻日志,实得 {aoe_lines}')
        self.assertEqual(aoe_lines[0], '群攻 区内=3 阈值=3')

    def test_no_log_when_switch_off(self):
        """决策日志关着 → 不写群攻行(10Hz 下不限频会刷爆日志)。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        lines = [c.args[0] for c in task.log_debug.call_args_list if c.args]
        self.assertEqual([ln for ln in lines if ln.startswith('群攻 ')], [])
```

- [ ] **Step 2: 跑测试确认它失败**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline.TestAoeAttack -v
```

Expected: FAIL —— `test_fires_aoe_and_skips_single_attack` 报 `'f' not found in [...]`（群攻键从没被按过）

- [ ] **Step 3: 写实现（两处）**

**3a. 模块级 `aoe_log_line`** —— 放在 `template_captured_line` 之后：

```python
def aoe_log_line(count, threshold):
    """群攻触发行 —— 格式唯一事实源(同 decision_log_line)。

    判据 A 直接 grep 「群攻」数行数,并核对每行的 区内 >= 阈值。
    不塞进决策行是有意的:decision_log_line 被两个 analyze 脚本的正则和一批
    绑定测试吃着,为一个偶发事件改它的格式不划算(spec §4)。
    """
    return f'群攻 区内={count} 阈值={threshold}'
```

**3b. `_do_attack()`** —— 在 `if cfg['攻击模式'] != '检测': return` 之后、原单体逻辑之前插入群攻分支（原单体逻辑一个字不改）：

```python
        if cfg['攻击模式'] != '检测':
            return
        # 群攻优先,与单体二选一:被围时一发前后双向命中,比「转向 + 单体」划算,
        # 且不需要朝向(spec §3.9 行为矩阵)。
        # 同时推进 _last_attack —— 群攻施法约 1 秒,攻击间隔(秒) 若被调到比它短
        # (默认 1.5 不会,实机常调到 0.7),不推的话单体攻击键会落在自己的群攻
        # 施法中间把它打断,和 2026-08-07「长按连挥 → 改回轻点」修的是同一类
        # 按键边沿问题(spec §3.7)。默认配置下这一行是惰性的,但它兜住的是
        # 用户把节拍调快之后的情形,不该等出问题再补。
        if self._aoe_ready(cfg, keys, now):
            self.send_key(keys['群攻键(可留空)'])
            self._last_aoe = now
            self._last_attack = now
            if cfg.get('决策日志开关'):
                self.log_debug(aoe_log_line(self._last_zone_count,
                                            cfg['群攻怪数阈值']))
            return
        if (self._last_attack_present
                ...原样不动...
```

同时把 `_do_attack` 的 docstring 补一句（放在现有 docstring 的最后一行 `定频模式不在这里管...` 之前）：

```
        接敌区内怪数达到 群攻怪数阈值 时改按群攻键(前后双向命中),那一拍不按
        单体攻击键;判据见 _aoe_ready。
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline -v
```

Expected: PASS —— `TestAoeAttack` 9 个用例全绿。

**一处既有用例需同步改时点**（本计划原先漏算的跨任务交互）：Task 3 的
`test_ready_when_count_reaches_threshold` 隐含「跑完这一拍 `_last_aoe` 仍是 0.0 哨兵」，
而 Task 4 让 `_do_attack` 在 `now=100.0` 那一拍真发了群攻、把 `_last_aoe` 推成 100.0，
于是 `_aoe_ready(..., 100.0)` 被群攻间隔门拦住返回 False。这是间隔门的正确行为，不是实现
bug——把该用例断言的 `now` 从 100.0 改成 102.0（与 `test_not_ready_within_interval` 的
101.0/102.0 同口径），实现不动。其余既有用例无回归。

- [ ] **Step 5: 提交**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: _do_attack 群攻分支——达阈值改按双向技能键,与单体二选一

群攻同时推进 _last_attack:群攻施法约 1 秒,攻击间隔调到比它短时
(默认 1.5 不会,实机常调 0.7),不推的话单体攻击键会落在自己的
群攻施法中间打断它(同 2026-08-07 长按改轻点那类边沿问题)。
触发行单独 grep,不进 decision_log_line——那个格式被两个 analyze
脚本的正则和一批绑定测试吃着。"
```

---

### Task 5: 群攻拍不转向 + 寻怪互斥不变量

**Files:**
- Modify: `src/task/MapleFarmTask.py` —— `_detect_and_act()` 的转向门（约 `:674` 那个 `if turn is not None and ...`）
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: `self._aoe_ready(cfg, keys, now)`（Task 3）
- Produces: `_detect_and_act` 内局部变量 `aoe_ready`（同一拍内求值一次，Task 6 的 overlay 直接复用它）

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_farm_task_offline.py` 末尾：

```python
class TestAoeSkipsTurn(unittest.TestCase):
    """群攻双向命中,那一拍转向零收益却要付一次方向键 tap + 作废检测节拍
    (self._last_detect = 0.0)。只跳过真发群攻的那一拍(spec §3.6)。"""

    def test_no_turn_on_aoe_tick(self):
        """面朝右 + 区内 3 只全在左(本该转向) + 群攻就绪 → 不发方向键,只发群攻键。"""
        task = _aoe_task()
        task._facing = 'RIGHT'
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1130), _aoe_mob(1230)])
        sent = _sent(task)
        self.assertIn('f', sent)
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertEqual(task._facing, 'RIGHT')   # 朝向信念不动,不产生新分叉

    def test_turns_normally_below_threshold(self):
        """对照组:同样面朝右、怪在左,但只有 1 只 → 照常转向(转向逻辑没被改坏)。"""
        task = _aoe_task()
        task._facing = 'RIGHT'
        _run_with_mobs(task, [_aoe_mob(1030)])
        self.assertIn('left', _sent(task))
        self.assertEqual(task._facing, 'LEFT')

    def test_turns_normally_while_aoe_on_cooldown(self):
        """群攻节拍未到 → 转向照常(不许整段禁转向,否则冷却那 2 秒面朝空处挨打)。"""
        task = _aoe_task()
        task._facing = 'RIGHT'
        task._last_aoe = 99.5          # 群攻间隔 2.0 未到
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1130), _aoe_mob(1230)],
                       now=100.0)
        sent = _sent(task)
        self.assertNotIn('f', sent)
        self.assertIn('left', sent)

    def test_seek_and_aoe_are_mutually_exclusive(self):
        """隐式不变量:crowd 成立 ⇒ 接敌区有怪 ⇒ 走接战分支,不可能同时在寻怪。
        将来有人改 seek_hold 的算法,这条会红(spec §3.8)。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)], now=100.0)
        self.assertEqual(task._last_aoe, 100.0)   # 这一拍确实放了群攻
        self.assertIsNone(task._seek_dir)         # 同一拍不可能在寻怪
```

- [ ] **Step 2: 跑测试确认它失败**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline.TestAoeSkipsTurn -v
```

Expected: FAIL —— `test_no_turn_on_aoe_tick` 报 `'left' unexpectedly found in [...]`（转向门还没加群攻判据）

- [ ] **Step 3: 写实现（两处，同一个函数）**

**3a.** 在 Task 3 插入的计数两行之后，紧接着求值一次（`_detect_and_act` 内局部变量，转向门和 overlay 共用同一份）：

```python
        in_zone = [x for x, y in centres if farm_logic.point_in_zone((x, y), zone)]
        self._last_zone_count = len(in_zone)
        # 本拍会不会放群攻:转向门与 overlay 都用这一份,不各自再调一次 ——
        # 判据必须与 _do_attack 那次求值同值,否则会出现「以为要群攻所以没转向、
        # 结果群攻没发」的两头落空拍(spec §3.4)。
        aoe_ready = self._aoe_ready(cfg, keys, now)
```

**3b.** 转向门加一项 `and not aoe_ready`（在 `turn is not None` 之后、`turn_allowed` 之前），并补注释：

```python
            # 群攻拍不转向:双向命中不需要朝向,转向在这一拍是纯支出 ——
            # 一次方向键 tap + 下面那句 self._last_detect = 0.0 作废检测节拍。
            # 只跳过「真发群攻」的这一拍;群攻冷却中的拍照常转向,否则冷却那
            # 2 秒里怪全在背侧时,单体攻击区(面朝侧半区)是空的,角色站着挨打
            # (spec §3.6)。_facing 在群攻拍完全不动,也就不会有「盲写了朝向、
            # 下一拍单体按着错朝向打空」的新分叉。
            if (turn is not None
                    and not aoe_ready
                    and farm_logic.turn_allowed(now, self._last_turn, cfg['转向冷却(秒)'])
                    and not farm_logic.stun_suppressed(
                        now, self._last_hit, cfg['硬直抑制窗(秒)'])
                    and self._key_sendable()):
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline -v
```

Expected: PASS —— `TestAoeSkipsTurn` 4 个用例全绿，既有转向用例（`test_detect_mode_turns_then_attacks_when_mob_behind` 等）无回归。

- [ ] **Step 5: 提交**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 群攻拍不转向——双向命中不需要朝向,转向在那一拍是纯支出

只跳过真发群攻的那一拍;冷却中的拍照常转向,否则那 2 秒里怪全在
背侧时单体攻击区是空的,角色站着挨打。群攻拍 _facing 完全不动,
不产生「盲写朝向 → 下一拍单体打空」的新分叉。"
```

---

### Task 6: overlay 群攻就绪态

**Files:**
- Modify: `src/task/MapleFarmTask.py` —— `_draw_debug()`（约 `:511`）签名加 `aoe_ready=False`，接敌区框线宽/标签随它变；`_detect_and_act()` 的 `_draw_debug(...)` 调用处传参
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: `_detect_and_act` 里的局部变量 `aoe_ready`（Task 5）
- Produces: `_draw_debug(self, cfg, body, zone, attack_area, mobs, mob_present, attack_present, aoe_ready=False, search_region=None, feet_y=None, frame_w=None)`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_farm_task_offline.py` 末尾：

```python
class TestAoeOverlay(unittest.TestCase):
    """群攻就绪时接敌区框加粗 + 标签改名,给 E2E 判据 D 一个可视对象。"""

    def _draw_kwargs(self, mobs):
        task = _aoe_task()
        task._boxes_enabled = MagicMock(return_value=True)
        task._draw_debug = MagicMock()
        _run_with_mobs(task, mobs)
        self.assertTrue(task._draw_debug.called, '_draw_debug 没被调用')
        return task._draw_debug.call_args.kwargs

    def test_aoe_ready_passed_true(self):
        kwargs = self._draw_kwargs([_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        self.assertIs(kwargs['aoe_ready'], True)

    def test_aoe_ready_passed_false_below_threshold(self):
        kwargs = self._draw_kwargs([_aoe_mob(1230), _aoe_mob(1530)])
        self.assertIs(kwargs['aoe_ready'], False)
```

- [ ] **Step 2: 跑测试确认它失败**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline.TestAoeOverlay -v
```

Expected: FAIL —— `KeyError: 'aoe_ready'`

- [ ] **Step 3: 写实现（三处）**

**3a. `_draw_debug` 签名** —— 加 `aoe_ready=False`（放在 `attack_present` 之后、`search_region` 之前，保持既有关键字参数顺序习惯）：

```python
    def _draw_debug(self, cfg, body, zone, attack_area, mobs, mob_present, attack_present,
                    aoe_ready=False, search_region=None, feet_y=None, frame_w=None):
```

docstring 第一行补一句：

```
        群攻就绪时接敌区框加粗(1→3)且标签改 接敌区(群攻),给 E2E 判据 D 一个可视对象。
```

**3b. `_draw_debug` 闭包外**（和 `zone_color` / `attack_color` 放一起）：

```python
        zone_color = ZONE_HOT_COLOR if mob_present else ZONE_IDLE_COLOR
        # 群攻态在闭包外定死:paint 是 Qt 重绘时才执行的,那时 now 早过去了,
        # 在闭包里现调 _aoe_ready 会画出与本拍决策不一致的框(spec §4)。
        zone_pen_width = 3 if aoe_ready else 1
        zone_label = '接敌区(群攻)' if aoe_ready else '接敌区'
```

**3c. `paint` 闭包里画接敌区那两行** —— 用上面两个变量（标签框宽度 100 → 140，`接敌区(群攻)` 六个字画不下）：

```python
                painter.setPen(QPen(zone_color, zone_pen_width))
                painter.drawRect(rect(zx0, zy0, zx1 - zx0, zy1 - zy0))
                painter.drawText(rect(zx0, zy0 - 20, 140, 20), zone_label)
```

**3d. `_detect_and_act` 的调用处** —— 加 `aoe_ready=aoe_ready`：

```python
            self._draw_debug(cfg, body=body, zone=zone, attack_area=draw_area,
                             mobs=mobs, mob_present=mob_present,
                             attack_present=self._last_attack_present,
                             aoe_ready=aoe_ready,
                             search_region=region, feet_y=anchor_hit.y, frame_w=w)
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline -v
```

Expected: PASS —— `TestAoeOverlay` 2 个用例全绿。

- [ ] **Step 5: 提交**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: overlay 群攻就绪态——接敌区框加粗 + 标签改 接敌区(群攻)

就绪标志在 _detect_and_act 求值一次再传参,不在 paint 闭包里现算:
闭包是 Qt 重绘时才跑的,那时 now 已经过去,会画出与决策不一致的框
(同 2026-08-09「悬浮窗比朝向慢一拍」那类问题)。"
```

---

### Task 7: 全量回归 + 编译检查 + E2E 截图验收

**Files:**
- Modify: `AGENTS.md`（§11.7 基线段落，追加本次 E2E 结论）
- Create: `screenshots/e2e/aoe_attack/aoe_zone_<YYYYMMDD>.png`

**Interfaces:**
- Consumes: Task 1-6 的全部产出
- Produces: 无代码接口；产出是验收证据

- [ ] **Step 1: 全量单测**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_logic tests.test_warrior_debug_offline tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_calibrate_offline tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine tests.test_facing tests.test_analyze_facing tests.test_analyze_seek tests.test_analyze_turn tests.test_analyze_anchor
```

Expected: 全绿（允许既有的显式 skip：存档帧缺失 ×5、OCR 限制 ×2）。**有红就停下修，不许带病往下走。**

> 比 AGENTS.md §11.6 的列表多带了 `test_facing` 与四个 `test_analyze_*`：本次改了 `_log_decision` 的**签名**（格式没动），这五个模块是离线的、几乎零成本，比「格式没改所以应该没影响」稳。
>
> 仍然**有意排除** `test_yolo` / `test_m0_live` / `test_e2e_warrior` —— 它们要真机/模型/GUI，不在离线回归范围内（AGENTS.md §11.6 的原话是「排除重型 live/yolo 测试，它们只做编译检查」，Step 2 的 py_compile 已覆盖）。

- [ ] **Step 2: 编译检查**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"
```

Expected: 打印 `OK`

- [ ] **Step 3: 启 GUI 做 E2E**

按 AGENTS.md §11.5 流程：

1. 停掉占用 WGC 的旧 GUI
2. 启 `main_debug.py`（后台 + 日志重定向）
3. 在「自动打怪」里：`攻击模式=检测`、勾选 `启用标记框`、`游戏按键` 页把 `群攻键(可留空)` 填一个键（如 `d`）、`群攻怪数阈值` 临时调成 `1`（**只为把群攻态稳定画出来**，截完图改回 3）
4. 截图：`.\.venv-warrior\Scripts\python.exe scripts\_e2e_capture.py <pid> screenshots\e2e\aoe_attack\aoe_zone_<YYYYMMDD>.png`

- [ ] **Step 4: 视觉模型验收（判据 D，合入门槛）**

用 vision-capable 模型核对截图，必须能确认：

- 画面上接敌区框**明显比未就绪时粗**（线宽 3 vs 1）
- 该框的标签文字是 **`接敌区(群攻)`**，不是 `接敌区`
- 攻击区（粗亮框）与怪物框（黄）照旧存在，没有被这次改动画坏

FAIL 则修复后重截，不许带病合入。

- [ ] **Step 5: 把结论写进 AGENTS.md §11.7**

在 §11.7 的 E2E 列表里追加一条（日期换成实际验收日）：

```markdown
  - **通过**：群攻 overlay —— `screenshots/e2e/aoe_attack/aoe_zone_<YYYYMMDD>.png`
    经视觉模型验收，接敌区框在群攻就绪时加粗且标签为「接敌区(群攻)」，
    攻击区/怪物框无回归
```

- [ ] **Step 6: 提交**

```bash
git add AGENTS.md screenshots/e2e/aoe_attack/
git commit -m "test: 群攻 E2E 截图验收通过,更新 AGENTS.md 基线

判据 D(视觉验收)通过:接敌区框在群攻就绪时加粗且标签改名,
攻击区/怪物框无回归。"
```

---

## 实弹验证（合并前的最后一关，需要真机挂机，不在自动化范围内）

代码合入前必须跑完 spec §5.3 的 A/B/C 三条，任何一条不过都不许声称功能完成：

**A（确实生效且计数自洽）** —— 绑好群攻键、`群攻怪数阈值` 恢复 3、开 `决策日志开关`，挂机 10 分钟：

```powershell
Select-String -Path logs\ok-mxd.log -Pattern '^.*群攻 ' | Measure-Object -Line
```

- 「群攻」行数 **> 0**（一次都没触发 → 阈值太高或计数没接上，A 不过则 B 无意义）
- 每行的 `区内=N` 必须 **N ≥ 阈值**，违例行数必须为 **0**

**B（不变差）** —— `群攻键` 绑定 / 留空 交替各跑 3 轮 × 10 分钟，记每轮每分钟经验增长。通过线：**绑定组中位数 ≥ 留空组中位数**。低于则先看喝蓝频率（多半是群攻耗蓝拖垮续航），调大 `群攻间隔(秒)` 重测，不许直接回滚。

**C（症状消失）** —— 用户主观确认：被围时确实放得出群攻，且不再出现「被围时左右扭」。

---

## 自查记录（写完计划后按 spec 逐条核对）

| Spec 章节 | 覆盖任务 |
|---|---|
| §3.1 配置变更（三个键 + 留空关闭 + 阈值依据） | Task 2 |
| §3.2 计数区 = 接敌区、框中心判定 | Task 3（`point_in_zone` + `zone`） |
| §3.3 纯函数 `crowd_present` | Task 1 |
| §3.4 单一判据 `_aoe_ready` | Task 3 |
| §3.5 接线（状态 / 计数 / `in_zone` 复用 / `_do_attack` 分支） | Task 3 + Task 4 |
| §3.6 群攻拍不转向 | Task 5 |
| §3.7 群攻推进 `_last_attack` | Task 4（`test_aoe_pushes_single_attack_cadence`） |
| §3.8 寻怪互斥不变量 | Task 5（`test_seek_and_aoe_are_mutually_exclusive`） |
| §3.9 行为矩阵五行 | Task 4（前四行）+ Task 5（转向那一列） |
| §3.10 计数不去抖 | Task 1（注释 + 用原始计数，无去抖代码） |
| §4 `aoe_log_line` + 不动 `decision_log_line` + overlay | Task 4 + Task 6 |
| §5.1 纯函数单测 5 条 | Task 1 Step 1 |
| §5.2 任务级用例 a–j | Task 3/4/5（a=T4.1, b=T4.2, c=T4.3, d=T5.1, e=T4.5, f=T4.4, g=T4.7, h=T4.6, i=T5.4, j=T4.8） |
| §5.3 判据 A/B/C/D | Task 7 + 实弹章节 |
| §6 明确不做 | 无任务（本计划未引入任何被禁项：无新区参数、无 MP 门控、无定频群攻、无去抖、无额外寻怪分支、未改 `decision_log_line` 格式、未改 `attack_turn_direction`） |

**类型/命名一致性核对：**
- `crowd_present(mob_count, threshold)` —— Task 1 定义，Task 3 `_aoe_ready` 调用，参数顺序一致 ✓
- `_aoe_ready(self, cfg, keys, now)` —— Task 3 定义，Task 4（`_do_attack`）与 Task 5（转向门/局部变量 `aoe_ready`）调用，签名一致 ✓
- `aoe_log_line(count, threshold)` —— Task 4 定义并在同任务调用 ✓
- `self._last_zone_count` / `self._last_aoe` —— Task 3 定义，Task 4/5/6 使用，名字一致 ✓
- `_log_decision` 新签名（`in_zone` 在 `centres` 之后）—— Task 3 同时改定义与唯一调用点 ✓
- `_draw_debug` 新签名（`aoe_ready` 在 `attack_present` 之后）—— Task 6 同时改定义与唯一调用点 ✓
- 测试夹具 `AOE_KEYS` / `_aoe_mob` / `_aoe_task` / `_run_with_mobs` / `_sent` —— Task 3 Step 1 一次定义，Task 4/5/6 复用 ✓
