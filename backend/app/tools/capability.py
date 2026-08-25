from __future__ import annotations

from typing import Any

from ..tools.exposure import ToolExposure, tools_for_task
from .base import RiskLevel, Tool, ToolResult


class RequestCapabilityTool(Tool):
    """Escape hatch when the task-specific tool subset is too small."""

    name = "request_capability"
    description = (
        "Expose additional Jarvis tools for this task. Call this when you need a capability "
        "that is not in the current tool list (for example git, docker, desktop, browser, office, screenshot)."
    )
    risk = RiskLevel.LOW
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["request", "list"], "description": "request a tool or list the current set"},
            "name": {"type": "string", "description": "Single capability to grant"},
            "capabilities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names to enable, e.g. git, browser, docker",
            },
            "task_class": {"type": "string"},
            "reason": {"type": "string"},
        },
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from .registry import REGISTRY

        exposure = REGISTRY._context.get("exposure")
        if not isinstance(exposure, ToolExposure):
            exposure = ToolExposure(kwargs.get("task_class") or "mixed")
            REGISTRY.bind_exposure(exposure)
        action = (kwargs.get("action") or "request").strip().lower()
        if action == "list":
            names = sorted(exposure.names() | tools_for_task(kwargs.get("task_class") or exposure.task_class))
            return ToolResult(True, "Available tools: " + ", ".join(names), data={"tools": names})
        wanted: list[str] = []
        if kwargs.get("name"):
            wanted.append(str(kwargs.get("name")))
        raw = kwargs.get("capabilities") or kwargs.get("tools") or []
        if isinstance(raw, str):
            wanted.extend([part.strip() for part in raw.replace(",", " ").split() if part.strip()])
        elif isinstance(raw, list):
            wanted.extend(str(item) for item in raw if item)
        if not wanted:
            return ToolResult(False, "", error="name or capabilities is required")
        added: list[str] = []
        messages: list[str] = []
        ok = True
        for item in wanted:
            granted, message, extra = exposure.grant(item)
            ok = ok and granted
            messages.append(message)
            added.extend(extra)
        if not ok and not added:
            return ToolResult(False, "", error="; ".join(messages))
        return ToolResult(True, " ".join(messages), data={"granted": added})
