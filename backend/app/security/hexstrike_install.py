"""Managed, pinned Windows installer for the defensive HexStrike runtime."""
from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import load_settings, repo_root, save_settings
from .hexstrike import audit_hexstrike

APPROVED_HEXSTRIKE_REMOTE = "https://github.com/0x4m4/hexstrike-ai.git"
APPROVED_HEXSTRIKE_COMMIT = "d689933ff579d839c676c82b231f8e98326c5f04"


@dataclass
class HexStrikeInstallStatus:
    state: str = "idle"
    stage: str = "idle"
    progress: int = 0
    install_path: str = ""
    approved_remote: str = APPROVED_HEXSTRIKE_REMOTE
    approved_commit: str = APPROVED_HEXSTRIKE_COMMIT
    installed_commit: str = ""
    error: str = ""
    log_tail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class HexStrikeInstaller:
    STAGE_PROGRESS = {
        "validate": 5,
        "clone": 15,
        "checkout": 30,
        "venv": 45,
        "dependencies": 65,
        "health": 85,
        "activate": 95,
        "ready": 100,
    }

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._status = HexStrikeInstallStatus()

    def default_path(self) -> Path:
        configured = (os.environ.get("JARVIS_HEXSTRIKE_HOME") or "").strip()
        return Path(configured).expanduser() if configured else repo_root() / "runtime" / "hexstrike-ai"

    def _installed_commit(self, path: Path) -> str:
        if not (path / ".git").exists():
            return ""
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    def _installed_remote(self, path: Path) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    def _source_clean(self, path: Path) -> bool:
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "diff", "--quiet", "HEAD", "--"],
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def _installation_ready(self, path: Path) -> bool:
        remote = self._installed_remote(path)
        return (
            self._installed_commit(path) == APPROVED_HEXSTRIKE_COMMIT
            and remote in {APPROVED_HEXSTRIKE_REMOTE, "git@github.com:0x4m4/hexstrike-ai.git"}
            and self._source_clean(path)
            and (path / "hexstrike_server.py").is_file()
            and (path / "hexstrike-env" / "Scripts" / "python.exe").is_file()
        )

    def installation_ready(self, path: Path) -> bool:
        """Return true only for the reviewed, clean pinned checkout."""
        return self._installation_ready(path)

    def status(self) -> HexStrikeInstallStatus:
        path = Path(self._status.install_path) if self._status.install_path else self.default_path()
        self._status.install_path = str(path.resolve())
        self._status.installed_commit = self._installed_commit(path)
        if self._status.state == "idle" and self._installation_ready(path):
            self._status.state = "ready"
            self._status.stage = "ready"
            self._status.progress = 100
        return HexStrikeInstallStatus(**self._status.as_dict())

    def start(self, install_path: str | None = None) -> HexStrikeInstallStatus:
        if self._task and not self._task.done():
            return self.status()
        path = Path(install_path).expanduser() if install_path else self.default_path()
        if not path.is_absolute():
            path = repo_root() / path
        self._status = HexStrikeInstallStatus(
            state="running",
            stage="queued",
            progress=0,
            install_path=str(path.resolve()),
        )
        audit_hexstrike("install_started", install_path=self._status.install_path, commit=APPROVED_HEXSTRIKE_COMMIT)
        self._task = asyncio.create_task(self._run(path.resolve()))
        return self.status()

    async def cancel(self) -> HexStrikeInstallStatus:
        process = self._process
        if process and process.returncode is None:
            if os.name == "nt":
                taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
                killer = await asyncio.create_subprocess_exec(
                    str(taskkill), "/PID", str(process.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.wait(), timeout=10)
            else:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=8)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        if self._task and not self._task.done():
            self._task.cancel()
        self._process = None
        self._status.state = "cancelled"
        self._status.stage = "cancelled"
        self._status.error = "Installation cancelled; any staging directory was preserved for inspection."
        audit_hexstrike("install_cancelled", install_path=self._status.install_path)
        return self.status()

    async def _run(self, path: Path) -> None:
        if os.name != "nt":
            self._status.state = "failed"
            self._status.stage = "failed"
            self._status.error = "The managed HexStrike bootstrapper is Windows-only."
            return
        script = repo_root() / "scripts" / "bootstrap-hexstrike.ps1"
        settings = load_settings()
        port = int(settings.hexstrike.port or 8888)
        args = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-InstallPath",
            str(path),
            "-Commit",
            APPROVED_HEXSTRIKE_COMMIT,
            "-Port",
            str(port),
        ]
        output: list[str] = []
        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(repo_root()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            assert self._process.stdout is not None
            async for raw in self._process.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                output.append(line)
                output = output[-40:]
                self._status.log_tail = "\n".join(output)[-5000:]
                if line.startswith("STAGE:"):
                    stage = line.split(":", 1)[1].strip().lower()
                    self._status.stage = stage
                    self._status.progress = self.STAGE_PROGRESS.get(stage, self._status.progress)
            code = await self._process.wait()
            if code != 0:
                raise RuntimeError(output[-1] if output else f"bootstrapper exited with code {code}")
            installed_commit = self._installed_commit(path)
            if not self._installation_ready(path):
                raise RuntimeError("installed HexStrike source, commit, server, or virtual environment failed validation")
            settings = load_settings()
            settings.hexstrike.install_path = str(path)
            settings.hexstrike.python_executable = str(path / "hexstrike-env" / "Scripts" / "python.exe")
            settings.hexstrike.host = "127.0.0.1"
            save_settings(settings)
            self._status.state = "ready"
            self._status.stage = "ready"
            self._status.progress = 100
            self._status.installed_commit = installed_commit
            self._status.error = ""
            audit_hexstrike("install_ready", install_path=str(path), commit=installed_commit)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._status.state = "failed"
            self._status.stage = "failed"
            self._status.error = str(exc)[:500]
            audit_hexstrike("install_failed", install_path=str(path), error=self._status.error)
        finally:
            self._process = None


HEXSTRIKE_INSTALLER = HexStrikeInstaller()
