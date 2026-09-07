@echo off
chcp 65001 >nul
title 团队日计划 - 公网访问
cd /d "%~dp0"

echo.
echo ========================================
echo   团队日计划 · 启动公网访问
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 安装依赖
echo [1/3] 检查依赖...
pip install -r requirements.txt -q

:: 启动 Flask（新窗口）
echo [2/3] 启动 Web 服务...
start "团队日计划-Web" cmd /k "cd /d %~dp0 && python app.py"

:: 等待服务启动
timeout /t 3 /nobreak >nul

:: 启动 Cloudflare 隧道
echo [3/3] 创建公网链接（约 10 秒）...
echo.
echo 请等待下方出现 https://xxxx.trycloudflare.com 链接
echo 将该链接发到微信群，组员即可手机访问
echo.
echo 注意：关闭本窗口后链接失效；永久域名请运行 deploy.ps1
echo.
cloudflared tunnel --url http://127.0.0.1:5000

pause
