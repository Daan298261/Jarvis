from __future__ import annotations

from typing import Any

from ..config import load_settings
from ..inference.manager import MANAGER
from ..workers.code import OpenInterpreterBackend, sandbox_working_directory
from .base import RiskLevel, Tool, ToolResult


class CodeWorkerTool(Tool):
    name = "code_worker"
    description = (
        "Delegate a substantial coding or shell task to Open Interpreter when it is installed. "
        "Use for multi-file code generation or exploratory scripting. Stay inside allowed directories. "
        "Jarvis must still inspect the diff and verify. Prefer native python/terminal/filesystem for simple work. "
        "Open Interpreter is forced onto Jarvis's local OpenAI-compatible endpoint; it must not call cloud APIs."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "What the worker should accomplish. Be specific about files and the end state.",
            },
            "working_directory": {
                "type": "string",
                "description": "Project folder. Must be inside allowed directories.",
            },
            "timeout_seconds": {"type": "integer", "description": "Wall-clock limit. Default 180."},
        },
        "required": ["instruction"],
    }

    def __init__(self, context_getter) -> None:
        self.context_getter = context_getter

    async def execute(self, **kwargs: Any) -> ToolResult:
        instruction = (kwargs.get("instruction") or "").strip()
        if not instruction:
            return ToolResult(False, "", error="instruction is required")
        context = self.context_getter() or {}
        allowed = list(context.get("allowed_directories") or [])
        try:
            working = sandbox_working_directory(kwargs.get("working_directory"), allowed)
        except PermissionError as exc:
            return ToolResult(False, "", error=str(exc))
        timeout = kwargs.get("timeout_seconds")
        try:
            timeout_s = float(timeout) if timeout is not None else 180.0
        except (TypeError, ValueError):
            timeout_s = 180.0
        timeout_s = max(15.0, min(timeout_s, 1800.0))

        settings = load_settings()
        api_base = MANAGER.base_url(settings)
        api_key = settings.inference.api_key or "local"
        model = settings.inference.remote_model or "openai/Qwen3.5-27B"
        if not str(model).startswith(("openai/", "ollama/")):
            model = f"openai/{model}"

        backend = OpenInterpreterBackend()
        return await backend.run(
            instruction,
            working,
            api_base=api_base,
            api_key=api_key,
            model=model,
            timeout=timeout_s,
        )
