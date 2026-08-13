# 补BUFF 按键间隔 + FIFO 队列 Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/buff-interval-queue.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让多个 BUFF 同时到期时逐拍补键（间隔 ≥「补BUFF间隔(秒)」默认 0.5s），修复同拍连按被技能前摇吞键的问题。

**Architecture:** 到期 BUFF 入 `collections.deque()` FIFO 队列（入队即更新 `_last_buff_times` 防重复入队），run() §3.6 每拍至多 `popleft` 一个按键，受 `_last_buff_press` 节流；攻击区有怪时整个块跳过、队列保留。

**Tech Stack:** Python 3.12 / unittest / 现有 MapleFarmTask 任务框架（无新依赖）

---

### Task 1: 配置键声明（补BUFF间隔(秒)）

**Covers:** [S3]

**Files:**
- Modify: `src/task/MapleFarmTask.py:34-35`（DEFAULT_CONFIG）
- Modify: `src/task/MapleFarmTask.py:105-106`（CONFIG_GROUPS 挂机辅助组）
- Modify: `src/task/MapleFarmTask.py:240-241`（DESCRIPTIONS）
- Test: `tests/test_config_groups.py`（完整性用例自动覆盖，无需手改）

- [ ] **Step 1: DEFAULT_CONFIG 加键**

在 `'补BUFF列表': [],`（:35）之后插入：

```python
    '补BUFF间隔(秒)': 0.5,
```

- [ ] **Step 2: CONFIG_GROUPS 归组**

把 `('挂机辅助', ['喂宠物开关', '喂宠物间隔(秒)', '补BUFF开关', '补BUFF列表', ...])`（:105）改为：

```python
    ('挂机辅助', ['喂宠物开关', '喂宠物间隔(秒)', '补BUFF开关', '补BUFF间隔(秒)', '补BUFF列表', '坐椅开关', '坐椅延迟(秒)',
                 '经验停滞上限(分钟)']),
```

- [ ] **Step 3: DESCRIPTIONS 加描述**

在 `'补BUFF列表': ...`（:241）之后插入：

```python
            '补BUFF间隔(秒)': '相邻两个 BUFF 按键之间的最小间隔(秒),防技能前摇吞键。多个 BUFF 同时到期时逐拍补、间隔至少此值;间隔期间攻击区仍无怪才会推进队列',
```

- [ ] **Step 4: 验证归组完整性**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_config_groups`
Expected: 全绿（新键被 CONFIG_GROUPS 覆盖、无重复）

- [ ] **Step 5: Commit**

```bash
git add src/task/MapleFarmTask.py
git commit -m "feat: add buff press interval config (default 0.5s)"
```

---

### Task 2: 状态字段 + import + 暂停清队列

**Covers:** [S5.1, S5.2]

**Files:**
- Modify: `src/task/MapleFarmTask.py:1-13`（imports）
- Modify: `src/task/MapleFarmTask.py:337`（_reset_state）
- Modify: `src/task/MapleFarmTask.py:1257`（_on_executor_paused）

- [ ] **Step 1: 加 import**

在 `import time`（:2）之后插入：

```python
import collections
```

- [ ] **Step 2: _reset_state 加字段**

在 `self._last_buff_times = {}        # 每个 BUFF 上次补的时间 {名称: 时刻};空 = 全部未补过,到点即补`（:337）之后插入：

```python
        self._buff_queue = collections.deque()  # 补BUFF 待按键 FIFO 队列 [(name, key)];空 = 无待补
        self._last_buff_press = 0.0             # 上次补BUFF按键时刻;0.0 哨兵=从未按过,不受间隔限制
```

- [ ] **Step 3: 暂停清队列**

把 `_on_executor_paused` 里（:1257）：

```python
            self._last_buff_times = {}
```

改为：

```python
            self._last_buff_times = {}
            self._buff_queue.clear()   # 暂停清队列:残留条目是过期计时,恢复后按"从未补过"重新入队
```

