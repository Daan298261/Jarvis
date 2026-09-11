from __future__ import annotations

from urllib.parse import urlparse

from ..config import load_settings, save_settings
from .manager import MANAGER
from .profiles import PROFILES
from .runtime_profiles import RuntimeProfile
from ..persona.owner_chat import rebind_owner_conversations_after_hotswap


def parse_runtime_endpoint(endpoint: str) -> tuple[str, int]:
    raw = (endpoint or "").strip()
    if not raw:
        return "127.0.0.1", 8088
    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8088
        return host, int(port)
    if ":" in raw:
        host, port_text = raw.rsplit(":", 1)
        try:
            return (host.strip() or "127.0.0.1"), int(port_text.strip())
        except ValueError:
            return raw, 8088
    return raw, 8088


def _resolve_builtin_profile_name(runtime: RuntimeProfile, fallback: str) -> str:
    candidate = (runtime.model_profile or "").strip()
    if candidate and candidate in PROFILES:
        return candidate
    if runtime.name in PROFILES:
        return runtime.name
    return fallback


def apply_runtime_profile_to_settings(runtime: RuntimeProfile) -> None:
    settings = load_settings()
    provider = (runtime.provider or "").strip().lower()
    if provider in {"lmstudio", "lm-studio", "lm_studio"}:
        settings.inference.backend = "lmstudio"
    elif provider:
        settings.inference.backend = provider
    host, port = parse_runtime_endpoint(runtime.endpoint)
    settings.inference.host = host
    settings.inference.port = port
    settings.inference.remote_model = (runtime.model or "").strip()
    if runtime.context_limit:
        settings.inference.context_size = int(runtime.context_limit)
    save_settings(settings)


async def activate_runtime_profile(runtime: RuntimeProfile, *, force: bool = True):
    settings = load_settings()
    previous_context = int(MANAGER.state.context_size or settings.inference.context_size or 0)
    apply_runtime_profile_to_settings(runtime)
    settings = load_settings()
    profile_name = _resolve_builtin_profile_name(runtime, settings.inference.profile)
    context_size = int(runtime.context_limit or settings.inference.context_size or 0) or None
    await MANAGER.load(
        settings,
        profile_name,
        context_size=context_size,
        force=force,
    )
    new_context = int(MANAGER.state.context_size or context_size or settings.inference.context_size or 0)
    rebind_owner_conversations_after_hotswap(
        new_context,
        previous_context_limit=previous_context if previous_context > 0 else None,
    )
    return MANAGER.state
