from __future__ import annotations

import importlib.util
from typing import Any

from ..config import AppSettings, load_settings
from ..tools.base import ToolResult
from .local_llm import local_chat_openai

DEFAULT_BROWSER_BACKEND = "playwright"


def playwright_is_default() -> bool:
    return DEFAULT_BROWSER_BACKEND == "playwright"


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


class BrowserUseBackend:
    """Intelligent browser discovery worker. Playwright remains the deterministic default."""

    id = "browser-use"
    name = "Browser Use"
    license_id = "MIT"

    def available(self) -> bool:
        return _module_available("browser_use")

    def probe(self) -> dict[str, Any]:
        if self.available():
            return {
                "id": self.id,
                "name": self.name,
                "kind": "optional",
                "available": True,
                "status": "ready",
                "detail": (
                    "Intelligent browser discovery via browser-use. "
                    "Playwright remains the default deterministic backend."
                ),
            }
        return {
            "id": self.id,
            "name": self.name,
            "kind": "optional",
            "available": False,
            "status": "missing",
            "detail": (
                "Adapter is integrated. Install the MIT-licensed browser-use package to enable "
                "intelligent discovery. Playwright stays the default; Jarvis will fall back to it."
            ),
        }

    async def run(
        self,
        goal: str,
        url: str | None = None,
        settings: AppSettings | None = None,
    ) -> ToolResult:
        if not goal or not str(goal).strip():
            return ToolResult(False, "", error="goal is required")
        if not self.available():
            return ToolResult(
                False,
                "",
                error=(
                    "Browser Use is not installed on this machine. "
                    "Use the Playwright browser tool or web_fetch instead."
                ),
            )
        current = settings or load_settings()
        task = str(goal).strip()
        if url:
            task = f"{task}\nStart at: {url}"
        try:
            result = await self._invoke(task, current)
        except Exception as exc:
            return ToolResult(
                False,
                "",
                error=f"Browser Use failed: {exc}. Fall back to the Playwright browser tool.",
            )
        return ToolResult(True, str(result), data={"backend": self.id, "goal": goal, "url": url})

    async def _invoke(self, task: str, settings: AppSettings) -> Any:
        from browser_use import Agent

        llm = local_chat_openai(settings)
        try:
            agent = Agent(task=task, llm=llm)
        except TypeError:
            agent = Agent(task=task, llm=llm, use_vision=False)
        result = agent.run()
        if hasattr(result, "__await__"):
            result = await result
        return result
