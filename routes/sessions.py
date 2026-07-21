"""Dashboard-owned Kimi session list and title APIs."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from config import load_dashboard_config, save_dashboard_config
from services.session_titles import (
    get_session,
    get_title_settings,
    list_sessions,
    queue_title_generation,
    restore_session,
    validate_title_model,
)

bp = Blueprint("sessions", __name__)


@bp.route("/api/sessions")
def api_sessions():
    try:
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        archived = request.args.get("archived", "active")
        result = list_sessions(limit=limit, offset=offset, archived=archived)
        return jsonify(result)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "会话列表读取失败"}), 500


@bp.route("/api/sessions/<session_id>")
def api_session_detail(session_id: str):
    session = get_session(session_id, detail=True)
    if session is None:
        return jsonify({"error": "会话不存在"}), 404
    return jsonify(session)


@bp.route("/api/sessions/<session_id>/restore", methods=["POST"])
def api_restore_session(session_id: str):
    try:
        result = restore_session(session_id)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception:
        return jsonify({"error": "会话恢复失败"}), 500
    if result is None:
        return jsonify({"error": "会话不存在"}), 404
    return jsonify({
        "restored": result["changed"],
        "session": result["session"],
    })


@bp.route("/api/sessions/<session_id>/title/generate", methods=["POST"])
def api_generate_session_title(session_id: str):
    body = request.get_json(silent=True) or {}
    settings = get_title_settings()
    max_title_length = body.get("max_title_length", settings.get("max_title_length", 80))
    try:
        result = queue_title_generation(session_id, max_title_length=max_title_length, source="manual")
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "标题生成任务创建失败"}), 500
    if result is None:
        return jsonify({"error": "会话不存在"}), 404
    return jsonify(result), 202 if result.get("status") in {"queued", "running"} else 200


@bp.route("/api/session-title-settings", methods=["GET"])
def api_session_title_settings():
    return jsonify(get_title_settings())


@bp.route("/api/session-title-settings", methods=["POST"])
def api_save_session_title_settings():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "配置格式无效"}), 400
    try:
        config = load_dashboard_config()
        current = config.get("session_titles", {})
        if "model" in body:
            current["model"] = validate_title_model(body["model"])
        elif current.get("model"):
            current["model"] = validate_title_model(current["model"])
        if "enabled" in body:
            if not isinstance(body["enabled"], bool):
                raise ValueError("enabled 必须是布尔值")
            current["enabled"] = body["enabled"]
        current.update({key: body[key] for key in ("auto_generate", "every_exchanges", "max_title_length") if key in body})
        config["session_titles"] = current
        normalized = save_dashboard_config(config)
        return jsonify(normalized.get("session_titles", {}))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "标题配置保存失败"}), 500
