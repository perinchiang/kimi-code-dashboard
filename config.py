"""Central configuration: paths, constants, and app-wide settings."""

import json
import logging
import logging.handlers
import os
import tempfile
import threading
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).parent.resolve()
load_dotenv(APP_DIR / ".env")

HOME = Path.home()

# --- Paths ---
AGENTS_DIR = HOME / ".agents"
SKILL_LOCK = AGENTS_DIR / ".skill-lock.json"
KIMI_CODE_DIR = HOME / ".kimi-code"
KIMI_CONFIG = KIMI_CODE_DIR / "config.toml"
MCP_CONFIG = KIMI_CODE_DIR / "mcp.json"
KIMI_LOG = KIMI_CODE_DIR / "logs" / "kimi-code.log"
KIMI_CREDENTIALS = KIMI_CODE_DIR / "credentials" / "kimi-code.json"
SESSIONS_DIR = KIMI_CODE_DIR / "sessions"
GATEWAY_BASE = "http://127.0.0.1:8420"
TASKS_CONFIG = APP_DIR / "tasks.json"
DASHBOARD_CONFIG = APP_DIR / "dashboard-config.json"

_DEFAULT_DASHBOARD_CONFIG = {
    "dashboard": {"host": "127.0.0.1", "port": 18080},
    "kimi_web": {
        "bind": "0.0.0.0",
        "port": 5494,
        "bypass_auth": True,
        "allowed_hosts": "",
        "public_urls": [],
    },
}
_dashboard_config_lock = threading.RLock()


def validate_port(value, name="port") -> int:
    """Return a valid TCP port, rejecting booleans, fractions, and out-of-range values."""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是 1-65535 之间的整数")
    if isinstance(value, int):
        port = value
    elif isinstance(value, str) and value.strip().isdigit():
        port = int(value.strip())
    else:
        raise ValueError(f"{name} 必须是 1-65535 之间的整数")
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} 必须是 1-65535 之间的整数")
    return port


def _normalize_dashboard_config(data: dict | None) -> dict:
    data = data if isinstance(data, dict) else {}
    dashboard = data.get("dashboard") if isinstance(data.get("dashboard"), dict) else {}
    kimi_web = data.get("kimi_web") if isinstance(data.get("kimi_web"), dict) else {}

    dashboard_host = str(dashboard.get("host", "127.0.0.1")).strip() or "127.0.0.1"
    bind = str(kimi_web.get("bind", "0.0.0.0")).strip() or "0.0.0.0"
    allowed_hosts = kimi_web.get("allowed_hosts", "")
    if isinstance(allowed_hosts, list):
        allowed_hosts = ",".join(str(item).strip() for item in allowed_hosts if str(item).strip())
    else:
        allowed_hosts = str(allowed_hosts or "")
    public_urls = kimi_web.get("public_urls", [])
    if isinstance(public_urls, str):
        public_urls = [public_urls]
    if not isinstance(public_urls, list):
        public_urls = []

    return {
        "dashboard": {
            "host": dashboard_host,
            "port": validate_port(dashboard.get("port", 18080), "dashboard.port"),
        },
        "kimi_web": {
            "bind": bind,
            "port": validate_port(kimi_web.get("port", 5494), "kimi_web.port"),
            "bypass_auth": bool(kimi_web.get("bypass_auth", True)),
            "allowed_hosts": allowed_hosts,
            "public_urls": [str(url).strip() for url in public_urls if str(url).strip()],
        },
    }


def load_dashboard_config() -> dict:
    """Load and validate dashboard-config.json, falling back to safe defaults."""
    with _dashboard_config_lock:
        try:
            data = json.loads(DASHBOARD_CONFIG.read_text(encoding="utf-8"))
            return _normalize_dashboard_config(data)
        except FileNotFoundError:
            return _normalize_dashboard_config(_DEFAULT_DASHBOARD_CONFIG)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logging.getLogger("kimi_dashboard").warning(
                "Failed to load %s, using defaults: %s", DASHBOARD_CONFIG, exc
            )
            return _normalize_dashboard_config(_DEFAULT_DASHBOARD_CONFIG)


def save_dashboard_config(data: dict) -> dict:
    """Validate and atomically persist dashboard configuration."""
    normalized = _normalize_dashboard_config(data)
    payload = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
    with _dashboard_config_lock:
        DASHBOARD_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{DASHBOARD_CONFIG.name}.", suffix=".tmp", dir=DASHBOARD_CONFIG.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, DASHBOARD_CONFIG)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
    return normalized


# --- Dashboard metadata ---
DASHBOARD_VERSION = "1.0.17"
LAUNCHD_PLIST_PATH = HOME / "Library" / "LaunchAgents" / "com.perinchiang.kimi-code-dashboard.plist"

_dashboard_runtime_config = load_dashboard_config()["dashboard"]
DASHBOARD_HOST = _dashboard_runtime_config["host"]
DASHBOARD_PORT = _dashboard_runtime_config["port"]
DASHBOARD_URL = f"http://127.0.0.1:{DASHBOARD_PORT}"

# --- Kimi binary ---
KIMI_BIN = KIMI_CODE_DIR / "bin" / ("kimi.exe" if os.name == "nt" else "kimi")
KIMI_GITHUB_LATEST = "https://api.github.com/repos/MoonshotAI/kimi-code/releases/latest"
KIMI_RELEASES_PAGE = "https://github.com/MoonshotAI/kimi-code/releases"

# --- Dashboard binary / updates ---
DASHBOARD_GITHUB_LATEST = "https://api.github.com/repos/perinchiang/kimi-code-dashboard/releases/latest"
DASHBOARD_RELEASES_PAGE = "https://github.com/perinchiang/kimi-code-dashboard/releases"

# --- Kimi Web ---
# Pat prefers: bind 0.0.0.0, no auth, allowed reverse-proxy host, keep-alive.
KIMI_WEB_PORT = int(os.getenv("KIMI_WEB_PORT", "5494"))
KIMI_WEB_HOST = os.getenv("KIMI_WEB_HOST", "0.0.0.0")
KIMI_WEB_KEEP_ALIVE = os.getenv("KIMI_WEB_KEEP_ALIVE", "1") in ("1", "true", "True", "yes")
KIMI_WEB_BYPASS_AUTH = os.getenv("KIMI_WEB_BYPASS_AUTH", "1") in ("1", "true", "True", "yes")
KIMI_WEB_ALLOWED_HOSTS = [h.strip() for h in os.getenv("KIMI_WEB_ALLOWED_HOSTS", "").split(",") if h.strip()]
KIMI_WEB_PUBLIC_URL = os.getenv("KIMI_WEB_PUBLIC_URL", "").rstrip("/")

# --- Cache TTLs (seconds) ---
TREND_CACHE_TTL = 60
TOOL_USAGE_CACHE_TTL = 60
VERSION_CACHE_TTL_OK = 600
VERSION_CACHE_TTL_ERR = 60


def setup_logging() -> logging.Logger:
    """Configure module-level logger that writes to dashboard.log."""
    logger = logging.getLogger("kimi_dashboard")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        handler = logging.handlers.RotatingFileHandler(
            APP_DIR / "dashboard.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
        )
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        # Also log WARNING+ to console
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        console.setFormatter(formatter)
        logger.addHandler(console)
    return logger


log = setup_logging()
