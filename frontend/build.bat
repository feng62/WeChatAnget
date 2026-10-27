@echo off
cd /d "%~dp0"
echo 正在构建 Vue 3 + Tailwind CSS 前端到 static 目录...
call pnpm run build
if errorlevel 1 (
    echo 构建异常，尝试使用 npm 构建...
    call npm run build
)
echo.
echo 前端构建完成！已自动更新到 static/ 目录。
pause