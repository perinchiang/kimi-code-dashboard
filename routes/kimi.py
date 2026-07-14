"""Kimi usage, trends, quota, version check, and model distribution API blueprint."""

import concurrent.futures
import getpass
import json
import os
import platform
import re
import subprocess
import threading
import urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify

from config import (
    DASHBOARD_GITHUB_LATEST,
    DASHBOARD_RELEASES_PAGE,
    DASHBOARD_VERSION,
    KIMI_BIN,
    KIMI_CODE_DIR,
    KIMI_CONFIG,
    KIMI_CREDENTIALS,
    KIMI_GITHUB_LATEST,
    KIMI_LOG,
    KIMI_RELEASES_PAGE,
    SESSIONS_DIR,
    VERSION_CACHE_TTL_ERR,
    VERSION_CACHE_TTL_OK,
    log,
)
from services.helpers import no_window_kwargs, safe_json_load
from services.wire_parser import get_model_usage, get_trends, get_tool_usage

try:
    import tomllib  # Python 3.11+
except ImportError:
    tomllib = None

bp = Blueprint("kimi", __name__)


def _get_device_label() -> str:
    """Return a friendly device label like 'Patrickchiang's MacBook Air'.

    Falls back to username + OS name if model detection fails.
    """
    username = getpass.getuser() or os.getenv("USER") or os.getenv("USERNAME") or "本地"
    system = platform.system()
    model = ""

    try:
        if system == "Darwin":
            # system_profiler is slow; try sysctl hw.model first, then map common IDs.
            result = subprocess.run(
                ["sysctl", "-n", "hw.model"],
                capture_output=True, text=True, timeout=5,
            )
            hw_model = result.stdout.strip()
            model = _map_mac_model(hw_model) if hw_model else ""
            if not model:
                # Fallback to system_profiler for a human-readable name.
                result = subprocess.run(
                    ["system_profiler", "SPHardwareDataType", "-json"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    sp = json.loads(result.stdout)
                    items = sp.get("SPHardwareDataType", [])
                    if items:
                        model = items[0].get("machine_model", "")
        elif system == "Windows":
            # 优先用 PowerShell Get-CimInstance(Win11 24H2 起默认不再安装 wmic)
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance -ClassName Win32_ComputerSystem).Model"],
                capture_output=True, text=True, errors="replace", timeout=10,
                **no_window_kwargs(),
            )
            model = result.stdout.strip() if result.returncode == 0 else ""
            # Fallback:旧版 Windows 仍可用 wmic
            if not model:
                result = subprocess.run(
                    ["wmic", "computersystem", "get", "model", "/value"],
                    capture_output=True, text=True, errors="replace", timeout=10,
                    **no_window_kwargs(),
                )
                for line in result.stdout.splitlines():
                    if line.startswith("Model="):
                        model = line.split("=", 1)[1].strip()
                        break
        elif system == "Linux":
            product_path = Path("/sys/class/dmi/id/product_name")
            if product_path.exists():
                model = product_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        log.debug("Device model detection failed: %s", e)

    if not model:
        model = system or "Computer"

    # Capitalize first letter of username for nicer display.
    display_user = username[:1].upper() + username[1:] if username else "本地"
    return f"{display_user}'s {model}"


def _map_mac_model(hw_model: str) -> str:
    """Map common Mac hw.model identifiers to human-readable names."""
    # Mapping is intentionally conservative; unknown IDs fall back to system_profiler.
    mappings = {
        "MacBookAir10,1": "MacBook Air M1",
        "MacBookAir10,2": "MacBook Air M1",
        "Mac14,2": "MacBook Air M2",
        "Mac14,15": "MacBook Air M2",
        "Mac15,12": "MacBook Air M3",
        "Mac15,13": "MacBook Air M3",
        "MacBookPro18,1": "MacBook Pro 14-inch M1 Pro",
        "MacBookPro18,2": "MacBook Pro 16-inch M1 Pro",
        "Mac14,9": "MacBook Pro 14-inch M2 Pro",
        "Mac14,10": "MacBook Pro 16-inch M2 Pro",
        "Mac15,3": "MacBook Pro 14-inch M3",
        "Mac15,6": "MacBook Pro 14-inch M3 Pro",
        "Mac15,7": "MacBook Pro 16-inch M3 Pro",
        "Mac15,8": "MacBook Pro 14-inch M3 Max",
        "Mac15,9": "MacBook Pro 16-inch M3 Max",
        "Mac13,1": "Mac Studio M1 Max",
        "Mac13,2": "Mac Studio M1 Ultra",
        "Mac14,13": "Mac Studio M2 Max",
        "Mac14,14": "Mac Studio M2 Ultra",
        "Mac15,5": "Mac Studio M3 Ultra",
        "Mac13,2": "Mac Studio M1 Ultra",
        "Macmini9,1": "Mac mini M1",
        "Mac14,3": "Mac mini M2",
        "Mac14,12": "Mac mini M2 Pro",
        "Mac15,4": "Mac mini M3",
        "Mac15,5": "Mac mini M3 Pro",
        "iMac21,1": "iMac 24-inch M1",
        "iMac21,2": "iMac 24-inch M1",
        "iMac23,1": "iMac 24-inch M3",
        "iMac23,2": "iMac 24-inch M3",
    }
    return mappings.get(hw_model, "")


