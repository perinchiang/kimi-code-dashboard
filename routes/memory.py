"""Memory status API blueprint (L0-L3 via TencentDB Gateway)."""

import concurrent.futures
import re
import sqlite3
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import GATEWAY_BASE, log
from services.helpers import http_get, http_post

bp = Blueprint("memory", __name__)

L0_DB_PATH = Path.home() / ".memory-tencentdb" / "memory-tdai" / "vectors.db"
L0_PAGE_LIMIT = 500
_MEMORY_SUMMARY_CACHE = {"data": None, "at": 0.0}
_MEMORY_SUMMARY_CACHE_TTL = 30
_MEMORY_SUMMARY_CACHE_LOCK = threading.Lock()


def _read_l0_page(query: str, limit: int, before_timestamp: str = "", before_record_id: str = ""):
    """Read a stable, cursor-paginated L0 page from the local SQLite store."""
    if not L0_DB_PATH.is_file():
        return None

    try:
        db_uri = f"file:{L0_DB_PATH.as_posix()}?mode=ro"
        connection = sqlite3.connect(db_uri, uri=True)
        connection.row_factory = sqlite3.Row
    except (OSError, sqlite3.Error) as exc:
        log.warning("Unable to open L0 SQLite store: %s", exc)
        return None

    try:
        base_clauses = ["session_key = ?"]
        base_params = ["kimi-default"]
        if query:
            like = f"%{query}%"
            base_clauses.append(
                "(message_text LIKE ? OR session_key LIKE ? OR session_id LIKE ? OR role LIKE ?)"
            )
            base_params.extend([like, like, like, like])

        total_where = f"WHERE {' AND '.join(base_clauses)}" if base_clauses else ""
        total = connection.execute(
            f"SELECT COUNT(*) FROM l0_conversations {total_where}", base_params
        ).fetchone()[0]

        page_clauses = list(base_clauses)
        page_params = list(base_params)
        if before_timestamp and before_record_id:
            try:
                cursor_timestamp = int(before_timestamp)
            except ValueError:
                return None
            page_clauses.append("(timestamp < ? OR (timestamp = ? AND record_id < ?))")
            page_params.extend([cursor_timestamp, cursor_timestamp, before_record_id])

        page_where = f"WHERE {' AND '.join(page_clauses)}" if page_clauses else ""
        remaining = connection.execute(
            f"SELECT COUNT(*) FROM l0_conversations {page_where}", page_params
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT record_id, session_key, session_id, role, message_text, recorded_at, timestamp
            FROM l0_conversations
            {page_where}
            ORDER BY timestamp DESC, record_id DESC
            LIMIT ?
            """,
            [*page_params, limit],
        ).fetchall()
    except sqlite3.Error as exc:
        log.warning("Unable to read L0 SQLite store: %s", exc)
        return None
    finally:
        connection.close()

    items = [
        {
            "record_id": row["record_id"],
            "role": row["role"],
            "session": row["session_key"] or row["session_id"] or "",
            "timestamp": row["recorded_at"] or str(row["timestamp"]),
            "timestamp_value": row["timestamp"],
            "score": 0,
            "content": row["message_text"],
        }
        for row in rows
    ]
    last = rows[-1] if rows else None
    return {
        "items": items,
        "total": total,
        "returned": len(items),
        "has_more": remaining > len(items),
        "next_cursor": (
            {
                "timestamp": last["timestamp"],
                "record_id": last["record_id"],
            }
            if last and remaining > len(items)
            else None
        ),
    }


@bp.route("/api/memory")
def api_memory():
    now = time.time()
    if (
        _MEMORY_SUMMARY_CACHE["data"] is not None
        and now - _MEMORY_SUMMARY_CACHE["at"] <= _MEMORY_SUMMARY_CACHE_TTL
    ):
        return jsonify(_MEMORY_SUMMARY_CACHE["data"])

    with _MEMORY_SUMMARY_CACHE_LOCK:
        now = time.time()
        if (
            _MEMORY_SUMMARY_CACHE["data"] is not None
            and now - _MEMORY_SUMMARY_CACHE["at"] <= _MEMORY_SUMMARY_CACHE_TTL
        ):
            return jsonify(_MEMORY_SUMMARY_CACHE["data"])

        def count(path: str, payload: dict, parser) -> int:
            resp = http_post(f"{GATEWAY_BASE}{path}", payload, timeout=15)
            if resp is None:
                return -1
            return len(parser(resp.get("results", "")))

        local_l0 = _read_l0_page("", 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                "l1": executor.submit(count, "/search/memories", {"query": "*", "type": "episodic", "limit": 500}, _parse_memories),
                "l2": executor.submit(count, "/search/memories", {"query": "*", "type": "instruction", "limit": 500}, _parse_memories),
                "l3": executor.submit(count, "/search/memories", {"query": "*", "type": "persona", "limit": 500}, _parse_memories),
                "gatewayReachable": executor.submit(http_get, f"{GATEWAY_BASE}/health"),
            }
            if local_l0 is None:
                futures["l0"] = executor.submit(
                    count,
                    "/search/conversations",
                    {"query": "*", "limit": 500, "session_key": "kimi-default"},
                    _parse_conversations,
                )
            l1 = futures["l1"].result()
            l2 = futures["l2"].result()
            l3 = futures["l3"].result()
            gateway_reachable = futures["gatewayReachable"].result() is not None
            l0 = local_l0["total"] if local_l0 is not None else futures["l0"].result()

        data = {
            "l0": l0,
            "l1": l1,
            "l2": l2,
            "l3": l3,
            "gatewayReachable": gateway_reachable,
        }
        _MEMORY_SUMMARY_CACHE["data"] = data
        _MEMORY_SUMMARY_CACHE["at"] = time.time()
        return jsonify(data)


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
    """Return a page of memory items, using local pagination for L0."""
    level = (request.args.get("level") or "l0").lower()
    q = (request.args.get("q") or "").strip()
    try:
        limit = min(max(int(request.args.get("limit", str(L0_PAGE_LIMIT))), 1), L0_PAGE_LIMIT)
    except ValueError:
        limit = L0_PAGE_LIMIT

    if level not in _LEVEL_MAP:
        return jsonify({"error": "invalid level"}), 400

    if level == "l0":
        local_page = _read_l0_page(
            q,
            limit,
            request.args.get("before_timestamp", ""),
            request.args.get("before_record_id", ""),
        )
        if local_page is not None:
            return jsonify({
                "level": level,
                "gatewayReachable": True,
                "source": "local-sqlite",
                **local_page,
            })

    endpoint, extra = _LEVEL_MAP[level]
    payload = {**extra, "query": "*", "limit": limit}

    resp = http_post(f"{GATEWAY_BASE}/search/{endpoint}", payload, timeout=20)
    if resp is None:
        return jsonify({
            "level": level,
            "total": 0,
            "returned": 0,
            "has_more": False,
            "next_cursor": None,
            "items": [],
            "gatewayReachable": False,
        })

    results = resp.get("results", "")
    items = _parse_conversations(results) if endpoint == "conversations" else _parse_memories(results)

    # L0 原始对话按时间倒序，L1-L3 按 priority 倒序 + score 倒序
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
        "returned": len(items),
        "has_more": False,
        "next_cursor": None,
        "items": items,
        "gatewayReachable": True,
    })
