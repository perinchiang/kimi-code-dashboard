"""MCP server status API blueprint.

Supports listing, enabling/disabling, editing config, and removing MCP servers.
Disabled servers are stored in ~/.kimi-code/.mcp-disabled.json.
"""

import json
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import GATEWAY_BASE, KIMI_CODE_DIR, MCP_CONFIG, log
from services.helpers import http_get, safe_json_load

bp = Blueprint("mcp", __name__)

MCP_DISABLED_CONFIG = KIMI_CODE_DIR / ".mcp-disabled.json"


def _load_mcp_config() -> dict:
    return safe_json_load(MCP_CONFIG) or {"mcpServers": {}}


def _save_mcp_config(cfg: dict) -> bool:
    try:
        MCP_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        log.error("Failed to write %s: %s", MCP_CONFIG, e)
        return False


def _load_disabled_config() -> dict:
    return safe_json_load(MCP_DISABLED_CONFIG) or {"mcpServers": {}}


def _save_disabled_config(cfg: dict) -> bool:
    try:
        MCP_DISABLED_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        log.error("Failed to write %s: %s", MCP_DISABLED_CONFIG, e)
        return False


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
        "env": cfg.get("env", {}),
        "description": cfg.get("description", ""),
        "status": status,
        "detail": detail,
    }


@bp.route("/api/mcp")
def api_mcp():
    cfg = _load_mcp_config()
    disabled_cfg = _load_disabled_config()
    enabled_servers = cfg.get("mcpServers", {})
    disabled_servers = disabled_cfg.get("mcpServers", {})

    result = []
    for name, srv in enabled_servers.items():
        info = _check_mcp_server(name, srv)
        info["enabled"] = True
        result.append(info)

    for name, srv in disabled_servers.items():
        info = _check_mcp_server(name, srv)
        info["enabled"] = False
        result.append(info)

    result.sort(key=lambda s: s["name"].lower())
    online = sum(1 for r in result if r["status"] == "online")
    available = sum(1 for r in result if r["status"] in ("online", "available"))
    enabled_count = sum(1 for r in result if r["enabled"])
    disabled_count = len(result) - enabled_count
    return jsonify({
        "total": len(result),
        "online": online,
        "available": available,
        "enabled": enabled_count,
        "disabled": disabled_count,
        "servers": result,
    })


@bp.route("/api/mcp/<server_id>/toggle", methods=["POST"])
def api_mcp_toggle(server_id: str):
    """Enable or disable an MCP server by moving it between configs."""
    cfg = _load_mcp_config()
    disabled_cfg = _load_disabled_config()
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled", True))

    enabled_servers = cfg.setdefault("mcpServers", {})
    disabled_servers = disabled_cfg.setdefault("mcpServers", {})

    currently_enabled = server_id in enabled_servers
    target_enabled = enabled

    if currently_enabled == target_enabled:
        return jsonify({"success": True, "enabled": target_enabled})

    if target_enabled:
        if server_id in disabled_servers:
            enabled_servers[server_id] = disabled_servers.pop(server_id)
        else:
            return jsonify({"success": False, "error": "Server not found in disabled list"}), 404
    else:
        if server_id in enabled_servers:
            disabled_servers[server_id] = enabled_servers.pop(server_id)
        else:
            return jsonify({"success": False, "error": "Server not found"}), 404

    if not _save_mcp_config(cfg):
        return jsonify({"success": False, "error": "保存 mcp.json 失败"}), 500
    if not _save_disabled_config(disabled_cfg):
        return jsonify({"success": False, "error": "保存 .mcp-disabled.json 失败"}), 500

    return jsonify({"success": True, "enabled": target_enabled})


@bp.route("/api/mcp/<server_id>/save", methods=["POST"])
def api_mcp_save(server_id: str):
    """Save MCP server configuration."""
    cfg = _load_mcp_config()
    disabled_cfg = _load_disabled_config()
    body = request.get_json(silent=True) or {}

    enabled_servers = cfg.setdefault("mcpServers", {})
    disabled_servers = disabled_cfg.setdefault("mcpServers", {})

    srv = enabled_servers.get(server_id) or disabled_servers.get(server_id)
    if not srv:
        return jsonify({"success": False, "error": "Server not found"}), 404

    new_srv = {
        "command": str(body.get("command", srv.get("command", ""))).strip(),
        "args": list(body.get("args", srv.get("args", []))),
        "cwd": str(body.get("cwd", srv.get("cwd", ""))).strip(),
        "description": str(body.get("description", srv.get("description", ""))).strip(),
    }
    if "env" in body or "env" in srv:
        new_srv["env"] = dict(body.get("env", srv.get("env", {})))

    if server_id in enabled_servers:
        enabled_servers[server_id] = new_srv
    else:
        disabled_servers[server_id] = new_srv

    if not _save_mcp_config(cfg):
        return jsonify({"success": False, "error": "保存 mcp.json 失败"}), 500
    if not _save_disabled_config(disabled_cfg):
        return jsonify({"success": False, "error": "保存 .mcp-disabled.json 失败"}), 500

    return jsonify({"success": True})


@bp.route("/api/mcp/<server_id>/delete", methods=["POST"])
def api_mcp_delete(server_id: str):
    """Remove an MCP server from both enabled and disabled configs."""
    cfg = _load_mcp_config()
    disabled_cfg = _load_disabled_config()

    enabled_servers = cfg.setdefault("mcpServers", {})
    disabled_servers = disabled_cfg.setdefault("mcpServers", {})

    if server_id not in enabled_servers and server_id not in disabled_servers:
        return jsonify({"success": False, "error": "Server not found"}), 404

    enabled_servers.pop(server_id, None)
    disabled_servers.pop(server_id, None)

    if not _save_mcp_config(cfg):
        return jsonify({"success": False, "error": "保存 mcp.json 失败"}), 500
    if not _save_disabled_config(disabled_cfg):
        return jsonify({"success": False, "error": "保存 .mcp-disabled.json 失败"}), 500

    return jsonify({"success": True})
