# 防挂机走位 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自动打怪任务定时做一次「左走一段再走回来」的小幅位移，避免长时间站桩不动被游戏防挂机机制踢下线或被识别为固定行为模式的脚本。

**Architecture:** 两层。Task 1 是「怎么走」——一个不关心时机、只管执行一次往返走位动作的方法 `_do_walk()`。Task 2 是「什么时候走」——接进主循环的节流与顺延判断，复用既有的 `farm_logic.should_attack()` 做"距上次过去了多久"的计时，不新增同构函数。两层之间只有一个调用点：`self._do_walk(keys)`。

**Tech Stack:** Python 3.12（嵌入式，无 pytest，用标准库 `unittest`）；`random.choice` 选走位方向。

**Spec:** `docs/superpowers/specs/2026-08-06-anti-idle-walk-design.md`

**分支约定：** 这个功能独立于 `feat/attack-zone-mob-gating`（尚未合并），本计划的代码改动全部基于 **`master`** 分支的现状（`MapleFarmTask.py` 当前是比例制攻击区版本，没有 OCR 锚点）。执行时请在 `master` 上开新分支，不要 checkout 到 `feat/attack-zone-mob-gating`。

## Global Constraints

- Python 解释器**只用** `H:\ok-mxd\data\apps\ok-ww\python\python.exe`；**禁止 pip install**（环境无 pytest，测试框架是 `unittest`）
- 所有命令在仓库根目录 `H:\ok-mxd\ok-mxd` 下执行
- 单模块测试：`PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v`
- 全量回归：`PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover tests -v`（master 基线：**42 通过、4 skip**，改动后应变成 42+新增数，4 skip 不变）
- 配置键、日志、注释一律中文，与既有代码保持一致
- **不要运行 `main_debug.py`** —— 它启动时会清空 `screenshots/`（含未入库的存档测试帧，`tests/test_bars.py`/`tests/test_potions.py`/`tests/test_farm_task_offline.py` 都依赖它）
- 每个任务结束时提交；提交信息用英文，结尾加一行：
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

### Task 1: 走位动作机制（`_do_walk`）

**Files:**
- Modify: `config.py`（`游戏按键` 全局配置加两个键）
- Modify: `src/task/MapleFarmTask.py`（`DEFAULT_CONFIG` 加一项、新增 `_do_walk` 方法）
- Test: `tests/test_farm_task_offline.py`（更新模块级 `KEYS` 夹具、新增 2 条测试）

**Interfaces:**
- Consumes: 无新依赖，`self.send_key(key, down_time=...)` 是既有接口（`ok/task/task.py:460`，`down_time` 参数会阻塞按住指定时长）
- Produces: `MapleFarmTask._do_walk(self, keys: dict) -> None`。`keys` 必须含 `'左移键'`/`'右移键'` 两个键名（形状与 `self.get_global_config('游戏按键')` 返回值一致）。调用后会往 `self.send_key` 发出恰好两次调用：先随机选一侧、按住 `self.config['走位持续时间(秒)']` 秒，再反方向按住同样时长。Task 2 会调用这个方法，不关心其内部实现。

- [ ] **Step 1: 写失败的测试**

打开 `tests/test_farm_task_offline.py`，把文件顶部第 9-10 行的模块级 `KEYS` 夹具改成（新增两个方向键）：

```python
KEYS = {'攻击键': 'shift', '血药键': 'home', '蓝药键': 'insert',
        '回城卷键(可留空)': '', '拾取键': 'z', '左移键': 'left', '右移键': 'right'}
```

在 `TestFarmTaskOffline` 类内追加两个测试方法（放在 `test_detect_mode_idles_when_mob_outside_zone` 之后即可）：

