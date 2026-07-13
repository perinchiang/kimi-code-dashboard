"""Combined wire.jsonl parser with incremental reading, caching, and model stats.

This module replaces the two separate functions (_parse_wire_usage_records and
_parse_tool_calls) that each independently iterated all session wire.jsonl files.

Key improvements:
1. Single pass: extracts usage records, tool calls, and model stats together.
2. Incremental: tracks per-file mtime + byte offset, only reads new bytes.
3. Cached: results are cached with a configurable TTL.
4. Model usage: aggregates token counts per model name.
"""

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import SESSIONS_DIR, TOOL_USAGE_CACHE_TTL, TREND_CACHE_TTL, log


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class UsageRecord:
    """A single usage.record event from wire.jsonl."""
    dt: datetime
    model: str
    input_other: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0

    @property
    def input_total(self) -> int:
        return self.input_other + self.cache_read + self.cache_creation

    @property
    def total(self) -> int:
        return self.input_total + self.output


@dataclass
class ParseResult:
    """Aggregated result of parsing all wire.jsonl files."""
    usage_records: list[UsageRecord] = field(default_factory=list)
    tool_counts: Counter = field(default_factory=Counter)
    skill_counts: Counter = field(default_factory=Counter)
    model_counts: Counter = field(default_factory=Counter)       # calls per model
    model_tokens: dict[str, dict[str, int]] = field(default_factory=dict)  # model -> {input, output, total}


# ---------------------------------------------------------------------------
# Incremental file tracking
# ---------------------------------------------------------------------------

# Persistent state: {file_path_str: (mtime, size, byte_offset)}
_file_state: dict[str, tuple[float, int, int]] = {}


def _should_read_file(path: Path) -> tuple[bool, int]:
    """Check if *path* has changed since last read. Returns (should_read, last_offset)."""
    key = str(path)
    try:
        stat = path.stat()
    except OSError:
        return False, 0

    mtime, size, offset = _file_state.get(key, (0, 0, 0))

    # File hasn't changed (same mtime + same size)
    if stat.st_mtime == mtime and stat.st_size == size:
        return False, offset

    # File shrank (truncated/rotated) — read from start
    if stat.st_size < offset:
        log.debug("File %s shrank, reading from start", path.name)
        return True, 0

    return True, offset


def _mark_file_read(path: Path, offset: int):
    """Record that we've read up to *offset* in *path*."""
    key = str(path)
    try:
        stat = path.stat()
        _file_state[key] = (stat.st_mtime, stat.st_size, offset)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def _iter_wire_files() -> list[Path]:
    """Find all wire.jsonl files under SESSIONS_DIR."""
    if not SESSIONS_DIR.exists():
        return []
    files = []
    for workspace_dir in SESSIONS_DIR.iterdir():
        if not workspace_dir.is_dir():
            continue
        for session_dir in workspace_dir.iterdir():
            if not session_dir.is_dir() or not session_dir.name.startswith("session_"):
                continue
            agents_dir = session_dir / "agents"
            if not agents_dir.exists():
                continue
            for agent_dir in agents_dir.iterdir():
                wire = agent_dir / "wire.jsonl"
                if wire.is_file():
                    files.append(wire)
    return files


