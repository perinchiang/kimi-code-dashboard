"""Cloudflare R2 上传服务。

读取 ~/.kimi-code/config.toml 中的 [image_bed] 配置，
上传文件到 R2（S3 兼容 API），并维护本地缓存 image_upload_cache.json。

缓存格式：
{
  "f_01KX...": {
    "url": "https://cdn.example.com/f_01KX...",
    "uploaded_at": "2026-07-13T10:00:00"
  }
}
"""

import json
import shutil
import tomllib
from datetime import datetime
from pathlib import Path
import glob
import os

try:
    import boto3
    from botocore.config import Config as BotoConfig
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

from config import log
from services.helpers import atomic_write_text, config_lock, lock_for

KIMI_CODE_DIR = Path.home() / ".kimi-code"
CONFIG_PATH = KIMI_CODE_DIR / "config.toml"
CACHE_PATH = KIMI_CODE_DIR / "dashboard" / "image_upload_cache.json"
FILES_DIR = KIMI_CODE_DIR / "files"
SESSIONS_DIR = KIMI_CODE_DIR / "sessions"


# ---------------------------------------------------------------------------
# Config 读取
# ---------------------------------------------------------------------------

def load_image_bed_config() -> dict:
    """从 config.toml 读取 [image_bed] 段。

    返回 dict，字段：
      enabled, provider, endpoint_url, access_key, secret_key,
      bucket, public_base_url, path_template
    如果配置不存在或读取失败，返回空字段 + enabled=False。

    自动迁移：旧版 account_id 字段会推导成 endpoint_url。
    """
    defaults = {
        "enabled": False,
        "provider": "r2",
        "endpoint_url": "",
        "access_key": "",
        "secret_key": "",
        "bucket": "",
        "public_base_url": "",
        "path_template": "{file_id}",
    }
    if not CONFIG_PATH.exists():
        return defaults
    try:
        cfg = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        ib = cfg.get("image_bed", {})
        # 合并：以 defaults 为底，覆盖已配置字段
        result = dict(defaults)
        for k in defaults:
            if k in ib:
                result[k] = ib[k]
        # 自动迁移：旧版 account_id -> endpoint_url
        if not result["endpoint_url"]:
            old_account_id = ib.get("account_id", "")
            if old_account_id:
                result["endpoint_url"] = f"https://{old_account_id}.r2.cloudflarestorage.com"
            # 如果 public_base_url 看起来是 R2 endpoint（包含 .r2.cloudflarestorage.com），也迁移
            pub = result.get("public_base_url", "")
            if pub and ".r2.cloudflarestorage.com" in pub and not old_account_id:
                result["endpoint_url"] = pub.rstrip("/")
                result["public_base_url"] = ""
        # enabled 判定：关键字段都填了才视为可用
        result["enabled"] = bool(
            result["endpoint_url"] and result["access_key"] and result["secret_key"]
            and result["bucket"]
        )
        return result
    except Exception as e:
        log.warning("Failed to read image_bed config: %s", e)
        defaults["error"] = str(e)
        return defaults


def save_image_bed_config(new_cfg: dict) -> None:
    """写入 [image_bed] 段到 config.toml，保留其他内容。

    new_cfg 字段：provider, endpoint_url, access_key, secret_key,
                  bucket, public_base_url, path_template
    """
    import tomli_w
    # 备份
    backup = CONFIG_PATH.with_suffix(
        f".toml.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
    )
    try:
        shutil.copy2(CONFIG_PATH, backup)
    except Exception as e:
        log.warning("Could not backup config.toml: %s", e)

    # 清理旧 .bak 文件（保留最近 10 个）
    baks = sorted(glob.glob(str(CONFIG_PATH) + ".*.bak"), key=lambda p: Path(p).stat().st_mtime, reverse=True)
    for old in baks[10:]:
        try:
            Path(old).unlink()
        except OSError:
            pass

    with config_lock(lock_for(CONFIG_PATH)):
        # 读取现有配置（utf-8-sig 透明跳过 BOM）
        try:
            cfg = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            cfg = {}
        except Exception as e:
            log.error("config.toml 解析失败,中止写入以防止数据丢失: %s", e)
            raise

        # 更新 image_bed 段
        cfg["image_bed"] = {
            "provider": new_cfg.get("provider", "r2"),
            "endpoint_url": new_cfg.get("endpoint_url", "").strip().rstrip("/"),
            "access_key": new_cfg.get("access_key", "").strip(),
            "secret_key": new_cfg.get("secret_key", "").strip(),
            "bucket": new_cfg.get("bucket", "").strip(),
            "public_base_url": new_cfg.get("public_base_url", "").strip().rstrip("/"),
            "path_template": (new_cfg.get("path_template", "").strip() or "{file_id}"),
        }

        with open(CONFIG_PATH, "wb") as f:
            tomli_w.dump(cfg, f)


