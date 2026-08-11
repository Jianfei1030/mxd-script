---
feature: double-attack
status: delivered
specs: []
plans:
  - plans/2026-08-10-double-attack.md
branch: master
commits: 47325e5..154156e
---

# Double Attack（二连击）— Final Report

## What Was Built

为挂机增加「二连击」功能：检测模式下怪物进入攻击范围时，攻击键与副攻击键**背靠背连按两次**（先攻击键、立即副攻击键，中间不插入垫步等任何指令）。解决「一次打不死、第一下后怪靠近被角色/宠物遮挡导致短暂检测不到、恰好要两下才死」的怪物——第一下打残，怪被遮挡的窗口里第二下已补刀，不需要等它再次进入可检测范围。

超过两下才死的怪不适合此模式（用户口径），功能默认关闭。

## Architecture

三处改动：

| 文件 | 职责 |
|---|---|
| `config.py` | 「游戏按键」新增 `副攻击键(可留空)`，默认 ''。留空 = 二连击关闭（同群攻键约定） |
| `src/task/MapleFarmTask.py` | `DEFAULT_CONFIG` 新增 `二连击开关`（默认 False）；`CONFIG_GROUPS`「攻击」组归入 |
| `src/task/MapleFarmTask.py` `_do_attack` | 单体攻击分支内判定二连击 |

核心逻辑（`_do_attack` 单体路径）：

```python
double_attack = (cfg.get('二连击开关') and keys.get('副攻击键(可留空)', ''))
# 垫步门加 not double_attack → 二连击开启时跳过攻击前垫步
...
self.send_key(keys['攻击键'])
if double_attack:
    self.send_key(keys['副攻击键(可留空)'])
self._last_attack = now
```

两键共用同一条 `攻击间隔(秒)` 节拍，`_last_attack = now` 只记一次——一轮二连击视为一次攻击，与群攻路径同口径。

### Design Decisions

- **垫步被跳过**：用户明确要求「攻击-副攻击中间不插入任何指令」。垫步插入的是方向键 15ms 轻点，会把两键拆开，违背零插入铁律，故二连击开启时 `not double_attack` 门跳过垫步。
- **副攻击键留空 = 关闭**：复用群攻键「留空 = 功能关闭」约定，避免用户开了开关却没绑键时静默只按一下（测试 `test_double_attack_skipped_when_subkey_empty` 钉死）。
- **群攻路径零改动**：`_aoe_ready` 分支 return 在前，区内怪数达阈值时只按群攻键，二连击不介入——群攻本就是补刀场景的反面（被围时一发群攻）。
- **定频模式不适用**：定频无攻击区概念，无「怪进入攻击范围」事件，二连击只作用于检测模式。

## Usage

1. 设置页「游戏按键」→ 绑定「副攻击键(可留空)」（如 `x`）
2. 「自动打怪」卡片展开区「攻击」组 → 打开「二连击开关」
3. 检测模式下怪进入攻击区即连发：攻击键 → 副攻击键

行为矩阵：

| 二连击开关 | 副攻击键 | 攻击前垫步开关 | 行为 |
|---|---|---|---|
| off | 任意 | on/off | 原行为不变（垫步→攻击键） |
| on | 空 | 任意 | 视为关闭，只按攻击键 |
| on | 已绑定 | on | 攻击键→副攻击键，**跳过垫步** |
| on | 已绑定 | off | 攻击键→副攻击键 |

## Verification

- `tests/test_farm_task_offline.py` `TestAttackTap` 新增 6 用例：默认关 / 两键背靠背（断言 `[call('shift'), call('x')]`）/ 副键留空关闭 / 跳过垫步（断言无方向键插入）/ 共用攻击间隔 / 群攻路径不受影响
- 全量回归：600 tests **OK (skipped=12)**——无新增红（12 个 skip 均为存量：存档帧缺失/OCR 限制/val 数据缺失）
- 编译检查：`py_compile` 全源码 OK
- E2E：纯按键时序逻辑由单测直接断言 `send_key` 调用序列覆盖，不依赖 GUI 渲染；GUI 侧仅配置项新增（自动渲染）。实机验证需绑定副攻击键后开启开关观察连续两次出招

## Journey Log

- [lesson] 垫步与二连击互斥来自用户口径「攻击-副攻击零插入」——测试断言 call 序列而非行为描述，把零插入钉死在回归里
- [lesson] 复用「留空 = 关闭」约定而非再建一个开关状态，避免配置面出现「开了开关却没绑键」的半开状态

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/plans/2026-08-10-double-attack.md` | Implementation plan | 3 tasks, 全部完成 |
