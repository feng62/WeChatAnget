@echo off
cd /d "%~dp0"

echo.
echo ========================================================
echo   微信 4.x 桌面端贴边伴随窗口 (AI Copilot 智能助手)
echo ========================================================
echo.

set "PY=D:\Tool\python\python.exe"
if not exist "%PY%" set "PY=D:\Program\python\python3.14\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

set PYTHONUNBUFFERED=1
echo 正在启动微信侧边伴侣窗口: %PY% copilot_dock_gui.py
echo.

"%PY%" copilot_dock_gui.py

if errorlevel 1 (
  echo.
  echo [提示] 运行遇到异常？请检查微信桌面端是否运行。
  pause
)