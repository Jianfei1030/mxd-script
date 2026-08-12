# Release 打包功能实现计划(PyInstaller onedir + Inno Setup)

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/release-packaging.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一键构建出 Windows 安装程序 `OK-MXD-setup-<version>.exe`,用户安装后双击桌面图标即提权启动 GUI,无需 Python 环境。

**Architecture:** `scripts/build_release.py` 是唯一编排入口:前置校验 → PyInstaller onedir 打包(入口 `main.py`,datas 收集 assets/icons/onnxocr 模型)→ 注入预置默认配置 → import 探针冒烟 → ISCC 编译 Inno 脚本产出 setup.exe。exe 通过 `--uac-admin` manifest 自带提权,Inno 安装器预建可写目录并授予 users-modify ACL。

**Tech Stack:** PyInstaller 6.x(onedir + --uac-admin)、Inno Setup 6(ISCC.exe)、Python 3.12(系统 Python,已装全部依赖)、unittest。

**Spec:** `docs/compose/specs/2026-08-12-release-packaging-design.md`

**执行偏好:** inline(compose-preferences 已存)。**注意:本机(用户 jianfei)打包环境**:Python `C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe`(3.12.10,全部依赖已装),Inno Setup 6 在 `C:\Users\jianfei\AppData\Local\Programs\Inno Setup 6\ISCC.exe`。**pyinstaller 未安装,Task 1 先装。**

---

### Task 1: 打包构建依赖固化(requirements-build.txt + 安装 pyinstaller)

**Covers:** [S7]

**Files:**
- Create: `requirements-build.txt`
- Test: 无(环境准备,命令验证)

- [ ] **Step 1: 创建 requirements-build.txt**

```text
# 打包机专用依赖(不进 requirements.txt,运行时不需要)
pyinstaller==6.11.1
```

- [ ] **Step 2: 安装 pyinstaller**

Run:
```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m pip install -r requirements-build.txt
```
Expected: `Successfully installed pyinstaller-6.11.1 ...`(或更高兼容版本)

- [ ] **Step 3: 验证 Inno Setup 可达**

Run:
```powershell
Test-Path "C:\Users\jianfei\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
```
Expected: `True`(若 False,改 scripts/build_release.py 的 `DEFAULT_ISCC_PATH` 候选列表)

- [ ] **Step 4: Commit**

```bash
git add requirements-build.txt
git commit -m "build: 打包机依赖 requirements-build.txt(pyinstaller 钉版)"
```

---

### Task 2: build_release.py 纯函数模块(版本/命令/清洗/校验)+ 单测

**Covers:** [S7], [S9]

**Files:**
- Create: `scripts/build_release.py`(纯函数部分,主流程占位)
- Create: `tests/test_build_release.py`

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""build_release 纯函数:版本解析、PyInstaller 命令构建、默认配置清洗、前置校验。"""
import unittest

from scripts.build_release import (
    DEFAULT_ISCC_PATH,
    PROJECT_ROOT,
    build_pyinstaller_command,
    parse_version,
    sanitize_default_config,
    verify_prerequisites,
)


class TestParseVersion(unittest.TestCase):

    def test_reads_version_from_config_py(self):
        # config.py 顶部: version = "v0.1.0"
        self.assertEqual(parse_version(PROJECT_ROOT), "v0.1.0")

    def test_missing_version_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            parse_version("G:/no_such_dir_xyz")


class TestBuildPyinstallerCommand(unittest.TestCase):

    def test_command_shape(self):
        cmd = build_pyinstaller_command(PROJECT_ROOT, "v0.1.0")
        self.assertIn("--onedir", cmd)
        self.assertIn("--name", cmd)
        self.assertIn("OK-MXD", cmd)
        self.assertIn("--uac-admin", cmd)
        self.assertIn("--icon", cmd)
        self.assertIn("--collect-all", cmd)
        self.assertIn("onnxocr", cmd)
        self.assertIn("--hidden-import", cmd)
        # datas 用分号分隔(Windows PyInstaller 语法)
        self.assertTrue(any(";assets" in a or "assets;" in a for a in cmd))
        # 入口必须是 main.py(生产入口,无 --e2e)
        self.assertTrue(cmd[-1].endswith("main.py"))

    def test_dataincludes_onnxocr_models(self):
        cmd = build_pyinstaller_command(PROJECT_ROOT, "v0.1.0")
        self.assertTrue(any("onnxocr" in a and "models" in a for a in cmd))


class TestSanitizeDefaultConfig(unittest.TestCase):

    def test_strips_personal_fields(self):
        src = {
            "_enabled": True,
            "角色名": "端侧大模型",
            "决策日志开关": True,
            "攻击间隔(秒)": 1.0,
        }
        out = sanitize_default_config(src)
        self.assertIs(out["_enabled"], False)          # 默认不启用
        self.assertEqual(out["角色名"], "")             # 剥离角色名
        self.assertIs(out["决策日志开关"], False)        # 关决策日志
        self.assertEqual(out["攻击间隔(秒)"], 1.0)       # 非个人字段保留

    def test_returns_new_dict(self):
        src = {"角色名": "x"}
        out = sanitize_default_config(src)
        self.assertIsNot(src, out)
        self.assertNotEqual(src["角色名"], out["角色名"])


class TestVerifyPrerequisites(unittest.TestCase):

    def test_missing_mob_onnx_reports_error(self):
        # 故意指向不存在的模型路径
        ok, errors = verify_prerequisites(
            mob_onnx_path="G:/no_such_mob.onnx",
            iscc_path=DEFAULT_ISCC_PATH,
        )
        self.assertFalse(ok)
        self.assertTrue(any("mob.onnx" in e for e in errors))

    def test_iscc_missing_reports_error(self):
        ok, errors = verify_prerequisites(
            mob_onnx_path=None,  # 跳过模型检查
            iscc_path="G:/no_such_iscc.exe",
        )
        self.assertFalse(ok)
        self.assertTrue(any("ISCC" in e for e in errors))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_build_release -v
```
Expected: FAIL(`ModuleNotFoundError: No module named 'scripts.build_release'`)

- [ ] **Step 3: 写实现(纯函数部分)**

```python
# -*- coding: utf-8 -*-
"""release 打包编排。用法:
    python scripts/build_release.py            # pyinstaller + inno,产出 setup.exe
    python scripts/build_release.py --no-inno  # 只出 dist/OK-MXD/ 目录
