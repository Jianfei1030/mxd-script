# 没药自动回城设计文档

> 日期：2026-08-10
> 状态：已批准（用户确认全部设计决策）

## [S1] 问题

挂机时血药/蓝药耗尽，当前行为只是 `stop_farming('血/蓝药耗尽')`（MapleFarmTask.py:1368）——任务停在原地等用户人工处理，角色一直站在怪堆里。本特性实现：没药时自动用回城卷回城，回城后停任务并通知用户买药。

**关键约束（用户确认）**：回城卷轴**无法在快捷键使用**，必须通过视觉方案识别回城卷在背包里的位置，然后**双击**使用。这不是 `send_key(回城卷键)`，而是「打开背包 → 视觉定位卷轴 → 双击 → 回城」。

## [S2] 方案概述

```
MapleFarmTask.run() §3.5 药水耗尽保护（现有 30s 低频 OCR 检查,不动节奏）
  → potions_exhausted 判定血/蓝药耗尽
  → 新增分支（替换原 stop_farming 直停）:
       「没药回城开关」开 且 背包键已配 且 回城卷模板存在
         → 进入回城子流程（多拍状态机）
      否则 → stop_farming('血/蓝药耗尽')（保持现状）
```

**回城子流程（状态机,run() 每拍推进）**：
```
idle → open_bag（按背包键,等背包打开）
     → find_scroll（模板匹配定位回城卷;未找到 → 失败停止+通知）
     → double_click（双击卷轴,无确认框直接回城）
     → wait_return（等待回城完成:画面变化/静止恢复,超时即失败）
     → done（stop_farming('没药回城') + 通知用户买药）
```

**用户明确决策**：
- 回城方式：回城卷回城（复用「回城卷」概念,但改为视觉定位+双击,不走快捷键）
- 回城后动作：停任务 + 通知,不做自动买药
- 触发时机：复用现有 30s 低频 OCR 检查（§3.5）,不动检测节奏
- 识别方式：**模板匹配**（我来定:项目已有 anchor.py 的 TM_SQDIFF_NORMED 先例;固定图标+固定 UI,零训练、快而准;YOLO 扩类需大量采集标注,不划算）
- 双击后流程：无确认框直接回城
- 低血保命回城：**只改没药回城**;低血保命回城保持现状（回城卷键）,不共用视觉方案
- 背包打开：新增「背包键(可留空)」配置

## [S3] 回城卷识别（模板匹配）

### 3.1 模板来源

- 新增 `screenshots/scroll_templates/scroll.png`（回城卷图标模板,开发期采集）
- 采集方式：打开背包 → 截帧 → 用现有 `label_boxes.py` 标注回城卷框 → 从标注框裁剪图标存为模板（新增脚本 `scripts/crop_template.py`,一次裁剪成模板 PNG）
- 模板匹配在**背包区域内**扫描（背包 ROI 需标定,默认全屏背包打开时扫描,后续可收窄）

### 3.2 匹配实现

新增 `src/detect/scroll.py`（纯函数,可单测）：
- `load_template(path)`：读模板灰度图,失败返回 None（缺失时回城子流程直接走失败路径,不崩）
- `find_scroll(frame, template, threshold)`：cv2 `matchTemplate` + `minMaxLoc`,阈值判定,返回命中中心点 `(x, y)` 或 None
- 与 anchor.py 同口径：`TM_SQDIFF_NORMED`（值越小越像,阈值归一化后比较）

### 3.3 匹配范围

- 背包打开后全屏范围匹配（背包 UI 固定,模板唯一性强）
- 未找到 → 失败路径：停任务 + 通知「未找到回城卷,请手动回城」（不反复重试）

## [S4] 回城子流程状态机

新增实例字段（MapleFarmTask）：
- `_return_state`：`'idle' | 'open_bag' | 'find_scroll' | 'double_click' | 'wait_return' | 'done' | 'failed'`
- `_return_started_at`：子流程开始时间（超时判定）
- `_return_step_at`：当前步骤开始时间

