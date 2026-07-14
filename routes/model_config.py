"""Model/provider configuration for Kimi Code CLI.

Reads and writes ~/.kimi-code/config.toml (providers / models / default_model).
The rest of the config file is preserved as-is.
"""

import json
import shutil
import tomllib
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import tomli_w
from flask import Blueprint, jsonify, request

from config import log

bp = Blueprint("model_config", __name__, url_prefix="/api/model-config")

CONFIG_PATH = Path.home() / ".kimi-code" / "config.toml"
MASK = "••••••••"


def _is_protected_provider(pid: str) -> bool:
    """Built-in/managed providers should not be edited or deleted."""
    return pid.startswith("managed:") or pid == "kimi"


def _load() -> dict:
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def _save(cfg: dict) -> None:
    backup = CONFIG_PATH.with_suffix(f".toml.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak")
    try:
        shutil.copy2(CONFIG_PATH, backup)
    except Exception as e:
        log.warning("Could not backup config.toml: %s", e)
    with open(CONFIG_PATH, "wb") as f:
        tomli_w.dump(cfg, f)


def _mask_key(key: str | None) -> str:
    return MASK if key else ""


def _infer_provider_type(base_url: str, hint: str | None) -> str:
    """Infer the Kimi Code provider type from the URL or user hint.

    Valid Kimi Code provider types: anthropic, openai, kimi, google-genai,
    openai_responses, vertexai. When the hint is empty/unknown we guess from
    the base URL; most OpenAI-compatible services fall back to "openai".
    """
    url = (base_url or "").lower()
    hint = (hint or "").strip().lower()

    valid = {"anthropic", "openai", "kimi", "google-genai", "openai_responses", "vertexai"}
    if hint in valid:
        return hint

    if "anthropic" in url:
        return "anthropic"
    if "generativelanguage.googleapis.com" in url or "gemini" in url:
        return "google-genai"
    if "aiplatform.googleapis.com" in url or "vertexai" in url or "vertex-ai" in url:
        return "vertexai"
    if "kimi" in url or "moonshot" in url:
        return "kimi"
    if "openai" in url and ("responses" in url or "/responses" in url):
        return "openai_responses"
    if "openai" in url:
        return "openai"

    # Default for unknown OpenAI-compatible endpoints.
    return "openai"


def _normalize_type(t: str | None) -> str:
    """Normalize legacy provider types to current Kimi Code values."""
    legacy = {
        "openai_legacy": "openai",
    }
    return legacy.get((t or "").lower().strip(), t or "")


def _providers_list(cfg: dict):
    providers = cfg.get("providers", {})
    result = []
    for pid, p in providers.items():
        result.append({
            "id": pid,
            "type": _normalize_type(p.get("type", "")),
            "base_url": p.get("base_url", ""),
            "api_key": _mask_key(p.get("api_key")),
            "custom_headers": p.get("custom_headers", {}),
            "env": p.get("env", {}),
        })
    return result


def _models_list(cfg: dict):
    models = cfg.get("models", {})
    result = []
    for mid, m in models.items():
        result.append({
            "id": mid,
            "provider": m.get("provider", ""),
            "model": m.get("model", ""),
            "display_name": m.get("display_name", ""),
            "max_context_size": m.get("max_context_size", 0),
            "max_tokens": m.get("max_tokens", 0),
            "capabilities": m.get("capabilities", []),
        })
    return result


