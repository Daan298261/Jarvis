from __future__ import annotations

from typing import Any

from ..agent.tool_exposure import resolve_requested_names, wants_full_access
from .base import RiskLevel, Tool, ToolResult


class RequestToolsTool(Tool):
    name = "request_tools"
    description = (
        "Ask the runtime to expose additional tools for this task. Use when the current "
        "tool set cannot finish the work. Pass tool names (browser, git, desktop, …) or "
        "categories: browser, coding, windows, office, mcp, all."
    )
    risk = RiskLevel.LOW
    parameters = {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names or categories to add to the exposed set.",
            },
            "reason": {
                "type": "string",
                "description": "Why the current tool set is insufficient.",
            },
        },
        "required": ["names"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        names = kwargs.get("names") or []
        reason = str(kwargs.get("reason") or "").strip()
        if wants_full_access("", names):
            return ToolResult(
                True,
                "All enabled tools are now available for the rest of this task.",
                data={"all": True, "names": names, "reason": reason},
            )
        added = sorted(resolve_requested_names(names))
        if not added:
            return ToolResult(
                False,
                "",
                error=(
                    "Provide names or categories such as browser, coding, windows, "
                    "office, mcp, all, or a concrete tool name."
                ),
            )
        suffix = f" Reason: {reason}" if reason else ""
        return ToolResult(
            True,
            f"Added tools: {', '.join(added)}.{suffix}",
            data={"added": added, "reason": reason, "all": False},
        )
