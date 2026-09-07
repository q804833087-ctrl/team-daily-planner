@echo off
chcp 65001 >nul
title 团队日计划 - 长期运行
cd /d "%~dp0"

echo.
echo ========================================
echo   团队日计划 · 长期运行（数据本地保存）
echo ========================================
echo.

pip install -r requirements.txt -q 2>nul

:: 启动 Web 服务
curl -s http://127.0.0.1:5000/health >nul 2>&1
if errorlevel 1 (
    echo [1/2] 启动 Web 服务...
    start /B "" python app.py > server.log 2>&1
    timeout /t 3 /nobreak >nul
) else (
    echo [1/2] Web 服务已在运行
)

:: 启动公网隧道
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>nul | find /I "cloudflared.exe" >nul
if errorlevel 1 (
    echo [2/2] 创建公网链接...
    start /B cloudflared tunnel --url http://127.0.0.1:5000 > tunnel.log 2>&1
    timeout /t 12 /nobreak >nul
) else (
    echo [2/2] 公网隧道已在运行
)

:: 写入访问地址
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /C:"IPv4"') do (
    set "IP=%%i"
    goto :gotip
)
:gotip
set IP=%IP: =%

(
echo 团队日计划 - 访问地址
echo ====================
echo.
echo 数据文件（永久保存）: %~dp0data\planner.db
echo.
echo 局域网访问（同 WiFi/办公室）:
echo   http://%IP%:5000
echo.
echo 公网访问（微信可打开，电脑需开机）:
) > "公网地址.txt"

findstr /R "https://.*trycloudflare.com" tunnel.log 2>nul >> "公网地址.txt"
if errorlevel 1 echo   （隧道启动中，请稍等 10 秒后重新运行本脚本查看）>> "公网地址.txt"

echo.>> "公网地址.txt"
echo 管理者 PIN: 8888>> "公网地址.txt"

type "公网地址.txt"
echo.
echo 提示：注册开机自启请运行 设置开机自启.ps1
echo.
pause