def mask_secret(s: str) -> str:
    """脱敏密钥用于前端展示。"""
    if not s:
        return ""
    if len(s) <= 8:
        return "••••"
    return s[:4] + "••••" + s[-4:]


# ---------------------------------------------------------------------------
# 缓存读写
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    atomic_write_text(CACHE_PATH, json.dumps(cache, ensure_ascii=False, indent=2))


def get_uploaded_url(file_id: str) -> str | None:
    """查询某个 file_id 是否已上传，返回外链 URL 或 None。"""
    cache = _load_cache()
    entry = cache.get(file_id)
    if entry and entry.get("url"):
        return entry["url"]
    return None


def get_uploaded_map() -> dict:
    """返回完整的 {file_id: {url, uploaded_at}} 映射，供列表展示用。"""
    return _load_cache()


# ---------------------------------------------------------------------------
# 上传逻辑
# ---------------------------------------------------------------------------

def test_connection(cfg: dict) -> dict:
    """测试 R2 连接是否可用。

    返回 {"ok": bool, "msg": str}
    """
    if not HAS_BOTO3:
        return {"ok": False, "msg": "未安装 boto3，请运行 pip install boto3"}
    if not cfg.get("enabled"):
        return {"ok": False, "msg": "配置不完整（缺少 endpoint_url/access_key/secret_key/bucket）"}
    try:
        client = _get_client(cfg)
        client.head_bucket(Bucket=cfg["bucket"])
        return {"ok": True, "msg": f"连接成功，bucket={cfg['bucket']}"}
    except Exception as e:
        return {"ok": False, "msg": f"连接失败: {e}"}


def upload_file(file_id: str, cfg: dict | None = None) -> dict:
    """上传 ~/.kimi-code/files/<file_id> 到 R2。

    返回 {"success": bool, "url": str, "error": str}
    如果已上传（缓存命中），直接返回缓存的 URL。
    """
    # 缓存命中
    cached = get_uploaded_url(file_id)
    if cached:
        return {"success": True, "url": cached, "cached": True}

    if cfg is None:
        cfg = load_image_bed_config()
    if not cfg.get("enabled"):
        return {"success": False, "error": "图床未配置或配置不完整"}
    if not HAS_BOTO3:
        return {"success": False, "error": "未安装 boto3，请运行 pip install boto3"}

    # 读取 index.json 拿到文件名和 media_type
    index_path = FILES_DIR / "index.json"
    if not index_path.exists():
        return {"success": False, "error": "找不到 files/index.json"}
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"success": False, "error": f"读取 index.json 失败: {e}"}

    # index.json 实际结构：{"version":1, "files":[{id, name, media_type, size, created_at}]}
    # 兼容旧式纯 list 和顶层 dict
    if isinstance(index, list):
        files_list = index
    elif isinstance(index, dict):
        files_list = index.get("files", [])
        # 兼容旧式 {file_id: entry}
        if not files_list and file_id in index:
            files_list = [{file_id: index[file_id]}]
    else:
        files_list = []
    entry = next((x for x in files_list if x.get("id") == file_id), None)
    if not entry:
        return {"success": False, "error": f"index.json 中找不到 {file_id}"}

    file_path = FILES_DIR / file_id
    if not file_path.exists():
        return {"success": False, "error": f"文件不存在: {file_path}"}

    media_type = entry.get("media_type", "application/octet-stream")
    name = entry.get("name", file_id)
    created_at = entry.get("created_at", "")

    try:
        client = _get_client(cfg)
        # 用 path_template 生成 object key
        key = _render_path_template(cfg.get("path_template", "{file_id}"), file_id, name, media_type, created_at)
        client.upload_file(
            Filename=str(file_path),
            Bucket=cfg["bucket"],
            Key=key,
            ExtraArgs={"ContentType": media_type},
        )
        # 拼接外链 URL：有 public_base_url 用之，否则用 endpoint + bucket + key
        base = cfg.get("public_base_url", "").rstrip("/")
        if base:
            url = f"{base}/{key}"
        else:
            # 回退：endpoint_url + bucket + key（不一定公开可访问）
            url = f"{cfg.get('endpoint_url','').rstrip('/')}/{cfg['bucket']}/{key}"

        # 写缓存
        with config_lock(lock_for(CACHE_PATH)):
            cache = _load_cache()
            cache[file_id] = {
                "url": url,
                "uploaded_at": datetime.now().isoformat(),
                "name": name,
                "key": key,
            }
            _save_cache(cache)
        log.info("Uploaded %s to R2: %s", file_id, url)
        return {"success": True, "url": url, "name": name, "key": key}
    except Exception as e:
        log.error("R2 upload failed for %s: %s", file_id, e)
        return {"success": False, "error": str(e)}


