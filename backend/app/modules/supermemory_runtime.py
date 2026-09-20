"""Managed local Supermemory module lifecycle for RFC-0132."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .. import config as app_config
from ..memory.supermemory import UPSTREAM_RELEASE, UPSTREAM_REPOSITORY, validate_base_url
from .supervisor import StartSpec, get_supervisor

MODULE_ID = "supermemory"
MODULE_NAME = "Supermemory"
_INSTALL_LOCK = asyncio.Lock()
_INSTALL_TASK: asyncio.Task[None] | None = None
_INSTALL_STATUS = "idle"
_INSTALL_DETAIL = ""
_INSTALL_ERROR = ""


def install_dir() -> Path:
    return app_config.repo_root() / "runtime" / "supermemory"


def binary_path() -> Path:
    return install_dir() / "supermemory-server.exe"


def data_path() -> Path:
    return app_config.data_dir() / "supermemory"


def _local_endpoint() -> tuple[str, int]:
    settings = app_config.load_settings().supermemory
    base_url = validate_base_url(settings.base_url, allow_remote=False)
    parsed = urlparse(base_url)
    return base_url, int(parsed.port or (443 if parsed.scheme == "https" else 80))


async def _endpoint_reachable(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5, trust_env=False) as client:
            response = await client.get(base_url)
        return response.status_code < 500
    except httpx.HTTPError:
        return False


def _runtime_env(port: int) -> dict[str, str]:
    current = app_config.load_settings()
    inference = current.inference
    model = inference.remote_model.strip() or "jarvis-local"
    return {
        "SUPERMEMORY_DATA_DIR": str(data_path()),
        "SUPERMEMORY_PORT": str(port),
        "SUPERMEMORY_DISABLE_TELEMETRY": "1",
        "OPENAI_BASE_URL": f"http://{inference.host}:{inference.port}/v1",
        "OPENAI_API_KEY": inference.api_key.strip() or "jarvis-local",
        "OPENAI_MODEL": model,
    }


def worker_probe() -> dict[str, Any]:
    """Synchronous service inventory for the node/delegation control plane.

    Supermemory's own port is never advertised as a cross-device endpoint.
    Other devices must use Jarvis's authenticated API layer, which owns
    authorization and gives delegated tasks bounded context rather than keys.
    """
    settings = app_config.load_settings().supermemory
    installed = binary_path().is_file()
    running = get_supervisor(MODULE_ID).is_running
    if not settings.enabled:
        status = "disabled"
    elif running:
        status = "ready"
    elif installed:
        status = "not_loaded"
    else:
        status = "missing"
    return {
        "id": MODULE_ID,
        "name": MODULE_NAME,
        "kind": "memory",
        "status": status,
        "detail": "Node-local semantic recall; delegated access is mediated by Jarvis API.",
    }


async def module_status() -> dict[str, Any]:
    global _INSTALL_STATUS
    supervisor = get_supervisor(MODULE_ID)
    snapshot = supervisor.snapshot().as_dict()
    installed = binary_path().is_file()
    try:
        base_url, _ = _local_endpoint()
        healthy = await _endpoint_reachable(base_url)
        endpoint_error = ""
    except ValueError as exc:
        base_url = app_config.load_settings().supermemory.base_url
        healthy = False
        endpoint_error = str(exc)
    if installed and _INSTALL_STATUS == "idle":
        _INSTALL_STATUS = "ready"
    settings = app_config.load_settings().supermemory
    return {
        "id": MODULE_ID,
        "name": MODULE_NAME,
        "description": "Local semantic recall accelerator with automatic ContextRepo fallback.",
        "kind": "local_sidecar",
        "enabled": settings.enabled,
        "auto_start": settings.auto_start,
        "installed": installed,
        "install_status": _INSTALL_STATUS,
        "install_detail": _INSTALL_DETAIL,
        "install_error": _INSTALL_ERROR,
        "running": bool(snapshot["running"] or healthy),
        "managed": bool(snapshot["running"]),
        "starting": snapshot["starting"],
        "pid": snapshot["pid"],
        "healthy": healthy,
        "base_url": base_url,
        "console_url": base_url,
        "endpoint_error": endpoint_error,
        "last_error": snapshot["last_error"],
        "native_fallback": True,
        "authoritative_store": "jarvis_context_repo",
        "owner_vault": "obsidian",
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_release": UPSTREAM_RELEASE,
        "platform_supported": os.name == "nt",
        "computer_use_ready": True,
    }


def catalog_list_row() -> dict[str, Any]:
    settings = app_config.load_settings().supermemory
    return {
        "id": MODULE_ID,
        "name": MODULE_NAME,
        "description": "Optional local semantic recall with native fallback.",
        "kind": "local_sidecar",
        "enabled": settings.enabled,
        "installed": binary_path().is_file(),
        "downloadable": os.name == "nt",
    }


async def set_enabled(enabled: bool, *, auto_start: bool | None = None) -> dict[str, Any]:
    settings = app_config.load_settings()
    settings.supermemory.enabled = enabled
    if auto_start is not None:
        settings.supermemory.auto_start = auto_start
    app_config.save_settings(settings)
    if not enabled:
        await stop()
    return await module_status()


async def _run_bootstrap() -> None:
    global _INSTALL_STATUS, _INSTALL_DETAIL, _INSTALL_ERROR
    if os.name != "nt":
        _INSTALL_STATUS = "error"
        _INSTALL_ERROR = "The pinned automatic installer currently supports Windows x64."
        return
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    script = app_config.repo_root() / "scripts" / "bootstrap-supermemory.ps1"
    if not powershell or not script.is_file():
        _INSTALL_STATUS = "error"
        _INSTALL_ERROR = "PowerShell or the Supermemory bootstrap script is unavailable."
        return
    _INSTALL_STATUS = "installing"
    _INSTALL_DETAIL = "Downloading and verifying the pinned official release."
    _INSTALL_ERROR = ""
    process = await asyncio.create_subprocess_exec(
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-InstallPath",
        str(install_dir()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    text = output.decode("utf-8", errors="replace")
    if process.returncode != 0 or not binary_path().is_file():
        _INSTALL_STATUS = "error"
        _INSTALL_DETAIL = "Installation failed."
        _INSTALL_ERROR = (text.strip() or f"Installer exited with code {process.returncode}")[-800:]
        return
    _INSTALL_STATUS = "ready"
    _INSTALL_DETAIL = "Pinned release installed and checksum verified."
    _INSTALL_ERROR = ""


async def _install_then_start() -> None:
    global _INSTALL_STATUS, _INSTALL_DETAIL, _INSTALL_ERROR
    try:
        await _run_bootstrap()
        if _INSTALL_STATUS == "ready":
            await set_enabled(True, auto_start=True)
            await start()
    except Exception as exc:
        _INSTALL_STATUS = "error"
        _INSTALL_DETAIL = "Installation failed."
        _INSTALL_ERROR = str(exc)[:800]


async def install_and_start() -> dict[str, Any]:
    global _INSTALL_TASK, _INSTALL_STATUS, _INSTALL_DETAIL, _INSTALL_ERROR
    async with _INSTALL_LOCK:
        if _INSTALL_TASK is None or _INSTALL_TASK.done():
            _INSTALL_STATUS = "installing"
            _INSTALL_DETAIL = "Downloading and verifying the pinned official release."
            _INSTALL_ERROR = ""
            _INSTALL_TASK = asyncio.create_task(_install_then_start())
    return await module_status()


async def wait_for_install() -> None:
    """Wait for the current install/start task without exposing its internals."""
    task = _INSTALL_TASK
    if task is not None:
        await asyncio.shield(task)


async def start() -> dict[str, Any]:
    if not binary_path().is_file():
        return {**(await module_status()), "ok": False, "detail": "Install Supermemory first."}
    try:
        base_url, port = _local_endpoint()
    except ValueError as exc:
        return {**(await module_status()), "ok": False, "detail": str(exc)}
    if await _endpoint_reachable(base_url):
        return {**(await module_status()), "ok": True, "detail": "Supermemory is already running."}
    data_path().mkdir(parents=True, exist_ok=True)
    supervisor = get_supervisor(MODULE_ID)
    snapshot = await supervisor.start(
        StartSpec(
            argv=(str(binary_path()),),
            cwd=install_dir(),
            health_url=base_url,
            env=_runtime_env(port),
        )
    )
    status = await module_status()
    if not snapshot.running:
        return {**status, "ok": False, "detail": snapshot.last_error or "Supermemory did not start."}
    settings = app_config.load_settings()
    settings.supermemory.enabled = True
    app_config.save_settings(settings)
    return {**(await module_status()), "ok": True, "detail": "Supermemory started locally."}


async def stop() -> dict[str, Any]:
    supervisor = get_supervisor(MODULE_ID)
    if not supervisor.is_running:
        status = await module_status()
        detail = "An externally managed Supermemory process was left running." if status["running"] else "Supermemory is stopped."
        return {**status, "ok": True, "detail": detail}
    await supervisor.stop()
    return {**(await module_status()), "ok": True, "detail": "Jarvis-managed Supermemory stopped."}


async def auto_start() -> None:
    settings = app_config.load_settings().supermemory
    if settings.enabled and settings.auto_start and binary_path().is_file():
        await start()


async def shutdown() -> None:
    await get_supervisor(MODULE_ID).stop()


def reset_runtime_state() -> None:
    global _INSTALL_TASK, _INSTALL_STATUS, _INSTALL_DETAIL, _INSTALL_ERROR
    if _INSTALL_TASK and not _INSTALL_TASK.done():
        _INSTALL_TASK.cancel()
    _INSTALL_TASK = None
    _INSTALL_STATUS = "idle"
    _INSTALL_DETAIL = ""
    _INSTALL_ERROR = ""