```python
    def test_do_walk_left_first(self):
        task = make_task(**{'走位持续时间(秒)': 0.4})
        with patch('src.task.MapleFarmTask.random.choice', return_value='左移键'):
            task._do_walk(KEYS)
        self.assertEqual(task.send_key.call_args_list,
                         [call('left', down_time=0.4), call('right', down_time=0.4)])

    def test_do_walk_right_first(self):
        task = make_task(**{'走位持续时间(秒)': 0.4})
        with patch('src.task.MapleFarmTask.random.choice', return_value='右移键'):
            task._do_walk(KEYS)
        self.assertEqual(task.send_key.call_args_list,
                         [call('right', down_time=0.4), call('left', down_time=0.4)])
```

- [ ] **Step 2: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v
```
Expected: 新增两条 FAIL —— `AttributeError: 'MapleFarmTask' object has no attribute '_do_walk'`

- [ ] **Step 3: `config.py` 加两个方向键**

`config.py` 里 `key_config_option` 的字典（第 9-14 行）改成：

```python
key_config_option = ConfigOption('游戏按键', {
    '攻击键': 'ctrl',
    '血药键': 'home',
    '蓝药键': 'insert',
    '回城卷键(可留空)': '',
    '拾取键': 'z',
    '左移键': 'left',
    '右移键': 'right',
}, description='冒险岛游戏内按键,与游戏内键盘设置保持一致', config_description={
    '回城卷键(可留空)': '低血保命用。留空则低血时只停止任务不逃跑',
}, show_at_tab=True, icon=FluentIcon.GAME)
```

- [ ] **Step 4: `MapleFarmTask.py` 加配置项与 `_do_walk` 方法**

顶部 import（第 1 行）改成加一行：

```python
import random
import time
```

`DEFAULT_CONFIG`（第 13-32 行）在 `'攻击区中心Y': 0.5,` 后面追加一项（注意逗号）：

```python
    '攻击区中心Y': 0.5,
    '走位持续时间(秒)': 0.4,
}
```

在 `_slot_of` 静态方法（第 85-87 行）之后、`run` 方法（第 89 行）之前插入：

```python
    def _do_walk(self, keys):
        """防挂机走位:随机一侧走出去再走回来,净位移 0,不会走出站桩点或掉下平台。"""
        hold = self.config['走位持续时间(秒)']
        first = random.choice(('左移键', '右移键'))
        second = '右移键' if first == '左移键' else '左移键'
        self.send_key(keys[first], down_time=hold)
        self.send_key(keys[second], down_time=hold)
```

- [ ] **Step 5: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v
```
Expected: PASS（含新增 2 条，共 11 条本文件测试全过）

- [ ] **Step 6: 全量回归**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover tests -v
```
Expected: `Ran 44 tests ... OK (skipped=4)`

- [ ] **Step 7: 提交**

```bash
git add config.py src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "$(cat <<'EOF'
feat: anti-idle walk mechanics (_do_walk)

Adds a back-and-forth left/right movement primitive: hold one randomly
chosen direction for a configured duration, release, hold the opposite
direction the same duration. Net displacement is zero by construction, so
it can't walk the character off the current platform.

Not wired into the run loop yet - that's the next task.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 走位触发时机（`run()` 接线）

**Files:**
- Modify: `src/task/MapleFarmTask.py`（`DEFAULT_CONFIG` 加两项、`_reset_state` 加两个状态、`run()` 第 4 步缓存检测结果 + 新增第 4.5 步）
- Test: `tests/test_farm_task_offline.py`（新增 6 条测试）

**Interfaces:**
- Consumes: `MapleFarmTask._do_walk(self, keys)`（Task 1）；既有的 `farm_logic.should_attack(now, last, interval) -> bool`（`src/task/farm_logic.py:35`，"距上次过去了多久是否达到间隔"，本任务直接复用它判断走位是否到点，不新增同构函数）
- Produces: 无（终点任务，不被后续任务消费）

- [ ] **Step 1: 写失败的测试**

在 `TestFarmTaskOffline` 类内追加（放在 Task 1 新增的两条测试之后即可）：

