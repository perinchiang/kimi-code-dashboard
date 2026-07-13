import json

"""Skills API blueprint.

Supports listing, enabling/disabling, editing metadata, and uninstalling skills.
"""

import shutil
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import AGENTS_DIR, SKILL_LOCK, log
from services.helpers import parse_skill_frontmatter, safe_json_load

bp = Blueprint("skills", __name__)


def _load_lock() -> dict:
    return safe_json_load(SKILL_LOCK) or {"version": 3, "skills": {}, "dismissed": {}, "disabled": {}}


def _save_lock(lock: dict) -> bool:
    try:
        SKILL_LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        log.error("Failed to write %s: %s", SKILL_LOCK, e)
        return False


def _skill_info(skill_id: str, meta: dict) -> dict:
    skill_path = AGENTS_DIR / meta.get("skillPath", f"skills/{skill_id}/SKILL.md")
    if not skill_path.exists():
        skill_path = AGENTS_DIR / "skills" / skill_id / "SKILL.md"
    if skill_path.exists():
        info = parse_skill_frontmatter(skill_path)
        local = True
    else:
        info = {"name": skill_id, "description": "Skill files not present in local workspace."}
        local = False
    return {
        "id": skill_id,
        "name": info.get("name") or skill_id,
        "description": info.get("description", ""),
        "source": meta.get("source", ""),
        "sourceUrl": meta.get("sourceUrl", ""),
        "installedAt": meta.get("installedAt", ""),
        "local": local,
    }


@bp.route("/api/skills")
def api_skills():
    lock = _load_lock()
    skills = []
    disabled_ids = set()

    # Enabled skills from lock file
    for skill_id, meta in lock.get("skills", {}).items():
        info = _skill_info(skill_id, meta)
        info["enabled"] = True
        skills.append(info)

    # Disabled skills from lock file
    for skill_id, meta in lock.get("disabled", {}).items():
        info = _skill_info(skill_id, meta)
        info["enabled"] = False
        skills.append(info)
        disabled_ids.add(skill_id)

    # Local project skills not tracked in the lock file
    local_skills_dir = AGENTS_DIR / "skills"
    if local_skills_dir.exists():
        for skill_dir in local_skills_dir.iterdir():
            if skill_dir.is_dir() and skill_dir.name not in lock.get("skills", {}) and skill_dir.name not in disabled_ids:
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    info = parse_skill_frontmatter(skill_md)
                    skills.append({
                        "id": skill_dir.name,
                        "name": info.get("name") or skill_dir.name,
                        "description": info.get("description", ""),
                        "source": "local/project",
                        "sourceUrl": "",
                        "installedAt": "",
                        "local": True,
                        "enabled": True,
                    })

    skills.sort(key=lambda s: s["name"].lower())
    return jsonify({
        "total": len(skills),
        "localCount": sum(1 for s in skills if s["local"]),
        "enabledCount": sum(1 for s in skills if s["enabled"]),
        "disabledCount": sum(1 for s in skills if not s["enabled"]),
        "skills": skills,
    })


@bp.route("/api/skills/<skill_id>/toggle", methods=["POST"])
def api_skill_toggle(skill_id: str):
    """Enable or disable a skill by moving it between skills and disabled dicts."""
    lock = _load_lock()
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled", True))

    skills = lock.setdefault("skills", {})
    disabled = lock.setdefault("disabled", {})

    currently_enabled = skill_id in skills
    target_enabled = enabled

    if currently_enabled == target_enabled:
        return jsonify({"success": True, "enabled": target_enabled})

    if target_enabled:
        if skill_id not in disabled:
            # Local-only skill: create minimal entry
            skills[skill_id] = {"source": "local/project", "sourceUrl": "", "installedAt": "", "skillPath": f"skills/{skill_id}/SKILL.md"}
        else:
            skills[skill_id] = disabled.pop(skill_id)
    else:
        if skill_id in skills:
            disabled[skill_id] = skills.pop(skill_id)
        else:
            disabled[skill_id] = {"source": "local/project", "sourceUrl": "", "installedAt": "", "skillPath": f"skills/{skill_id}/SKILL.md"}

    if not _save_lock(lock):
        return jsonify({"success": False, "error": "保存 .skill-lock.json 失败"}), 500

    return jsonify({"success": True, "enabled": target_enabled})


@bp.route("/api/skills/<skill_id>/save", methods=["POST"])
def api_skill_save(skill_id: str):
    """Save skill metadata (name/description frontmatter, source info)."""
    lock = _load_lock()
    body = request.get_json(silent=True) or {}

    skills = lock.setdefault("skills", {})
    disabled = lock.setdefault("disabled", {})

    meta = skills.get(skill_id) or disabled.get(skill_id)
    if not meta:
        # Local-only skill
        meta = {"source": "local/project", "sourceUrl": "", "installedAt": "", "skillPath": f"skills/{skill_id}/SKILL.md"}
        skills[skill_id] = meta

    # Update source metadata
    if "source" in body:
        meta["source"] = str(body["source"]).strip()
    if "sourceUrl" in body:
        meta["sourceUrl"] = str(body["sourceUrl"]).strip()

    # Update SKILL.md frontmatter
    skill_path = AGENTS_DIR / meta.get("skillPath", f"skills/{skill_id}/SKILL.md")
    if not skill_path.exists():
        skill_path = AGENTS_DIR / "skills" / skill_id / "SKILL.md"

    if skill_path.exists():
        try:
            text = skill_path.read_text(encoding="utf-8")
            name = str(body.get("name", "")).strip()
            description = str(body.get("description", "")).strip()
            if text.startswith("---"):
                end = text.find("---", 3)
                if end != -1:
                    new_fm = f"---\nname: {name}\ndescription: {description}\n---"
                    rest = text[end + 3:].lstrip("\n")
                    skill_path.write_text(new_fm + "\n\n" + rest, encoding="utf-8")
            else:
                new_fm = f"---\nname: {name}\ndescription: {description}\n---\n\n"
                skill_path.write_text(new_fm + text, encoding="utf-8")
        except Exception as e:
            log.error("Failed to update SKILL.md for %s: %s", skill_id, e)
            return jsonify({"success": False, "error": "更新 SKILL.md 失败: " + str(e)}), 500

    if not _save_lock(lock):
        return jsonify({"success": False, "error": "保存 .skill-lock.json 失败"}), 500

    return jsonify({"success": True})


@bp.route("/api/skills/<skill_id>/delete", methods=["POST"])
def api_skill_delete(skill_id: str):
    """Uninstall a skill: remove from lock file and delete skill directory."""
    lock = _load_lock()

    skills = lock.setdefault("skills", {})
    disabled = lock.setdefault("disabled", {})

    meta = skills.pop(skill_id, None) or disabled.pop(skill_id, None)

    skill_path = None
    if meta:
        skill_path = AGENTS_DIR / meta.get("skillPath", f"skills/{skill_id}/SKILL.md")
    if not skill_path or not skill_path.exists():
        skill_path = AGENTS_DIR / "skills" / skill_id / "SKILL.md"

    if skill_path and skill_path.exists():
        skill_dir = skill_path.parent
        try:
            shutil.rmtree(skill_dir)
        except Exception as e:
            log.error("Failed to remove skill directory %s: %s", skill_dir, e)
            return jsonify({"success": False, "error": "删除 skill 目录失败: " + str(e)}), 500

    if not _save_lock(lock):
        return jsonify({"success": False, "error": "保存 .skill-lock.json 失败"}), 500

    return jsonify({"success": True})
