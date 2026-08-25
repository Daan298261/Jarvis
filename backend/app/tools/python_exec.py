from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import venv
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult


class PythonTool(Tool):
    name = "python"
    description = (
        "Create or run Python in an isolated way. Actions: run_code, run_file, create_venv, "
        "install. Prefer create_venv for project-specific packages. working_directory should "
        "be the project root when installing dependencies."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["run_code", "run_file", "create_venv", "install"]},
            "code": {"type": "string"},
            "path": {"type": "string"},
            "working_directory": {"type": "string"},
            "venv_path": {"type": "string"},
            "packages": {"type": "array", "items": {"type": "string"}},
            "timeout_seconds": {"type": "integer", "default": 120},
        },
        "required": ["action"],
    }

    async def _run(self, args: list[str], cwd: str | None, timeout: int) -> ToolResult:
        started = time.time()
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
            return ToolResult(False, "", error=f"Python timed out after {timeout}s")
        duration = round((time.time() - started) * 1000, 1)
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        code = proc.returncode or 0
        return ToolResult(
            code == 0,
            f"exit_code={code}\nduration_ms={duration}\n--- stdout ---\n{out}\n--- stderr ---\n{err}",
            error="" if code == 0 else err[-2000:],
        )

    def _python_bin(self, venv_path: str | None) -> str:
        if venv_path:
            root = Path(venv_path)
            for candidate in (
                root / "Scripts" / "python.exe",
                root / "bin" / "python",
                root / "bin" / "python3",
            ):
                if candidate.exists():
                    return str(candidate)
        return sys.executable or "python"

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        cwd = kwargs.get("working_directory")
        timeout = int(kwargs.get("timeout_seconds") or 120)
        venv_path = kwargs.get("venv_path")
        py = self._python_bin(venv_path)
        try:
            if action == "run_code":
                code = kwargs.get("code") or ""
                handle = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
                handle.write(code)
                handle.close()
                try:
                    return await self._run([py, handle.name], cwd, timeout)
                finally:
                    os.unlink(handle.name)
            if action == "run_file":
                path = kwargs.get("path")
                if not path:
                    return ToolResult(False, "", error="path is required")
                return await self._run([py, path], cwd, timeout)
            if action == "create_venv":
                path = Path(kwargs.get("venv_path") or kwargs.get("path") or ".venv")
                if cwd:
                    path = Path(cwd) / path if not path.is_absolute() else path
                venv.EnvBuilder(with_pip=True).create(str(path))
                return ToolResult(True, f"Created virtualenv at {path}")
            if action == "install":
                packages = kwargs.get("packages") or []
                req = Path(cwd or ".") / "requirements.txt"
                args = [py, "-m", "pip", "install"]
                if packages:
                    args.extend(packages)
                elif req.exists():
                    args.extend(["-r", str(req)])
                else:
                    return ToolResult(False, "", error="No packages or requirements.txt provided")
                return await self._run(args, cwd, timeout)
            return ToolResult(False, "", error=f"Unknown action {action}")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
