---
feature: release-packaging
status: delivered
specs:
  - docs/compose/specs/2026-08-12-release-packaging-design.md
plans:
  - docs/compose/plans/2026-08-12-release-packaging.md
branch: master
commits: 33ac52a..f61576c
---

# Release 打包功能 — Final Report

## What Was Built

一条命令产出可分发的 Windows 安装程序:用户在无 Python 的机器上安装 `OK-MXD-setup-<version>.exe` 后,双击桌面图标即弹 UAC 提权并启动 GUI,开箱即用。

入口 `scripts/build_release.py`,完整链路:前置校验(mob.onnx / ISCC)→ PyInstaller onedir 打包(`main.py` 入口,`--uac-admin` 提权 manifest)→ 拷贝 assets/icons 到 exe 同级 → 注入清洗后的默认配置 → 冒烟检查产物 → ISCC 编译 Inno 安装器。本机产出约 121-138MB 压缩包、解压后 376MB。

## Architecture

```
dist/OK-MXD/                       ← PyInstaller onedir 产物(构建机本地)
├── OK-MXD.exe                     ← 主程序,requireAdministrator manifest
├── _internal/                     ← 依赖(python312.dll、全部 .pyd/.dll、PYZ 字节码)
│   ├── onnxocr/models/            ← OCR 模型(22MB,add-data 收集)
│   └── ...
├── assets/mob_model/mob.onnx      ← 检测模型(手动拷贝,非 add-data)
├── icons/                         ← 图标(手动拷贝)
├── configs/MapleFarmTask.json     ← 清洗后的默认配置
├── logs/  screenshots/            ← 可写目录(Inno users-modify ACL)
└── OK-MXD-setup-v0.1.0.exe        ← Inno 安装包(lzma2 压缩)
```

**关键接口**(全部在 `scripts/build_release.py`,纯函数可单测):

| 函数 | 职责 |
|---|---|
| `parse_version(project_root)` | 从 config.py 正则提取 `version = "vX.Y.Z"` |
| `_site_package_data_pair(pkg, sub, dst)` | pip 包内数据 add-data 条目(动态解析 site-packages 路径) |
| `_src_hidden_imports(project_root)` | 展开 src 全部子模块为 `--hidden-import` |
| `build_pyinstaller_command(...)` | 拼 PyInstaller 命令 |
| `copy_runtime_dirs(...)` | assets/icons 拷贝到 exe 同级 |
| `sanitize_default_config(src)` | 配置清洗:不启用/剥离角色名/关决策日志 |
| `inject_default_config(...)` | 写 dist configs/MapleFarmTask.json |
| `verify_prerequisites(...)` | mob.onnx/ISCC 存在性校验 |
| `clean_old_build(...)` | 删旧 dist(防日志文件占用) |
| `smoke_probe(...)` | 静态检查 exe/mob.onnx/det.onnx/_internal |
| `run_installer(...)` | ISCC 编译 → setup.exe |

**Inno 要点**(`scripts/installer.iss`):`PrivilegesRequired=admin`、`DefaultDirName={autopf}\OK-MXD`、桌面+开始菜单图标、`[Dirs] Permissions: users-modify` 预建可写目录、`[UninstallDelete]` 卸载全删。中文语言文件 `scripts/ChineseSimplified.isl` 内置(精简版 Inno 不带)。

## Design Decisions

- **PyInstaller onedir + Inno,而非 onefile/嵌入式 Python**:依赖含大量 .pyd/.dll/.onnx 动态收集难,onedir 把收集问题降到目录拷贝;onefile 启动解压慢且可写目录生命周期外;pyappify 自动更新超 v1 范围
- **assets/icons 手动拷贝而非 `--add-data`**:PyInstaller 6.x 把 datas 打进 `_internal/`,而运行时 `get_path_relative_to_exe` 找 exe 同级目录——add-data 收集会导致模型加载失败
- **src 子模块用展开的 `--hidden-import` 而非 `--collect-submodules`**:config.py 用字符串类名 + importlib 动态加载(`'src.globals'` 等),静态分析抓不到;spec 生成时项目根未进 sys.path,`--collect-submodules` 只收集到 3 个模块,展开成显式 hidden-import 才能收全 20 个
- **exe 自带 `--uac-admin` manifest 而非启动器提权**:双击直接弹 UAC,无额外启动器层
- **打包前删旧 dist**:PyInstaller `--clean` 只清 build 缓存,旧 dist 里的 logs/ok-script.log 被运行中实例占用会导致重打包 PermissionError

## Usage

```powershell
# 完整打包(前置:requirements-build.txt 已装 pyinstaller、已装 Inno Setup 6、assets/mob_model/mob.onnx 存在)
& "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" scripts\build_release.py
# 只出目录不自测安装器
& "...\python.exe" scripts\build_release.py --no-inno
```

产物:`dist/OK-MXD-setup-<version>.exe`。`mob.onnx` 在 .gitignore,打包机需从有模型的机器拷贝(脚本会显式校验并报错)。

## Verification

- **单测**:`tests/test_build_release.py` 8 用例(版本解析/命令构建/配置清洗/前置校验),179 个全量单测全绿
- **冒烟**:脚本内 `smoke_probe` 静态检查 4 项产物;`--no-inno` 幂等验证通过(第二次打包成功)
- **启动探活**:ShellExecute runas 提权启动,进程 Responding=True、标题「OK-MXD v0.1.0」、WorkingSet 226MB、日志完整走完 init → displayed → app.exec(),无 ModuleNotFoundError
- **待完成**:T6 干净虚拟机 E2E(安装→启动→配置保存→卸载)为人工步骤,尚未执行

## Journey Log

- [lesson] PyInstaller 6.x onedir 的 datas 默认进 `_internal/`,与框架 `get_path_relative_to_exe`(找 exe 同级)冲突——运行时资源必须手动拷贝到 exe 同级
- [lesson] importlib 字符串动态加载的模块(`'src.globals'`)静态分析抓不到,必须展开为显式 `--hidden-import`
- [lesson] agent 受限窗口站无法弹 UAC,`--uac-admin` exe 探活必须用 ShellExecute `runas`(返回 42),且杀进程也要提权 taskkill
- [lesson] 精简版 Inno Setup 6 不带 ChineseSimplified.isl,语言文件须内置到 scripts/ 并相对引用
- [lesson] 打包机路径易混:onnxocr 是 site-packages 包,`--add-data` 需动态解析安装路径,不能假设在项目目录

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/specs/2026-08-12-release-packaging-design.md` | 设计 | 方案/约束/风险表 |
| `docs/compose/plans/2026-08-12-release-packaging.md` | 实施计划 | 6 任务,Task 6 人工验收未执行 |
| `scripts/build_release.py` | 打包编排 | 唯一入口 |
| `scripts/installer.iss` | Inno 脚本 | 安装器 |
| `scripts/ChineseSimplified.isl` | 语言包 | 官方 21.5KB |
| `tests/test_build_release.py` | 单测 | 8 用例 |
| `requirements-build.txt` | 打包依赖 | pyinstaller 钉版 |
