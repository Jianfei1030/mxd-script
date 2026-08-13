# 补BUFF 按键间隔 + FIFO 队列设计文档

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/buff-interval-queue.md)

> 日期：2026-08-13
> 状态：已批准（用户确认全部设计决策：全局间隔 0.5s、暂停队列先打怪）

## [S1] 问题

补BUFF 功能（2026-08-10 上线，spec `2026-08-10-buff-timer-design.md`）存在一个实测缺陷：多个 BUFF **同时到期**时，`run()` §3.6 在同一拍内**连续** `send_key` 所有到期 BUFF 的键（`MapleFarmTask.py:1401-1403` 的 `for name, key in due:` 循环）。

用户实测：3 个 BUFF 中 2 个同为 180s 冷却，到 180s 时**经常只补上一个**——推测是游戏内技能施放有前摇/冷却机制，两个键紧挨着按下时第二个被吞。

**根因**：无按键间间隔、无队列——到期即同拍连按，不留给游戏技能施放的时间。

## [S2] 方案概述

到期 BUFF **入 FIFO 队列**，逐拍**节流出队**按键——每个检测拍最多按一个 BUFF 键，相邻两个按键之间受全局「补BUFF间隔(秒)」控制。队列推进期间若攻击区来怪，**暂停队列**（不清空），优先打怪，攻击区空了继续补剩下。

```
run() 补BUFF块（§3.6）:
  if 补BUFF开关 开 且 _last_attack_present is False:          ← 攻击区无怪
      if 队列空:
          due = due_buffs(...)                                  ← 全部到期 BUFF
          if due:
              入队即更新 _last_buff_times[name] = now          ← 防下一拍重复入队
              全部 extend 进 _buff_queue
      if 队列非空 且 now - _last_buff_press >= 补BUFF间隔(秒):
          name, key = _buff_queue.popleft()                     ← FIFO 逐出队
          松寻怪键/停追
          send_key(key)
          _last_buff_press = now
          log 补BUFF: name
          return                                                ← 本拍只补BUFF
  攻击区有怪 → 整个块跳过,队列保留不推进,正常攻击
```

**关键语义**：
- **入队即计时**：`_last_buff_times[name] = now` 在入队时设置（不是出队按键时）。原因：`due_buffs` 每次 run() 都会重新计算，若出队才计时，队列里的 BUFF 会被下一拍 `due_buffs` 重复判为到期、重复入队。入队即计时保证「已安排补」的 BUFF 不再进队列。副作用：被怪长时间打断时计时从入队时刻起算（下次提前补），但补BUFF本来就该让位给战斗，可接受。
- **FIFO 队列**：`collections.deque()`，保持配置顺序逐出队。用户曾提到「队列或栈」，选队列（FIFO）——配置顺序即补BUFF顺序，栈会颠倒顺序。
- **有怪暂停**：队列**不清空**、不推进，`return` 由攻击逻辑接管；攻击区空了下一拍继续 `popleft`。

## [S3] 配置项（MapleFarmTask DEFAULT_CONFIG + CONFIG_GROUPS「挂机辅助」组）

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 补BUFF间隔(秒) | float | 0.5 | 相邻两个补BUFF按键之间的最小间隔。游戏技能施放有前摇/冷却，同一拍连按多个 BUFF 键会吞键（用户实测 2 个 180s BUFF 同时到期只补上一个）。间隔期间攻击区仍无怪才会推进队列 |

- 放在 `补BUFF开关` 之后（DEFAULT_CONFIG :35 旁）
- CONFIG_GROUPS「挂机辅助」组 `['补BUFF开关', '补BUFF间隔(秒)', '补BUFF列表', ...]`
- GUI 描述（DESCRIPTIONS，MapleFarmTask.py:240 旁）：「相邻两个 BUFF 按键之间的最小间隔（秒），防技能前摇吞键。多个 BUFF 同时到期时逐拍补、间隔至少此值」
- 普通 float 配置，`ConfigItemFactory` 自动渲染为数字输入，无需新控件

## [S4] 纯函数（farm_logic.py）

**零改动**。`parse_buff_config` / `due_buffs` 保持现状——间隔节流是任务级状态（`_last_buff_press` + 队列），不改变纯函数接口。

## [S5] 任务集成（MapleFarmTask）

### 5.1 实例字段（_reset_state 新增，:337 旁）

```python
self._buff_queue = collections.deque()  # 补BUFF 待按键 FIFO 队列 [(name, key)];空 = 无待补
self._last_buff_press = 0.0             # 上次补BUFF按键时刻;0.0 哨兵=从未按过,不受间隔限制
```

