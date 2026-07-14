"""Scheduled tasks API blueprint.

Security fix: /api/tasks/<id>/run is now POST-only.
PowerShell injection fix: task names are escaped via ps_escape_single_quote.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import SESSIONS_DIR, TASKS_CONFIG, log
from services.helpers import (
    atomic_write_text,
    config_lock,
    lock_for,
    no_window_kwargs,
    ps_escape_single_quote,
    safe_json_load,
)

bp = Blueprint("tasks", __name__)

_DAY_NAMES = ["日", "一", "二", "三", "四", "五", "六"]
_DAY_NAME_TO_INT = {name: i for i, name in enumerate(_DAY_NAMES)}


def _load_tasks_config() -> dict:
    cfg = safe_json_load(TASKS_CONFIG) or {"scriptsDir": "", "tasks": []}
    # 展开 scriptsDir 中的 ~,Python 的 Path 不会自动展开
    scripts_dir = cfg.get("scriptsDir", "")
    if scripts_dir:
        cfg["scriptsDir"] = str(Path(scripts_dir).expanduser())
    return cfg


def _save_tasks_config(cfg: dict) -> bool:
    try:
        atomic_write_text(TASKS_CONFIG, json.dumps(cfg, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        log.error("Failed to write %s: %s", TASKS_CONFIG, e)
        return False


def _run_ps(cmd: str) -> subprocess.CompletedProcess:
    """Run a PowerShell command and return the result."""
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
        **no_window_kwargs(),
    )


def _task_result_status(code: int | None) -> dict:
    if code is None:
        return {"label": "未知", "ok": None}
    if code == 0:
        return {"label": "成功", "ok": True}
    if code == 267011:
        return {"label": "尚未运行", "ok": None}
    if code == 267012:
        return {"label": "未计划", "ok": None}
    if code == 267013:
        return {"label": "已终止", "ok": False}
    if code == 267014:
        return {"label": "无有效触发器", "ok": False}
    if code == 267009:
        return {"label": "运行中", "ok": True}
    if code == 267010:
        return {"label": "已禁用", "ok": False}
    return {"label": f"失败 ({code})", "ok": False}


def _query_task_status(task_name: str) -> dict:
    """Query Windows Task Scheduler for a task's status."""
    if not task_name:
        return {"registered": False, "state": "未注册"}

    safe_name = ps_escape_single_quote(task_name)
    try:
        cmd = (
            f"$t = Get-ScheduledTask -TaskName '{safe_name}' -ErrorAction SilentlyContinue; "
            f"if ($t) {{ $i = $t | Get-ScheduledTaskInfo; "
            f"Write-Output ([string]$t.State + '|' + "
            f"$i.LastRunTime.ToString('yyyy-MM-ddTHH:mm:ss') + '|' + "
            f"$i.NextRunTime.ToString('yyyy-MM-ddTHH:mm:ss') + '|' + "
            f"$i.LastTaskResult) }}"
        )
        result = _run_ps(cmd)
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split("|")
            last_result = int(parts[3]) if len(parts) > 3 and parts[3].lstrip("-").isdigit() else None
            return {
                "registered": True,
                "state": parts[0] if len(parts) > 0 else "Unknown",
                "lastRun": parts[1] if len(parts) > 1 else None,
                "nextRun": parts[2] if len(parts) > 2 else None,
                "lastResult": last_result,
                "resultStatus": _task_result_status(last_result),
            }
    except Exception as e:
        log.warning("Task status query failed for '%s': %s", task_name, e)
    return {"registered": False, "state": "未注册"}


def _read_task_log(scripts_dir: str, log_file: str, lines: int = 50) -> str:
    if not log_file:
        return ""
    log_path = Path(scripts_dir) / log_file
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        all_lines = text.strip().splitlines()
        return "\n".join(all_lines[-lines:]) if all_lines else ""
    except Exception as e:
        log.warning("Failed to read task log %s: %s", log_path, e)
        return ""


