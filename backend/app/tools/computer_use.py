from __future__ import annotations

from typing import Any

from ..reflex_loop.schema import SurfaceKind
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


class ReflexComputerUseTool(Tool):
    """RFC-0172 Reflex-first computer-use fast loop (desktop ActionFrame path)."""

    name = "reflex_computer_use"
    description = (
        "Reflex-first desktop computer-use fast loop (RFC-0172). "
        "Observes an ActionFrame of named UI Automation controls, asks the Reflex Lane for one "
        "typed operation+target, executes by target_id only (no model selectors/coordinates/JS/shell), "
        "and verifies postconditions. Actions: run. Provide goal and nodes (or rely on prior action_frame)."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["run"]},
            "goal": {"type": "string"},
            "app": {"type": "string"},
            "nodes": {
                "type": "array",
                "description": "ActionFrame nodes from desktop action_frame / inspect",
                "items": {"type": "object"},
            },
        },
        "required": ["action", "goal"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action") or "run"
        if action != "run":
            return ToolResult(False, "", error=f"Unknown action {action}")
        goal = str(kwargs.get("goal") or "").strip()
        if not goal:
            return ToolResult(False, "", error="goal is required")
        nodes = kwargs.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            return ToolResult(
                False,
                "",
                error=(
                    "reflex_computer_use requires ActionFrame nodes from desktop action_frame; "
                    "refusing to invent controls or coordinates"
                ),
            )
        from ..reflex_loop.runtime import run_reflex_with_inmemory_world

        return await run_reflex_with_inmemory_world(
            goal,
            surface=SurfaceKind.DESKTOP,
            nodes=list(nodes),
            identity=str(kwargs.get("app") or ""),
            title=str(kwargs.get("app") or ""),
            enforce_permissions=True,
        )
