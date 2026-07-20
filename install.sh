#!/usr/bin/env bash
#
# kimi-code-dashboard installer for macOS and Linux.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/perinchiang/kimi-code-dashboard/master/install.sh | bash
#
# What it does:
#   1. Checks Python 3.10+ and git
#   2. Clones/updates ~/.kimi-code/dashboard
#   3. Creates venv + installs dependencies
#   4. Generates kimi-dashboard wrapper in ~/.kimi-code/bin/
#   5. Checks PATH and prints usage

set -euo pipefail

INSTALL_DIR="$HOME/.kimi-code"
DASHBOARD_DIR="$INSTALL_DIR/dashboard"
BIN_DIR="$INSTALL_DIR/bin"
REPO_URL="https://github.com/perinchiang/kimi-code-dashboard.git"

# Colors
if [ -t 1 ]; then
    CYAN='\033[1;36m'
    GREEN='\033[1;32m'
    YELLOW='\033[1;33m'
    RED='\033[1;31m'
    BOLD='\033[1m'
    RESET='\033[0m'
else
    CYAN=''; GREEN=''; YELLOW=''; RED=''; BOLD=''; RESET=''
fi

_log()   { printf "${CYAN}==>${RESET} %s\n" "$*"; }
_ok()    { printf "${GREEN}==>${RESET} %s\n" "$*"; }
_warn()  { printf "${YELLOW}==>${RESET} %s\n" "$*" >&2; }
_err()   { printf "${RED}error:${RESET} %s\n" "$*" >&2; }

# --- 1. Check Python 3.10+ ---
_log "检测 Python..."
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        major=$("$cmd" -c 'import sys; print(sys.version_info[0])' 2>/dev/null || echo "0")
        minor=$("$cmd" -c 'import sys; print(sys.version_info[1])' 2>/dev/null || echo "0")
        if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; }; then
            PYTHON="$cmd"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    _err "未找到 Python 3.10+"
    _err "请安装 Python 3.10 或更高版本:"
    _err "  macOS:  brew install python@3.12"
    _err "  Ubuntu: sudo apt install python3 python3-venv"
    _err "  Arch:   sudo pacman -S python"
    exit 1
fi
_ok "找到 Python: $($PYTHON --version)"

# --- Check git ---
if ! command -v git >/dev/null 2>&1; then
    _err "未找到 git,请先安装 git"
    exit 1
fi

# --- 2. Clone or update ---
_log "克隆/更新 Dashboard..."
mkdir -p "$INSTALL_DIR"
if [ -d "$DASHBOARD_DIR/.git" ]; then
    _log "已存在,执行 git pull..."
    git -C "$DASHBOARD_DIR" pull --ff-only origin master || {
        _warn "git pull 失败,请手动检查 $DASHBOARD_DIR"
    }
else
    if [ -d "$DASHBOARD_DIR" ]; then
        _warn "$DASHBOARD_DIR 已存在但不是 git 仓库,跳过 clone"
    else
        git clone --depth 1 "$REPO_URL" "$DASHBOARD_DIR"
    fi
fi

# --- 3. venv + dependencies ---
_log "创建虚拟环境..."
if [ ! -d "$DASHBOARD_DIR/.venv" ]; then
    "$PYTHON" -m venv "$DASHBOARD_DIR/.venv"
fi
_ok "安装依赖..."
"$DASHBOARD_DIR/.venv/bin/python" -m pip install --quiet --upgrade pip
"$DASHBOARD_DIR/.venv/bin/python" -m pip install --quiet -r "$DASHBOARD_DIR/requirements.txt"

# --- 4. Generate wrapper ---
_log "生成 kimi-dashboard 命令..."
mkdir -p "$BIN_DIR"
WRAPPER="$BIN_DIR/kimi-dashboard"
cat > "$WRAPPER" <<'WRAPPER_EOF'
#!/usr/bin/env bash
cd "$HOME/.kimi-code/dashboard"
exec ".venv/bin/python" launch_menu.py "$@"
WRAPPER_EOF
chmod +x "$WRAPPER"
_ok "已生成: $WRAPPER"

# --- 5. Check PATH ---
case ":$PATH:" in
    *":$BIN_DIR:"*)
        _ok "PATH 已包含 $BIN_DIR"
        ;;
    *)
        _warn "PATH 未包含 $BIN_DIR"
        _warn "请将以下行加入 ~/.zshrc 或 ~/.bashrc:"
        printf '  export PATH="%s:$PATH"\n' "$BIN_DIR"
        _warn "然后执行 source ~/.zshrc(或 ~/.bashrc)"
        ;;
esac

# --- 6. Done ---
echo
_ok "安装完成!"
echo
printf "${BOLD}用法:${RESET}\n"
printf "  kimi-dashboard          # 弹出菜单\n"
printf "  kimi-dashboard 1        # 启动 Dashboard\n"
printf "  kimi-dashboard 2        # 启动本地 Kimi Code Web\n"
printf "  kimi-dashboard 3        # 启动外网访问 Kimi Code Web\n"
printf "  kimi-dashboard 4        # 停止 Kimi Code Web\n"
printf "  kimi-dashboard 5        # 更新 Kimi Code\n"
printf "  kimi-dashboard 6        # 更新 Dashboard\n"
printf "  kimi-dashboard 7        # 完全卸载 Dashboard\n"
printf "  kimi-dashboard 8        # 重启 Dashboard\n"
echo
printf "或直接启动面板: ${BOLD}$DASHBOARD_DIR/.venv/bin/python app.py${RESET}\n"
