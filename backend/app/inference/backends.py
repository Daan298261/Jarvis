from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import AppSettings, logs_dir, runtime_dir
from ..hardware import detect_hardware
from .profiles import ModelProfile, model_paths
from .vision import mmproj_args

LLAMA_CPP_ALIASES = {"llama.cpp", "llamacpp", "llama_cpp", "llama", "local"}
REMOTE_ALIASES = {"remote", "openai", "openai-compat", "openai-compatible", "lan", "lmstudio", "ollama", "vllm", "sglang"}


async def wait_for_health(url: str, timeout: float, process: Any | None = None) -> bool:
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=3) as client:
        while time.time() < deadline:
            if process is not None and process.returncode is not None:
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


class InferenceBackend:
    """A way to make an OpenAI-compatible endpoint available.

    Chat always goes through `ModelProvider`. A backend only decides whether
    Jarvis has to bring the server up itself and how.
    """

    name = "abstract"
    manages_process = False
    requires_local_files = False

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    @property
    def pid(self) -> int | None:
        return None

    def health_url(self) -> str:
        return f"http://{self.settings.inference.host}:{self.settings.inference.port}/health"

    def missing_requirements(self, profile: ModelProfile) -> list[str]:
        return []

    async def start(self, profile: ModelProfile, timeout: float = 300, vision: bool = False) -> bool:
        raise NotImplementedError

    async def stop(self) -> None:
        return None

    def describe(self) -> dict[str, Any]:
        return {"backend": self.name, "manages_process": self.manages_process}


class LlamaCppBackend(InferenceBackend):
    """Local llama.cpp `llama-server`, started and supervised by Jarvis."""

    name = "llama.cpp"
    manages_process = True
    requires_local_files = True

    def __init__(self, settings: AppSettings) -> None:
        super().__init__(settings)
        self._process: asyncio.subprocess.Process | None = None
        self._log_handle = None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    def server_path(self) -> Path:
        exe = "llama-server.exe" if os.name == "nt" else "llama-server"
        candidate = runtime_dir() / exe
        if candidate.exists():
            return candidate
        return runtime_dir() / "llama-server.exe"

    def model_path(self, profile: ModelProfile) -> Path:
        return model_paths()["root"] / profile.filename

    def missing_requirements(self, profile: ModelProfile) -> list[str]:
        missing = []
        model = self.model_path(profile)
        if not model.exists():
            missing.append(f"model file missing: {model}")
        if not self.server_path().exists():
            missing.append(f"llama-server missing at {self.server_path()}")
        return missing

    def build_args(
        self,
        profile: ModelProfile,
        *,
        context_size: int | None = None,
        vision: bool = False,
    ) -> list[str]:
        hardware = detect_hardware()
        inference = self.settings.inference
        paths = model_paths()
        mmproj = paths["mmproj"]
        threads = inference.threads or hardware.cpu_cores
        ctx = int(context_size or profile.context_size or inference.context_size)
        args = [
            str(self.server_path()),
            "--model",
            str(self.model_path(profile)),
            "--alias",
            "Qwen3.5-27B",
            "--host",
            inference.host,
            "--port",
            str(inference.port),
            "--ctx-size",
            str(ctx),
            "--flash-attn",
            inference.flash_attn,
            "--jinja",
            "--reasoning-format",
            "deepseek",
            "--reasoning",
            "on" if profile.thinking else "off",
            "--cache-type-k",
            inference.cache_type_k,
            "--cache-type-v",
            inference.cache_type_v,
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
        ]
        if inference.fit:
            args.extend(["--fit", "on", "--fit-target", str(inference.fit_target_mib)])
        else:
            args.extend(["--n-gpu-layers", "99"])
        if vision and mmproj.exists():
            args.extend(["--mmproj", str(mmproj), "--image-min-tokens", "1024"])
        return args

    async def start(
        self,
        profile: ModelProfile,
        timeout: float = 300,
        *,
        context_size: int | None = None,
        vision: bool = False,
    ) -> bool:
        await self.stop()
        log_file = logs_dir() / "llama-server.log"
        self._log_handle = open(log_file, "ab", buffering=0)
        env = os.environ.copy()
        env["CUDA_MODULE_LOADING"] = "LAZY"
        self._process = await asyncio.create_subprocess_exec(
            *self.build_args(profile, context_size=context_size, vision=vision),
            cwd=str(runtime_dir()),
            stdout=self._log_handle,
            stderr=self._log_handle,
            env=env,
        )
        return await wait_for_health(self.health_url(), timeout, self._process)

    async def stop(self) -> None:
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
        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None


class RemoteOpenAICompatibleBackend(InferenceBackend):
    """An OpenAI-compatible server Jarvis does not own.

    Covers another PC on the LAN, a dedicated GPU box, LM Studio, Ollama,
    vLLM, or SGLang. Jarvis only checks that it answers.
    """

    name = "remote-openai-compatible"
    manages_process = False
    requires_local_files = False

    async def start(self, profile: ModelProfile, timeout: float = 60, vision: bool = False) -> bool:
        return await wait_for_health(self.health_url(), timeout)


def resolve_backend(settings: AppSettings) -> InferenceBackend:
    requested = (settings.inference.backend or "llama.cpp").strip().lower()
    if requested in REMOTE_ALIASES:
        return RemoteOpenAICompatibleBackend(settings)
    if requested in LLAMA_CPP_ALIASES:
        return LlamaCppBackend(settings)
    # An unknown name with a non-local host can only mean somebody else's server.
    if settings.inference.host not in {"127.0.0.1", "localhost", "::1"}:
        return RemoteOpenAICompatibleBackend(settings)
    return LlamaCppBackend(settings)
