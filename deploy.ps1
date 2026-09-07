# 团队日计划 — 一键部署到免费云（Render + Neon）
# 用法：右键「使用 PowerShell 运行」，或在 PowerShell 中执行 .\deploy.ps1

$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot
Set-Location $ProjectDir

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  团队日计划 · 免费云部署助手" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# --- 检查 Git ---
$gitPath = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitPath) {
    Write-Host "[1/5] 正在安装 Git..." -ForegroundColor Yellow
    winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements --silent
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}
Write-Host "[OK] Git 已就绪" -ForegroundColor Green

# --- 初始化 Git 仓库 ---
if (-not (Test-Path ".git")) {
    git init
    git branch -M main
    git add .
    git commit -m "团队日计划初始版本"
    Write-Host "[OK] Git 仓库已初始化" -ForegroundColor Green
} else {
    Write-Host "[OK] Git 仓库已存在" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  第 1 步：创建免费数据库（Neon）" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. 浏览器将打开 neon.tech 注册页（可用 GitHub 登录，完全免费）"
Write-Host "2. 创建项目 → 复制 Connection String（选 Pooled 或 Direct 均可）"
Write-Host "3. 格式类似：postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require"
Write-Host ""
Start-Process "https://console.neon.tech/signup"
$databaseUrl = Read-Host "请粘贴 Neon 的 DATABASE_URL"

if (-not $databaseUrl -or $databaseUrl -notmatch "postgres") {
    Write-Host "DATABASE_URL 格式不对，请重新运行脚本" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  第 2 步：部署到 Render（免费域名）" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. 浏览器将打开 Render 注册页"
Write-Host "2. 登录后 → New + → Blueprint"
Write-Host "3. 连接 GitHub 仓库（需先把代码 push 到 GitHub，见下方说明）"
Write-Host "4. 在环境变量中设置 DATABASE_URL = 刚才复制的连接串"
Write-Host "5. 部署完成后获得免费域名：https://team-daily-planner-xxxx.onrender.com"
Write-Host ""
Start-Process "https://dashboard.render.com/register"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  第 3 步：推送代码到 GitHub" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "如果还没有 GitHub 仓库，请："
Write-Host "  1. 打开 https://github.com/new 创建空仓库（如 team-daily-planner）"
Write-Host "  2. 不要勾选 README"
Write-Host "  3. 复制仓库地址，粘贴到下方"
Write-Host ""
$repoUrl = Read-Host "GitHub 仓库地址（如 https://github.com/你的用户名/team-daily-planner.git）"

if ($repoUrl) {
    git remote remove origin 2>$null
    git remote add origin $repoUrl
    git push -u origin main
    Write-Host "[OK] 代码已推送到 GitHub" -ForegroundColor Green
    Start-Process "https://dashboard.render.com/blueprints"
}

# 保存本地 env 供参考
@"
DATABASE_URL=$databaseUrl
SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
"@ | Out-File -Encoding utf8 ".env.example"

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  部署配置已准备完毕！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Render 环境变量（在 Dashboard → Environment 中添加）："
Write-Host "  DATABASE_URL = $databaseUrl"
Write-Host "  SECRET_KEY   = （Render 会自动生成，或随机字符串）"
Write-Host ""
Write-Host "免费域名格式：https://你的服务名.onrender.com"
Write-Host "微信可直接打开，建议收藏发给 7 位组员。"
Write-Host ""
Write-Host "管理者 PIN 默认 8888，可在 config.json 修改后重新 push。"
Write-Host ""
