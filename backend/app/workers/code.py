from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
from pathlib import Path
from typing import Any

from ..tools.base import ToolResult
from ..tools.safety import resolve_allowed_path

_RUNNER = r"""
import json
import sys

instruction = sys.argv[1]
api_base = sys.argv[2]
api_key = sys.argv[3]
model = sys.argv[4]

from interpreter import interpreter

interpreter.offline = True
interpreter.auto_run = True
interpreter.safe_mode = "off"
interpreter.llm.model = model
interpreter.llm.api_base = api_base
interpreter.llm.api_key = api_key
try:
    interpreter.disable_telemetry = True
except Exception:
    pass
try:
    interpreter.anonymous_telemetry = False
except Exception:
    pass

messages = interpreter.chat(instruction, display=False)
print(json.dumps(messages, default=str))
"""


def open_interpreter_status() -> dict[str, Any]:
    module = importlib.util.find_spec("interpreter") is not None
    cli = shutil.which("interpreter")
    available = bool(module or cli)
    if available:
        detail = (
            "Optional code/shell worker behind an adapter. Forced onto Jarvis's local "
            "OpenAI-compatible endpoint. Jarvis still verifies the result."
        )
        status = "ready"
    else:
        detail = (
            "Install the open-interpreter package to enable this worker. "
            "Native python, terminal, and filesystem tools remain the default."
        )
        status = "missing"
    return {
        "id": "open-interpreter",
        "name": "Open Interpreter",
        "kind": "optional",
        "available": available,
        "status": status,
        "detail": detail,
        "module": module,
        "cli": cli,
    }


def _summarize_messages(payload: Any) -> str:
    if isinstance(payload, str):
        text = payload.strip()
        return text[-8000:] if len(text) > 8000 else text
    if not isinstance(payload, list):
        return json.dumps(payload, default=str)[:8000]
    chunks: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            chunks.append(str(item))
            continue
        role = item.get("role") or "assistant"
        content = item.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(str(part["text"]))
                elif isinstance(part, str):
                    parts.append(part)
            content = "\n".join(parts)
        if content:
            chunks.append(f"{role}: {content}")
    text = "\n".join(chunks).strip() or json.dumps(payload, default=str)
    return text[-8000:] if len(text) > 8000 else text


class CodeAgentBackend:
    """Specialist coding worker. Native tools remain the default path."""

    name = "native"

    def available(self) -> bool:
        return True

    def describe(self) -> dict[str, Any]:
        return {"backend": self.name, "available": self.available()}

    async def run(
        self,
        instruction: str,
        working_directory: Path,
        *,
        api_base: str,
        api_key: str,
        model: str,
        timeout: float,
    ) -> ToolResult:
        return ToolResult(
            False,
            "",
            error="Open Interpreter is not installed. Use python, terminal, and filesystem tools instead.",
        )


class OpenInterpreterBackend(CodeAgentBackend):
    name = "open-interpreter"

    def available(self) -> bool:
        return bool(open_interpreter_status()["available"])

    def describe(self) -> dict[str, Any]:
        status = open_interpreter_status()
        return {"backend": self.name, **status}

    async def run(
        self,
        instruction: str,
        working_directory: Path,
        *,
        api_base: str,
        api_key: str,
        model: str,
        timeout: float,
    ) -> ToolResult:
        status = open_interpreter_status()
        if not status["available"]:
            return await super().run(
                instruction,
                working_directory,
                api_base=api_base,
                api_key=api_key,
                model=model,
                timeout=timeout,
            )
        env = os.environ.copy()
        env["OPENAI_API_BASE"] = api_base
        env["OPENAI_API_KEY"] = api_key or "local"
        env["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
        working_directory.mkdir(parents=True, exist_ok=True)

        if status["module"]:
            proc = await asyncio.create_subprocess_exec(
                sys_executable(),
                "-c",
                _RUNNER,
                instruction,
                api_base,
                api_key or "local",
                model,
                cwd=str(working_directory),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                status["cli"] or "interpreter",
                "--offline",
                "--auto_run",
                "--disable_telemetry",
                "--api_base",
                api_base,
                "--api_key",
                api_key or "local",
                "--model",
                model,
                instruction,
                cwd=str(working_directory),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(False, "", error=f"Open Interpreter timed out after {int(timeout)}s")
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        if proc.returncode:
            return ToolResult(False, out, error=err.strip() or f"Open Interpreter exited {proc.returncode}")
        summary = _summarize_messages(_try_json(out) if out.strip().startswith("[") else out)
        return ToolResult(
            True,
            summary or out or "Open Interpreter finished with no output.",
            data={"backend": self.name, "working_directory": str(working_directory)},
        )


def sys_executable() -> str:
    import sys

    return sys.executable


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def resolve_code_backend() -> CodeAgentBackend:
    backend = OpenInterpreterBackend()
    if backend.available():
        return backend
    return CodeAgentBackend()


def sandbox_working_directory(path: str | None, allowed: list[str]) -> Path:
    if path:
        return resolve_allowed_path(path, allowed)
    if allowed:
        return Path(allowed[0]).expanduser().resolve()
    return Path.cwd().resolve()
