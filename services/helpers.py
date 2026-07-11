"""Shared helper utilities: JSON loading, HTTP, TCP, YAML parsing, PowerShell escaping."""

import json
import socket
import urllib.request
from pathlib import Path

import yaml

from config import log


def safe_json_load(path: Path) -> dict | None:
    """Load JSON from *path*, returning None on any error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        log.warning("Failed to load JSON from %s: %s", path, e)
        return None


def http_get(url: str, timeout: int = 5) -> dict | None:
    """GET *url* and return parsed JSON, or None on failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.debug("http_get failed for %s: %s", url, e)
        return None


def http_post(url: str, payload: dict, timeout: int = 10) -> dict | None:
    """POST JSON to *url* and return parsed JSON, or None on failure."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.debug("http_post failed for %s: %s", url, e)
        return None


def tcp_open(host: str, port: int, timeout: int = 2) -> bool:
    """Check if a TCP connection to *host:port* can be established."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def parse_skill_frontmatter(skill_md: Path) -> dict:
    """Parse YAML frontmatter from a SKILL.md file.

    Returns dict with at least 'name' and 'description' keys.
    """
    result = {"name": skill_md.parent.name, "description": ""}
    try:
        text = skill_md.read_text(encoding="utf-8")
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                fm = yaml.safe_load(text[3:end])
                if isinstance(fm, dict):
                    result["name"] = fm.get("name", result["name"])
                    result["description"] = fm.get("description", "")
    except Exception as e:
        log.debug("Failed to parse frontmatter from %s: %s", skill_md, e)
    return result


def ps_escape_single_quote(s: str) -> str:
    """Escape a string for safe embedding inside PowerShell single-quoted strings.

    In PowerShell, the only character that needs escaping inside single quotes
    is the single quote itself — it's doubled: ' → ''
    """
    return s.replace("'", "''")
