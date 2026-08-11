# 断线重连实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 冒险岛挂机掉线自动重连——静止守卫触发后,组合信号确认掉线,按录制步骤列表自动重连,只试一次失败即停。

**Architecture:** 独立 `MapleReconnectTask`(TriggerTask) + 纯函数层 `reconnect_logic.py`;`MapleFarmTask` 静止守卫分支新增触发点(运行时经 `og.executor.get_task_by_class` 查找,弱依赖);步骤列表存相对坐标(0-1)JSON 配置,开发期用 `scripts/record_login_steps.py`(pynput)录制默认值。

**Spec:** [2026-08-10-disconnect-reconnect-design.md](../specs/2026-08-10-disconnect-reconnect-design.md)

**Tech Stack:** Python 3.12 / PySide6 GUI / unittest / pynput==1.8.2(已装,无新依赖)

## Global Constraints

- 禁止 hard code 本地路径;相对坐标(0-1)存配置,不存绝对像素
- 重连任务与挂机任务解耦:MapleFarmTask 只加触发点,不 import 重连任务;`og.executor.get_task_by_class` + try/except 兜底,重连任务缺失时行为与现在一致
- 只试一次,失败即停;不做重试循环
- 新配置键只改对应任务的 DEFAULT_CONFIG + CONFIG_GROUPS;重连任务配置键归入自己的 CONFIG_GROUPS
- 测试命令: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest <modules>`
- 编译检查: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`

---

### Task 1: 纯函数层 reconnect_logic.py + 单测

**Covers:** spec [S3.2]（掉线确认）、[S4]（步骤推进）、[S5]（重连确认/超时/只试一次）

**Files:**
- Add: `src/task/reconnect_logic.py`
- Add: `tests/test_reconnect_logic.py`

**Interfaces:**
- Consumes: 无（纯函数,入参传帧/信号值,不依赖 task/executor）
- Produces: 掉线确认判定、步骤推进、重连确认判定、超时判定——Task 2 的任务类只做调度

- [ ] **Step 1: 先写测试（TDD 红）**

`tests/test_reconnect_logic.py` 覆盖：
- `disconnect_confirmed(hp, has_boxes, frozen, ...)`：三信号组合——全满足 True；任一缺失 False；连续帧计数逻辑（帧数递增/中断重置/达到阈值确认）
- 步骤推进：`next_step_index(step_index, total_steps)` 索引推进、越界停止；步骤列表空/单步/多步
- 重连确认：`reconnect_confirmed(hp, frozen)`（HP 出现且不静止 → True）；`reconnect_timed_out(now, started_at, timeout)`（边界：恰好超时）

先跑测试确认红：
```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_reconnect_logic
```
Expected: FAIL（模块不存在）

- [ ] **Step 2: 实现纯函数**

`src/task/reconnect_logic.py` 实现上述函数（含模块级 docstring 说明相对坐标约定）。保持与 farm_logic.py 相同的纯函数风格（无 self、无 IO、类型靠推断）。

- [ ] **Step 3: 全绿**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_reconnect_logic
```
Expected: OK（全绿）

---

### Task 2: MapleReconnectTask 任务类 + 状态机 + 离线测试

**Covers:** spec [S2]（状态机）、[S3.2]（掉线确认调度）、[S4]（步骤执行）、[S5]（成功/失败处理）、[S6]（配置）

**Files:**
- Add: `src/task/MapleReconnectTask.py`
- Add: `tests/test_reconnect_task_offline.py`

**Interfaces:**
- Consumes: `self.frame`（executor 预取,同 MapleFarmTask）、`self.click(x, y, name=...)`、`self.sleep(...)`、`bars.read_hp`、`find_all`（BaseMapleTask）、`guards.signature/frame_frozen`、`self.config`（DEFAULT_CONFIG 见下）
- Produces: 触发后自动 enable/disable 自身;成功时重新 enable 挂机任务

- [ ] **Step 1: 任务类骨架 + DEFAULT_CONFIG + CONFIG_GROUPS**

`src/task/MapleReconnectTask.py`（`TriggerTask, BaseMapleTask` 双继承,同 MapleFarmTask 模式）：

```python
DEFAULT_CONFIG = {
    '重连开关': False,
    '掉线确认帧数': 5,
    '重连确认超时(秒)': 30.0,
    '重连步骤': [],
}

CONFIG_GROUPS = [
    ('断线重连', ['重连开关', '掉线确认帧数', '重连确认超时(秒)', '重连步骤']),
]
```

- [ ] **Step 2: 状态机 run()**

```python
def run(self):
    # IDLE:未被触发(重连开关关 或 非掉线流程中)快速 return
    if not self.config.get('重连开关') or self._state == 'idle':
        self._state = 'idle'
        return
    ...
