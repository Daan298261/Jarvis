"""HexStrike AI process supervisor and loopback operator gateway (RFC-0048/0106).

HexStrike is a third-party loopback MCP/API (default 127.0.0.1:8888). Jarvis
starts it when the operator selects the cybersecurity suite profile, registers
upstream MCP for owner-operator context, and proxies discovered operator routes
on loopback only (never WAN / command / payload / exploit endpoints).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import data_dir, load_settings, logs_dir, repo_root, save_settings
from ..inference.runtime_profiles import RuntimeProfile

log = logging.getLogger(__name__)

HEXSTRIKE_SUITE_NAME = "hexstrike-suite"
HEXSTRIKE_SHAPE_ID = "hex_aegis"
DEFAULT_PORT = 8888
DEFAULT_HOST = "127.0.0.1"

ALLOWED_GET_EXACT = frozenset(
    {
        "health",
        "api/telemetry",
        "api/cache/stats",
        "api/processes/list",
        "api/processes/dashboard",
    }
)
ALLOWED_GET_PREFIXES = ("api/processes/status/",)
ALLOWED_POST_PREFIXES: tuple[str, ...] = ()

DEFENSIVE_POST_EXACT = frozenset(
    {
        "api/tools/nmap",
        "api/tools/trivy",
        "api/tools/checkov",
        "api/tools/docker-bench-security",
        "api/tools/exiftool",
    }
)
_MANAGED_TERMINATE_RE = re.compile(r"^api/processes/terminate/[1-9][0-9]*$")

_BLOCKED_TOKENS = (
    "command",
    "payload",
    "exploit",
    "python",
    "shell",
    "file-write",
    "file_write",
    "attack",
    "hack-back",
    "hackback",
)


@dataclass
class HexStrikeStatus:
    suite: str = HEXSTRIKE_SUITE_NAME
    shape_id: str = HEXSTRIKE_SHAPE_ID
    installed: bool = False
    running: bool = False
    starting: bool = False
    install_path: str = ""
    python_executable: str = ""
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    health_url: str = ""
    embed_path: str = "/api/hexstrike/console"
    native_ui: bool = False
    pid: int | None = None
    last_error: str = ""
    tools: dict[str, Any] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)
    processes: dict[str, Any] = field(default_factory=dict)
    dashboard: dict[str, Any] | None = None
    health: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "shape_id": self.shape_id,
            "installed": self.installed,
            "running": self.running,
            "starting": self.starting,
            "install_path": self.install_path,
            "python_executable": self.python_executable,
            "host": self.host,
            "port": self.port,
            "health_url": self.health_url,
            "embed_path": self.embed_path,
            "native_ui": self.native_ui,
            "pid": self.pid,
            "last_error": self.last_error,
            "tools": self.tools,
            "telemetry": self.telemetry,
            "processes": self.processes,
            "dashboard": self.dashboard,
            "health": self.health,
        }


def is_suite_runtime(profile: RuntimeProfile) -> bool:
    if (profile.provider or "").strip().lower() == "hexstrike":
        return True
    for tag in profile.capability_tags:
        lowered = str(tag).strip().lower()
        if lowered == "suite" or lowered.startswith("suite:"):
            return True
    return False


def is_hexstrike_suite(profile: RuntimeProfile) -> bool:
    name = (profile.name or "").strip().lower()
    ident = (profile.id or "").strip().lower()
    if name in {HEXSTRIKE_SUITE_NAME, "hexstrike"}:
        return True
    if ident in {HEXSTRIKE_SUITE_NAME, f"recommended-{HEXSTRIKE_SUITE_NAME}"}:
        return True
    if (profile.provider or "").strip().lower() == "hexstrike":
        return True
    tags = {str(tag).strip().lower() for tag in profile.capability_tags}
    return "suite:hexstrike" in tags


def normalize_upstream_path(path: str) -> str:
    raw = (path or "").strip().lstrip("/")
    if not raw:
        raise ValueError("upstream path is required")
    if "%" in raw or "\\" in raw or any(part in {".", ".."} for part in raw.split("/")):
        raise ValueError("invalid upstream path")
    return raw


def _path_blocked(cleaned: str) -> bool:
    lowered = cleaned.lower()
    return any(token in lowered for token in _BLOCKED_TOKENS)


def operator_post_allowed(path: str) -> bool:
    """Loopback operator POST paths Jarvis may invoke after catalog discovery."""
    try:
        cleaned = normalize_upstream_path(path)
    except ValueError:
        return False
    if _path_blocked(cleaned):
        return False
    if cleaned in DEFENSIVE_POST_EXACT:
        return True
    if _MANAGED_TERMINATE_RE.fullmatch(cleaned):
        return True
    if cleaned.startswith("api/tools/"):
        suffix = cleaned.split("/", 2)[-1]
        return bool(suffix) and suffix not in {".", ".."}
    return False


def gateway_allows(method: str, path: str) -> bool:
    """Deny-by-default allowlist for HexStrike upstream HTTP proxy."""
    try:
        cleaned = normalize_upstream_path(path)
    except ValueError:
        return False
    if _path_blocked(cleaned):
        return False
    verb = (method or "GET").strip().upper()
    if verb == "GET":
        if cleaned in ALLOWED_GET_EXACT:
            return True
        if any(cleaned.startswith(prefix) for prefix in ALLOWED_GET_PREFIXES):
            return True
        return cleaned.startswith("api/tools/")
    if verb == "POST":
        return operator_post_allowed(cleaned)
    return False


def _audit_path() -> Path:
    path = data_dir() / "hexstrike-audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def audit_hexstrike(action: str, **fields: Any) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        **fields,
    }
    try:
        with _audit_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
    except OSError:
        log.debug("HexStrike audit write failed", exc_info=True)


def _loopback_host(host: str) -> str:
    cleaned = (host or DEFAULT_HOST).strip() or DEFAULT_HOST
    if cleaned not in {"127.0.0.1", "::1", "localhost"}:
        return DEFAULT_HOST
    return "127.0.0.1" if cleaned == "localhost" else cleaned


def candidate_install_roots(explicit: str = "") -> list[Path]:
    roots: list[Path] = []
    env_home = (os.environ.get("JARVIS_HEXSTRIKE_HOME") or "").strip()
    for raw in (explicit, env_home):
        if raw:
            roots.append(Path(raw).expanduser())
    roots.extend(
        [
            repo_root() / "runtime" / "hexstrike-ai",
            repo_root().parent / "hexstrike-ai",
            Path.home() / "hexstrike-ai",
        ]
    )
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def resolve_install(explicit: str = "") -> Path | None:
    for root in candidate_install_roots(explicit):
        server = root / "hexstrike_server.py"
        if server.is_file():
            return root
    return None


def resolve_python(install: Path, explicit: str = "") -> str:
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists():
            return str(path)
    for candidate in (
        install / "hexstrike-env" / "Scripts" / "python.exe",
        install / "hexstrike-env" / "bin" / "python",
        install / ".venv" / "Scripts" / "python.exe",
        install / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


class HexStrikeManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._log_handle: Any = None
        self._starting = False
        self.last_error = ""
        self._health: dict[str, Any] = {}

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _settings_view(self) -> tuple[str, str, str, int]:
        settings = load_settings()
        hex_cfg = settings.hexstrike
        host = _loopback_host(hex_cfg.host)
        port = int(hex_cfg.port or DEFAULT_PORT)
        return hex_cfg.install_path, hex_cfg.python_executable, host, port

    def _base_status(self) -> HexStrikeStatus:
        install_path, python_executable, host, port = self._settings_view()
        install = resolve_install(install_path)
        python = resolve_python(install, python_executable) if install else python_executable
        running = self.is_running
        return HexStrikeStatus(
            installed=install is not None,
            running=running,
            starting=self._starting,
            install_path=str(install) if install else install_path,
            python_executable=python,
            host=host,
            port=port,
            health_url=f"http://{host}:{port}/health",
            pid=self._process.pid if running and self._process else None,
            last_error=self.last_error,
        )

    async def status(self, *, enrich: bool = True) -> HexStrikeStatus:
        snapshot = self._base_status()
        if enrich and snapshot.running:
            await self._enrich(snapshot)
        return snapshot

    async def configure(self, *, install_path: str | None = None, python_executable: str | None = None, port: int | None = None) -> HexStrikeStatus:
        settings = load_settings()
        if install_path is not None:
            settings.hexstrike.install_path = install_path.strip()
        if python_executable is not None:
            settings.hexstrike.python_executable = python_executable.strip()
        if port is not None:
            settings.hexstrike.port = int(port)
        save_settings(settings)
        audit_hexstrike("configure", install_path=settings.hexstrike.install_path, port=settings.hexstrike.port)
        return await self.status(enrich=False)

    async def ensure_started(self) -> HexStrikeStatus:
        async with self._lock:
            current = self._base_status()
            if current.running:
                await self._enrich(current)
                return current
            from ..policy.cyber_ato import license_blocks

            blocked = license_blocks("hexstrike")
            if blocked:
                self.last_error = blocked
                current.last_error = self.last_error
                audit_hexstrike("start_skipped", reason="license_locked")
                return current
            if not current.installed:
                self.last_error = (
                    "HexStrike AI is not installed. Clone https://github.com/0x4m4/hexstrike-ai "
                    "into runtime/hexstrike-ai or set the install path in the suite HUD."
                )
                current.last_error = self.last_error
                audit_hexstrike("start_skipped", reason="not_installed")
                return current
            from .hexstrike_install import HEXSTRIKE_INSTALLER

            if not HEXSTRIKE_INSTALLER.installation_ready(Path(current.install_path)):
                self.last_error = "HexStrike checkout is not the reviewed clean pinned commit. Run Install/Repair."
                current.last_error = self.last_error
                audit_hexstrike("start_skipped", reason="unreviewed_source")
                return current
            self._starting = True
            current.starting = True
            try:
                started = await self._spawn(current)
                self.last_error = "" if started else (self.last_error or "HexStrike did not become healthy")
            except Exception as exc:
                self.last_error = str(exc)[:400]
                started = False
            finally:
                self._starting = False
            snapshot = self._base_status()
            snapshot.last_error = self.last_error
            if started:
                await self._enrich(snapshot)
                try:
                    from .hexstrike_mcp import register_hexstrike_mcp
                    from .hexstrike_operator import refresh_discovered_catalog, sync_operator_surface

                    install = Path(snapshot.install_path)
                    surface = await sync_operator_surface(register_mcp=True)
                    if not surface.get("operator_ready"):
                        hint = surface.get("mcp", {}).get("error") or surface.get("reason") or "operator surface not ready"
                        self.last_error = f"HexStrike server is up but operator surface failed: {hint}"[:400]
                        snapshot.last_error = self.last_error
                        audit_hexstrike("operator_surface_failed", detail=surface)
                    else:
                        await refresh_discovered_catalog(force=True)
                except Exception as exc:
                    self.last_error = f"HexStrike operator surface failed: {exc}"[:400]
                    snapshot.last_error = self.last_error
                    log.exception("HexStrike MCP/catalog refresh after start failed")
                audit_hexstrike("started", pid=snapshot.pid, port=snapshot.port)
            else:
                audit_hexstrike("start_failed", error=self.last_error)
            return snapshot

    async def stop(self) -> HexStrikeStatus:
        async with self._lock:
            await self._stop_unlocked()
            self.last_error = ""
            try:
                from .hexstrike_mcp import unregister_hexstrike_mcp

                await unregister_hexstrike_mcp()
            except Exception:
                log.debug("HexStrike MCP unregister failed", exc_info=True)
            audit_hexstrike("stopped")
            return self._base_status()

    async def _stop_unlocked(self) -> None:
        process = self._process
        self._process = None
        self._health = {}
        if process and process.returncode is None:
            try:
                if os.name == "nt":
                    taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
                    killer = await asyncio.create_subprocess_exec(
                        str(taskkill), "/PID", str(process.pid), "/T", "/F",
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
                log.debug("HexStrike stop failed", exc_info=True)
        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None

    async def _spawn(self, current: HexStrikeStatus) -> bool:
        await self._stop_unlocked()
        install = Path(current.install_path)
        server = install / "hexstrike_server.py"
        logs_dir().mkdir(parents=True, exist_ok=True)
        log_file = logs_dir() / "hexstrike-server.log"
        self._log_handle = open(log_file, "ab", buffering=0)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["HEXSTRIKE_HOST"] = "127.0.0.1"
        env["HEXSTRIKE_PORT"] = str(current.port)
        env["JARVIS_HEXSTRIKE_STATE_DIR"] = str(install / "jarvis-state")
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        compat = Path(__file__).with_name("hexstrike_compat.py")
        args = [
            current.python_executable or sys.executable,
            str(compat),
            "--server",
            str(server),
            "--port",
            str(current.port),
        ]
        kwargs: dict[str, Any] = {
            "cwd": str(install),
            "stdout": self._log_handle,
            "stderr": self._log_handle,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        self._process = await asyncio.create_subprocess_exec(*args, **kwargs)
        ready = await self._wait_for_loopback_health(current.health_url, timeout=180)
        if not ready:
            self.last_error = "HexStrike process started but /health did not respond on loopback."
            await self._stop_unlocked()
            return False
        return True

    async def _wait_for_loopback_health(self, url: str, *, timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            while asyncio.get_running_loop().time() < deadline:
                if self._process is not None and self._process.returncode is not None:
                    return False
                try:
                    response = await client.get(url)
                    if response.status_code < 500:
                        try:
                            payload = response.json()
                            self._health = payload if isinstance(payload, dict) else {}
                        except ValueError:
                            self._health = {}
                        return True
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
        return False

    async def _enrich(self, snapshot: HexStrikeStatus) -> None:
        base = f"http://{snapshot.host}:{snapshot.port}"
        health = self._health
        if isinstance(health, dict):
            snapshot.health = health
            tools = (
                health.get("tools_status")
                or health.get("tools")
                or health.get("available_tools")
                or health.get("tool_status")
                or health.get("tools_status")
            )
            if isinstance(tools, dict):
                snapshot.tools = tools
            elif isinstance(tools, list):
                snapshot.tools = {"available": tools}
        telemetry = await self._get_json(f"{base}/api/telemetry")
        if isinstance(telemetry, dict):
            snapshot.telemetry = telemetry
        processes = await self._get_json(f"{base}/api/processes/list")
        if isinstance(processes, dict):
            snapshot.processes = processes
        elif isinstance(processes, list):
            snapshot.processes = {"items": processes}
        dashboard = await self._get_json(f"{base}/api/processes/dashboard")
        if isinstance(dashboard, dict):
            snapshot.dashboard = dashboard
            snapshot.native_ui = False
        elif dashboard is not None:
            snapshot.dashboard = {"raw": True}
            snapshot.native_ui = True

    async def proxy(self, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes, str]:
        cleaned = normalize_upstream_path(path)
        if not gateway_allows(method, cleaned):
            audit_hexstrike("proxy_denied", method=method, path=cleaned)
            raise PermissionError(f"HexStrike gateway does not allow {method} /{cleaned}")
        snapshot = self._base_status()
        if not snapshot.running:
            raise RuntimeError("HexStrike is not running")
        url = f"http://{snapshot.host}:{snapshot.port}/{cleaned}"
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.request(method.upper(), url, content=body or None)
        content_type = response.headers.get("content-type", "application/json")
        audit_hexstrike("proxy", method=method, path=cleaned, status=response.status_code)
        return response.status_code, response.content, content_type

    async def post_operator(self, path: str, payload: dict[str, Any]) -> Any:
        """Invoke one discovered loopback operator endpoint."""
        cleaned = normalize_upstream_path(path)
        if not operator_post_allowed(cleaned):
            audit_hexstrike("operator_proxy_denied", path=cleaned)
            raise PermissionError(f"HexStrike operator gateway does not allow POST /{cleaned}")
        snapshot = self._base_status()
        if not snapshot.running:
            raise RuntimeError("HexStrike is not running")
        url = f"http://{snapshot.host}:{snapshot.port}/{cleaned}"
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            response = await client.post(url, json=payload)
        audit_hexstrike("operator_proxy", path=cleaned, status=response.status_code)
        if response.status_code >= 400:
            raise RuntimeError(f"HexStrike returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            return {"text": response.text[:12000]}

    async def post_defensive(self, path: str, payload: dict[str, Any]) -> Any:
        """Backward-compatible alias for RFC-0086 defensive routes."""
        return await self.post_operator(path, payload)

    async def _get_json(self, url: str) -> Any | None:
        parsed = urlparse(url)
        if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            return None
        try:
            async with httpx.AsyncClient(timeout=4, trust_env=False) as client:
                response = await client.get(url)
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        ctype = (response.headers.get("content-type") or "").lower()
        if "json" in ctype:
            try:
                return response.json()
            except ValueError:
                return None
        if "html" in ctype:
            return {"html": True}
        try:
            return response.json()
        except ValueError:
            return None


HEXSTRIKE = HexStrikeManager()
