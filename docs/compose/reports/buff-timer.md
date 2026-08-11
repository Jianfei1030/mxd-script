---
feature: buff-timer
status: delivered
specs:
  - specs/2026-08-10-buff-timer-design.md
plans:
  - plans/2026-08-10-buff-timer.md
branch: master
commits: c3c7a79..7da0eee
---

# 定时补BUFF（Buff Timer）— Final Report

## What Was Built

挂机定时补BUFF：每个 BUFF **独立配置按键 + 间隔时间**，到点且**攻击区内无怪**时自动按 BUFF 快捷键补上；攻击区内有怪则优先解决怪物，补BUFF顺延到下一拍；触发那一拍暂停攻击/寻怪，只按 BUFF 键。

用户口径（spec §S1 关键约束）：每 BUFF 独立间隔（非全局统一）；攻击区判定用有向攻击区（`_last_attack_present`，去抖后）；补BUFF时停手。

## Architecture

三处改动 + 两个纯函数：

| 文件 | 职责 |
|---|---|
| `src/task/farm_logic.py` | `parse_buff_config` 扩展为三元组 `(name, key, interval)`（支持 `:间隔秒` 后缀）；新增 `due_buffs` 到期判定 |
| `src/task/MapleFarmTask.py` | `DEFAULT_CONFIG` 新增 `补BUFF开关`(False) / `补BUFF列表`('')；`CONFIG_GROUPS`「挂机辅助」组归入；`_reset_state` 加 `_last_buff_times`；`run()` §3.6 补BUFF块 |
| `tests/` | `test_farm_logic.py`（解析/到期边界）+ `test_farm_task_offline.py::TestBuffTimer`（7 用例） |

核心逻辑（`run()` §3.6，攻击块之前）：

```python
if cfg['补BUFF开关'] and self._last_attack_present is False:
    due = farm_logic.due_buffs(now, farm_logic.parse_buff_config(cfg['补BUFF列表']),
                               self._last_buff_times)
    if due:
        self._release_seek_key()   # 停手:先松开寻怪长按的方向键
        self._seek_dir = None      # 停追:本拍不寻怪
        for name, key in due:
            self.send_key(key)
            self._last_buff_times[name] = now
        self.log_info(f'补BUFF: {", ".join(n for n, _ in due)}')
        return   # 本拍只补BUFF,不执行攻击/寻怪/坐椅等
```

### Design Decisions

- **每 BUFF 独立计时**：`_last_buff_times: dict[str, float]`，到期 = `now - last_times.get(name, 0) >= interval`，未补过视为到期（到点即补）。
- **坏间隔整条丢弃**：`bad=x:abc` 整条忽略而非保留为"手动键"——配置打错字不该静默变成手动模式，用户会以为自动补生效了（计划明确口径）。
- **interval None 永不自动补**：`魔法盾=q`（无 `:间隔`）保留手动按键能力，不参与 `due_buffs`。
- **有怪优先**：`_last_attack_present is False` 门——攻击区有怪时补BUFF块直接跳过，攻击逻辑正常执行。
- **停手语义**：触发时松寻怪键 + 停追 + 本拍 `return`，与死亡/保命 return 同模式。
- **定频模式不补BUFF**：定频无攻击区状态（`_last_attack_present` 恒 None），`is False` 判定不成立，开关描述已注明（同坐椅的定频例外）。

## Usage

「自动打怪」卡片展开区「挂机辅助」组：

1. 打开「补BUFF开关」
2. 填「补BUFF列表」：`魔法盾=q:180,狂暴=w:300`（逗号分隔，每项 `名称=按键:间隔秒`）
3. 检测模式下到点且攻击区内无怪 → 自动按 q 补魔法盾、w 补狂暴

行为矩阵：

| 补BUFF开关 | 攻击区有怪 | BUFF 到期 | 行为 |
|---|---|---|---|
| off | 任意 | 任意 | 不补 |
| on | 是 | 任意 | 不补,正常攻击,顺延下一拍 |
| on | 否 | 无到期 | 不补,正常挂机 |
| on | 否 | 有到期 | 松寻怪键+停追+按到期 BUFF 键+本拍 return |
| on | 否 | 多 BUFF 部分到期 | 只补到期的,各自独立计时 |

## Verification

- `tests/test_farm_logic.py`：parse_buff_config 三元组/空串/坏条目/坏间隔跳过 + due_buffs 从未补过/未到期/边界(=间隔恰好到期)/interval None/多 BUFF 混合
- `tests/test_farm_task_offline.py::TestBuffTimer` 7 用例：开关关不补 / 到期补键+更新计时 / 未到期不补 / 有怪不补 / 多BUFF只补到期 / 触发停手(松寻怪键+停追+本拍 return) / interval None 不补
- 全量回归：660 tests **OK (skipped=16)**——无新增红（skip 均为存量：存档帧缺失等）
- 编译检查：`py_compile` 全源码 OK
- E2E：offscreen 渲染「自动打怪」ConfigCard，断言 `补BUFF开关`/`补BUFF列表` 出现在「挂机辅助」组，截图 `screenshots/e2e/buff_timer/config_card_offscreen_20260812.png` 经视觉模型验收通过（UI 结构正常，中文字体 tofu 为 offscreen 环境缺字体，非代码问题）
- 实机验收待做：站桩配置 `魔法盾=q:180,狂暴=w:300` 观察 3 分钟自动补；战斗中被怪打断时优先攻击

## Journey Log

- [lesson] 测试隔离：坐椅/走位/寻怪都有独立节拍（`_last_attack_present is False` 时坐椅会触发、走位 120s 到期），补BUFF用例必须在 `_task` 工厂里关掉三者，否则 `send_key` 序列断言被 `call('r')`/方向键污染
- [lesson] 测试预期算术错误：`狂暴=w:300` 在 `now=200` 时 `200-0=200 < 300` 未到期——用例先用真实间隔算清楚再写断言（第一次写错导致红）
- [lesson] PowerShell `Add-Content` 追加中文 + 后续 `edit` 工具替换同一区域会遇到 CRLF/编码匹配失败，改用 Python 脚本做字节级替换

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/specs/2026-08-10-buff-timer-design.md` | Design spec | 已批准（用户确认全部设计决策） |
| `docs/compose/plans/2026-08-10-buff-timer.md` | Implementation plan | 5 tasks, 全部完成 |
