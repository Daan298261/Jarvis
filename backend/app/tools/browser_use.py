from __future__ import annotations

from typing import Any

from ..config import load_settings
from ..workers.browser import BrowserUseBackend
from .base import RiskLevel, Tool, ToolResult

_BACKEND = BrowserUseBackend()


class BrowserUseTool(Tool):
    name = "browser_use"
    description = (
        "Optional intelligent browser worker (Browser Use) for unfamiliar sites that need discovery. "
        "Playwright (`browser`) remains the default for known selectors and repetitive workflows. "
        "If Browser Use is not installed, use browser or web_fetch instead."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "What to accomplish in the browser"},
            "url": {"type": "string", "description": "Optional starting URL (also drives network permission scope)"},
        },
        "required": ["goal"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        settings = load_settings()
        goal = str(kwargs.get("goal") or "")
        url = kwargs.get("url")
        if isinstance(url, str):
            url = url.strip() or None
        else:
            url = None
        return await _BACKEND.run(goal, url, settings)
