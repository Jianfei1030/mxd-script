# 断线重连设计文档

> 日期：2026-08-10
> 状态：已批准（用户确认全部设计决策）

## [S1] 问题

冒险岛挂机掉线时：画面静止 → 游戏退回登录界面（输入账号密码处）+ overlay 弹窗提示掉线。当前行为：`MapleFarmTask` 静止守卫（默认 60s 画面静止）触发 `stop_farming('画面长时间静止(卡死/掉线/弹窗)')` → 任务 disable → 挂机停止，需人工重连。本特性实现掉线检测 + 自动重连，减少人工干预。

## [S2] 方案概述

**触发链（最简单路径，用户确认口径）**：

```
MapleFarmTask 静止守卫触发（画面静止 > 上限）
  → stop_farming('画面长时间静止(卡死/掉线/弹窗)')   [现有代码]
  → 触发 MapleReconnectTask.enable()                  [新增 3 行]
  → 重连任务 run() 状态机:
       IDLE（未被触发,快速 return）
       → CONFIRM_DISCONNECT（组合信号确认掉线,连续 N 帧）
       → EXECUTE_STEPS（按步骤列表逐条 click + sleep）
       → CONFIRM_RECONNECT（轮询 HP 条出现/画面不再静止,超时即失败）
       → SUCCESS: disable 自己 + 重新 enable 挂机任务
       → FAIL: 只试一次,disable + notify 用户,不自动重试
```

**用户明确决策**：
- 掉线检测信号：组合信号（HP条消失 + 无怪 + 静止帧），但**触发时机复用现有静止守卫**，不新增检测循环（"静止守卫触发后采取检测掉线，掉线检测成功就执行重连，就这么简单，没必要自己实现一堆"）
- 重连逻辑位置：独立重连任务类（不并入 MapleFarmTask）
- 步骤配置：开发期用鼠标事件录制脚本采集坐标（相对坐标 0-1）与时间间隔，实测确定后写入默认配置，并开放给用户配置
- 触发衔接：方案 A 事件触发 + 状态机（MapleFarmTask 静止守卫处 enable 重连任务）
- **重连失败策略：只试一次，失败即停**（用户最新修正，覆盖早期"自动重试"决策）

## [S3] 掉线检测与触发链路

### 3.1 触发点（MapleFarmTask 静止守卫分支，MapleFarmTask.py:1430-1437）

现有代码：

```python
sig = guards.signature(frame)
if self._last_sig is None or not guards.frame_frozen(self._last_sig, sig):
    self._last_sig = sig
    self._last_change_time = now
elif now - self._last_change_time > cfg['画面静止上限(秒)']:
    self.stop_farming('画面长时间静止(卡死/掉线/弹窗)')
    return
```

新增（在 `stop_farming` 之后）：

```python
    self._try_trigger_reconnect()
    return
```

`_try_trigger_reconnect` 实现：

```python
def _try_trigger_reconnect(self):
    """静止守卫触发后,若重连任务存在且开启,enable 它。重连任务缺失/关闭时
    保持原行为(任务已停,由用户人工处理)。"""
    try:
        from ok import og
        task = og.executor.get_task_by_class(MapleReconnectTask)
        if task is not None and task.config.get('重连开关', False):
            task.enable()
            self.log_warning('已触发断线重连任务')
    except Exception as e:
        self.log_warning(f'触发重连任务失败: {e!r}')
```

- 弱依赖：`get_task_by_class` + try/except 兜底，重连任务不存在/异常时挂机任务行为与现在完全一致
- 不动 `stop_farming` 本身（死亡/低血/药尽等 disable 不触发重连——只有静止守卫这一条路径触发，用户确认）

### 3.2 掉线确认（重连任务内，CONFIRM_DISCONNECT 阶段）

组合信号连续 `掉线确认帧数`（默认 5 帧 ≈ 2.5s @10Hz）帧全部满足才确认掉线：

| 信号 | 判定 | 实现 |
|---|---|---|
| HP 条消失 | `bars.read_hp(frame) < 0.01` | `src/detect/bars.py:34` |
| 无怪无玩家 | `find_all(frame)` 返回空 | `BaseMapleTask.find_all`（YOLO 全类别） |
| 画面静止 | `guards.frame_frozen(sig_a, sig_b)` | `src/detect/guards.py:11` |

- 确认成功 → EXECUTE_STEPS
- 确认失败（中途任何一帧不满足）→ 判定为「卡死/加载中等非掉线场景」→ disable 自己，保持停住，notify 用户人工处理

## [S4] 重连步骤状态机（EXECUTE_STEPS）

步骤列表 = 有序点击序列，存 JSON 配置，每步：

```json
{"名称": "关闭掉线弹窗", "x": 0.5, "y": 0.4, "等待(秒)": 1.0}
```

- **相对坐标（0-1）**：与 `click()` 的 relative 语义一致（task.py:157），分辨率自适应
- 每步执行：`self.click(x, y, name=步骤名)` → `self.sleep(等待)`
- **断点续传**：`_step_index` 存实例字段，run() 每拍推进，重启 GUI 后从上次中断的步骤续跑
- 步骤列表由录制脚本生成默认值，用户在 GUI `ModifyListItem`（ConfigItemFactory.py:63-69 已支持 list）里增删改

## [S5] 重连成功确认与失败处理（CONFIRM_RECONNECT）

