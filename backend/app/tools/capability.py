from __future__ import annotations

from typing import Any

from .base import RiskLevel, Tool, ToolResult
from .exposure import NATIVE_TOOLS, REQUEST_CAPABILITY, exposure_catalog, tools_for_task


class CapabilityTool(Tool):
    """Escape hatch so a task-scoped tool subset can grow mid-run."""

    name = REQUEST_CAPABILITY
    description = (
        "List or request additional native tools for this task. Jarvis only sends a "
        "task-relevant subset of tools on each model call. If you need browser, docker, "
        "office, desktop, screenshot, git, mcp, or another missing capability, request it "
        "here instead of guessing. Actions: list, request."
    )
    risk = RiskLevel.LOW
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "request"], "default": "request"},
            "name": {
                "type": "string",
                "description": "Tool or capability to expose, e.g. browser, git, docker, office, desktop, screenshot, mcp",
            },
            "task_class": {"type": "string"},
        },
        "required": [],
    }

    def __init__(self, exposure_getter=None) -> None:
        self.exposure_getter = exposure_getter

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = (kwargs.get("action") or "request").lower()
        if action == "list":
            task_class = kwargs.get("task_class") or ""
            current = sorted(tools_for_task(task_class)) if task_class else sorted(NATIVE_TOOLS)
            catalog = {key: values for key, values in exposure_catalog().items()}
            return ToolResult(
                True,
                "Native capabilities: "
                + ", ".join(NATIVE_TOOLS)
                + "\nDefault for this task_class: "
                + ", ".join(current),
                data={"native": list(NATIVE_TOOLS), "task_defaults": catalog, "current": current},
            )
        requested = kwargs.get("name") or kwargs.get("capability") or kwargs.get("tool")
        getter = self.exposure_getter
        exposure = getter() if callable(getter) else None
        if exposure is None:
            from .exposure import ToolExposure

            exposure = ToolExposure(kwargs.get("task_class"))
        ok, message, added = exposure.grant(requested)
        return ToolResult(ok, message, data={"added": added}, error="" if ok else message)
