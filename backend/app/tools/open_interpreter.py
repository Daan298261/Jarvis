from __future__ import annotations

from typing import Any

from ..config import load_settings
from ..workers.code import OpenInterpreterBackend
from .base import RiskLevel, Tool, ToolResult
from .safety import resolve_allowed_path

_BACKEND = OpenInterpreterBackend()


class OpenInterpreterTool(Tool):
    name = "open_interpreter"
    description = (
        "Optional Open Interpreter worker for substantial coding or shell jobs. "
        "Keep simple file and shell work on native filesystem/python/terminal tools. "
        "If Open Interpreter is missing, use those native tools instead. Jarvis must still verify."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "delegate"]},
            "goal": {"type": "string", "description": "What the worker should change or fix"},
            "path": {"type": "string", "description": "Repository or project directory"},
        },
        "required": ["action"],
    }

    def __init__(self, context_getter) -> None:
        self.context_getter = context_getter

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        if action == "status":
            probe = _BACKEND.probe()
            return ToolResult(True, probe["detail"], data=probe)
        if action != "delegate":
            return ToolResult(False, "", error=f"Unknown action {action}")
        goal = kwargs.get("goal")
        if not goal:
            return ToolResult(False, "", error="goal is required")
        context = self.context_getter() if self.context_getter else {}
        allowed = list(context.get("allowed_directories") or [])
        raw_path = kwargs.get("path") or (allowed[0] if allowed else ".")
        try:
            path = resolve_allowed_path(str(raw_path), allowed)
        except PermissionError as exc:
            return ToolResult(False, "", error=str(exc))
        settings = load_settings()
        return await _BACKEND.run(str(goal), path, settings)
