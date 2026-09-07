$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat = Join-Path $dir "后台启动.bat"
schtasks /Create /TN "TeamDailyPlanner" /TR "cmd /c `"$bat`"" /SC ONLOGON /RL LIMITED /F
Write-Host "OK: auto-start on login registered"
