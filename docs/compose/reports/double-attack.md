# Double Attack（二连击）最终报告

> 2026-08-10 需求 → 2026-08-11 实施完成。计划: `docs/compose/plans/2026-08-10-double-attack.md`

## 目标

有的怪物一次打不死——第一下打完后它靠近尝试攻击，被角色/宠物遮挡导致短暂检测不到，直到怪进入可检测范围才最终击杀，恰好约 2 下。为这类怪物增加「二连击」：检测模式下怪进入攻击范围，先按攻击键、立即接副攻击键，两键之间**不插入任何指令**（垫步被跳过）。

## 实现

| 文件 | 改动 |
|---|---|
| `config.py` | 「游戏按键」新增 `副攻击键(可留空)`（默认 ''，留空 = 二连击关闭，同群攻键约定） |
| `src/task/MapleFarmTask.py` | `DEFAULT_CONFIG` 新增 `二连击开关`（默认 False）；`CONFIG_GROUPS`「攻击」组归入；配置描述补充 |
| `src/task/MapleFarmTask.py` `_do_attack` | 单体攻击分支：`double_attack = 二连击开关 and 副攻击键非空` → 垫步门加 `not double_attack` → 攻击键后紧接副攻击键，`_last_attack = now` 记一次（共用攻击间隔节拍） |
| `tests/test_farm_task_offline.py` | KEYS 补副攻击键；TestAttackTap 新增 6 用例 |

## 行为矩阵

| 二连击开关 | 副攻击键 | 攻击前垫步开关 | 行为 |
|---|---|---|---|
| off | 任意 | on/off | 原行为不变（垫步→攻击键） |
| on | 空 | 任意 | 视为关闭，只按攻击键 |
| on | 已绑定 | on | 攻击键→副攻击键，**跳过垫步** |
| on | 已绑定 | off | 攻击键→副攻击键 |
| 群攻路径（区内怪数≥阈值） | — | — | 只按群攻键，二连击不介入（`_aoe_ready` return 在前） |

## 测试证据

- `tests.test_farm_task_offline.TestAttackTap`：6 个新用例（默认关/两键背靠背/副键留空关闭/跳过垫步/共用攻击间隔/群攻路径不受影响）+ 全部既有用例绿
- 全量回归：`unittest discover` 600 tests **OK (skipped=12)**——无新增红（12 个 skip 均为存量：存档帧缺失/OCR 限制/val 数据缺失）
- 编译检查：`py_compile` 全源码 OK

## 提交

- `47325e5` feat: 新增副攻击键与二连击开关配置(默认关,攻击组)
- `9ee3906` feat: 二连击——攻击键+副攻击键背靠背连按,开启时跳过垫步
- `2xxxxxx` docs: double attack 功能入 AGENTS.md 与最终报告

## E2E 说明

本功能为纯按键时序逻辑，行为由 TestAttackTap 直接断言 `send_key` 调用序列覆盖（`[call('shift'), call('x')]` 背靠背、无方向键插入），不依赖 GUI 渲染；GUI 侧仅有配置项新增（自动由 ConfigCard 渲染，含搜索/分组），启动无崩溃即可。实机验证需在设置页「游戏按键」绑定副攻击键后，开启「二连击开关」观察游戏内连续两次出招。
