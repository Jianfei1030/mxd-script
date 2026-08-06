@echo off
setlocal
title OK-MXD 启动器
chcp 65001 >nul

REM ============================================================
REM  一键启动 GUI。双击即可 —— 会自己弹 UAC 提权。
REM  提权是必须的:PyDirect 发按键要管理员权限,否则 error 5 发不出去。
REM ============================================================

REM ---- 1. 自提权 ----
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要管理员权限,正在请求提权...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PY=H:\ok-mxd\data\apps\ok-ww\python\python.exe"
set "FRAME=screenshots\test_frames\training_ground_full_2560x1440.png"
set "BACKUP=H:\ok-mxd\_frames_backup\training_ground_full_2560x1440.png"

if not exist "%PY%" (
    echo [错误] 找不到嵌入式 Python: %PY%
    pause
    exit /b 1
)

REM ---- 2. 前台挂机需要游戏先开着,没开只提醒不拦 ----
tasklist /fi "imagename eq Maplestory_Classic.exe" 2>nul | find /i "Maplestory_Classic.exe" >nul
if errorlevel 1 (
    echo [提醒] 没检测到游戏进程 Maplestory_Classic.exe。
    echo        这是前台挂机,启动前请先开好游戏并调到 2560x1440。
    echo.
)

REM ---- 3. 启动 ----
echo 正在启动 OK-MXD GUI...
echo 启动后请在任务配置里确认:攻击模式=检测、角色名已填写。
echo.
"%PY%" main_debug.py
set "EXITCODE=%errorlevel%"

REM ---- 4. 退出后补回存档测试帧 ----
REM     GUI 启动会清空 screenshots/,而该帧已不在版本控制里(screenshots/ 整个被 gitignore),
REM     丢了 test_bars / test_potions / test_farm_task_offline 三个测试模块会直接报错。
if not exist "%FRAME%" (
    if exist "%BACKUP%" (
        if not exist "screenshots\test_frames" mkdir "screenshots\test_frames"
        copy /y "%BACKUP%" "%FRAME%" >nul
        echo 已从备份恢复存档测试帧。
    ) else (
        echo [警告] 存档测试帧已丢失,且备份也不存在: %BACKUP%
        echo        tests/test_bars.py 等三个模块会因此报错。
    )
)

echo.
echo GUI 已退出（exit code %EXITCODE%）。日志: logs\ok-script.log
pause
