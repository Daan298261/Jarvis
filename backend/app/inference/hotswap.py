from __future__ import annotations

from urllib.parse import urlparse

from ..config import load_settings, save_settings
from ..persona.owner_chat import rebind_owner_conversations_after_hotswap
from .backends import (
    DEFAULT_PORTS,
    LMSTUDIO_ALIASES,
    probe_remote_server,
    resolve_advertised_model,
    suggested_port,
)
from .manager import MANAGER
from .profiles import PROFILES
from .runtime_profiles import RuntimeProfile

LOCAL_BACKEND_ALIASES = {"llama.cpp", "llamacpp", "llama_cpp", "llama", "local"}


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


def _normalize_provider(provider: str) -> str:
    cleaned = (provider or "").strip().lower()
    if cleaned in LMSTUDIO_ALIASES:
        return "lmstudio"
    return cleaned


def _provider_needs_remote_probe(provider: str) -> bool:
    normalized = _normalize_provider(provider)
    if not normalized or normalized in LOCAL_BACKEND_ALIASES:
        return False
    return True


def _resolve_builtin_profile_name(runtime: RuntimeProfile, fallback: str) -> str:
    candidate = (runtime.model_profile or "").strip()
    if candidate and candidate in PROFILES:
        return candidate
    if runtime.name in PROFILES:
        return runtime.name
    return fallback


def local_lmstudio_fallback_settings(settings):
    """Return a Jarvis-managed fallback for an unavailable local LM Studio server.

    A local catalog selection can legitimately point at LM Studio while it is
    running. It must not, however, leave a desktop unable to start after that
    optional server has been closed. Never apply this fallback to a LAN/remote
    endpoint: those are explicit operator-managed runtime choices.
    """
    provider = _normalize_provider(settings.inference.backend)
    host = (settings.inference.host or "").strip().lower()
    if provider != "lmstudio" or host not in {"127.0.0.1", "localhost", "::1"}:
        return None

    fallback = settings.model_copy(deep=True)
    fallback.inference.backend = "llama.cpp"
    fallback.inference.host = "127.0.0.1"
    fallback.inference.port = int(DEFAULT_PORTS["llama.cpp"])
    fallback.inference.remote_model = ""
    if fallback.inference.profile not in PROFILES:
        fallback.inference.profile = "bootstrap"
    return fallback


async def apply_runtime_profile_to_settings(runtime: RuntimeProfile) -> None:
    # Only save after the external runtime has answered its probe. A failed
    # click must never leave a stale LM Studio server as the next boot target.
    settings = load_settings().model_copy(deep=True)
    provider = _normalize_provider(runtime.provider or "")
    if provider == "lmstudio":
        settings.inference.backend = "lmstudio"
    elif provider:
        settings.inference.backend = provider

    host, port = parse_runtime_endpoint(runtime.endpoint)
    if provider == "lmstudio" and not (runtime.endpoint or "").strip():
        port = int(DEFAULT_PORTS["lmstudio"])
    elif provider:
        port = suggested_port(provider, port)
    settings.inference.host = host
    settings.inference.port = port

    hint = (runtime.model or "").strip()
    if _provider_needs_remote_probe(provider):
        probe = await probe_remote_server(
            host,
            port,
            settings.inference.api_key,
            timeout=8.0,
            retry=True,
        )
        if not probe.get("ok"):
            detail = probe.get("error") or "inference server did not respond"
            raise RuntimeError(
                f"Could not reach {provider or 'inference server'} at {host}:{port}. "
                f"Load the model in LM Studio (or start the server), then try again. ({detail})"
            )
        advertised = list(probe.get("models") or [])
        resolved = resolve_advertised_model(hint, advertised)
        if hint and advertised and resolved == hint and hint not in advertised:
            if not any(hint.lower() in name.lower() for name in advertised):
                shown = ", ".join(advertised[:5])
                raise RuntimeError(
                    f"Model '{hint}' is not loaded on the server. Currently loaded: {shown}"
                )
        settings.inference.remote_model = resolved
    else:
        settings.inference.remote_model = hint

    if runtime.model_profile and runtime.model_profile in PROFILES:
        settings.inference.profile = runtime.model_profile
    if runtime.context_limit:
        settings.inference.context_size = int(runtime.context_limit)
    save_settings(settings)


async def activate_runtime_profile(runtime: RuntimeProfile, *, force: bool = True):
    from ..security.hexstrike import HEXSTRIKE, is_hexstrike_suite, is_suite_runtime

    if is_hexstrike_suite(runtime) or is_suite_runtime(runtime):
        await HEXSTRIKE.ensure_started()
        return MANAGER.state

    if HEXSTRIKE.is_running:
        await HEXSTRIKE.stop()

    settings = load_settings()
    previous_context = int(MANAGER.state.context_size or settings.inference.context_size or 0)
    await apply_runtime_profile_to_settings(runtime)
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
