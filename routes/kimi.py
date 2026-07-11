"""Kimi usage, trends, quota, version check, and model distribution API blueprint."""

import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone

from flask import Blueprint, jsonify

from config import (
    KIMI_BIN,
    KIMI_CREDENTIALS,
    KIMI_GITHUB_LATEST,
    KIMI_LOG,
    KIMI_RELEASES_PAGE,
    SESSIONS_DIR,
    VERSION_CACHE_TTL_ERR,
    VERSION_CACHE_TTL_OK,
    log,
)
from services.helpers import safe_json_load
from services.wire_parser import get_model_usage, get_trends, get_tool_usage

bp = Blueprint("kimi", __name__)


# ---------------------------------------------------------------------------
# Kimi basic info
# ---------------------------------------------------------------------------
@bp.route("/api/kimi")
def api_kimi():
    version = "unknown"
    starts = []

    if KIMI_LOG.exists():
        try:
            text = KIMI_LOG.read_text(encoding="utf-8")
            versions = re.findall(r"version=(\S+)", text)
            if versions:
                version = versions[-1]
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


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------
@bp.route("/api/kimi-quota")
def api_kimi_quota():
    api_key = os.getenv("KIMI_API_KEY", "")
    if not api_key:
        return jsonify({
            "configured": False,
            "error": "KIMI_API_KEY not set",
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
        return jsonify({
            "configured": True,
            "error": f"HTTP {e.code}",
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
_version_cache: dict = {"data": None, "at": 0.0, "ok": False}


def _get_kimi_version_cli() -> str:
    try:
        result = subprocess.run(
            [str(KIMI_BIN), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0].strip()
    except Exception as e:
        log.debug("kimi --version failed: %s", e)
    return ""


def _fetch_latest_release() -> dict | None:
    body = None
    rate_limited = False

    try:
        req = urllib.request.Request(
            KIMI_GITHUB_LATEST,
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
        else:
            return {"error": f"HTTP {e.code}"}
    except Exception:
        rate_limited = True

    if body is None and rate_limited:
        try:
            result = subprocess.run(
                ["gh", "release", "view", "--repo", "MoonshotAI/kimi-code",
                 "--json", "tagName,name,publishedAt,url,body"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                gh_body = json.loads(result.stdout.strip())
                body = {
                    "tag_name": gh_body.get("tagName", ""),
                    "name": gh_body.get("name", ""),
                    "published_at": gh_body.get("publishedAt", ""),
                    "html_url": gh_body.get("url", KIMI_RELEASES_PAGE),
                    "body": gh_body.get("body", ""),
                }
        except Exception as e:
            log.debug("gh release fallback failed: %s", e)

    if body is None:
        msg = "GitHub API 限流，请稍后再试" if rate_limited else "查询失败"
        return {"error": "rate_limited" if rate_limited else "fetch_failed", "message": msg}

    tag = body.get("tag_name", "")
    version = tag.rsplit("@", 1)[-1] if "@" in tag else tag.lstrip("v")
    notes = body.get("body", "") or ""
    if len(notes) > 600:
        notes = notes[:600] + "\u2026"
    return {
        "version": version,
        "tagName": tag,
        "name": body.get("name", ""),
        "publishedAt": body.get("published_at", ""),
        "url": body.get("html_url", KIMI_RELEASES_PAGE),
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


@bp.route("/api/kimi-update")
def api_kimi_update_check():
    current = _get_kimi_version_cli() or "unknown"
    now_ts = datetime.now(timezone.utc).timestamp()
    cached = _version_cache["data"]
    cache_ttl = VERSION_CACHE_TTL_OK if _version_cache["ok"] else VERSION_CACHE_TTL_ERR
    if cached is None or now_ts - _version_cache["at"] > cache_ttl:
        latest_info = _fetch_latest_release()
        if latest_info is None:
            latest_info = {"error": "查询失败"}
        _version_cache["data"] = latest_info
        _version_cache["at"] = now_ts
        _version_cache["ok"] = "error" not in latest_info
    else:
        latest_info = cached

    if "error" in latest_info:
        return jsonify({
            "current": current,
            "latest": None,
            "updateAvailable": False,
            "error": latest_info["error"],
            "message": latest_info.get("message", ""),
        })

    latest = latest_info.get("version", "")
    update_available = bool(current != "unknown" and latest and _compare_versions(current, latest) < 0)

    return jsonify({
        "current": current,
        "latest": latest,
        "updateAvailable": update_available,
        "releaseName": latest_info.get("name", ""),
        "publishedAt": latest_info.get("publishedAt", ""),
        "releaseUrl": latest_info.get("url", ""),
        "releaseNotes": latest_info.get("notes", ""),
    })


_upgrade_state: dict = {"proc": None, "log_path": None, "started_at": 0.0}


@bp.route("/api/kimi-update/run", methods=["POST"])
def api_kimi_update_run():
    """POST-only: triggers `kimi upgrade` as a background subprocess."""
    proc = _upgrade_state.get("proc")
    if proc is not None and proc.poll() is None:
        return jsonify({"status": "already_running"})

    import tempfile
    log_fd, log_path = tempfile.mkstemp(suffix=".log", prefix="kimi_upgrade_")
    os.close(log_fd)
    try:
        logf = open(log_path, "w", encoding="utf-8")
        kwargs = {
            "stdout": logf,
            "stderr": subprocess.STDOUT,
            "cwd": str(KIMI_BIN.parent.parent),
        }
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen([str(KIMI_BIN), "upgrade"], **kwargs)
    except Exception as e:
        log.error("Failed to start kimi upgrade: %s", e)
        return jsonify({"status": "error", "error": str(e)})

    _upgrade_state["proc"] = proc
    _upgrade_state["log_path"] = log_path
    _upgrade_state["started_at"] = datetime.now(timezone.utc).timestamp()
    return jsonify({"status": "started"})


@bp.route("/api/kimi-update/status")
def api_kimi_update_status():
    proc = _upgrade_state.get("proc")
    log_path = _upgrade_state.get("log_path")
    if proc is None:
        return jsonify({"status": "idle", "running": False, "log": ""})

    running = proc.poll() is None
    exit_code = proc.returncode if not running else None
    log_text = ""
    if log_path and os.path.exists(log_path):
        try:
            log_text = open(log_path, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            log_text = ""

    status = "running" if running else ("success" if exit_code == 0 else "failed")
    return jsonify({
        "status": status,
        "running": running,
        "exitCode": exit_code,
        "log": log_text[-4000:] if len(log_text) > 4000 else log_text,
    })
