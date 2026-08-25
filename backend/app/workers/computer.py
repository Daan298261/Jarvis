"""Computer-use backends: native Windows UI Automation, Microsoft UFO, Cua.

Native pywinauto stays the deterministic default. UFO and Cua are optional
workers Jarvis can call when they are installed; missing packages degrade to
a clear error that points at the native `desktop` tool.
"""

from __future__ import annotations

import asyncio
import importlib.util
import platform
import shutil
import sys
from typing import Any

from ..tools.base import ToolResult

UFO_TIMEOUT_SECONDS = 180
CUA_TIMEOUT_SECONDS = 180


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


class ComputerUseBackend:
    id: str
    name: str
    license_id: str = ""

    def available(self) -> bool:
        return False

    def probe(self) -> dict[str, Any]:
        raise NotImplementedError

    def build_command(self, goal: str, app: str | None = None, kind: str | None = None) -> list[str]:
        raise NotImplementedError

    async def run(self, goal: str, app: str | None = None, timeout_seconds: int | None = None) -> ToolResult:
        raise NotImplementedError


class NativeWindowsBackend(ComputerUseBackend):
    """pywinauto / UI Automation. Coordinate clicking remains last resort."""

    id = "windows_ui"
    name = "Windows UI Automation"
    license_id = "BSD"

    def available(self) -> bool:
        return platform.system() == "Windows" and _module_available("pywinauto")

    def probe(self) -> dict[str, Any]:
        if self.available():
            return {
                "id": self.id,
                "name": self.name,
                "kind": "native",
                "available": True,
                "status": "ready",
                "detail": "pywinauto / UI Automation. Coordinate clicking is last resort.",
            }
        return {
            "id": self.id,
            "name": self.name,
            "kind": "native",
            "available": False,
            "status": "unavailable",
            "detail": "pywinauto / UI Automation. Coordinate clicking is last resort.",
        }

    def build_command(self, goal: str, app: str | None = None, kind: str | None = None) -> list[str]:
        return []

    async def run(self, goal: str, app: str | None = None, timeout_seconds: int | None = None) -> ToolResult:
        if not str(goal or "").strip():
            return ToolResult(False, "", error="goal is required")
        if not self.available():
            return ToolResult(
                False,
                "",
                error=(
                    "Native Windows UI Automation is not available on this machine. "
                    "Use the desktop tool on Windows with pywinauto installed."
                ),
            )
        hint = f" for app {app}" if app else ""
        return ToolResult(
            True,
            (
                f"Use the native desktop tool{hint} for: {goal.strip()}. "
                "Prefer named UI Automation controls over coordinates."
            ),
            data={"backend": self.id, "goal": goal, "app": app},
        )


class UFOBackend(ComputerUseBackend):
    """Microsoft UFO / UFO² HostAgent–AppAgent worker."""

    id = "ufo"
    name = "Microsoft UFO"
    license_id = "MIT"
    modules = ("ufo", "ufo2", "microsoft_ufo")
    clis = ("ufo", "ufo2")

    def detect_kind(self) -> str | None:
        for name in self.modules:
            if _module_available(name):
                return f"python-module:{name}"
        for cli in self.clis:
            if shutil.which(cli):
                return f"cli:{cli}"
        return None

    def available(self) -> bool:
        return self.detect_kind() is not None

    def probe(self) -> dict[str, Any]:
        kind = self.detect_kind()
        if kind:
            return {
                "id": self.id,
                "name": self.name,
                "kind": "optional",
                "available": True,
                "status": "ready",
                "detail": (
                    f"UFO {kind} is available as a Windows HostAgent/AppAgent worker. "
                    "Native UI Automation remains the deterministic default."
                ),
            }
        return {
            "id": self.id,
            "name": self.name,
            "kind": "optional",
            "available": False,
            "status": "missing",
            "detail": (
                "Adapter is integrated. Install Microsoft UFO locally to enable HostAgent/AppAgent "
                "Windows control. Until then Jarvis uses the native desktop tool."
            ),
        }

    def build_command(self, goal: str, app: str | None = None, kind: str | None = None) -> list[str]:
        resolved = kind or self.detect_kind() or "python-module:ufo"
        if resolved.startswith("cli:"):
            command = [resolved.split(":", 1)[1], "--task", goal]
        else:
            module = resolved.split(":", 1)[1]
            command = [sys.executable, "-m", module, "--task", goal]
        if app:
            command.extend(["--app", app])
        return command

    async def run(self, goal: str, app: str | None = None, timeout_seconds: int | None = None) -> ToolResult:
        if not str(goal or "").strip():
            return ToolResult(False, "", error="goal is required")
        kind = self.detect_kind()
        if not kind:
            return ToolResult(
                False,
                "",
                error=(
                    "Microsoft UFO is not installed on this machine. "
                    "Use the native desktop tool (UI Automation) instead."
                ),
            )
        command = self.build_command(str(goal).strip(), app, kind)
        timeout = timeout_seconds or UFO_TIMEOUT_SECONDS
        try:
            stdout, stderr, code = await self._invoke(command, timeout)
        except Exception as exc:
            return ToolResult(
                False,
                "",
                error=f"UFO failed: {exc}. Fall back to the native desktop tool.",
            )
        output = (stdout or stderr or "").strip()
        data = {"backend": self.id, "kind": kind, "command": command, "exit_code": code, "app": app}
        if code != 0:
            return ToolResult(
                False,
                output,
                data=data,
                error=f"UFO exited {code}. Continue with the native desktop tool and verify the UI state.",
            )
        reminder = "\n\nJarvis must independently inspect the UI (desktop snapshot or named control) after UFO returns."
        return ToolResult(True, (output or "UFO finished.") + reminder, data=data)

    async def _invoke(self, command: list[str], timeout: int) -> tuple[str, str, int]:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"UFO timed out after {timeout}s")
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        return stdout, stderr, proc.returncode or 0


