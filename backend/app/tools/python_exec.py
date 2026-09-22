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

_PY_ACTIONS = ("run_code", "run_file", "create_venv", "install")


def normalize_python_call(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Salvage Qwen-style XML leftovers that dump source into `action`.

    Live 1.4.9 log: action=\"run_code>\\nimport os...\" with no `code` field.
    """
    out = dict(kwargs)
    action = str(out.get("action") or "").strip()
    code = str(out.get("code") or "").strip()
    command = str(out.get("command") or "").strip()
    if action in _PY_ACTIONS:
        if action == "run_code" and not code and command:
            out["code"] = command
        return out
    for name in _PY_ACTIONS:
        if not action.startswith(name):
            continue
        rest = action[len(name) :].lstrip(" \t>")
        rest = rest.lstrip("\r\n")
        out["action"] = name
        if name == "run_code" and rest and not code:
            out["code"] = rest
        elif name == "run_file" and rest and not out.get("path"):
            out["path"] = rest.splitlines()[0].strip()
        return out
    if "\n" in action or action.startswith(("import ", "from ", "print(", "def ", "class ")):
        out["action"] = "run_code"
        if not code:
            out["code"] = action
        return out
    if not action and (code or command):
        out["action"] = "run_code"
        if not code:
            out["code"] = command
    return out


class PythonTool(Tool):
    name = "python"
    description = (
        "Create or run Python in an isolated way. Actions: run_code, run_file, create_venv, "
        "install. Put the script in `code` (run_code) or an absolute `path` (run_file) — never "
        "inside `action`. For copying files or folders use filesystem action=copy instead of a "
        "script. Prefer create_venv for project-specific packages. working_directory should "
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

    def _resolve_script(self, path: str, cwd: str | None) -> Path:
        raw = Path(path)
        if raw.is_file():
            return raw
        if cwd:
            nested = Path(cwd) / path
            if nested.is_file():
                return nested
        return raw

    async def execute(self, **kwargs: Any) -> ToolResult:
        kwargs = normalize_python_call(kwargs)
        action = kwargs.get("action")
        cwd = kwargs.get("working_directory")
        timeout = int(kwargs.get("timeout_seconds") or 120)
        venv_path = kwargs.get("venv_path")
        py = self._python_bin(venv_path)
        try:
            if action == "run_code":
                code = kwargs.get("code") or ""
                if not str(code).strip():
                    return ToolResult(
                        False,
                        "",
                        error="run_code requires `code`. Do not put the script in `action`. "
                        "To copy files use filesystem action=copy with path and destination.",
                    )
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
                resolved = self._resolve_script(str(path), cwd)
                if not resolved.is_file():
                    return ToolResult(
                        False,
                        "",
                        error=(
                            f"Script not found: {resolved}. Pass an absolute path or working_directory. "
                            "To copy files or folders use filesystem action=copy instead of run_file."
                        ),
                    )
                return await self._run([py, str(resolved)], cwd, timeout)
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
            return ToolResult(
                False,
                "",
                error=(
                    f"Unknown action {action!r}. Valid actions: run_code, run_file, create_venv, install. "
                    "Put source in `code`, not `action`. To copy a tree use filesystem action=copy."
                ),
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
