@echo off
cd /d "%~dp0"

echo.
echo ========================================================
echo   微信 4.x 多账号并发消息读取与媒体处理演示
echo ========================================================
echo.

set "PY=D:\Tool\python\python.exe"
if not exist "%PY%" set "PY=D:\Program\python\python3.14\python.exe"
if not exist "%PY%" set "PY=%~dp0..\whale_gril\runtime\python\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

set PYTHONUNBUFFERED=1
echo 启动解释器: %PY%
"%PY%" -u src\demo_read_messages.py %*

if errorlevel 1 (
  echo.
  echo [提示] 运行遇到异常？你也可以运行模拟演示查看解析效果：
  echo   "%PY%" src\demo_read_messages.py --mock
  echo.
  pause
)
