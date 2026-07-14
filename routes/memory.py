"""Memory status API blueprint (L0-L3 via TencentDB Gateway)."""

import re

from flask import Blueprint, jsonify, request

from config import GATEWAY_BASE, log
from services.helpers import http_get, http_post

bp = Blueprint("memory", __name__)


@bp.route("/api/memory")
def api_memory():
    def count(path: str, payload: dict, parser) -> int:
        resp = http_post(f"{GATEWAY_BASE}{path}", payload, timeout=15)
        if resp is None:
            return -1
        return len(parser(resp.get("results", "")))

    l0 = count("/search/conversations", {"query": "*", "limit": 500, "session_key": "kimi-default"}, _parse_conversations)
    l1 = count("/search/memories", {"query": "*", "type": "episodic", "limit": 500}, _parse_memories)
    l2 = count("/search/memories", {"query": "*", "type": "instruction", "limit": 500}, _parse_memories)
    l3 = count("/search/memories", {"query": "*", "type": "persona", "limit": 500}, _parse_memories)

    return jsonify({
        "l0": l0,
        "l1": l1,
        "l2": l2,
        "l3": l3,
        "gatewayReachable": http_get(f"{GATEWAY_BASE}/health") is not None,
    })


# --- results 文本解析 ---
# gateway 的 /search/* 接口返回的是拼好的纯文本(results 字段)，不是结构化数组。
# 这里把文本解析回结构化条目，供详情页列表展示。格式不稳时 fallback 到原文。

_CONV_HEAD_RE = re.compile(
    r"\*\*\[(.+?)\]\*\*\s+Session:\s+(.+?)\s+\[(.+?)\]\s+\(score:\s*([\d.]+)\)\s*\n*([\s\S]*)"
)
_MEM_ITEM_RE = re.compile(
    r"- \*\*\[(.+?)\]\*\*\s*\(priority:\s*(\d+)\)\s*(?:\[scene:\s*(.+?)\]\s*)?\(score:\s*([\d.]+)\)\s*\n([\s\S]*?)(?=\n- \*\*\[|$)"
)


def _parse_conversations(results: str) -> list:
    """解析 /search/conversations 的 results 文本为条目列表。

    文本形如: 'Found N matching message(s):\n\n---\n**[role]** Session: x [ts] (score: s)\n\ncontent\n---\n...'
    条目间以单独一行的 --- 分隔，但 content 里也可能含 ---（markdown 分隔线），
    会被误拆。误拆的块（不以 **[role]** Session: 开头）合并回上一条的 content。
    """
    items = []
    for block in re.split(r"(?m)^---\s*$", results):
        block = block.strip()
        if not block or block.startswith("Found "):
            continue
        m = _CONV_HEAD_RE.match(block)
        if m:
            items.append({
                "role": m.group(1).strip(),
                "session": m.group(2).strip(),
                "timestamp": m.group(3).strip(),
                "score": float(m.group(4)),
                "content": m.group(5).strip(),
            })
        elif items:
            # content 里的 --- 误拆，合并回上一条
            items[-1]["content"] = (items[-1].get("content", "") + "\n---\n" + block).strip()
    return items


def _parse_memories(results: str) -> list:
    """解析 /search/memories 的 results 文本为条目列表。

    文本形如: 'Found N matching memories:\n\n- **[type]** (priority: N) [scene: x] (score: s)\n  content\n\n- ...'
    """
    items = []
    for m in _MEM_ITEM_RE.finditer(results):
        items.append({
            "type": m.group(1).strip(),
            "priority": int(m.group(2)),
            "scene": (m.group(3) or "").strip(),
            "score": float(m.group(4)),
            "content": m.group(5).strip(),
        })
    return items


_LEVEL_MAP = {
    "l0": ("conversations", {"session_key": "kimi-default"}),
    "l1": ("memories", {"type": "episodic"}),
    "l2": ("memories", {"type": "instruction"}),
    "l3": ("memories", {"type": "persona"}),
}


@bp.route("/api/memory/items")
def api_memory_items():
    """返回某层级(L0-L3)的记忆条目列表，解析 gateway 文本为结构化条目。

    gateway 的 search 接口对 query 做语义相似度排序但不剔除低分项，
    传任意词都返回全部条目。因此这里始终用 '*' 拉全量，再在本地按
    keyword 做大小写不敏感子串过滤，让前端搜索真正生效。
    """
    level = (request.args.get("level") or "l0").lower()
    q = (request.args.get("q") or "").strip()
    try:
        limit = min(max(int(request.args.get("limit", "500")), 1), 500)
    except ValueError:
        limit = 500

    if level not in _LEVEL_MAP:
        return jsonify({"error": "invalid level"}), 400

    endpoint, extra = _LEVEL_MAP[level]
    payload = {**extra, "query": "*", "limit": limit}

    resp = http_post(f"{GATEWAY_BASE}/search/{endpoint}", payload, timeout=20)
    if resp is None:
        return jsonify({
            "level": level,
            "total": 0,
            "items": [],
            "gatewayReachable": False,
        })

    results = resp.get("results", "")
    items = _parse_conversations(results) if endpoint == "conversations" else _parse_memories(results)

    # L0 原始对话按时间倒序，最新记录在前；L1-L3 按 priority 倒序 + score 倒序
    if endpoint == "conversations":
        items.sort(key=lambda m: m.get("timestamp") or "", reverse=True)
    else:
        items.sort(key=lambda m: (m.get("priority") or 0, m.get("score") or 0), reverse=True)

    # 本地子串过滤（大小写不敏感）。在 content/scene/session/role/type 上匹配。
    if q:
        ql = q.lower()
        def _hit(m):
            for v in (m.get("content"), m.get("scene"), m.get("session"),
                      m.get("role"), m.get("type")):
                if v and ql in v.lower():
                    return True
            return False
        items = [m for m in items if _hit(m)]

    return jsonify({
        "level": level,
        "total": len(items),
        "items": items,
        "gatewayReachable": True,
    })
