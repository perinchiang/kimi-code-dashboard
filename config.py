"""Central configuration: paths, constants, and app-wide settings."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).parent.resolve()
load_dotenv(APP_DIR / ".env")

HOME = Path.home()

# --- Paths ---
AGENTS_DIR = HOME / ".agents"
SKILL_LOCK = AGENTS_DIR / ".skill-lock.json"
KIMI_CODE_DIR = HOME / ".kimi-code"
MCP_CONFIG = KIMI_CODE_DIR / "mcp.json"
KIMI_LOG = KIMI_CODE_DIR / "logs" / "kimi-code.log"
KIMI_CREDENTIALS = KIMI_CODE_DIR / "credentials" / "kimi-code.json"
SESSIONS_DIR = KIMI_CODE_DIR / "sessions"
GATEWAY_BASE = "http://127.0.0.1:8420"
TASKS_CONFIG = APP_DIR / "tasks.json"

# --- Dashboard metadata ---
DASHBOARD_VERSION = "1.0.14"
LAUNCHD_PLIST_PATH = HOME / "Library" / "LaunchAgents" / "com.perinchiang.kimi-code-dashboard.plist"

# --- Kimi binary ---
KIMI_BIN = KIMI_CODE_DIR / "bin" / ("kimi.exe" if os.name == "nt" else "kimi")
KIMI_GITHUB_LATEST = "https://api.github.com/repos/MoonshotAI/kimi-code/releases/latest"
KIMI_RELEASES_PAGE = "https://github.com/MoonshotAI/kimi-code/releases"

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
        handler = logging.FileHandler(APP_DIR / "dashboard.log", encoding="utf-8")
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