- [ ] **Step 4: 编译检查**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import py_compile; py_compile.compile('src/task/MapleFarmTask.py', doraise=True); print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add src/task/MapleFarmTask.py
git commit -m "feat: add buff queue state and clear on pause"
```

---

### Task 3: TestBuffTimer 新增用例（红）

**Covers:** [S7.1]

**Files:**
- Test: `tests/test_farm_task_offline.py`（TestBuffTimer 类，:3679 后追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_farm_task_offline.py` 的 `TestBuffTimer` 类末尾（`test_pause_resume_signal_does_not_reset_timer` 之后，:3769 附近）追加四个用例：

```python
    def test_multi_buff_same_due_spaced(self):
        """两 BUFF 同到期 → 分拍补:第一拍只按第一个,间隔未到不按,间隔到才按第二个。"""
        task = self._task('魔法盾=q:180,狂暴=w:180')
        task._last_attack_present = False
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.0)  # 从未补过 → 都到期
        self.assertEqual(task.send_key.call_args_list, [call('q')])        # 只按第一个
        self.assertEqual(task._last_buff_times, {'魔法盾': 200.0, '狂暴': 200.0})  # 入队即计时
        self.assertEqual(len(task._buff_queue), 1)
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.2)  # 间隔未到(0.2<0.5)
        self.assertEqual(task.send_key.call_args_list, [call('q')])        # 不按
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.5)  # 间隔到(0.5)
        self.assertEqual(task.send_key.call_args_list, [call('q'), call('w')])
        self.assertEqual(len(task._buff_queue), 0)

    def test_buff_queue_paused_when_mob(self):
        """队列推进中来怪 → 不按键、队列保留;怪消失后继续补。"""
        task = self._task('魔法盾=q:180,狂暴=w:180')
        task._last_attack_present = False
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.0)
        self.assertEqual(task.send_key.call_args_list, [call('q')])
        self.assertEqual(len(task._buff_queue), 1)
        task._last_attack_present = True
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.5)  # 有怪:整个块跳过
        self.assertEqual(task.send_key.call_args_list, [call('q')])        # 不按
        self.assertEqual(len(task._buff_queue), 1)                          # 队列保留
        task._last_attack_present = False
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.5)  # 怪走,间隔已到
        self.assertEqual(task.send_key.call_args_list, [call('q'), call('w')])
        self.assertEqual(len(task._buff_queue), 0)

    def test_pause_clears_buff_queue(self):
        """暂停清空队列+计时;恢复后重新入队补齐。"""
        task = self._task('魔法盾=q:180,狂暴=w:180')
        task._last_attack_present = False
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.0)
        self.assertEqual(len(task._buff_queue), 1)
        task._on_executor_paused(True)
        self.assertEqual(len(task._buff_queue), 0)
        self.assertEqual(task._last_buff_times, {})
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=2000.0)  # 恢复,从未补过 → 重新入队
        self.assertEqual(task.send_key.call_args_list, [call('q'), call('w')])  # 第一拍按 q,队列剩 w
        self.assertEqual(len(task._buff_queue), 1)
```

- [ ] **Step 2: 跑测试确认红**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_task_offline.TestBuffTimer.test_multi_buff_same_due_spaced tests.test_farm_task_offline.TestBuffTimer.test_buff_queue_paused_when_mob tests.test_farm_task_offline.TestBuffTimer.test_pause_clears_buff_queue`
Expected: FAIL（当前实现同拍连按两键，第一断言 `[call('q')]` 得 `[call('q'), call('w')]`）

- [ ] **Step 3: Commit**

```bash
git add tests/test_farm_task_offline.py
git commit -m "test: buff queue spacing/pause cases (red)"
```

---

### Task 4: run() 补BUFF块重构（绿）

**Covers:** [S2, S5.3]

**Files:**
- Modify: `src/task/MapleFarmTask.py:1392-1405`

- [ ] **Step 1: 替换补BUFF块**

把 :1392-1405 整块（`# 3.6 定时补BUFF...` 到 `return   # 本拍只补BUFF,不执行攻击/寻怪/坐椅等`）替换为：