# ---------------------------------------------------------------------------
# Kimi basic info
# ---------------------------------------------------------------------------
@bp.route("/api/kimi")
def api_kimi():
    # Prefer live `kimi --version` so the UI reflects upgrades immediately.
    version = _get_kimi_version_cli() or "unknown"
    starts = []

    if version == "unknown" and KIMI_LOG.exists():
        try:
            text = KIMI_LOG.read_text(encoding="utf-8")
            versions = re.findall(r"version=(\S+)", text)
            if versions:
                version = versions[-1]
        except Exception as e:
            log.warning("Failed to parse kimi log: %s", e)

    if KIMI_LOG.exists():
        try:
            text = KIMI_LOG.read_text(encoding="utf-8")
            starts = re.findall(
                r"^([\d\-T:.Z]+)\s+.*kimi-code starting\s+version=(\S+)",
                text,
                re.MULTILINE,
            )
        except Exception as e:
            log.warning("Failed to parse kimi log: %s", e)

    logged_in = False
    if KIMI_CREDENTIALS.exists():
        creds = safe_json_load(KIMI_CREDENTIALS)
        logged_in = bool(creds and creds.get("access_token"))

    session_count = 0
    if SESSIONS_DIR.exists():
        try:
            for workspace_dir in SESSIONS_DIR.iterdir():
                if workspace_dir.is_dir():
                    session_count += sum(
                        1 for d in workspace_dir.iterdir()
                        if d.is_dir() and d.name.startswith("session_")
                    )
        except Exception as e:
            log.warning("Failed to count sessions: %s", e)

    return jsonify({
        "version": version,
        "startCount": len(starts),
        "lastStartAt": starts[-1][0] if starts else None,
        "sessionCount": session_count,
        "loggedIn": logged_in,
        "consoleUrl": "https://www.kimi.com/code/console?from=kfc_overview_topbar",
        "deviceLabel": _get_device_label(),
    })


# ---------------------------------------------------------------------------
# Trends (cached)
# ---------------------------------------------------------------------------
@bp.route("/api/kimi-trends")
def api_kimi_trends():
    return jsonify(get_trends())


# ---------------------------------------------------------------------------
# Tool usage (cached)
# ---------------------------------------------------------------------------
@bp.route("/api/tool-usage")
def api_tool_usage():
    return jsonify(get_tool_usage())


# ---------------------------------------------------------------------------
# Model usage distribution (new feature)
# ---------------------------------------------------------------------------
@bp.route("/api/model-usage")
def api_model_usage():
    return jsonify(get_model_usage())