- 步骤执行完后轮询（每拍一次）：HP 条出现（`bars.read_hp > 0.05`）且画面不再静止 → SUCCESS
- 超时 `重连确认超时(秒)`（默认 30s）→ FAIL
- **只试一次**：FAIL 后 `disable()` 自己 + `notification` 通知用户，不自动重试
- SUCCESS：`disable()` 自己 + 重新 `enable()` 挂机任务（若挂机任务仍存在）

## [S6] 配置项（GUI 分组「断线重连」）

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 重连开关 | bool | false | 总开关，关掉则掉线后不触发重连 |
| 掉线确认帧数 | int | 5 | 组合信号连续确认帧数 |
| 重连确认超时(秒) | float | 30 | 步骤执行完轮询回到游戏的超时 |
| 重连步骤 | list | [] | 步骤列表（录制生成默认值，用户可编辑） |

- 新增键必须同步加入 `MapleFarmTask.CONFIG_GROUPS`？——否：**重连任务有自己的 `CONFIG_GROUPS`**（独立任务类），挂机任务零配置改动
- 测试完整性：`tests/test_config_groups.py` 只检查 MapleFarmTask 的 DEFAULT_CONFIG，重连任务新增 `tests/test_reconnect_config_groups.py` 或复用同款完整性用例（按任务类名分别校验）

## [S7] 录制工具（scripts/record_login_steps.py，开发期一次性工具）

- 用 `pynput.mouse.Listener`（requirements.txt 已含 pynput==1.8.2）监听全局鼠标点击
- 快捷键：F9 开始/停止录制；记录每次点击的**相对坐标**（x/win_w, y/win_h，窗口尺寸从 `og.executor.method.width/height` 或 `config['window_size']` 读取）和**时间间隔**
- 手动登录一次完整流程（关闭弹窗 → 连接 → 选服 → 选线 → 选角色 → 进入游戏），结束后输出 JSON 步骤列表
- 输出粘贴为 `configs/MapleReconnectTask.json` 的 `重连步骤` 默认值
- 用户可调整：频道坐标、角色位坐标都在步骤列表里，每步 x/y 用户可改

## [S8] 文件结构与依赖

**新增**：
- `src/task/MapleReconnectTask.py` — 任务类 + 状态机（TriggerTask）
- `src/task/reconnect_logic.py` — 纯函数：掉线确认判定、步骤推进、超时判定（可单测）
- `scripts/record_login_steps.py` — 录制工具
- `tests/test_reconnect_logic.py` — 纯函数单测
- `tests/test_reconnect_task_offline.py` — 任务离线测试（合成帧，无 GUI/游戏）

**修改**：
- `config.py:74-76` — trigger_tasks 注册 `["src.task.MapleReconnectTask", "MapleReconnectTask"]`
- `src/task/MapleFarmTask.py:1430-1437` — 静止守卫分支加 `_try_trigger_reconnect()`
- `src/task/__init__.py` — 无需改（按模块路径导入）

**依赖**：pynput==1.8.2（已装，无新依赖）

## [S9] 测试与验收

### 9.1 单元测试（离线可跑，AGENTS.md §11.2 铁律）

`tests/test_reconnect_logic.py`：
- 掉线确认：三信号组合判定（HP消失/无怪/静止）正常路径、单信号缺失、连续帧确认/中断重置
- 步骤推进：索引推进、坐标/等待透传、列表空/单步/多步
- 超时判定：轮询成功、超时失败、边界（恰好超时）
- 只试一次：FAIL 后状态置终态不再重试

`tests/test_reconnect_task_offline.py`：
- IDLE 快速 return（不触发重连时零副作用）
- 触发后状态流转：CONFIRM_DISCONNECT → EXECUTE_STEPS → CONFIRM_RECONNECT → SUCCESS/FAIL
- 合成帧兜底：纯黑帧（HP=0、无怪、静止）构造掉线场景；黑帧仅用于行为逻辑测试（AGENTS.md §11.4）
- `重连开关=False` 时 MapleFarmTask 不触发重连
- 断点续传：模拟中途 _step_index 保留

### 9.2 配置完整性

- `tests/test_reconnect_config_groups.py`（或并入 test_config_groups）：重连任务 DEFAULT_CONFIG 全部键被 CONFIG_GROUPS 覆盖且不重复、唯一组名

### 9.3 编译检查与全量单测

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_reconnect_logic tests.test_reconnect_task_offline tests.test_reconnect_config_groups tests.test_farm_task_offline tests.test_config_groups
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"
```

### 9.4 E2E（AGENTS.md §11.3）

- 启动真实 GUI（main_debug.py）无崩溃
- 「实时触发」tab 出现「断线重连」卡片，配置分组/搜索/折叠正常（offscreen grab + 视觉验收，见 §12 分组特性经验）
- 真实掉线重连需实机验证（游戏内断线），验收记录写入 spec 验收章节

## [S10] 全局约束（Global Constraints）

- 禁止 hard code 本地路径（AGENTS.md §11.1）
- 禁止宽范围 grep（全局记忆 2026-08-11 立规）；探索用 explore subagent
- 测试命令必须从包目录/项目根执行，Python 3.12：`C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe`
- 新配置键只改 DEFAULT_CONFIG + CONFIG_GROUPS
- 重连任务与挂机任务解耦：MapleFarmTask 只加触发点，不 import 重连任务（运行时 `og.executor.get_task_by_class` 查找）
- 只试一次，失败即停；不做重试循环、不做多次尝试
- 相对坐标（0-1）存配置，不存绝对像素
