from __future__ import annotations

from typing import Any

from ..workers.computer import CuaBackend, UFOBackend
from .base import RiskLevel, Tool, ToolResult


class UFOTool(Tool):
    name = "ufo"
    description = (
        "Optional Microsoft UFO HostAgent/AppAgent worker for native Windows apps. "
        "Prefer the desktop tool's named UI Automation controls first. "
        "Actions: run. Provide a goal and optional app title."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["run"]},
            "goal": {"type": "string"},
            "app": {"type": "string", "description": "Optional window title or process name."},
        },
        "required": ["action", "goal"],
    }

    def __init__(self) -> None:
        self.backend = UFOBackend()

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action") or "run"
        if action != "run":
            return ToolResult(False, "", error=f"Unknown action {action}")
        return await self.backend.run(str(kwargs.get("goal") or ""), app=kwargs.get("app"))


class CuaTool(Tool):
    name = "cua"
    description = (
        "Optional Cua computer-use worker. Prefer native desktop UI Automation first. "
        "Actions: run. Provide a goal and optional app title."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["run"]},
            "goal": {"type": "string"},
            "app": {"type": "string", "description": "Optional window title or process name."},
        },
        "required": ["action", "goal"],
    }

    def __init__(self) -> None:
        self.backend = CuaBackend()

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action") or "run"
        if action != "run":
            return ToolResult(False, "", error=f"Unknown action {action}")
        return await self.backend.run(str(kwargs.get("goal") or ""), app=kwargs.get("app"))