def _get_kimi_api_key() -> str:
    """Read the Kimi provider API key from Kimi Code config.toml.

    Falls back to KIMI_API_KEY env var for backward compatibility.
    """
    # 1. Prefer the key configured in Kimi Code "第三方模型 - kimi".
    if tomllib and KIMI_CONFIG.exists():
        try:
            cfg = tomllib.loads(KIMI_CONFIG.read_text(encoding="utf-8-sig"))
            providers = cfg.get("providers", {})
            for key, value in providers.items():
                if isinstance(value, dict) and value.get("type") == "kimi":
                    candidate = value.get("api_key", "")
                    if candidate:
                        return candidate
        except Exception as e:
            log.debug("Failed to read Kimi provider key from config.toml: %s", e)

    # 2. Backward compatibility: explicit env key.
    env_key = os.getenv("KIMI_API_KEY", "")
    if env_key:
        return env_key

    return ""


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------
@bp.route("/api/kimi-quota")
def api_kimi_quota():
    api_key = _get_kimi_api_key()
    if not api_key:
        return jsonify({
            "configured": False,
            "error": "请前往第三方模型中 Kimi 配置好 key",
            "fiveHour": None,
            "weekly": None,
        })

    # API keys must be ASCII to be sent in HTTP headers.
    try:
        api_key.encode("ascii")
    except UnicodeEncodeError:
        return jsonify({
            "configured": True,
            "error": "请前往第三方模型中 Kimi 配置好 key",
            "fiveHour": None,
            "weekly": None,
        })

    url = "https://api.kimi.com/coding/v1/usages"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_msg = f"HTTP {e.code}"
        if e.code == 401:
            error_msg = "请前往第三方模型中 Kimi 配置好 key"
        return jsonify({
            "configured": True,
            "error": error_msg,
            "fiveHour": None,
            "weekly": None,
        })
    except (UnicodeEncodeError, UnicodeDecodeError) as e:
        log.warning("Kimi quota query failed (encoding): %s", e)
        return jsonify({
            "configured": True,
            "error": "请前往第三方模型中 Kimi 配置好 key",
            "fiveHour": None,
            "weekly": None,
        })
    except Exception as e:
        log.warning("Kimi quota query failed: %s", e)
        return jsonify({
            "configured": True,
            "error": str(e),
            "fiveHour": None,
            "weekly": None,
        })

    def _parse_tier(value):
        if not value:
            return None
        limit = value.get("limit")
        remaining = value.get("remaining")
        reset_time = value.get("resetTime")
        try:
            limit_f = float(limit) if limit is not None else None
            remaining_f = float(remaining) if remaining is not None else None
            used_f = (limit_f - remaining_f) if limit_f is not None and remaining_f is not None else None
        except (TypeError, ValueError):
            limit_f = remaining_f = used_f = None
        return {
            "limit": limit_f,
            "remaining": remaining_f,
            "used": used_f,
            "resetTime": reset_time,
        }

    five_hour = None
    if isinstance(body.get("limits"), list) and body["limits"]:
        first = body["limits"][0]
        if isinstance(first, dict):
            five_hour = _parse_tier(first.get("detail"))

    weekly = _parse_tier(body.get("usage"))

    return jsonify({
        "configured": True,
        "error": None,
        "fiveHour": five_hour,
        "weekly": weekly,
    })


# ---------------------------------------------------------------------------
# Version check & one-click update
# ---------------------------------------------------------------------------
_version_cache: dict = {
    "kimi": {"data": None, "at": 0.0, "ok": False},
    "dashboard": {"data": None, "at": 0.0, "ok": False},
}


def _get_kimi_version_cli() -> str:
    try:
        result = subprocess.run(
            [str(KIMI_BIN), "--version"],
            capture_output=True, text=True, timeout=10,
            **no_window_kwargs(),
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0].strip()
    except Exception as e:
        log.debug("kimi --version failed: %s", e)
    return ""


def _fetch_latest_release(api_url: str, repo: str, releases_page: str) -> dict | None:
    """Fetch the latest release from GitHub API, falling back to `gh` CLI on rate limits."""
    body = None
    rate_limited = False

    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "kimi-code-dashboard",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            rate_limited = True
        elif e.code == 404:
            return {"error": "no_releases", "message": "暂无发布版本"}
        else:
            return {"error": f"HTTP {e.code}"}
    except Exception:
        rate_limited = True

    if body is None and rate_limited:
        try:
            result = subprocess.run(
                ["gh", "release", "view", "--repo", repo,
                 "--json", "tagName,name,publishedAt,url,body"],
                capture_output=True, text=True, timeout=15,
                **no_window_kwargs(),
            )
            if result.returncode == 0 and result.stdout.strip():
                gh_body = json.loads(result.stdout.strip())
                body = {
                    "tag_name": gh_body.get("tagName", ""),
                    "name": gh_body.get("name", ""),
                    "published_at": gh_body.get("publishedAt", ""),
                    "html_url": gh_body.get("url", releases_page),
                    "body": gh_body.get("body", ""),
                }
        except Exception as e:
            log.debug("gh release fallback failed: %s", e)

    if body is None:
        msg = "GitHub API 限流，请稍后再试" if rate_limited else "查询失败"
        return {"error": "rate_limited" if rate_limited else "fetch_failed", "message": msg}

    tag = body.get("tag_name", "")
    if not tag:
        return {"error": "invalid_response"}
    version = tag.rsplit("@", 1)[-1] if "@" in tag else tag.lstrip("v")
    notes = body.get("body", "") or ""
    if len(notes) > 600:
        notes = notes[:600] + "\u2026"
    return {
        "version": version,
        "tagName": tag,
        "name": body.get("name", ""),
        "publishedAt": body.get("published_at", ""),
        "url": body.get("html_url", releases_page),
        "notes": notes,
    }


