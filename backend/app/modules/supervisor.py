"""Generic module-worker process supervisor (RFC-0105).

Jarvis-owned subprocesses on loopback with pid tracking. Only stops processes
Jarvis started. Shape mirrors HexStrike supervisor without coupling to HexStrike.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import logs_dir

log = logging.getLogger(__name__)

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
DEFAULT_LOOPBACK = "127.0.0.1"


@dataclass(frozen=True)
class StartSpec:
    argv: tuple[str, ...]
    cwd: Path
    health_url: str = ""
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class WorkerSnapshot:
    member_id: str
    running: bool = False
    starting: bool = False
    pid: int | None = None
    health_url: str = ""
    last_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "running": self.running,
            "starting": self.starting,
            "pid": self.pid,
            "health_url": self.health_url,
            "last_error": self.last_error,
        }


def is_loopback_url(url: str) -> bool:
    """Empty URL means process-alive check only (no HTTP). Non-empty must be loopback."""
    raw = (url or "").strip()
    if not raw:
        return True
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if (parsed.scheme or "").lower() not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().lower()
    return host in LOOPBACK_HOSTS


def loopback_bind_env(extra: dict[str, str] | None = None, *, port: str = "") -> dict[str, str]:
    """Force child workers onto loopback; never inherit a WAN bind from the parent."""
    env = {
        "HOST": DEFAULT_LOOPBACK,
        "HOSTNAME": DEFAULT_LOOPBACK,
        "BIND": DEFAULT_LOOPBACK,
        "BIND_HOST": DEFAULT_LOOPBACK,
        "SERVER_HOST": DEFAULT_LOOPBACK,
    }
    if port:
        env["PORT"] = str(port)
    if extra:
        for key, value in extra.items():
            # Caller may set PORT / health-related vars, but host bind stays loopback.
            if str(key).upper() in {"HOST", "HOSTNAME", "BIND", "BIND_HOST", "SERVER_HOST"}:
                continue
            env[str(key)] = str(value)
    return env


def normalize_health_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if not is_loopback_url(raw):
        return ""
    parsed = urlparse(raw)
    hostname = (parsed.hostname or "").lower()
    # Prefer IPv4 loopback for localhost; keep ::1 when explicitly used.
    host = "::1" if hostname == "::1" else DEFAULT_LOOPBACK
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    path = parsed.path or "/"
    return f"{parsed.scheme}://{netloc}{path}"


class ModuleWorkerSupervisor:
    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._log_handle: Any = None
        self._starting = False
        self.last_error = ""
        self._health_url = ""

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def managed_pid(self) -> int | None:
        if self.is_running and self._process:
            return self._process.pid
        return None

    def snapshot(self) -> WorkerSnapshot:
        running = self.is_running
        return WorkerSnapshot(
            member_id=self.member_id,
            running=running,
            starting=self._starting,
            pid=self._process.pid if running and self._process else None,
            health_url=self._health_url,
            last_error=self.last_error,
        )

    async def start(self, spec: StartSpec) -> WorkerSnapshot:
        async with self._lock:
            if self.is_running:
                return self.snapshot()
            if not is_loopback_url(spec.health_url):
                self.last_error = "Health URL must be loopback (127.0.0.1 / ::1 / localhost)"
                self._starting = False
                return self.snapshot()
            self._starting = True
            self._health_url = normalize_health_url(spec.health_url)
            try:
                bound = StartSpec(
                    argv=spec.argv,
                    cwd=spec.cwd,
                    health_url=self._health_url,
                    env=loopback_bind_env(spec.env),
                )
                ok = await self._spawn(bound)
                if not ok:
                    self.last_error = self.last_error or "Process did not become healthy"
            except Exception as exc:
                self.last_error = str(exc)[:400]
                ok = False
            finally:
                self._starting = False
            snap = self.snapshot()
            if not ok:
                snap.last_error = self.last_error
            return snap

    async def stop(self) -> WorkerSnapshot:
        async with self._lock:
            await self._stop_unlocked()
            self.last_error = ""
            return self.snapshot()

    async def _spawn(self, spec: StartSpec) -> bool:
        await self._stop_unlocked()
        if not spec.cwd.is_dir():
            self.last_error = "Checkout directory is missing"
            return False
        if not spec.argv:
            self.last_error = "Start command is empty"
            return False
        logs_dir().mkdir(parents=True, exist_ok=True)
        log_file = logs_dir() / f"module-worker-{self.member_id}.log"
        self._log_handle = open(log_file, "ab", buffering=0)
        env = os.environ.copy()
        env.update(spec.env)
        env["PYTHONUNBUFFERED"] = "1"
        kwargs: dict[str, Any] = {
            "cwd": str(spec.cwd),
            "stdout": self._log_handle,
            "stderr": self._log_handle,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        self._process = await asyncio.create_subprocess_exec(*spec.argv, **kwargs)
        if spec.health_url:
            ready = await self._wait_for_health(spec.health_url, timeout=120)
            if not ready:
                self.last_error = "Process started but health URL did not respond on loopback"
                await self._stop_unlocked()
                return False
        else:
            await asyncio.sleep(0.5)
            if self._process.returncode is not None:
                self.last_error = f"Process exited with code {self._process.returncode}"
                await self._stop_unlocked()
                return False
        return True

    async def _wait_for_health(self, url: str, *, timeout: float) -> bool:
        if not is_loopback_url(url):
            return False
        deadline = asyncio.get_running_loop().time() + timeout
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            while asyncio.get_running_loop().time() < deadline:
                if self._process is not None and self._process.returncode is not None:
                    return False
                try:
                    response = await client.get(url)
                    if response.status_code < 500:
                        return True
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.25)
        return False

    async def _stop_unlocked(self) -> None:
        process = self._process
        self._process = None
        if process and process.returncode is None:
            try:
                if os.name == "nt":
                    taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
                    killer = await asyncio.create_subprocess_exec(
                        str(taskkill),
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await asyncio.wait_for(killer.wait(), timeout=10)
                    await asyncio.wait_for(process.wait(), timeout=10)
                else:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=8)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
            except Exception:
                log.debug("module worker stop failed", exc_info=True)
        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None


_SUPERVISORS: dict[str, ModuleWorkerSupervisor] = {}


def get_supervisor(member_id: str) -> ModuleWorkerSupervisor:
    key = (member_id or "").strip()
    if key not in _SUPERVISORS:
        _SUPERVISORS[key] = ModuleWorkerSupervisor(key)
    return _SUPERVISORS[key]


def reset_supervisors() -> None:
    """Test helper."""
    _SUPERVISORS.clear()


def read_jarvis_module_manifest(root: Path) -> dict[str, Any] | None:
    for name in ("jarvis-module.json", ".jarvis-module.json"):
        path = root / name
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            return payload if isinstance(payload, dict) else None
    return None


def _port_from_manifest(manifest: dict[str, Any] | None, default: str) -> str:
    if not manifest:
        return default
    if manifest.get("port"):
        return str(manifest.get("port"))
    health = str(manifest.get("health_url") or manifest.get("health") or "")
    if health and is_loopback_url(health):
        parsed = urlparse(health)
        if parsed.port:
            return str(parsed.port)
    return default


def resolve_start_spec(root: Path, role: str) -> StartSpec | None:
    """Resolve a loopback worker start command from Jarvis metadata or safe heuristics.

    Fail closed: no inventing WAN binds or non-loopback health URLs. Missing start
    metadata returns None so callers report an honest error instead of a fake run.
    """
    if not root.is_dir():
        return None
    manifest = read_jarvis_module_manifest(root)
    if manifest:
        raw_cmd = manifest.get("start") or manifest.get("command")
        if isinstance(raw_cmd, list) and raw_cmd:
            argv = tuple(str(part) for part in raw_cmd)
        elif isinstance(raw_cmd, str) and raw_cmd.strip():
            argv = tuple(raw_cmd.strip().split())
        else:
            argv = ()
        if argv:
            cwd = (root / str(manifest.get("cwd") or ".")).resolve()
            if not cwd.is_dir():
                return None
            health_raw = str(manifest.get("health_url") or manifest.get("health") or "")
            if health_raw and not is_loopback_url(health_raw):
                return None
            health = normalize_health_url(health_raw)
            env_raw = manifest.get("env") if isinstance(manifest.get("env"), dict) else {}
            port = _port_from_manifest(manifest, "")
            env = loopback_bind_env({str(k): str(v) for k, v in env_raw.items()}, port=port)
            return StartSpec(argv=argv, cwd=cwd, health_url=health, env=env)

    role_key = (role or "").strip().lower().replace("-", "_")
    if role_key == "graph_ui":
        package = root / "package.json"
        if package.is_file():
            try:
                data = json.loads(package.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            scripts = data.get("scripts") if isinstance(data, dict) else {}
            if isinstance(scripts, dict):
                for script_name in ("dev", "start", "preview"):
                    if script_name in scripts:
                        port = _port_from_manifest(manifest, "5174")
                        return StartSpec(
                            argv=("npm", "run", script_name),
                            cwd=root,
                            health_url=f"http://{DEFAULT_LOOPBACK}:{port}/",
                            env=loopback_bind_env(port=port),
                        )
        return None

    if role_key == "harness":
        for script in ("start.sh", "run.sh", "dev.sh"):
            path = root / script
            if path.is_file():
                # Process-alive check only — do not invent a health port.
                return StartSpec(
                    argv=(str(path),),
                    cwd=root,
                    health_url="",
                    env=loopback_bind_env(),
                )
        for entry in ("main.py", "server.py", "app.py"):
            path = root / entry
            if path.is_file():
                return StartSpec(
                    argv=(sys.executable, str(path)),
                    cwd=root,
                    health_url="",
                    env=loopback_bind_env(),
                )
    return None


def discover_graph_ui_url(root: Path) -> str | None:
    """Return a loopback UI URL when the clone advertises one; else None (open-folder path)."""
    if not root.is_dir():
        return None
    manifest = read_jarvis_module_manifest(root)
    if manifest:
        for key in ("ui_url", "health_url", "health"):
            raw = str(manifest.get(key) or "").strip()
            if raw and is_loopback_url(raw):
                return normalize_health_url(raw)
        if manifest.get("port"):
            return f"http://{DEFAULT_LOOPBACK}:{manifest['port']}/"
    package = root / "package.json"
    if package.is_file():
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        scripts = data.get("scripts") if isinstance(data, dict) else {}
        if isinstance(scripts, dict) and any(name in scripts for name in ("dev", "start", "preview")):
            port = _port_from_manifest(manifest, "5174")
            return f"http://{DEFAULT_LOOPBACK}:{port}/"
    return None