class CuaBackend(ComputerUseBackend):
    """Cua / trycua computer-use worker. Accessibility first, coordinates last."""

    id = "cua"
    name = "Cua"
    license_id = "MIT"
    modules = ("cua", "computer", "agent_s", "agent_s2")
    clis = ("cua",)

    def detect_kind(self) -> str | None:
        for name in self.modules:
            if _module_available(name):
                return f"python-module:{name}"
        for cli in self.clis:
            if shutil.which(cli):
                return f"cli:{cli}"
        return None

    def available(self) -> bool:
        return self.detect_kind() is not None

    def probe(self) -> dict[str, Any]:
        kind = self.detect_kind()
        if kind:
            return {
                "id": self.id,
                "name": self.name,
                "kind": "optional",
                "available": True,
                "status": "ready",
                "detail": (
                    f"Cua {kind} is available as a computer-use worker. "
                    "Prefer accessibility trees; native UI Automation stays the default."
                ),
            }
        return {
            "id": self.id,
            "name": self.name,
            "kind": "optional",
            "available": False,
            "status": "missing",
            "detail": (
                "Adapter is integrated. Install Cua (trycua) locally for computer-use. "
                "Until then Jarvis uses the native desktop tool."
            ),
        }

    def build_command(self, goal: str, app: str | None = None, kind: str | None = None) -> list[str]:
        resolved = kind or self.detect_kind() or "python-module:cua"
        if resolved.startswith("cli:"):
            command = [resolved.split(":", 1)[1], "run", "--task", goal]
        else:
            module = resolved.split(":", 1)[1]
            command = [sys.executable, "-m", module, "--task", goal]
        if app:
            command.extend(["--app", app])
        return command

    async def run(self, goal: str, app: str | None = None, timeout_seconds: int | None = None) -> ToolResult:
        if not str(goal or "").strip():
            return ToolResult(False, "", error="goal is required")
        kind = self.detect_kind()
        if not kind:
            return ToolResult(
                False,
                "",
                error=(
                    "Cua is not installed on this machine. "
                    "Use the native desktop tool (UI Automation) instead."
                ),
            )
        command = self.build_command(str(goal).strip(), app, kind)
        timeout = timeout_seconds or CUA_TIMEOUT_SECONDS
        try:
            stdout, stderr, code = await self._invoke(command, timeout)
        except Exception as exc:
            return ToolResult(
                False,
                "",
                error=f"Cua failed: {exc}. Fall back to the native desktop tool.",
            )
        output = (stdout or stderr or "").strip()
        data = {"backend": self.id, "kind": kind, "command": command, "exit_code": code, "app": app}
        if code != 0:
            return ToolResult(
                False,
                output,
                data=data,
                error=f"Cua exited {code}. Continue with the native desktop tool and verify the UI state.",
            )
        reminder = "\n\nJarvis must independently inspect the UI after Cua returns. A worker report of success is not verification."
        return ToolResult(True, (output or "Cua finished.") + reminder, data=data)

    async def _invoke(self, command: list[str], timeout: int) -> tuple[str, str, int]:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"Cua timed out after {timeout}s")
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        return stdout, stderr, proc.returncode or 0


def preferred_computer_backend() -> ComputerUseBackend:
    """Native UI Automation first, then UFO, then Cua. Never crash if none are ready."""
    native = NativeWindowsBackend()
    if native.available():
        return native
    ufo = UFOBackend()
    if ufo.available():
        return ufo
    cua = CuaBackend()
    if cua.available():
        return cua
    return native
