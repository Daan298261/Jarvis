"""Start a local LM Studio app + HTTP server when Play needs it."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from .backends import probe_remote_server

_log = logging.getLogger(__name__)

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SERVER_WAIT_SECONDS = 45.0
POLL_SECONDS = 1.0


async def resolve_lmstudio_artifact(
    host: str, port: int, hint: str, quantization: str, advertised: list[str], api_key: str = "",
) -> str | None:
    """Map renamed GGUFs using an exact native display name AND quantization.

    LM Studio can expose a repository alias different from the local filename.
    Never compensate with a family-only or first-model fallback.
    """
    if not hint or not quantization:
        return None
    filename = hint.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".gguf")
    base = re.sub(rf"[-_. @]*{re.escape(quantization)}$", "", filename, flags=re.IGNORECASE)
    normalize = lambda value: re.sub(r"[^a-z0-9]", "", str(value).lower())
    from .backends import inference_headers

    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False, headers=inference_headers(api_key)) as client:
            response = await client.get(f"http://{host}:{port}/api/v1/models")
            response.raise_for_status()
            rows = response.json().get("models", [])
        matches = {
            str(row["key"]) for row in rows
            if isinstance(row, dict) and row.get("type") == "llm"
            and row.get("key") in advertised
            and isinstance(row.get("quantization"), dict)
            and normalize(row["quantization"].get("name")) == normalize(quantization)
            and normalize(row.get("display_name")) == normalize(base)
        }
        return next(iter(matches)) if len(matches) == 1 else None
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return None


def is_loopback_host(host: str) -> bool:
    return (host or "").strip().lower() in LOOPBACK


def lmstudio_cli() -> str | None:
    found = shutil.which("lms")
    if found:
        return found
    home = Path.home()
    for candidate in (home / ".lmstudio" / "bin" / "lms.exe", home / ".lmstudio" / "bin" / "lms"):
        if candidate.is_file():
            return str(candidate)
    return None


def lmstudio_app_path() -> Path | None:
    local = Path(os.environ.get("LOCALAPPDATA") or "")
    program_files = Path(os.environ.get("PROGRAMFILES") or r"C:\Program Files")
    candidates = (
        local / "Programs" / "LM Studio" / "LM Studio.exe",
        local / "LM-Studio" / "LM Studio.exe",
        program_files / "LM Studio" / "LM Studio.exe",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def _launch_app(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 — owner-local LM Studio executable
        return
    subprocess.Popen(  # noqa: S603
        [str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _run_cli(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


async def _wait_until_up(host: str, port: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {"ok": False, "error": "LM Studio did not become ready"}
    while time.monotonic() < deadline:
        last = await probe_remote_server(host, port, timeout=2.0, retry=False)
        if last.get("ok"):
            return last
        await asyncio.sleep(POLL_SECONDS)
    return last


async def ensure_local_lmstudio(
    *,
    host: str,
    port: int,
    model: str = "",
    context_size: int = 16384,
    timeout: float = SERVER_WAIT_SECONDS,
) -> dict[str, Any]:
    """Bring up loopback LM Studio so Play can continue without a manual start."""
    if not is_loopback_host(host):
        return {"ok": False, "method": "skipped", "detail": "refusing to auto-start a remote LM Studio"}

    probe = await probe_remote_server(host, port, timeout=2.0, retry=False)
    loaded = await _loaded_model_ids(host, port) if probe.get("ok") and model else None
    model_ready = not model or (model in loaded if loaded is not None else model in (probe.get("models") or []))
    if probe.get("ok") and model_ready:
        return {"ok": True, "method": "already-up", "detail": "LM Studio was already serving"}

    cli = lmstudio_cli()
    app = lmstudio_app_path()
    if not cli and not app:
        return {
            "ok": False,
            "method": "missing",
            "detail": "LM Studio is not installed on this PC",
        }

    if app and not probe.get("ok"):
        try:
            await asyncio.to_thread(_launch_app, app)
        except Exception as exc:
            _log.warning("Could not launch LM Studio app: %s", exc)

    if cli and not probe.get("ok"):
        try:
            started = await asyncio.to_thread(
                _run_cli,
                [cli, "server", "start"] if int(port) == 1234 else [cli, "server", "start", "--port", str(int(port))],
                30.0,
            )
            if started.returncode != 0:
                _log.warning(
                    "lms server start exited %s: %s",
                    started.returncode,
                    (started.stderr or started.stdout or "")[:400],
                )
        except Exception as exc:
            _log.warning("lms server start failed: %s", exc)

    ready = probe if probe.get("ok") else await _wait_until_up(host, port, timeout)
    if not ready.get("ok"):
        return {
            "ok": False,
            "method": "wait",
            "detail": ready.get("error") or "LM Studio did not open its local server",
        }

    hint = (model or "").strip()
    if hint and cli:
        try:
            requested_context = max(4096, min(65536, int(context_size or 16384)))
            loaded = await asyncio.to_thread(
                _run_cli,
                [cli, "load", hint, "-c", str(requested_context), "-y"],
                min(timeout, 90.0),
            )
            if loaded.returncode != 0:
                _log.warning("lms load failed: %s", (loaded.stderr or loaded.stdout or "")[:400])
        except Exception as exc:
            _log.warning("lms load failed: %s", exc)
        ready = await probe_remote_server(host, port, timeout=4.0, retry=True)

    loaded = await _loaded_model_ids(host, port) if model else None
    model_ready = not model or (model in loaded if loaded is not None else model in (ready.get("models") or []))
    return {
        "ok": bool(ready.get("ok") and model_ready),
        "method": "auto-start",
        "detail": "Started LM Studio on this PC" if model_ready else "The selected LM Studio model did not load",
        "models": list(ready.get("models") or []),
    }


async def _loaded_model_ids(host: str, port: int) -> set[str] | None:
    """Native inventory distinguishes loaded weights from downloaded/JIT models."""
    async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
        for path in ("/api/v1/models", "/api/v0/models"):
            try:
                response = await client.get(f"http://{host}:{port}{path}")
                if not response.is_success:
                    continue
                body = response.json()
                if not isinstance(body, dict):
                    continue
                modern = body.get("models")
                if isinstance(modern, list) and any(isinstance(row, dict) and "loaded_instances" in row for row in modern):
                    result = set()
                    for row in modern:
                        if isinstance(row, dict) and row.get("type") == "llm" and row.get("loaded_instances"):
                            if row.get("key"):
                                result.add(str(row["key"]))
                            result.update(str(item["id"]) for item in row["loaded_instances"] if isinstance(item, dict) and item.get("id"))
                    return result
                legacy = body.get("data")
                if isinstance(legacy, list) and any(isinstance(row, dict) and "state" in row for row in legacy):
                    return {str(row["id"]) for row in legacy if isinstance(row, dict) and row.get("state") == "loaded" and row.get("id")}
            except (httpx.HTTPError, ValueError, TypeError):
                continue
    return None