def _parse_schedule(schedule: str) -> dict:
    """Parse a human-readable schedule string into a trigger dict."""
    schedule = schedule or ""
    # 每日 HH:MM
    m = re.match(r"每日\s+(\d{1,2}):(\d{2})", schedule)
    if m:
        return {"type": "daily", "time": f"{int(m.group(1)):02d}:{m.group(2)}"}
    # 每周X HH:MM (support multiple days: 每周日、一 21:30)
    m = re.match(r"每周\s*([日一二三四五六、]+)\s+(\d{1,2}):(\d{2})", schedule)
    if m:
        days_str = m.group(1)
        days = []
        for d in days_str.replace("。", "").split("。"):
            d = d.strip()
            if d in _DAY_NAME_TO_INT:
                days.append(_DAY_NAME_TO_INT[d])
        if not days:
            days = [0]
        return {
            "type": "weekly",
            "time": f"{int(m.group(2)):02d}:{m.group(3)}",
            "daysOfWeek": sorted(list(set(days))),
        }
    # 每月X日 HH:MM
    m = re.match(r"每月\s*(\d{1,2})\s*日\s+(\d{1,2}):(\d{2})", schedule)
    if m:
        return {
            "type": "monthly",
            "day": int(m.group(1)),
            "time": f"{int(m.group(2)):02d}:{m.group(3)}",
        }
    # Default to daily 00:00
    return {"type": "daily", "time": "00:00"}


def _format_schedule(trigger: dict) -> str:
    """Format a trigger dict into a human-readable schedule string."""
    ttype = trigger.get("type", "daily")
    time = trigger.get("time", "00:00")
    if ttype == "daily":
        return f"每日 {time}"
    if ttype == "weekly":
        days = sorted(set(trigger.get("daysOfWeek", [0])))
        day_str = "、".join(f"周{_DAY_NAMES[d]}" for d in days)
        return f"每周{day_str} {time}"
    if ttype == "monthly":
        return f"每月{trigger.get('day', 1)}日 {time}"
    if ttype == "once":
        return f"一次 {trigger.get('datetime', '')}"
    return trigger.get("cron", "")


def _build_trigger_ps(trigger: dict) -> str:
    """Build a New-ScheduledTaskTrigger PowerShell snippet."""
    import re as _re

    ttype = trigger.get("type", "daily")
    time = str(trigger.get("time", "00:00"))
    # 校验 time 格式为 HH:MM,防止命令注入
    if not _re.match(r"^\d{1,2}:\d{2}$", time):
        time = "00:00"
    safe_time = ps_escape_single_quote(time)
    if ttype == "daily":
        return f"New-ScheduledTaskTrigger -Daily -At '{safe_time}'"
    if ttype == "weekly":
        days = sorted(set(trigger.get("daysOfWeek", [0])))
        weekdays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        days_en = [weekdays[d] for d in days if 0 <= d <= 6]
        days_str = ",".join(days_en)
        return f"New-ScheduledTaskTrigger -Weekly -DaysOfWeek {days_str} -At '{safe_time}'"
    if ttype == "monthly":
        day = trigger.get("day", 1)
        if not isinstance(day, int) or not (1 <= day <= 31):
            day = 1
        return f"New-ScheduledTaskTrigger -Monthly -DaysOfMonth {day} -At '{safe_time}'"
    if ttype == "once":
        dt = str(trigger.get("datetime", ""))
        safe_dt = ps_escape_single_quote(dt)
        return f"New-ScheduledTaskTrigger -Once -At '{safe_dt}'"
    # Fallback to daily
    return f"New-ScheduledTaskTrigger -Daily -At '{safe_time}'"


def _register_scheduled_task(task: dict, scripts_dir: str) -> tuple[bool, str]:
    """Create or update a Windows scheduled task."""
    task_name = task.get("taskName", "")
    if not task_name:
        return False, "taskName 为空"

    script = task.get("script", "")
    if not script:
        return False, "script 为空"

    script_path = Path(scripts_dir) / script
    python_exe = sys.executable
    safe_name = ps_escape_single_quote(task_name)
    safe_script = ps_escape_single_quote(str(script_path))
    safe_python = ps_escape_single_quote(python_exe)
    safe_working = ps_escape_single_quote(scripts_dir)

    trigger_ps = _build_trigger_ps(task.get("trigger", {}))
    cmd = (
        f"$action = New-ScheduledTaskAction -Execute '{safe_python}' -Argument '{safe_script}' -WorkingDirectory '{safe_working}'; "
        f"$trigger = {trigger_ps}; "
        f"$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable; "
        f"Register-ScheduledTask -TaskName '{safe_name}' -Action $action -Trigger $trigger -Settings $settings -Force"
    )
    result = _run_ps(cmd)
    if result.returncode != 0:
        error = result.stderr.strip() or "未知错误"
        log.error("Register scheduled task '%s' failed: %s", task_name, error)
        return False, error
    return True, ""


