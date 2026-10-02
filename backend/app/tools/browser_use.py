from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

from ..config import live_workspace_roots_from_context, load_settings
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
        "no model-generated selectors/JS). If Browser Use is not installed, use browser or web_fetch instead. "
        "url may be http(s) or a local workspace file on USB/`D:`."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "What to accomplish in the browser"},
            "url": {
                "type": "string",
                "description": "Optional starting URL or local workspace file (USB/`D:` HTML/PDF)",
            },
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

    def __init__(self, context_getter: Callable[[], dict[str, Any]] | None = None) -> None:
        self.context_getter = context_getter or (lambda: {})

    def _allowed(self) -> list[str]:
        raw = self.context_getter() if callable(self.context_getter) else {}
        return live_workspace_roots_from_context(raw)

    def _resolve_start_url(self, url: str | None) -> str | None:
        text = str(url or "").strip()
        if not text:
            return None
        from .browser import looks_like_workspace_file_target, resolve_browser_open_url

        scheme = (urlparse(text).scheme or "").lower()
        if scheme in {"http", "https"}:
            return text
        if scheme == "file" or looks_like_workspace_file_target(text):
            return resolve_browser_open_url(text, self._allowed())
        return text

    async def execute(self, **kwargs: Any) -> ToolResult:
        settings = load_settings()
        goal = str(kwargs.get("goal") or "")
        raw_url = kwargs.get("url")
        if isinstance(raw_url, str):
            raw_url = raw_url.strip() or None
        else:
            raw_url = None
        try:
            url = self._resolve_start_url(raw_url)
        except PermissionError as exc:
            return ToolResult(False, "", error=str(exc))
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
                enforce_permissions=True,
            )
        return await _BACKEND.run(goal, url, settings)