def _compare_versions(a: str, b: str) -> int:
    def parse(v: str) -> list[int]:
        parts: list[int] = []
        for p in v.split("."):
            num = ""
            for ch in p:
                if ch.isdigit():
                    num += ch
                else:
                    break
            parts.append(int(num) if num else 0)
        return parts
    pa, pb = parse(a), parse(b)
    while len(pa) < len(pb):
        pa.append(0)
    while len(pb) < len(pa):
        pb.append(0)
    for x, y in zip(pa, pb):
        if x < y:
            return -1
        if x > y:
            return 1
    return 0


def _get_cached_latest(product: str, api_url: str, repo: str, releases_page: str) -> dict:
    """Return cached or freshly fetched latest-release info for a product."""
    now_ts = datetime.now(timezone.utc).timestamp()
    cache = _version_cache[product]
    cache_ttl = VERSION_CACHE_TTL_OK if cache["ok"] else VERSION_CACHE_TTL_ERR
    if cache["data"] is None or now_ts - cache["at"] > cache_ttl:
        latest_info = _fetch_latest_release(api_url, repo, releases_page)
        if latest_info is None:
            latest_info = {"error": "查询失败"}
        cache["data"] = latest_info
        cache["at"] = now_ts
        cache["ok"] = "error" not in latest_info
    return cache["data"]


def _build_version_response(current: str, latest_info: dict) -> dict:
    """Build version-check response for a single product."""
    if "error" in latest_info:
        return {
            "current": current,
            "latest": None,
            "updateAvailable": False,
            "error": latest_info["error"],
            "message": latest_info.get("message", ""),
        }
    latest = latest_info.get("version", "")
    update_available = bool(current != "unknown" and latest and _compare_versions(current, latest) < 0)
    return {
        "current": current,
        "latest": latest,
        "updateAvailable": update_available,
        "releaseName": latest_info.get("name", ""),
        "publishedAt": latest_info.get("publishedAt", ""),
        "releaseUrl": latest_info.get("url", ""),
        "releaseNotes": latest_info.get("notes", ""),
    }


@bp.route("/api/kimi-update")
def api_kimi_update_check():
    # Check both products in parallel to keep the click-to-check snappy.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        kimi_future = executor.submit(
            _get_cached_latest,
            "kimi",
            KIMI_GITHUB_LATEST,
            "MoonshotAI/kimi-code",
            KIMI_RELEASES_PAGE,
        )
        dashboard_future = executor.submit(
            _get_cached_latest,
            "dashboard",
            DASHBOARD_GITHUB_LATEST,
            "perinchiang/kimi-code-dashboard",
            DASHBOARD_RELEASES_PAGE,
        )
        kimi_info = kimi_future.result()
        dashboard_info = dashboard_future.result()

    return jsonify({
        "kimi": _build_version_response(_get_kimi_version_cli() or "unknown", kimi_info),
        "dashboard": _build_version_response(DASHBOARD_VERSION, dashboard_info),
    })


_upgrade_state: dict = {"proc": None, "log_path": None, "started_at": 0.0, "manual": False}
_upgrade_lock = threading.Lock()

_MANUAL_INSTALL_URL_PS1 = "https://code.kimi.com/kimi-code/install.ps1"
_MANUAL_INSTALL_URL_SH = "https://code.kimi.com/kimi-code/install.sh"


