from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import psutil

from ..config import AppSettings, logs_dir
from ..providers.openai_compat import OpenAICompatProvider
from .backends import InferenceBackend, resolve_backend
from .profiles import ModelProfile, declared_profiles, mmproj_path, profile_as_dict, profile_gguf, resolve_profile


@dataclass
class InferenceState:
    loaded: bool = False
    loading: bool = False
    profile: str = "balanced"
    quant: str = ""
    model_path: str = ""
    mmproj_path: str = ""
    backend: str = "llama.cpp"
    manages_process: bool = True
    host: str = "127.0.0.1"
    port: int = 8088
    context_size: int = 0
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


def _with_context(profile: ModelProfile, context_size: int) -> ModelProfile:
    return replace(profile, context_size=context_size)


class InferenceManager:
    """Owns model lifecycle. Process control is delegated to an InferenceBackend."""

    def __init__(self) -> None:
        self.state = InferenceState()
        self.backend: InferenceBackend | None = None
        self._lock = asyncio.Lock()
        self.provider: OpenAICompatProvider | None = None

    def base_url(self, settings: AppSettings) -> str:
        return f"http://{settings.inference.host}:{settings.inference.port}/v1"

    async def load(self, settings: AppSettings, profile_name: str | None = None) -> InferenceState:
        async with self._lock:
            profile = resolve_profile(profile_name or settings.inference.profile)
            backend = resolve_backend(settings)
            model = profile_gguf(profile)

            missing = backend.missing_requirements(profile)
            if missing:
                self.state.last_error = "; ".join(missing)
                raise FileNotFoundError(self.state.last_error)

            if self.backend and self.state.loaded and self.state.profile == profile.name and self.backend.name == backend.name and self.state.vision == bool(settings.inference.vision):
                return self.state

            self._apply_profile_state(settings, profile, backend, model)

            # Adopt a server that is already answering when we did not start one.
            existing = OpenAICompatProvider(self.base_url(settings), model=profile.alias)
            already_running = (self.backend is None or self.backend.pid is None) and await existing.health()
            if already_running:
                self.backend = backend
                self.provider = existing
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

            ready = await backend.start(profile, timeout=300)
            if not ready and backend.manages_process:
                # Most first-load failures on a 16 GB card are context pressure.
                fallback = _with_context(profile, 16384)
                ready = await backend.start(fallback, timeout=240)
                if ready:
                    self.state.context_size = fallback.context_size
            self.state.pid = backend.pid
            if not ready:
                self.state.loading = False
                self.state.last_error = f"{backend.name} did not become ready"
                detail = f". See {logs_dir() / 'llama-server.log'}" if backend.manages_process else f" at {self.base_url(settings)}"
                raise RuntimeError(self.state.last_error + detail)

            self.state.loaded = True
            self.state.loading = False
            self.state.load_time_seconds = round(time.time() - started, 2)
            self.provider = OpenAICompatProvider(self.base_url(settings), model=profile.alias)
            await self.refresh_resources()
            return self.state

    def _apply_profile_state(
        self,
        settings: AppSettings,
        profile: ModelProfile,
        backend: InferenceBackend,
        model: Path,
    ) -> None:
        projector = mmproj_path(profile)
        vision = bool(settings.inference.vision) and projector.exists()
        self.state.profile = profile.name
        self.state.quant = profile.quant
        self.state.model_path = str(model) if backend.requires_local_files else ""
        self.state.mmproj_path = str(projector) if vision else ""
        self.state.host = settings.inference.host
        self.state.port = settings.inference.port
        self.state.context_size = profile.context_size
        self.state.backend = backend.name
        self.state.manages_process = backend.manages_process
        self.state.vision = vision
        self.state.family = profile.family
        self.state.alias = profile.alias
        self.state.thinking_mode = profile.thinking_mode

    async def unload(self) -> InferenceState:
        async with self._lock:
            if self.backend:
                await self.backend.stop()
            self.provider = None
            self.state.loaded = False
            self.state.loading = False
            self.state.pid = None
            return self.state

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
            "active_model": (self.state.alias or profile.alias) if self.state.loaded else None,
            "official_model": profile.repo,
            "family": self.state.family or profile.family,
            "thinking_mode": self.state.thinking_mode or profile.thinking_mode,
            "vision": self.state.vision,
            "quantization": self.state.quant or profile.quant,
            "profile": self.state.profile or profile.name,
            "context_size": self.state.context_size if self.state.loaded else profile.context_size,
            "inference_backend": self.state.backend,
            "manages_process": self.state.manages_process,
            "gpu_layers": "auto (--fit on)" if settings.inference.fit else "99",
            "flash_attn": settings.inference.flash_attn,
            "host": settings.inference.host,
            "port": settings.inference.port,
            "base_url": self.base_url(settings),
            "vram_used_mib": self.state.vram_used_mib,
            "ram_used_gb": self.state.ram_used_gb,
            "tokens_per_second": self.state.generation_tps,
            "prompt_tokens_per_second": self.state.prompt_tps,
            "load_time_seconds": self.state.load_time_seconds,
            "pid": self.state.pid,
            "last_error": self.state.last_error,
            "model_path": self.state.model_path,
            "mmproj_path": self.state.mmproj_path,
            "thinking": profile.thinking,
            "profiles": [profile_as_dict(item) for item in declared_profiles()],
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
