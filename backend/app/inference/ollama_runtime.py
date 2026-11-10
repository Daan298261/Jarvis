"""Ensure loopback Ollama is up and the requested model is present (installer + Play)."""

from __future__ import annotations

import asyncio
import httpx
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from .backends import probe_remote_server
from .gpu_prefer import ensure_ollama_gpu
from .idle_unload import UNLOADED_DETAIL, warm_blocked
from .keep_alive import ollama_request
from .loaded_models import LOADED, OLLAMA
from ..persona.persona_brain import UMI_OLLAMA_MODEL

_log = logging.getLogger(__name__)

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PULL_TIMEOUT_SECONDS = 3600.0
SERVER_WAIT_SECONDS = 45.0
POLL_SECONDS = 1.0


class OllamaAlreadyRunning(ValueError):
    """The existing listener/process must be reused, never replaced."""


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
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
        if local.is_file():
            return str(local)
    return None


TRAY_APP_NAMES = {"ollama app.exe", "ollama app"}
SERVER_LOG_TAIL_BYTES = 64 * 1024
PORT_CONFLICT_MARKERS = ("only one usage of each socket address", "address already in use")


def ollama_tray_app() -> str | None:
    """The Windows Ollama tray app owns its server; prefer it to a bare `ollama serve`."""
    if sys.platform != "win32":
        return None
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama app.exe"]
    cli = ollama_cli()
    if cli:
        candidates.insert(0, Path(cli).with_name("ollama app.exe"))
    return next((str(path) for path in candidates if path.is_file()), None)


def ollama_tray_running() -> list[int]:
    import psutil
    pids = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if str(process.info.get("name") or "").lower() in TRAY_APP_NAMES:
                pids.append(int(process.info["pid"]))
        except (OSError, psutil.Error, TypeError, ValueError):
            continue
    return pids


def ollama_autostart() -> list[str]:
    """Read-only: where the owner registered the tray app to start at login (never modified)."""
    if sys.platform != "win32":
        return []
    found = []
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"
    try:
        found += [str(p) for p in startup.glob("*.lnk") if p.stem.lower().startswith("ollama")]
    except OSError:
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if "ollama" in f"{name} {value}".lower():
                    found.append(f"HKCU Run: {name}")
    except (ImportError, OSError):
        pass
    return found


def ollama_server_log() -> Path | None:
    if sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama/server.log"
    else:
        path = Path.home() / ".ollama/logs/server.log"
    return path if path.is_file() else None


def ollama_port_conflict() -> dict | None:
    """Detect the tray server's bind-retry loop (bounded tail read of its own log)."""
    path = ollama_server_log()
    if not path:
        return None
    try:
        stat = path.stat()
        with path.open("rb") as handle:
            handle.seek(max(0, stat.st_size - SERVER_LOG_TAIL_BYTES))
            tail = handle.read().decode("utf-8", "replace").lower()
    except OSError:
        return None
    hits = sum(tail.count(marker) for marker in PORT_CONFLICT_MARKERS)
    if hits < 3 or time.time() - stat.st_mtime > 300:
        return None
    return {"log": str(path), "log_bytes": stat.st_size, "recent_conflicts": hits}


def _start_server(host: str, port: int, *, env_overrides: dict[str, str] | None = None) -> str:
    """Start Ollama once: adopt any existing/pending server, prefer the tray app, never duplicate."""
    from .running_models import port_in_use, ollama_serves
    if port_in_use(port) or ollama_serves() or ollama_tray_running():
        raise OllamaAlreadyRunning("Ollama port/process is already in use; duplicate server launch refused")
    if not ollama_cli():
        raise FileNotFoundError("ollama CLI is not installed")
    env = os.environ.copy()
    env.update({k: v for k, v in (env_overrides or {}).items()
                if k in {"OLLAMA_KV_CACHE_TYPE", "OLLAMA_FLASH_ATTENTION"}})
    address = f"[{host}]" if ":" in host else host
    env["OLLAMA_HOST"] = f"{address}:{int(port)}"
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    tray = ollama_tray_app()
    # The tray app serves its default loopback port. Launching it (instead of a bare
    # server) means its own login-time autostart finds a running instance, not a busy
    # port it retries forever.
    if tray and is_loopback_host(host) and int(port) == 11434:
        subprocess.Popen([tray], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, cwd=str(Path(tray).parent))
        _log.info("ollama_start method=tray-app")
        return "tray-app"
    subprocess.Popen(
        [ollama_cli(), "serve"], env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
    )
    _log.info("ollama_start method=serve")
    return "serve"


def _model_present(advertised: list[str], model: str) -> bool:
    hint = (model or "").strip()
    if not hint:
        return bool(advertised)
    def canonical(name: str) -> str:
        name = name.strip().lower()
        return name[:-7] if name.endswith(":latest") else name
    return any(canonical(name) == canonical(hint) for name in advertised)


def _run_ollama(args: list[str], *, timeout: float, host: str = "127.0.0.1", port: int = 11434) -> subprocess.CompletedProcess[str]:
    cli = ollama_cli()
    if not cli:
        raise FileNotFoundError("ollama CLI is not installed")
    env = os.environ.copy()
    address = f"[{host}]" if ":" in host else host
    env["OLLAMA_HOST"] = f"{address}:{int(port)}"
    return subprocess.run(
        [cli, *args],
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
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
        try:
            await asyncio.to_thread(_start_server, host, port)
        except OllamaAlreadyRunning:
            # Adopt it: an existing (or still-starting tray) server is waited for, never replaced.
            _log.info("Ollama already has a listener/process; waiting for the existing server")
        except OSError as exc:
            return {"ok": False, "method": "start-failed", "detail": str(exc)}
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
                timeout=PULL_TIMEOUT_SECONDS, host=host, port=port,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "method": "pull-timeout", "detail": f"Timed out pulling {hint}"}
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "ollama pull failed").strip()[:240]
            return {"ok": False, "method": "pull-failed", "detail": detail}
        probe = await probe_remote_server(host, port, timeout=8.0, retry=True)
        advertised = list(probe.get("models") or [])

    resolved = next((name for name in advertised if _model_present([name], hint)), hint)
    if hint and not _model_present(advertised, hint):
        return {
            "ok": False,
            "method": "model-missing",
            "detail": f"Model {hint} is not installed; download it from the Model page",
            "models": advertised[:8],
        }

    warm: dict[str, Any] = {"ok": True, "method": "ready"}
    if resolved and warm_blocked():
        return {"ok": False, "method": "unloaded", "detail": UNLOADED_DETAIL, "models": advertised[:12]}
    if resolved:
        warm = await ensure_ollama_gpu(host=host, port=port, model=resolved, timeout=120.0)
        if warm.get("method") == "skipped":
            try:
                async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
                    response = await ollama_request(client, host, port, "/api/generate", resolved,
                                                    {"prompt": "", "stream": False})
                    response.raise_for_status()
                LOADED.record(OLLAMA, resolved)
                warm = {"ok": True, "detail": "Model loaded"}
            except Exception as exc:
                warm = {"ok": False, "detail": str(exc)[:240]}
        if not warm.get("ok"):
            return {"ok": False, "method": "warm-failed", "detail": warm.get("detail") or "Model failed to load"}

    return {
        "ok": True,
        "method": "ollama-ready",
        "detail": warm.get("detail") or "Ollama model ready",
        "model": resolved,
        "models": advertised[:12],
    }