def _unregister_scheduled_task(task_name: str) -> tuple[bool, str]:
    """Delete a Windows scheduled task."""
    if not task_name:
        return False, "taskName 为空"
    safe_name = ps_escape_single_quote(task_name)
    cmd = f"Unregister-ScheduledTask -TaskName '{safe_name}' -Confirm:$false -ErrorAction SilentlyContinue"
    result = _run_ps(cmd)
    if result.returncode != 0:
        error = result.stderr.strip() or "未知错误"
        log.error("Unregister scheduled task '%s' failed: %s", task_name, error)
        return False, error
    return True, ""


def _set_task_enabled(task_name: str, enabled: bool) -> tuple[bool, str]:
    """Enable or disable a Windows scheduled task."""
    if not task_name:
        return False, "taskName 为空"
    safe_name = ps_escape_single_quote(task_name)
    verb = "Enable" if enabled else "Disable"
    cmd = f"{verb}-ScheduledTask -TaskName '{safe_name}'"
    result = _run_ps(cmd)
    if result.returncode != 0:
        error = result.stderr.strip() or "未知错误"
        log.error("%s scheduled task '%s' failed: %s", verb, task_name, error)
        return False, error
    return True, ""


def _find_task(cfg: dict, task_id: str) -> dict | None:
    for t in cfg.get("tasks", []):
        if t.get("id") == task_id:
            return t
    return None


@bp.route("/api/tasks")
def api_tasks():
    cfg = _load_tasks_config()
    scripts_dir = cfg.get("scriptsDir", "")
    tasks = []
    for t in cfg.get("tasks", []):
        status = _query_task_status(t.get("taskName", ""))
        log_preview = _read_task_log(scripts_dir, t.get("logFile", ""), 50)
        trigger = t.get("trigger") or _parse_schedule(t.get("schedule", ""))
        tasks.append({
            "id": t.get("id", ""),
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "script": t.get("script", ""),
            "schedule": t.get("schedule", ""),
            "trigger": trigger,
            "enabled": t.get("enabled", True),
            "sources": t.get("sources", []),
            "taskName": t.get("taskName", ""),
            "status": status,
            "logPreview": log_preview,
        })
    return jsonify({"tasks": tasks, "total": len(tasks)})


@bp.route("/api/tasks/<task_id>/run", methods=["POST"])
def api_task_run(task_id: str):
    """POST-only: trigger a scheduled task."""
    cfg = _load_tasks_config()
    scripts_dir = cfg.get("scriptsDir", "")
    task = _find_task(cfg, task_id)
    if not task:
        return jsonify({"status": "error", "error": "Task not found"})

    task_name = task.get("taskName", "")
    if task_name:
        safe_name = ps_escape_single_quote(task_name)
        try:
            cmd = (
                f"$t = Get-ScheduledTask -TaskName '{safe_name}' -ErrorAction SilentlyContinue; "
                f"if ($t) {{ Start-ScheduledTask -TaskName '{safe_name}'; Write-Output 'started' }} "
                f"else {{ Write-Output 'not_registered' }}"
            )
            result = _run_ps(cmd)
            if result.returncode == 0 and result.stdout.strip() == "started":
                return jsonify({"status": "launched", "taskName": task_name})
        except Exception as e:
            log.warning("Task trigger failed for '%s': %s", task_name, e)

    # Fallback: run script directly
    script_path = Path(scripts_dir) / task.get("script", "")
    if not script_path.exists():
        return jsonify({"status": "error", "error": f"Script not found: {script_path}"})
    try:
        kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "cwd": str(Path(scripts_dir)),
        }
        kwargs.update(no_window_kwargs())
        subprocess.Popen([sys.executable, str(script_path)], **kwargs)
        return jsonify({"status": "launched", "script": task.get("script", ""), "note": "direct"})
    except Exception as e:
        log.error("Direct script launch failed: %s", e)
        return jsonify({"status": "error", "error": str(e)})


