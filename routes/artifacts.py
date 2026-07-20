"""Artifacts 浏览器 routes：列出 Kimi Code 产物 + 手动上传到图床。

产物目录：~/.kimi-code/files/
  - index.json: {"version":1, "files":[{id, name, media_type, size, created_at}]}
  - <file_id>: 实际文件内容
"""

from pathlib import Path

from flask import Blueprint, jsonify, request, send_file, abort

from config import log
from services import r2_uploader

bp = Blueprint("artifacts", __name__)

FILES_DIR = r2_uploader.FILES_DIR


def _is_safe_file_id(file_id: str) -> bool:
    """Reject path traversal attempts in file_id."""
    if not file_id:
        return False
    return "/" not in file_id and "\\" not in file_id and ".." not in file_id


@bp.route("/api/artifacts/all")
def api_list_all_artifacts():
    """统一列出所有产物（用户上传 + AI 生成），按时间倒序，AI 优先。

    Query:
      type: all / image / other (默认 all)
      q: 关键词
      limit: 默认 200，最大 500
      offset: 默认 0
    """
    file_type = (request.args.get("type") or "all").strip().lower()
    if file_type not in ("all", "image", "other"):
        file_type = "all"
    keyword = request.args.get("q", "")
    try:
        limit = max(1, min(500, int(request.args.get("limit", 200))))
    except ValueError:
        limit = 200
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        offset = 0
    data = r2_uploader.list_all_artifacts(file_type=file_type, keyword=keyword, limit=limit, offset=offset)
    return jsonify(data)


@bp.route("/api/artifacts")
def api_list_artifacts():
    """列出产物，附加图床上传状态。

    Query:
      type: all / image / other (默认 all)
      q: 文件名关键词
      limit: 默认 100，最大 500
      offset: 默认 0
    """
    file_type = (request.args.get("type") or "all").strip().lower()
    if file_type not in ("all", "image", "other"):
        file_type = "all"
    keyword = request.args.get("q", "")
    try:
        limit = max(1, min(500, int(request.args.get("limit", 100))))
    except ValueError:
        limit = 100
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        offset = 0

    data = r2_uploader.list_artifacts(
        file_type=file_type, keyword=keyword, limit=limit, offset=offset
    )
    return jsonify(data)


@bp.route("/api/artifacts/<file_id>/content")
def api_artifact_content(file_id: str):
    """读取本地产物文件内容。图片/文本直接返回流，供前端预览。

    自动判断来源：先查 files/，找不到再查 blobs/。
    """
    if not _is_safe_file_id(file_id):
        abort(400, description="无效的 file_id")
    # 1. 先查 files/
    index_path = FILES_DIR / "index.json"
    if index_path.exists():
        import json
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            index = {}
        files_list = index.get("files", []) if isinstance(index, dict) else (index if isinstance(index, list) else [])
        entry = next((x for x in files_list if x.get("id") == file_id), None)
        if entry:
            file_path = FILES_DIR / file_id
            if file_path.exists():
                media_type = entry.get("media_type", "application/octet-stream")
                return send_file(str(file_path), mimetype=media_type, as_attachment=False,
                                 download_name=entry.get("name", file_id))

    # 2. 再查 blobs/（file_id 视为 sha256）
    if all(c in "0123456789abcdefABCDEF" for c in file_id) and len(file_id) >= 32:
        blob_path = r2_uploader.find_blob_path(file_id)
        if blob_path and blob_path.exists():
            try:
                with open(blob_path, "rb") as f:
                    head = f.read(16)
                media_type = r2_uploader._detect_mime(head)
            except Exception:
                media_type = "application/octet-stream"
            return send_file(str(blob_path), mimetype=media_type, as_attachment=False)

    abort(404, description=f"找不到产物 {file_id}")


@bp.route("/api/artifacts/<file_id>/upload", methods=["POST"])
def api_upload_artifact(file_id: str):
    """上传产物到图床。自动判断来源：file_id 或 sha256。"""
    if not _is_safe_file_id(file_id):
        return jsonify({"success": False, "error": "无效的 file_id"}), 400
    # 先查 files/
    index_path = FILES_DIR / "index.json"
    if index_path.exists():
        import json
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            index = {}
        files_list = index.get("files", []) if isinstance(index, dict) else (index if isinstance(index, list) else [])
        if any(x.get("id") == file_id for x in files_list):
            return jsonify(r2_uploader.upload_file(file_id))

    # 再查 blobs/
    if all(c in "0123456789abcdefABCDEF" for c in file_id) and len(file_id) >= 32:
        return jsonify(r2_uploader.upload_blob(file_id))

    return jsonify({"success": False, "error": f"找不到产物 {file_id}"}), 404


