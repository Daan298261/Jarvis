"""One place that decides how long a model ANZU loads may stay resident.

``inference.keep_warm`` (default OFF) selects between the idle policy and the
always-warm behaviour. Every Ollama / LM Studio load or request ANZU sends, and the
idle-unload timer, read this module; nothing else may spell a keep-alive value.
Only models ANZU itself loaded (``LoadedModels``) ever receive these values.
"""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from .. import config as _config
from ..config import AppSettings
from .backends import LMSTUDIO_ALIASES, OLLAMA_ALIASES, inference_headers
from .loaded_models import LMSTUDIO, LOADED, OLLAMA, canonical

log = logging.getLogger(__name__)
# Models ANZU never sends a request, an unload or a keep_alive to, whatever else is true
# (CoS/PG ruling: Black Grid's ingest model shares the owner's Ollama). A backstop in front of
# the ``LoadedModels`` ledger, which already fails closed for any model ANZU did not load.
DENIED_MODELS = frozenset({"bgm-ingest-9b"})

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


def lmstudio_ttl_seconds(settings: AppSettings | None = None, model: str = "") -> int | None:
    """LM Studio ``ttl`` in seconds, or ``None`` (no TTL) when Keep warm is on or ``model`` is denied."""
    app = settings or current_settings()
    if model and is_denied(model):
        return None
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
    """Keep-alive fields for one request to ``model`` at ``base_url`` (empty for a denied model).

    Ollama resets a model to its own default whenever a request omits ``keep_alive``, so *every*
    ANZU request to a loopback Ollama model carries it, whether or not ANZU loaded it (the
    value only restates the idle policy; ``bgm-ingest-9b`` is the one exception). Unloads, the
    idle timer and the release path still touch only models in the ledger. LM Studio gets
    ``ttl`` only for an instance ANZU loaded, and only while Keep warm is off.
    """
    family = backend_family(base_url, settings)
    if family is None or is_denied(model):
        return {}
    if family == OLLAMA:
        return {"keep_alive": ollama_keep_alive(settings)}
    if LOADED.match(family, [model]) is None:
        return {}
    ttl = lmstudio_ttl_seconds(settings, model)
    return {} if ttl is None else {"ttl": ttl}


def is_denied(model: str) -> bool:
    """True for a model ANZU must never address (any tag of a denied name)."""
    name = canonical(model).split(":", 1)[0].rsplit("/", 1)[-1]
    return name in DENIED_MODELS


class DeniedModelError(ValueError):
    """An Ollama request named a model ANZU may never address."""


def ollama_body(model: str, body: dict[str, Any] | None = None, *, release: bool = False,
                settings: AppSettings | None = None) -> dict[str, Any]:
    """The one place an Ollama request body gets its ``keep_alive``.

    ``"300s"`` (idle window) with Keep warm off, ``"-1"`` with it on, ``0`` for an explicit
    unload (``release=True``). Ollama applies its own 5 minute default to a request that omits
    the field, so every native request ANZU sends goes through here. Raises for a denied model.
    """
    if is_denied(model):
        raise DeniedModelError(f"{model} is not an ANZU model; ANZU never sends it a request.")
    return {**(body or {}), "model": model, "keep_alive": 0 if release else ollama_keep_alive(settings)}


async def ollama_request(client: httpx.AsyncClient, host: str, port: int, path: str, model: str,
                         body: dict[str, Any] | None = None, *, release: bool = False,
                         settings: AppSettings | None = None) -> httpx.Response:
    """POST a native Ollama generate or chat request with the policy keep_alive (the only sender)."""
    address = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return await client.post(f"http://{address}:{int(port)}{path}", json=ollama_body(model, body, release=release, settings=settings))


async def touch_ollama_if_resident(base_url: str, model: str, api_key: str = "",
                                   settings: AppSettings | None = None) -> bool:
    """Keep-alive touch after a turn served through Ollama's OpenAI-compatible ``/v1``.

    ``/v1`` honours a ``keep_alive`` field only on Ollama >= 0.35 and silently ignores it on
    older builds, so the policy must not depend on it: a prompt-less native ``/api/generate``
    carrying the policy value follows the turn, but only when ``/api/ps`` lists the model (a
    touch never loads anything). Any resident non-denied model ANZU just served is touched; errors never reach the turn.
    """
    from .idle_unload import warm_blocked

    if warm_blocked():  # after Unload / idle unload nothing is touched or reloaded until an owner turn or Load
        return False
    if backend_family(base_url, settings) != OLLAMA or is_denied(model):
        return False
    parsed = urlparse(base_url)
    host, port = parsed.hostname or "127.0.0.1", int(parsed.port or 11434)
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False, headers=inference_headers(api_key)) as client:
            ps = await client.get(f"http://{host}:{port}/api/ps")
            ps.raise_for_status()
            resident = {canonical(str(m.get("name") or m.get("model") or "")) for m in (ps.json().get("models") or []) if isinstance(m, dict)}
            if canonical(model) not in resident:
                return False
            response = await ollama_request(client, host, port, "/api/generate", model, {"prompt": "", "stream": False}, settings=settings)
            response.raise_for_status()
        return True
    except Exception as exc:  # a touch is best effort; the idle timer and verified unload remain the enforcers
        log.debug("Ollama keep-alive touch skipped: %s", exc)
        return False