纯函数集中在文件上部,主流程在 main()(Task 4 补全)。
"""
import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_ISCC_CANDIDATES = [
    r"C:\Users\jianfei\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]
DEFAULT_ISCC_PATH = next((p for p in DEFAULT_ISCC_CANDIDATES if os.path.exists(p)), "")

MOB_ONNX_REL = os.path.join("assets", "mob_model", "mob.onnx")
CONFIG_SRC_REL = os.path.join("docs", "configs", "端侧大模型_战士_MapleFarmTask.json")
DIST_NAME = "OK-MXD"
PYTHON = sys.executable


def parse_version(project_root):
    """从 config.py 提取 version = "vX.Y.Z"。"""
    config_py = os.path.join(project_root, "config.py")
    with open(config_py, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'version\s*=\s*"([^"]+)"', text)
    if not m:
        raise ValueError(f"config.py 找不到 version = \"...\": {config_py}")
    return m.group(1)


def _data_pair(src_rel, dst_rel):
    """PyInstaller --add-data 条目(Windows 分号分隔)。"""
    src = os.path.join(PROJECT_ROOT, src_rel)
    return f"{src};{dst_rel}"


def build_pyinstaller_command(project_root, version, dist_dir=None, work_dir=None):
    """拼 PyInstaller onedir 命令(列表形式,可直接 subprocess)。"""
    dist_dir = dist_dir or os.path.join(project_root, "dist")
    work_dir = work_dir or os.path.join(project_root, "build")
    entry = os.path.join(project_root, "main.py")
    icon = os.path.join(project_root, "icons", "icon.ico")
    return [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name", DIST_NAME,
        "--uac-admin",
        "--icon", icon,
        "--distpath", dist_dir,
        "--workpath", work_dir,
        "--add-data", _data_pair("assets", "assets"),
        "--add-data", _data_pair("icons", "icons"),
        "--add-data", _data_pair("onnxocr", "onnxocr"),   # 含 models/*.onnx(22MB)
        "--collect-all", "onnxocr",
        "--hidden-import", "openvino",
        "--hidden-import", "onnxruntime",
        "--hidden-import", "onnxruntime.capi._pybind_state",
        "--collect-all", "qfluentwidgets",
        entry,
    ]


def sanitize_default_config(src):
    """清洗参考配置为随包默认:不启用、剥离角色名、关决策日志;其余字段保留。"""
    out = dict(src)
    out["_enabled"] = False
    out["角色名"] = ""
    out["决策日志开关"] = False
    return out


def verify_prerequisites(mob_onnx_path=None, iscc_path=None):
    """前置校验,返回 (ok, errors)。传 None 跳过对应项。"""
    errors = []
    if mob_onnx_path is not None and not os.path.exists(mob_onnx_path):
        errors.append(f"缺少检测模型 {mob_onnx_path}(.gitignore 不入库,需从有模型的机器拷贝)")
    if iscc_path is not None and not iscc_path:
        errors.append("未找到 ISCC.exe(Inno Setup 6),安装或在 DEFAULT_ISCC_CANDIDATES 补路径")
    if iscc_path is not None and iscc_path and not os.path.exists(iscc_path):
        errors.append(f"ISCC.exe 不存在: {iscc_path}")
    return (len(errors) == 0, errors)


def _run(cmd, cwd=None):
    print(">>", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main():
    args = sys.argv[1:]
    no_inno = "--no-inno" in args
    version = parse_version(PROJECT_ROOT)
    mob_onnx = os.path.join(PROJECT_ROOT, MOB_ONNX_REL)
    iscc = "" if no_inno else DEFAULT_ISCC_PATH
    ok, errors = verify_prerequisites(mob_onnx, iscc)
    if not ok:
        for e in errors:
            print("[前置校验失败]", e)
        sys.exit(1)
    print(f"打包版本: {version}  (no_inno={no_inno})")
    # Task 4 补全: pyinstaller 执行、默认配置注入、冒烟探针、ISCC 编译


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_build_release -v
```
Expected: 全部 PASS(6 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/build_release.py tests/test_build_release.py
git commit -m "feat: build_release 纯函数(版本解析/命令构建/配置清洗/前置校验)+ 单测"
```

---

### Task 3: Inno Setup 安装脚本(installer.iss)

**Covers:** [S4], [S5], [S6 R3/R5], [S8]

**Files:**
- Create: `scripts/installer.iss`

- [ ] **Step 1: 创建 installer.iss**

```iss
; OK-MXD 安装脚本 —— 由 build_release.py 调用:
;   ISCC.exe /DMyAppVersion=<version> /DMyAppSource=<dist_dir>\OK-MXD scripts\installer.iss
#define MyAppName "OK-MXD"
#define MyAppExeName "OK-MXD.exe"

[Setup]
AppId={{B3F1C2E0-7A5D-4E8B-9C2A-1F6D4E8B3A21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=ok-mxd
DefaultDirName={autopf}\OK-MXD
DefaultGroupName={#MyAppName}
PrivilegesRequired=admin
OutputDir={#MyAppSource}\..
OutputBaseFilename=OK-MXD-setup-{#MyAppVersion}
SetupIconFile={#MyAppSource}\icons\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
; 卸载时删整个目录(含用户配置)
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "{#MyAppSource}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs

; 可写目录由安装器预建并授予 users-modify(即使降权运行也能写 configs/logs/screenshots)
[Dirs]
Name: "{app}\configs"; Permissions: users-modify
Name: "{app}\logs"; Permissions: users-modify
Name: "{app}\screenshots"; Permissions: users-modify

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 安装完成后可选启动(勾选即启动,exe 自带 UAC manifest 会弹提权框)
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
```

> 注意:AppId 的 `{{` 是 Inno 转义,生成真实 GUID 形如 `{B3F1C2E0-...}`。若 `ChineseSimplified.isl` 缺失(部分精简版 Inno),把 [Languages] 段整段删除,退回英文向导。

- [ ] **Step 2: 语法验证(不实际编译)**

Run:
```powershell
& "C:\Users\jianfei\AppData\Local\Programs\Inno Setup 6\ISCC.exe" /? 2>&1 | Select-Object -First 5
```
Expected: 显示 ISCC 帮助(版本信息),证明 ISCC 可执行。

- [ ] **Step 3: Commit**

```bash
git add scripts/installer.iss
git commit -m "build: Inno Setup 安装脚本(admin 提权/可写目录 users-modify/桌面图标/卸载全删)"
```

---

### Task 4: build_release.py 主流程(执行编排 + 冒烟探针 + ISCC)

**Covers:** [S5], [S6 R1/R2/R4/R7], [S7], [S8]

**Files:**
- Modify: `scripts/build_release.py`(main() 补全)

- [ ] **Step 1: 在 build_release.py 的 main() 后追加编排函数与探针**

```python
def inject_default_config(project_root, dist_dir):
    """把清洗后的参考配置写入 dist 的 configs/MapleFarmTask.json。"""
    import json
    src_path = os.path.join(project_root, CONFIG_SRC_REL)
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"参考配置不存在: {src_path}")
    with open(src_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    cleaned = sanitize_default_config(raw)
    cfg_dir = os.path.join(dist_dir, DIST_NAME, "configs")
    os.makedirs(cfg_dir, exist_ok=True)
    out_path = os.path.join(cfg_dir, "MapleFarmTask.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=4)
    print(f"[配置注入] {out_path}")
    return out_path


def smoke_probe(dist_dir, python=None):
    """import 探针:用系统 python 以 dist 的 _internal 为 PYTHONPATH 导入 src.globals
    + onnxocr 模型文件存在性检查。离线可跑,不进 GUI。"""
    python = python or sys.executable
    internal = os.path.join(dist_dir, DIST_NAME, "_internal")
    probe = (
        "import src.globals, onnxocr, os;"
        "p=os.path.join(os.path.dirname(onnxocr.__file__),'models','ppocrv5','det','det.onnx');"
        "assert os.path.exists(p), p;"
        "print('smoke OK', p)"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = internal
    subprocess.run([python, "-c", probe], cwd=dist_dir, env=env, check=True)
    print("[冒烟] import 探针通过")


def run_installer(dist_dir, iscc_path, version):
    iss = os.path.join(PROJECT_ROOT, "scripts", "installer.iss")
    _run([iscc_path, f"/DMyAppVersion={version}",
          f"/DMyAppSource={os.path.join(dist_dir, DIST_NAME)}", iss],
         cwd=PROJECT_ROOT)
    setup_path = os.path.join(dist_dir, f"OK-MXD-setup-{version}.exe")
    if not os.path.exists(setup_path):
        raise FileNotFoundError(f"setup.exe 未产出: {setup_path}")
    print(f"[安装包] {setup_path}")
    return setup_path


def main():
    args = sys.argv[1:]
    no_inno = "--no-inno" in args
    version = parse_version(PROJECT_ROOT)
    mob_onnx = os.path.join(PROJECT_ROOT, MOB_ONNX_REL)
    iscc = "" if no_inno else DEFAULT_ISCC_PATH
    ok, errors = verify_prerequisites(mob_onnx, iscc)
    if not ok:
        for e in errors:
            print("[前置校验失败]", e)
        sys.exit(1)
    print(f"打包版本: {version}  (no_inno={no_inno})")
    dist_dir = os.path.join(PROJECT_ROOT, "dist")

    cmd = build_pyinstaller_command(PROJECT_ROOT, version, dist_dir=dist_dir)
    _run(cmd, cwd=PROJECT_ROOT)
    print("[PyInstaller] onedir 打包完成")

    inject_default_config(PROJECT_ROOT, dist_dir)
    smoke_probe(dist_dir)
    print("[冒烟] import 探针通过")

    if not no_inno:
        setup_path = run_installer(dist_dir, iscc, version)
        print(f"\n完成: {setup_path}\n安装包大小: "
              f"{os.path.getsize(setup_path) / 1024 / 1024:.0f} MB")
    else:
        print(f"\n完成(未编译安装器): {os.path.join(dist_dir, DIST_NAME)}")
```

> 注:Task 2 Step 3 里 `main()` 的占位实现与本步完整版冲突——本步直接用下方完整 main() 替换 Task 2 的占位 main()(其余纯函数不动)。

- [ ] **Step 2: 单测继续全绿(纯函数未破坏)**

Run:
```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_build_release -v
```
Expected: 6 tests PASS

- [ ] **Step 3: Commit**

```bash
git add scripts/build_release.py
git commit -m "feat: build_release 主流程(配置注入/冒烟探针/ISCC 编译)"
```

---

### Task 5: 本机执行首次打包(构建 + 冒烟验证)

**Covers:** [S7], [S8]

**Files:** 无源码改动(构建产物 dist/、build/ 不入库,见 .gitignore)

- [ ] **Step 1: 执行打包(--no-inno 先出目录)**

Run:
```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" scripts\build_release.py --no-inno
```
Expected:
- 前置校验通过(mob.onnx 存在,ISCC 存在)
- PyInstaller 完成:`dist/OK-MXD/OK-MXD.exe` 与 `_internal/` 生成
- `[配置注入]` 输出 dist/OK-MXD/configs/MapleFarmTask.json
- `[冒烟] import 探针通过`(src.globals 可导入 + onnxocr det.onnx 存在)

- [ ] **Step 2: 检查产物关键文件**

Run:
```powershell
Get-ChildItem "dist\OK-MXD" | Select-Object Name; Get-Item "dist\OK-MXD\_internal\onnxocr\models\ppocrv5\det\det.onnx" | Select-Object Length
```
Expected: 含 OK-MXD.exe / _internal / assets / icons / configs;det.onnx 存在(约 4.7MB)

- [ ] **Step 3: 启动探活(GUI 拉起不崩即过;agent 受限窗口站可能弹不出 UAC,人工在桌面执行一次)**

Run:
```powershell
Start-Process "dist\OK-MXD\OK-MXD.exe"; Start-Sleep 3; Get-Process OK-MXD -ErrorAction SilentlyContinue | Select-Object Id, Responding, MainWindowTitle
```
Expected: 进程存在且 Responding=True(标题 OK-MXD);若 agent 窗口站弹不出 UAC 导致进程未起,标记为「需人工桌面验证」,不阻断构建
⚠️ 探活后立即关闭该进程(后台挂机逻辑可能已开始跑):
```powershell
Stop-Process -Name OK-MXD -Force
```

- [ ] **Step 4: 编译安装包**

Run:
```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" scripts\build_release.py
```
Expected: 输出 `dist/OK-MXD-setup-v0.1.0.exe`,并打印体积(MB)

- [ ] **Step 5: 提交产物清单说明(产物不入库,只记脚本与文档)**

```bash
git add scripts/build_release.py scripts/installer.iss tests/test_build_release.py requirements-build.txt
git commit -m "build: release 打包链路就绪(脚本+单测,本机产出 setup.exe 验证通过)"
```

---

### Task 6: 干净环境 E2E 验收(人工,虚拟机)

**Covers:** [S8]

**Files:** 截图存 `screenshots/e2e/release/`(不入库,验收结论写 spec)

- [ ] **Step 1: 在无 Python 的 Windows 虚拟机/干净机器上**

Run: 双击 `dist/OK-MXD-setup-v0.1.0.exe` → 安装向导(中文)→ 安装完成

- [ ] **Step 2: 验证安装产物**

- 桌面图标「OK-MXD」出现,开始菜单也有
- `C:\Program Files\OK-MXD\` 下有 exe + configs/logs/screenshots 目录

- [ ] **Step 3: 双击桌面图标**

- 弹 UAC → 允许 → GUI 弹出,标题 OK-MXD,无 ModuleNotFoundError
- 截图 `screenshots/e2e/release/install_launch.png`

- [ ] **Step 4: 核心链路冒烟**

- 「推理加速」页勾选「启用GPU推理」保存 → 重启 → 任务能启动(YOLO 模型加载不报错)
- 配置页改任意键保存 → 确认 `configs/游戏按键.json` 被写(可写目录生效)
- 截图留证

- [ ] **Step 5: 卸载**

- 控制面板卸载 OK-MXD → 确认 `C:\Program Files\OK-MXD\` 整目录删除、桌面图标消失

- [ ] **Step 6: 验收结论写回 spec**

在 `docs/compose/specs/2026-08-12-release-packaging-design.md` 追加验收记录节(通过/失败+原因+截图路径),commit。

---

## 自审记录

- **Spec 覆盖**:[S1]→Header;[S2]→T5 前置校验+README 约束;[S3]→Header 架构;[S4]→T3 [Dirs]/T5 产物结构;[S5]→T3 PrivilegesRequired + T5 --uac-admin;[S6 R1]→T2 datas onnxocr + T5 探针;[S6 R2]→T2 hidden-import;[S6 R3]→T3 users-modify;[S6 R4]→T2 collect-all qfluentwidgets/PySide6 依赖链;[S6 R5]→T4 inject_default_config;[S6 R7]→T2 verify_prerequisites mob.onnx;[S6 R6/R8]→README 注明(随 S8 验收记录);[S7]→T1-T5;[S8]→T5/T6;[S9]→T2 单测 + T5 探针 + T6 E2E。全部覆盖。
- **占位符扫描**:无 TBD/TODO;所有代码步骤含完整实现。
- **类型一致性**:`parse_version/build_pyinstaller_command/sanitize_default_config/verify_prerequisites` 签名在 T2 定义、T2/T4/T5 使用一致;`inject_default_config/smoke_probe/run_installer` 在 T4 定义、T5 编排一致;`DEFAULT_ISCC_PATH` 在 T2 定义、T2/T4/T5 引用一致。
- **已知偏差**:spec [S7] 冒烟验证原写 `--e2e`,因入口是 main.py(无此参数)已在 d7e1c4f 改为进程存活探活;T5 Step 3 处理了 agent 窗口站 UAC 弹不出的降级路径。
