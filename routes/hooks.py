"""Hooks API blueprint.

Reads and writes Kimi Code CLI lifecycle hooks from ~/.kimi-code/config.toml.
Active hooks live under the top-level `hooks` array; disabled hooks live under
`disabled_hooks`. Kimi Code CLI validates hook objects strictly, so we do not
store any dashboard-only metadata inside individual hook entries.
"""

import glob
import hashlib
import json
import shutil
import tomllib
from datetime import datetime
from pathlib import Path

import tomli_w
from flask import Blueprint, jsonify, request

from config import KIMI_CODE_DIR, KIMI_CONFIG, log
from services.helpers import atomic_write_text, config_lock, lock_for

bp = Blueprint("hooks", __name__)

HOOK_SCHEMA_FIELDS = ("event", "command", "matcher", "timeout")

# Dashboard-only metadata for hooks (Kimi CLI rejects unknown keys inside hook objects).
HOOK_DESCRIPTIONS_DIR = KIMI_CODE_DIR / "dashboard"
HOOK_DESCRIPTIONS_FILE = HOOK_DESCRIPTIONS_DIR / "hook-descriptions.json"


def _hook_hash(hook: dict) -> str:
    """Return a stable hash for a hook based on its Kimi-compatible content."""
    normalized = json.dumps(_clean_hook(hook), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _load_descriptions() -> dict:
    """Load the dashboard-only hook descriptions mapping."""
    try:
        if HOOK_DESCRIPTIONS_FILE.exists():
            return json.loads(HOOK_DESCRIPTIONS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Failed to load hook descriptions: %s", e)
    return {}


def _save_descriptions(descriptions: dict) -> bool:
    """Save the dashboard-only hook descriptions mapping."""
    try:
        HOOK_DESCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            HOOK_DESCRIPTIONS_FILE,
            json.dumps(descriptions, ensure_ascii=False, indent=2),
        )
        return True
    except Exception as e:
        log.error("Failed to save hook descriptions: %s", e)
        return False


def _cleanup_old_backups(max_keep: int = 10) -> None:
    """Keep only the most recent *max_keep* .bak files for config.toml."""
    baks = sorted(glob.glob(str(KIMI_CONFIG) + ".*.bak"), key=lambda p: Path(p).stat().st_mtime, reverse=True)
    for old in baks[max_keep:]:
        try:
            Path(old).unlink()
        except OSError:
            pass


def _backup_config() -> Path:
    """Create a timestamped backup of config.toml before mutation."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = KIMI_CONFIG.with_suffix(f".toml.{timestamp}.bak")
    try:
        shutil.copy2(KIMI_CONFIG, backup_path)
        log.info("Backed up %s to %s", KIMI_CONFIG, backup_path)
    except Exception as e:
        log.error("Failed to backup %s: %s", KIMI_CONFIG, e)
    _cleanup_old_backups()
    return backup_path


def _load_config() -> dict:
    try:
        return tomllib.loads(KIMI_CONFIG.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        log.warning("%s not found, returning empty config", KIMI_CONFIG)
        return {}
    except Exception as e:
        log.error("Failed to load %s: %s", KIMI_CONFIG, e)
        return {}


def _save_config(data: dict) -> bool:
    """Write data back to config.toml with a timestamped backup."""
    _backup_config()
    try:
        # Normalize empty arrays to omit the key entirely for cleanliness.
        if not data.get("hooks"):
            data.pop("hooks", None)
        if not data.get("disabled_hooks"):
            data.pop("disabled_hooks", None)
        atomic_write_text(KIMI_CONFIG, tomli_w.dumps(data))
        log.info("Updated %s", KIMI_CONFIG)
        return True
    except Exception as e:
        log.error("Failed to write %s: %s", KIMI_CONFIG, e)
        return False


def _clean_hook(hook: dict) -> dict:
    """Return a hook dict containing only Kimi-compatible fields."""
    clean = {}
    for key in HOOK_SCHEMA_FIELDS:
        if key in hook and hook[key] not in (None, ""):
            clean[key] = hook[key]
    return clean


def _normalize_hook(hook: dict, descriptions: dict | None = None) -> dict:
    """Normalize a hook for API responses."""
    if descriptions is None:
        descriptions = _load_descriptions()
    timeout = hook.get("timeout")
    try:
        timeout = int(timeout) if timeout is not None else None
    except (TypeError, ValueError):
        timeout = None
    cleaned = _clean_hook(hook)
    hhash = _hook_hash(cleaned)
    return {
        "event": hook.get("event", ""),
        "command": hook.get("command", ""),
        "matcher": hook.get("matcher", ""),
        "timeout": timeout,
        "description": descriptions.get(hhash, ""),
        "hash": hhash,
    }


def _list_hooks(data: dict) -> list:
    """Build a flat list of hooks with synthetic IDs.

    IDs are positional indices across [active..., disabled...]. This is stable
    enough for a single-user local dashboard because each request reloads the
    file before mutation.
    """
    descriptions = _load_descriptions()
    active = data.get("hooks") or []
    disabled = data.get("disabled_hooks") or []
    result = []
    for idx, hook in enumerate(active):
        item = _normalize_hook(hook, descriptions)
        item["enabled"] = True
        item["id"] = str(idx)
        result.append(item)
    offset = len(active)
    for idx, hook in enumerate(disabled):
        item = _normalize_hook(hook, descriptions)
        item["enabled"] = False
        item["id"] = str(offset + idx)
        result.append(item)
    return result


def _locate_hook(data: dict, hook_id: str):
    """Return (array_key, index) for a synthetic hook ID, or (None, None)."""
    try:
        idx = int(hook_id)
    except (TypeError, ValueError):
        return None, None
    active = data.get("hooks") or []
    disabled = data.get("disabled_hooks") or []
    if 0 <= idx < len(active):
        return "hooks", idx
    offset = len(active)
    if offset <= idx < offset + len(disabled):
        return "disabled_hooks", idx - offset
    return None, None


@bp.route("/api/hooks")
def api_hooks():
    data = _load_config()
    hooks = _list_hooks(data)
    enabled_count = sum(1 for h in hooks if h["enabled"])
    return jsonify({
        "total": len(hooks),
        "enabledCount": enabled_count,
        "disabledCount": len(hooks) - enabled_count,
        "hooks": hooks,
    })


@bp.route("/api/hooks", methods=["POST"])
def api_hook_create():
    body = request.get_json(silent=True) or {}
    event = str(body.get("event", "")).strip()
    command = str(body.get("command", "")).strip()
    if not event or not command:
        return jsonify({"success": False, "error": "event 和 command 不能为空"}), 400

    matcher = str(body.get("matcher", "")).strip() or None
    timeout_raw = body.get("timeout")
    timeout = None
    if timeout_raw not in (None, ""):
        try:
            timeout = int(timeout_raw)
            if timeout <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "timeout 必须是正整数"}), 400

    new_hook = _clean_hook({
        "event": event,
        "command": command,
        "matcher": matcher,
        "timeout": timeout,
    })

    with config_lock(lock_for(KIMI_CONFIG)):
        data = _load_config()
        enabled = bool(body.get("enabled", True))
        key = "hooks" if enabled else "disabled_hooks"
        data.setdefault(key, [])
        data[key].append(new_hook)

        if not _save_config(data):
            return jsonify({"success": False, "error": "保存 config.toml 失败"}), 500

    # Save dashboard-only description.
    description = str(body.get("description", "")).strip()
    if description:
        descriptions = _load_descriptions()
        descriptions[_hook_hash(new_hook)] = description
        _save_descriptions(descriptions)

    return jsonify({"success": True})


@bp.route("/api/hooks/<hook_id>", methods=["POST"])
def api_hook_update(hook_id: str):
    body = request.get_json(silent=True) or {}
    event = str(body.get("event", "")).strip()
    command = str(body.get("command", "")).strip()
    if not event or not command:
        return jsonify({"success": False, "error": "event 和 command 不能为空"}), 400

    matcher = str(body.get("matcher", "")).strip() or None
    timeout_raw = body.get("timeout")
    timeout = None
    if timeout_raw not in (None, ""):
        try:
            timeout = int(timeout_raw)
            if timeout <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "timeout 必须是正整数"}), 400

    updated = _clean_hook({
        "event": event,
        "command": command,
        "matcher": matcher,
        "timeout": timeout,
    })

    with config_lock(lock_for(KIMI_CONFIG)):
        data = _load_config()
        key, idx = _locate_hook(data, hook_id)
        if key is None:
            return jsonify({"success": False, "error": "Hook 不存在"}), 404

        old_hash = _hook_hash(_clean_hook(data[key][idx]))
        target_enabled = bool(body.get("enabled", key == "hooks"))
        current_enabled = key == "hooks"

        if target_enabled == current_enabled:
            data[key][idx] = updated
        else:
            # Move between arrays.
            data[key].pop(idx)
            new_key = "hooks" if target_enabled else "disabled_hooks"
            data.setdefault(new_key, [])
            data[new_key].append(updated)

        if not _save_config(data):
            return jsonify({"success": False, "error": "保存 config.toml 失败"}), 500

    # Update dashboard-only description.
    descriptions = _load_descriptions()
    description = str(body.get("description", "")).strip()
    new_hash = _hook_hash(updated)
    if old_hash in descriptions and old_hash != new_hash:
        descriptions.pop(old_hash, None)
    if description:
        descriptions[new_hash] = description
    elif new_hash in descriptions:
        descriptions.pop(new_hash, None)
    _save_descriptions(descriptions)

    return jsonify({"success": True})


@bp.route("/api/hooks/<hook_id>/toggle", methods=["POST"])
def api_hook_toggle(hook_id: str):
    with config_lock(lock_for(KIMI_CONFIG)):
        data = _load_config()
        key, idx = _locate_hook(data, hook_id)
        if key is None:
            return jsonify({"success": False, "error": "Hook 不存在"}), 404

        hook = data[key].pop(idx)
        new_key = "disabled_hooks" if key == "hooks" else "hooks"
        data.setdefault(new_key, [])
        data[new_key].append(hook)

        if not _save_config(data):
            return jsonify({"success": False, "error": "保存 config.toml 失败"}), 500
    return jsonify({"success": True})


@bp.route("/api/hooks/<hook_id>/delete", methods=["POST"])
def api_hook_delete(hook_id: str):
    with config_lock(lock_for(KIMI_CONFIG)):
        data = _load_config()
        key, idx = _locate_hook(data, hook_id)
        if key is None:
            return jsonify({"success": False, "error": "Hook 不存在"}), 404

        removed = _clean_hook(data[key][idx])
        data[key].pop(idx)

        if not _save_config(data):
            return jsonify({"success": False, "error": "保存 config.toml 失败"}), 500

    # Clean up dashboard-only description.
    descriptions = _load_descriptions()
    hhash = _hook_hash(removed)
    if hhash in descriptions:
        descriptions.pop(hhash, None)
        _save_descriptions(descriptions)

    return jsonify({"success": True})
