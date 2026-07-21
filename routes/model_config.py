"""Model/provider configuration for Kimi Code CLI.

Reads and writes ~/.kimi-code/config.toml (providers / models / default_model).
The rest of the config file is preserved as-is.
"""

import copy
import hashlib
import json
import glob
import shutil
import subprocess
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import tomli_w
from flask import Blueprint, jsonify, request

from config import KIMI_BIN, KIMI_CODE_DIR, log
from services.helpers import atomic_write_text, config_lock, lock_for, no_window_kwargs

bp = Blueprint("model_config", __name__, url_prefix="/api/model-config")

CONFIG_PATH = Path.home() / ".kimi-code" / "config.toml"
MASK = "••••••••"
CATALOG_URL = "https://models.dev/api.json"
CATALOG_CACHE_PATH = KIMI_CODE_DIR / "cache" / "kimi-dashboard-model-catalog.json"
CATALOG_CACHE_TTL = 6 * 60 * 60
CATALOG_MAX_BYTES = 12 * 1024 * 1024
CATALOG_LOCK = threading.RLock()
VALID_PROVIDER_TYPES = {"anthropic", "openai", "kimi", "google-genai", "openai_responses", "vertexai"}
KNOWN_OPENAI_COMPATIBLE = {
    "302ai", "bailian", "deepseek", "fireworks-ai", "groq", "huggingface", "minimax",
    "novita-ai", "openrouter", "opencode", "siliconflow", "tencent-hunyuan", "togetherai",
    "zhipuai", "zai", "qwen", "dashscope",
}
KNOWN_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "togetherai": "https://api.together.xyz/v1",
}


def _parse_json_output(text: str) -> dict:
    """Parse a JSON object from CLI output, tolerating incidental stdout text."""
    text = (text or "").strip()
    candidates = [text]
    first = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if first > 0:
        candidates.append(text[first:])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except (TypeError, json.JSONDecodeError):
            continue
    raise ValueError("catalog did not return a JSON object")


def _run_kimi_catalog() -> dict:
    """Read the provider catalog through Kimi's read-only catalog command."""
    candidates = []
    if KIMI_BIN.exists():
        candidates.append(KIMI_BIN)
    kimi_on_path = shutil.which("kimi")
    if kimi_on_path:
        path_candidate = Path(kimi_on_path)
        if path_candidate not in candidates:
            candidates.append(path_candidate)
    if not candidates:
        raise FileNotFoundError("kimi executable not found")

    last_error = None
    for binary in candidates:
        try:
            result = subprocess.run(
                [str(binary), "provider", "catalog", "list", "--json"],
                capture_output=True,
                text=True,
                timeout=30,
                **no_window_kwargs(),
            )
            if result.returncode != 0:
                detail = (result.stderr or "").strip().splitlines()
                last_error = RuntimeError(detail[-1][:240] if detail else "kimi catalog command failed")
                continue
            return _parse_json_output(result.stdout)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(str(last_error or "kimi catalog command failed"))


