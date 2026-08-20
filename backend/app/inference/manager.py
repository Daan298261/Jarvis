from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psutil

from ..config import AppSettings, runtime_dir
from ..hardware import detect_hardware
from ..providers.openai_compat import OpenAICompatProvider
from .profiles import ModelProfile, model_paths, resolve_profile


@dataclass
class InferenceState:
    loaded: bool = False
    loading: bool = False
    profile: str = "balanced"
    quant: str = ""
    model_path: str = ""
    mmproj_path: str = ""
    backend: str = "llama.cpp"
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
    def __init__(self) -> None:
        self.state = InferenceState()
        self._process: asyncio.subprocess.Process | None = None
        self._log_handle = None
        self._lock = asyncio.Lock()
        self.provider: OpenAICompatProvider | None = None

    def base_url(self, settings: AppSettings) -> str:
        return f"http://{settings.inference.host}:{settings.inference.port}/v1"

    def llama_server_path(self) -> Path:
        return runtime_dir() / "llama-server.exe"

    def build_args(self, settings: AppSettings, profile: ModelProfile) -> list[str]:
        hw = detect_hardware()
        paths = model_paths()
        model = paths["root"] / profile.filename
        mmproj = paths["mmproj"]
        threads = settings.inference.threads or hw.cpu_cores
        args = [
            str(self.llama_server_path()),
            "--model",
            str(model),
            "--alias",
            "Qwen3.5-27B",
            "--host",
            settings.inference.host,
            "--port",
            str(settings.inference.port),
            "--ctx-size",
            str(profile.context_size if profile.context_size else settings.inference.context_size),
            "--flash-attn",
            settings.inference.flash_attn,
            "--jinja",
            "--reasoning-format",
            "deepseek",
            "--reasoning",
            "on" if profile.thinking else "off",
            "--cache-type-k",
            settings.inference.cache_type_k,
            "--cache-type-v",
            settings.inference.cache_type_v,
            "--threads",
            str(threads),
            "--temp",
            str(profile.temperature),
            "--top-p",
            str(profile.top_p),
            "--top-k",
            str(profile.top_k),
            "--min-p",
            "0",
            "--prio",
            "3",
            "--metrics",
            "--image-min-tokens",
            "1024",
        ]
        if settings.inference.fit:
            args.extend(["--fit", "on", "--fit-target", str(settings.inference.fit_target_mib)])
        else:
            args.extend(["--n-gpu-layers", "99"])
        if mmproj.exists():
            args.extend(["--mmproj", str(mmproj)])
        return args

    async def load(self, settings: AppSettings, profile_name: str | None = None) -> InferenceState:
        async with self._lock:
            profile = resolve_profile(profile_name or settings.inference.profile)
            paths = model_paths()
            model = paths["root"] / profile.filename
            if not model.exists():
                raise FileNotFoundError(f"Model file missing: {model}")
            exe = self.llama_server_path()
            if not exe.exists():
                raise FileNotFoundError(f"llama-server missing at {exe}")

            if self._process and self.state.loaded and self.state.profile == profile.name:
                return self.state

            existing = OpenAICompatProvider(self.base_url(settings), model="Qwen3.5-27B")
            if await existing.health() and not self._process:
                self.provider = existing
                self.state.loaded = True
                self.state.loading = False
                self.state.profile = profile.name
                self.state.quant = profile.quant
                self.state.model_path = str(model)
                self.state.mmproj_path = str(paths["mmproj"]) if paths["mmproj"].exists() else ""
                self.state.host = settings.inference.host
                self.state.port = settings.inference.port
                self.state.context_size = profile.context_size
                self.state.backend = "llama.cpp"
                await self.refresh_resources()
                return self.state

            await self._stop_locked()
            self.state.loading = True
            self.state.last_error = ""
            self.state.profile = profile.name
            self.state.quant = profile.quant
            self.state.model_path = str(model)
            self.state.mmproj_path = str(paths["mmproj"]) if paths["mmproj"].exists() else ""
            self.state.host = settings.inference.host
            self.state.port = settings.inference.port
            self.state.context_size = profile.context_size
            self.state.backend = "llama.cpp"
            args = self.build_args(settings, profile)
            from ..config import logs_dir

            log_file = logs_dir() / "llama-server.log"
            started = time.time()
            if self._log_handle:
                try:
                    self._log_handle.close()
                except Exception:
                    pass
            self._log_handle = open(log_file, "ab", buffering=0)
            env = os.environ.copy()
            env["CUDA_MODULE_LOADING"] = "LAZY"
            self._process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(runtime_dir()),
                stdout=self._log_handle,
                stderr=self._log_handle,
                env=env,
            )
            self.state.pid = self._process.pid
            ready = await self._wait_ready(settings, timeout=300)
            if not ready:
                await self._stop_locked()
                fallback_profile = ModelProfile(
                    name=profile.name,
                    label=profile.label,
                    quant=profile.quant,
                    filename=profile.filename,
                    thinking=profile.thinking,
                    context_size=16384,
                    temperature=profile.temperature,
                    top_p=profile.top_p,
                    top_k=profile.top_k,
                    presence_penalty=profile.presence_penalty,
                    description=profile.description,
                )
                args = self.build_args(settings, fallback_profile)
                self._process = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=str(runtime_dir()),
                    stdout=self._log_handle,
                    stderr=self._log_handle,
                    env=env,
                )
                self.state.pid = self._process.pid
                self.state.context_size = 16384
                ready = await self._wait_ready(settings, timeout=240)
            if not ready:
                self.state.loading = False
                self.state.last_error = "llama-server did not become ready"
                raise RuntimeError(self.state.last_error + f". See {log_file}")
            self.state.loaded = True
            self.state.loading = False
            self.state.load_time_seconds = round(time.time() - started, 2)
            self.provider = OpenAICompatProvider(self.base_url(settings), model="Qwen3.5-27B")
            await self.refresh_resources()
            return self.state

    async def _wait_ready(self, settings: AppSettings, timeout: float) -> bool:
        url = f"http://{settings.inference.host}:{settings.inference.port}/health"
        deadline = time.time() + timeout
        async with httpx.AsyncClient(timeout=3) as client:
            while time.time() < deadline:
                if self._process and self._process.returncode is not None:
                    return False
                try:
                    response = await client.get(url)
                    if response.status_code < 500:
                        return True
                except Exception:
                    await asyncio.sleep(1.2)
                    continue
                await asyncio.sleep(0.8)
        return False

    async def unload(self) -> InferenceState:
        async with self._lock:
            await self._stop_locked()
            return self.state

    async def _stop_locked(self) -> None:
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=8)
                except TimeoutError:
                    self._process.kill()
                    await self._process.wait()
            except Exception:
                pass
        self._process = None
        self.provider = None
        self.state.loaded = False
        self.state.loading = False
        self.state.pid = None

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


MANAGER = InferenceManager()
