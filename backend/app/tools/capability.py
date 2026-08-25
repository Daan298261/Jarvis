from __future__ import annotations

from typing import Any

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
            "capabilities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names to enable, e.g. git, browser, docker",
            },
            "reason": {"type": "string"},
        },
        "required": ["capabilities"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        wanted = kwargs.get("capabilities") or []
        if isinstance(wanted, str):
            wanted = [wanted]
        names = ", ".join(str(item) for item in wanted) or "(none)"
        return ToolResult(True, f"Capability request recorded: {names}")
