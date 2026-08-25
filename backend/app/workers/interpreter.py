"""Optional Open Interpreter adapter. Jarvis stays the orchestrator and still verifies."""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any

from ..config import AppSettings, load_settings
from ..tools.base import ToolResult
from .local_llm import merge_local_env

INTERPRETER_TIMEOUT_SECONDS = 900


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


class OpenInterpreterBackend:
    """Optional code/shell worker. Native filesystem/python/git remain the fallback."""

    id = "open-interpreter"
    name = "Open Interpreter"
    license_id = "MIT"

    def detect_kind(self) -> str | None:
        if _module_available("interpreter"):
            return "python-module"
        if shutil.which("interpreter"):
            return "cli"
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
                    f"Open Interpreter {kind} is available as a code/shell worker. "
                    "Keep simple file and shell work on native tools. Jarvis still verifies."
                ),
            }
        return {
            "id": self.id,
            "name": self.name,
            "kind": "optional",
            "available": False,
            "status": "missing",
            "detail": (
                "Adapter is integrated. Install Open Interpreter locally to delegate larger "
                "code/shell jobs. Until then Jarvis uses filesystem, python, git, and terminal, "
                "and still verifies."
            ),
        }

    def build_command(self, goal: str, path: Path, kind: str | None = None) -> list[str]:
        resolved = kind or self.detect_kind()
        if resolved == "cli":
            return ["interpreter", "--os", "-y", "-c", goal]
        return [sys.executable, "-m", "interpreter", "--os", "-y", "-c", goal]

    async def run(
        self,
        goal: str,
        path: str | Path,
        settings: AppSettings | None = None,
        timeout_seconds: int | None = None,
    ) -> ToolResult:
        if not goal or not str(goal).strip():
            return ToolResult(False, "", error="goal is required")
        kind = self.detect_kind()
        if not kind:
            return ToolResult(
                False,
                "",
                error=(
                    "Open Interpreter is not installed on this machine. "
                    "Use filesystem, python, git, and terminal instead. Jarvis must still verify."
                ),
            )
        current = settings or load_settings()
        workdir = Path(path)
        command = self.build_command(str(goal).strip(), workdir, kind)
        timeout = timeout_seconds or min(
            current.default_timeout_seconds or INTERPRETER_TIMEOUT_SECONDS,
            INTERPRETER_TIMEOUT_SECONDS,
        )
        try:
            stdout, stderr, code = await self._invoke(command, workdir, current, timeout)
        except Exception as exc:
            return ToolResult(
                False,
                "",
                error=f"Open Interpreter failed: {exc}. Continue with native filesystem/python/git tools and verify.",
            )
        output = (stdout or stderr or "").strip()
        data = {"backend": self.id, "kind": kind, "command": command, "exit_code": code, "path": str(workdir)}
        if code != 0:
            return ToolResult(
                False,
                output,
                data=data,
                error=(
                    f"Open Interpreter exited {code}. Jarvis must inspect the working tree and tests itself; "
                    "do not trust a worker report of success."
                ),
            )
        reminder = (
            "\n\nJarvis must independently inspect the diff and run tests. "
            "An Open Interpreter report of 'fixed' is not verification."
        )
        return ToolResult(True, (output or "Open Interpreter finished.") + reminder, data=data)

    async def _invoke(
        self,
        command: list[str],
        workdir: Path,
        settings: AppSettings,
        timeout: int,
    ) -> tuple[str, str, int]:
        env = merge_local_env(settings)
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workdir) if workdir.exists() else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"Open Interpreter timed out after {timeout}s")
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        return stdout, stderr, proc.returncode or 0
