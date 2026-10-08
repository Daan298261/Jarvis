"""Grow only idle, local LM Studio instances with verified resource headroom."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path

import psutil

_resize_lock = asyncio.Lock()


def admitted(estimated_gpu_gib: float, estimated_total_gib: float, *, gpu_total_gib: float,
             other_gpu_gib: float, available_ram_gib: float) -> bool:
    return (estimated_gpu_gib > 0 and estimated_total_gib > 0
            and estimated_gpu_gib + max(0, other_gpu_gib) + 3 <= gpu_total_gib
            and estimated_total_gib + 12 <= available_ram_gib)


async def grow_local_instance(settings, target: int, identifier: str) -> int | None:
    # CLI talks to the local daemon. Never use it for another computer/port.
    if settings.inference.host not in {"localhost", "127.0.0.1", "::1"} or settings.inference.port != 1234:
        return None
    cli = shutil.which("lms")
    fallback = Path.home() / ".lmstudio/bin/lms.exe"
    if not cli and fallback.is_file():
        cli = str(fallback)
    if not cli:
        return None

    async def run(*args):
        def execute():
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            result = subprocess.run([cli, *map(str, args)], capture_output=True, text=True,
                                    timeout=180, creationflags=flags)
            if result.returncode:
                raise RuntimeError(result.stderr or result.stdout)
            return result.stdout
        return await asyncio.to_thread(execute)

    async with _resize_lock:
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
            # Recheck idle immediately before mutation. A busy instance is left alone.
            check = next((r for r in json.loads(await run("ps", "--json")) if r.get("identifier") == identifier), {})
            if check.get("status") != "idle" or check.get("queued", 0):
                return None
            await run("unload", identifier)
            try:
                await run("load", key, "--identifier", identifier, "--gpu", "max", "--parallel", 1,
                          "--context-length", chosen, "--yes")
                loaded = next(r for r in json.loads(await run("ps", "--json")) if r.get("identifier") == identifier)
                if int(loaded["contextLength"]) != chosen:
                    raise ValueError("Loaded context differs from requested context")
                return chosen
            except BaseException:
                # Shield restoration from task cancellation; preserve the same API identifier.
                async def restore():
                    try:
                        await run("unload", identifier)
                    except Exception:
                        pass
                    await run("load", key, "--identifier", identifier, "--gpu", "max", "--parallel",
                              row.get("parallel", 1), "--context-length", old, "--yes")
                await asyncio.shield(restore())
                raise
        except (RuntimeError, ValueError, KeyError, StopIteration, OSError, subprocess.SubprocessError):
            return None