def _render_path_template(template: str, file_id: str, name: str, media_type: str, created_at: str) -> str:
    """根据模板渲染 R2 object key。

    支持的占位符：
      {file_id}  - 产物 ID（默认）
      {name}     - 原始文件名（含扩展名）
      {stem}     - 文件名主干（不含扩展名）
      {ext}      - 扩展名（不含点，如 png）
      {date}     - 创建日期 YYYY-MM-DD（基于 created_at 或当天）
      {year}     - 创建年
      {month}    - 创建月（01-12）
      {day}      - 创建日（01-31）
      {media}    - media_type 子类型（如 png）
    """
    from datetime import datetime as _dt
    # 解析 created_at（ISO 格式，可能带 Z）
    dt = None
    if created_at:
        try:
            dt = _dt.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            dt = None
    if dt is None:
        dt = _dt.now()

    # 文件名主干和扩展名
    stem = name
    ext = ""
    if "." in name:
        stem, _, ext = name.rpartition(".")
    media_sub = media_type.split("/")[-1] if "/" in media_type else media_type

    try:
        return template.format(
            file_id=file_id,
            name=name,
            stem=stem,
            ext=ext,
            date=dt.strftime("%Y-%m-%d"),
            year=dt.strftime("%Y"),
            month=dt.strftime("%m"),
            day=dt.strftime("%d"),
            media=media_sub,
        )
    except (KeyError, IndexError, ValueError):
        # 模板里有未知占位符，回退到 file_id
        return file_id


def list_artifacts(file_type: str = "all", keyword: str = "", limit: int = 100, offset: int = 0) -> dict:
    """列出 Kimi Code 产物，附加图床上传状态。

    参数：
      file_type: all / image / other
      keyword: 文件名搜索（不区分大小写）
      limit, offset: 分页

    返回：
      {
        "files": [{id, name, media_type, size, created_at, uploaded_url, uploaded_at}],
        "total": int,
        "image_bed_enabled": bool
      }
    """
    index_path = FILES_DIR / "index.json"
    if not index_path.exists():
        return {"files": [], "total": 0, "image_bed_enabled": load_image_bed_config().get("enabled", False)}
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"files": [], "total": 0, "image_bed_enabled": False, "error": str(e)}

    if isinstance(index, list):
        files_list = index
    elif isinstance(index, dict):
        files_list = index.get("files", [])
    else:
        files_list = []

    # 过滤
    kw = (keyword or "").strip().lower()
    upload_map = get_uploaded_map()
    # GC: 清理缓存中已不存在的 file_id（不影响 blob: 前缀的条目）
    valid_ids = {f.get("id") for f in files_list if f.get("id")}
    cache = dict(upload_map)
    cache_dirty = False
    for cached_id in list(cache.keys()):
        if not cached_id.startswith("blob:") and cached_id not in valid_ids:
            del cache[cached_id]
            cache_dirty = True
    result = []
    for f in files_list:
        media = f.get("media_type", "")
        is_image = media.startswith("image/")
        if file_type == "image" and not is_image:
            continue
        if file_type == "other" and is_image:
            continue
        name = f.get("name", "")
        if kw and kw not in name.lower() and kw not in f.get("id", "").lower():
            continue
        # 附加上传状态
        item = dict(f)
        cache_entry = cache.get(f.get("id"), {})
        item["uploaded_url"] = cache_entry.get("url", "")
        item["uploaded_at"] = cache_entry.get("uploaded_at", "")
        result.append(item)

    # 按创建时间倒序
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    total = len(result)
    page = result[offset: offset + limit]
    if cache_dirty:
        _save_cache(cache)
    return {
        "files": page,
        "total": total,
        "image_bed_enabled": load_image_bed_config().get("enabled", False),
    }