- 顶部 import `collections`（检查是否已导入，未导入则加）
- 队列元素是 `(name, key)` 二元组（`due_buffs` 返回格式，直接 extend）

### 5.2 暂停清队列（_on_executor_paused :1257 旁）

```python
self._last_buff_times = {}
self._buff_queue.clear()   # 暂停清队列:残留条目是过期计时,恢复后按"从未补过"重新入队
```

### 5.3 run() 补BUFF块重构（:1392-1405）

```python
# 3.6 定时补BUFF(挂机辅助):攻击区内无怪才补;有怪优先解决,队列保留顺延。
# 多个 BUFF 同时到期时入 FIFO 队列逐拍出队按键,间隔受「补BUFF间隔(秒)」控制,
# 避免同拍连按被技能前摇吞键(2026-08-13 用户实测)。
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

- **单 BUFF 到期行为不变**：入队后同拍立即出队按键 + return（`_last_buff_press` 首次为 0.0，0.0 哨兵放行）
- **多 BUFF 同到期**：第一拍 `popleft` 按一个 return；下一拍 `now - _last_buff_press` 未到 0.5s → 不按 → 正常攻击/寻怪；到 0.5s 且攻击区无怪 → 按第二个
- **定频模式**：`_last_attack_present` 恒 None，`is False` 不成立 → 不补BUFF（既有语义，不变）

## [S6] 文件结构与依赖

**修改**：
- `src/task/MapleFarmTask.py` — DEFAULT_CONFIG + CONFIG_GROUPS + DESCRIPTIONS + import collections + _reset_state + _on_executor_paused + run() 补BUFF块
- `tests/test_farm_task_offline.py` — TestBuffTimer 新增队列/间隔用例
- `tests/test_config_groups.py` — 新键归组完整性自动覆盖

**依赖**：无新依赖

## [S7] 测试与验收

### 7.1 单元测试（离线可跑）

`tests/test_farm_task_offline.py::TestBuffTimer` 新增：
- **多 BUFF 同到期分拍补**：`魔法盾=q:180,狂暴=w:180` 同时到期 → 第一拍只按 `q`（`_last_buff_times` 两个都已更新为 now）；第二拍 now+0.5 按 `w`，队列空
- **间隔未到不按**：第一拍按 `q` 后，now+0.2 拍不按键（`send_key` 不再被调用），now+0.5 拍按 `w`
- **队列推进中来怪暂停**：第一拍按 `q` 后 `_last_attack_present=True` 的拍不按键（队列保留），恢复 False 后下一间隔拍按 `w`
- **暂停清空队列**：两 BUFF 同到期第一拍按 `q` 后 `_on_executor_paused(True)` → `_buff_queue` 空；恢复后重新入队补
- **单 BUFF 行为不变**：现有 7 用例保持通过（入队+同拍出队=原行为）

现有断言兼容性：
- `test_due_and_no_mob_sends_buff_key_and_updates_time`：单 BUFF，第一拍入队+出队按 `q`，`_last_buff_times['魔法盾']=200.0` —— 入队即计时仍为 200.0 ✓
- `test_buff_stops_seek_this_tick`：出队路径仍 `_release_seek_key` + `_seek_dir=None` ✓
- `test_mob_in_zone_skips_buff_and_attacks`：有怪整个块跳过，不触队列 ✓
- `test_no_interval_entry_never_auto_buffs`：`due_buffs` 返回空 → 不入队 ✓

### 7.2 编译检查与全量单测

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_logic tests.test_farm_task_offline tests.test_config_groups
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"
```
Expected: 全绿 + OK

### 7.3 E2E（AGENTS.md §11.3）

- GUI 启动无崩溃;「自动打怪」卡片「挂机辅助」组出现「补BUFF间隔(秒)」
- 实机验收：配置两个 180s BUFF，站桩等 180s 观察是否分拍补齐（两键间隔 ≥0.5s，不再吞键），结论写入报告

## [S8] 全局约束（Global Constraints）

- 新配置键只改 DEFAULT_CONFIG + CONFIG_GROUPS + DESCRIPTIONS
- 全局「补BUFF间隔(秒)」默认 0.5（用户确认）；每个 BUFF 自己的冷却间隔（180s 等）仍是每项独立配置
- FIFO 队列保持配置顺序；有怪暂停队列不清空（用户确认）
- 入队即计时（防重复入队）；暂停清空计时+队列
- 定频模式不补BUFF（无攻击区状态，既有语义）
- 测试命令/编译检查同上；禁止 hard code 本地路径
