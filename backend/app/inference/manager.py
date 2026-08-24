from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from ..config import AppSettings, logs_dir
from ..providers.openai_compat import OpenAICompatProvider
from .backends import InferenceBackend, resolve_backend
from .profiles import ModelProfile, model_paths, resolve_profile, with_context


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
    context_size: int = 32768
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


class InferenceManager:
    """Owns model lifecycle. Process control is delegated to an InferenceBackend."""

    def __init__(self) -> None:
        self.state = InferenceState()
        self.backend: InferenceBackend | None = None
        self._lock = asyncio.Lock()
        self.provider: OpenAICompatProvider | None = None

    def base_url(self, settings: AppSettings) -> str:
        return f"http://{settings.inference.host}:{settings.inference.port}/v1"

    async def load(
        self,
        settings: AppSettings,
        profile_name: str | None = None,
        context_size: int | None = None,
        force: bool = False,
    ) -> InferenceState:
        async with self._lock:
            profile = resolve_profile(profile_name or settings.inference.profile)
            if context_size:
                profile = with_context(profile, int(context_size))
            backend = resolve_backend(settings)
            paths = model_paths()
            model = paths["root"] / profile.filename

            missing = backend.missing_requirements(profile)
            if missing:
                self.state.last_error = "; ".join(missing)
                raise FileNotFoundError(self.state.last_error)

            same = (
                self.backend
                and self.state.loaded
                and self.state.profile == profile.name
                and self.backend.name == backend.name
                and int(self.state.context_size or 0) == int(profile.context_size or 0)
            )
            if same and not force:
                return self.state

            self._apply_profile_state(settings, profile, backend, model, paths)

            # Adopt a server that is already answering when we did not start one.
            existing = OpenAICompatProvider(self.base_url(settings), model="Qwen3.5-27B")
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
                fallback = with_context(profile, 16384)
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
            self.provider = OpenAICompatProvider(self.base_url(settings), model="Qwen3.5-27B")
            await self.refresh_resources()
            return self.state

    def _apply_profile_state(
        self,
        settings: AppSettings,
        profile: ModelProfile,
        backend: InferenceBackend,
        model: Path,
        paths: dict[str, Path],
    ) -> None:
        self.state.profile = profile.name
        self.state.quant = profile.quant
        self.state.model_path = str(model) if backend.requires_local_files else ""
        self.state.mmproj_path = str(paths["mmproj"]) if paths["mmproj"].exists() else ""
        self.state.host = settings.inference.host
        self.state.port = settings.inference.port
        self.state.context_size = profile.context_size
        self.state.backend = backend.name
        self.state.manages_process = backend.manages_process

    async def unload(self) -> InferenceState:
        async with self._lock:
            if self.backend:
                await self.backend.stop()
            self.provider = None
            self.state.loaded = False
            self.state.loading = False
            self.state.pid = None
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
            await self.load(settings, self.state.profile or settings.inference.profile, context_size=target, force=True)
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
            "active_model": "Qwen3.5-27B" if self.state.loaded else None,
            "official_model": "Qwen/Qwen3.5-27B",
            "quantization": self.state.quant or profile.quant,
            "profile": self.state.profile,
            "context_size": self.state.context_size or profile.context_size,
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
