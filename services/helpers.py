"""Shared helper utilities: JSON loading, HTTP, TCP, YAML parsing, PowerShell escaping."""

import contextlib
import json
import os
import socket
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import yaml

from config import log


def no_window_kwargs() -> dict:
    """Return subprocess kwargs that hide console windows on Windows.

    Uses STARTUPINFO(SW_HIDE) + CREATE_NO_WINDOW so that neither the direct
    child nor any grandchild (e.g. node.exe spawned by kimi.exe) flashes a
    black console window.
    """
    kwargs: dict = {}
    if hasattr(subprocess, "STARTUPINFO"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def safe_json_load(path: Path) -> dict | None:
    """Load JSON from *path*, returning None on any error.

    Uses utf-8-sig to transparently skip an optional BOM that Windows
    Notepad writes by default when saving as "UTF-8".
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        log.warning("Failed to load JSON from %s: %s", path, e)
        return None


def lock_for(path: Path) -> Path:
    """Return the sibling lock-file path for *path*.

    `tasks.json` -> `tasks.json.lock`, `config.toml` -> `config.toml.lock`.
    Used together with config_lock() to serialize load-modify-save sequences.
    """
    path = Path(path)
    return path.parent / (path.name + ".lock")


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


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically write *text* to *path* via tempfile + rename.

    Writes to a temp file in the same directory, then renames over the target.
    On Windows, rename is atomic on the same filesystem. On POSIX, os.replace
    is atomic. Prevents partial-write corruption on crash.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextlib.contextmanager
def config_lock(lock_path: Path, timeout: float = 5.0):
    """Cross-platform file lock for serializing config.toml writes.

    Uses msvcrt.locking on Windows, fcntl.flock on POSIX. Blocks up to
    *timeout* seconds; raises TimeoutError if the lock cannot be acquired.
    """
    import time

    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "w", encoding="utf-8")
    acquired = False
    try:
        start = time.monotonic()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() - start >= timeout:
                    raise TimeoutError(
                        f"Could not acquire lock on {lock_path} within {timeout}s"
                    )
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        f.close()
