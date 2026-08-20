from __future__ import annotations

import asyncio
import os
import shutil
import time
from typing import Any

from .base import RiskLevel, Tool, ToolResult
from .safety import classify_command


class TerminalTool(Tool):
    name = "terminal"
    description = (
        "Run a local command. shell can be powershell, cmd, python, git, or bash/wsl. "
        "Captures stdout, stderr, exit code and duration. Use working_directory when possible. "
        "For long jobs set timeout_seconds. Do not use this to format disks or destroy backups."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "shell": {"type": "string", "enum": ["powershell", "cmd", "python", "git", "bash", "wsl"], "default": "powershell"},
            "working_directory": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 120},
        },
        "required": ["command"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command") or ""
        shell = (kwargs.get("shell") or "powershell").lower()
        cwd = kwargs.get("working_directory") or os.getcwd()
        timeout = int(kwargs.get("timeout_seconds") or 120)
        risk = classify_command(command)
        if risk == RiskLevel.IRREVERSIBLE:
            return ToolResult(False, "", error="Blocked irreversible command. Ask the user explicitly if this is required.")
        if shell == "powershell":
            args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
        elif shell == "cmd":
            args = ["cmd", "/c", command]
        elif shell == "python":
            args = ["python", "-c", command] if "\n" in command or command.startswith("print") else ["python", *command.split()]
            if command.endswith(".py") or " " in command and not command.startswith("print"):
                args = ["python"] + command.split()
        elif shell == "git":
            args = ["git"] + command.split() if not command.startswith("git ") else command if False else (command.split() if command.startswith("git") else ["git", *command.split()])
            if not command.startswith("git"):
                args = ["git", *command.split()]
            else:
                args = command.split()
        elif shell in {"bash", "wsl"}:
            if shutil.which("wsl"):
                args = ["wsl", "-e", "bash", "-lc", command]
            elif shutil.which("bash"):
                args = ["bash", "-lc", command]
            else:
                return ToolResult(False, "", error="WSL/bash is not available on this machine")
        else:
            args = ["powershell", "-NoProfile", "-Command", command]
        started = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(False, "", error=f"Command timed out after {timeout}s")
            duration = round((time.time() - started) * 1000, 1)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            code = proc.returncode or 0
            text = (
                f"exit_code={code}\nduration_ms={duration}\n"
                f"--- stdout ---\n{out}\n--- stderr ---\n{err}"
            )
            return ToolResult(code == 0, text, data={"exit_code": code, "duration_ms": duration}, error="" if code == 0 else err[-2000:])
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
