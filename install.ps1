# kimi-code-dashboard installer for Windows.
#
# Usage:
#   irm https://raw.githubusercontent.com/perinchiang/kimi-code-dashboard/master/install.ps1 | iex
#
# What it does:
#   1. Checks Python 3.10+ and git
#   2. Clones/updates ~/.kimi-code/dashboard
#   3. Creates venv + installs dependencies
#   4. Generates kimi-dashboard.bat in ~/.kimi-code/bin/
#   5. Checks PATH and prints usage

$ErrorActionPreference = "Stop"

$INSTALL_DIR = "$env:USERPROFILE\.kimi-code"
$DASHBOARD_DIR = "$INSTALL_DIR\dashboard"
$BIN_DIR = "$INSTALL_DIR\bin"
$REPO_URL = "https://github.com/perinchiang/kimi-code-dashboard.git"

function Log($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "==> $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "==> $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "error: $msg" -ForegroundColor Red }

# --- 1. Check Python 3.10+ ---
Log "检测 Python..."
$PYTHON = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                $PYTHON = $cmd
                break
            }
        }
    } catch {}
}
if (-not $PYTHON) {
    Err "未找到 Python 3.10+"
    Err "请从 https://www.python.org/downloads/ 安装 Python 3.10 或更高版本"
    exit 1
}
Ok "找到 Python: $(& $PYTHON --version)"

# --- Check git ---
try {
    $null = git --version 2>$null
    if ($LASTEXITCODE -ne 0) { throw "no git" }
} catch {
    Err "未找到 git,请先安装 git: https://git-scm.com/download/win"
    exit 1
}

# --- 2. Clone or update ---
Log "克隆/更新 Dashboard..."
if (-not (Test-Path $INSTALL_DIR)) {
    New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null
}

if (Test-Path "$DASHBOARD_DIR\.git") {
    Log "已存在,执行 git pull..."
    try {
        git -C $DASHBOARD_DIR pull --ff-only origin master
    } catch {
        Warn "git pull 失败,请手动检查 $DASHBOARD_DIR"
    }
} elseif (Test-Path $DASHBOARD_DIR) {
    Warn "$DASHBOARD_DIR 已存在但不是 git 仓库,跳过 clone"
} else {
    git clone --depth 1 $REPO_URL $DASHBOARD_DIR
}

# --- 3. venv + dependencies ---
Log "创建虚拟环境..."
if (-not (Test-Path "$DASHBOARD_DIR\.venv")) {
    & $PYTHON -m venv "$DASHBOARD_DIR\.venv"
}
Ok "安装依赖..."
& "$DASHBOARD_DIR\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$DASHBOARD_DIR\.venv\Scripts\python.exe" -m pip install --quiet -r "$DASHBOARD_DIR\requirements.txt"

# --- 4. Generate wrapper ---
Log "生成 kimi-dashboard 命令..."
if (-not (Test-Path $BIN_DIR)) {
    New-Item -ItemType Directory -Path $BIN_DIR -Force | Out-Null
}
$WRAPPER = "$BIN_DIR\kimi-dashboard.bat"
$BAT = "@echo off`r`ncd /d `"%USERPROFILE%\.kimi-code\dashboard`"`r`n`".venv\Scripts\python.exe`" launch_menu.py %*"
Set-Content -Path $WRAPPER -Value $BAT -Encoding ASCII
Ok "已生成: $WRAPPER"

# --- 5. Check PATH ---
$PATH_DIRS = $env:PATH -split ";"
if ($PATH_DIRS -contains $BIN_DIR) {
    Ok "PATH 已包含 $BIN_DIR"
} else {
    Warn "PATH 未包含 $BIN_DIR"
    Warn "请将以下行加入 PowerShell Profile (运行 notepad `$PROFILE 编辑):"
    Write-Host "  `$env:PATH += `";$BIN_DIR`"" -ForegroundColor White
    Warn "或通过 系统设置 > 环境变量 添加该目录"
}

# --- 6. Done ---
Write-Host ""
Ok "安装完成!"
Write-Host ""
Write-Host "用法:" -ForegroundColor White
Write-Host "  kimi-dashboard          # 弹出菜单"
Write-Host "  kimi-dashboard 1        # 启动 Dashboard"
Write-Host "  kimi-dashboard 2        # 启动本地 Kimi Code Web"
Write-Host "  kimi-dashboard 3        # 启动外网访问 Kimi Code Web"
Write-Host "  kimi-dashboard 4        # 停止 Kimi Code Web"
Write-Host "  kimi-dashboard 5        # 更新 Kimi Code"
Write-Host "  kimi-dashboard 6        # 更新 Dashboard"
Write-Host "  kimi-dashboard 7        # 完全卸载 Dashboard" -ForegroundColor White
Write-Host ""
Write-Host "或直接启动面板: $DASHBOARD_DIR\.venv\Scripts\python.exe app.py" -ForegroundColor White
