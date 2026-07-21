"""Local Kimi session discovery and Dashboard-owned title generation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import tomllib
import urllib.error
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from config import APP_DIR, KIMI_CONFIG, SESSIONS_DIR, log
from services.helpers import atomic_write_text, safe_json_load

SESSION_TITLE_DIR = APP_DIR / "session-titles"
_MAX_TITLE_INPUT_CHARS = 12000
_MAX_SUMMARY_CHARS = 6000
_MAX_MESSAGE_CHARS = 1800
_MAX_TITLE_CHARS = 200
_SESSION_ID_RE = re.compile(r"^session_[A-Za-z0-9_-]+$")
_SECRET_RE = re.compile(
    r"(?i)(?:api[_-]?key|token|password|secret|authorization)\s*[:=]\s*[^\s,;]+|"
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,})\b"
)
_META_BLOCK_RE = re.compile(
    r"<(?:(?:system)(?:-reminder)?|hook_result|kimi-skill-loaded)\b[^>]*>.*?</(?:system|system-reminder|hook_result|kimi-skill-loaded)>",
    re.IGNORECASE | re.DOTALL,
)
_SKILL_PREFIX_RE = re.compile(
    r"(?is)^skill\s+tool\s+loaded\s+instructions\s+for\s+this\s+request\..*?(?=<kimi-skill-loaded\b)"
)


class TitleProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int = 0, retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="session-title")
_jobs_lock = threading.RLock()
_jobs: dict[str, dict[str, Any]] = {}
_futures: dict[str, Future] = {}
_scan_cache_lock = threading.RLock()
_scan_cache: dict[str, tuple[tuple[int, int], tuple[int, int], dict[str, Any]]] = {}
_auto_attempts: dict[str, str] = {}
_watcher_lock = threading.Lock()
_watcher_thread: threading.Thread | None = None
_watcher_process_lock_handle = None
_TITLE_WATCH_INTERVAL = 5


def is_safe_session_id(session_id: str) -> bool:
    """Return whether a session id is safe to use as a sidecar filename."""
    return bool(isinstance(session_id, str) and _SESSION_ID_RE.fullmatch(session_id))


def _session_dirs() -> list[Path]:
    if not SESSIONS_DIR.is_dir():
        return []
    result = []
    try:
        for workspace_dir in SESSIONS_DIR.iterdir():
            if not workspace_dir.is_dir():
                continue
            for session_dir in workspace_dir.iterdir():
                if session_dir.is_dir() and is_safe_session_id(session_dir.name):
                    result.append(session_dir)
    except OSError as exc:
        log.warning("Failed to scan Kimi sessions: %s", exc)
    return result


def _find_session_dir(session_id: str) -> Path | None:
    if not is_safe_session_id(session_id):
        return None
    for session_dir in _session_dirs():
        if session_dir.name == session_id:
            return session_dir
    return None


def _file_signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return 0, 0


def _sidecar_path(session_id: str) -> Path:
    if not is_safe_session_id(session_id):
        raise ValueError("session_id 无效")
    return SESSION_TITLE_DIR / (session_id + ".json")


def _load_sidecar(session_id: str) -> dict[str, Any]:
    data = safe_json_load(_sidecar_path(session_id))
    return data if isinstance(data, dict) else {}


def _save_sidecar(session_id: str, data: dict[str, Any]) -> None:
    path = _sidecar_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _write_kimi_title(session_id: str, title: str) -> None:
    """Update Kimi's native session title without touching transcript data."""
    session_dir = _find_session_dir(session_id)
    if session_dir is None:
        raise RuntimeError("Kimi 会话不存在")
    state_path = session_dir / "state.json"
    state = safe_json_load(state_path)
    if not isinstance(state, dict):
        raise RuntimeError("Kimi 会话状态无法读取")
    state["title"] = title
    if "isCustomTitle" in state:
        state["isCustomTitle"] = True
    atomic_write_text(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _clean_text(value: Any, limit: int = _MAX_MESSAGE_CHARS) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("thinking") or ""
                if isinstance(text, str):
                    parts.append(text)
        text = "\n".join(parts)
    elif value is None:
        return ""
    else:
        text = str(value)
    text = _SKILL_PREFIX_RE.sub("", text)
    text = _META_BLOCK_RE.sub(" ", text)
    text = _SECRET_RE.sub("[redacted]", text)
    return " ".join(text.split())[:limit].strip()


def _event_text(event: dict[str, Any]) -> str:
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    return _clean_text(message.get("content") or event.get("input"))


def _scan_wire(session_dir: Path) -> dict[str, Any]:
    """Extract compact session facts without retaining the transcript."""
    compactions: list[dict[str, Any]] = []
    recent_messages: list[dict[str, str]] = []
    first_prompt = ""
    context_user_count = 0
    prompt_user_count = 0
    compaction_user_count = 0
    last_message_role = ""
    wire_files = sorted((session_dir / "agents").glob("*/wire.jsonl")) if (session_dir / "agents").is_dir() else []

    def append_recent_message(role: str, text: str) -> None:
        if text and role in {"user", "assistant"}:
            recent_messages.append({"role": role, "text": text})
            if len(recent_messages) > 8:
                recent_messages.pop(0)

    for wire_path in wire_files:
        assistant_parts: list[str] = []
        try:
            with wire_path.open("r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    try:
                        event = json.loads(raw_line)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    event_type = event.get("type") or ""
                    if event_type == "context.apply_compaction":
                        summary = _clean_text(event.get("summary"), _MAX_SUMMARY_CHARS)
                        context_summary = _clean_text(event.get("contextSummary"), _MAX_SUMMARY_CHARS)
                        if summary or context_summary:
                            compactions.append({
                                "summary": summary,
                                "context_summary": context_summary,
                                "compacted_count": event.get("compactedCount"),
                                "tokens_before": event.get("tokensBefore"),
                                "tokens_after": event.get("tokensAfter"),
                                "kept_user_message_count": event.get("keptUserMessageCount"),
                                "time": event.get("time"),
                            })
                            try:
                                compaction_user_count = max(
                                    compaction_user_count,
                                    int(event.get("keptUserMessageCount") or 0),
                                )
                            except (TypeError, ValueError):
                                pass
                    elif event_type == "context.append_message":
                        message = event.get("message") if isinstance(event.get("message"), dict) else {}
                        role = str(message.get("role") or "")
                        text = _clean_text(message.get("content"))
                        if role == "user" and text:
                            context_user_count += 1
                        if text:
                            last_message_role = role
                        append_recent_message(role, text)
                    elif event_type == "context.append_loop_event":
                        loop_event = event.get("event") if isinstance(event.get("event"), dict) else {}
                        loop_type = loop_event.get("type") or ""
                        if loop_type == "step.begin":
                            assistant_parts = []
                        elif loop_type == "content.part":
                            part = loop_event.get("part") if isinstance(loop_event.get("part"), dict) else {}
                            if part.get("type") == "text":
                                text = _clean_text(part.get("text"))
                                if text:
                                    assistant_parts.append(text)
                        elif loop_type == "step.end":
                            finish_reason = str(loop_event.get("finishReason") or "").lower()
                            if finish_reason in {"end_turn", "stop"}:
                                assistant_text = _clean_text("\n".join(assistant_parts), _MAX_MESSAGE_CHARS)
                                if assistant_text:
                                    append_recent_message("assistant", assistant_text)
                                    last_message_role = "assistant"
                            assistant_parts = []
                    elif event_type == "turn.prompt":
                        origin = event.get("origin") if isinstance(event.get("origin"), dict) else {}
                        prompt_text = _event_text(event)
                        if origin.get("kind", "user") == "user" and prompt_text:
                            prompt_user_count += 1
                        if prompt_text and not first_prompt:
                            first_prompt = prompt_text

        except OSError:
            continue

    user_message_count = max(context_user_count, prompt_user_count, compaction_user_count)
    compactions.sort(key=lambda item: _sort_timestamp(item.get("time")))
    latest_compaction = compactions[-1] if compactions else None
    return {
        "user_message_count": user_message_count,
        "first_prompt": first_prompt,
        "recent_messages": recent_messages,
        "last_message_role": last_message_role,
        "compaction_count": len(compactions),
        "last_compaction": latest_compaction,
        "last_compaction_at": latest_compaction.get("time") if latest_compaction else None,
    }


def _read_state(session_dir: Path) -> dict[str, Any]:
    state = safe_json_load(session_dir / "state.json")
    return state if isinstance(state, dict) else {}


def _workspace_name(session_dir: Path) -> str:
    try:
        return str(session_dir.parent.name)
    except Exception:
        return ""


def _fallback_title(state: dict[str, Any], wire: dict[str, Any]) -> str:
    original = _clean_text(state.get("title"), _MAX_TITLE_CHARS)
    if original and original.lower() not in {"untitled", "new chat"}:
        return original
    prompt = wire.get("first_prompt") or ""
    if prompt:
        return prompt[:80].rstrip() + ("…" if len(prompt) > 80 else "")
    return "未命名会话"


def _source_context(wire: dict[str, Any]) -> tuple[str, str]:
    latest = wire.get("last_compaction") or {}
    context_summary = latest.get("context_summary") or ""
    summary = latest.get("summary") or ""
    if context_summary:
        return "contextSummary", context_summary[:_MAX_SUMMARY_CHARS]
    if summary:
        return "summary", summary[:_MAX_SUMMARY_CHARS]
    messages = wire.get("recent_messages") or []
    if messages:
        lines = [f"{item.get('role', 'message')}: {item.get('text', '')}" for item in messages[-6:]]
        return "recent_messages", "\n".join(lines)[:_MAX_SUMMARY_CHARS]
    if wire.get("first_prompt"):
        return "first_prompt", str(wire["first_prompt"])[:_MAX_SUMMARY_CHARS]
    return "none", ""


def _fingerprint(context: str, wire: dict[str, Any]) -> str:
    payload = json.dumps({
        "context": context,
        "message_count": wire.get("user_message_count", 0),
        "last_compaction_at": wire.get("last_compaction_at"),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _scan_session(session_dir: Path) -> dict[str, Any]:
    session_id = session_dir.name
    state_path = session_dir / "state.json"
    wire_paths = list((session_dir / "agents").glob("*/wire.jsonl")) if (session_dir / "agents").is_dir() else []
    state_sig = _file_signature(state_path)
    wire_sig = (0, 0)
    for wire_path in wire_paths:
        sig = _file_signature(wire_path)
        wire_sig = (max(wire_sig[0], sig[0]), wire_sig[1] + sig[1])
    with _scan_cache_lock:
        cached = _scan_cache.get(session_id)
        if cached and cached[0] == state_sig and cached[1] == wire_sig:
            record = dict(cached[2])
            sidecar = _load_sidecar(session_id)
            if sidecar.get("title"):
                record["title"] = _clean_text(sidecar.get("title"), _MAX_TITLE_CHARS)
                record["title_source"] = "sidecar"
            record["manual_title"] = bool(sidecar.get("manual"))
            record["title_job"] = _job_status(session_id)
            record["title_job_error"] = _job_error(session_id)
            return record

    state = _read_state(session_dir)
    wire = _scan_wire(session_dir)
    source_kind, source_context = _source_context(wire)
    sidecar = _load_sidecar(session_id)
    record = {
        "session_id": session_id,
        "workspace_name": _workspace_name(session_dir),
        "workspace": state.get("workDir") or state.get("cwd") or "",
        "original_title": _clean_text(state.get("title"), _MAX_TITLE_CHARS),
        "kimi_custom_title": bool(state.get("isCustomTitle")),
        "title": _clean_text(sidecar.get("title"), _MAX_TITLE_CHARS) or _fallback_title(state, wire),
        "title_source": "sidecar" if sidecar.get("title") else ("kimi" if state.get("title") else "fallback"),
        "manual_title": bool(sidecar.get("manual")),
        "created_at": state.get("createdAt"),
        "updated_at": state.get("updatedAt") or state.get("createdAt"),
        "archived": bool(state.get("archived")),
        "user_message_count": wire.get("user_message_count", 0),
        "last_message_role": wire.get("last_message_role", ""),
        "compaction_count": wire.get("compaction_count", 0),
        "last_compaction_at": wire.get("last_compaction_at"),
        "source_kind": source_kind,
        "source_fingerprint": _fingerprint(source_context, wire),
        "title_job": _job_status(session_id),
        "title_job_error": _job_error(session_id),
        "_source_context": source_context,
        "_wire": wire,
    }
    with _scan_cache_lock:
        _scan_cache[session_id] = (state_sig, wire_sig, dict(record))
    return record


def _sort_timestamp(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def list_sessions(limit: int = 50, offset: int = 0, archived: str = "active") -> dict[str, Any]:
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    if archived not in {"active", "archived", "all"}:
        raise ValueError("archived 必须是 active、archived 或 all")
    records = [_public_record(_scan_session(path), detail=False) for path in _session_dirs()]
    if archived == "active":
        records = [record for record in records if not record.get("archived")]
    elif archived == "archived":
        records = [record for record in records if record.get("archived")]
    records.sort(key=lambda item: _sort_timestamp(item.get("updated_at")), reverse=True)
    return {
        "sessions": records[offset:offset + limit],
        "total": len(records),
        "offset": offset,
        "limit": limit,
        "archived": archived,
    }


def restore_session(session_id: str) -> dict[str, Any] | None:
    """Restore an archived session by changing only its state flag."""
    if not is_safe_session_id(session_id):
        raise ValueError("session_id 无效")
    session_dir = _find_session_dir(session_id)
    if session_dir is None:
        return None
    state_path = session_dir / "state.json"
    state = safe_json_load(state_path)
    if not isinstance(state, dict):
        raise RuntimeError("Kimi 会话状态无法读取")
    changed = bool(state.get("archived"))
    if changed:
        state["archived"] = False
        atomic_write_text(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        _invalidate_scan(session_id)
    return {
        "changed": changed,
        "session": get_session(session_id, detail=False),
    }


def get_session(session_id: str, detail: bool = True) -> dict[str, Any] | None:
    if not is_safe_session_id(session_id):
        return None
    for session_dir in _session_dirs():
        if session_dir.name == session_id:
            return _public_record(_scan_session(session_dir), detail=detail)
    return None


def _public_record(record: dict[str, Any], detail: bool) -> dict[str, Any]:
    result = {key: value for key, value in record.items() if not key.startswith("_")}
    if detail:
        result["source_context"] = record.get("_source_context", "")
        latest = (record.get("_wire") or {}).get("last_compaction")
        result["last_compaction"] = latest
    return result


def set_manual_title(session_id: str, title: str) -> dict[str, Any] | None:
    record = get_session(session_id, detail=False)
    if record is None:
        return None
    title = _clean_text(title, _MAX_TITLE_CHARS)
    sidecar = _load_sidecar(session_id)
    if title:
        sidecar.update({
            "session_id": session_id,
            "title": title,
            "source": "manual",
            "manual": True,
            "generated_at": time.time(),
            "source_fingerprint": record["source_fingerprint"],
        })
    else:
        sidecar.pop("title", None)
        sidecar.update({"session_id": session_id, "source": "auto", "manual": False, "generated_at": time.time()})
    _save_sidecar(session_id, sidecar)
    _invalidate_scan(session_id)
    return get_session(session_id, detail=False)


def _invalidate_scan(session_id: str) -> None:
    with _scan_cache_lock:
        _scan_cache.pop(session_id, None)


def _job_status(session_id: str) -> str:
    with _jobs_lock:
        return str((_jobs.get(session_id) or {}).get("status", "idle"))


def _job_error(session_id: str) -> str:
    with _jobs_lock:
        return str((_jobs.get(session_id) or {}).get("error", "") or "")


def _set_job(session_id: str, status: str, **extra: Any) -> None:
    with _jobs_lock:
        item = _jobs.setdefault(session_id, {})
        item.update({"status": status, **extra})


def _load_kimi_config() -> dict[str, Any]:
    if not KIMI_CONFIG.exists():
        raise RuntimeError("未找到 Kimi Code config.toml")
    try:
        cfg = tomllib.loads(KIMI_CONFIG.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError("Kimi Code config.toml 无法读取") from exc
    return cfg if isinstance(cfg, dict) else {}


def get_configured_model_aliases() -> set[str]:
    """Return model aliases currently configured in Kimi Code."""
    cfg = _load_kimi_config()
    models = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
    return {str(alias).strip() for alias in models if str(alias).strip()}


def validate_title_model(model_alias: str) -> str:
    """Validate a Dashboard title model alias, allowing empty for Kimi default."""
    model_alias = str(model_alias or "").strip()
    if model_alias and model_alias not in get_configured_model_aliases():
        raise ValueError(f"标题模型 '{model_alias}' 未在 Kimi Code 中配置")
    return model_alias


def _load_llm_config(selected_model: str = "") -> tuple[str, str, str, str, dict[str, str]]:
    cfg = _load_kimi_config()
    models = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
    configured_model = str(selected_model or "").strip()
    if not configured_model:
        try:
            from config import load_dashboard_config
            configured_model = str(
                (load_dashboard_config().get("session_titles") or {}).get("model") or ""
            ).strip()
        except Exception:
            configured_model = ""
    model_alias = configured_model or str(cfg.get("default_model") or "").strip()
    model_cfg = models.get(model_alias) if isinstance(models.get(model_alias), dict) else {}
    model_id = str(model_cfg.get("model") or model_alias).strip()
    provider_id = str(model_cfg.get("provider") or "").strip()
    providers = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    provider_cfg = providers.get(provider_id) if isinstance(providers.get(provider_id), dict) else {}
    provider_type = str(provider_cfg.get("type") or "openai").strip().lower()
    base_url = str(provider_cfg.get("base_url") or "").strip().rstrip("/")
    api_key = str(provider_cfg.get("api_key") or "").strip()
    headers = provider_cfg.get("custom_headers") if isinstance(provider_cfg.get("custom_headers"), dict) else {}
    if not base_url and provider_type == "kimi":
        base_url = "https://api.kimi.com/coding/v1"
    if not model_id or not base_url:
        raise RuntimeError("默认模型或 Provider Base URL 未配置")
    return provider_type, model_id, base_url, api_key, {str(k): str(v) for k, v in headers.items()}


def _generate_title_with_llm(context: str, max_title_length: int = 80) -> str:
    provider_type, model_id, base_url, api_key, custom_headers = _load_llm_config()
    if provider_type not in {"openai", "openai_legacy", "kimi", "openai_responses"}:
        raise RuntimeError(f"暂不支持 Provider 类型: {provider_type}")
    prompt = context[:_MAX_TITLE_INPUT_CHARS]
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "为这段会话生成一个简短、准确的标题。只输出标题本身，不要引号、Markdown、标点解释或换行。中文不超过 20 个字，英文使用 4-8 个词。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 256,
    }
    if "deepseek" in model_id.lower():
        payload["thinking"] = {"type": "disabled"}
    log.debug(
        "Session title provider request: provider_type=%s model=%s context_chars=%d",
        provider_type,
        model_id,
        len(prompt),
    )
    headers = {"Content-Type": "application/json", "Accept": "application/json", **custom_headers}
    if api_key:
        headers.setdefault("Authorization", f"Bearer {api_key}")
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        retry_after = None
        try:
            retry_after = float(exc.headers.get("Retry-After")) if exc.headers.get("Retry-After") else None
        except (TypeError, ValueError):
            pass
        raise TitleProviderError(
            f"Provider 返回 HTTP {exc.code}",
            status_code=exc.code,
            retry_after=retry_after,
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("无法连接标题生成 Provider") from exc
    choices = body.get("choices") if isinstance(body, dict) else None
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
    title = _clean_text(message.get("content"), max_title_length)
    title = title.strip(" \t\r\n\"'“”‘’`#*。！!：:;")
    if not title:
        raise RuntimeError("Provider 未返回有效标题")
    return title[:max_title_length].rstrip()


def _is_manual_kimi_title(record: dict[str, Any], sidecar: dict[str, Any]) -> bool:
    """Treat native custom titles as manual unless this sidecar wrote them."""
    return bool(record.get("kimi_custom_title")) and not (
        sidecar.get("source") == "llm"
        and sidecar.get("title")
        and sidecar.get("title") == record.get("original_title")
    )


def _generate_title_with_retry(
    context: str,
    max_title_length: int,
    session_id: str,
    source: str,
    max_attempts: int = 3,
) -> str:
    for attempt in range(1, max_attempts + 1):
        try:
            return _generate_title_with_llm(context, max_title_length)
        except TitleProviderError as exc:
            if exc.status_code != 429 or attempt >= max_attempts:
                raise
            delay = exc.retry_after if exc.retry_after is not None else 5 * (2 ** (attempt - 1))
            delay = max(1.0, min(60.0, delay))
            log.warning(
                "Session title Provider HTTP 429; retrying session=%s source=%s attempt=%d/%d delay=%.1fs",
                session_id,
                source,
                attempt + 1,
                max_attempts,
                delay,
            )
            _set_job(session_id, "running", source=source, retry_attempt=attempt, retry_in=delay)
            time.sleep(delay)
    raise RuntimeError("标题生成重试失败")


def _run_title_job(session_id: str, source_fingerprint: str, max_title_length: int, source: str) -> None:
    try:
        record = get_session(session_id, detail=True)
        if not record:
            raise RuntimeError("会话不存在")
        sidecar = _load_sidecar(session_id)
        if sidecar.get("manual") or _is_manual_kimi_title(record, sidecar):
            _set_job(session_id, "skipped", source=source, finished_at=time.time())
            return
        if record.get("source_fingerprint") != source_fingerprint:
            source_fingerprint = record.get("source_fingerprint") or source_fingerprint
        context = record.get("source_context") or record.get("original_title") or ""
        log.info(
            "Session title generation started: session=%s source=%s context_chars=%d",
            session_id,
            source,
            len(context),
        )
        title = _generate_title_with_retry(context, max_title_length, session_id, source)
        record = get_session(session_id, detail=True)
        sidecar = _load_sidecar(session_id)
        if not record:
            raise RuntimeError("会话不存在")
        if sidecar.get("manual") or _is_manual_kimi_title(record, sidecar):
            _set_job(session_id, "skipped", source=source, finished_at=time.time())
            return
        _write_kimi_title(session_id, title)
        sidecar.update({
            "session_id": session_id,
            "title": title,
            "source": "llm",
            "manual": False,
            "generated_at": time.time(),
            "source_message_count": record.get("user_message_count", 0),
            "source_fingerprint": source_fingerprint,
        })
        _save_sidecar(session_id, sidecar)
        _invalidate_scan(session_id)
        _set_job(session_id, "ready", source=source, finished_at=time.time(), title=title)
    except Exception as exc:
        error = _SECRET_RE.sub("[redacted]", str(exc)).strip()
        error = error[:300] or type(exc).__name__
        log.warning("Session title generation failed for %s source=%s: %s", session_id, source, error)
        _set_job(session_id, "error", source=source, finished_at=time.time(), error=error)


def queue_title_generation(
    session_id: str,
    max_title_length: int = 80,
    source: str = "manual",
) -> dict[str, Any] | None:
    record = get_session(session_id, detail=True)
    if record is None:
        return None
    with _jobs_lock:
        current = _jobs.get(session_id) or {}
        if current.get("status") in {"queued", "running"}:
            return {"session_id": session_id, "status": current["status"]}
        if not record.get("source_context"):
            _set_job(session_id, "error", source=source, error="没有可用于标题生成的会话摘要")
            return {"session_id": session_id, "status": "error", "error": "没有可用于标题生成的会话摘要"}
        source_fingerprint = record.get("source_fingerprint") or ""
        _set_job(session_id, "queued", source=source, queued_at=time.time())
        future = _executor.submit(
            _run_title_job,
            session_id,
            source_fingerprint,
            max(20, min(int(max_title_length), _MAX_TITLE_CHARS)),
            source,
        )
        _futures[session_id] = future
        if not future.done():
            _set_job(session_id, "running", source=source, started_at=time.time())
    return {"session_id": session_id, "status": "running"}


def get_title_settings() -> dict[str, Any]:
    from config import load_dashboard_config
    return load_dashboard_config().get("session_titles", {})


def maybe_auto_queue(record: dict[str, Any]) -> None:
    settings = get_title_settings()
    if not settings.get("auto_generate"):
        return
    if record.get("last_message_role") != "assistant":
        return
    count = int(record.get("user_message_count") or 0)
    if count < 1:
        return
    try:
        interval = max(0, min(100, int(settings.get("every_exchanges", 10))))
    except (TypeError, ValueError):
        interval = 10
    if count != 1 and (interval == 0 or count % interval):
        return

    session_id = record["session_id"]
    sidecar = _load_sidecar(session_id)
    if sidecar.get("manual") or _is_manual_kimi_title(record, sidecar):
        return
    if sidecar.get("source_fingerprint") == record.get("source_fingerprint"):
        return
    if (
        sidecar.get("source") == "llm"
        and sidecar.get("title")
        and record.get("original_title")
        and record.get("original_title") != sidecar.get("title")
    ):
        return

    fingerprint = record.get("source_fingerprint") or ""
    with _jobs_lock:
        if _auto_attempts.get(session_id) == fingerprint:
            return
        _auto_attempts[session_id] = fingerprint
    queue_title_generation(session_id, int(settings.get("max_title_length", 80)), source="auto")


def _watch_signature(session_dir: Path) -> tuple[tuple[int, int], tuple[int, int]]:
    state_sig = _file_signature(session_dir / "state.json")
    wire_sig = (0, 0)
    agents_dir = session_dir / "agents"
    if agents_dir.is_dir():
        for wire_path in agents_dir.glob("*/wire.jsonl"):
            sig = _file_signature(wire_path)
            wire_sig = (max(wire_sig[0], sig[0]), wire_sig[1] + sig[1])
    return state_sig, wire_sig


def _watcher_signatures(session_dirs: list[Path]) -> dict[str, tuple[tuple[int, int], tuple[int, int]]]:
    return {session_dir.name: _watch_signature(session_dir) for session_dir in session_dirs}


def _watcher_changes(
    previous: dict[str, tuple[tuple[int, int], tuple[int, int]]],
    session_dirs: list[Path],
) -> tuple[dict[str, tuple[tuple[int, int], tuple[int, int]]], list[Path]]:
    current = _watcher_signatures(session_dirs)
    changed = [session_dir for session_dir in session_dirs if previous.get(session_dir.name) != current[session_dir.name]]
    return current, changed


def _title_watcher_loop() -> None:
    # Establish a baseline without renaming sessions that predate this process.
    signatures = _watcher_signatures(_session_dirs())
    while True:
        try:
            signatures, changed_sessions = _watcher_changes(signatures, _session_dirs())
            for session_dir in changed_sessions:
                maybe_auto_queue(_scan_session(session_dir))
        except Exception as exc:
            log.warning("Automatic session title scan failed: %s", type(exc).__name__)
        time.sleep(_TITLE_WATCH_INTERVAL)


def _acquire_watcher_process_lock() -> bool:
    """Allow only one Dashboard process to run the title watcher."""
    global _watcher_process_lock_handle
    if _watcher_process_lock_handle is not None:
        return True
    lock_path = SESSION_TITLE_DIR / ".watcher.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    try:
        handle = lock_path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ImportError):
        if handle is not None:
            handle.close()
        return False
    _watcher_process_lock_handle = handle
    return True


def start_title_watcher() -> None:
    """Start the process-local watcher used for automatic title generation."""
    global _watcher_thread
    with _watcher_lock:
        if _watcher_thread and _watcher_thread.is_alive():
            return
        if not _acquire_watcher_process_lock():
            log.info("Session title watcher is already active in another Dashboard process")
            return
        _watcher_thread = threading.Thread(
            target=_title_watcher_loop,
            name="session-title-watcher",
            daemon=True,
        )
        _watcher_thread.start()