def _fetch_models_dev_catalog() -> dict:
    """Fetch the public catalog as a fallback when the local CLI cannot."""
    req = urllib.request.Request(
        CATALOG_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "Kimi-Code-Dashboard/ProviderCatalog",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > CATALOG_MAX_BYTES:
            raise ValueError("provider catalog response is too large")
        payload = resp.read(CATALOG_MAX_BYTES + 1)
    if len(payload) > CATALOG_MAX_BYTES:
        raise ValueError("provider catalog response is too large")
    return _parse_json_output(payload.decode("utf-8"))


def _catalog_provider_type(provider_id: str, provider: dict) -> tuple[str, str]:
    """Return (Kimi provider type, UI compatibility kind) without guessing broadly."""
    pid = provider_id.lower().strip()
    npm = str(provider.get("npm") or provider.get("package") or "").lower()
    explicit = _normalize_type(provider.get("type") or provider.get("protocol"))
    if explicit in VALID_PROVIDER_TYPES:
        return explicit, "direct"
    if pid in {"vertexai", "google-vertex", "google-vertexai", "google-vertex-anthropic"} or "google-vertex" in npm:
        return "vertexai", "manual"
    if pid in {"anthropic", "claude"} or "anthropic" in npm:
        return "anthropic", "direct"
    if pid in {"google", "gemini", "google-gemini", "google-genai"} or "google-generative-ai" in npm:
        return "google-genai", "direct"
    if pid in {"kimi", "moonshot", "moonshotai"} or "moonshot" in npm:
        return "kimi", "direct"
    if pid in {"openai", "openai-responses"} or npm.endswith("/openai") or npm == "@ai-sdk/openai":
        return ("openai_responses" if "responses" in pid else "openai"), "direct"
    if pid in KNOWN_OPENAI_COMPATIBLE or "openai-compatible" in npm:
        return "openai", "openai-compatible"
    if provider.get("api"):
        return "", "manual"
    return "", "unsupported"


def _catalog_default_base_url(provider_id: str, provider_type: str) -> str:
    pid = provider_id.lower()
    if pid in KNOWN_BASE_URLS:
        return KNOWN_BASE_URLS[pid]
    if provider_type == "anthropic":
        return "https://api.anthropic.com"
    if provider_type == "openai":
        return "https://api.openai.com/v1" if pid == "openai" else ""
    if provider_type == "openai_responses":
        return "https://api.openai.com/v1"
    if provider_type == "google-genai":
        return "https://generativelanguage.googleapis.com"
    if provider_type == "kimi":
        return "https://api.moonshot.ai/v1"
    return ""


def _catalog_model_capabilities(model: dict, provider_id: str) -> list[str]:
    """Map catalog metadata to Kimi model capability names."""
    caps = set()
    has_metadata = any(key in model for key in ("reasoning", "tool_call", "modalities"))
    if model.get("reasoning") is True:
        caps.add("thinking")
    if model.get("tool_call") is True:
        caps.add("tool_use")
    modalities = model.get("modalities") if isinstance(model.get("modalities"), dict) else {}
    input_modalities = modalities.get("input") if isinstance(modalities.get("input"), list) else []
    if "image" in input_modalities:
        caps.add("image_in")
    if "video" in input_modalities:
        caps.add("video_in")
    if not has_metadata:
        caps.update(_infer_model_capabilities(str(model.get("id") or ""), provider_id))
    return sorted(caps)


def _normalize_catalog(raw: dict, source: str) -> dict:
    """Normalize Kimi CLI/models.dev provider data for the Dashboard UI."""
    if isinstance(raw.get("providers"), dict):
        raw = raw["providers"]
    if not isinstance(raw, dict):
        raise ValueError("provider catalog has an invalid shape")

    providers = []
    for provider_key, raw_provider in raw.items():
        if not isinstance(raw_provider, dict):
            continue
        provider_id = str(raw_provider.get("id") or provider_key).strip()
        if not provider_id or any(ord(ch) < 32 for ch in provider_id):
            continue
        provider_type, compatibility = _catalog_provider_type(provider_id, raw_provider)
        api = raw_provider.get("api") or raw_provider.get("base_url") or ""
        base_url = str(api).strip() if isinstance(api, str) else ""
        if not base_url:
            base_url = _catalog_default_base_url(provider_id, provider_type)
        elif provider_id.lower() in KNOWN_BASE_URLS and "${" not in base_url:
            base_url = KNOWN_BASE_URLS[provider_id.lower()]
        env = raw_provider.get("env", [])
        if isinstance(env, dict):
            env = list(env.keys())
        if not isinstance(env, list):
            env = []
        raw_models = raw_provider.get("models", {})
        if isinstance(raw_models, dict):
            model_items = raw_models.items()
        elif isinstance(raw_models, list):
            model_items = ((str(index), value) for index, value in enumerate(raw_models))
        else:
            model_items = []

        models = []
        for model_key, raw_model in model_items:
            if isinstance(raw_model, str):
                raw_model = {"id": raw_model}
            if not isinstance(raw_model, dict):
                continue
            model_id = str(raw_model.get("id") or model_key).strip()
            if not model_id:
                continue
            limits = raw_model.get("limit") if isinstance(raw_model.get("limit"), dict) else {}
            context_size = limits.get("context")
            output_size = limits.get("output")
            try:
                context_size = int(context_size) if context_size else _infer_context_size(model_id)
            except (TypeError, ValueError):
                context_size = _infer_context_size(model_id)
            try:
                output_size = int(output_size) if output_size else 4096
            except (TypeError, ValueError):
                output_size = 4096
            cost = raw_model.get("cost") if isinstance(raw_model.get("cost"), dict) else {}
            cost = {key: value for key, value in cost.items() if key in {"input", "output", "cache_read", "cache_write"} and isinstance(value, (int, float))}
            reasoning_options = raw_model.get("reasoning_options")
            support_efforts = []
            if isinstance(reasoning_options, list):
                for option in reasoning_options:
                    if isinstance(option, dict) and option.get("type") == "effort" and isinstance(option.get("values"), list):
                        support_efforts.extend(str(value) for value in option["values"] if value)
            model_entry = {
                "id": model_id,
                "display_name": str(raw_model.get("name") or model_id),
                "description": str(raw_model.get("description") or ""),
                "max_context_size": context_size,
                "max_output_size": output_size,
                "capabilities": _catalog_model_capabilities(raw_model, provider_id),
                "capabilities_auto": False if any(key in raw_model for key in ("reasoning", "tool_call", "modalities")) else True,
                "modalities": copy.deepcopy(raw_model.get("modalities")) if isinstance(raw_model.get("modalities"), dict) else {},
                "reasoning": raw_model.get("reasoning") if isinstance(raw_model.get("reasoning"), bool) else None,
                "tool_call": raw_model.get("tool_call") if isinstance(raw_model.get("tool_call"), bool) else None,
                "status": str(raw_model.get("status") or ""),
                "cost": cost,
            }
            if support_efforts:
                model_entry["support_efforts"] = sorted(set(support_efforts))
            models.append(model_entry)

        providers.append({
            "id": provider_id,
            "name": str(raw_provider.get("name") or provider_id),
            "type": provider_type,
            "compatibility": compatibility,
            "base_url": base_url,
            "docs": str(raw_provider.get("doc") or raw_provider.get("docs") or ""),
            "env": [str(value) for value in env if value],
            "npm": str(raw_provider.get("npm") or ""),
            "models_count": len(models),
            "models": models,
            "source": source,
        })
    providers.sort(key=lambda item: (item["name"].lower(), item["id"].lower()))
    return {
        "providers": providers,
        "source": source,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


def _read_catalog_cache() -> dict | None:
    try:
        cached = json.loads(CATALOG_CACHE_PATH.read_text(encoding="utf-8"))
        if isinstance(cached, dict) and isinstance(cached.get("catalog"), dict):
            return cached
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return None


def _write_catalog_cache(catalog: dict) -> None:
    payload = json.dumps({"cached_at": time.time(), "catalog": catalog}, ensure_ascii=False)
    atomic_write_text(CATALOG_CACHE_PATH, payload)


def _load_catalog(force: bool = False) -> dict:
    """Load a fresh catalog, falling back to the last successful local snapshot."""
    with CATALOG_LOCK:
        cached = _read_catalog_cache()
        cached_catalog = cached.get("catalog") if cached else None
        cache_age = time.time() - float(cached.get("cached_at", 0)) if cached else float("inf")
        if not force and cached_catalog and cache_age < CATALOG_CACHE_TTL:
            return {**cached_catalog, "stale": False, "error": None}

        errors = []
        for loader, source in ((_run_kimi_catalog, "kimi-cli"), (_fetch_models_dev_catalog, "models.dev")):
            try:
                catalog = _normalize_catalog(loader(), source)
                _write_catalog_cache(catalog)
                return {**catalog, "stale": False, "error": None}
            except Exception as exc:
                errors.append(f"{source}: {str(exc)[:180]}")
                log.warning("Provider preset refresh failed via %s: %s", source, exc)
        if cached_catalog:
            return {**cached_catalog, "stale": True, "error": "; ".join(errors)}
        raise RuntimeError("无法加载 Provider 预设：" + "; ".join(errors))


def _find_catalog_provider(catalog: dict, provider_id: str) -> dict | None:
    for provider in catalog.get("providers", []):
        if provider.get("id") == provider_id:
            return provider
    return None


def _valid_http_url(value: str, required: bool = True) -> str:
    value = str(value or "").strip()
    if not value and not required:
        return ""
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Base URL 必须是有效的 http/https 地址")
    return value.rstrip("/")


def _provider_models_url(base_url: str, provider_type: str) -> str:
    base_url = base_url.rstrip("/")
    if provider_type == "anthropic" and not base_url.endswith("/v1"):
        return base_url + "/v1/models"
    if provider_type == "google-genai":
        return base_url + "/v1beta/models"
    if provider_type == "vertexai":
        raise ValueError("Vertex AI 需要项目和 ADC 配置，暂不支持通用 /models 测试")
    return base_url + "/models"


def _validate_headers(headers) -> dict[str, str]:
    if headers is None:
        return {}
    if not isinstance(headers, dict):
        raise ValueError("custom_headers 必须是对象")
    result = {}
    for key, value in headers.items():
        key = str(key).strip()
        if not key or any(ord(ch) < 33 for ch in key) or not isinstance(value, (str, int, float)):
            raise ValueError("custom_headers 包含无效值")
        result[key] = str(value)
    return result


def _extract_model_items(data) -> list[dict]:
    """Extract model records from common OpenAI, Google, and registry response shapes."""
    if isinstance(data, dict):
        raw_items = data.get("data") if isinstance(data.get("data"), list) else data.get("models")
    elif isinstance(data, list):
        raw_items = data
    else:
        raw_items = []
    if not isinstance(raw_items, list):
        return []
    result = []
    for item in raw_items:
        if isinstance(item, str):
            result.append({"id": item})
            continue
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("name")
        if isinstance(model_id, str) and model_id.startswith("models/"):
            model_id = model_id.split("/", 1)[1]
        if model_id:
            result.append({**item, "id": str(model_id)})
    return result


def _request_provider_models(base_url: str, provider_type: str, api_key: str = "", custom_headers: dict | None = None) -> tuple[object, list[dict]]:
    """Request a provider model list without persisting credentials."""
    base_url = _valid_http_url(base_url)
    provider_type = _normalize_type(provider_type)
    if provider_type not in VALID_PROVIDER_TYPES:
        raise ValueError("不支持的 Provider 协议类型")
    url = _provider_models_url(base_url, provider_type)
    headers = {"Accept": "application/json", "User-Agent": "Kimi-Code-Dashboard/ProviderTest"}
    if api_key:
        if provider_type == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        elif provider_type == "google-genai":
            headers["x-goog-api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"
    headers.update(_validate_headers(custom_headers))
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = resp.read(5 * 1024 * 1024 + 1)
    if len(payload) > 5 * 1024 * 1024:
        raise ValueError("Provider 返回内容过大")
    data = json.loads(payload.decode("utf-8"))
    return data, _extract_model_items(data)


def _safe_provider_id(value: str, label: str = "provider id") -> str:
    value = str(value or "").strip()
    if not value or len(value) > 160 or any(ord(ch) < 32 for ch in value):
        raise ValueError(f"{label} 无效")
    return value


def _model_alias(models: dict, provider_id: str, model_id: str) -> str:
    """Keep ordinary aliases readable and namespace collisions deterministically."""
    current = models.get(model_id)
    if current is None or current.get("provider") == provider_id:
        return model_id
    base = f"{provider_id}/{model_id}"
    current = models.get(base)
    if current is None or current.get("provider") == provider_id:
        return base
    digest = hashlib.sha1(f"{provider_id}:{model_id}".encode("utf-8")).hexdigest()[:8]
    candidate = f"{base}__{digest}"
    index = 2
    while candidate in models and models[candidate].get("provider") != provider_id:
        candidate = f"{base}__{digest}_{index}"
        index += 1
    return candidate


def _catalog_model_entry(provider_id: str, alias: str, model: dict) -> dict:
    entry = {
        "provider": provider_id,
        "model": model["id"],
        "display_name": model.get("display_name") or model["id"],
        "max_context_size": int(model.get("max_context_size") or 128000),
        "max_output_size": int(model.get("max_output_size") or 4096),
        "capabilities": list(model.get("capabilities") or []),
        "capabilities_auto": bool(model.get("capabilities_auto", False)),
    }
    if model.get("support_efforts"):
        entry["support_efforts"] = list(model["support_efforts"])
        entry["default_effort"] = "high" if "high" in entry["support_efforts"] else entry["support_efforts"][0]
    return entry


def _catalog_import_payload(body: dict) -> tuple[str, dict, list[dict], str]:
    """Validate import input against the current catalog and return normalized values."""
    catalog_id = _safe_provider_id(body.get("catalog_provider_id") or body.get("catalog_id"), "catalog provider id")
    catalog = _load_catalog()
    provider = _find_catalog_provider(catalog, catalog_id)
    if not provider:
        raise LookupError("Provider 预设不存在或已刷新，请重新选择")
    provider_id = _safe_provider_id(body.get("provider_id") or body.get("id") or catalog_id)
    if _is_protected_provider(provider_id):
        raise PermissionError("cannot import into built-in provider")
    if provider.get("compatibility") in {"manual", "unsupported"}:
        raise ValueError("该 Provider 预设需要手动配置，请使用“手动添加”入口")
    provider_type = _normalize_type(body.get("type") or provider.get("type"))
    if provider_type not in VALID_PROVIDER_TYPES:
        raise ValueError("该 Provider 预设没有可用的 Kimi Code 协议，请改用手动配置")
    base_url = _valid_http_url(body.get("base_url") or provider.get("base_url"), required=provider_type != "vertexai")
    selected_ids = body.get("model_ids") or body.get("selected_model_ids")
    if not isinstance(selected_ids, list) or not selected_ids or len(selected_ids) > 100:
        raise ValueError("至少选择一个、最多选择 100 个 Model")
    selected_ids = list(dict.fromkeys(str(value).strip() for value in selected_ids if isinstance(value, str) and value.strip()))
    if not selected_ids:
        raise ValueError("至少选择一个、最多选择 100 个 Model")

    live_models = body.get("tested_models")
    if not isinstance(live_models, list) or not live_models:
        raise ValueError("请先使用 API Key 测试连接，再选择要导入的 Model")
    model_by_id = {}
    for raw_model in live_models:
        if not isinstance(raw_model, dict):
            continue
        model_id = str(raw_model.get("id") or "").strip()
        if not model_id or model_id in model_by_id:
            continue
        try:
            context_size = int(raw_model.get("max_context_size") or 128000)
        except (TypeError, ValueError):
            context_size = 128000
        try:
            output_size = int(raw_model.get("max_output_size") or 4096)
        except (TypeError, ValueError):
            output_size = 4096
        model_by_id[model_id] = {
            "id": model_id,
            "display_name": str(raw_model.get("display_name") or model_id),
            "max_context_size": max(1, context_size),
            "max_output_size": max(1, output_size),
            "capabilities": [str(cap) for cap in raw_model.get("capabilities", []) if isinstance(cap, str)],
            "capabilities_auto": False,
        }
    selected_models = [model_by_id[model_id] for model_id in selected_ids if model_id in model_by_id]
    if len(selected_models) != len(selected_ids):
        raise ValueError("所选 Model 不属于本次连接测试结果，请重新测试后选择")
    default_model = body.get("default_model") or body.get("default_model_id") or selected_models[0]["id"]
    if default_model not in selected_ids:
        raise ValueError("默认 Model 必须是已选择的 Model")
    api_key = body.get("api_key")
    if api_key == MASK:
        api_key = ""
    if api_key is not None and not isinstance(api_key, str):
        raise ValueError("api_key 无效")
    if not api_key and provider_type != "vertexai":
        raise ValueError("API Key 不能为空")
    return provider_id, {
        "type": provider_type,
        "base_url": base_url,
        "api_key": api_key or "",
        "custom_headers": _validate_headers(body.get("custom_headers")),
        "env": body.get("env") if isinstance(body.get("env"), dict) else {},
    }, selected_models, default_model


def _is_protected_provider(pid: str) -> bool:
    """Built-in/managed providers should not be edited or deleted."""
    return pid.startswith("managed:") or pid == "kimi"


def _load() -> dict:
    return tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def _cleanup_old_backups(max_keep: int = 10) -> None:
    """Keep only the most recent *max_keep* .bak files for config.toml."""
    baks = sorted(glob.glob(str(CONFIG_PATH) + ".*.bak"), key=lambda p: Path(p).stat().st_mtime, reverse=True)
    for old in baks[max_keep:]:
        try:
            Path(old).unlink()
        except OSError:
            pass


def _save(cfg: dict) -> None:
    backup = CONFIG_PATH.with_suffix(f".toml.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak")
    try:
        shutil.copy2(CONFIG_PATH, backup)
    except Exception as e:
        log.warning("Could not backup config.toml: %s", e)
    _cleanup_old_backups()
    atomic_write_text(CONFIG_PATH, tomli_w.dumps(cfg))


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
            "max_output_size": m.get("max_output_size") or m.get("max_tokens", 0),
            "capabilities": m.get("capabilities", []),
            "capabilities_auto": m.get("capabilities_auto"),
            "support_efforts": m.get("support_efforts", []),
            "default_effort": m.get("default_effort", ""),
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


@bp.route("/catalog/providers", methods=["GET"])
def api_catalog_providers():
    """Return a searchable summary of the read-only Provider presets."""
    try:
        query = (request.args.get("query") or "").strip().lower()
        compatibility = (request.args.get("compatibility") or "").strip().lower()
        importable = (request.args.get("importable") or "").strip().lower() in {"1", "true", "yes"}
        try:
            offset = max(0, int(request.args.get("offset", 0)))
            limit = min(100, max(1, int(request.args.get("limit", 30))))
        except ValueError:
            return jsonify({"error": "offset/limit 无效"}), 400
        catalog = _load_catalog()
        cfg = _load()
        configured = set((cfg.get("providers") or {}).keys())
        providers = []
        for provider in catalog.get("providers", []):
            haystack = " ".join((provider.get("id", ""), provider.get("name", ""), provider.get("type", ""))).lower()
            if query and query not in haystack:
                continue
            if compatibility and provider.get("compatibility") != compatibility:
                continue
            if importable and provider.get("compatibility") not in {"direct", "openai-compatible"}:
                continue
            providers.append({
                key: provider.get(key)
                for key in ("id", "name", "type", "compatibility", "base_url", "docs", "env", "models_count", "source")
            })
            providers[-1]["configured"] = provider.get("id") in configured
        page = providers[offset:offset + limit]
        return jsonify({
            "providers": page,
            "total": len(providers),
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < len(providers),
            "source": catalog.get("source"),
            "fetched_at": catalog.get("fetched_at"),
            "stale": bool(catalog.get("stale")),
            "error": catalog.get("error"),
        })
    except Exception as e:
        log.error("Failed to list Provider presets: %s", e)
        return jsonify({"error": str(e)}), 502


@bp.route("/catalog/providers/<path:provider_id>", methods=["GET"])
def api_catalog_provider(provider_id: str):
    """Return one Provider preset and its model metadata without credentials."""
    try:
        provider_id = _safe_provider_id(provider_id, "catalog provider id")
        catalog = _load_catalog()
        provider = _find_catalog_provider(catalog, provider_id)
        if not provider:
            return jsonify({"error": "Provider 预设不存在"}), 404
        cfg = _load()
        configured = provider_id in (cfg.get("providers") or {})
        result = copy.deepcopy(provider)
        result["configured"] = configured
        return jsonify({
            "provider": result,
            "source": catalog.get("source"),
            "fetched_at": catalog.get("fetched_at"),
            "stale": bool(catalog.get("stale")),
            "error": catalog.get("error"),
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        log.error("Failed to load Provider preset %s: %s", provider_id, e)
        return jsonify({"error": str(e)}), 502


@bp.route("/catalog/refresh", methods=["POST"])
def api_catalog_refresh():
    """Force a Provider preset refresh and retain the old snapshot on failure."""
    try:
        catalog = _load_catalog(force=True)
        status = 200 if not catalog.get("stale") else 502
        return jsonify({
            "ok": status == 200,
            "source": catalog.get("source"),
            "fetched_at": catalog.get("fetched_at"),
            "provider_count": len(catalog.get("providers", [])),
            "stale": bool(catalog.get("stale")),
            "error": catalog.get("error"),
        }), status
    except Exception as e:
        log.error("Failed to refresh Provider presets: %s", e)
        return jsonify({"error": str(e)}), 502


def _test_model_summary(model: dict, provider_id: str) -> dict:
    model_id = str(model.get("id") or "")
    limits = model.get("limit") if isinstance(model.get("limit"), dict) else {}
    try:
        context_size = int(limits.get("context") or _infer_context_size(model_id))
    except (TypeError, ValueError):
        context_size = _infer_context_size(model_id)
    try:
        output_size = int(limits.get("output") or 4096)
    except (TypeError, ValueError):
        output_size = 4096
    return {
        "id": model_id,
        "display_name": str(model.get("name") or model_id),
        "max_context_size": max(1, context_size),
        "max_output_size": max(1, output_size),
        "capabilities": _catalog_model_capabilities(model, provider_id),
    }


@bp.route("/catalog/test", methods=["POST"])
def api_catalog_test():
    """Test a Provider connection in memory; never save or echo the API key."""
    body = request.get_json(silent=True) or {}
    try:
        provider_id = _safe_provider_id(body.get("provider_id") or body.get("catalog_provider_id") or "provider")
        provider_type = _normalize_type(body.get("type") or "openai")
        base_url = _valid_http_url(body.get("base_url"), required=provider_type != "vertexai")
        api_key = body.get("api_key") or ""
        if not isinstance(api_key, str):
            raise ValueError("api_key 无效")
        if not api_key and provider_type != "vertexai":
            raise ValueError("API Key 不能为空")
        if provider_type == "vertexai":
            return jsonify({"ok": False, "error": "Vertex AI 需要本机 ADC、项目和区域配置，暂不支持通用连接测试"}), 400
        _, models = _request_provider_models(base_url, provider_type, api_key, body.get("custom_headers"))
        return jsonify({
            "ok": True,
            "provider": provider_id,
            "model_count": len(models),
            "models": [_test_model_summary(model, provider_id) for model in models[:100]],
        })
    except urllib.error.HTTPError as e:
        log.warning("Provider preset connection test returned HTTP %s for %s", e.code, body.get("provider_id") or body.get("catalog_provider_id") or "provider")
        return jsonify({"ok": False, "error": f"Provider 返回 HTTP {e.code}"}), 502
    except (urllib.error.URLError, TimeoutError) as e:
        log.warning("Provider preset connection test failed: %s", type(e).__name__)
        return jsonify({"ok": False, "error": "无法连接 Provider，请检查 Base URL、网络和 API Key"}), 502
    except (ValueError, json.JSONDecodeError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        log.error("Provider preset connection test failed: %s", type(e).__name__)
        return jsonify({"ok": False, "error": "Provider 连接测试失败"}), 502


@bp.route("/catalog/import", methods=["POST"])
def api_catalog_import():
    """Import one preset Provider and only the models explicitly selected by the user."""
    body = request.get_json(silent=True) or {}
    try:
        provider_id, provider_entry, selected_models, default_model_id = _catalog_import_payload(body)
        overwrite = bool(body.get("overwrite"))
        with config_lock(lock_for(CONFIG_PATH)):
            cfg = _load()
            providers = cfg.setdefault("providers", {})
            models = cfg.setdefault("models", {})
            old_provider = providers.get(provider_id)
            if old_provider is not None and not overwrite:
                return jsonify({"error": f"Provider '{provider_id}' 已存在，请确认覆盖或更换 ID", "conflict": True}), 409

            entry = dict(provider_entry)
            if old_provider and not entry.get("api_key") and old_provider.get("api_key"):
                entry["api_key"] = old_provider["api_key"]
            if old_provider and not entry.get("custom_headers") and old_provider.get("custom_headers"):
                entry["custom_headers"] = old_provider["custom_headers"]
            if old_provider and not entry.get("env") and old_provider.get("env"):
                entry["env"] = old_provider["env"]
            providers[provider_id] = entry

            aliases = {}
            for model in selected_models:
                model_id = model["id"]
                alias = _model_alias(models, provider_id, model_id)
                models[alias] = _catalog_model_entry(provider_id, alias, model)
                aliases[model_id] = alias

            explicit_default = bool(body.get("default_model") or body.get("default_model_id"))
            if old_provider and not explicit_default and cfg.get("default_model"):
                final_default = cfg["default_model"]
            else:
                final_default = aliases[default_model_id]
                cfg["default_model"] = final_default
            _save(cfg)

        return jsonify({
            "ok": True,
            "provider": provider_id,
            "overwritten": old_provider is not None,
            "models": [{"id": alias, "model": model_id} for model_id, alias in aliases.items()],
            "default_model": final_default,
        })
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    except urllib.error.HTTPError as e:
        return jsonify({"error": f"Provider 返回 HTTP {e.code}"}), 502
    except (ValueError, json.JSONDecodeError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        log.error("Failed to import Provider preset: %s", type(e).__name__)
        return jsonify({"error": "Provider 导入失败，请检查 config.toml 和目录状态"}), 500


@bp.route("/provider", methods=["POST"])
def api_save_provider():
    body = request.get_json(silent=True) or {}
    pid = (body.get("id") or "").strip()
    if not pid:
        return jsonify({"error": "provider id required"}), 400
    if _is_protected_provider(pid):
        return jsonify({"error": "cannot edit built-in provider"}), 403

    try:
        with config_lock(lock_for(CONFIG_PATH)):
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
        with config_lock(lock_for(CONFIG_PATH)):
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


def _infer_model_capabilities(model_id: str, provider: str = "") -> list[str]:
    """Guess common chat model capabilities from provider and model name."""
    mid = (model_id or "").lower()
    pid = (provider or "").lower()
    specialized = any(k in mid for k in ("embedding", "moderation", "whisper", "transcri", "tts", "speech", "dall-e", "gpt-image", "music"))
    if specialized:
        return []

    caps: set[str] = set()
    mainstream = any(k in f"{pid} {mid}" for k in ("minimax", "kimi", "moonshot", "gpt", "openai", "claude", "anthropic", "gemini", "google", "deepseek", "qwen", "mistral", "llama"))
    if mainstream or any(k in mid for k in ("vision", "multimodal", "-vl", "_vl", "omni")):
        caps.add("tool_use")
    if any(k in pid for k in ("minimax", "kimi", "moonshot", "openai", "anthropic", "claude", "gemini", "google")) or any(k in mid for k in ("gpt-4", "gpt-5", "claude", "gemini", "kimi", "moonshot", "minimax-m", "vision", "multimodal", "-vl", "_vl", "omni")):
        caps.add("image_in")
    if any(k in pid for k in ("gemini", "google")) or any(k in mid for k in ("kimi-k2.5", "kimi-k2.6", "kimi-k2.7", "kimi-k3", "moonshot", "minimax-m3", "video")):
        caps.add("video_in")
    if any(k in mid for k in ("thinking", "reasoner", "reasoning", "deepseek-reasoner", "o1", "o2", "o3", "o4", "r1", "r2", "kimi-k2.5", "kimi-k2.6", "kimi-k2.7", "kimi-k3", "minimax-m2", "minimax-m2.5", "minimax-m2.7", "claude-4")):
        caps.add("thinking")
    if any(k in mid for k in ("thinking", "reasoner", "reasoning", "deepseek-reasoner", "o1", "o2", "o3", "o4", "r1", "r2", "kimi-k3")):
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
        # 部分 provider（如 opencode zen）套了 Cloudflare，默认 urllib UA 会被 Error 1010 拦截
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
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
                "capabilities": _infer_model_capabilities(mid, pid),
                "max_context_size": _infer_context_size(mid),
                "max_output_size": 4096,
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
        with config_lock(lock_for(CONFIG_PATH)):
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
                "max_output_size": int(body.get("max_output_size") or body.get("max_tokens") or old.get("max_output_size") or old.get("max_tokens", 4096)),
            }
            caps = body.get("capabilities")
            if caps is not None:
                entry["capabilities"] = list(caps)
            elif "capabilities" in old:
                entry["capabilities"] = old["capabilities"]
            if "capabilities_auto" in body:
                entry["capabilities_auto"] = bool(body.get("capabilities_auto"))
            elif "capabilities_auto" in old:
                entry["capabilities_auto"] = old["capabilities_auto"]

            if body.get("display_name"):
                entry["display_name"] = body["display_name"]
            elif "display_name" in old:
                entry["display_name"] = old["display_name"]

            # 推理强度开关（同 K3 三档：low / high / max）
            # 前端传 effort_enabled=true → 写入 support_efforts + default_effort
            # 前端传 effort_enabled=false → 删除这两个字段
            effort_enabled = body.get("effort_enabled")
            if effort_enabled is True:
                entry["support_efforts"] = ["low", "high", "max"]
                entry["default_effort"] = body.get("default_effort") or "high"
            elif effort_enabled is False:
                # 显式关闭：不写入，也不保留旧值
                pass
            elif "default_effort" in old:
                # 未传 effort_enabled：保留旧值
                entry["default_effort"] = old["default_effort"]
                entry["support_efforts"] = old.get("support_efforts", ["low", "high", "max"])

            models[mid] = entry
            _save(cfg)
        return jsonify({"ok": True, "model": mid})
    except Exception as e:
        log.error("Failed to save model: %s", e)
        return jsonify({"error": str(e)}), 500


def _ordered_entries(entries: dict, requested: list) -> dict:
    """Rebuild a mapping in requested order while preserving omitted entries."""
    ordered = {}
    seen = set()
    for key in requested:
        if isinstance(key, str) and key in entries and key not in seen:
            ordered[key] = entries[key]
            seen.add(key)
    for key, value in entries.items():
        if key not in seen:
            ordered[key] = value
    return ordered


@bp.route("/provider-order", methods=["POST"])
def api_save_provider_order():
    body = request.get_json(silent=True) or {}
    requested = body.get("order")
    if not isinstance(requested, list):
        return jsonify({"error": "provider order must be a list"}), 400
    try:
        with config_lock(lock_for(CONFIG_PATH)):
            cfg = _load()
            providers = cfg.get("providers", {})
            cfg["providers"] = _ordered_entries(providers, requested)
            _save(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        log.error("Failed to save provider order: %s", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/model-order", methods=["POST"])
def api_save_model_order():
    body = request.get_json(silent=True) or {}
    provider = (body.get("provider") or "").strip()
    requested = body.get("order")
    if not provider:
        return jsonify({"error": "provider required"}), 400
    if not isinstance(requested, list):
        return jsonify({"error": "model order must be a list"}), 400
    try:
        with config_lock(lock_for(CONFIG_PATH)):
            cfg = _load()
            models = cfg.get("models", {})
            provider_models = {mid: model for mid, model in models.items() if model.get("provider", "") == provider}
            ordered_provider_models = _ordered_entries(provider_models, requested)
            reordered = {}
            inserted = False
            for mid, model in models.items():
                if model.get("provider", "") == provider:
                    if not inserted:
                        reordered.update(ordered_provider_models)
                        inserted = True
                else:
                    reordered[mid] = model
            if provider_models and not inserted:
                reordered.update(ordered_provider_models)
            cfg["models"] = reordered
            _save(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        log.error("Failed to save model order: %s", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/model/<path:mid>", methods=["DELETE"])
def api_delete_model(mid: str):
    try:
        with config_lock(lock_for(CONFIG_PATH)):
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
        with config_lock(lock_for(CONFIG_PATH)):
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
