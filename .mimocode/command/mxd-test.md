---
description: 运行 mxd-script 的全量离线单测与全源码编译检查（项目测试纪律 AGENTS.md §11）。任何代码改动后、合入前使用。可选参数 $1 = 只跑指定测试模块（如 test_farm_logic），留空 = 默认全量子集。
---

# 运行项目单测 + 编译检查

项目铁律（AGENTS.md §11）：**没有测试证据的特性不算完成**；任何改动必须跑全量单测 + 编译检查全绿。

## 1. 单测（默认全量子集）

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_logic tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine tests.test_analyze_anchor tests.test_analyze_facing tests.test_analyze_seek tests.test_analyze_turn tests.test_facing tests.test_label_boxes tests.test_yolo
```

只跑指定模块（`$1` 传模块名）：
```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.$1
```

## 2. 编译检查（全源码）

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"
```

- 用 `py_compile.compile(doraise=True)`，不要用 `py_compile src\*.py`（不支持通配符）。
- **不要直接 import 测试/脚本文件**（会执行主逻辑挂起），只用 unittest / py_compile。

## 3. 已知基线（2026-08-10）

- 单测：**523 用例 / 8 显式 skip / 1 红**。红的是 `test_anchor_offline.TestAnchorOnRealFrames.test_b_anchor_y_in_expected_band`（长期存在的既有失败，与本次改动无关，对照 `master` 同样红）。
- 环境依赖缺失的用例会显式 skip（不 assert 报错假失败）。
- 若出现新红：用 `git stash push` 压改动 → 跑全量 → `stash pop` 对比，判断是否自己引入。

## 4. 日志检查（改代码后必做）

改完代码不能只看编译+单测绿，还要 grep 运行时日志确认无新报错：
```powershell
Select-String -Path logs\ok-script.log -Pattern "Exception|Traceback|error" | Select-Object -Last 20
```
