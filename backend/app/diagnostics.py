"""Redacted diagnostics for System / desktop status surfaces."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config import (
    data_dir,
    load_settings,
    logs_dir,
    models_dir,
    repo_root,
    runtime_dir,
)
from .hardware import detect_hardware
from .setup_state import load_setup_state
from .swarm.nodes import load_or_create_local_node_id

# Never include these keys (or nested) in diagnostics / copy-diagnostics.
SECRET_KEY_FRAGMENTS = (
    "private_key",
    "auth_token",
    "api_key",
    "password",
    "secret",
    "token",
    "credential",
)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(frag in lowered for frag in SECRET_KEY_FRAGMENTS)


def redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_key(str(key)):
                out[str(key)] = "[redacted]"
            else:
                out[str(key)] = redact_mapping(item)
        return out
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    return value


def frontend_version() -> str:
    pkg = repo_root() / "frontend" / "package.json"
    try:
        import json

        data = json.loads(pkg.read_text(encoding="utf-8"))
        return str(data.get("version") or "0.0.0")
    except Exception:
        return "unknown"


def app_version() -> str:
    # Prefer Tauri package version when present; fall back to FastAPI app version.
    cargo = repo_root() / "frontend" / "src-tauri" / "Cargo.toml"
    if cargo.exists():
        try:
            for line in cargo.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("version"):
                    return line.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass
    return "1.0.0"


def build_diagnostics(
    *,
    model_snapshot: dict[str, Any] | None = None,
    backend_pid: int | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    hw = detect_hardware()
    setup = load_setup_state()
    node_id = load_or_create_local_node_id()
    hostname = getattr(hw, "hostname", None) or os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or ""

    inference_status = "unloaded"
    if model_snapshot:
        if model_snapshot.get("loading"):
            inference_status = "loading"
        elif model_snapshot.get("loaded"):
            inference_status = "loaded"

    payload: dict[str, Any] = {
        "application_version": app_version(),
        "frontend_version": frontend_version(),
        "backend_version": "1.0.0",
        "backend_status": "ready",
        "backend_pid": backend_pid or os.getpid(),
        "api_port": settings.bind_port,
        "bind_host": settings.bind_host,
        "inference_backend": settings.inference.backend,
        "inference_host": settings.inference.host,
        "inference_port": settings.inference.port,
        "inference_profile": settings.inference.profile,
        "inference_status": inference_status,
        "local_model": (model_snapshot or {}).get("active_model") or "",
        "model_loaded": bool((model_snapshot or {}).get("loaded")),
        "model_loading": bool((model_snapshot or {}).get("loading")),
        "model_last_error": (model_snapshot or {}).get("last_error") or "",
        "node_id": node_id,
        "hostname": hostname,
        "data_directory": str(data_dir()),
        "logs_directory": str(logs_dir()),
        "runtime_directory": str(runtime_dir()),
        "models_directory": str(models_dir()),
        "repo_root": str(repo_root()),
        "setup_completed": bool(setup.get("completed")),
        "setup_step": setup.get("current_step"),
        "os_name": hw.os_name,
        "os_version": hw.os_version,
        "cpu_name": hw.cpu_name,
        "cpu_cores": hw.cpu_cores,
        "cpu_threads": hw.cpu_threads,
        "ram_total_gb": hw.ram_total_gb,
        "gpu_name": hw.gpu_name,
        "vram_total_mib": hw.vram_total_mib,
        "disk_free_gb": hw.disk_free_gb,
        "log_files": _list_log_files(),
    }
    return redact_mapping(payload)


def diagnostics_text(payload: dict[str, Any] | None = None) -> str:
    data = payload or build_diagnostics()
    lines = [f"{key}: {value}" for key, value in data.items()]
    return "\n".join(lines) + "\n"


def _list_log_files() -> list[str]:
    root = logs_dir()
    names: list[str] = []
    try:
        for path in sorted(root.glob("*.log")):
            names.append(str(path))
    except Exception:
        pass
    return names
