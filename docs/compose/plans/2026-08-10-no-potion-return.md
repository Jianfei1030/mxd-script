# 没药自动回城实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 挂机血药/蓝药耗尽时自动回城——打开背包 → 模板匹配定位回城卷 → 双击 → 回城 → 停任务+通知。只试一次,失败即停。

**Architecture:** 复用现有 §3.5 药水耗尽保护（30s 低频 OCR 检查,节奏不动）;耗尽判定后进入回城子流程状态机（MapleFarmTask 内多拍推进）;回城卷识别用 cv2 模板匹配（anchor.py 同款 TM_SQDIFF_NORMED,零训练）;模板 PNG 开发期采集。

**Spec:** [2026-08-10-no-potion-return-design.md](../specs/2026-08-10-no-potion-return-design.md)

**Tech Stack:** Python 3.12 / PySide6 GUI / unittest / cv2（已装,无新依赖）

## Global Constraints

- 禁止 hard code 本地路径;模板路径相对项目根（`screenshots/scroll_templates/scroll.png`）
- 新配置键只改对应任务 DEFAULT_CONFIG + CONFIG_GROUPS
- 回城子流程期间 run() 其他逻辑不执行（状态机优先）;只试一次,失败即停
- 低血保命回城（回城卷键路径）保持现状,本次不改
- 测试命令: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest <modules>`
- 编译检查: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`

---

### Task 1: 模板匹配纯函数 scroll.py + 单测

**Covers:** spec [S3]（识别实现）

**Files:**
- Add: `src/detect/scroll.py`
- Add: `tests/test_scroll.py`

**Interfaces:**
- Consumes: 帧 BGR ndarray + 模板灰度图 + 阈值
- Produces: `load_template(path) -> np.ndarray | None`、`find_scroll(frame, template, threshold) -> (x, y) | None`——Task 2 的 MapleFarmTask 用这两个函数

- [ ] **Step 1: 先写测试（TDD 红）**

`tests/test_scroll.py`（合成帧,cv2 绘制）：
- 已知图案命中正确位置
- 无关图案返回 None
- 阈值判定（低阈值命中/高阈值拒绝）
- 模板缺失 load_template 返回 None

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_scroll
```
Expected: FAIL（模块不存在）

- [ ] **Step 2: 实现**

`src/detect/scroll.py`：
```python
def load_template(path):  # 读灰度,cv2.imread(path, 0);失败返回 None
def find_scroll(frame, template, threshold):
    # cv2.matchTemplate + minMaxLoc;TM_SQDIFF_NORMED 值越小越像
    # min_val <= threshold 时返回 (x, y),否则 None
```

- [ ] **Step 3: 全绿**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_scroll
```
Expected: OK

---

### Task 2: 配置层（背包键 + 没药回城开关 + 归组）

**Covers:** spec [S5]（配置）

**Files:**
- Modify: `config.py:9-27`（游戏按键加 `背包键(可留空)`,默认 'i',config_description 补描述）
- Modify: `src/task/MapleFarmTask.py` DEFAULT_CONFIG（`'没药回城开关': False`、`'背包延迟(秒)': 1.0`、`'回城等待超时(秒)': 10.0`）
- Modify: `src/task/MapleFarmTask.py` CONFIG_GROUPS「保命与药水」组加三个新键
- Modify: `src/task/MapleFarmTask.py` 配置描述 dict 补键描述

**Interfaces:**
- Consumes: 无
- Produces: 配置键——Task 3 的 §3.5 分支读取

- [ ] **Step 1: 加 DEFAULT_CONFIG 键,跑完整性用例确认红**

在 `'药水耗尽保护': True,` 后插入三个新键,运行 `tests.test_config_groups` 确认 FAIL（未归组）。

- [ ] **Step 2: 归组 + 补描述**

