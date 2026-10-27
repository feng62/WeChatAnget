@echo off
cd /d "%~dp0"

echo.
echo ========================================================
echo   微信 4.x 桌面副驾驶伴随助手 (丝滑吸附 + AI 智能建议)
echo ========================================================
echo.

set "PY=D:\Tool\python\python.exe"
if not exist "%PY%" set "PY=D:\Program\python\python3.14\python.exe"
if not exist "%PY%" set "PY=%~dp0..\whale_gril\runtime\python\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

set PYTHONUNBUFFERED=1
echo 启动解释器: %PY%
echo 正在连接微信桌面端并启动伴随窗口...
echo.

"%PY%" src\copilot_dock.py

if errorlevel 1 (
  echo.
  echo [提示] 启动遇到异常？请检查微信桌面端是否已登录并正常运行。
  echo.
  pause
)