@bp.route("/api/tasks/<task_id>/log")
def api_task_log(task_id: str):
    cfg = _load_tasks_config()
    scripts_dir = cfg.get("scriptsDir", "")
    task = _find_task(cfg, task_id)
    if not task:
        return jsonify({"log": "", "logFile": ""})
    log_text = _read_task_log(scripts_dir, task.get("logFile", ""), 200)
    return jsonify({"log": log_text, "logFile": task.get("logFile", "")})


@bp.route("/api/tasks/<task_id>/toggle", methods=["POST"])
def api_task_toggle(task_id: str):
    """Enable or disable a task."""
    body = request.get_json(silent=True) or {}

    with config_lock(lock_for(TASKS_CONFIG)):
        cfg = _load_tasks_config()
        task = _find_task(cfg, task_id)
        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404

        enabled = bool(body.get("enabled", not task.get("enabled", True)))
        task["enabled"] = enabled

        if not _save_tasks_config(cfg):
            return jsonify({"success": False, "error": "保存 tasks.json 失败"}), 500

    ok, error = _set_task_enabled(task.get("taskName", ""), enabled)
    if not ok:
        return jsonify({"success": True, "enabled": enabled, "warning": "配置已保存，但更新 Windows 计划任务失败（需要管理员权限）: " + error})

    return jsonify({"success": True, "enabled": enabled})


@bp.route("/api/tasks/create", methods=["POST"])
def api_task_create():
    """Create a new scheduled task."""
    body = request.get_json(silent=True) or {}

    task_id = str(body.get("id", "")).strip()
    task_name_display = str(body.get("name", "")).strip()
    script = str(body.get("script", "")).strip()
    task_name = str(body.get("taskName", "")).strip()

    if not task_id:
        return jsonify({"success": False, "error": "id 不能为空"}), 400
    if not task_name_display:
        return jsonify({"success": False, "error": "name 不能为空"}), 400
    if not script:
        return jsonify({"success": False, "error": "script 不能为空"}), 400
    if not task_name:
        return jsonify({"success": False, "error": "taskName 不能为空"}), 400

    trigger = body.get("trigger") or {"type": "daily", "time": "00:00"}
    if isinstance(trigger, dict):
        trigger["type"] = trigger.get("type", "daily")
        trigger["time"] = trigger.get("time", "00:00")
        if trigger["type"] == "weekly":
            trigger["daysOfWeek"] = sorted(set(trigger.get("daysOfWeek", [0])))
        schedule = _format_schedule(trigger)
    else:
        trigger = {"type": "daily", "time": "00:00"}
        schedule = "每日 00:00"

    task = {
        "id": task_id,
        "name": task_name_display,
        "description": str(body.get("description", "")).strip(),
        "script": script,
        "schedule": schedule,
        "trigger": trigger,
        "enabled": bool(body.get("enabled", True)),
        "logFile": str(body.get("logFile", "")).strip(),
        "sources": list(body.get("sources", [])),
        "taskName": task_name,
    }

    with config_lock(lock_for(TASKS_CONFIG)):
        cfg = _load_tasks_config()
        scripts_dir = cfg.get("scriptsDir", "")

        # Check id / taskName uniqueness
        for t in cfg.get("tasks", []):
            if t.get("id") == task_id:
                return jsonify({"success": False, "error": f"任务 id '{task_id}' 已存在"}), 409
            if t.get("taskName", "").lower() == task_name.lower():
                return jsonify({"success": False, "error": f"taskName '{task_name}' 已存在"}), 409

        cfg.setdefault("tasks", []).append(task)

        if not _save_tasks_config(cfg):
            return jsonify({"success": False, "error": "保存 tasks.json 失败"}), 500

    warning = None
    if task.get("enabled", True):
        ok, error = _register_scheduled_task(task, scripts_dir)
        if not ok:
            warning = "配置已保存，但注册 Windows 计划任务失败（需要管理员权限）: " + error

    result = {"success": True, "task": task}
    if warning:
        result["warning"] = warning
    return jsonify(result), 201