def _scan_blob_sources() -> dict:
    """扫描所有 wire.jsonl，返回 {sha256: source} 映射。

    source: 'user' / 'ai'
    判定规则：哪个角色先引用，就归哪个；同时被引用归 user。
    """
    import re
    sources = {}
    wire_pattern = str(SESSIONS_DIR / "*" / "session_*" / "agents" / "*" / "wire.jsonl")
    for wp in glob.glob(wire_pattern):
        try:
            with open(wp, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    refs = re.findall(r'blobref:[^;"]+;([a-f0-9]{64})', line)
                    if not refs:
                        continue
                    ev_type = ev.get("type", "")
                    role = None
                    if ev_type == "context.append_message":
                        role = ev.get("message", {}).get("role", "")
                    elif ev_type == "turn.prompt":
                        role = "user"
                    elif ev_type == "context.append_loop_event":
                        if ev.get("event", {}).get("type") == "tool.result":
                            role = "ai"
                    if role == "user":
                        for r in refs:
                            if sources.get(r) != "ai":
                                sources[r] = "user"
                    elif role == "ai":
                        for r in refs:
                            if r not in sources:
                                sources[r] = "ai"
        except Exception:
            continue
    return sources


def list_all_artifacts(file_type: str = "all", keyword: str = "", limit: int = 200, offset: int = 0) -> dict:
    """统一列出所有产物（用户上传 + AI 生成），按时间倒序，AI 优先。

    用户上传图在 files/ 和会话 blobs/ 都有副本，blobs/ 里的用户副本会跳过避免重复。

    返回 {
        "items": [{id, source, name, media_type, size, created_at, uploaded_url, uploaded_at}],
        "total": int,
        "image_bed_enabled": bool
    }
    """
    upload_map = get_uploaded_map()
    items = []

    # 1. 用户上传（files/）
    index_path = FILES_DIR / "index.json"
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            files_list = index.get("files", []) if isinstance(index, dict) else (index if isinstance(index, list) else [])
            for f in files_list:
                media = f.get("media_type", "")
                is_image = media.startswith("image/")
                if file_type == "image" and not is_image:
                    continue
                if file_type == "other" and is_image:
                    continue
                name = f.get("name", "")
                fid = f.get("id", "")
                kw = (keyword or "").strip().lower()
                if kw and kw not in name.lower() and kw not in fid.lower():
                    continue
                cache_entry = upload_map.get(fid, {})
                items.append({
                    "id": fid,
                    "source": "user",
                    "name": name,
                    "media_type": media,
                    "size": f.get("size", 0),
                    "created_at": f.get("created_at", ""),
                    "sort_time": f.get("created_at", ""),
                    "uploaded_url": cache_entry.get("url", ""),
                    "uploaded_at": cache_entry.get("uploaded_at", ""),
                })
        except Exception as e:
            log.warning("list_all_artifacts: failed to read index: %s", e)

    # 2. AI 生成（blobs/）— 通过 wire.jsonl 判断归属，跳过用户上传的副本
    if SESSIONS_DIR.exists():
        blob_sources = _scan_blob_sources()
        pattern = str(SESSIONS_DIR / "*" / "session_*" / "agents" / "*" / "blobs" / "*")
        seen_sha = set()
        for path_str in glob.glob(pattern):
            p = Path(path_str)
            if not p.is_file():
                continue
            sha = p.name
            if sha in seen_sha:
                continue
            seen_sha.add(sha)
            # 判断归属：扫不到的默认 ai（保守）
            source = blob_sources.get(sha, "ai")
            # 跳过用户上传的副本（files/ 里已有，避免重复）
            if source == "user":
                continue
            try:
                stat = p.stat()
                with open(p, "rb") as f:
                    head = f.read(16)
                mime = _detect_mime(head)
                if file_type == "image" and not mime.startswith("image/"):
                    continue
                if file_type == "other" and mime.startswith("image/"):
                    continue
                kw = (keyword or "").strip().lower()
                if kw and kw not in sha.lower():
                    continue
                mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
                cache_entry = upload_map.get(_blob_cache_key(sha), {})
                items.append({
                    "id": sha,
                    "source": "ai",
                    "name": sha[:12] + "…",
                    "media_type": mime,
                    "size": stat.st_size,
                    "created_at": mtime,
                    "sort_time": mtime,
                    "uploaded_url": cache_entry.get("url", ""),
                    "uploaded_at": cache_entry.get("uploaded_at", ""),
                })
            except Exception:
                continue

    # 排序：sort_time 倒序；同时间 AI 优先（source="ai" 排前）
    items.sort(key=lambda x: (x.get("sort_time", ""), x.get("source") == "user"), reverse=True)
    total = len(items)
    page = items[offset: offset + limit]
    return {
        "items": page,
        "total": total,
        "image_bed_enabled": load_image_bed_config().get("enabled", False),
    }


# ---------------------------------------------------------------------------
# AI 生成图片（会话 blobs）— 保留 list_blobs/upload_blob 供 MCP 使用
# ---------------------------------------------------------------------------

def _detect_mime(head: bytes) -> str:
    """根据文件头检测 mime type。"""
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if head[:3] == b'\xff\xd8\xff':
        return "image/jpeg"
    if head[:4] == b'GIF8':
        return "image/gif"
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return "image/webp"
    return "application/octet-stream"


def _blob_cache_key(sha256: str) -> str:
    return f"blob:{sha256}"


def list_blobs(keyword: str = "", limit: int = 200, offset: int = 0) -> dict:
    """扫描所有会话的 blobs/ 目录，列出 AI 生成/引用的图片。

    返回 {
        "blobs": [{sha256, media_type, size, mtime, session_id, uploaded_url, uploaded_at}],
        "total": int,
        "image_bed_enabled": bool
    }
    """
    if not SESSIONS_DIR.exists():
        return {"blobs": [], "total": 0, "image_bed_enabled": load_image_bed_config().get("enabled", False)}

    # glob: sessions/*/agents/*/blobs/*
    pattern = str(SESSIONS_DIR / "*" / "session_*" / "agents" / "*" / "blobs" / "*")
    all_blobs = {}  # sha256 -> info（去重，同一图可能在多会话出现）
    for path_str in glob.glob(pattern):
        p = Path(path_str)
        if not p.is_file():
            continue
        sha = p.name
        if sha in all_blobs:
            # 已见过，只更新 session_id 为最新的
            all_blobs[sha]["session_count"] = all_blobs[sha].get("session_count", 1) + 1
            continue
        try:
            stat = p.stat()
            with open(p, "rb") as f:
                head = f.read(16)
            mime = _detect_mime(head)
            # 从路径提取 session_id
            # .../sessions/<workspace>/session_<uuid>/agents/<agent>/blobs/<sha>
            parts = p.parts
            session_id = ""
            for part in parts:
                if part.startswith("session_"):
                    session_id = part
                    break
            all_blobs[sha] = {
                "sha256": sha,
                "media_type": mime,
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "session_id": session_id,
                "session_count": 1,
                "path": str(p),
            }
        except Exception as e:
            log.debug("Failed to read blob %s: %s", path_str, e)
            continue

    # 附加上传状态
    upload_map = get_uploaded_map()
    result = []
    kw = (keyword or "").strip().lower()
    for sha, info in all_blobs.items():
        if kw and kw not in sha.lower():
            continue
        cache_entry = upload_map.get(_blob_cache_key(sha), {})
        info["uploaded_url"] = cache_entry.get("url", "")
        info["uploaded_at"] = cache_entry.get("uploaded_at", "")
        result.append(info)

    # 按 mtime 倒序
    result.sort(key=lambda x: x.get("mtime", ""), reverse=True)
    total = len(result)
    page = result[offset: offset + limit]
    return {
        "blobs": page,
        "total": total,
        "image_bed_enabled": load_image_bed_config().get("enabled", False),
    }


def find_blob_path(sha256: str) -> Path | None:
    """在所有会话 blobs/ 目录中查找指定 sha256 的文件。"""
    pattern = str(SESSIONS_DIR / "*" / "session_*" / "agents" / "*" / "blobs" / sha256)
    matches = glob.glob(pattern)
    return Path(matches[0]) if matches else None


def upload_blob(sha256: str, cfg: dict | None = None) -> dict:
    """上传会话 blobs/ 里的图片到 R2。

    用 blob:<sha256> 作为缓存 key，避免与 files/ 的 file_id 冲突。
    """
    cache_key = _blob_cache_key(sha256)
    # 缓存命中
    cache = _load_cache()
    cached = cache.get(cache_key)
    if cached and cached.get("url"):
        return {"success": True, "url": cached["url"], "cached": True}

    if cfg is None:
        cfg = load_image_bed_config()
    if not cfg.get("enabled"):
        return {"success": False, "error": "图床未配置或配置不完整"}
    if not HAS_BOTO3:
        return {"success": False, "error": "未安装 boto3，请运行 pip install boto3"}

    blob_path = find_blob_path(sha256)
    if not blob_path or not blob_path.exists():
        return {"success": False, "error": f"找不到 blob: {sha256}"}

    # 检测 mime type
    try:
        with open(blob_path, "rb") as f:
            head = f.read(16)
        media_type = _detect_mime(head)
    except Exception as e:
        return {"success": False, "error": f"读取文件失败: {e}"}

    try:
        client = _get_client(cfg)
        # 用 sha256 作为 key（去重，同图只传一次）
        key = _render_path_template(
            cfg.get("path_template", "{file_id}"),
            file_id=sha256[:16],
            name=sha256[:16],
            stem=sha256[:16],
            ext=media_type.split("/")[-1] if "/" in media_type else "",
            created_at="",
            media=media_type.split("/")[-1] if "/" in media_type else "",
        )
        client.upload_file(
            Filename=str(blob_path),
            Bucket=cfg["bucket"],
            Key=key,
            ExtraArgs={"ContentType": media_type},
        )
        # 拼接外链
        base = cfg.get("public_base_url", "").rstrip("/")
        if base:
            url = f"{base}/{key}"
        else:
            url = f"{cfg.get('endpoint_url','').rstrip('/')}/{cfg['bucket']}/{key}"

        # 写缓存
        with config_lock(lock_for(CACHE_PATH)):
            cache = _load_cache()
            cache[cache_key] = {
                "url": url,
                "uploaded_at": datetime.now().isoformat(),
                "name": sha256[:16],
                "key": key,
                "sha256": sha256,
            }
            _save_cache(cache)
        log.info("Uploaded blob %s to R2: %s", sha256[:12], url)
        return {"success": True, "url": url, "sha256": sha256, "key": key}
    except Exception as e:
        log.error("R2 blob upload failed for %s: %s", sha256[:12], e)
        return {"success": False, "error": str(e)}


def _get_client(cfg: dict):
    """构造 S3 兼容客户端（R2 / MinIO / OSS 等）。"""
    endpoint = cfg.get("endpoint_url", "").rstrip("/")
    if not endpoint:
        raise ValueError("endpoint_url 未配置")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        region_name="auto",
        config=BotoConfig(signature_version="s3v4"),
    )
