from __future__ import annotations

from typing import Any

from .base import RiskLevel, Tool, ToolResult


class RequestToolsTool(Tool):
    name = "request_tools"
    description = (
        "Ask Jarvis to expose additional tools for this task. Use when the current tool list is "
        "missing a capability you actually need (browser, desktop, office, docker, git, screenshot, "
        "terminal, python, web_fetch, mcp, or all). The new tools appear on the next model turn."
    )
    risk = RiskLevel.LOW
    parameters = {
        "type": "object",
        "properties": {
            "capabilities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Capability names to add, for example [\"browser\", \"git\"]",
            },
            "reason": {"type": "string"},
        },
        "required": ["capabilities"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from ..agent.tool_exposure import grant_requested_tools, tool_names_for

        granted = grant_requested_tools(kwargs)
        if not granted:
            return ToolResult(
                False,
                "",
                error="No recognized capabilities. Try browser, desktop, office, docker, git, "
                "screenshot, terminal, python, web_fetch, mcp, or all.",
            )
        preview = tool_names_for("mixed" if "all" in granted else "filesystem", granted)
        reason = (kwargs.get("reason") or "").strip()
        note = f" Reason: {reason}" if reason else ""
        return ToolResult(
            True,
            f"Granted additional tools: {', '.join(granted)}.{note} "
            f"They will be in the next tool list ({', '.join(preview) if preview else 'full set'}).",
            data={"granted": granted},
        )