```python
    def test_walk_switch_off_never_walks(self):
        task = make_task(**{'走位开关': False, '攻击模式': '定频'})
        task._last_walk = -1000.0
        run_with_frame(task)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)

    def test_walk_fixed_mode_walks_when_due(self):
        task = make_task(**{'攻击模式': '定频', '走位持续时间(秒)': 0.4})
        task._last_walk = -1000.0
        with patch('src.task.MapleFarmTask.random.choice', return_value='左移键'):
            run_with_frame(task)
        sent = [c for c in task.send_key.call_args_list if c.args and c.args[0] in ('left', 'right')]
        self.assertEqual(sent, [call('left', down_time=0.4), call('right', down_time=0.4)])
        self.assertEqual(task._last_walk, 100.0)  # run_with_frame 把 time.time() 固定在 100.0

    def test_walk_detect_mode_defers_when_mob_present(self):
        task = make_task(**{'攻击模式': '检测'})
        task._last_walk = -1000.0
        mob = MagicMock(x=1200, y=700, width=60, height=50)  # 中心在默认攻击区内
        task.find_mobs = MagicMock(return_value=[mob])
        run_with_frame(task)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertTrue(task._last_mob_present)
        self.assertEqual(task._last_walk, -1000.0)  # 未更新,顺延到下一次判定

    def test_walk_detect_mode_walks_when_no_mob(self):
        task = make_task(**{'攻击模式': '检测', '走位持续时间(秒)': 0.4})
        task._last_walk = -1000.0
        task.find_mobs = MagicMock(return_value=[])
        with patch('src.task.MapleFarmTask.random.choice', return_value='右移键'):
            run_with_frame(task)
        sent = [c for c in task.send_key.call_args_list if c.args and c.args[0] in ('left', 'right')]
        self.assertEqual(sent, [call('right', down_time=0.4), call('left', down_time=0.4)])
        self.assertFalse(task._last_mob_present)
        self.assertEqual(task._last_walk, 100.0)

    def test_walk_not_due_yet_skips(self):
        task = make_task(**{'攻击模式': '定频'})
        task._last_walk = 99.0  # 100.0-99.0=1s < 默认 120s 间隔,未到
        run_with_frame(task)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertEqual(task._last_walk, 99.0)  # 未变

    def test_walk_detect_mode_no_walk_before_first_detection(self):
        """启动后一次检测都还没跑过(_last_mob_present 仍是初始值 None),
        即使到了走位时间点也不许走——没有新鲜的"有没有怪"判断就贸然移动,
        可能正好撞进怪堆。这里把 _last_attack 设成很接近 now,让本拍的检测
        本身也不触发(should_attack 判定攻击间隔未到),模拟"两次检测之间、
        且从未检测过"的窗口。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_walk = -1000.0
        task._last_attack = 99.9  # 100.0-99.9=0.1s < 默认攻击间隔 1.5s,本拍不跑检测
        task.find_mobs = MagicMock()
        run_with_frame(task)
        task.find_mobs.assert_not_called()
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertIsNone(task._last_mob_present)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v
```
Expected: 新增 6 条中至少部分 FAIL —— `KeyError: '走位开关'`（`DEFAULT_CONFIG` 里还没有这个键）或 `AttributeError: 'MapleFarmTask' object has no attribute '_last_mob_present'`

- [ ] **Step 3: `DEFAULT_CONFIG` 加两项、`_reset_state` 加两个状态**

`DEFAULT_CONFIG` 里 Task 1 加的 `'走位持续时间(秒)': 0.4,` 那一行后面追加：

```python
    '走位持续时间(秒)': 0.4,
    '走位开关': True,
    '走位间隔(秒)': 120,
}
```

`_reset_state`（第 48-60 行）末尾追加两行（**必须**加进这里——这个项目有过教训：新状态漏进 `_reset_state()` 会导致重新启用任务后计时器不复位、秒发）：

```python
        self._last_exp_gain_time = 0.0
        self._last_walk = 0.0
        self._last_mob_present = None
```

- [ ] **Step 4: 改 `run()` 第 4 步、新增第 4.5 步**

把 `run()` 里第 4 步（Task 1 在文件前面插入了 `_do_walk`，这段代码的行号已经下移，按内容原样查找替换，不要按行号定位）：

