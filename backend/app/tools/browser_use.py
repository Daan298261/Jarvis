from __future__ import annotations

from typing import Any

from ..config import load_settings
from ..reflex_loop.schema import SurfaceKind
from ..workers.browser import BrowserUseBackend
from .base import RiskLevel, Tool, ToolResult

_BACKEND = BrowserUseBackend()


class BrowserUseTool(Tool):
    name = "browser_use"
    description = (
        "Optional intelligent browser worker (Browser Use) for unfamiliar sites that need discovery. "
        "Playwright (`browser`) remains the default for known selectors and repetitive workflows. "
        "Pass mode=reflex for the RFC-0172 Reflex-first fast loop (ActionFrame + typed op/target; "
        "no model-generated selectors/JS). If Browser Use is not installed, use browser or web_fetch instead."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "What to accomplish in the browser"},
            "url": {"type": "string", "description": "Optional starting URL (also drives network permission scope)"},
            "mode": {
                "type": "string",
                "enum": ["agent", "reflex"],
                "description": "agent=Browser Use generative worker; reflex=RFC-0172 ActionFrame fast loop",
            },
            "nodes": {
                "type": "array",
                "description": "Optional ActionFrame nodes for reflex dry-run / injected observation",
                "items": {"type": "object"},
            },
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
        mode = str(kwargs.get("mode") or "agent").strip().lower()
        if mode == "reflex":
            from ..reflex_loop.runtime import run_reflex_with_inmemory_world

            nodes = kwargs.get("nodes")
            if not isinstance(nodes, list) or not nodes:
                return ToolResult(
                    False,
                    "",
                    error=(
                        "reflex mode requires an ActionFrame node list (from browser action_frame) "
                        "until a live page observer is bound; refusing rather than inventing controls"
                    ),
                )
            return await run_reflex_with_inmemory_world(
                goal,
                surface=SurfaceKind.BROWSER,
                nodes=list(nodes),
                identity=url or "",
                title=str(kwargs.get("title") or ""),
                enforce_permissions=False,
            )
        return await _BACKEND.run(goal, url, settings)
