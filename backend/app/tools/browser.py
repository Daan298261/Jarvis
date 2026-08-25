from __future__ import annotations

from typing import Any

from ..config import AppSettings, load_settings
from .base import RiskLevel, Tool, ToolResult
from .browser_backends import resolve_browser_backend


class BrowserTool(Tool):
    name = "browser"
    description = (
        "Automate Chromium with Playwright (deterministic) or Browser Use (intelligent discovery). "
        "Playwright actions: open, snapshot, click, type, fill, press, evaluate, screenshot, tabs, download, upload, close. "
        "Browser Use action: task (natural-language instruction). "
        "Use snapshot first with Playwright, then click by accessible name or CSS selector."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "open",
                    "snapshot",
                    "click",
                    "type",
                    "fill",
                    "press",
                    "evaluate",
                    "screenshot",
                    "tabs",
                    "download",
                    "upload",
                    "close",
                    "task",
                ],
            },
            "backend": {
                "type": "string",
                "description": "Optional override: playwright (default) or browser-use for task action.",
            },
            "url": {"type": "string"},
            "selector": {"type": "string"},
            "name": {"type": "string", "description": "Accessible name for click/type"},
            "text": {"type": "string"},
            "task": {"type": "string", "description": "Natural-language browser task for Browser Use"},
            "key": {"type": "string"},
            "script": {"type": "string"},
            "path": {"type": "string"},
            "headless": {"type": "boolean"},
            "max_steps": {"type": "integer", "description": "Browser Use step limit"},
            "use_vision": {"type": "boolean", "description": "Browser Use screenshot analysis"},
        },
        "required": ["action"],
    }

    def __init__(self, context_getter) -> None:
        self.context_getter = context_getter

    def _settings(self) -> AppSettings:
        raw = self.context_getter()
        settings = load_settings()
        if isinstance(raw, AppSettings):
            return raw
        browser = raw.get("browser") if isinstance(raw, dict) else None
        if isinstance(browser, dict):
            merged = settings.model_dump()
            merged["browser"] = {**settings.browser.model_dump(), **browser}
            return AppSettings.model_validate(merged)
        return settings

    async def execute(self, **kwargs: Any) -> ToolResult:
        settings = self._settings()
        action = kwargs.get("action")
        requested = kwargs.get("backend")
        if action == "task" and not requested:
            requested = "browser-use"
        backend = resolve_browser_backend(settings, requested)
        return await backend.execute(**kwargs)