```

状态：`idle → confirm_disconnect → execute_steps → confirm_reconnect → success/fail`。实例字段：`_state`、`_disconnect_frames`、`_step_index`、`_state_started_at`。每拍推进:
- `confirm_disconnect`：`disconnect_confirmed(...)` 连续 N 帧 → `execute_steps`;中断 → disable 自己 + notify（判定非掉线）
- `execute_steps`：`self.click(step['x'], step['y'], name=step['名称'])` + `self.sleep(step['等待(秒)'])` + `_step_index += 1`;列表走完 → `confirm_reconnect`
- `confirm_reconnect`：轮询 HP 出现且不静止 → success;超时 → fail（只试一次）
- `success`：disable 自己 + 重新 enable 挂机任务（`og.executor.get_task_by_class(MapleFarmTask)` + `enable()` + try 兜底）
- `fail`：disable 自己 + notify 用户,不重试

- [ ] **Step 3: 离线测试**

`tests/test_reconnect_task_offline.py`（合成帧兜底,AGENTS.md §11.4）：
- IDLE 快速 return（未触发时零副作用,不调用 click）
- 触发后状态流转（mock click/sleep 记录调用序列）:confirm_disconnect → execute_steps → confirm_reconnect → success/fail
- 黑帧构造掉线场景（HP=0、无怪、静止）
- 断点续传：`_step_index` 保留
- `重连开关=False` 时 `_try_trigger_reconnect` 不触发

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_reconnect_task_offline
```
Expected: OK

---

### Task 3: MapleFarmTask 触发点（3 行）+ 注册

**Covers:** spec [S3.1]（触发链）

**Files:**
- Modify: `src/task/MapleFarmTask.py:1435-1437`（静止守卫分支）
- Modify: `config.py:74-76`（trigger_tasks 注册）

**Interfaces:**
- Consumes: `MapleReconnectTask` 类名（仅字符串查找,不 import）
- Produces: 静止守卫触发后 enable 重连任务

- [ ] **Step 1: 加触发点**

`MapleFarmTask.py` 静止守卫分支 `self.stop_farming('画面长时间静止(卡死/掉线/弹窗)')` 后加 `self._try_trigger_reconnect()` + return;新增 `_try_trigger_reconnect` 方法（运行时 `from ok import og` + `og.executor.get_task_by_class(MapleReconnectTask)`,try/except 兜底,日志 warning）。

- [ ] **Step 2: 注册任务**

`config.py:74-76` trigger_tasks 追加：
```python
["src.task.MapleReconnectTask", "MapleReconnectTask"],
```

- [ ] **Step 3: 验证既有测试不回归**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_task_offline tests.test_config_groups
```
Expected: OK（既有测试全绿）

---

### Task 4: 配置完整性测试

**Covers:** spec [S6]（配置）、[S9.2]（完整性）

**Files:**
- Add: `tests/test_reconnect_config_groups.py`

**Interfaces:**
- Consumes: `MapleReconnectTask.DEFAULT_CONFIG` / `CONFIG_GROUPS`
- Produces: 完整性保障（同 test_config_groups 对 MapleFarmTask 的检查）

- [ ] **Step 1: 复用完整性用例**

同 `tests/test_config_groups.py` 模式：`DEFAULT_CONFIG` 全部键被 `CONFIG_GROUPS` 覆盖且不重复、唯一组名、组内键存在于 DEFAULT_CONFIG。

- [ ] **Step 2: 全绿**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_reconnect_config_groups
```
Expected: OK

---

### Task 5: 录制脚本 record_login_steps.py

**Covers:** spec [S7]（录制工具）

**Files:**
- Add: `scripts/record_login_steps.py`

**Interfaces:**
- Consumes: pynput.mouse.Listener、窗口尺寸（`og.executor.method.width/height` 或 `config['window_size']`,运行时获取,禁止 hard code）
- Produces: JSON 步骤列表（打印到 stdout,供粘贴为 `重连步骤` 默认值）

- [ ] **Step 1: 实现录制脚本**

- F9 开始/停止录制;`pynput.mouse.Listener` 监听 on_click,记录相对坐标 + 与上次点击的时间间隔;退出时打印 `{"重连步骤": [...]}` JSON
- 项目根由脚本自身推导（AGENTS.md §11.1）;依赖缺失（如 pynput 未装）时显式报错提示安装
- 使用说明写脚本 docstring（如何录制一次完整登录流程）

- [ ] **Step 2: 编译检查**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import py_compile; py_compile.compile('scripts/record_login_steps.py', doraise=True); print('OK')"
```
Expected: OK

---

### Task 6: 全量验证

**Covers:** spec [S9.3][S9.4]

**Files:** 无（验证）

- [ ] **Step 1: 全量单测 + 编译检查**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_logic tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine tests.test_analyze_anchor tests.test_analyze_facing tests.test_analyze_seek tests.test_analyze_turn tests.test_facing tests.test_label_boxes tests.test_yolo tests.test_config_groups tests.test_config_card_ui tests.test_reconnect_logic tests.test_reconnect_task_offline tests.test_reconnect_config_groups
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"
```
Expected: 全绿 + OK

- [ ] **Step 2: GUI 启动 E2E**

启动 `main_debug.py`（ShellExecute runas,AGENTS.md §1.3）无崩溃;「实时触发」tab 出现「断线重连」卡片,配置分组显示正常（offscreen grab + 视觉验收,同 §12 config_groups 经验）。验收结论写入 spec 验收章节。

- [ ] **Step 3: 文档更新**

- `AGENTS.md` 新增「断线重连」章节（配置键表格 + 录制脚本用法 + 实机验收记录指针）
- spec 验收章节写 E2E 结论

---

### Task 7: 最终报告

- 写 `docs/compose/reports/disconnect-reconnect.md`（frontmatter + specs/plans/branch/commits + 验收结论,格式同 `docs/compose/reports/double-attack.md`）
- 更新 plan 文件 NOTE 标记（同 double-attack plan 模式）
