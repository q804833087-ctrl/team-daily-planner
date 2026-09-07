@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: 已在运行则跳过
curl -s http://127.0.0.1:5000/health >nul 2>&1
if not errorlevel 1 goto :tunnel

echo [启动] Web 服务...
start /B "" python app.py >nul 2>&1
timeout /t 3 /nobreak >nul

:tunnel
:: 检查是否已有 cloudflared
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>nul | find /I "cloudflared.exe" >nul
if not errorlevel 1 (
    if exist "公网地址.txt" type "公网地址.txt"
    exit /b 0
)

echo [启动] 公网隧道...
for /f "tokens=*" %%a in ('cloudflared tunnel --url http://127.0.0.1:5000 2^>^&1 ^| findstr trycloudflare.com') do (
    echo %%a | findstr /R "https://.*trycloudflare.com" > "%~dp0公网地址.txt"
)
start /B cloudflared tunnel --url http://127.0.0.1:5000 > "%~dp0tunnel.log" 2>&1
timeout /t 12 /nobreak >nul
findstr "trycloudflare.com" "%~dp0tunnel.log" | findstr "https://" > "%~dp0公网地址.txt" 2>nul
if exist "公网地址.txt" type "公网地址.txt"