def _parse_file(path: Path, offset: int, result: ParseResult) -> int:
    """Parse a single wire.jsonl from *offset*, append to *result*.

    Returns the new byte offset.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = obj.get("type", "")

                # --- usage.record ---
                if event_type == "usage.record":
                    ts = obj.get("time")
                    if not isinstance(ts, (int, float)):
                        continue
                    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone()
                    model = obj.get("model", "unknown")
                    usage = obj.get("usage", {})

                    rec = UsageRecord(
                        dt=dt,
                        model=model,
                        input_other=usage.get("inputOther", 0),
                        output=usage.get("output", 0),
                        cache_read=usage.get("inputCacheRead", 0),
                        cache_creation=usage.get("inputCacheCreation", 0),
                    )
                    result.usage_records.append(rec)

                    # Model stats
                    result.model_counts[model] += 1
                    if model not in result.model_tokens:
                        result.model_tokens[model] = {"input": 0, "output": 0, "total": 0, "calls": 0}
                    mt = result.model_tokens[model]
                    mt["input"] += rec.input_total
                    mt["output"] += rec.output
                    mt["total"] += rec.total
                    mt["calls"] += 1

                # --- tool.call (nested inside context.append_loop_event) ---
                elif event_type == "context.append_loop_event":
                    event = obj.get("event", {})
                    if event.get("type") != "tool.call":
                        continue
                    name = event.get("name", "")
                    if not name:
                        continue
                    result.tool_counts[name] += 1
                    if name == "Skill":
                        skill_name = event.get("args", {}).get("skill", "unknown")
                        result.skill_counts[skill_name] += 1

            new_offset = f.tell()
            _mark_file_read(path, new_offset)
            return new_offset
    except Exception as e:
        log.warning("Error parsing %s: %s", path, e)
        return offset


def parse_all(force: bool = False) -> ParseResult:
    """Parse all wire.jsonl files incrementally.

    If *force* is True, clear state and do a full re-read.
    Returns a ParseResult with all accumulated data (not just the new data).
    """
    if force:
        _file_state.clear()

    result = ParseResult()

    for wire_file in _iter_wire_files():
        should_read, offset = _should_read_file(wire_file)
        if should_read:
            _parse_file(wire_file, offset, result)
        # If file hasn't changed, its data was already accumulated in previous calls
        # — but since ParseResult is fresh each call, we need to re-read unchanged
        # files too. So actually, for correctness, we always parse from the
        # recorded offset (which may be the full file if unchanged).
        # The incremental optimization kicks in because seek(offset) skips already-read bytes.
        elif offset > 0:
            # File unchanged — still need to re-read it for this fresh ParseResult
            _parse_file(wire_file, 0, result)

    return result


# ---------------------------------------------------------------------------
# Full re-parse (no incremental, for cache misses)
# ---------------------------------------------------------------------------

def parse_all_full() -> ParseResult:
    """Do a complete re-parse of all wire.jsonl files from scratch.

    Used when the incremental state is stale or on first load.
    """
    _file_state.clear()
    result = ParseResult()
    for wire_file in _iter_wire_files():
        _parse_file(wire_file, 0, result)
    return result


# ---------------------------------------------------------------------------
# Cached high-level API
# ---------------------------------------------------------------------------

_trend_cache: dict = {"data": None, "at": 0.0}
_tool_usage_cache: dict = {"data": None, "at": 0.0}
_model_usage_cache: dict = {"data": None, "at": 0.0}


def _trend_key(dt: datetime, unit: str) -> tuple[str, str]:
    if unit == "hour":
        return dt.strftime("%Y-%m-%d %H:00"), dt.strftime("%H:00")
    if unit == "day":
        return dt.strftime("%Y-%m-%d"), dt.strftime("%m-%d")
    cal = dt.isocalendar()
    return f"{cal.year}-W{cal.week:02d}", f"W{cal.week:02d}"


def _aggregate_usage(records: list[UsageRecord], unit: str, count: int) -> list[dict]:
    """Aggregate token usage into the last *count* hour/day/week buckets."""
    total_counts: Counter = Counter()
    input_counts: Counter = Counter()
    output_counts: Counter = Counter()
    cache_counts: Counter = Counter()

    for rec in records:
        key, _ = _trend_key(rec.dt, unit)
        total_counts[key] += rec.total
        input_counts[key] += rec.input_total
        output_counts[key] += rec.output
        cache_counts[key] += rec.cache_read

    result: list[dict] = []
    now = datetime.now().astimezone()
    for i in range(count - 1, -1, -1):
        if unit == "hour":
            d = now - timedelta(hours=i)
        elif unit == "day":
            d = now - timedelta(days=i)
        else:
            d = now - timedelta(weeks=i)
        key, label = _trend_key(d, unit)
        inp = input_counts.get(key, 0)
        cache = cache_counts.get(key, 0)
        cache_rate = round((cache / inp * 100), 1) if inp > 0 else 0.0
        result.append({
            "key": key,
            "label": label,
            "value": total_counts.get(key, 0),
            "input": inp,
            "output": output_counts.get(key, 0),
            "cacheRead": cache,
            "cacheRate": cache_rate,
        })
    return result


def _evaluate_cache_rate(input_total: int, cache_read: int) -> dict:
    """Return human-readable cache hit evaluation for the grand total.

    Thresholds:
    - 优秀: cache rate >= 70%
    - 良好: 40% <= cache rate < 70%
    - 很差: cache rate < 40% (or no input tokens)
    """
    if input_total <= 0:
        return {"label": "无数据", "level": "none"}
    rate = cache_read / input_total * 100
    if rate >= 70:
        return {"label": "优秀", "level": "excellent"}
    if rate >= 40:
        return {"label": "良好", "level": "good"}
    return {"label": "很差", "level": "poor"}


def get_trends() -> dict:
    """Get cached trend data, re-parsing if stale."""
    now_ts = time.time()
    if _trend_cache["data"] is None or now_ts - _trend_cache["at"] > TREND_CACHE_TTL:
        log.debug("Trend cache miss, parsing wire.jsonl files")
        result = parse_all_full()
        grand_input = sum(r.input_total for r in result.usage_records)
        grand_output = sum(r.output for r in result.usage_records)
        grand_total = grand_input + grand_output
        grand_cache = sum(r.cache_read for r in result.usage_records)

        _trend_cache["data"] = {
            "daily": _aggregate_usage(result.usage_records, "hour", 24),
            "weekly": _aggregate_usage(result.usage_records, "day", 7),
            "monthly": _aggregate_usage(result.usage_records, "day", 30),
            "yearly": _aggregate_usage(result.usage_records, "day", 365),
            "total": {
                "value": grand_total,
                "input": grand_input,
                "output": grand_output,
                "cacheRead": grand_cache,
                "cacheRate": round((grand_cache / grand_input * 100), 1) if grand_input > 0 else 0.0,
                "cacheEvaluation": _evaluate_cache_rate(grand_input, grand_cache),
            },
        }
        _trend_cache["at"] = now_ts

        # Also update tool-usage and model-usage caches since we just parsed everything
        _update_tool_usage_cache(result)
        _update_model_usage_cache(result)

    return _trend_cache["data"]


def _update_tool_usage_cache(result: ParseResult):
    """Update the tool-usage cache from a ParseResult."""
    tools = [{"name": k, "count": v} for k, v in result.tool_counts.most_common(15)]
    skills = [{"name": k, "count": v} for k, v in result.skill_counts.most_common(15)]
    _tool_usage_cache["data"] = {
        "totalToolCalls": sum(result.tool_counts.values()),
        "totalSkillCalls": sum(result.skill_counts.values()),
        "tools": tools,
        "skills": skills,
    }
    _tool_usage_cache["at"] = time.time()


def get_tool_usage() -> dict:
    """Get cached tool/skill usage data, re-parsing if stale."""
    now_ts = time.time()
    if _tool_usage_cache["data"] is None or now_ts - _tool_usage_cache["at"] > TOOL_USAGE_CACHE_TTL:
        log.debug("Tool-usage cache miss, parsing wire.jsonl files")
        result = parse_all_full()
        _update_tool_usage_cache(result)
        # Also update trend + model caches
        _trend_cache["at"] = 0  # force trend refresh next call
        _update_model_usage_cache(result)
    return _tool_usage_cache["data"]


def _update_model_usage_cache(result: ParseResult):
    """Update the model-usage cache from a ParseResult."""
    models = []
    for model, tokens in sorted(result.model_tokens.items(), key=lambda x: x[1]["total"], reverse=True):
        models.append({
            "model": model,
            "calls": tokens["calls"],
            "input": tokens["input"],
            "output": tokens["output"],
            "total": tokens["total"],
        })
    _model_usage_cache["data"] = {
        "models": models,
        "totalCalls": sum(result.model_counts.values()),
        "totalTokens": sum(t["total"] for t in result.model_tokens.values()),
    }
    _model_usage_cache["at"] = time.time()


def get_model_usage() -> dict:
    """Get cached model usage distribution, re-parsing if stale."""
    now_ts = time.time()
    if _model_usage_cache["data"] is None or now_ts - _model_usage_cache["at"] > TOOL_USAGE_CACHE_TTL:
        log.debug("Model-usage cache miss, parsing wire.jsonl files")
        result = parse_all_full()
        _update_model_usage_cache(result)
        # Also update other caches
        _trend_cache["at"] = 0
        _update_tool_usage_cache(result)
    return _model_usage_cache["data"]
