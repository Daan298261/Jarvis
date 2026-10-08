"""Grow only idle, local LM Studio instances with verified resource headroom."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil

from ..observability.rolling_log import record_event
from .request_lease import RequestLease

_log = logging.getLogger(__name__)
_resize_lock = asyncio.Lock()


class LocalContextRestoreError(Exception):
    """The local instance was unloaded and could not be restored to its original load."""


def admitted(estimated_gpu_gib: float, estimated_total_gib: float, *, gpu_total_gib: float,
             other_gpu_gib: float, available_ram_gib: float) -> bool:
    return (estimated_gpu_gib > 0 and estimated_total_gib > 0
            and estimated_gpu_gib + max(0, other_gpu_gib) + 3 <= gpu_total_gib
            and estimated_total_gib + 12 <= available_ram_gib)


def _nested_config(row: dict[str, Any]) -> dict[str, Any]:
    config = row.get("config")
    return config if isinstance(config, dict) else {}


def gpu_offload_from_row(row: dict[str, Any]) -> str | None:
    """Return the original ``lms load --gpu`` value, or None if it was not recorded."""
    gpu = row.get("gpu")
    if gpu is None:
        gpu = _nested_config(row).get("gpu")
    if isinstance(gpu, dict):
        kind = str(gpu.get("type") or gpu.get("offload") or "").strip().lower()
        if kind in {"max", "off"}:
            return kind
        ratio = gpu.get("ratio", gpu.get("value"))
        if ratio is True or ratio == 1 or ratio == "max":
            return "max"
        if ratio is False or ratio == 0 or ratio == "off":
            return "off"
        if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
            if ratio >= 1:
                return "max"
            if ratio <= 0:
                return "off"
            return str(ratio)
        if isinstance(ratio, str) and ratio.strip():
            return ratio.strip()
        return None
    if gpu is True or gpu == "max":
        return "max"
    if gpu is False or gpu in {"off", "0"}:
        return "off"
    if isinstance(gpu, (int, float)) and not isinstance(gpu, bool):
        if gpu >= 1:
            return "max"
        if gpu <= 0:
            return "off"
        return str(gpu)
    if isinstance(gpu, str) and gpu.strip():
        return gpu.strip()
    return None


def instance_load_args(row: dict[str, Any], *, key: str, identifier: str, context_length: int) -> list[Any]:
    """Rebuild ``lms load`` arguments from the original ``lms ps --json`` row."""
    config = _nested_config(row)
    args: list[Any] = [key, "--identifier", identifier]
    gpu = gpu_offload_from_row(row)
    if gpu is not None:
        args.extend(["--gpu", gpu])
    parallel = row.get("parallel", config.get("parallel"))
    if parallel is not None:
        args.extend(["--parallel", parallel])
    args.extend(["--context-length", context_length, "--yes"])
    ttl = row.get("ttl", config.get("ttl"))
    if isinstance(ttl, (int, float)) and not isinstance(ttl, bool) and ttl > 0:
        args.extend(["--ttl", int(ttl)])
    flash = row.get("flashAttention", config.get("flashAttention", config.get("flash_attn")))
    if flash is True or flash in {"on", "auto-on"}:
        args.append("--flash-attention")
    return args


def _surface_restore_failure(identifier: str, error: BaseException) -> None:
    message = f"Failed to restore LM Studio instance {identifier}: {error}"
    _log.error(message)
    record_event("context_restore_failed", message=message, identifier=identifier)


async def grow_local_instance(
    settings,
    target: int,
    identifier: str,
    *,
    lease: RequestLease | None = None,
    on_unloaded: Any | None = None,
) -> int | None:
    # CLI talks to the local daemon. Never use it for another computer/port.
    if settings.inference.host not in {"localhost", "127.0.0.1", "::1"} or settings.inference.port != 1234:
        return None
    cli = shutil.which("lms")
    fallback = Path.home() / ".lmstudio/bin/lms.exe"
    if not cli and fallback.is_file():
        cli = str(fallback)
    if not cli:
        return None
    lease = lease or RequestLease()

    async def run(*args):
        def execute():
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            result = subprocess.run([cli, *map(str, args)], capture_output=True, text=True,
                                    timeout=180, creationflags=flags)
            if result.returncode:
                raise RuntimeError(result.stderr or result.stdout)
            return result.stdout
        pending = asyncio.create_task(asyncio.to_thread(execute))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            # A CLI load can outlive cancellation. Finish it before restoring the slot.
            await pending
            raise

    async with _resize_lock:
        original_args: list[Any] = []
        old = 0
        try:
            rows = json.loads(await run("ps", "--json"))
            row = next((r for r in rows if r.get("identifier") == identifier), None)
            if not row:
                return None
            old = int(row["contextLength"])
            if old >= target:
                return old
            if row.get("status") != "idle" or row.get("queued", 0):
                return None
            key = row["modelKey"]
            target = min(target, int(row["maxContextLength"]))
            original_args = instance_load_args(row, key=key, identifier=identifier, context_length=old)

            async def estimate(size):
                output = await run("load", key, "--gpu", "max", "--parallel", 1,
                                   "--context-length", size, "--estimate-only")
                gpu = re.search(r"Estimated GPU Memory:\s*([\d.]+) GiB", output)
                total = re.search(r"Estimated Total Memory:\s*([\d.]+) GiB", output)
                if not gpu or not total:
                    raise ValueError("LM Studio did not return a resource estimate")
                return float(gpu[1]), float(total[1])

            current_gpu, _ = await estimate(old)
            def resources():
                result = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,memory.used",
                                         "--format=csv,noheader,nounits"], capture_output=True,
                                        text=True, timeout=5, check=True)
                total, used = map(float, result.stdout.splitlines()[0].split(","))
                return total / 1024, max(0, used / 1024 - current_gpu), psutil.virtual_memory().available / 1024**3
            total, other, available = await asyncio.to_thread(resources)
            chosen = 0
            for size in sorted({16384, 32768, 65536, 131072, 262144, target}, reverse=True):
                if size > target or size <= old:
                    continue
                gpu, memory = await estimate(size)
                if admitted(gpu, memory, gpu_total_gib=total, other_gpu_gib=other, available_ram_gib=available):
                    chosen = size
                    break
            if not chosen:
                return None
            async with lease.exclusive() as acquired:
                if not acquired:
                    return None
                # Recheck idle under the exclusive lease so no request can start in the gap.
                check = next((r for r in json.loads(await run("ps", "--json")) if r.get("identifier") == identifier), {})
                if check.get("status") != "idle" or check.get("queued", 0):
                    return None
                try:
                    await run("unload", identifier)
                    await run("load", key, "--identifier", identifier, "--gpu", "max", "--parallel", 1,
                              "--context-length", chosen, "--yes")
                    loaded = next(r for r in json.loads(await run("ps", "--json")) if r.get("identifier") == identifier)
                    if int(loaded["contextLength"]) != chosen:
                        raise ValueError("Loaded context differs from requested context")
                    return chosen
                except BaseException as original:
                    try:
                        await _restore_original(run, identifier, original_args, old)
                    except LocalContextRestoreError as restore_exc:
                        if on_unloaded is not None:
                            on_unloaded(str(restore_exc))
                        raise restore_exc
                    raise original
        except LocalContextRestoreError:
            raise
        except (RuntimeError, ValueError, KeyError, StopIteration, OSError, subprocess.SubprocessError):
            return None


async def _restore_original(run, identifier: str, original_args: list[Any], old: int) -> None:
    """Reload the instance with the captured original settings. Failures are fatal."""
    async def restore():
        try:
            await run("unload", identifier)
        except Exception as exc:
            _log.warning("unload during context restore failed for %s: %s", identifier, exc)
        if not original_args:
            raise RuntimeError("original load settings were not captured")
        await run("load", *original_args)
        loaded = next(r for r in json.loads(await run("ps", "--json")) if r.get("identifier") == identifier)
        if int(loaded["contextLength"]) != old:
            raise ValueError("Restored context differs from the original load")

    try:
        await asyncio.shield(restore())
    except Exception as exc:
        _surface_restore_failure(identifier, exc)
        raise LocalContextRestoreError(
            f"The local model was unloaded and could not be restored at {old} context: {exc}"
        ) from exc