@bp.route("/api/kimi-update/run", methods=["POST"])
def api_kimi_update_run():
    """POST-only: triggers `kimi upgrade` as a background subprocess."""
    import tempfile
    with _upgrade_lock:
        proc = _upgrade_state.get("proc")
        if proc is not None and proc.poll() is None:
            return jsonify({"status": "already_running"})

        log_fd, log_path = tempfile.mkstemp(suffix=".log", prefix="kimi_upgrade_")
        os.close(log_fd)
        try:
            logf = open(log_path, "w", encoding="utf-8")
            kwargs = {
                "stdout": logf,
                "stderr": subprocess.STDOUT,
                "cwd": str(KIMI_BIN.parent.parent),
            }
            kwargs.update(no_window_kwargs())
            proc = subprocess.Popen([str(KIMI_BIN), "upgrade"], **kwargs)
        except Exception as e:
            log.error("Failed to start kimi upgrade: %s", e)
            logf.close()
            return jsonify({"status": "error", "error": str(e)})

        _upgrade_state["proc"] = proc
        _upgrade_state["logf"] = logf
        _upgrade_state["log_path"] = log_path
        _upgrade_state["started_at"] = datetime.now(timezone.utc).timestamp()
        _upgrade_state["manual"] = False
    return jsonify({"status": "started"})


@bp.route("/api/kimi-update/manual-run", methods=["POST"])
def api_kimi_update_manual_run():
    """POST-only: run the official installer for manual Kimi Code installs.

    Windows uses install.ps1 (PowerShell); macOS/Linux uses install.sh (bash).
    """
    import tempfile
    with _upgrade_lock:
        proc = _upgrade_state.get("proc")
        if proc is not None and proc.poll() is None:
            return jsonify({"status": "already_running"})

        log_fd, log_path = tempfile.mkstemp(suffix=".log", prefix="kimi_manual_upgrade_")
        os.close(log_fd)
        try:
            logf = open(log_path, "w", encoding="utf-8")
            if platform.system() == "Windows":
                cmd = [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command", f"irm {_MANUAL_INSTALL_URL_PS1} | iex",
                ]
                log.info("Started manual Kimi Code install via PowerShell")
            else:
                # macOS / Linux: curl install.sh | bash
                cmd = ["bash", "-c", f"curl -fsSL {_MANUAL_INSTALL_URL_SH} | bash"]
                log.info("Started manual Kimi Code install via bash")
            kwargs = {
                "stdout": logf,
                "stderr": subprocess.STDOUT,
            }
            kwargs.update(no_window_kwargs())
            proc = subprocess.Popen(cmd, **kwargs)
        except Exception as e:
            log.error("Failed to start manual kimi install: %s", e)
            logf.close()
            return jsonify({"status": "error", "error": str(e)})

        _upgrade_state["proc"] = proc
        _upgrade_state["logf"] = logf
        _upgrade_state["log_path"] = log_path
        _upgrade_state["started_at"] = datetime.now(timezone.utc).timestamp()
        _upgrade_state["manual"] = True
    return jsonify({"status": "started"})


@bp.route("/api/kimi-update/status")
def api_kimi_update_status():
    with _upgrade_lock:
        proc = _upgrade_state.get("proc")
        log_path = _upgrade_state.get("log_path")
    if proc is None:
        return jsonify({"status": "idle", "running": False, "log": ""})

    running = proc.poll() is None
    exit_code = proc.returncode if not running else None
    log_text = ""
    if log_path and os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                log_text = f.read()
        except Exception:
            log_text = ""

    # 进程结束后关闭日志 fd,避免泄漏
    if not running:
        old_logf = _upgrade_state.pop("logf", None)
        if old_logf and not old_logf.closed:
            try:
                old_logf.close()
            except Exception:
                pass
        # Clean up the temp log file
        if log_path:
            try:
                os.unlink(log_path)
            except OSError:
                pass
        _upgrade_state["log_path"] = None
        _upgrade_state["proc"] = None

    status = "running" if running else ("success" if exit_code == 0 else "failed")
    manual_update = False
    manual_command = ""
    if not running and "Auto-update is not supported" in log_text:
        status = "manual_update"
        manual_update = True
        m = re.search(r"To update manually, run:\s*(.+)", log_text)
        if m:
            manual_command = m.group(1).strip()
        elif platform.system() == "Windows":
            manual_command = f"irm {_MANUAL_INSTALL_URL_PS1} | iex"
        else:
            manual_command = f"curl -fsSL {_MANUAL_INSTALL_URL_SH} | bash"

    return jsonify({
        "status": status,
        "running": running,
        "exitCode": exit_code,
        "log": log_text[-4000:] if len(log_text) > 4000 else log_text,
        "manualUpdate": manual_update,
        "manualCommand": manual_command,
        "manual": bool(_upgrade_state.get("manual")),
    })