@bp.route("/api/tasks/<task_id>/save", methods=["POST"])
def api_task_save(task_id: str):
    """Save task edits and update the scheduled task."""
    body = request.get_json(silent=True) or {}

    with config_lock(lock_for(TASKS_CONFIG)):
        cfg = _load_tasks_config()
        task = _find_task(cfg, task_id)
        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404

        scripts_dir = cfg.get("scriptsDir", "")

        # Update editable fields
        task["name"] = str(body.get("name", task.get("name", ""))).strip()
        task["description"] = str(body.get("description", task.get("description", ""))).strip()
        task["script"] = str(body.get("script", task.get("script", ""))).strip()
        task["logFile"] = str(body.get("logFile", task.get("logFile", ""))).strip()
        task["sources"] = list(body.get("sources", task.get("sources", [])))

        trigger = body.get("trigger")
        if trigger and isinstance(trigger, dict):
            trigger["type"] = trigger.get("type", "daily")
            trigger["time"] = trigger.get("time", "00:00")
            if trigger["type"] == "weekly":
                trigger["daysOfWeek"] = sorted(set(trigger.get("daysOfWeek", [0])))
            task["trigger"] = trigger
            task["schedule"] = _format_schedule(trigger)

        if not _save_tasks_config(cfg):
            return jsonify({"success": False, "error": "保存 tasks.json 失败"}), 500

    # Re-register the scheduled task if enabled
    warning = None
    if task.get("enabled", True):
        ok, error = _register_scheduled_task(task, scripts_dir)
        if not ok:
            warning = "配置已保存，但更新 Windows 计划任务失败（需要管理员权限）: " + error
    else:
        # If disabled, just make sure it exists but is disabled
        _register_scheduled_task(task, scripts_dir)
        _set_task_enabled(task.get("taskName", ""), False)

    result = {"success": True, "task": task}
    if warning:
        result["warning"] = warning
    return jsonify(result)


@bp.route("/api/tasks/<task_id>/delete", methods=["POST"])
def api_task_delete(task_id: str):
    """Delete a task and its scheduled task."""
    task_name = ""

    with config_lock(lock_for(TASKS_CONFIG)):
        cfg = _load_tasks_config()
        task = _find_task(cfg, task_id)
        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404

        task_name = task.get("taskName", "")
        cfg["tasks"] = [t for t in cfg.get("tasks", []) if t.get("id") != task_id]
        if not _save_tasks_config(cfg):
            return jsonify({"success": False, "error": "保存 tasks.json 失败"}), 500

    warning = None
    if task_name:
        ok, error = _unregister_scheduled_task(task_name)
        if not ok:
            warning = "配置已删除，但移除 Windows 计划任务失败（需要管理员权限）: " + error

    result = {"success": True}
    if warning:
        result["warning"] = warning
    return jsonify(result)


# === 后台任务（Kimi Code CLI 运行时任务） ===

_BG_CACHE_TTL = 10  # 秒
_bg_cache = {"data": None, "ts": 0.0}
_TASK_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_SESSION_ID_RE = re.compile(r"^session_[0-9a-f-]+$")


