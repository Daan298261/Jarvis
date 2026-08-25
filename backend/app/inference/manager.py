from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import psutil

from ..config import AppSettings, logs_dir
from ..providers.openai_compat import OpenAICompatProvider
from .backends import InferenceBackend, probe_remote_server, resolve_backend
from .profiles import ModelProfile, model_paths, profile_gguf, resolve_profile, declared_profiles


def resolve_vision(settings: AppSettings, requested: bool | None = None) -> bool:
    mode = (settings.inference.vision or "lazy").strip().lower()
    if mode in {"off", "never", "disabled"}:
        return False
    if mode in {"always", "on", "enabled"}:
        return True
    return bool(requested)


@dataclass
class InferenceState:
    loaded: bool = False
    loading: bool = False
    profile: str = "balanced"
    quant: str = ""
    model_path: str = ""
    mmproj_path: str = ""
    vision_loaded: bool = False
    vision_mode: str = "lazy"
    backend: str = "llama.cpp"
    manages_process: bool = True
    host: str = "127.0.0.1"
    port: int = 8088
    context_size: int = 16384
    gpu_layers: str = "fit"
    flash_attn: str = "auto"
    pid: int | None = None
    load_time_seconds: float | None = None
    prompt_tps: float | None = None
    generation_tps: float | None = None
    vram_used_mib: int | None = None
    ram_used_gb: float | None = None
    last_error: str = ""
    llama_version: str = ""
    vision: bool = False
    family: str = ""
    alias: str = ""
    thinking_mode: str = ""
    advertised_models: list[str] | None = None
    health_path: str = ""
    remote_model: str = ""


def _with_context(profile: ModelProfile, context_size: int) -> ModelProfile:
    return replace(profile, context_size=context_size)


def _default_load_context(profile: ModelProfile) -> int:
    cap = int(profile.context_size or 16384)
    if profile.name == "fast":
        return min(8192, cap)
    return min(16384, cap)