| 状态 | 动作 | 转移 |
|---|---|---|
| idle | 无 | 检测到耗尽且开关开 → open_bag |
| open_bag | `send_key(背包键)` | 延迟 `背包延迟(秒)`(默认 1.0)后 → find_scroll |
| find_scroll | `find_scroll(frame, template)` | 命中 → double_click;None → failed |
| double_click | `click(x, y)` ×2(间隔 ~0.3s) | → wait_return |
| wait_return | 轮询画面变化（签名变化,guards.signature 差值恢复）| 变化确认 → done;超时 `回城等待超时(秒)`(默认 10s)→ failed |
| done | `stop_farming('没药回城,请买药')` | → idle（任务已 disable） |
| failed | `stop_farming('回城失败:...')` + 通知 | → idle（只试一次） |

- 失败路径**只试一次**：不做重试循环（与断线重连同风格）
- 子流程期间挂机任务 run() 其他逻辑**不再执行**（进入子流程后每拍只推进回城状态机,防边回城边打怪）

## [S5] 配置项

### 5.1 全局按键（config.py「游戏按键」）

| 键 | 默认 | 说明 |
|---|---|---|
| 背包键(可留空) | 'i' | 打开/关闭背包。留空则没药回城功能不可用（走现有 stop_farming） |

### 5.2 MapleFarmTask DEFAULT_CONFIG + CONFIG_GROUPS「保命与药水」组

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 没药回城开关 | bool | false | 总开关 |
| 背包延迟(秒) | float | 1.0 | 按背包键后等背包打开的延迟 |
| 回城等待超时(秒) | float | 10.0 | 双击后等待回城完成的超时 |

（回城卷模板路径固定 `screenshots/scroll_templates/scroll.png`,不开放配置——开发期一次性采集,减少配置面）

## [S6] 文件结构与依赖

**新增**：
- `src/detect/scroll.py` — 模板匹配纯函数
- `scripts/crop_template.py` — 从背包帧+标注框裁剪模板（开发期工具）
- `tests/test_scroll.py` — 模板匹配单测

**修改**：
- `config.py:9-27` — 游戏按键加 `背包键(可留空)`
- `src/task/MapleFarmTask.py` — DEFAULT_CONFIG + CONFIG_GROUPS 新键;§3.5 耗尽分支改回城子流程;新增状态机方法
- `tests/test_farm_logic.py` — 无（回城判定逻辑简单,并入任务测试）
- `tests/test_farm_task_offline.py` — 回城子流程状态机测试
- `tests/test_config_groups.py` — 新键归组完整性自动覆盖

**依赖**：无新依赖（cv2 已有,模板匹配同 anchor.py）

## [S7] 测试与验收

### 7.1 单元测试（离线可跑）

`tests/test_scroll.py`：
- 合成帧上绘制已知图案 → 模板匹配命中正确位置
- 无关图案 → 返回 None
- 阈值判定：低阈值命中/高阈值拒绝
- 模板缺失 → load_template 返回 None（不崩）

`tests/test_farm_task_offline.py`（新增回城用例）：
- 耗尽触发：hp_count=0 且 hp<阈值 → 进入回城子流程（而非直接 stop）
- 开关关/背包键留空 → 走原 stop_farming 路径
- 状态流转：open_bag → find_scroll（合成帧画模板）→ double_click（记录 click 序列）→ wait_return → done
- 模板未找到 → failed + stop_farming
- 超时 → failed
- 只试一次：failed 后不再重试

### 7.2 编译检查与全量单测

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_scroll tests.test_farm_task_offline tests.test_config_groups
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"
```

### 7.3 E2E（AGENTS.md §11.3）

- GUI 启动无崩溃;「自动打怪」卡片「保命与药水」组出现新键
- 实机验收：游戏内没药场景触发回城（需实机验证模板匹配命中率）,结论写入 spec 验收章节
- 模板采集：开发期打开背包截帧 → crop_template 生成模板 → 人工核对

## [S8] 全局约束（Global Constraints）

- 禁止 hard code 本地路径;模板路径相对项目根
- 新配置键只改 DEFAULT_CONFIG + CONFIG_GROUPS
- 回城子流程期间 run() 其他逻辑不执行（状态机优先）
- 只试一次,失败即停;不做重试循环
- 低血保命回城（回城卷键路径）保持现状,本次不改
- 识别用模板匹配（cv2,零训练）;不用 YOLO 扩类（采集标注成本高,固定图标不值得）