```python
        # 4. 攻击
        if cfg['攻击模式'] == '检测':
            if farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)']):
                mobs = self.find_mobs(frame)
                if self._mob_in_attack_zone(frame, mobs, cfg):
                    self.send_key(keys['攻击键'])
                    self._last_attack = now
        elif farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)']):
            self.send_key(keys['攻击键'])
            self._last_attack = now
```

替换为（新增 `mob_present` 变量并写入 `self._last_mob_present`，追加第 4.5 步）：

```python
        # 4. 攻击
        if cfg['攻击模式'] == '检测':
            if farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)']):
                mobs = self.find_mobs(frame)
                mob_present = self._mob_in_attack_zone(frame, mobs, cfg)
                self._last_mob_present = mob_present
                if mob_present:
                    self.send_key(keys['攻击键'])
                    self._last_attack = now
        elif farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)']):
            self.send_key(keys['攻击键'])
            self._last_attack = now

        # 4.5 防挂机走位(默认开启)。有独立的 120s 节奏,不挂在 1.5s 攻击节拍上;
        # 检测模式下如果这一拍刚好判定有怪(正在打),顺延到下一次判定"无怪"再走,
        # 不打断输出。定频模式没有"有没有怪"这个概念,到点直接走。
        if cfg['走位开关'] and farm_logic.should_attack(now, self._last_walk, cfg['走位间隔(秒)']):
            can_walk = cfg['攻击模式'] == '定频' or self._last_mob_present is False
            if can_walk:
                self._do_walk(keys)
                self._last_walk = now
```

- [ ] **Step 5: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v
```
Expected: PASS（本文件共 17 条测试全过：原 9 条 + Task 1 的 2 条 + Task 2 的 6 条）

- [ ] **Step 6: 全量回归**

```bash
PYTHONIOENCODING=utf-8 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover tests -v
```
Expected: `Ran 50 tests ... OK (skipped=4)`

- [ ] **Step 7: 提交**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "$(cat <<'EOF'
feat: gate anti-idle walk on a timer, deferring while a mob is being fought

Reuses farm_logic.should_attack for the walk-due check instead of adding a
duplicate function. Detect mode caches this tick's mob-presence result in
_last_mob_present so the walk gate never triggers an extra OCR/YOLO pass;
before the first detection ever runs, the gate stays closed (None sentinel)
rather than walking blind.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## 计划自查

**规格覆盖**：spec §2.1 触发节奏（复用 `should_attack`，不新增同构函数）→ Task 2 Step 4；§2.2 与战斗冲突处理（顺延 + `_last_mob_present` 缓存 + None 哨兵）→ Task 2 Step 3/4，测试覆盖 `test_walk_detect_mode_defers_when_mob_present`/`test_walk_detect_mode_no_walk_before_first_detection`；§2.3 走位动作（随机方向、净位移 0、同步阻塞）→ Task 1；§2.4 配置变更（`左移键`/`右移键`/`走位开关`/`走位间隔(秒)`/`走位持续时间(秒)`）→ Task 1 Step 3/4 + Task 2 Step 3；§2.5 新状态进 `_reset_state()`→ Task 2 Step 3；§2.6 主循环接线（独立于攻击节拍、不嵌进 if/elif）→ Task 2 Step 4；§4.1 六条离线用例 → Task 2 Step 1（一一对应）；§4.2 实弹验证 → 不在本计划内，需人操作，已在 spec 里单列，不遗漏也不虚构一个 agent 做不到的任务；§5 明确不做的三项 → 计划中无对应任务（正确，未夹带）。

**类型一致性**：`_do_walk(self, keys)` 在 Task 1 定义、Task 2 Step 4 原样调用 `self._do_walk(keys)`，`keys` 变量在 `run()` 里已由 `keys = self.get_global_config('游戏按键')`（第 104 行，未改动）提供，含 Task 1 新加的 `左移键`/`右移键`。`_last_walk`/`_last_mob_present` 在 Task 2 Step 3 声明、Step 4 读写，命名前后一致。
