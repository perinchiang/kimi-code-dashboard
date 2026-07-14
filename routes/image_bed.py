"""图床配置 API。

提供 R2 凭证的读取（脱敏）、保存、测试连接接口。
凭证写入 ~/.kimi-code/config.toml 的 [image_bed] 段，MCP 也会读这份配置。
"""

from flask import Blueprint, jsonify, request

from config import log
from services.r2_uploader import (
    load_image_bed_config,
    save_image_bed_config,
    mask_secret,
    test_connection,
)

bp = Blueprint("image_bed", __name__, url_prefix="/api/image-bed")


@bp.route("/config", methods=["GET"])
def get_config():
    """读取图床配置（密钥脱敏）。"""
    cfg = load_image_bed_config()
    # 脱敏密钥
    return jsonify({
        "enabled": cfg.get("enabled", False),
        "provider": cfg.get("provider", "r2"),
        "endpoint_url": cfg.get("endpoint_url", ""),
        "access_key_masked": mask_secret(cfg.get("access_key", "")),
        "secret_key_masked": mask_secret(cfg.get("secret_key", "")),
        "bucket": cfg.get("bucket", ""),
        "public_base_url": cfg.get("public_base_url", ""),
        "path_template": cfg.get("path_template", "{file_id}"),
        "has_access_key": bool(cfg.get("access_key")),
        "has_secret_key": bool(cfg.get("secret_key")),
        "error": cfg.get("error"),
    })


@bp.route("/config", methods=["POST"])
def save_config():
    """保存图床配置。

    请求体字段：
      provider, endpoint_url, bucket, public_base_url, path_template
      access_key (可选：为空或不传表示保留原值)
      secret_key (可选：同上)
    """
    body = request.get_json(silent=True) or {}
    # 读取现有配置，保留未提交的密钥
    existing = load_image_bed_config()
    new_cfg = {
        "provider": body.get("provider", "r2"),
        "endpoint_url": body.get("endpoint_url", "").strip().rstrip("/"),
        "bucket": body.get("bucket", "").strip(),
        "public_base_url": body.get("public_base_url", "").strip().rstrip("/"),
        "path_template": (body.get("path_template", "").strip() or "{file_id}"),
        # 密钥：前端传明文则更新，传空字符串则保留原值
        "access_key": (body.get("access_key") or "").strip() or existing.get("access_key", ""),
        "secret_key": (body.get("secret_key") or "").strip() or existing.get("secret_key", ""),
    }
    try:
        save_image_bed_config(new_cfg)
        log.info("Image bed config saved")
        return jsonify({"success": True})
    except Exception as e:
        log.error("Failed to save image bed config: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/test", methods=["POST"])
def test_conn():
    """测试 R2 连接。"""
    cfg = load_image_bed_config()
    result = test_connection(cfg)
    return jsonify(result)
