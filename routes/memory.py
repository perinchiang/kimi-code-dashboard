"""Memory status API blueprint (L0-L3 via TencentDB Gateway)."""

from flask import Blueprint, jsonify

from config import GATEWAY_BASE, log
from services.helpers import http_get, http_post

bp = Blueprint("memory", __name__)


@bp.route("/api/memory")
def api_memory():
    def search(path: str, payload: dict) -> int:
        resp = http_post(f"{GATEWAY_BASE}{path}", payload, timeout=15)
        if resp is None:
            return -1
        return resp.get("total", 0)

    l0 = search("/search/conversations", {"query": "*", "limit": 1000, "session_key": "kimi-default"})
    l1 = search("/search/memories", {"query": "*", "type": "episodic", "limit": 1000})
    l2 = search("/search/memories", {"query": "*", "type": "instruction", "limit": 1000})
    l3 = search("/search/memories", {"query": "*", "type": "persona", "limit": 1000})

    return jsonify({
        "l0": l0,
        "l1": l1,
        "l2": l2,
        "l3": l3,
        "gatewayReachable": http_get(f"{GATEWAY_BASE}/health") is not None,
    })