@bp.route("", methods=["GET"])
def api_get_config():
    try:
        cfg = _load()
        return jsonify({
            "default_model": cfg.get("default_model", ""),
            "providers": _providers_list(cfg),
            "models": _models_list(cfg),
        })
    except Exception as e:
        log.error("Failed to load model config: %s", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/provider", methods=["POST"])
def api_save_provider():
    body = request.get_json(silent=True) or {}
    pid = (body.get("id") or "").strip()
    if not pid:
        return jsonify({"error": "provider id required"}), 400
    if _is_protected_provider(pid):
        return jsonify({"error": "cannot edit built-in provider"}), 403

    try:
        cfg = _load()
        providers = cfg.setdefault("providers", {})
        old = providers.get(pid, {})
        base_url = body.get("base_url") or old.get("base_url", "")
        entry = {
            "type": _infer_provider_type(base_url, body.get("type")) or old.get("type", "openai"),
            "base_url": base_url,
        }
        new_key = body.get("api_key", MASK)
        if new_key != MASK:
            entry["api_key"] = new_key
        elif "api_key" in old:
            entry["api_key"] = old["api_key"]

        if body.get("custom_headers"):
            entry["custom_headers"] = body["custom_headers"]
        elif "custom_headers" in old:
            entry["custom_headers"] = old["custom_headers"]

        if body.get("env"):
            entry["env"] = body["env"]
        elif "env" in old:
            entry["env"] = old["env"]

        providers[pid] = entry
        _save(cfg)
        return jsonify({"ok": True, "provider": pid})
    except Exception as e:
        log.error("Failed to save provider: %s", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/provider/<path:pid>", methods=["DELETE"])
def api_delete_provider(pid: str):
    if _is_protected_provider(pid):
        return jsonify({"error": "cannot delete built-in provider"}), 403
    try:
        cfg = _load()
        providers = cfg.get("providers", {})
        if pid not in providers:
            return jsonify({"error": "provider not found"}), 404
        del providers[pid]
        _save(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        log.error("Failed to delete provider: %s", e)
        return jsonify({"error": str(e)}), 500


def _infer_model_capabilities(model_id: str) -> list[str]:
    """Guess capabilities from the model id / name.

    Most providers do not expose capability metadata in /models, so we use
    well-known patterns and heuristics.
    """
    mid = (model_id or "").lower()
    caps: set[str] = {"tool_use"}

    # Multimodal.
    if any(k in mid for k in ("vision", "gpt-4o", "claude-3", "gemini-1.5", "gemini-2", "kimi-k2")):
        caps.add("image_in")
    if "video" in mid:
        caps.add("video_in")

    # Reasoning / thinking models.
    if any(k in mid for k in ("thinking", "reasoner", "reasoning", "o1", "o3", "r1", "deepseek-reasoner")):
        caps.add("thinking")
        caps.add("always_thinking")

    return sorted(caps)


def _infer_context_size(model_id: str) -> int:
    """Guess max context size from the model id / name."""
    mid = (model_id or "").lower()

    if "claude-3" in mid:
        return 200000
    if "gemini-1.5" in mid or "gemini-2" in mid:
        return 1000000
    if "gemini" in mid:
        return 32768
    if any(k in mid for k in ("gpt-4o", "gpt-4-turbo", "gpt-4.5")):
        return 128000
    if "gpt-4-32k" in mid:
        return 32768
    if "gpt-4" in mid and "vision" not in mid:
        return 8192
    if "kimi" in mid or "moonshot" in mid:
        return 256000
    if any(k in mid for k in ("deepseek", "qwen", "llama-3.1", "llama-3.2", "llama-3.3")):
        return 128000

    return 128000


@bp.route("/provider/<path:pid>/detect-models", methods=["POST"])
def api_detect_models(pid: str):
    """Call the provider's /models endpoint and return discoverable model IDs."""
    if _is_protected_provider(pid):
        return jsonify({"error": "cannot detect models for built-in provider"}), 403
    try:
        cfg = _load()
        providers = cfg.get("providers", {})
        if pid not in providers:
            return jsonify({"error": "provider not found"}), 404

        p = providers[pid]
        base_url = (p.get("base_url") or "").rstrip("/")
        if not base_url:
            return jsonify({"error": "provider has no base_url"}), 400

        api_key = p.get("api_key", "")
        url = base_url + "/models"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        for k, v in (p.get("custom_headers") or {}).items():
            req.add_header(k, v)

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # OpenAI-compatible shape: { "data": [{"id": "..."}, ...] }
        raw_models = []
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            for item in data["data"]:
                if isinstance(item, dict) and "id" in item:
                    raw_models.append(item["id"])
        elif isinstance(data, dict) and "models" in data and isinstance(data["models"], list):
            for item in data["models"]:
                if isinstance(item, dict) and "id" in item:
                    raw_models.append(item["id"])
                elif isinstance(item, str):
                    raw_models.append(item)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "id" in item:
                    raw_models.append(item["id"])
                elif isinstance(item, str):
                    raw_models.append(item)

        # Filter out already-configured models for this provider.
        existing = {m.get("model") for m in cfg.get("models", {}).values() if m.get("provider") == pid}
        models = []
        for mid in raw_models:
            if mid in existing:
                continue
            models.append({
                "id": mid,
                "capabilities": _infer_model_capabilities(mid),
                "max_context_size": _infer_context_size(mid),
                "max_tokens": 4096,
            })

        return jsonify({"ok": True, "provider": pid, "models": models})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:500]
        log.error("Detect models HTTP error for %s: %s %s", pid, e.code, body)
        return jsonify({"error": f"provider returned HTTP {e.code}: {body}"}), 502
    except Exception as e:
        log.error("Failed to detect models for %s: %s", pid, e)
        return jsonify({"error": str(e)}), 500


@bp.route("/model", methods=["POST"])
def api_save_model():
    body = request.get_json(silent=True) or {}
    mid = (body.get("id") or "").strip()
    if not mid:
        return jsonify({"error": "model id required"}), 400

    try:
        cfg = _load()
        providers = cfg.get("providers", {})
        models = cfg.setdefault("models", {})
        old = models.get(mid, {})
        provider = body.get("provider") or old.get("provider", "")
        if _is_protected_provider(provider):
            return jsonify({"error": "cannot edit model of built-in provider"}), 403
        if provider and provider not in providers:
            return jsonify({"error": f"provider '{provider}' not found"}), 400
        entry = {
            "provider": provider or old.get("provider", ""),
            "model": body.get("model") or old.get("model", mid),
            "max_context_size": int(body.get("max_context_size") or old.get("max_context_size", 128000)),
            "max_tokens": int(body.get("max_tokens") or old.get("max_tokens", 4096)),
        }
        caps = body.get("capabilities")
        if caps is not None:
            entry["capabilities"] = list(caps)
        elif "capabilities" in old:
            entry["capabilities"] = old["capabilities"]

        if body.get("display_name"):
            entry["display_name"] = body["display_name"]
        elif "display_name" in old:
            entry["display_name"] = old["display_name"]

        models[mid] = entry
        _save(cfg)
        return jsonify({"ok": True, "model": mid})
    except Exception as e:
        log.error("Failed to save model: %s", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/model/<path:mid>", methods=["DELETE"])
def api_delete_model(mid: str):
    try:
        cfg = _load()
        models = cfg.get("models", {})
        model = models.get(mid)
        if model and _is_protected_provider(model.get("provider", "")):
            return jsonify({"error": "cannot delete model of built-in provider"}), 403
        if mid not in models:
            return jsonify({"error": "model not found"}), 404
        del models[mid]
        # Keep default_model valid.
        if cfg.get("default_model") == mid:
            cfg["default_model"] = next(iter(models.keys()), "")
        _save(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        log.error("Failed to delete model: %s", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/default-model", methods=["POST"])
def api_set_default_model():
    body = request.get_json(silent=True) or {}
    mid = (body.get("id") or "").strip()
    if not mid:
        return jsonify({"error": "model id required"}), 400
    try:
        cfg = _load()
        models = cfg.get("models", {})
        if mid not in models:
            return jsonify({"error": f"model '{mid}' not found"}), 400
        cfg["default_model"] = mid
        _save(cfg)
        return jsonify({"ok": True, "default_model": mid})
    except Exception as e:
        log.error("Failed to set default model: %s", e)
        return jsonify({"error": str(e)}), 500
