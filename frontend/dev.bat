@echo off
cd /d "%~dp0"
echo 正在启动 Vue 3 + Vite 本地开发热更服务器 (http://localhost:5173)...
call pnpm run dev
if errorlevel 1 (
    call npm run dev
)
pause