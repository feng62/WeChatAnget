@echo off
cd /d "%~dp0"

echo.
echo ========================================================
echo   微信 4.x 桌面版 Web 控制台 (AI 消息与记忆系统)
echo ========================================================
echo.

set "PY=D:\Tool\python\python.exe"
if not exist "%PY%" set "PY=D:\Program\python\python3.14\python.exe"
if not exist "%PY%" set "PY=%~dp0..\whale_gril\runtime\python\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

set PYTHONUNBUFFERED=1
echo 启动解释器: %PY%
echo 正在启动 Web 服务端 (http://127.0.0.1:8000)...
echo.

start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"

"%PY%" src\web_server.py

if errorlevel 1 (
  echo.
  echo [提示] 启动遇到异常？请检查微信桌面端是否已登录并正常运行。
  echo.
  pause
)