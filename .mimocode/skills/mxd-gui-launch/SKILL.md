---
name: mxd-gui-launch
description: 管理员权限启动/停止/存活验证 mxd-script 的 GUI（main_debug.py），以及后台化 WGC 抓帧（标定/诊断用）。当用户要求「启动 GUI」「开调试窗口」「停 GUI」「抓帧」「截图标定帧」或需要 E2E 截图取证时使用。覆盖 ShellExecute runas 提权、MainWindowTitle/WorkingSet 存活判定、cmd /c start /B 后台抓帧三套已验证模式。
---

# mxd GUI 启动/停止/抓帧

mxd-script 的 GUI = `main_debug.py`（PySide6 + qfluentwidgets，主窗口标题含 `OK-MXD`）。
本技能封装三套**经过实机验证**的操作模式，避免每次重新踩坑。

## 0. 前置：Python 路径（机器相关）

- **本项目工作目录 `C:\projects\mxd-script`**：项目 venv = `.venv-warrior\Scripts\python.exe`（相对项目根）。
- 文档中「当前机器 jianfei」的路径（`G:\projects\MyDocs\projects\mxd_script` + 系统 Python 3.12）仅为旧记录参考；**以实际工作目录为准**，先 `Test-Path .venv-warrior\Scripts\python.exe` 探测。
- **禁止 hard code 本地路径**（项目铁律 §11.1）：命令用项目根相对路径或运行目录推导，不要写死盘符。
- 换机器首次跑：先 `python -m pip install -r requirements.txt`（依赖缺失会 GUI 秒退：`ModuleNotFoundError: No module named 'onnxocr'`）。

## 1. 启动 GUI（必须管理员权限）

⛔ **铁律：GUI 必须管理员运行**——pydirect `is_admin()` 是硬门槛，非管理员按键发送被禁用（检测只读可用）。

### 正确做法：ShellExecute `runas`（推荐，2026-08-10 实机验证）

> 不要用 `Start-Process -Verb RunAs`：在 `mimo.exe serve` 派生 shell 中会**静默失败**（UAC 策略自动批准 + 受限窗口站，进程根本没起来、无报错）。
> `-Verb RunAs` 与 `-RedirectStandardOutput/Error` 参数集互斥，提权进程也没有日志重定向。

```powershell
$py = <Python 绝对路径>   # 见 §0
$proj = <项目根绝对路径>
Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public class SHExec{[DllImport("shell32.dll", CharSet=CharSet.Unicode)]public static extern int ShellExecute(IntPtr hwnd, string op, string file, string args, string dir, int show);}'
$r = [SHExec]::ShellExecute([IntPtr]::Zero, "runas", $py, "main_debug.py", $proj, 1)
# $r <= 32 才是错误；42 或更大 = 成功（ShellExecute 返回句柄值域）
```

### 存活判定（提权进程无日志重定向，只能看窗口）

```powershell
Get-Process | Where-Object { $_.MainWindowTitle -like '*OK-MXD*' -and $_.WorkingSet -gt 100MB -and $_.Responding } | Select-Object Id, ProcessName, MainWindowTitle, @{n='WS_MB';e={[int]($_.WorkingSet/1MB)}}
```

- **看 MainWindowTitle 含 `OK-MXD`** + **WorkingSet > 100MB**（GUI 真身，stub 进程只有数 MB）+ **Responding=True**。
- GUI 可能产生**双进程**（stub + 真实 GUI），WorkingSet 是区分标准。
- 管理员启动的 GUI 用普通权限 `Stop-Process` 可能失败——需提权杀或用任务管理器。

## 2. 停止 GUI

- 采集/抓帧/标定前**必须先停 GUI**（GUI 持有游戏窗口的 WGC 抓帧会话，前台直跑抓帧会无限挂起）。
- 普通 GUI：`Get-Process | Where-Object { $_.MainWindowTitle -like '*OK-MXD*' } | Stop-Process -Force`
- 管理员 GUI 杀不掉时：用 ShellExecute runas 提权 PowerShell 再 `Stop-Process`，或请用户任务管理器结束。

## 3. 后台化 WGC 抓帧（标定/诊断用）

⛔ **WGC 抓帧禁止前台直跑**（`build_capture()` 可能无限挂起等游戏窗口前台）；`pythonw.exe` 会静默崩溃。

正确模式（三步）：

1. 抓帧逻辑写成独立 `.py` 脚本（不用 `-c` 内联，避免转义；已有 `scripts/_capture_calib.py`、`scripts/capture_frame.py` 可复用）。
2. `cmd /c start /B` 后台启动：
   ```powershell
   cmd /c start /B .venv-warrior\Scripts\python.exe scripts\_capture_calib.py
   ```
3. 独立短命令（5-15s）轮询输出文件（如 `screenshots/calib_frame.png`）直到出现。

## 4. E2E 截图取证

- 工具：`scripts/_e2e_capture.py <pid> <out_path>`（按 PID 截窗口；GUI 存活判定见 §1）。
- 截图存 `screenshots/e2e/<特性名>/`，文件名带日期。
- 验收：用 vision-capable 模型（`actor models --vision` 查看可用项，如 `xiaomi/mimo-v2.5`）检查截图内容是否符合预期（界面元素、框颜色/位置）。
