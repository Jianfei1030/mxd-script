# 定时补BUFF实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 挂机定时补BUFF——每个 BUFF 独立配置按键+间隔,到点且攻击区内无怪时自动按快捷键补上;攻击区内有怪优先解决,补BUFF顺延;补BUFF时停手。

**Architecture:** 复用已预留的 `farm_logic.parse_buff_config`(farm_logic.py:205,`名称=按键` 逗号分隔)扩展支持每项 `:间隔秒`;新增 `due_buffs` 纯函数按每 BUFF 独立计时;MapleFarmTask run() 攻击块之前加补BUFF块(攻击区无怪门 + 停手 return)。

**Spec:** [2026-08-10-buff-timer-design.md](../specs/2026-08-10-buff-timer-design.md)

**Tech Stack:** Python 3.12 / PySide6 GUI / unittest(无新依赖)

## Global Constraints

- 新配置键只改 DEFAULT_CONFIG + CONFIG_GROUPS
- 每个 BUFF 独立间隔(用户口径);`interval None` 不自动补(保留手动按键)
- 攻击区内有怪优先解决,补BUFF顺延;补BUFF时停手(松寻怪键+停追+本拍 return)
- 定频模式不补BUFF(无攻击区状态),开关描述注明
- 测试命令: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest <modules>`
- 编译检查: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`

---

### Task 1: farm_logic 纯函数扩展 + 单测

**Covers:** spec [S4]（parse_buff_config 扩展 + due_buffs）

**Files:**
- Modify: `src/task/farm_logic.py:205-214`（parse_buff_config）
- Modify: `tests/test_farm_logic.py:92-97`（断言更新）+ 新增 due_buffs 用例

**Interfaces:**
- Consumes: 无（纯函数）
- Produces: `parse_buff_config(text) -> [(name, key, interval)]`、`due_buffs(now, buffs, last_times) -> [(name, key)]`——Task 2 的 run() 使用

- [ ] **Step 1: 先更新测试（TDD 红）**

`tests/test_farm_logic.py::test_parse_buff_config` 改为三元组断言,新增间隔解析用例:
```python
self.assertEqual(fl.parse_buff_config('magic_shield=q:180,armor=w'),
                 [('magic_shield', 'q', 180), ('armor', 'w', None)])
self.assertEqual(fl.parse_buff_config('bad=x:abc,good=y:60'), [('good', 'y', 60)])  # 坏间隔跳过
```

新增 `test_due_buffs`:
- 到期返回（`due_buffs(200.0, [('a','q',180)], {'a': 0.0})` → `[('a','q')]`）
- 未到期不返回（`last_times={'a': 100.0}` → `[]`）
- interval None 不返回
- 从未补过（last_times 无该名）视为到期
- 多 BUFF 混合到期

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_logic
```
Expected: FAIL（parse_buff_config 还返回二元组,due_buffs 不存在）

- [ ] **Step 2: 实现**

`src/task/farm_logic.py` 按 spec [S4.1][S4.2] 实现。

- [ ] **Step 3: 全绿**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_logic
```
Expected: OK

---

### Task 2: 配置层（补BUFF开关 + 补BUFF列表 + 归组）

**Covers:** spec [S3]（配置）

**Files:**
- Modify: `src/task/MapleFarmTask.py` DEFAULT_CONFIG（`'补BUFF开关': False`、`'补BUFF列表': ''`）
- Modify: `src/task/MapleFarmTask.py` CONFIG_GROUPS「挂机辅助」组加两个新键
- Modify: `src/task/MapleFarmTask.py` 配置描述 dict 补键描述

**Interfaces:**
- Consumes: 无
- Produces: 配置键——Task 3 的 run() 读取

- [ ] **Step 1: 加 DEFAULT_CONFIG 键,跑完整性用例确认红**

在 `'喂宠物间隔(秒)': 900,` 附近插入两个新键,运行 `tests.test_config_groups` 确认 FAIL（未归组）。

- [ ] **Step 2: 归组 + 补描述**

CONFIG_GROUPS「挂机辅助」组加：`'补BUFF开关', '补BUFF列表'`。补描述（如 `'补BUFF列表': '格式 名称=按键:间隔秒,逗号分隔。例: 魔法盾=q:180,狂暴=w:300。间隔缺省不自动补'`）。

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_config_groups
```
Expected: OK

---

### Task 3: run() 补BUFF块 + 实例字段

**Covers:** spec [S5]（任务集成）

**Files:**
- Modify: `src/task/MapleFarmTask.py`

**Interfaces:**
- Consumes: `farm_logic.due_buffs/parse_buff_config`、`self.send_key`、`self._release_seek_key`、`self._last_attack_present`、`self.config` 新键
- Produces: 到点且攻击区无怪时补BUFF,补BUFF时停手

- [ ] **Step 1: 实例字段初始化**

`_reset_state()` 加 `self._last_buff_times = {}`。

- [ ] **Step 2: run() 补BUFF块**

在 §4 攻击块之前（`# 4. 攻击` 注释前）插入 spec [S5.2] 代码块。注意：
- `cfg['补BUFF开关']` 与 `self._last_attack_present is False` 双条件
- 触发时 `_release_seek_key()` + `_seek_dir = None` + 依次 `send_key` + 更新 `_last_buff_times` + `return`
- 开关描述注明定频模式不补

- [ ] **Step 3: 离线测试（TDD 补充）**

`tests/test_farm_task_offline.py` 新增补BUFF用例（构造攻击区无怪/有怪场景,记录 send_key 序列）：
- 开关关 → 不补
- 到点且攻击区无怪 → 按 BUFF 键 + 更新计时
- 攻击区有怪 → 不补,正常攻击
- 多 BUFF 只补到期的
- 触发时停手（_seek_dir 置 None、不寻怪不攻击）
- return 语义（本拍后续逻辑跳过）

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_task_offline
```
Expected: OK

---

### Task 4: 全量验证 + 文档

**Covers:** spec [S7]（测试与验收）

**Files:** 无代码（验证）+ `AGENTS.md` 更新

- [ ] **Step 1: 全量单测 + 编译检查**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_logic tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine tests.test_analyze_anchor tests.test_analyze_facing tests.test_analyze_seek tests.test_analyze_turn tests.test_facing tests.test_label_boxes tests.test_yolo tests.test_config_groups tests.test_config_card_ui
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`
Expected: 全绿 + OK

- [ ] **Step 2: GUI 启动 E2E**

启动 `main_debug.py`（ShellExecute runas,AGENTS.md §1.3）无崩溃;「自动打怪」卡片「挂机辅助」组出现新键（offscreen grab + 视觉验收）。

- [ ] **Step 3: 文档更新**

- `AGENTS.md` 补「定时补BUFF」配置键说明
- spec 验收章节写 E2E 结论;实机验收记录（站桩 3 分钟补 BUFF、战斗中优先攻击）

---

### Task 5: 最终报告

- 写 `docs/compose/reports/buff-timer.md`（frontmatter + specs/plans/branch/commits + 验收结论,格式同 `docs/compose/reports/double-attack.md`）
- 更新 plan 文件 NOTE 标记