class InferenceManager:
    """Owns model lifecycle. Process control is delegated to an InferenceBackend."""

    def __init__(self) -> None:
        self.state = InferenceState()
        self.backend: InferenceBackend | None = None
        self._lock = asyncio.Lock()
        self.provider: OpenAICompatProvider | None = None

    def base_url(self, settings: AppSettings) -> str:
        return f"http://{settings.inference.host}:{settings.inference.port}/v1"

    def provider_model(self, settings: AppSettings, advertised: list[str] | None = None) -> str:
        chosen = (settings.inference.remote_model or "").strip()
        if chosen:
            return chosen
        if advertised:
            return advertised[0]
        profile = resolve_profile(self.state.profile or settings.inference.profile)
        return profile.alias or "Qwen3.5-9B"

    def provider_api_key(self, settings: AppSettings) -> str:
        return (settings.inference.api_key or "").strip() or "local"

    def _make_provider(self, settings: AppSettings, advertised: list[str] | None = None) -> OpenAICompatProvider:
        return OpenAICompatProvider(
            self.base_url(settings),
            api_key=self.provider_api_key(settings),
            model=self.provider_model(settings, advertised),
        )

    def _vision_requested(self, settings: AppSettings, vision: bool | None) -> bool:
        return resolve_vision(settings, vision)

    async def load(
        self,
        settings: AppSettings,
        profile_name: str | None = None,
        context_size: int | None = None,
        force: bool = False,
        vision: bool | None = None,
    ) -> InferenceState:
        async with self._lock:
            profile = resolve_profile(profile_name or settings.inference.profile)
            if context_size:
                profile = _with_context(profile, int(context_size))
            backend = resolve_backend(settings)
            same = (
                not force
                and self.backend
                and self.state.loaded
                and self.state.profile == profile.name
                and self.backend.name == backend.name
                and int(self.state.context_size or 0) >= int(profile.context_size or 0)
                and (not vision or self.state.vision_loaded)
            )
            if same:
                return self.state
            return await self._load_locked(
                settings,
                profile.name,
                context_size=context_size or profile.context_size,
                vision=vision,
            )

    async def ensure_runtime(
        self,
        settings: AppSettings,
        profile_name: str | None = None,
        *,
        context_size: int | None = None,
        vision: bool = False,
    ) -> InferenceState:
        """Reload only when context must grow or vision must be attached."""
        async with self._lock:
            if not self.state.loaded or not self.provider:
                return await self._load_locked(
                    settings,
                    profile_name,
                    context_size=context_size,
                    vision=vision,
                )
            want_context = int(context_size or self.state.context_size or 0)
            want_vision = bool(vision)
            if (
                (self.state.context_size or 0) >= want_context
                and (not want_vision or self.state.vision_loaded)
            ):
                return self.state
            return await self._load_locked(
                settings,
                profile_name or self.state.profile,
                context_size=want_context,
                vision=want_vision,
                force=True,
            )

    async def ensure_vision(self, settings: AppSettings) -> InferenceState:
        return await self.ensure_runtime(
            settings,
            self.state.profile,
            context_size=self.state.context_size,
            vision=True,
        )

    async def _load_locked(
        self,
        settings: AppSettings,
        profile_name: str | None,
        *,
        context_size: int | None,
        vision: bool | None,
        force: bool = False,
    ) -> InferenceState:
        profile = resolve_profile(profile_name or settings.inference.profile)
        backend = resolve_backend(settings)
        paths = model_paths()
        model = profile_gguf(profile)
        want_vision = self._vision_requested(settings, vision)
        want_context = int(
            context_size
            or _default_load_context(profile)
            or profile.context_size
        )

        missing = backend.missing_requirements(profile)
        if missing:
            self.state.last_error = "; ".join(missing)
            raise FileNotFoundError(self.state.last_error)

        reusable = (
            not force
            and self.backend
            and self.state.loaded
            and self.state.profile == profile.name
            and self.backend.name == backend.name
            and (self.state.context_size or 0) >= want_context
            and (not want_vision or self.state.vision_loaded)
        )
        if reusable:
            return self.state

        self._apply_profile_state(settings, profile, backend, model, paths, want_context, want_vision)

        probe = await probe_remote_server(
            settings.inference.host,
            settings.inference.port,
            settings.inference.api_key,
            timeout=6,
        )
        already_running = (self.backend is None or self.backend.pid is None) and bool(probe.get("ok"))
        if already_running and not backend.manages_process:
            advertised = list(probe.get("models") or [])
            self._record_probe(probe, settings)
            self.backend = backend
            self.backend.last_probe = probe
            self.provider = self._make_provider(settings, advertised)
            self.state.loaded = True
            self.state.loading = False
            self.state.pid = backend.pid
            await self.refresh_resources()
            return self.state

        if self.backend:
            await self.backend.stop()
        self.backend = backend
        self.state.loading = True
        self.state.last_error = ""
        started = time.time()

        start_kwargs: dict[str, Any] = {"timeout": 300, "context_size": want_context, "vision": want_vision}
        try:
            ready = await backend.start(profile, **start_kwargs)
        except TypeError:
            ready = await backend.start(profile, timeout=300)
        if not ready and backend.manages_process and want_context > 16384:
            fallback_ctx = 16384
            try:
                ready = await backend.start(
                    _with_context(profile, fallback_ctx),
                    timeout=240,
                    context_size=fallback_ctx,
                    vision=want_vision,
                )
            except TypeError:
                ready = await backend.start(_with_context(profile, fallback_ctx), timeout=240)
            if ready:
                self.state.context_size = fallback_ctx
        self.state.pid = backend.pid
        if not ready:
            self.state.loading = False
            self.state.last_error = f"{backend.name} did not become ready"
            detail = (
                f". See {logs_dir() / 'llama-server.log'}"
                if backend.manages_process
                else f" at {self.base_url(settings)}"
            )
            raise RuntimeError(self.state.last_error + detail)

        advertised = list((backend.last_probe or {}).get("models") or [])
        if backend.last_probe:
            self._record_probe(backend.last_probe, settings)
        self.state.loaded = True
        self.state.loading = False
        self.state.load_time_seconds = round(time.time() - started, 2)
        self.provider = self._make_provider(settings, advertised)
        await self.refresh_resources()
        return self.state

    def _apply_profile_state(
        self,
        settings: AppSettings,
        profile: ModelProfile,
        backend: InferenceBackend,
        model: Path,
        paths: dict[str, Path],
        context_size: int,
        vision: bool,
    ) -> None:
        self.state.profile = profile.name
        self.state.quant = profile.quant
        self.state.model_path = str(model) if backend.requires_local_files else ""
        self.state.vision_loaded = bool(vision and paths["mmproj"].exists())
        self.state.mmproj_path = str(paths["mmproj"]) if self.state.vision_loaded else ""
        self.state.vision_mode = settings.inference.vision_mode or "lazy"
        self.state.vision = bool(vision)
        self.state.host = settings.inference.host
        self.state.port = settings.inference.port
        self.state.context_size = int(context_size or profile.context_size)
        self.state.backend = backend.name
        self.state.manages_process = backend.manages_process
        self.state.family = profile.family
        self.state.alias = profile.alias
        self.state.thinking_mode = profile.thinking_mode
        self.state.remote_model = settings.inference.remote_model

    def _record_probe(self, probe: dict[str, Any], settings: AppSettings) -> None:
        self.state.advertised_models = list(probe.get("models") or [])
        self.state.health_path = str(probe.get("health_path") or "")
        self.state.remote_model = self.provider_model(settings, self.state.advertised_models)

    async def unload(self) -> InferenceState:
        async with self._lock:
            if self.backend:
                await self.backend.stop()
            self.provider = None
            self.state.loaded = False
            self.state.loading = False
            self.state.pid = None
            self.state.vision_loaded = False
            self.state.mmproj_path = ""
            return self.state

    async def apply_context(self, settings: AppSettings, context_size: int, *, allow_shrink: bool = False) -> int:
        """Set the live context window. Mid-task callers pass allow_shrink=False so we only grow."""
        target = int(context_size or 0)
        if target <= 0:
            return int(self.state.context_size or 0)
        current = int(self.state.context_size or 0)
        if current == target:
            return current
        if not allow_shrink and current >= target and current > 0:
            return current
        manages = bool(self.backend and getattr(self.backend, "manages_process", False))
        if not manages:
            self.state.context_size = target
            return target
        try:
            await self.load(
                settings,
                self.state.profile or settings.inference.profile,
                context_size=target,
                force=True,
            )
        except Exception:
            return int(self.state.context_size or current)
        return int(self.state.context_size or target)

    async def refresh_resources(self) -> None:
        try:
            import subprocess

            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout.strip()
            if out:
                self.state.vram_used_mib = int(float(out.splitlines()[0].strip()))
        except Exception:
            pass
        try:
            if self.state.pid:
                proc = psutil.Process(self.state.pid)
                self.state.ram_used_gb = round(proc.memory_info().rss / (1024**3), 2)
        except Exception:
            pass

    async def snapshot(self, settings: AppSettings) -> dict[str, Any]:
        await self.refresh_resources()
        healthy = False
        if self.provider:
            healthy = await self.provider.health()
        profile = resolve_profile(self.state.profile or settings.inference.profile)
        return {
            "loaded": self.state.loaded,
            "loading": self.state.loading,
            "healthy": healthy,
            "active_model": (
                (self.provider.model if self.provider else self.provider_model(settings, self.state.advertised_models))
                if self.state.loaded
                else None
            ),
            "official_model": profile.repo,
            "family": self.state.family or profile.family if self.state.loaded else profile.family,
            "thinking_mode": (
                self.state.thinking_mode or profile.thinking_mode or ("selective" if profile.thinking else "off")
            ),
            "vision": settings.inference.vision,
            "quantization": self.state.quant or profile.quant,
            "profile": self.state.profile or profile.name,
            "context_size": self.state.context_size if self.state.loaded else _default_load_context(profile),
            "context_cap": max((p.context_size for p in declared_profiles()), default=profile.context_size),
            "inference_backend": self.state.backend,
            "manages_process": self.state.manages_process,
            "gpu_layers": "auto (--fit on)" if settings.inference.fit else "99",
            "flash_attn": settings.inference.flash_attn,
            "host": settings.inference.host,
            "port": settings.inference.port,
            "base_url": self.base_url(settings),
            "advertised_models": self.state.advertised_models or [],
            "health_path": self.state.health_path,
            "remote_model": self.state.remote_model or settings.inference.remote_model,
            "api_key_configured": bool((settings.inference.api_key or "").strip()),
            "vram_used_mib": self.state.vram_used_mib,
            "ram_used_gb": self.state.ram_used_gb,
            "tokens_per_second": self.state.generation_tps,
            "prompt_tokens_per_second": self.state.prompt_tps,
            "load_time_seconds": self.state.load_time_seconds,
            "pid": self.state.pid,
            "last_error": self.state.last_error,
            "model_path": self.state.model_path,
            "mmproj_path": self.state.mmproj_path,
            "vision_loaded": self.state.vision_loaded,
            "thinking": profile.thinking,
            "vision_mode": settings.inference.vision_mode or "lazy",
            "profiles": [
                {
                    "name": p.name,
                    "label": p.label,
                    "family": p.family,
                    "thinking_mode": p.thinking_mode,
                    "context_size": p.context_size,
                }
                for p in declared_profiles()
            ],
            "context_policy": {
                "live": self.state.context_size or profile.context_size,
                "profile_cap": profile.context_size,
                "note": "Tasks start at 8K or 16K and expand to the profile cap only when the live prompt is under pressure.",
            },
        }

    async def record_timings(self, timings: dict[str, Any]) -> None:
        if not timings:
            return
        predicted = timings.get("predicted_per_second") or timings.get("predicted_n")
        prompt = timings.get("prompt_per_second")
        if isinstance(predicted, (int, float)):
            self.state.generation_tps = round(float(predicted), 2)
        if isinstance(prompt, (int, float)):
            self.state.prompt_tps = round(float(prompt), 2)
        try:
            from .benchmarks import record_benchmark_sample

            await record_benchmark_sample(
                profile=self.state.profile,
                quantization=self.state.quant,
                context_size=self.state.context_size,
                prompt_tps=self.state.prompt_tps,
                generation_tps=self.state.generation_tps,
                vram_used_mib=self.state.vram_used_mib,
                ram_used_gb=self.state.ram_used_gb,
                load_time_seconds=self.state.load_time_seconds,
                source="timing",
            )
        except Exception:
            pass


MANAGER = InferenceManager()
