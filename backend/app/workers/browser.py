from __future__ import annotations

import asyncio
import importlib.util
from typing import Any

from ..config import AppSettings, data_dir, load_settings
from ..tools.base import ToolResult
from .local_llm import local_chat_openai

DEFAULT_BROWSER_BACKEND = "playwright"

_SESSION_LOCK = asyncio.Lock()
_BROWSER_SESSION: Any | None = None
_SESSION_CREATED = False


def playwright_is_default() -> bool:
    return DEFAULT_BROWSER_BACKEND == "playwright"


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def reset_browser_use_session() -> None:
    """Test helper: drop the cached Browser Use session."""
    global _BROWSER_SESSION, _SESSION_CREATED
    _BROWSER_SESSION = None
    _SESSION_CREATED = False


def network_permission_block(tool_name: str, *, goal: str, url: str | None) -> str | None:
    """Return an error message when INTERNET_TOOLS permission gates block execution."""
    from ..policy.computer_permissions import evaluate_tool_permissions

    arguments: dict[str, Any] = {"goal": goal}
    if url:
        arguments["url"] = url
    decision = evaluate_tool_permissions(tool_name, arguments)
    if decision.status == "deny":
        return decision.reason
    if decision.status == "ask":
        return decision.reason or "Permission required before Browser Use can reach the network."
    return None


def structured_payload_from_history(history: Any, *, start_url: str | None = None) -> dict[str, Any]:
    """Map a browser-use AgentHistoryList into Jarvis ingest-friendly fields."""
    final_text = ""
    if history is not None and hasattr(history, "final_result"):
        try:
            final_text = str(history.final_result() or "")
        except Exception:
            final_text = ""

    resolved_url = (start_url or "").strip()
    title = ""
    action_trace: list[dict[str, Any]] = []
    extracted_chunks: list[str] = []

    items = getattr(history, "history", None) or []
    for index, item in enumerate(items):
        step: dict[str, Any] = {"step": index + 1}
        state = getattr(item, "state", None)
        if state is not None:
            if hasattr(state, "url") and getattr(state, "url", None):
                resolved_url = str(getattr(state, "url"))
            elif hasattr(state, "to_dict"):
                state_dict = state.to_dict()
                if isinstance(state_dict, dict):
                    if state_dict.get("url"):
                        resolved_url = str(state_dict["url"])
                    if state_dict.get("title"):
                        title = str(state_dict["title"])
            if hasattr(state, "title") and getattr(state, "title", None):
                title = str(getattr(state, "title"))

        model_output = getattr(item, "model_output", None)
        actions = getattr(model_output, "action", None) if model_output is not None else None
        if actions:
            serialized: list[Any] = []
            for action in actions[:5]:
                if hasattr(action, "model_dump"):
                    serialized.append(action.model_dump(exclude_none=True, mode="json"))
                else:
                    serialized.append(str(action))
            step["actions"] = serialized

        for result in getattr(item, "result", None) or []:
            content = getattr(result, "extracted_content", None)
            if content:
                text = str(content).strip()
                if text:
                    extracted_chunks.append(text[:800])
                    step.setdefault("extracted", []).append(text[:400])
            err = getattr(result, "error", None)
            if err:
                step.setdefault("errors", []).append(str(err)[:240])

        if len(step) > 1:
            action_trace.append(step)
        if len(action_trace) >= 32:
            break

    extracted_text = final_text.strip()
    if not extracted_text and extracted_chunks:
        extracted_text = "\n\n".join(dict.fromkeys(extracted_chunks))

    return {
        "url": resolved_url,
        "title": title,
        "extracted_text": extracted_text,
        "action_trace": action_trace,
        "steps": len(items) if hasattr(items, "__len__") else 0,
    }


def format_browser_use_output(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    if payload.get("title"):
        parts.append(f"Title: {payload['title']}")
    if payload.get("url"):
        parts.append(f"URL: {payload['url']}")
    body = str(payload.get("extracted_text") or "").strip()
    if body:
        parts.append(body)
    return "\n".join(parts).strip() or "Browser Use finished."


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
                    "Intelligent browser discovery via browser-use with session reuse and structured traces. "
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
                "Adapter is integrated. Use Install now on the Tools page to add the MIT browser-use package "
                "for intelligent discovery. Playwright stays the default; Jarvis falls back to browser and web_fetch."
            ),
        }

    async def run(
        self,
        goal: str,
        url: str | None = None,
        settings: AppSettings | None = None,
        *,
        skip_permission_check: bool = False,
    ) -> ToolResult:
        if not goal or not str(goal).strip():
            return ToolResult(False, "", error="goal is required")
        cleaned_goal = str(goal).strip()
        cleaned_url = (url or "").strip() or None

        if not self.available():
            return ToolResult(
                False,
                "",
                error=(
                    "Browser Use is not installed on this machine. "
                    "Use the Playwright browser tool or web_fetch instead."
                ),
            )

        if not skip_permission_check:
            blocked = network_permission_block("browser_use", goal=cleaned_goal, url=cleaned_url)
            if blocked:
                return ToolResult(False, "", error=blocked)

        current = settings or load_settings()
        task = cleaned_goal
        if cleaned_url:
            task = f"{task}\nStart at: {cleaned_url}"
        try:
            history = await self._invoke(task, current, start_url=cleaned_url)
        except Exception as exc:
            reset_browser_use_session()
            return ToolResult(
                False,
                "",
                error=f"Browser Use failed: {exc}. Fall back to the Playwright browser tool.",
            )
        structured = structured_payload_from_history(history, start_url=cleaned_url)
        output = format_browser_use_output(structured)
        data = {
            "backend": self.id,
            "goal": cleaned_goal,
            "url": structured.get("url") or cleaned_url,
            "title": structured.get("title") or "",
            "extracted_text": structured.get("extracted_text") or "",
            "action_trace": structured.get("action_trace") or [],
            "steps": structured.get("steps") or 0,
            "session_reused": _SESSION_CREATED,
        }
        return ToolResult(True, output, data=data)

    async def _shared_browser_session(self, settings: AppSettings) -> Any | None:
        global _BROWSER_SESSION, _SESSION_CREATED
        async with _SESSION_LOCK:
            if _BROWSER_SESSION is not None:
                _SESSION_CREATED = True
                return _BROWSER_SESSION
            try:
                from browser_use import BrowserSession
            except ImportError:
                try:
                    from browser_use.browser.session import BrowserSession  # type: ignore[attr-defined]
                except ImportError:
                    return None

            profile_dir = data_dir() / "browser-use-profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            headless = bool(settings.browser.headless)
            try:
                session = BrowserSession(headless=headless, user_data_dir=str(profile_dir))
            except TypeError:
                session = BrowserSession(headless=headless)
            _BROWSER_SESSION = session
            _SESSION_CREATED = False
            return session

    async def _invoke(self, task: str, settings: AppSettings, *, start_url: str | None = None) -> Any:
        from browser_use import Agent

        llm = local_chat_openai(settings)
        browser_session = await self._shared_browser_session(settings)
        agent_kwargs: dict[str, Any] = {"task": task, "llm": llm}
        if browser_session is not None:
            agent_kwargs["browser"] = browser_session
        try:
            agent = Agent(**agent_kwargs)
        except TypeError:
            agent_kwargs["use_vision"] = False
            agent = Agent(**agent_kwargs)

        result = agent.run()
        if hasattr(result, "__await__"):
            result = await result
        return result