@bp.route("/api/artifacts/upload-batch", methods=["POST"])
def api_upload_batch():
    """批量上传。

    Body: {"file_ids": ["f_xxx", ...], "only_images": true}
    only_images=true 时跳过非图片文件。
    """
    body = request.get_json(silent=True) or {}
    file_ids = body.get("file_ids", [])
    only_images = bool(body.get("only_images", False))

    if not isinstance(file_ids, list) or not file_ids:
        return jsonify({"success": False, "error": "file_ids 不能为空"})

    # 读取 index 拿 media_type
    import json
    index_path = FILES_DIR / "index.json"
    if not index_path.exists():
        return jsonify({"success": False, "error": "index.json 不存在"})
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify({"success": False, "error": f"index.json 解析失败: {e}"})
    files_list = index.get("files", []) if isinstance(index, dict) else (index if isinstance(index, list) else [])
    entry_map = {f.get("id"): f for f in files_list}

    results = []
    success_count = 0
    for fid in file_ids:
        entry = entry_map.get(fid)
        if not entry:
            results.append({"id": fid, "success": False, "error": "index.json 中找不到"})
            continue
        if only_images and not entry.get("media_type", "").startswith("image/"):
            results.append({"id": fid, "success": False, "error": "非图片，已跳过", "skipped": True})
            continue
        r = r2_uploader.upload_file(fid)
        results.append({"id": fid, **r})
        if r.get("success"):
            success_count += 1

    return jsonify({
        "success": True,
        "total": len(file_ids),
        "success_count": success_count,
        "results": results,
    })


# --- AI 生成图片（会话 blobs）---

@bp.route("/api/artifacts/blobs")
def api_list_blobs():
    """列出所有会话 blobs/ 里的 AI 生成图片。

    Query:
      q: sha256 关键词搜索
      limit: 默认 200，最大 500
      offset: 默认 0
    """
    keyword = request.args.get("q", "")
    try:
        limit = max(1, min(500, int(request.args.get("limit", 200))))
    except ValueError:
        limit = 200
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        offset = 0
    data = r2_uploader.list_blobs(keyword=keyword, limit=limit, offset=offset)
    return jsonify(data)


@bp.route("/api/artifacts/blobs/<sha256>/content")
def api_blob_content(sha256: str):
    """读取会话 blob 图片内容。"""
    # 安全校验：sha256 只允许十六进制
    if not all(c in "0123456789abcdefABCDEF" for c in sha256) or len(sha256) < 32:
        abort(400, description="无效的 sha256")
    blob_path = r2_uploader.find_blob_path(sha256)
    if not blob_path or not blob_path.exists():
        abort(404, description="blob 不存在")
    # 检测 mime
    try:
        with open(blob_path, "rb") as f:
            head = f.read(16)
        media_type = r2_uploader._detect_mime(head)
    except Exception:
        media_type = "application/octet-stream"
    return send_file(str(blob_path), mimetype=media_type, as_attachment=False)


@bp.route("/api/artifacts/blobs/<sha256>/upload", methods=["POST"])
def api_upload_blob(sha256: str):
    """上传会话 blob 到图床。"""
    if not all(c in "0123456789abcdefABCDEF" for c in sha256) or len(sha256) < 32:
        return jsonify({"success": False, "error": "无效的 sha256"}), 400
    result = r2_uploader.upload_blob(sha256)
    return jsonify(result)


@bp.route("/api/artifacts/blobs/upload-batch", methods=["POST"])
def api_upload_blobs_batch():
    """批量上传 blob。

    Body: {"sha_list": ["abc...", ...]}
    """
    body = request.get_json(silent=True) or {}
    sha_list = body.get("sha_list", [])
    if not isinstance(sha_list, list) or not sha_list:
        return jsonify({"success": False, "error": "sha_list 不能为空"})

    results = []
    success_count = 0
    for sha in sha_list:
        r = r2_uploader.upload_blob(sha)
        results.append({"sha256": sha, **r})
        if r.get("success"):
            success_count += 1

    return jsonify({
        "success": True,
        "total": len(sha_list),
        "success_count": success_count,
        "results": results,
    })
