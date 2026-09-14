"""Prefer GPU offload for local model servers (llama.cpp, LM Studio, Ollama)."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any
from urllib.parse import quote

import httpx

_log = logging.getLogger(__name__)

LMS_GPU_FLAG = "max"
OLLAMA_NUM_GPU = 99
LLAMA_ALL_GPU_LAYERS = "99"


def nvidia_gpu_present() -> bool:
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    if visible in {"-1", "none"}:
        return False
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            result = subprocess.run(
                [smi, "-L"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if result.returncode == 0 and "GPU" in (result.stdout or ""):
                return True
        except Exception:
            _log.debug("nvidia-smi probe failed", exc_info=True)
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def llama_cpp_gpu_args(*, fit: bool, fit_target_mib: int, prefer_gpu: bool = True) -> list[str]:
    """llama.cpp already GPU-offloads; fit keeps a VRAM reserve, else all layers."""
    del prefer_gpu
    if fit:
        return ["--fit", "on", "--fit-target", str(fit_target_mib)]
    return ["--n-gpu-layers", LLAMA_ALL_GPU_LAYERS]


def ollama_gpu_options(prefer_gpu: bool = True) -> dict[str, Any]:
    if prefer_gpu and nvidia_gpu_present():
        return {"num_gpu": OLLAMA_NUM_GPU}
    return {}


def lmstudio_cli_load_args(model: str) -> list[str] | None:
    binary = shutil.which("lms")
    if not binary or not (model or "").strip():
        return None
    return [binary, "load", model.strip(), "--gpu", LMS_GPU_FLAG, "-y"]


async def ensure_lmstudio_gpu(*, host: str, port: int, model: str, timeout: float = 120.0) -> dict[str, Any]:
    """Ask LM Studio to load `model` with maximum GPU offload. Does not drive the GUI."""
    hint = (model or "").strip()
    if not hint:
        return {"ok": False, "method": "skipped", "detail": "no model id"}
    args = lmstudio_cli_load_args(hint)
    if args:
        try:
            completed = await _run_cli(args, timeout=timeout)
            if completed.returncode == 0:
                return {"ok": True, "method": "lms-cli", "detail": (completed.stdout or "")[:400]}
            _log.warning("lms load --gpu max failed: %s", (completed.stderr or completed.stdout or "")[:400])
        except Exception as exc:
            _log.warning("lms CLI GPU load failed: %s", exc)
    rest = await _lmstudio_rest_load(host, port, hint, timeout=min(timeout, 30.0))
    if rest.get("ok"):
        return rest
    return {
        "ok": False,
        "method": rest.get("method") or "none",
        "detail": rest.get("detail") or "LM Studio GPU load was not applied",
    }


async def _run_cli(args: list[str], timeout: float):
    return await __import__("asyncio").to_thread(
        subprocess.run,
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


async def _lmstudio_rest_load(host: str, port: int, model: str, timeout: float) -> dict[str, Any]:
    root = f"http://{host}:{int(port)}"
    payloads = (
        {"model": model, "config": {"gpu": {"ratio": 1.0}}},
        {"model": model, "gpu": {"ratio": 1.0}},
        {"model_key": model, "config": {"offload_ratio": 1.0}},
    )
    paths = ("/api/v0/models/load", "/api/v1/models/load", f"/api/v0/models/{quote(model, safe='')}/load")
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        for path in paths:
            for body in payloads:
                try:
                    response = await client.post(root + path, json=body)
                except Exception as exc:
                    return {"ok": False, "method": "rest", "detail": str(exc)[:240]}
                if response.status_code < 400:
                    return {"ok": True, "method": "rest", "detail": path}
                if response.status_code in {404, 405}:
                    break
    return {"ok": False, "method": "rest", "detail": "no LM Studio load endpoint accepted a GPU request"}


async def ensure_ollama_gpu(*, host: str, port: int, model: str, timeout: float = 20.0) -> dict[str, Any]:
    """Ask Ollama to (re)load `model` with GPU layers. Chat also sends num_gpu."""
    hint = (model or "").strip()
    if not hint or not nvidia_gpu_present():
        return {"ok": False, "method": "skipped", "detail": "no model or no NVIDIA GPU"}
    url = f"http://{host}:{int(port)}/api/generate"
    body = {
        "model": hint,
        "prompt": "",
        "stream": False,
        "keep_alive": "24h",
        "options": ollama_gpu_options(),
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(url, json=body)
        if response.status_code < 400:
            return {"ok": True, "method": "ollama-generate", "detail": hint}
        return {"ok": False, "method": "ollama-generate", "detail": f"HTTP {response.status_code}"}
    except Exception as exc:
        return {"ok": False, "method": "ollama-generate", "detail": str(exc)[:240]}
