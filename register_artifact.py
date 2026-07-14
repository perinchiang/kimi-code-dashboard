#!/usr/bin/env python3
"""Register a new file in ~/.kimi-code/files/index.json and return its file_id."""

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from services.helpers import atomic_write_text

FILES_DIR = Path.home() / ".kimi-code" / "files"
INDEX_PATH = FILES_DIR / "index.json"
FILE_PATH = FILES_DIR / "dashboard-arch-flowchart.png"

# Crockford base32 alphabet (excludes I, L, O, U)
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

def generate_file_id() -> str:
    # 26 chars after f_ to match existing ULID-like IDs
    return "f_" + "".join(secrets.choice(ALPHABET) for _ in range(26))

def main():
    file_id = generate_file_id()
    size = FILE_PATH.stat().st_size
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond:06d}Z"

    index = {"version": 1, "files": []}
    if INDEX_PATH.exists():
        try:
            index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    files_list = index.get("files", [])
    files_list.insert(0, {
        "id": file_id,
        "name": "dashboard-arch-flowchart.png",
        "media_type": "image/png",
        "size": size,
        "created_at": created_at,
    })
    index["files"] = files_list

    atomic_write_text(INDEX_PATH, json.dumps(index, ensure_ascii=False, indent=2))
    print(file_id)

if __name__ == "__main__":
    main()
