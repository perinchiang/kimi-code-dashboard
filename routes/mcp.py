"""MCP server status API blueprint."""

from pathlib import Path

from flask import Blueprint, jsonify

from config import GATEWAY_BASE, MCP_CONFIG, log
from services.helpers import http_get, safe_json_load

bp = Blueprint("mcp", __name__)


def _check_mcp_server(name: str, cfg: dict) -> dict:
    status = "unknown"
    detail = ""

    if name == "tencentdb-memory":
        health = http_get(f"{GATEWAY_BASE}/health")
        if health is not None:
            status = "online"
            detail = str(health.get("status", "ok"))
        else:
            status = "offline"
            detail = "Gateway not responding on port 8420"
    elif name == "memory":
        cmd = cfg.get("command", "")
        if Path(cmd).exists():
            status = "available"
            detail = "Python interpreter found; assumed managed by Kimi Code"
        else:
            status = "offline"
            detail = "Configured Python interpreter not found"
    else:
        cmd = cfg.get("command", "")
        if Path(cmd).exists():
            status = "available"
            detail = "Executable found"
        else:
            status = "offline"
            detail = "Executable not found"

    return {
        "name": name,
        "command": cfg.get("command", ""),
        "args": cfg.get("args", []),
        "cwd": cfg.get("cwd", ""),
        "status": status,
        "detail": detail,
    }


@bp.route("/api/mcp")
def api_mcp():
    cfg = safe_json_load(MCP_CONFIG) or {}
    servers = cfg.get("mcpServers", {})
    result = [_check_mcp_server(name, srv) for name, srv in servers.items()]
    online = sum(1 for r in result if r["status"] == "online")
    available = sum(1 for r in result if r["status"] in ("online", "available"))
    return jsonify({
        "total": len(result),
        "online": online,
        "available": available,
        "servers": result,
    })