def _scan_background_tasks() -> dict:
    """扫描 sessions 目录下的后台任务 JSON，返回汇总与列表。

    路径模式: sessions/<wd>/session_<uuid>/agents/<agent>/tasks/<task_id>.json
    日志路径: 同级 <task_id>/output.log
    """
    tasks = []
    try:
        # glob 单层匹配: sessions/<wd>/session_<uuid>/agents/<agent>/tasks/<task>.json
        pattern = "*/session_*/agents/*/tasks/*.json"
        for json_path in SESSIONS_DIR.glob(pattern):
            try:
                data = safe_json_load(json_path)
            except Exception:
                data = None
            if not isinstance(data, dict):
                continue
            try:
                # 路径解析: .../sessions/<wd>/session_<uuid>/agents/<agent>/tasks/<task_id>.json
                parts = json_path.parts
                # 找到 "sessions" 索引
                if "sessions" not in parts:
                    continue
                sess_idx = parts.index("sessions")
                work_dir_name = parts[sess_idx + 1] if len(parts) > sess_idx + 1 else ""
                session_full = parts[sess_idx + 2] if len(parts) > sess_idx + 2 else ""
                agent_id = parts[sess_idx + 4] if len(parts) > sess_idx + 4 else ""
                task_file = parts[-1]
                task_id = task_file[:-5] if task_file.endswith(".json") else task_file
            except Exception:
                continue

            session_short = session_full
            if session_short.startswith("session_"):
                session_short = session_short[len("session_"):]
            session_short = session_short[:8]

            task_id_val = str(data.get("taskId", task_id))
            status_val = str(data.get("status", "")).lower()
            started_at = data.get("startedAt")
            ended_at = data.get("endedAt")
            output_path = json_path.parent / task_id_val / "output.log"

            tasks.append({
                "taskId": task_id_val,
                "description": str(data.get("description", "")),
                "status": status_val,
                "kind": str(data.get("kind", "")),
                "command": str(data.get("command", "")),
                "pid": data.get("pid"),
                "exitCode": data.get("exitCode"),
                "startedAt": started_at,
                "endedAt": ended_at,
                "timeoutMs": data.get("timeoutMs"),
                "detached": bool(data.get("detached", False)),
                "sessionId": session_full,
                "sessionShort": session_short,
                "workDirName": work_dir_name,
                "agentId": agent_id,
                "outputPath": str(output_path),
            })
    except Exception as e:
        log.warning("Failed to scan background tasks: %s", e)

    # 分类计数
    running = sum(1 for t in tasks if t["status"] == "running")
    failed = sum(1 for t in tasks if t["status"] == "completed" and t.get("exitCode") not in (0, None))
    completed = sum(1 for t in tasks if t["status"] == "completed" and t.get("exitCode") == 0)

    # 排序：running 置顶 → 其余按 startedAt 倒序
    def sort_key(t):
        # running 优先级 0，其他 1；startedAt 缺失视为 0
        priority = 0 if t["status"] == "running" else 1
        started = t.get("startedAt") or 0
        # 倒序需要负号
        return (priority, -started if isinstance(started, (int, float)) else 0)

    tasks.sort(key=sort_key)

    return {
        "running": running,
        "completed": completed,
        "failed": failed,
        "total": len(tasks),
        "tasks": tasks,
    }


@bp.route("/api/background-tasks")
def api_background_tasks():
    """返回后台任务列表（带 TTL 缓存）。"""
    now = time.monotonic()
    if _bg_cache["data"] is None or now - _bg_cache["ts"] > _BG_CACHE_TTL:
        _bg_cache["data"] = _scan_background_tasks()
        _bg_cache["ts"] = now
    return jsonify(_bg_cache["data"])


@bp.route("/api/background-tasks/log")
def api_background_tasks_log():
    """读取后台任务 output.log 最后 200 行。

    Query: session=<session_xxx>&task=<task_id>
    """
    session = (request.args.get("session") or "").strip()
    task = (request.args.get("task") or "").strip()

    if not session or not _SESSION_ID_RE.match(session):
        return jsonify({"taskId": task, "log": "", "error": "invalid session"}), 400
    if not task or not _TASK_ID_RE.match(task):
        return jsonify({"taskId": task, "log": "", "error": "invalid task"}), 400

    # 在 SESSIONS_DIR 下定位 <wd>/session_xxx/agents/*/tasks/<task>.json
    try:
        pattern = f"*/{session}/agents/*/tasks/{task}.json"
        matches = list(SESSIONS_DIR.glob(pattern))
    except Exception as e:
        log.warning("glob failed for bg task log: %s", e)
        return jsonify({"taskId": task, "log": ""}), 500

    if not matches:
        return jsonify({"taskId": task, "log": "", "error": "task not found"}), 404

    json_path = matches[0]
    # log 路径硬约束在 tasks 目录内
    tasks_dir = json_path.parent
    log_path = (tasks_dir / task / "output.log").resolve()
    try:
        log_path.relative_to(tasks_dir.resolve())
    except ValueError:
        return jsonify({"taskId": task, "log": "", "error": "path traversal"}), 400

    if not log_path.exists():
        return jsonify({"taskId": task, "log": ""})

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        all_lines = text.strip().splitlines()
        tail = "\n".join(all_lines[-200:]) if all_lines else ""
        return jsonify({"taskId": task, "log": tail})
    except Exception as e:
        log.warning("Failed to read bg task log %s: %s", log_path, e)
        return jsonify({"taskId": task, "log": "", "error": str(e)}), 500
