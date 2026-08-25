from __future__ import annotations

from typing import Any

from .base import RiskLevel, Tool, ToolResult
from .exposure import ToolExposure, tools_for_task


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
            "action": {"type": "string", "enum": ["request", "list"]},
            "name": {"type": "string", "description": "Single capability to grant"},
            "capabilities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names to enable, e.g. git, browser, docker",
            },
            "reason": {"type": "string"},
            "task_class": {"type": "string"},
        },
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from .registry import REGISTRY

        action = (kwargs.get("action") or "request").strip().lower()
        exposure = REGISTRY._context.get("exposure")
        if not isinstance(exposure, ToolExposure):
            exposure = ToolExposure(kwargs.get("task_class") or "mixed")
            REGISTRY.bind_exposure(exposure)

        if action == "list":
            names = sorted(exposure.names())
            return ToolResult(True, "Available for this task: " + ", ".join(names), data={"tools": names})

        wanted: list[str] = []
        if kwargs.get("name"):
            wanted.append(str(kwargs["name"]))
        raw = kwargs.get("capabilities") or kwargs.get("tools") or []
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.replace(",", " ").split() if part.strip()]
        if isinstance(raw, list):
            wanted.extend(str(item) for item in raw if item)

        added: list[str] = []
        notes: list[str] = []
        for name in wanted:
            ok, message, extra = exposure.grant(name)
            notes.append(message)
            if ok:
                added.extend(extra or [name])
        if not wanted:
            fallback = sorted(tools_for_task(exposure.task_class))
            return ToolResult(True, "No capability named. Current tools: " + ", ".join(fallback), data={"tools": fallback})
        return ToolResult(
            True,
            " ".join(notes) if notes else f"Capability request recorded: {', '.join(wanted)}",
            data={"granted": added, "tools": sorted(exposure.names())},
        )
