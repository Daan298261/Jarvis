from __future__ import annotations

import asyncio
import importlib.util
import logging
from typing import Any

from ..config import AppSettings, data_dir, load_settings
from .browser_structured import (
    browser_use_tool_result_data,
    format_browser_use_output,
    structured_payload_from_history,
)
from .local_llm import local_browser_use_model, local_chat_openai_for_browser_use

logger = logging.getLogger(__name__)

DEFAULT_BROWSER_BACKEND = "playwright"
_DEFAULT_MAX_STEPS = 60

_SESSION_LOCK = asyncio.Lock()
_BROWSER_SESSION: Any | None = None
_SESSION_STARTED = False
_SESSION_REUSED = False


def playwright_is_default() -> bool:
    return DEFAULT_BROWSER_BACKEND == "playwright"


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def reset_browser_use_session() -> None:
    """Drop the cached Browser Use session (sync; does not await browser teardown)."""
    global _BROWSER_SESSION, _SESSION_STARTED, _SESSION_REUSED
    _BROWSER_SESSION = None
    _SESSION_STARTED = False
    _SESSION_REUSED = False


async def reset_browser_use_session_async() -> None:
    """Stop the cached browser-use session and clear Jarvis-side reuse state."""
    global _BROWSER_SESSION, _SESSION_STARTED, _SESSION_REUSED
    async with _SESSION_LOCK:
        session = _BROWSER_SESSION
        _BROWSER_SESSION = None
        _SESSION_STARTED = False
        _SESSION_REUSED = False
    if session is None:
        return
    for method_name in ("kill", "stop", "close"):
        method = getattr(session, method_name, None)
        if not callable(method):
            continue
        try:
            result = method()
            if hasattr(result, "__await__"):
                await result
            return
        except Exception as exc:
            logger.debug("browser-use session %s failed during reset: %s", method_name, exc)


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
                    "Intelligent browser discovery via browser-use with persistent session reuse "
                    "and structured URL/title/text/action traces for ingest. "
                    "Playwright remains the default deterministic backend."
                ),
                "installable": False,
            }
        return {
            "id": self.id,
            "name": self.name,
            "kind": "optional",
            "available": False,
            "status": "missing",
            "detail": (
                "Adapter is integrated. Use Install now on the Tools page to install the MIT browser-use "
                "package (browser-use[core] plus Playwright Chromium). Playwright stays the default; "
                "Jarvis falls back to browser and web_fetch until this worker is ready."
            ),
            "installable": True,
            "install_worker_id": self.id,
            "install_hint": "Install now on Tools runs the RFC-0090 allowlisted pip install for browser-use.",
        }

    async def run(
        self,
        goal: str,
        url: str | None = None,
        settings: AppSettings | None = None,
        *,
        skip_permission_check: bool = False,
    ):
        from ..tools.base import ToolResult

        global _SESSION_REUSED
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
        _SESSION_REUSED = False
        task = cleaned_goal
        if cleaned_url and cleaned_url not in task:
            task = f"{task}\nStart at: {cleaned_url}"
        try:
            history = await self._invoke(task, current, start_url=cleaned_url)
        except Exception as exc:
            await reset_browser_use_session_async()
            return ToolResult(
                False,
                "",
                error=f"Browser Use failed: {exc}. Fall back to the Playwright browser tool.",
            )
        structured = structured_payload_from_history(history, start_url=cleaned_url)
        output = format_browser_use_output(structured)
        data = browser_use_tool_result_data(
            goal=cleaned_goal,
            structured=structured,
            start_url=cleaned_url,
            session_reused=_SESSION_REUSED,
        )
        return ToolResult(True, output, data=data)

    def _browser_session_class(self) -> Any:
        try:
            from browser_use import BrowserSession

            return BrowserSession
        except ImportError:
            from browser_use.browser.session import BrowserSession  # type: ignore[attr-defined]

            return BrowserSession

    def _build_browser_session(self, settings: AppSettings) -> Any:
        BrowserSession = self._browser_session_class()
        profile_dir = data_dir() / "browser-use-profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        headless = bool(settings.browser.headless)
        kwargs: dict[str, Any] = {"headless": headless, "user_data_dir": str(profile_dir)}
        try:
            from browser_use import BrowserProfile

            profile = BrowserProfile(
                headless=headless,
                keep_alive=True,
                user_data_dir=str(profile_dir),
            )
            return BrowserSession(browser_profile=profile)
        except (ImportError, TypeError):
            pass
        try:
            return BrowserSession(**kwargs, keep_alive=True)
        except TypeError:
            try:
                return BrowserSession(**kwargs)
            except TypeError:
                return BrowserSession(headless=headless)

    async def _shared_browser_session(self, settings: AppSettings) -> Any | None:
        global _BROWSER_SESSION, _SESSION_STARTED, _SESSION_REUSED
        async with _SESSION_LOCK:
            if _BROWSER_SESSION is not None:
                _SESSION_REUSED = True
                session = _BROWSER_SESSION
            else:
                try:
                    session = self._build_browser_session(settings)
                except ImportError:
                    return None
                _BROWSER_SESSION = session
                _SESSION_REUSED = False
                _SESSION_STARTED = False

        if session is None:
            return None
        if not _SESSION_STARTED and hasattr(session, "start"):
            start = session.start
            try:
                started = start()
                if hasattr(started, "__await__"):
                    await started
                async with _SESSION_LOCK:
                    _SESSION_STARTED = True
            except Exception as exc:
                await reset_browser_use_session_async()
                raise RuntimeError(f"Browser Use session failed to start: {exc}") from exc
        return session

    def _agent_kwargs(
        self,
        task: str,
        settings: AppSettings,
        browser_session: Any | None,
        *,
        start_url: str | None,
    ) -> dict[str, Any]:
        llm = local_chat_openai_for_browser_use(settings)
        kwargs: dict[str, Any] = {
            "task": task,
            "llm": llm,
            "use_vision": False,
            "max_steps": _DEFAULT_MAX_STEPS,
            "directly_open_url": start_url is None,
        }
        if browser_session is not None:
            kwargs["browser"] = browser_session
        if start_url:
            kwargs["initial_actions"] = [{"navigate": {"url": start_url, "new_tab": False}}]
        kwargs["extend_system_message"] = (
            "Jarvis is the supervisor. Return concise plain-text results suitable for ingest. "
            f"Use the local model ({local_browser_use_model(settings)}) via Jarvis inference only."
        )
        return kwargs

    async def _invoke(self, task: str, settings: AppSettings, *, start_url: str | None = None) -> Any:
        from browser_use import Agent

        browser_session = await self._shared_browser_session(settings)
        agent_kwargs = self._agent_kwargs(task, settings, browser_session, start_url=start_url)
        try:
            agent = Agent(**agent_kwargs)
        except TypeError:
            agent_kwargs.pop("extend_system_message", None)
            agent_kwargs.pop("initial_actions", None)
            agent_kwargs["use_vision"] = False
            agent = Agent(**agent_kwargs)

        result = agent.run()
        if hasattr(result, "__await__"):
            result = await result
        return result


# Re-export structured helpers for tests and ingest callers.
from .browser_structured import browser_use_ingest_payload, browser_use_tool_result_data  # noqa: E402

__all__ = [
    "BrowserUseBackend",
    "DEFAULT_BROWSER_BACKEND",
    "browser_use_ingest_payload",
    "browser_use_tool_result_data",
    "format_browser_use_output",
    "network_permission_block",
    "playwright_is_default",
    "reset_browser_use_session",
    "reset_browser_use_session_async",
    "structured_payload_from_history",
]
