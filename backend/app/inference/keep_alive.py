"""One place that decides how long a model ANZU loads may stay resident.

``inference.keep_warm`` (default OFF) selects between the idle policy and the
always-warm behaviour. Every Ollama / LM Studio load or request ANZU sends, and the
idle-unload timer, read this module; nothing else may spell a keep-alive value.
Only models ANZU itself loaded (``LoadedModels``) ever receive these values.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from .. import config as _config
from ..config import AppSettings
from .backends import LMSTUDIO_ALIASES, OLLAMA_ALIASES
from .loaded_models import LMSTUDIO, LOADED, OLLAMA

DEFAULT_IDLE_UNLOAD_SECONDS = 300
# Always-warm (Keep warm ON): Ollama pins the model instead of relying on an expiry.
OLLAMA_PINNED_KEEP_ALIVE = "-1"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_DEFAULT_PORTS = {11434: OLLAMA, 1234: LMSTUDIO}

_cache: tuple[tuple, AppSettings] | None = None


def _stamp(path) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def current_settings() -> AppSettings:
    """Settings for per-request reads: re-read only when a settings file changed."""
    global _cache
    path, default = _config.settings_path(), _config.default_config_path()
    key = (str(path), _stamp(path), str(default), _stamp(default))
    if _cache is None or _cache[0] != key:
        _cache = (key, _config.load_settings())
    return _cache[1]


def keep_warm_enabled(settings: AppSettings | None = None) -> bool:
    return bool((settings or current_settings()).inference.keep_warm)


def idle_unload_seconds(settings: AppSettings | None = None) -> int:
    return int((settings or current_settings()).inference.idle_unload_seconds)


def ollama_keep_alive(settings: AppSettings | None = None) -> str:
    """``keep_alive`` for an ANZU-originated Ollama request: ``"300s"`` idle policy, ``"-1"`` pinned."""
    app = settings or current_settings()
    return OLLAMA_PINNED_KEEP_ALIVE if keep_warm_enabled(app) else f"{idle_unload_seconds(app)}s"


def lmstudio_ttl_seconds(settings: AppSettings | None = None) -> int | None:
    """LM Studio ``ttl`` in seconds, or ``None`` (no TTL) when Keep warm is on."""
    app = settings or current_settings()
    return None if keep_warm_enabled(app) else idle_unload_seconds(app)


def backend_family(base_url: str, settings: AppSettings | None = None) -> str | None:
    """``ollama`` / ``lmstudio`` when ``base_url`` is the loopback server of that kind."""
    parsed = urlparse(base_url)
    host, port = (parsed.hostname or "").lower(), parsed.port
    if host not in LOOPBACK or port is None:
        return None
    inference = (settings or current_settings()).inference
    if port == inference.port and (inference.host or "").lower() in LOOPBACK:
        configured = (inference.backend or "").strip().lower()
        if configured in OLLAMA_ALIASES:
            return OLLAMA
        if configured in LMSTUDIO_ALIASES:
            return LMSTUDIO
    return _DEFAULT_PORTS.get(port)


def request_extras(base_url: str, model: str, settings: AppSettings | None = None) -> dict[str, Any]:
    """Keep-alive fields for one request to ``model`` at ``base_url`` (empty for foreign models).

    Ollama resets a model to its own default whenever a request omits ``keep_alive``, so every
    ANZU request to an ANZU-loaded Ollama model carries it. LM Studio gets ``ttl`` while Keep
    warm is off.
    """
    family = backend_family(base_url, settings)
    if family is None or LOADED.match(family, [model]) is None:
        return {}
    if family == OLLAMA:
        return {"keep_alive": ollama_keep_alive(settings)}
    ttl = lmstudio_ttl_seconds(settings)
    return {} if ttl is None else {"ttl": ttl}
