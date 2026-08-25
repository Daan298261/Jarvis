from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import psutil

from ..config import AppSettings, runtime_dir
from ..hardware import detect_hardware
from ..security import llama_bind_host
from ..providers.openai_compat import OpenAICompatProvider
from .benchmarks import latest_for_profile, list_benchmarks, recent_benchmarks, record_benchmark
from .endpoint import (
    env_inference_api_key,
    inference_base_url,
    inference_model_name,
    is_remote_inference,
)
from .llama_process import inspect_running_llama, kill_llama_on_port, launch_matches_profile, reasoning_flag
from .profiles import ModelProfile, model_paths, resolve_profile


@dataclass
class InferenceState:
    loaded: bool = False
    loading: bool = False
    profile: str = "abliterated-balanced"
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
    thinking_at_process: bool | None = None
    remote: bool = False


class InferenceManager:
    def __init__(self) -> None:
        self.state = InferenceState()
        self._process: asyncio.subprocess.Process | None = None
        self._log_handle = None
        self._lock = asyncio.Lock()
        self.provider: OpenAICompatProvider | None = None

    def base_url(self, settings: AppSettings) -> str:
        return inference_base_url(settings)

    async def ready_for_profile(self, profile: ModelProfile) -> bool:
        """True only when this process has a live provider matching the profile."""
        if not self.provider or not self.state.loaded:
            return False
        if self.state.profile != profile.name:
            return False
        if self.state.thinking_at_process != profile.thinking:
            return False
        try:
            return bool(await self.provider.health())
        except Exception:
            return False

    def llama_server_path(self) -> Path:
        return runtime_dir() / "llama-server.exe"

    def build_args(self, settings: AppSettings, profile: ModelProfile) -> list[str]:
        hw = detect_hardware()
        paths = model_paths(profile)
        model = paths.get("gguf") or (paths["root"] / profile.filename)
        mmproj = paths["mmproj"]
        threads = settings.inference.threads or hw.cpu_cores
        args = [
            str(self.llama_server_path()),
            "--model",
            str(model),
            "--alias",
            getattr(profile, "alias", None) or "Qwen3.5-9B-Abliterated",
            "--host",
            llama_bind_host(settings.inference.host),
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
            reasoning_flag(profile.thinking),
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
            if is_remote_inference(settings):
                return await self._attach_remote_locked(settings)
            profile = resolve_profile(profile_name or settings.inference.profile)
            paths = model_paths(profile)
            model = paths.get("gguf") or (paths["root"] / profile.filename)
            if not model.exists():
                raise FileNotFoundError(f"Model file missing: {model}")
            exe = self.llama_server_path()
            if not exe.exists():
                raise FileNotFoundError(f"llama-server missing at {exe}")

            running = inspect_running_llama(settings.inference.port)
            owned_ok = bool(
                self._process
                and self.state.loaded
                and self.state.profile == profile.name
                and self.state.thinking_at_process == profile.thinking
            )
            if owned_ok and (running is None or launch_matches_profile(running, profile)):
                return self.state

            if running and launch_matches_profile(running, profile):
                self.provider = OpenAICompatProvider(
                    self.base_url(settings),
                    api_key=env_inference_api_key() or "local",
                    model=inference_model_name(settings),
                )
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
                self.state.remote = False
                self.state.pid = int(running["pid"])
                self.state.thinking_at_process = profile.thinking
                self._hydrate_from_store()
                await self.refresh_resources()
                self.persist_benchmark("attach")
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
            self.state.remote = False
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
            self.state.thinking_at_process = profile.thinking
            self.state.load_time_seconds = round(time.time() - started, 2)
            self.provider = OpenAICompatProvider(
                self.base_url(settings),
                api_key=env_inference_api_key() or "local",
                model=inference_model_name(settings),
            )
            await self.refresh_resources()
            self.persist_benchmark("load")
            return self.state

    async def _attach_remote_locked(self, settings: AppSettings) -> InferenceState:
        url = inference_base_url(settings)
        model = inference_model_name(settings)
        api_key = env_inference_api_key() or "local"
        if (
            self.state.loaded
            and self.state.remote
            and self.provider
            and self.provider.base_url.rstrip("/") == url.rstrip("/")
            and self.provider.model == model
        ):
            if await self.provider.health():
                return self.state
        await self._stop_locked()
        self.state.loading = True
        self.state.last_error = ""
        self.state.remote = True
        self.state.backend = str(settings.inference.backend or "openai-compat")
        if self.state.backend == "llama.cpp":
            self.state.backend = "openai-compat"
        self.state.profile = settings.inference.profile
        self.state.quant = "remote"
        self.state.model_path = url
        self.state.mmproj_path = ""
        parsed = urlparse(url)
        self.state.host = parsed.hostname or settings.inference.host
        self.state.port = int(parsed.port or settings.inference.port or 8088)
        self.state.pid = None
        self.state.thinking_at_process = None
        started = time.time()
        provider = OpenAICompatProvider(url, api_key=api_key, model=model)
        if not await provider.health():
            self.state.loading = False
            self.state.last_error = f"Remote inference is unreachable: {url}"
            raise RuntimeError(self.state.last_error)
        self.provider = provider
        self.state.loaded = True
        self.state.loading = False
        self.state.load_time_seconds = round(time.time() - started, 2)
        return self.state

    async def _wait_ready(self, settings: AppSettings, timeout: float) -> bool:
        url = f"http://{llama_bind_host(settings.inference.host)}:{settings.inference.port}/health"
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
        kill_local = self._process is not None or not self.state.remote
        port = 8088 if self.state.remote else (self.state.port or 8088)
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
        self.state.thinking_at_process = None
        self.state.remote = False
        if kill_local:
            kill_llama_on_port(port)

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

    def _hydrate_from_store(self) -> None:
        latest = latest_for_profile(self.state.profile)
        if not latest:
            return
        if self.state.generation_tps is None and latest.get("tokens_per_second") is not None:
            self.state.generation_tps = latest.get("tokens_per_second")
        if self.state.prompt_tps is None and latest.get("prompt_tokens_per_second") is not None:
            self.state.prompt_tps = latest.get("prompt_tokens_per_second")
        if self.state.load_time_seconds is None and latest.get("load_time_seconds") is not None:
            self.state.load_time_seconds = latest.get("load_time_seconds")
        if self.state.vram_used_mib is None and latest.get("vram_used_mib") is not None:
            self.state.vram_used_mib = latest.get("vram_used_mib")
        if self.state.ram_used_gb is None and latest.get("ram_used_gb") is not None:
            self.state.ram_used_gb = latest.get("ram_used_gb")

    def persist_benchmark(self, source: str) -> dict[str, Any] | None:
        try:
            profile = resolve_profile(self.state.profile)
            return record_benchmark(
                profile=self.state.profile or profile.name,
                quant=self.state.quant or profile.quant,
                context_size=self.state.context_size or profile.context_size,
                thinking=profile.thinking,
                tokens_per_second=self.state.generation_tps,
                prompt_tokens_per_second=self.state.prompt_tps,
                vram_used_mib=self.state.vram_used_mib,
                ram_used_gb=self.state.ram_used_gb,
                load_time_seconds=self.state.load_time_seconds,
                source=source,
            )
        except Exception:
            return None

    async def snapshot(self, settings: AppSettings) -> dict[str, Any]:
        self._hydrate_from_store()
        await self.refresh_resources()
        healthy = False
        if self.provider:
            healthy = await self.provider.health()
        profile = resolve_profile(self.state.profile or settings.inference.profile)
        latest = latest_for_profile(self.state.profile or profile.name)
        saved = latest or {}

        def pick(live: Any, key: str) -> Any:
            return live if live is not None else saved.get(key)

        tps = pick(self.state.generation_tps, "tokens_per_second")
        prompt_tps = pick(self.state.prompt_tps, "prompt_tokens_per_second")
        load_time = pick(self.state.load_time_seconds, "load_time_seconds")
        remote = bool(self.state.remote or is_remote_inference(settings))
        model_name = inference_model_name(settings)
        if self.provider and getattr(self.provider, "model", None):
            model_name = str(self.provider.model)
        reported_loaded = bool(self.state.loaded and (healthy or self.state.loading))
        if reported_loaded:
            vram = pick(self.state.vram_used_mib, "vram_used_mib")
            ram = pick(self.state.ram_used_gb, "ram_used_gb")
        else:
            vram = saved.get("vram_used_mib")
            ram = saved.get("ram_used_gb")
        return {
            "loaded": reported_loaded,
            "loading": self.state.loading,
            "healthy": healthy,
            "active_model": model_name if self.state.loaded else None,
            "official_model": "Qwen/Qwen3.5-27B",
            "quantization": self.state.quant or profile.quant,
            "profile": self.state.profile,
            "context_size": self.state.context_size or profile.context_size,
            "inference_backend": self.state.backend,
            "remote": remote,
            "gpu_layers": "n/a" if remote else ("auto (--fit on)" if settings.inference.fit else "99"),
            "flash_attn": settings.inference.flash_attn,
            "host": self.state.host or settings.inference.host,
            "port": self.state.port or settings.inference.port,
            "base_url": self.base_url(settings),
            "model": model_name,
            "api_key_configured": bool(env_inference_api_key()),
            "vram_used_mib": vram,
            "ram_used_gb": ram,
            "tokens_per_second": tps,
            "prompt_tokens_per_second": prompt_tps,
            "load_time_seconds": load_time,
            "benchmark": latest,
            "benchmarks": list_benchmarks(),
            "benchmark_history": recent_benchmarks(12),
            "benchmark_persisted_at": saved.get("recorded_at") or saved.get("updated_at"),
            "metrics_persisted": bool(saved),
            "pid": self.state.pid,
            "last_error": self.state.last_error,
            "model_path": self.state.model_path,
            "mmproj_path": self.state.mmproj_path,
            "thinking": profile.thinking,
            "thinking_at_process": self.state.thinking_at_process,
        }

    async def record_timings(self, timings: dict[str, Any], elapsed_seconds: float | None = None, usage: dict[str, Any] | None = None) -> None:
        predicted = None
        prompt = None
        if timings:
            predicted = timings.get("predicted_per_second")
            prompt = timings.get("prompt_per_second")
        if predicted is None and elapsed_seconds and usage:
            completion = usage.get("completion_tokens") or usage.get("completion_tokens_count")
            if isinstance(completion, (int, float)) and float(elapsed_seconds) > 0:
                predicted = float(completion) / float(elapsed_seconds)
        if isinstance(predicted, (int, float)):
            self.state.generation_tps = round(float(predicted), 2)
        if isinstance(prompt, (int, float)):
            self.state.prompt_tps = round(float(prompt), 2)
        if self.state.generation_tps is None and self.state.prompt_tps is None:
            return
        await self.refresh_resources()
        self.persist_benchmark("generation")

    async def run_benchmark(self, settings: AppSettings) -> dict[str, Any]:
        if not self.state.loaded or self.provider is None:
            raise RuntimeError("Model is not loaded")
        from ..providers.base import ChatMessage

        started = time.time()
        result = await self.provider.chat(
            [ChatMessage(role="user", content="Reply with the single word ready.")],
            max_tokens=8,
            thinking=False,
        )
        elapsed = time.time() - started
        await self.record_timings(result.timings, elapsed_seconds=elapsed, usage=result.usage)
        if self.state.generation_tps is None and self.state.prompt_tps is None:
            raise RuntimeError("Benchmark ran but llama.cpp did not return tok/s timings")
        return await self.snapshot(settings)


MANAGER = InferenceManager()
