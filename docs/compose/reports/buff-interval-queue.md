---
feature: buff-interval-queue
status: delivered
specs:
  - docs/compose/specs/2026-08-13-buff-interval-queue-design.md
plans:
  - docs/compose/plans/2026-08-13-buff-interval-queue.md
branch: master
commits: 419f33d..da441ce
---

# 补BUFF 按键间隔 + FIFO 队列 — Final Report

## What Was Built

修复了补BUFF 功能的一个实测缺陷：多个 BUFF 同时到期时，任务在**同一拍内连续按下**所有到期的 BUFF 键，游戏技能施放有前摇/冷却，第二个及之后的按键经常被吞（用户实测 3 个 BUFF 中 2 个同为 180s 冷却，到点只补上一个）。

现在到期 BUFF 进入 **FIFO 队列**（`collections.deque()`），每个检测拍至多出队一个按键，相邻两个按键之间至少间隔「补BUFF间隔(秒)」（新增配置，默认 0.5s）。队列推进期间攻击区来怪则**暂停队列**（不清空），优先打怪，攻击区空了继续补剩下。单 BUFF 到期行为不变（入队后同拍立即按键）。

## Architecture

改动集中在 `src/task/MapleFarmTask.py`，`farm_logic.py` 纯函数零改动（`parse_buff_config` / `due_buffs` 接口不变）。

**新增状态**（`_reset_state`，:341-342）：
- `self._buff_queue: deque` — 待按键 FIFO 队列，元素 `(name, key)`，即 `due_buffs` 的输出格式，可直接 `extend`
- `self._last_buff_press: float` — 上次补BUFF按键时刻；`0.0` 哨兵 = 从未按过，不受间隔限制（保证首次按键立即放行）

**run() §3.6 补BUFF块**（:1398-1418）两段式：
1. **入队**（队列空 & 开关开 & 攻击区无怪）：`due_buffs` 计算全部到期 → **入队即更新 `_last_buff_times[name] = now`** → 全部 `extend` 进队列。入队即计时是关键：`due_buffs` 每个检测拍都会重新计算，若出队时才计时，队列中的 BUFF 会被下一拍重复判为到期、重复入队
2. **出队**（队列非空 & 攻击区无怪 & `now - _last_buff_press >= 补BUFF间隔(秒)`）：`popleft()` 一个 → 松寻怪键/停追 → `send_key` → `_last_buff_press = now` → `return`

攻击区有怪时整个块跳过，队列保留不推进——补BUFF 让位给战斗（用户确认的「暂停队列先打怪」语义）。

**暂停清队列**（`_on_executor_paused`，:1263）：F9 暂停时与清空 `_last_buff_times` 一并 `_buff_queue.clear()`——否则残留队列条目是过期计时，恢复后带着旧条目继续补。

### Design Decisions

- **入队即计时**（非出队计时）：防重复入队是硬约束（`due_buffs` 每拍重算）。副作用是被怪长时间打断时计时从入队时刻起算、下次略提前补，但补BUFF 本就该让位给战斗，可接受
- **FIFO 队列而非栈**：保持配置顺序逐出队；栈会颠倒补BUFF 顺序
- **有怪暂停队列而非清空**：已到期未补完的条目不该丢弃；用户确认「暂停队列先打怪」
- **全局间隔而非每 BUFF 独立**：每个 BUFF 自己的冷却间隔（180s 等）已存在，这里是按键与按键之间的间隔，全局一个配置足够（用户确认）

## Usage

「实时触发」→「自动打怪」→ 展开区「挂机辅助」组：

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 补BUFF开关 | bool | false | 总开关 |
| 补BUFF间隔(秒) | float | 0.5 | 相邻两个 BUFF 按键的最小间隔，防技能前摇吞键 |
| 补BUFF列表 | list | [] | 点「Modify Buffs」编辑：名称/按键/间隔秒 |

示例：`补BUFF列表 = ['魔法盾=q:180', '狂暴=w:180']`，两个 BUFF 同时到 180s 时，第一拍按 `q`，0.5s 后按 `w`——不再同拍连按。若期间攻击区来怪，`w` 挂起，打完怪后补。

## Verification

- **新增测试**（`tests/test_farm_task_offline.py::TestBuffTimer`，+3 用例，TDD 红→绿）：
  - `test_multi_buff_same_due_spaced`：两 BUFF 同到期 → 第一拍只按第一个、间隔未到不按、0.5s 后按第二个；`_last_buff_times` 入队即计时（两个都更新）
  - `test_buff_queue_paused_when_mob`：队列推进中来怪 → 不按键、队列保留；怪消失后继续补
  - `test_pause_clears_buff_queue`：暂停清空队列+计时；恢复后重新入队补齐
- **回归**：`TestBuffTimer` 12/12、`tests.test_farm_task_offline` 302/302、全量 667 通过（12 skip 基线）、全源码编译 OK
- **既有用例兼容**：单 BUFF 语义不变（入队+同拍出队）；`test_only_due_buffs_sent` / `test_buff_stops_seek_this_tick` / `test_mob_in_zone_skips_buff_and_attacks` 无需改动
- **待实机验收**：配置两个 180s BUFF 站桩，观察 180s 时是否分拍补齐（间隔 ≥0.5s、不再吞键），结论待补充

## Journey Log

- [lesson] 测试断言 `send_key.call_args_list` 是**累积**的：暂停恢复用例中暂停前按过 `q`，恢复后重新入队再按 `q`，断言应为 `[q, q]` 而非 `[q, w]`——首版断言写错，红测试暴露后修正
- [lesson] 「入队即计时」是队列方案的隐含硬约束：`due_buffs` 每拍重算，出队才计时会导致队列条目重复入队——设计时先想清「重复判定」而不是实现时才发现

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/specs/2026-08-13-buff-interval-queue-design.md` | 设计文档 | 已标记 NOTE，指向本报告 |
| `docs/compose/plans/2026-08-13-buff-interval-queue.md` | 实现计划 | 已标记 NOTE，指向本报告 |
| `docs/compose/specs/2026-08-10-buff-timer-design.md` | 上游特性 spec | 本特性是其修复迭代 |
