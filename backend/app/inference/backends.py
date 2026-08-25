from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import AppSettings, logs_dir, runtime_dir
from ..hardware import detect_hardware
from dataclasses import replace

from .profiles import ModelProfile, mmproj_path, model_paths, profile_gguf
from .vision import mmproj_args

LLAMA_CPP_ALIASES = {"llama.cpp", "llamacpp", "llama_cpp", "llama", "local"}
OLLAMA_ALIASES = {"ollama"}
LMSTUDIO_ALIASES = {"lmstudio", "lm-studio", "lm_studio"}
VLLM_ALIASES = {"vllm"}
SGLANG_ALIASES = {"sglang"}
REMOTE_ALIASES = {
    "remote",
    "openai",
    "openai-compat",
    "openai-compatible",
    "lan",
} | OLLAMA_ALIASES | LMSTUDIO_ALIASES | VLLM_ALIASES | SGLANG_ALIASES

DEFAULT_PORTS = {
    "llama.cpp": 8088,
    "ollama": 11434,
    "lmstudio": 1234,
    "vllm": 8000,
    "sglang": 30000,
    "remote": 8088,
}

STOCK_PORTS = set(DEFAULT_PORTS.values())

PROBE_PATHS = ("/health", "/v1/models", "/models", "/api/tags")


def inference_headers(api_key: str | None) -> dict[str, str]:
    key = (api_key or "").strip()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def parse_models_payload(path: str, payload: Any) -> list[str]:
    names: list[str] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("id"):
                    names.append(str(item["id"]))
        models = payload.get("models")
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("model") or item.get("id")
                    if name:
                        names.append(str(name))
                elif isinstance(item, str):
                    names.append(item)
        if payload.get("object") == "list" and not names and isinstance(payload.get("data"), list):
            pass
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


async def probe_remote_server(
    host: str,
    port: int,
    api_key: str = "",
    timeout: float = 8.0,
    retry: bool = False,
) -> dict[str, Any]:
    """Health-check an OpenAI-compatible (or Ollama) server and list advertised models.

    llama.cpp answers `/health`. LM Studio / vLLM / SGLang answer `/v1/models`.
    Ollama answers `/api/tags` and also `/v1/models` on recent builds.
    """
    base = f"http://{host}:{port}"
    headers = inference_headers(api_key)
    health_path = None
    models: list[str] = []
    last_error = ""
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=2, headers=headers) as client:
        while True:
            for path in PROBE_PATHS:
                try:
                    response = await client.get(base + path)
                except Exception as exc:
                    last_error = str(exc)
                    continue
                if response.status_code >= 500:
                    last_error = f"{path} returned {response.status_code}"
                    continue
                if health_path is None:
                    health_path = path
                if path in {"/v1/models", "/models", "/api/tags"}:
                    try:
                        models = parse_models_payload(path, response.json()) or models
                    except Exception:
                        pass
                if health_path == "/health" and not models:
                    continue
                if health_path:
                    break
            if health_path or not retry or time.time() >= deadline:
                break
            await asyncio.sleep(0.4)
    return {
        "ok": health_path is not None,
        "host": host,
        "port": port,
        "base_url": f"{base}/v1",
        "health_path": health_path,
        "models": models,
        "error": "" if health_path else (last_error or "no health endpoint answered"),
    }


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
        self.last_probe: dict[str, Any] = {}

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
        payload = {"backend": self.name, "manages_process": self.manages_process}
        if self.last_probe:
            payload["probe"] = {
                "ok": self.last_probe.get("ok"),
                "health_path": self.last_probe.get("health_path"),
                "models": self.last_probe.get("models") or [],
            }
        return payload


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
        return profile_gguf(profile)

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
        projector = mmproj_path(profile)
        legacy = model_paths().get("mmproj")
        if legacy and Path(legacy).exists() and not projector.exists():
            projector = Path(legacy)
        threads = inference.threads or hardware.cpu_cores
        ctx = int(context_size or profile.context_size or inference.context_size)
        args = [
            str(self.server_path()),
            "--model",
            str(self.model_path(profile)),
            "--alias",
            profile.alias,
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
        # P0.5: do not reserve VRAM for the projector unless this load needs vision.
        mode = (getattr(inference, "vision_mode", None) or ("always" if inference.vision else "lazy")).strip().lower()
        want_vision = bool(vision) or mode in {"always", "on"} or (inference.vision and mode not in {"off", "never", "disabled", "lazy"})
        if want_vision:
            args.extend(mmproj_args(replace(profile, vision=True), projector))
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
        ready = await wait_for_health(self.health_url(), timeout, self._process)
        if ready:
            self.last_probe = {
                "ok": True,
                "health_path": "/health",
                "models": [profile.alias],
            }
        return ready

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

    def health_url(self) -> str:
        return f"http://{self.settings.inference.host}:{self.settings.inference.port}/v1/models"

    async def start(self, profile: ModelProfile, timeout: float = 60) -> bool:
        self.last_probe = await probe_remote_server(
            self.settings.inference.host,
            self.settings.inference.port,
            self.settings.inference.api_key,
            timeout=timeout,
            retry=True,
        )
        return bool(self.last_probe.get("ok"))


class OllamaBackend(RemoteOpenAICompatibleBackend):
    name = "ollama"

    def health_url(self) -> str:
        return f"http://{self.settings.inference.host}:{self.settings.inference.port}/api/tags"


class LMStudioBackend(RemoteOpenAICompatibleBackend):
    name = "lmstudio"


class VLLMBackend(RemoteOpenAICompatibleBackend):
    name = "vllm"


class SGLangBackend(RemoteOpenAICompatibleBackend):
    name = "sglang"


def resolve_backend(settings: AppSettings) -> InferenceBackend:
    requested = (settings.inference.backend or "llama.cpp").strip().lower()
    if requested in OLLAMA_ALIASES:
        return OllamaBackend(settings)
    if requested in LMSTUDIO_ALIASES:
        return LMStudioBackend(settings)
    if requested in VLLM_ALIASES:
        return VLLMBackend(settings)
    if requested in SGLANG_ALIASES:
        return SGLangBackend(settings)
    if requested in REMOTE_ALIASES:
        return RemoteOpenAICompatibleBackend(settings)
    if requested in LLAMA_CPP_ALIASES:
        return LlamaCppBackend(settings)
    # An unknown name with a non-local host can only mean somebody else's server.
    if settings.inference.host not in {"127.0.0.1", "localhost", "::1"}:
        return RemoteOpenAICompatibleBackend(settings)
    return LlamaCppBackend(settings)


def suggested_port(backend: str, current_port: int) -> int:
    key = (backend or "llama.cpp").strip().lower()
    if key in OLLAMA_ALIASES:
        family = "ollama"
    elif key in LMSTUDIO_ALIASES:
        family = "lmstudio"
    elif key in VLLM_ALIASES:
        family = "vllm"
    elif key in SGLANG_ALIASES:
        family = "sglang"
    elif key in REMOTE_ALIASES:
        family = "remote"
    else:
        family = "llama.cpp"
    default = DEFAULT_PORTS[family]
    if current_port in STOCK_PORTS:
        return default
    return current_port
