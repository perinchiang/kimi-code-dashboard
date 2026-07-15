"""Combined wire.jsonl parser with caching and model stats.

This module replaces the two separate functions (_parse_wire_usage_records and
_parse_tool_calls) that each independently iterated all session wire.jsonl files.

Key improvements:
1. Single pass: extracts usage records, tool calls, and model stats together.
2. Cached: results are cached with a configurable TTL (60s).
3. Model usage: aggregates token counts per model name.
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
    mcp_counts: Counter = field(default_factory=Counter)         # calls per MCP server
    model_counts: Counter = field(default_factory=Counter)       # calls per model
    model_tokens: dict[str, dict[str, int]] = field(default_factory=dict)  # model -> {input, output, total}
    # Time-windowed copies (keyed by window label: "24h" / "7d" / "30d")
    tool_counts_by_window: dict = field(default_factory=lambda: {"24h": Counter(), "7d": Counter(), "30d": Counter()})
    skill_counts_by_window: dict = field(default_factory=lambda: {"24h": Counter(), "7d": Counter(), "30d": Counter()})
    mcp_counts_by_window: dict = field(default_factory=lambda: {"24h": Counter(), "7d": Counter(), "30d": Counter()})
    model_tokens_by_window: dict = field(default_factory=lambda: {"24h": {}, "7d": {}, "30d": {}})
    # Time-series buckets for model usage charts
    model_tokens_by_day: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)   # day -> model -> stats
    model_tokens_by_week: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)  # week -> model -> stats


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def _iter_wire_files() -> list[Path]:
    """Find all wire.jsonl files under SESSIONS_DIR."""
    if not SESSIONS_DIR.exists():
        return []
    files = []
    try:
        workspace_iter = list(SESSIONS_DIR.iterdir())
    except OSError as e:
        log.warning("Failed to iterate sessions dir: %s", e)
        return files
    for workspace_dir in workspace_iter:
        if not workspace_dir.is_dir():
            continue
        try:
            session_iter = list(workspace_dir.iterdir())
        except OSError as e:
            log.warning("Failed to iterate workspace dir %s: %s", workspace_dir, e)
            continue
        for session_dir in session_iter:
            if not session_dir.is_dir() or not session_dir.name.startswith("session_"):
                continue
            agents_dir = session_dir / "agents"
            if not agents_dir.exists():
                continue
            try:
                agent_iter = list(agents_dir.iterdir())
            except OSError as e:
                log.warning("Failed to iterate agents dir %s: %s", agents_dir, e)
                continue
            for agent_dir in agent_iter:
                wire = agent_dir / "wire.jsonl"
                if wire.is_file():
                    files.append(wire)
    return files


def _parse_file(path: Path, offset: int, result: ParseResult) -> int:
    """Parse a single wire.jsonl from *offset*, append to *result*.

    Returns the new byte offset.
    """
    now = datetime.now().astimezone()
    # Window thresholds (as timedelta)
    win_24h = now - timedelta(hours=24)
    win_7d = now - timedelta(days=7)
    win_30d = now - timedelta(days=30)

    def _windows_for(dt):
        """Return list of window labels the dt falls into."""
        wins = []
        if dt >= win_24h:
            wins.append("24h")
        if dt >= win_7d:
            wins.append("7d")
        if dt >= win_30d:
            wins.append("30d")
        return wins

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

                    # Model stats (all-time)
                    result.model_counts[model] += 1
                    if model not in result.model_tokens:
                        result.model_tokens[model] = {"input": 0, "output": 0, "total": 0, "calls": 0}
                    mt = result.model_tokens[model]
                    mt["input"] += rec.input_total
                    mt["output"] += rec.output
                    mt["total"] += rec.total
                    mt["calls"] += 1

                    # Time-windowed model stats
                    for w in _windows_for(dt):
                        wm = result.model_tokens_by_window[w]
                        if model not in wm:
                            wm[model] = {"input": 0, "output": 0, "total": 0, "calls": 0}
                        wmt = wm[model]
                        wmt["input"] += rec.input_total
                        wmt["output"] += rec.output
                        wmt["total"] += rec.total
                        wmt["calls"] += 1

                    # Day / week buckets for model trend charts
                    day_key = dt.strftime("%Y-%m-%d")
                    week_key = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
                    for key, bucket in ((day_key, result.model_tokens_by_day), (week_key, result.model_tokens_by_week)):
                        if key not in bucket:
                            bucket[key] = {}
                        if model not in bucket[key]:
                            bucket[key][model] = {"input": 0, "output": 0, "total": 0, "calls": 0}
                        bmt = bucket[key][model]
                        bmt["input"] += rec.input_total
                        bmt["output"] += rec.output
                        bmt["total"] += rec.total
                        bmt["calls"] += 1

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
                    elif name.startswith("mcp__"):
                        # MCP tool names: mcp__<server>__<tool>
                        parts = name.split("__", 2)
                        if len(parts) >= 2:
                            mcp_server = parts[1]
                            result.mcp_counts[mcp_server] += 1

                    # Time-windowed tool/skill stats (if event has timestamp)
                    ts = obj.get("time")
                    if isinstance(ts, (int, float)):
                        try:
                            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone()
                        except Exception:
                            dt = None
                    else:
                        dt = None
                    if dt is not None:
                        for w in _windows_for(dt):
                            result.tool_counts_by_window[w][name] += 1
                            if name == "Skill":
                                skill_name = event.get("args", {}).get("skill", "unknown")
                                result.skill_counts_by_window[w][skill_name] += 1
                            elif name.startswith("mcp__"):
                                parts = name.split("__", 2)
                                if len(parts) >= 2:
                                    mcp_server = parts[1]
                                    result.mcp_counts_by_window[w][mcp_server] += 1

            new_offset = f.tell()
            return new_offset
    except Exception as e:
        log.warning("Error parsing %s: %s", path, e)
        return offset


# ---------------------------------------------------------------------------
# Full re-parse (single pass, for cache misses)
# ---------------------------------------------------------------------------

def parse_all_full() -> ParseResult:
    """Do a complete re-parse of all wire.jsonl files from scratch.

    Called by the cached high-level APIs on cache miss.
    """
    result = ParseResult()
    for wire_file in _iter_wire_files():
        _parse_file(wire_file, 0, result)
    return result


# ---------------------------------------------------------------------------
# Cached high-level API
# ---------------------------------------------------------------------------

_trend_cache: dict = {"data": None, "at": 0.0, "date": None}
_tool_usage_cache: dict = {"data": None, "at": 0.0, "date": None}
_model_usage_cache: dict = {"data": None, "at": 0.0, "date": None}
_cache_lock = __import__("threading").Lock()


def _trend_key(dt: datetime, unit: str) -> tuple[str, str]:
    if unit == "hour":
        return dt.strftime("%Y-%m-%d %H:00"), dt.strftime("%H:00")
    if unit == "day":
        return dt.strftime("%Y-%m-%d"), dt.strftime("%m-%d")
    cal = dt.isocalendar()
    return f"{cal.year}-W{cal.week:02d}", f"W{cal.week:02d}"


def _aggregate_usage(records: list[UsageRecord], unit: str, count: int) -> tuple[list[dict], dict]:
    """Aggregate token usage into the last *count* hour/day/week buckets.

    Buckets (for chart) use sliding windows: last N hours/days/weeks.
    Comparison uses calendar-aligned windows:
      - daily (hour unit): today (00:00-now) vs yesterday (same time range)
      - weekly (day unit): this week so far vs last week same range
      - monthly (day unit): this month so far vs last month same range
      - yearly (day unit): this year so far vs last year same range
    Returns (buckets_list, comparison_dict).
    """
    total_counts: Counter = Counter()
    input_counts: Counter = Counter()
    output_counts: Counter = Counter()
    cache_counts: Counter = Counter()
    # Separate accumulators for calendar-aligned comparison
    current_cal_total = 0
    previous_cal_total = 0

    now = datetime.now().astimezone()
    # Calendar-aligned boundaries
    if unit == "hour":
        # 日视图：今天 00:00 ~ 现在 vs 昨天 00:00 ~ 同一时刻
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        current_start = today_start
        current_end = now
        previous_start = yesterday_start
        previous_end = yesterday_start + (now - today_start)
    elif unit == "day" and count == 7:
        # 周视图：本周一 00:00 ~ 现在 vs 上周一 00:00 ~ 同一时刻
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        weekday = today_start.weekday()  # Mon=0..Sun=6
        this_monday = today_start - timedelta(days=weekday)
        last_monday = this_monday - timedelta(days=7)
        current_start = this_monday
        current_end = now
        previous_start = last_monday
        previous_end = last_monday + (now - this_monday)
    elif unit == "day" and count == 30:
        # 月视图：本月1日 00:00 ~ 现在 vs 上月1日 00:00 ~ 同一时刻
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        this_month_start = today_start.replace(day=1)
        # 上月同日：如果上月没有该日（如本月31日，上月只有30天），退到上月最后一天
        try:
            last_month_same_day = this_month_start.replace(month=this_month_start.month - 1) if this_month_start.month > 1 else this_month_start.replace(year=this_month_start.year - 1, month=12)
        except ValueError:
            # 上月没有今天这个日期（如 31 日），用上月最后一天
            if this_month_start.month > 1:
                last_month_same_day = (this_month_start.replace(day=1) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                last_month_same_day = (this_month_start.replace(day=1, year=this_month_start.year - 1, month=12) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        current_start = this_month_start
        current_end = now
        previous_start = last_month_same_day
        previous_end = last_month_same_day + (now - this_month_start)
    else:
        # 年视图（count == 365）：今年1月1日 ~ 现在 vs 去年1月1日 ~ 同一时刻
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        this_year_start = today_start.replace(month=1, day=1)
        last_year_same_moment = this_year_start.replace(year=this_year_start.year - 1)
        current_start = this_year_start
        current_end = now
        previous_start = last_year_same_moment
        previous_end = last_year_same_moment + (now - this_year_start)

    for rec in records:
        key, _ = _trend_key(rec.dt, unit)
        total_counts[key] += rec.total
        input_counts[key] += rec.input_total
        output_counts[key] += rec.output
        cache_counts[key] += rec.cache_read
        # Calendar-aligned comparison
        if current_start <= rec.dt < current_end:
            current_cal_total += rec.total
        elif previous_start <= rec.dt < previous_end:
            previous_cal_total += rec.total

    result: list[dict] = []
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

    change_percent: float | None = None
    if previous_cal_total > 0:
        change_percent = round((current_cal_total - previous_cal_total) / previous_cal_total * 100, 1)
    comparison = {
        "current": current_cal_total,
        "previous": previous_cal_total,
        "changePercent": change_percent,
    }
    return result, comparison


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


def _evaluate_active_days(active_days: int) -> dict:
    """Return human-readable active-days evaluation.

    Thresholds:
    - 优秀: active days >= 30
    - 良好: 7 <= active days < 30
    - 加油: 0 < active days < 7
    - 无数据: no active days
    """
    if active_days <= 0:
        return {"label": "无数据", "level": "none"}
    if active_days >= 30:
        return {"label": "优秀", "level": "excellent"}
    if active_days >= 7:
        return {"label": "良好", "level": "good"}
    return {"label": "加油", "level": "poor"}


def _compute_active_streak(records: list[UsageRecord]) -> tuple[int, int]:
    """Return (active_days, streak_days).

    active_days: number of distinct calendar days with usage records.
    streak_days: consecutive days (ending today or yesterday) with usage.
    """
    active_day_set = {r.dt.strftime("%Y-%m-%d") for r in records}
    active_days = len(active_day_set)
    today = datetime.now().astimezone().date()
    streak_days = 0
    for i in range(365 * 5):
        d = today - timedelta(days=i)
        if d.strftime("%Y-%m-%d") in active_day_set:
            streak_days += 1
        else:
            break
    return active_days, streak_days


def get_trends() -> dict:
    """Get cached trend data, re-parsing if stale."""
    now_ts = time.time()
    today = datetime.now().astimezone().date()
    if _trend_cache["data"] is None or now_ts - _trend_cache["at"] > TREND_CACHE_TTL or _trend_cache.get("date") != today:
        with _cache_lock:
            # Double-checked locking: another thread may have refreshed while we waited
            now_ts = time.time()
            today = datetime.now().astimezone().date()
            if _trend_cache["data"] is not None and now_ts - _trend_cache["at"] <= TREND_CACHE_TTL and _trend_cache.get("date") == today:
                return _trend_cache["data"]
            log.debug("Trend cache miss, parsing wire.jsonl files")
            result = parse_all_full()
            grand_input = sum(r.input_total for r in result.usage_records)
            grand_output = sum(r.output for r in result.usage_records)
            grand_total = grand_input + grand_output
            grand_cache = sum(r.cache_read for r in result.usage_records)
            active_days, streak_days = _compute_active_streak(result.usage_records)

            daily_buckets, daily_cmp = _aggregate_usage(result.usage_records, "hour", 24)
            weekly_buckets, weekly_cmp = _aggregate_usage(result.usage_records, "day", 7)
            monthly_buckets, monthly_cmp = _aggregate_usage(result.usage_records, "day", 30)
            yearly_buckets, yearly_cmp = _aggregate_usage(result.usage_records, "day", 365)

            _trend_cache["data"] = {
                "daily": daily_buckets,
                "weekly": weekly_buckets,
                "monthly": monthly_buckets,
                "yearly": yearly_buckets,
                "comparison": {
                    "daily": daily_cmp,
                    "weekly": weekly_cmp,
                    "monthly": monthly_cmp,
                    "yearly": yearly_cmp,
                },
                "total": {
                    "value": grand_total,
                    "input": grand_input,
                    "output": grand_output,
                    "cacheRead": grand_cache,
                    "cacheRate": round((grand_cache / grand_input * 100), 1) if grand_input > 0 else 0.0,
                    "cacheEvaluation": _evaluate_cache_rate(grand_input, grand_cache),
                    "activeDays": active_days,
                    "streakDays": streak_days,
                    "activeEvaluation": _evaluate_active_days(active_days),
                },
            }
            _trend_cache["at"] = now_ts
            _trend_cache["date"] = today

            # Also update tool-usage and model-usage caches since we just parsed everything
            _update_tool_usage_cache(result)
            _update_model_usage_cache(result)

    return _trend_cache["data"]


def _update_tool_usage_cache(result: ParseResult):
    """Update the tool-usage cache from a ParseResult."""
    def _build(tool_counter, skill_counter, mcp_counter):
        return {
            "totalToolCalls": sum(tool_counter.values()),
            "totalSkillCalls": sum(skill_counter.values()),
            "totalMcpCalls": sum(mcp_counter.values()),
            "tools": [{"name": k, "count": v} for k, v in tool_counter.most_common(15)],
            "skills": [{"name": k, "count": v} for k, v in skill_counter.most_common(15)],
            "mcpServers": [{"name": k, "count": v} for k, v in mcp_counter.most_common()],
            # Full counters for per-item lookup (not truncated to top 15)
            "skillCountsFull": dict(skill_counter),
            "mcpCountsFull": dict(mcp_counter),
        }
    all_data = _build(result.tool_counts, result.skill_counts, result.mcp_counts)
    _tool_usage_cache["data"] = {
        "totalToolCalls": all_data["totalToolCalls"],
        "totalSkillCalls": all_data["totalSkillCalls"],
        "totalMcpCalls": all_data["totalMcpCalls"],
        "tools": all_data["tools"],
        "skills": all_data["skills"],
        "mcpServers": all_data["mcpServers"],
        "skillCountsFull": all_data["skillCountsFull"],
        "mcpCountsFull": all_data["mcpCountsFull"],
        "windows": {
            "24h": _build(result.tool_counts_by_window["24h"], result.skill_counts_by_window["24h"], result.mcp_counts_by_window["24h"]),
            "7d":  _build(result.tool_counts_by_window["7d"],  result.skill_counts_by_window["7d"],  result.mcp_counts_by_window["7d"]),
            "30d": _build(result.tool_counts_by_window["30d"], result.skill_counts_by_window["30d"], result.mcp_counts_by_window["30d"]),
            "all": all_data,
        },
    }
    _tool_usage_cache["at"] = time.time()
    _tool_usage_cache["date"] = datetime.now().astimezone().date()


def get_tool_usage() -> dict:
    """Get cached tool/skill usage data, re-parsing if stale."""
    now_ts = time.time()
    today = datetime.now().astimezone().date()
    if _tool_usage_cache["data"] is None or now_ts - _tool_usage_cache["at"] > TOOL_USAGE_CACHE_TTL or _tool_usage_cache.get("date") != today:
        with _cache_lock:
            now_ts = time.time()
            today = datetime.now().astimezone().date()
            if _tool_usage_cache["data"] is not None and now_ts - _tool_usage_cache["at"] <= TOOL_USAGE_CACHE_TTL and _tool_usage_cache.get("date") == today:
                return _tool_usage_cache["data"]
            log.debug("Tool-usage cache miss, parsing wire.jsonl files")
            result = parse_all_full()
            _update_tool_usage_cache(result)
            _tool_usage_cache["date"] = today
            # Also update trend + model caches
            _trend_cache["at"] = 0  # force trend refresh next call
            _update_model_usage_cache(result)
    return _tool_usage_cache["data"]


def _build_model_trend_series(bucket_dict: dict, count: int, unit: str) -> list[dict]:
    """Build a time-series list of the last *count* *unit* buckets.

    unit is 'day' or 'week'. Empty buckets are filled with zero totals.
    Each item contains: key, label, total, models{model: total}.
    """
    now = datetime.now().astimezone()
    items = []
    for i in range(count - 1, -1, -1):
        if unit == "day":
            d = now - timedelta(days=i)
            key = d.strftime("%Y-%m-%d")
            label = d.strftime("%m-%d")
        else:
            cal = (now - timedelta(weeks=i)).isocalendar()
            key = f"{cal.year}-W{cal.week:02d}"
            label = f"W{cal.week:02d}"
        bucket = bucket_dict.get(key, {})
        models = {model: stats["total"] for model, stats in bucket.items()}
        total = sum(models.values())
        items.append({"key": key, "label": label, "total": total, "models": models})
    return items


def _update_model_usage_cache(result: ParseResult):
    """Update the model-usage cache from a ParseResult."""
    def _build(model_tokens_dict):
        models = []
        for model, tokens in sorted(model_tokens_dict.items(), key=lambda x: x[1]["total"], reverse=True):
            models.append({
                "model": model,
                "calls": tokens["calls"],
                "input": tokens["input"],
                "output": tokens["output"],
                "total": tokens["total"],
            })
        return {
            "models": models,
            "totalCalls": sum(t["calls"] for t in model_tokens_dict.values()),
            "totalTokens": sum(t["total"] for t in model_tokens_dict.values()),
        }
    all_data = _build(result.model_tokens)
    _model_usage_cache["data"] = {
        "models": all_data["models"],
        "totalCalls": all_data["totalCalls"],
        "totalTokens": all_data["totalTokens"],
        "windows": {
            "24h": _build(result.model_tokens_by_window["24h"]),
            "7d":  _build(result.model_tokens_by_window["7d"]),
            "30d": _build(result.model_tokens_by_window["30d"]),
            "all": all_data,
        },
        "trends": {
            "daily": _build_model_trend_series(result.model_tokens_by_day, 30, "day"),
        },
    }
    _model_usage_cache["at"] = time.time()
    _model_usage_cache["date"] = datetime.now().astimezone().date()


def get_model_usage() -> dict:
    """Get cached model usage distribution, re-parsing if stale."""
    now_ts = time.time()
    today = datetime.now().astimezone().date()
    if _model_usage_cache["data"] is None or now_ts - _model_usage_cache["at"] > TOOL_USAGE_CACHE_TTL or _model_usage_cache.get("date") != today:
        with _cache_lock:
            now_ts = time.time()
            today = datetime.now().astimezone().date()
            if _model_usage_cache["data"] is not None and now_ts - _model_usage_cache["at"] <= TOOL_USAGE_CACHE_TTL and _model_usage_cache.get("date") == today:
                return _model_usage_cache["data"]
            log.debug("Model-usage cache miss, parsing wire.jsonl files")
            result = parse_all_full()
            _update_model_usage_cache(result)
            _model_usage_cache["date"] = today
            # Also update other caches
            _trend_cache["at"] = 0
            _update_tool_usage_cache(result)
    return _model_usage_cache["data"]
