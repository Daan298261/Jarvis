from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent.autonomy import catalog as autonomy_catalog, resolve_autonomy
from ..agent.execution import available_modes, resolve_mode
from ..config import AppSettings, apply_logging_level, load_settings, logs_dir, save_settings
from ..inference.endpoint import env_inference_api_key, inference_base_url, is_remote_inference, normalize_base_url
from ..security import MIN_TOKEN_LENGTH, token_is_too_short, usable_auth_token, uvicorn_bind_host
from ..tools.registry import REGISTRY

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    autonomy: str | None = None
    execution_mode: str | None = None
    allowed_directories: list[str] | None = None
    default_timeout_seconds: int | None = None
    retry_limit: int | None = None
    logging_level: str | None = None
    lan_access: bool | None = None
    bind_host: str | None = None
    bind_port: int | None = None
    backup_enabled: bool | None = None
    profile: str | None = None
    browser_headless: bool | None = None
    browser_timeout_ms: int | None = None
    voice_speak_results: bool | None = None
    voice_stt_model: str | None = None
    inference_backend: str | None = None
    inference_host: str | None = None
    inference_port: int | None = None
    inference_base_url: str | None = None
    inference_model: str | None = None


def _payload(settings: AppSettings) -> dict:
    payload = settings.model_dump()
    payload.pop("auth_token", None)
    payload["autonomy"] = resolve_autonomy(settings.autonomy).name
    payload["autonomy_modes"] = autonomy_catalog()
    payload["execution_modes"] = [
        {"name": mode.name, "label": mode.label, "description": mode.description}
        for mode in available_modes()
    ]
    payload["auth_token_configured"] = bool(usable_auth_token())
    payload["auth_token_too_short"] = token_is_too_short()
    payload["bind_host"] = uvicorn_bind_host(settings.lan_access)
    payload["inference_api_key_configured"] = bool(env_inference_api_key())
    payload["inference_remote"] = is_remote_inference(settings)
    payload["inference_effective_url"] = inference_base_url(settings)
    payload["inference_note"] = (
        "Jarvis talks OpenAI-compatible /v1/chat/completions. Point it at another llama.cpp, vLLM, or LM Studio host. "
        "API keys stay in JARVIS_INFERENCE_API_KEY (never settings.json). Reload the model after changing this."
        if is_remote_inference(settings)
        else "Default is local llama.cpp on this PC (127.0.0.1:8088). Switch to OpenAI-compatible to use a GPU server without redesigning Jarvis."
    )
    inf = payload.get("inference")
    if isinstance(inf, dict):
        inf.pop("api_key", None)
    payload["listen_note"] = (
        "Restart Jarvis after changing LAN access so the bind address takes effect. "
        "A local llama-server process still binds 127.0.0.1:8088. Point inference at another "
        "OpenAI-compatible host on the Model page. Windows Firewall may prompt for Private network; do not allow Public."
    )
    payload["log_file"] = str(logs_dir() / "jarvis.log")
    payload["logging_levels"] = ["DEBUG", "INFO", "WARNING", "ERROR"]
    return payload


@router.get("")
async def get_settings():
    return _payload(load_settings())


@router.put("")
async def update_settings(body: SettingsUpdate):
    settings = load_settings()
    if body.autonomy is not None:
        key = body.autonomy.strip().lower()
        if key not in {"interactive", "trusted", "autonomous"}:
            raise HTTPException(400, "Autonomy must be interactive, trusted, or autonomous")
        settings.autonomy = resolve_autonomy(key).name
    if body.execution_mode is not None:
        settings.execution_mode = resolve_mode(body.execution_mode).name
    if body.allowed_directories is not None:
        settings.allowed_directories = body.allowed_directories
    if body.default_timeout_seconds is not None:
        settings.default_timeout_seconds = body.default_timeout_seconds
    if body.retry_limit is not None:
        settings.retry_limit = body.retry_limit
    if body.logging_level is not None:
        key = body.logging_level.strip().upper()
        if key not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise HTTPException(400, "logging_level must be DEBUG, INFO, WARNING, or ERROR")
        settings.logging_level = key
    if body.browser_timeout_ms is not None:
        timeout = int(body.browser_timeout_ms)
        if timeout < 1000 or timeout > 300000:
            raise HTTPException(400, "browser_timeout_ms must be between 1000 and 300000")
        settings.browser.timeout_ms = timeout
    if body.lan_access is not None:
        if body.lan_access and not usable_auth_token():
            if token_is_too_short():
                raise HTTPException(
                    400,
                    f"JARVIS_AUTH_TOKEN must be at least {MIN_TOKEN_LENGTH} characters. Bind stays 127.0.0.1.",
                )
            raise HTTPException(
                400,
                "LAN access requires JARVIS_AUTH_TOKEN in the user environment. Bind stays 127.0.0.1.",
            )
        settings.lan_access = body.lan_access
    if body.bind_host is not None:
        raise HTTPException(400, "bind_host is not settable; enable LAN access with JARVIS_AUTH_TOKEN instead")
    settings.bind_host = uvicorn_bind_host(settings.lan_access)
    settings.auth_required = bool(settings.lan_access and usable_auth_token())
    if body.bind_port is not None:
        settings.bind_port = body.bind_port
    if body.backup_enabled is not None:
        settings.backup_enabled = body.backup_enabled
    if body.profile is not None:
        settings.inference.profile = body.profile
    if body.browser_headless is not None:
        settings.browser.headless = body.browser_headless
    if body.voice_speak_results is not None:
        settings.voice.speak_results = body.voice_speak_results
    if body.voice_stt_model is not None:
        key = body.voice_stt_model.strip().lower()
        if key not in {"tiny", "tiny.en", "base", "base.en"}:
            raise HTTPException(400, "Voice STT model must be tiny, tiny.en, base, or base.en")
        settings.voice.stt_model = key
    if body.inference_backend is not None:
        key = body.inference_backend.strip().lower()
        if key in {"llama.cpp", "local", "llamacpp", "llama"}:
            settings.inference.backend = "llama.cpp"
            if body.inference_base_url is None:
                settings.inference.base_url = ""
            if body.inference_host is None:
                settings.inference.host = "127.0.0.1"
        elif key in {"remote", "openai", "openai-compat", "openai_compat", "vllm"}:
            settings.inference.backend = "openai-compat"
        else:
            raise HTTPException(400, "inference_backend must be llama.cpp or openai-compat")
    if body.inference_host is not None:
        host = body.inference_host.strip() or "127.0.0.1"
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        settings.inference.host = host
    if body.inference_port is not None:
        port = int(body.inference_port)
        if port < 1 or port > 65535:
            raise HTTPException(400, "inference_port must be 1-65535")
        settings.inference.port = port
    if body.inference_base_url is not None:
        raw = body.inference_base_url.strip()
        if raw:
            url = normalize_base_url(raw)
            if not url:
                raise HTTPException(400, "inference_base_url must be an http(s) URL")
            settings.inference.base_url = url
        else:
            settings.inference.base_url = ""
    if body.inference_model is not None:
        settings.inference.model = body.inference_model.strip() or "Qwen3.5-9B-Abliterated"
    if any(
        value is not None
        for value in (
            body.inference_backend,
            body.inference_host,
            body.inference_port,
            body.inference_base_url,
            body.inference_model,
        )
    ):
        from ..inference.endpoint import apply_inference_settings

        dumped = apply_inference_settings(settings.inference.model_dump(), env=False)
        settings.inference = type(settings.inference).model_validate(dumped)
    save_settings(settings)
    apply_logging_level(settings.logging_level)
    REGISTRY.apply_settings(settings)
    return _payload(settings)
