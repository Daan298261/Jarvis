"""Launch data and resource checks for RFC-0210's owner-controlled model servers.

This is not a provider/placement registry. Runtime profiles remain authoritative
for inference routing; these records only describe how to start a local server.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..config import data_dir, runtime_dir
from .keep_alive import is_denied


class ModelStart(BaseModel):
    profile_id: str
    context_size: int | None = Field(default=None, ge=512, le=262144)
    kv_cache: Literal["server", "f16", "q8_0", "q4_0"] = "server"
    flash_attention: Literal["server", "on", "off"] = "server"
    n_cpu_moe: int | None = Field(default=None, ge=0, le=256)
    # "idle" = ANZU's idle-unload policy; "server" = the server's own default, e.g. the
    # owner's OLLAMA_KEEP_ALIVE=-1 pin. Either way Unload frees VRAM on demand.
    keep_alive: Literal["idle", "server"] = "idle"
    confirm: bool = False
    confirm_over_budget: bool = False


BUILTIN_LAUNCH_PROFILES = [
    {"id": "qwen38-quality", "label": "Qwen3.8 27B · quality / overnight coding",
     "backend": "ollama", "model": "qwen3.8:27b-q4_K_M", "port": 11434,
     "context_size": 32768, "context_ceiling": 65536, "weight_mib": 17408,
     "kv_mib_per_1k_f16": 128,
     "notes": "Owner's VRPC research: partly CPU, about 8 tok/s at 32K. Hardware-dependent, not an ANZU benchmark."},
    {"id": "anzu-coder-27b", "label": "ANZU coder 27B · interactive coding",
     "backend": "ollama", "model": "anzu-coder-27b", "port": 11434,
     "context_size": 49152, "context_ceiling": 65536, "weight_mib": 12288,
     "kv_mib_per_1k_f16": 128,
     "notes": "Owner's VRPC research: Q3_K_S, about 45 tok/s at 48K on 16 GB; 64K spills to RAM, about 10 tok/s. Cache-dependent."},
]


def profile_id(backend: str, port: int, model: str) -> str:
    return hashlib.sha256(f"{backend}:{port}:{model}".encode()).hexdigest()[:24]


def _positive_number(value, default: float = 0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else default
    except (ValueError, TypeError):
        return default


def launch_profiles(inventory: list[dict]) -> list[dict]:
    """Downloaded models plus existing configured GGUFs; never download on a click."""
    profiles = [dict(p) for p in BUILTIN_LAUNCH_PROFILES]
    for server in inventory:
        if server["backend"] not in {"ollama", "lmstudio"}:
            continue
        # CLI control currently targets LM Studio's local default instance.
        if server["backend"] == "lmstudio" and server["port"] != 1234:
            continue
        for item in server.get("available_models", []):
            name = item.get("name")
            if not name or str(name).startswith("-"):
                continue
            profiles.append({"id": profile_id(server["backend"], server["port"], name),
                "label": name, "backend": server["backend"], "port": server["port"], "model": name,
                "context_size": 4096, "context_ceiling": 65536,
                "weight_mib": _positive_number(item.get("size") or item.get("size_bytes")) / 1024**2,
                "kv_mib_per_1k_f16": 128, "estimate_uncertain": True,
                "notes": "Downloaded model. KV estimate is approximate; actual allocation depends on architecture."})
    # Reuse configured runtime profiles rather than scanning weights into a new registry.
    from .runtime_profiles import list_runtime_profiles
    from .hotswap import parse_runtime_endpoint
    from .lmstudio_server import lmstudio_cli
    configured = list_runtime_profiles()
    lms = lmstudio_cli()
    for runtime in configured:
        if runtime.provider not in {"ollama", "lmstudio", "lm-studio", "lm_studio"}:
            continue
        host, port = parse_runtime_endpoint(runtime.endpoint)
        backend = "ollama" if runtime.provider == "ollama" else "lmstudio"
        if host not in {"127.0.0.1", "localhost", "::1"} or (backend == "lmstudio" and (not lms or port != 1234)):
            continue
        profiles.append({"id": "runtime-" + runtime.id, "label": runtime.label, "backend": backend,
            "port": port, "model": runtime.model, "context_size": min(runtime.context_limit, 32768),
            "context_ceiling": min(runtime.context_limit, 262144), "kv_mib_per_1k_f16": 128,
            "notes": "Existing runtime profile. Weights must already be downloaded; memory estimate may be unknown."})
    binary = shutil.which("llama-server") or str(runtime_dir() / ("llama-server.exe" if os.name == "nt" else "llama-server"))
    if Path(binary).is_file():
        for runtime in configured:
            path = Path(runtime.gguf_path) if runtime.gguf_path else None
            if not path or not path.is_file():
                continue
            moe = "35b" in path.name.lower() and ("qwen3.6" in path.name.lower() or "qwen3_6" in path.name.lower())
            profiles.append({"id": "gguf-" + runtime.id, "label": runtime.label,
                "backend": "llama.cpp", "model": str(path), "binary": binary, "port": 8080,
                "context_size": 131072 if moe else min(runtime.context_limit, 32768),
                "context_ceiling": 262144 if moe else runtime.context_limit,
                "weight_mib": path.stat().st_size / 1024**2, "kv_mib_per_1k_f16": 128,
                "n_cpu_moe": 32 if moe else None, "notes": "Configured GGUF. CPU expert offload available." if moe else "Configured GGUF."})
    # Optional owner-local launch data, never arbitrary executable/args from an HTTP body.
    # Useful for LM Studio while its server is down and GGUFs outside the registry.
    path = data_dir() / "model-launch-profiles.json"
    if path.is_file():
        entries = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError("model-launch-profiles.json must contain a list")
        for p in entries:
            if not isinstance(p, dict) or p.get("backend") not in {"ollama", "lmstudio", "llama.cpp"}:
                raise ValueError("Invalid local launch profile")
            if p["backend"] == "llama.cpp" and not all(Path(p.get(k) or "__missing__").is_file() for k in ("binary", "model")):
                continue
            profiles.append(dict(p))
    unique = {}
    for p in profiles:
        if not p.get("id") or not p.get("model") or str(p["model"]).startswith("-"):
            continue
        if is_denied(str(p["model"])):
            continue  # RFC-0242: ANZU never starts, touches or unloads a denied model (bgm-ingest-9b)
        try:
            port = int(p.get("port", 0))
            context = int(p.get("context_size", 4096))
            ceiling = int(p.get("context_ceiling", 65536))
        except (ValueError, TypeError):
            raise ValueError("Launch profile port/context must be integers") from None
        if not 1024 <= port <= 65535 or p["backend"] == "lmstudio" and port != 1234:
            continue
        if not 512 <= context <= ceiling <= 262144:
            raise ValueError("Launch profile context must be within 512..262144 and its ceiling")
        p.update(port=port, context_size=context, context_ceiling=ceiling)
        p["kv_mib_per_1k_f16"] = _positive_number(p.get("kv_mib_per_1k_f16"), 128)
        p["weight_mib"] = _positive_number(p.get("weight_mib"))
        if p.get("n_cpu_moe") is not None and (not isinstance(p["n_cpu_moe"], int) or not 0 <= p["n_cpu_moe"] <= 256):
            raise ValueError("CPU MoE layers must be an integer between 0 and 256")
        p["server_settings"] = p["backend"] == "ollama"
        p["server_restart_required_for_options"] = p["backend"] == "ollama"
        p["kv_cache_options"] = ["server", "f16", "q8_0", "q4_0"] if p["backend"] != "lmstudio" else ["server"]
        p["flash_attention_options"] = ["server", "on", "off"] if p["backend"] != "lmstudio" else ["server"]
        p["keep_alive_options"] = ["idle", "server"] if p["backend"] != "llama.cpp" else []
        unique[p["id"]] = p
    return list(unique.values())


def vram_snapshot() -> dict:
    binary = shutil.which("nvidia-smi")
    result = {"gpus": [], "processes": [], "available": False,
              "warning": "VRAM telemetry unavailable; confirm the estimate before starting."}
    if not binary:
        return result
    def query(fields: str, kind: str) -> list[list[str]]:
        try:
            completed = subprocess.run([binary, f"--query-{kind}={fields}", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return list(csv.reader(completed.stdout.splitlines(), skipinitialspace=True)) if completed.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired):
            return []
    for row in query("index,uuid,name,memory.total,memory.used,memory.free", "gpu"):
        try:
            index, uuid, name, total, used, free = row
            result["gpus"].append({"index": int(index), "uuid": uuid, "name": name,
                                   "total_mib": float(total), "used_mib": float(used), "free_mib": float(free)})
        except (ValueError, TypeError):
            continue
    for row in query("gpu_uuid,pid,process_name,used_gpu_memory", "compute-apps"):
        try:
            uuid, pid, name, memory = row
            result["processes"].append({"gpu_uuid": uuid, "pid": int(pid), "name": name,
                "used_mib": float(memory) if memory.replace(".", "", 1).isdigit() else None})
        except (ValueError, TypeError):
            continue
    result["available"] = bool(result["gpus"])
    result["warning"] = ("Process memory may be unavailable under Windows WDDM; graphics allocations are included in GPU totals."
                         if result["available"] else result["warning"])
    return result


def budget_check(profile: dict, request: ModelStart, telemetry: dict) -> dict:
    context = request.context_size or int(profile["context_size"])
    if context > int(profile["context_ceiling"]):
        raise ValueError("Context exceeds this launch profile's ceiling")
    # Unknown server cache = f16 worst case. Full weights is deliberately conservative
    # for partial CPU/MoE offload; never promise free VRAM by subtracting guesses.
    ratio = {"server": 1, "f16": 1, "q8_0": .53125, "q4_0": .28125}[request.kv_cache]
    weights = profile.get("weight_mib")
    estimate = (float(weights) + context / 1024 * float(profile["kv_mib_per_1k_f16"]) * ratio + 1024) if weights else None
    free = max((gpu["free_mib"] for gpu in telemetry.get("gpus", [])), default=None)
    requires = estimate is None or free is None or estimate > free
    return {"estimated_mib": round(estimate) if estimate else None, "free_mib": free,
        "context_size": context, "requires_confirmation": requires,
        "warning": "Estimate includes full weights, approximate KV and 1 GiB workspace; CPU offload may reduce actual VRAM."
                   if requires else "Estimate fits currently free VRAM; allocation is not guaranteed.",
        "telemetry": telemetry}
