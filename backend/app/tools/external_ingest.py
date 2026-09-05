from __future__ import annotations

import json
from typing import Any

from .base import RiskLevel, Tool, ToolResult


class ExternalIngestTool(Tool):
    name = "external_ingest"
    description = (
        "Ingest public social or web URLs into a normalized artifact (source, author, caption, "
        "images, video, links). Uses HTTP resolvers first, then Playwright browser, then Browser Use. "
        "Use for Instagram/TikTok/X/YouTube/GitHub posts and general web pages."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Public URL to ingest"},
            "headless": {
                "type": "boolean",
                "description": "Run browser fallbacks headless (default true)",
            },
        },
        "required": ["url"],
    }

    def __init__(self, context_getter) -> None:
        self.context_getter = context_getter

    async def execute(self, **kwargs: Any) -> ToolResult:
        from ..ingest.orchestrator import IngestError, ingest_url
        from .browser import BrowserTool
        from .browser_use import BrowserUseTool

        url = (kwargs.get("url") or "").strip()
        headless = kwargs.get("headless")
        ctx = self.context_getter() or {}
        browser_settings = ctx if isinstance(ctx, dict) else {}
        browser = BrowserTool(lambda: browser_settings)
        browser_use = BrowserUseTool()
        try:
            payload = await ingest_url(
                url,
                browser_tool=browser,
                browser_use_tool=browser_use,
                headless=headless,
            )
        except IngestError as exc:
            return ToolResult(
                False,
                "",
                error=str(exc),
                data={"tiers_attempted": exc.tiers_attempted, "url": url},
            )
        except ValueError as exc:
            return ToolResult(False, "", error=str(exc))
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))

        text = json.dumps(payload, indent=2, default=str)
        return ToolResult(True, text, data=payload)
