"""Scheduled tasks API blueprint.

Security fix: /api/tasks/<id>/run is now POST-only.
PowerShell injection fix: task names are escaped via ps_escape_single_quote.
"""

import subprocess
import sys
from pathlib import Path

from flask import Blueprint, jsonify

from config import TASKS_CONFIG, log
from services.helpers import ps_escape_single_quote, safe_json_load

bp = Blueprint("tasks", __name__)


def _load_tasks_config() -> dict:
    return safe_json_load(TASKS_CONFIG) or {"scriptsDir": "", "tasks": []}


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
    """Query Windows Task Scheduler for a task's status.

    Uses ps_escape_single_quote to prevent PowerShell injection.
    """
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
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=10,
        )
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


@bp.route("/api/tasks")
def api_tasks():
    cfg = _load_tasks_config()
    scripts_dir = cfg.get("scriptsDir", "")
    tasks = []
    for t in cfg.get("tasks", []):
        status = _query_task_status(t.get("taskName", ""))
        log_preview = _read_task_log(scripts_dir, t.get("logFile", ""), 50)
        tasks.append({
            "id": t.get("id", ""),
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "script": t.get("script", ""),
            "schedule": t.get("schedule", ""),
            "sources": t.get("sources", []),
            "taskName": t.get("taskName", ""),
            "status": status,
            "logPreview": log_preview,
        })
    return jsonify({"tasks": tasks, "total": len(tasks)})


@bp.route("/api/tasks/<task_id>/run", methods=["POST"])
def api_task_run(task_id: str):
    """POST-only: trigger a scheduled task.

    Tries Windows Task Scheduler first (so LastRunTime updates),
    falls back to running the script directly.
    """
    cfg = _load_tasks_config()
    scripts_dir = cfg.get("scriptsDir", "")
    for t in cfg.get("tasks", []):
        if t.get("id") == task_id:
            task_name = t.get("taskName", "")
            if task_name:
                safe_name = ps_escape_single_quote(task_name)
                try:
                    cmd = (
                        f"$t = Get-ScheduledTask -TaskName '{safe_name}' -ErrorAction SilentlyContinue; "
                        f"if ($t) {{ Start-ScheduledTask -TaskName '{safe_name}'; Write-Output 'started' }} "
                        f"else {{ Write-Output 'not_registered' }}"
                    )
                    result = subprocess.run(
                        ["powershell", "-NoProfile", "-Command", cmd],
                        capture_output=True, text=True, timeout=10,
                    )
                    if result.returncode == 0 and result.stdout.strip() == "started":
                        return jsonify({"status": "launched", "taskName": task_name})
                except Exception as e:
                    log.warning("Task trigger failed for '%s': %s", task_name, e)

            # Fallback: run script directly
            script_path = Path(scripts_dir) / t.get("script", "")
            if not script_path.exists():
                return jsonify({"status": "error", "error": f"Script not found: {script_path}"})
            try:
                kwargs = {
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                    "cwd": str(Path(scripts_dir)),
                }
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                subprocess.Popen([sys.executable, str(script_path)], **kwargs)
                return jsonify({"status": "launched", "script": t.get("script", ""), "note": "direct"})
            except Exception as e:
                log.error("Direct script launch failed: %s", e)
                return jsonify({"status": "error", "error": str(e)})
    return jsonify({"status": "error", "error": "Task not found"})


@bp.route("/api/tasks/<task_id>/log")
def api_task_log(task_id: str):
    cfg = _load_tasks_config()
    scripts_dir = cfg.get("scriptsDir", "")
    for t in cfg.get("tasks", []):
        if t.get("id") == task_id:
            log_text = _read_task_log(scripts_dir, t.get("logFile", ""), 50)
            return jsonify({"log": log_text, "logFile": t.get("logFile", "")})
    return jsonify({"log": "", "logFile": ""})