```python
        # 3.6 定时补BUFF(挂机辅助):攻击区内无怪才补;有怪优先解决,队列保留顺延。
        # 多个 BUFF 同时到期时入 FIFO 队列逐拍出队按键,间隔受「补BUFF间隔(秒)」控制,
        # 避免同拍连按被技能前摇吞键(2026-08-13 用户实测)。
        # 位置在攻击块之前:补BUFF只按键不检测,放最前保证「本拍只补BUFF」的 return 语义干净。
        # 攻击区判定用上一拍的 _last_attack_present(去抖后,10Hz 足够及时)。
        if cfg['补BUFF开关'] and self._last_attack_present is False:
            if not self._buff_queue:
                due = farm_logic.due_buffs(now, farm_logic.parse_buff_config(cfg['补BUFF列表']),
                                           self._last_buff_times)
                if due:
                    for name, _ in due:                     # 入队即计时,防下一拍重复入队
                        self._last_buff_times[name] = now
                    self._buff_queue.extend(due)
            if self._buff_queue and now - self._last_buff_press >= cfg['补BUFF间隔(秒)']:
                name, key = self._buff_queue.popleft()
                self._release_seek_key()   # 停手:先松开寻怪长按的方向键
                self._seek_dir = None      # 停追:本拍不寻怪
                self.send_key(key)
                self._last_buff_press = now
                self.log_info(f'补BUFF: {name}')
                return   # 本拍只补BUFF,不执行攻击/寻怪/坐椅等
```

- [ ] **Step 2: 跑新用例确认绿**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_task_offline.TestBuffTimer`
Expected: 全绿（新旧 10 用例全过）

- [ ] **Step 3: 跑 TestBuffTimer + TestFarmTaskOffline 全类防回归**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_task_offline`
Expected: 全绿

- [ ] **Step 4: Commit**

```bash
git add src/task/MapleFarmTask.py
git commit -m "fix: space out buff presses via FIFO queue (was same-tick burst)"
```

---

### Task 5: 全量验证 + 提交

**Covers:** [S7.2]

**Files:**（无新改动，验证用）

- [ ] **Step 1: 全量单测**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_logic tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine tests.test_analyze_anchor tests.test_analyze_facing tests.test_analyze_seek tests.test_analyze_turn tests.test_facing tests.test_label_boxes tests.test_yolo tests.test_config_groups tests.test_config_card_ui tests.test_dependency tests.test_dependency_ui tests.test_pydirect_extended tests.test_key_input`
Expected: 全绿（既有 skip 基线除外）

- [ ] **Step 2: 编译检查**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`
Expected: OK

- [ ] **Step 3: 确认工作区只含本次改动**

Run: `git status --short`
Expected: 仅 `src/task/MapleFarmTask.py`、`tests/test_farm_task_offline.py`、`docs/compose/specs/2026-08-13-buff-interval-queue-design.md`、`docs/compose/plans/2026-08-13-buff-interval-queue.md`（+ 报告，若已写）

- [ ] **Step 4: 提交 spec/plan**

```bash
git add docs/compose/specs/2026-08-13-buff-interval-queue-design.md docs/compose/plans/2026-08-13-buff-interval-queue.md
git commit -m "docs: buff interval+queue spec and plan"
```

---

## Self-Review 记录

- **Spec 覆盖**：S1 问题 → 全计划背景；S2 方案 → Task 4；S3 配置 → Task 1；S4 纯函数零改动 → 无任务（符合 spec 声明）；S5.1/S5.2 状态与暂停 → Task 2；S5.3 run 重构 → Task 4；S7.1 测试 → Task 3；S7.2 验证 → Task 5；S7.3 E2E → 报告中记录（实机验收，非代码任务）；S8 约束 → 分散于各任务
- **占位符扫描**：无 TBD/TODO，所有步骤含完整代码与命令
- **类型一致性**：`_buff_queue`（deque，元素 `(name, key)`）在 Task 2 定义、Task 3 断言 `len(...)`、Task 4 使用 `extend/popleft`，一致；`_last_buff_press` 0.0 哨兵语义在 Task 2/4 一致；配置键 `'补BUFF间隔(秒)'` 在 Task 1/4 一致
- **既有测试兼容**：`test_only_due_buffs_sent`（单到期）入队+同拍出队=原行为；`test_buff_stops_seek_this_tick` 出队路径保留 `_release_seek_key`+`_seek_dir=None`；`test_mob_in_zone_skips_buff_and_attacks` 有怪整块跳过不触队列 ✓
