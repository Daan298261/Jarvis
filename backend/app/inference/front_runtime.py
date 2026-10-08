"""Resident front-lane llama-server, separate from the worker server.

Default profile is Qwen3.5 2B Q4 on CPU (``-ngl 0``), so it does not take
worker VRAM. Qwen3.5 4B Q4 is the optional GPU profile and starts only when a
VRAM fit check says the worker and voice models still have room.

The front endpoint is an OpenAI-compatible URL: the local server, or a
manually configured LAN llama-server. Remote health uses the existing
inference probe. If that endpoint disappears, the lane falls back to the local
CPU server and records why. Placement policy uses the swarm role vocabulary
(AUTO / PREFERRED / FORCED / AVOID / DISABLED) via ``swarm.roles`` — it does
not add a third SwarmRole holder. Multi-node discovery of a front holder is
not in this tree; the remote side is a configured endpoint.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import psutil

from ..config import AppSettings, load_settings
from ..hardware import detect_hardware
from ..providers.base import ChatMessage
from ..swarm.roles import (
    ASSIGNMENT_AVOID,
    ASSIGNMENT_DISABLED,
    is_eligible_for_role,
    must_hold_role,
    validate_policy,
)
from .backends import LlamaCppBackend, probe_remote_server
from .manager import MANAGER
from .profiles import PROFILES, ModelProfile, profile_gguf, resolve_profile

_log = logging.getLogger(__name__)

FRONT_PROFILE_2B = "front_2b"
FRONT_PROFILE_4B = "front_4b"
FRONT_PROFILES = (FRONT_PROFILE_2B, FRONT_PROFILE_4B)
# Used only when the GGUF is not on disk yet. Real size wins once the file exists.
_WEIGHT_FALLBACK_MIB = {
    FRONT_PROFILE_2B: 1536,
    FRONT_PROFILE_4B: 2806,
}
_VOICE_RESERVE_MIB = 512
_CHATTERBOX_RESERVE_MIB = 2560
_WORKER_FALLBACK_RESERVE_MIB = 6144
_LOG_NAME = "llama-front.log"


@dataclass
class FrontDecision:
    mode: str = "disabled"
    reason: str = ""
    healthy: bool = False
    device: str = "cpu"
    profile: str = ""
    model: str = ""
    gguf: str = ""
    endpoint: str = ""
    port: int = 0
    context_size: int = 4096
    n_gpu_layers: int = 0
    placement: str = "local"
    placement_policy: str = "AUTO"
    remote_healthy: bool | None = None
    fallback_from: str = ""
    vram_total_mib: int | None = None
    vram_free_mib: int | None = None
    vram_required_mib: int = 0
    vram_voice_reserve_mib: int = 0
    vram_worker_reserve_mib: int = 0
    ram_available_mib: int | None = None
    ram_required_mib: int = 0
    prompt_cache: bool = True
    log_file: str = ""
    same_gguf_as_worker: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "reason": self.reason,
            "healthy": self.healthy,
            "device": self.device,
            "profile": self.profile,
            "model": self.model,
            "gguf": self.gguf,
            "endpoint": self.endpoint,
            "port": self.port,
            "context_size": self.context_size,
            "n_gpu_layers": self.n_gpu_layers,
            "placement": self.placement,
            "placement_policy": self.placement_policy,
            "remote_healthy": self.remote_healthy,
            "fallback_from": self.fallback_from,
            "vram_total_mib": self.vram_total_mib,
            "vram_free_mib": self.vram_free_mib,
            "vram_required_mib": self.vram_required_mib,
            "vram_voice_reserve_mib": self.vram_voice_reserve_mib,
            "vram_worker_reserve_mib": self.vram_worker_reserve_mib,
            "ram_available_mib": self.ram_available_mib,
            "ram_required_mib": self.ram_required_mib,
            "prompt_cache": self.prompt_cache,
            "log_file": self.log_file,
            "same_gguf_as_worker": self.same_gguf_as_worker,
        }


def front_choice_catalog() -> list[dict[str, Any]]:
    """Plain-language choices for setup and settings. Default is Faster / 2B."""
    return [
        {
            "id": FRONT_PROFILE_2B,
            "label": "Faster",
            "detail": "Qwen3.5 2B Q4 on CPU. Quick acknowledgements, no GPU memory.",
            "device": "cpu",
        },
        {
            "id": FRONT_PROFILE_4B,
            "label": "Smarter",
            "detail": "Qwen3.5 4B Q4 on GPU, only when VRAM remains beside the worker and voice.",
            "device": "gpu",
        },
    ]


def configured_profile_name(settings: AppSettings) -> str:
    name = (settings.front_responder.profile or "").strip()
    if name in PROFILES:
        return name
    return ""


def resolve_front_device(settings: AppSettings, profile_name: str) -> str:
    choice = (settings.front_responder.device or "auto").strip().lower()
    if choice == "cpu":
        return "cpu"
    if choice == "gpu":
        return "gpu"
    if profile_name == FRONT_PROFILE_4B:
        return "gpu"
    return "cpu"


def _parse_base_url(raw: str) -> tuple[str, int, str]:
    text = (raw or "").strip()
    if not text:
        return "", 0, ""
    if "://" not in text:
        text = "http://" + text
    parsed = urlparse(text)
    host = parsed.hostname or ""
    port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
    path = parsed.path or ""
    if path.rstrip("/").endswith("/v1"):
        base = f"{parsed.scheme}://{host}:{port}/v1"
    else:
        base = f"{parsed.scheme}://{host}:{port}/v1"
    return host, port, base.rstrip("/")


def _file_mib(path) -> int:
    try:
        if path is not None and path.is_file():
            return max(1, int(path.stat().st_size / (1024 * 1024)))
    except OSError:
        return 0
    return 0


def _voice_reserve_mib() -> int:
    try:
        from ..persona.named_persona import CATALOG, active_persona_id
        from ..voice_profiles.catalog import get_catalog

        persona = CATALOG.get(active_persona_id())
        voice_id = getattr(persona, "voice_profile_id", "") if persona else ""
        profile = get_catalog().get(voice_id) if voice_id else None
        engine = profile.tts.resolved_engine_id() if profile is not None else ""
    except Exception:
        engine = ""
    if engine in {"chatterbox", "chatterbox_turbo", "chatterbox-turbo"}:
        return _CHATTERBOX_RESERVE_MIB
    return _VOICE_RESERVE_MIB


def _worker_gguf_mib(settings: AppSettings) -> int:
    try:
        profile = resolve_profile(settings.inference.profile)
        size = _file_mib(profile_gguf(profile))
        if size:
            return size
    except Exception:
        pass
    return _WORKER_FALLBACK_RESERVE_MIB


class FrontRuntime:
    def __init__(self) -> None:
        self._backend: LlamaCppBackend | None = None
        self._provider: Any | None = None
        self._decision = FrontDecision(reason="not_started")
        self._lock = asyncio.Lock()
        self._force_distinct: bool | None = None
        self._test_provider: Any | None = None

    @property
    def decision(self) -> FrontDecision:
        return self._decision

    def status(self) -> dict[str, Any]:
        return self._decision.as_dict()

    def mark_for_tests(self, *, distinct: bool | None, provider: Any | None = None) -> None:
        """Test hook. ``distinct=None`` clears the override."""
        self._force_distinct = distinct
        self._test_provider = provider

    def reset_for_tests(self) -> None:
        self._force_distinct = None
        self._test_provider = None
        self._provider = None
        self._decision = FrontDecision(reason="not_started")

    def is_distinct(self, settings: AppSettings | None = None) -> bool:
        if self._force_distinct is not None:
            return bool(self._force_distinct)
        decision = self._decision
        if not decision.healthy or decision.mode not in {"resident", "remote"}:
            return False
        if decision.same_gguf_as_worker:
            return False
        app = settings or load_settings()
        worker_url = ""
        try:
            worker_url = MANAGER.base_url(app).rstrip("/")
        except Exception:
            worker_url = ""
        return bool(decision.endpoint) and decision.endpoint.rstrip("/") != worker_url

    def model_id(self, settings: AppSettings | None = None) -> str:
        if self._test_provider is not None:
            return str(getattr(self._test_provider, "model", "") or "")
        if self._decision.healthy and self._decision.model:
            return self._decision.model
        return ""

    def provider(self, settings: AppSettings | None = None) -> Any | None:
        if self._test_provider is not None:
            return self._test_provider
        if self._decision.healthy and self._provider is not None:
            return self._provider
        return None

    def decide(
        self,
        settings: AppSettings | None = None,
        *,
        vram_total_mib: int | None = None,
        vram_free_mib: int | None = None,
        ram_available_mib: int | None = None,
        worker_loaded: bool | None = None,
        remote_ok: bool | None = None,
        remote_error: str = "",
        gguf_present: bool | None = None,
    ) -> FrontDecision:
        app = settings or load_settings()
        cfg = app.front_responder
        decision = FrontDecision(
            placement=cfg.placement,
            prompt_cache=bool(cfg.prompt_cache),
            context_size=int(cfg.context_size or 4096),
            port=int(cfg.port or 8089),
        )
        try:
            policy = validate_policy(cfg.placement_policy or "AUTO")
        except ValueError:
            policy = "AUTO"
            decision.reason = "invalid_placement_policy"
        decision.placement_policy = policy
        if not cfg.enabled or not cfg.resident or policy == ASSIGNMENT_DISABLED:
            decision.mode = "disabled"
            decision.reason = decision.reason or ("disabled" if not cfg.enabled else "not_resident" if not cfg.resident else "placement_disabled")
            return decision
        if not is_eligible_for_role(policy, necessary=True) and policy == ASSIGNMENT_AVOID:
            # AVOID still allows the local lane; it only skips a remote preference.
            pass

        profile_name = configured_profile_name(app)
        if not profile_name:
            decision.mode = "disabled"
            decision.reason = "profile_unset"
            return decision
        profile = PROFILES[profile_name]
        decision.profile = profile.name
        decision.model = (cfg.model or "").strip() or profile.alias
        decision.device = resolve_front_device(app, profile.name)
        decision.n_gpu_layers = 0 if decision.device == "cpu" else max(1, int(cfg.n_gpu_layers or 0) or 99)
        gguf = profile_gguf(profile)
        decision.gguf = str(gguf)
        present = gguf.is_file() if gguf_present is None else bool(gguf_present)
        worker_path = ""
        try:
            worker_path = str(profile_gguf(resolve_profile(app.inference.profile)))
        except Exception:
            worker_path = ""
        decision.same_gguf_as_worker = bool(worker_path) and worker_path == decision.gguf

        hw = None
        if vram_total_mib is None or vram_free_mib is None or ram_available_mib is None:
            try:
                hw = detect_hardware()
            except Exception:
                hw = None
        if vram_total_mib is None and hw is not None:
            vram_total_mib = hw.vram_total_mib
        if vram_free_mib is None and hw is not None:
            vram_free_mib = hw.vram_free_mib
        if ram_available_mib is None:
            try:
                ram_available_mib = int(psutil.virtual_memory().available / (1024 * 1024))
            except Exception:
                ram_available_mib = None
        decision.vram_total_mib = vram_total_mib
        decision.vram_free_mib = vram_free_mib
        decision.ram_available_mib = ram_available_mib
        loaded = bool(MANAGER.state.loaded) if worker_loaded is None else bool(worker_loaded)
        decision.vram_voice_reserve_mib = _voice_reserve_mib() if decision.device == "gpu" else 0
        decision.vram_worker_reserve_mib = 0 if loaded or decision.device == "cpu" else _worker_gguf_mib(app)

        weights = _file_mib(gguf) or _WEIGHT_FALLBACK_MIB.get(profile.name, 1536)
        kv = max(128, int(decision.context_size) // 16)
        if decision.device == "gpu":
            decision.vram_required_mib = weights + kv + 384
        else:
            decision.vram_required_mib = 0
            decision.ram_required_mib = weights + kv + int(cfg.ram_headroom_mib or 0)
            if not loaded:
                decision.ram_required_mib += min(_worker_gguf_mib(app), _WORKER_FALLBACK_RESERVE_MIB)

        remote_decision = self._consider_remote(
            app,
            decision,
            remote_ok=remote_ok,
            remote_error=remote_error,
        )
        if remote_decision is not None:
            return remote_decision
        remote_note = decision.reason if decision.fallback_from == "remote" else ""
        # Unhealthy or missing remote already forced CPU. Recompute the RAM
        # budget so a 4B GPU plan does not skip that check on the way down.
        # AVOID / ineligible only skip the remote preference and keep the
        # local device (CPU 2B or GPU 4B).
        if decision.fallback_from == "remote" and decision.device == "cpu":
            decision.n_gpu_layers = 0
            decision.vram_required_mib = 0
            decision.vram_voice_reserve_mib = 0
            decision.vram_worker_reserve_mib = 0
            decision.ram_required_mib = weights + kv + int(cfg.ram_headroom_mib or 0)
            if not loaded:
                decision.ram_required_mib += min(_worker_gguf_mib(app), _WORKER_FALLBACK_RESERVE_MIB)

        if decision.same_gguf_as_worker:
            decision.mode = "shared"
            decision.reason = _join_reason(remote_note, "same_gguf_as_worker")
            decision.endpoint = ""
            return decision
        if not present:
            decision.mode = "fallback"
            decision.reason = _join_reason(remote_note, f"weights_missing: {decision.gguf}")
            _log.warning("front runtime fallback: %s", decision.reason)
            return decision

        if decision.device == "gpu":
            fit_reason = _gpu_fit_reason(decision)
            if fit_reason:
                decision.mode = "fallback"
                decision.reason = _join_reason(remote_note, fit_reason)
                _log.warning("front runtime VRAM fallback: %s", decision.reason)
                return decision
        else:
            ram_reason = _ram_fit_reason(decision)
            if ram_reason:
                decision.mode = "fallback"
                decision.reason = _join_reason(remote_note, ram_reason)
                _log.warning("front runtime RAM fallback: %s", decision.reason)
                return decision

        from ..config import logs_dir

        decision.mode = "resident"
        local_reason = "cpu_resident" if decision.device == "cpu" else "gpu_resident"
        decision.reason = _join_reason(remote_note, local_reason)
        decision.endpoint = f"http://{app.inference.host}:{decision.port}/v1"
        decision.log_file = str(logs_dir() / _LOG_NAME)
        return decision

    def _consider_remote(
        self,
        settings: AppSettings,
        decision: FrontDecision,
        *,
        remote_ok: bool | None,
        remote_error: str,
    ) -> FrontDecision | None:
        cfg = settings.front_responder
        if (cfg.placement or "local") != "remote":
            return None
        policy = decision.placement_policy
        if policy == ASSIGNMENT_DISABLED or not is_eligible_for_role(policy, necessary=False):
            decision.fallback_from = "remote"
            decision.reason = "remote_not_eligible"
            return None
        if policy == ASSIGNMENT_AVOID:
            decision.fallback_from = "remote"
            decision.reason = "remote_avoid"
            return None
        host, port, base = _parse_base_url(cfg.remote_base_url)
        if not host or not port:
            decision.fallback_from = "remote"
            decision.reason = "remote_endpoint_missing"
            _log.warning("front runtime remote endpoint missing; using local CPU server")
            decision.placement = "local"
            decision.device = "cpu"
            decision.n_gpu_layers = 0
            return None
        ok = remote_ok
        if ok is None:
            ok = False
            remote_error = remote_error or "remote_not_probed"
        decision.remote_healthy = bool(ok)
        if ok:
            decision.mode = "remote"
            decision.healthy = True
            decision.reason = "remote_healthy"
            decision.endpoint = base
            decision.device = "cpu"
            decision.n_gpu_layers = 0
            if must_hold_role(policy):
                decision.reason = "remote_forced"
            return decision
        # Graceful: a dead remote node must not take the lane down with it.
        decision.fallback_from = "remote"
        forced = " force_not_honored" if must_hold_role(policy) else ""
        detail = (remote_error or "unhealthy").strip()
        decision.reason = f"remote_unhealthy:{detail}{forced}"
        _log.warning("front runtime remote unhealthy, falling back to local CPU server: %s", decision.reason)
        decision.placement = "local"
        decision.device = "cpu"
        decision.n_gpu_layers = 0
        return None

    async def probe_remote(self, settings: AppSettings) -> tuple[bool, str]:
        host, port, _base = _parse_base_url(settings.front_responder.remote_base_url)
        if not host:
            return False, "remote_endpoint_missing"
        key = (settings.front_responder.remote_api_key or settings.inference.api_key or "").strip()
        try:
            probe = await probe_remote_server(host, port, api_key=key, timeout=3.0, retry=False)
        except Exception as exc:
            return False, str(exc)[:240]
        if probe.get("ok"):
            return True, ""
        return False, str(probe.get("error") or "unhealthy")[:240]

    async def ensure_started(self, settings: AppSettings | None = None) -> FrontDecision:
        app = settings or load_settings()
        async with self._lock:
            remote_ok = None
            remote_error = ""
            if (app.front_responder.placement or "local") == "remote":
                remote_ok, remote_error = await self.probe_remote(app)
            decision = self.decide(app, remote_ok=remote_ok, remote_error=remote_error)
            if decision.mode == "remote":
                self._attach_provider(app, decision)
                self._decision = decision
                return decision
            if decision.mode != "resident":
                await self._stop_backend()
                self._provider = None
                decision.healthy = False
                self._decision = decision
                return decision
            started = await self._start_local(app, decision)
            self._decision = started
            return started

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_backend()
            self._provider = None
            self._decision = FrontDecision(reason="stopped")

    async def _stop_backend(self) -> None:
        backend = self._backend
        self._backend = None
        if backend is not None:
            try:
                await backend.stop()
            except Exception:
                _log.debug("front server stop failed", exc_info=True)

    def _attach_provider(self, settings: AppSettings, decision: FrontDecision) -> None:
        from ..providers.openai_compat import OpenAICompatProvider

        key = (settings.front_responder.remote_api_key or settings.inference.api_key or "local").strip() or "local"
        timeout = max(1.0, settings.front_responder.timeout_ms / 1000.0)
        self._provider = OpenAICompatProvider(
            decision.endpoint,
            api_key=key,
            model=decision.model or "front",
            timeout=timeout,
        )
        decision.healthy = True

    async def _start_local(self, settings: AppSettings, decision: FrontDecision) -> FrontDecision:
        profile = PROFILES[decision.profile]
        await self._stop_backend()
        backend = LlamaCppBackend(settings)
        missing = backend.missing_requirements(profile)
        if missing:
            decision.mode = "fallback"
            decision.healthy = False
            decision.reason = "server_or_weights_missing: " + "; ".join(missing)[:500]
            _log.warning("front runtime fallback: %s", decision.reason)
            return decision
        try:
            ready = await backend.start(
                profile,
                timeout=120,
                context_size=decision.context_size,
                vision=False,
                port=decision.port,
                host=settings.inference.host,
                reasoning=False,
                parallel=1,
                n_gpu_layers=decision.n_gpu_layers,
                keep=-1 if decision.prompt_cache else 0,
                prompt_cache=bool(decision.prompt_cache),
                log_name=_LOG_NAME,
            )
        except Exception as exc:
            decision.mode = "fallback"
            decision.healthy = False
            decision.reason = f"start_failed: {exc}"[:500]
            _log.warning("front runtime start failed: %s", decision.reason)
            return decision
        if not ready:
            decision.mode = "fallback"
            decision.healthy = False
            decision.reason = "start_failed: health check timed out"
            _log.warning("front runtime fallback: %s", decision.reason)
            try:
                await backend.stop()
            except Exception:
                pass
            return decision
        self._backend = backend
        self._attach_provider(settings, decision)
        try:
            await self._warmup(decision)
        except Exception:
            _log.debug("front warmup completion failed", exc_info=True)
        _log.info(
            "front runtime resident profile=%s device=%s port=%s ngl=%s",
            decision.profile,
            decision.device,
            decision.port,
            decision.n_gpu_layers,
        )
        return decision

    async def _warmup(self, decision: FrontDecision) -> None:
        provider = self._provider
        if provider is None or not hasattr(provider, "chat_stream"):
            return
        messages = [ChatMessage(role="user", content="Hi")]
        try:
            async with asyncio.timeout(8):
                async for _delta in provider.chat_stream(
                    messages,
                    max_tokens=1,
                    temperature=0.0,
                    thinking=False,
                ):
                    break
        except Exception:
            _log.debug("front warmup yielded no token", exc_info=True)


def _join_reason(prefix: str, reason: str) -> str:
    if prefix and reason and prefix != reason:
        return f"{prefix}; {reason}"
    return reason or prefix


def _gpu_fit_reason(decision: FrontDecision) -> str:
    free = decision.vram_free_mib
    total = decision.vram_total_mib
    need = int(decision.vram_required_mib)
    voice = int(decision.vram_voice_reserve_mib)
    worker = int(decision.vram_worker_reserve_mib)
    if free is None or total is None:
        return (
            "vram_probe_unavailable: refusing to start a GPU front server without "
            f"measured VRAM (required_mib={need}, voice_reserve_mib={voice}, worker_reserve_mib={worker})"
        )
    budget = int(free) - voice - worker
    if budget < need:
        return (
            "vram_insufficient: "
            f"free_mib={free} total_mib={total} required_mib={need} "
            f"voice_reserve_mib={voice} worker_reserve_mib={worker} "
            f"budget_mib={budget}"
        )
    return ""


def _ram_fit_reason(decision: FrontDecision) -> str:
    available = decision.ram_available_mib
    need = int(decision.ram_required_mib)
    if available is None:
        return f"ram_probe_unavailable: required_mib={need}"
    if int(available) < need:
        return f"ram_insufficient: available_mib={available} required_mib={need}"
    return ""


def front_profile_or_none(name: str) -> ModelProfile | None:
    profile = PROFILES.get((name or "").strip())
    if profile is None or profile.name not in FRONT_PROFILES:
        return None
    return profile


FRONT_RUNTIME = FrontRuntime()
