"""AGENTS.md editor API with fixed, safe scope mappings."""

import glob
import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import APP_DIR, KIMI_CODE_DIR, log
from services.helpers import atomic_write_text, config_lock, lock_for

bp = Blueprint("agents", __name__)

_SCOPE_META = {
    "global": {
        "label": "全局 Kimi Code",
        "description": "对所有 Kimi Code 会话生效",
    },
    "user": {
        "label": "全局 Agent",
        "description": "对所有 Agent 工具共享的用户指令",
    },
    "project": {
        "label": "当前项目",
        "description": "当前 Dashboard 项目的项目规则",
    },
    "project-kimi": {
        "label": "项目 Kimi Code",
        "description": "仅对当前项目的 Kimi Code 指令生效",
    },
}


def _kimi_home() -> Path:
    configured = os.getenv("KIMI_CODE_HOME", "").strip()
    return Path(configured).expanduser() if configured else KIMI_CODE_DIR


def _scope_path(scope: str) -> Path | None:
    if scope == "global":
        return _kimi_home() / "AGENTS.md"
    if scope == "user":
        return Path.home() / ".agents" / "AGENTS.md"
    if scope == "project":
        return APP_DIR / "AGENTS.md"
    if scope == "project-kimi":
        return APP_DIR / ".kimi-code" / "AGENTS.md"
    return None


def _revision(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _safe_resolved_path(path: Path) -> Path:
    """Resolve a fixed target and reject symlinks that redirect writes."""
    if path.name != "AGENTS.md":
        raise ValueError("非法 Agent 文件名")
    if path.is_symlink() or (path.parent.exists() and path.parent.is_symlink()):
        raise ValueError("拒绝操作指向其他位置的 Agent 路径")
    return path.resolve()


def _read_scope(scope: str) -> dict:
    path = _scope_path(scope)
    if path is None:
        raise ValueError("未知的 Agent 指令作用域")
    path = _safe_resolved_path(path)
    meta = _SCOPE_META[scope]
    result = {
        "id": scope,
        "label": meta["label"],
        "description": meta["description"],
        "path": str(path),
        "exists": False,
        "size": 0,
        "mtime": None,
        "revision": "",
        "content": "",
        "writable": os.access(path.parent, os.W_OK) if path.parent.exists() else True,
    }
    if not path.exists():
        return result
    if not path.is_file():
        raise OSError("目标 AGENTS.md 不是普通文件")
    content = path.read_text(encoding="utf-8")
    stat = path.stat()
    result.update({
        "exists": True,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "revision": _revision(content),
        "content": content,
        "writable": os.access(path, os.W_OK),
    })
    return result


def _public_scope(data: dict) -> dict:
    data = dict(data)
    data.pop("content", None)
    return data


def _backup_path(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return path.with_name(f"{path.name}.{timestamp}.bak")


def _cleanup_backups(path: Path, max_keep: int = 10) -> None:
    backups = sorted(
        glob.glob(str(path.with_name(f"{path.name}.*.bak"))),
        key=lambda item: Path(item).stat().st_mtime,
        reverse=True,
    )
    for old in backups[max_keep:]:
        try:
            Path(old).unlink()
        except OSError:
            pass


def _backup_existing(path: Path) -> None:
    if not path.exists():
        return
    shutil.copy2(path, _backup_path(path))
    _cleanup_backups(path)


def _error_response(message: str, status: int = 500):
    return jsonify({"success": False, "error": message}), status


@bp.route("/api/agents")
def api_agents():
    scopes = []
    for scope in _SCOPE_META:
        try:
            scopes.append(_public_scope(_read_scope(scope)))
        except Exception as exc:
            log.warning("Failed to inspect Agent scope %s: %s", scope, exc)
            scopes.append({
                "id": scope,
                "label": _SCOPE_META[scope]["label"],
                "description": _SCOPE_META[scope]["description"],
                "exists": False,
                "error": "无法读取文件状态",
            })
    return jsonify({"scopes": scopes})


@bp.route("/api/agents/<scope>")
def api_agent(scope: str):
    try:
        return jsonify(_read_scope(scope))
    except ValueError as exc:
        return _error_response(str(exc), 400)
    except FileNotFoundError:
        return _error_response("AGENTS.md 不存在", 404)
    except UnicodeDecodeError:
        return _error_response("AGENTS.md 不是 UTF-8 文本文件", 422)
    except OSError as exc:
        log.error("Failed to read Agent scope %s: %s", scope, exc)
        return _error_response("读取 AGENTS.md 失败", 500)


@bp.route("/api/agents/<scope>", methods=["PUT"])
def api_agent_save(scope: str):
    path = _scope_path(scope)
    if path is None:
        return _error_response("未知的 Agent 指令作用域", 400)
    body = request.get_json(silent=True) or {}
    content = body.get("content")
    if not isinstance(content, str):
        return _error_response("content 必须是字符串", 400)
    requested_revision = body.get("revision", "")
    if not isinstance(requested_revision, str):
        return _error_response("revision 必须是字符串", 400)
    force = body.get("force") is True

    try:
        path = _safe_resolved_path(path)
        with config_lock(lock_for(path)):
            current_content = ""
            if path.exists():
                if not path.is_file():
                    return _error_response("目标 AGENTS.md 不是普通文件", 409)
                current_content = path.read_text(encoding="utf-8")
            current_revision = _revision(current_content) if path.exists() else ""
            if not force and requested_revision != current_revision:
                current = _read_scope(scope)
                return jsonify({
                    "success": False,
                    "conflict": True,
                    "error": "文件已被外部修改，请重新载入或确认覆盖保存",
                    "current": current,
                }), 409
            _backup_existing(path)
            atomic_write_text(path, content)
            saved = _read_scope(scope)
            saved.pop("content", None)
            return jsonify({"success": True, **saved})
    except UnicodeDecodeError:
        return _error_response("AGENTS.md 不是 UTF-8 文本文件，无法保存", 422)
    except (OSError, TimeoutError) as exc:
        log.error("Failed to save Agent scope %s: %s", scope, exc)
        return _error_response("保存 AGENTS.md 失败", 500)
    except ValueError as exc:
        return _error_response(str(exc), 400)