CONFIG_GROUPS「保命与药水」组加：`'没药回城开关', '背包延迟(秒)', '回城等待超时(秒)'`。

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_config_groups
```
Expected: OK

---

### Task 3: 回城子流程状态机

**Covers:** spec [S4]（状态机）、[S2]（方案概述）

**Files:**
- Modify: `src/task/MapleFarmTask.py`

**Interfaces:**
- Consumes: `scroll.load_template/find_scroll`、`self.send_key(背包键)`、`self.click(x, y)`、`guards.signature`、`self.config` 新键
- Produces: 回城子流程推进;完成/失败后 stop_farming

- [ ] **Step 1: 实例字段初始化**

`_reset_state()` 加：`_return_state = 'idle'`、`_return_started_at = 0.0`、`_return_step_at = 0.0`、`_return_template = None`（懒加载模板,首次进子流程时 load 一次）。

- [ ] **Step 2: 替换 §3.5 耗尽分支**

原：
```python
if empty:
    self.stop_farming(f'{"血" if empty == "hp" else "蓝"}药耗尽')
    return
```
改为：
```python
if empty:
    if self._try_start_return(cfg, keys):
        return  # 进入回城子流程,本拍不再执行其他逻辑
    self.stop_farming(f'{"血" if empty == "hp" else "蓝"}药耗尽')
    return
```

`_try_start_return(cfg, keys)`：开关开 且 `背包键(可留空)` 非空 且模板已加载 → 置 `_return_state='open_bag'`、`_return_started_at=now`、返回 True;否则返回 False。

- [ ] **Step 3: run() 顶部子流程优先**

run() 开头（`frame is None` 检查后）：
```python
if self._return_state != 'idle':
    self._advance_return(now, cfg, keys)
    return
```
`_advance_return` 按 [S4] 表推进状态机;done/failed 时 `stop_farming(...)` + `_return_state='idle'`。

**注意**：进入子流程的拍——`_try_start_return` 返回 True 且 return,下一拍 run() 顶部 `_return_state != 'idle'` 拦截,正常推进。回城期间不执行攻击/喝药/寻怪等逻辑。

- [ ] **Step 4: 离线测试（TDD 补充）**

`tests/test_farm_task_offline.py` 新增回城用例：
- 耗尽触发进入子流程（合成帧画模板图案,hp_count=0）
- 开关关/背包键留空 → 走原 stop_farming
- 状态流转全链（open_bag→find_scroll→double_click→wait_return→done,记录 click/send_key 调用序列）
- 模板未找到 → failed
- 超时 → failed
- 只试一次：failed 后状态回 idle 不重试

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_task_offline
```
Expected: OK

---

### Task 4: 模板裁剪工具 crop_template.py

**Covers:** spec [S3.1]（模板来源）

**Files:**
- Add: `scripts/crop_template.py`

**Interfaces:**
- Consumes: 背包打开帧路径 + 标注框（复用 label_boxes 输出的 txt）
- Produces: `screenshots/scroll_templates/scroll.png`（模板灰度图）

- [ ] **Step 1: 实现**

- 输入：`--frame <背包帧> --label <对应 yolo txt>`（txt 存 0 cx cy w h）
- 输出：从帧裁剪标注框区域,保存灰度 PNG 到 `screenshots/scroll_templates/scroll.png`
- 项目根由脚本自身推导（AGENTS.md §11.1）

- [ ] **Step 2: 编译检查**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import py_compile; py_compile.compile('scripts/crop_template.py', doraise=True); print('OK')"
```
Expected: OK

---

### Task 5: 全量验证 + 文档

**Covers:** spec [S7]（测试与验收）

**Files:** 无代码（验证）+ `AGENTS.md` 更新

- [ ] **Step 1: 全量单测 + 编译检查**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_logic tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine tests.test_analyze_anchor tests.test_analyze_facing tests.test_analyze_seek tests.test_analyze_turn tests.test_facing tests.test_label_boxes tests.test_yolo tests.test_config_groups tests.test_config_card_ui tests.test_scroll
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`
Expected: 全绿 + OK

- [ ] **Step 2: GUI 启动 E2E**

启动 `main_debug.py`（ShellExecute runas,AGENTS.md §1.3）无崩溃;「自动打怪」卡片「保命与药水」组出现新键（offscreen grab + 视觉验收）。

- [ ] **Step 3: 文档更新**

- `AGENTS.md` 补「没药自动回城」配置键说明（§10 参考配置表附近）
- spec 验收章节写 E2E 结论;实机模板命中率验收记录（需游戏内没药场景）

---

### Task 6: 最终报告

- 写 `docs/compose/reports/no-potion-return.md`（frontmatter + specs/plans/branch/commits + 验收结论,格式同 `docs/compose/reports/double-attack.md`）
- 更新 plan 文件 NOTE 标记
