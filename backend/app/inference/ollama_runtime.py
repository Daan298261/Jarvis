"""Ensure loopback Ollama is up and the requested model is present (installer + Play)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
import time
from typing import Any

from .backends import probe_remote_server, resolve_advertised_model
from .gpu_prefer import ensure_ollama_gpu
from ..persona.persona_brain import UMI_OLLAMA_MODEL

_log = logging.getLogger(__name__)

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PULL_TIMEOUT_SECONDS = 3600.0
SERVER_WAIT_SECONDS = 45.0
POLL_SECONDS = 1.0


def is_loopback_host(host: str) -> bool:
    return (host or "").strip().lower() in LOOPBACK


def ollama_cli() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    if sys.platform == "win32":
        local = shutil.which("ollama.exe")
        if local:
            return local
    return None


def _model_present(advertised: list[str], model: str) -> bool:
    hint = (model or "").strip()
    if not hint:
        return bool(advertised)
    resolved = resolve_advertised_model(hint, advertised)
    if resolved in advertised:
        return True
    lower = hint.lower()
    return any(lower in name.lower() or name.lower() in lower for name in advertised)


def _run_ollama(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    cli = ollama_cli()
    if not cli:
        raise FileNotFoundError("ollama CLI is not installed")
    return subprocess.run(
        [cli, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


async def _wait_until_up(host: str, port: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {"ok": False, "error": "Ollama did not become ready"}
    while time.monotonic() < deadline:
        last = await probe_remote_server(host, port, timeout=2.0, retry=False)
        if last.get("ok"):
            return last
        await asyncio.sleep(POLL_SECONDS)
    return last


async def ensure_local_ollama(
    *,
    host: str,
    port: int,
    model: str = "",
    timeout: float = SERVER_WAIT_SECONDS,
    pull_if_missing: bool = True,
) -> dict[str, Any]:
    """Bring up loopback Ollama and ensure `model` is pulled and warmed when possible."""
    if not is_loopback_host(host):
        return {"ok": False, "method": "skipped", "detail": "refusing to auto-manage a remote Ollama host"}

    hint = (model or UMI_OLLAMA_MODEL).strip()
    probe = await probe_remote_server(host, port, timeout=2.0, retry=False)
    if not probe.get("ok"):
        if not ollama_cli():
            return {
                "ok": False,
                "method": "missing-cli",
                "detail": "Ollama is not installed. Re-run the Jarvis installer Umi brain option.",
            }
        probe = await _wait_until_up(host, port, timeout)
        if not probe.get("ok"):
            return {
                "ok": False,
                "method": "server-down",
                "detail": probe.get("error") or "Ollama is not responding on loopback",
            }

    advertised = list(probe.get("models") or [])
    if pull_if_missing and hint and not _model_present(advertised, hint):
        if not ollama_cli():
            return {"ok": False, "method": "missing-cli", "detail": "Ollama CLI missing for model pull"}
        _log.info("ollama_pull_start model=%s", hint[:120])
        try:
            completed = await asyncio.to_thread(
                _run_ollama,
                ["pull", hint],
                timeout=PULL_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "method": "pull-timeout", "detail": f"Timed out pulling {hint}"}
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "ollama pull failed").strip()[:240]
            return {"ok": False, "method": "pull-failed", "detail": detail}
        probe = await probe_remote_server(host, port, timeout=8.0, retry=True)
        advertised = list(probe.get("models") or [])

    resolved = resolve_advertised_model(hint, advertised) if hint else (advertised[0] if advertised else "")
    if hint and advertised and not _model_present(advertised, hint):
        return {
            "ok": False,
            "method": "model-missing",
            "detail": f"Model {hint} is not available after pull",
            "models": advertised[:8],
        }

    warm: dict[str, Any] = {"ok": True, "method": "ready"}
    if resolved:
        warm = await ensure_ollama_gpu(host=host, port=port, model=resolved)

    return {
        "ok": True,
        "method": "ollama-ready",
        "detail": warm.get("detail") or "Ollama model ready",
        "model": resolved,
        "models": advertised[:12],
    }
