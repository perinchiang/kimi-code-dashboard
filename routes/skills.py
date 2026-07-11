"""Skills API blueprint."""

from flask import Blueprint, jsonify

from config import AGENTS_DIR, SKILL_LOCK, log
from services.helpers import parse_skill_frontmatter, safe_json_load

bp = Blueprint("skills", __name__)


@bp.route("/api/skills")
def api_skills():
    lock = safe_json_load(SKILL_LOCK) or {}
    skills = []

    locked_ids = set()
    for skill_id, meta in lock.get("skills", {}).items():
        locked_ids.add(skill_id)
        skill_path = AGENTS_DIR / meta.get("skillPath", f"skills/{skill_id}/SKILL.md")
        local_md = skill_path if skill_path.exists() else AGENTS_DIR / "skills" / skill_id / "SKILL.md"

        if local_md.exists():
            info = parse_skill_frontmatter(local_md)
            local = True
        else:
            info = {"name": skill_id, "description": "Skill files not present in local workspace."}
            local = False

        skills.append({
            "id": skill_id,
            "name": info.get("name") or skill_id,
            "description": info.get("description", ""),
            "source": meta.get("source", ""),
            "sourceUrl": meta.get("sourceUrl", ""),
            "installedAt": meta.get("installedAt", ""),
            "local": local,
        })

    # Add local project skills not tracked in the lock file
    local_skills_dir = AGENTS_DIR / "skills"
    if local_skills_dir.exists():
        for skill_dir in local_skills_dir.iterdir():
            if skill_dir.is_dir() and skill_dir.name not in locked_ids:
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
                    })

    return jsonify({
        "total": len(skills),
        "localCount": sum(1 for s in skills if s["local"]),
        "skills": skills,
    })
