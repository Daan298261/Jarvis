from __future__ import annotations

import asyncio
import base64
import importlib.util
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..config import AppSettings, data_dir
from .base import ToolResult

PLAYWRIGHT_ALIASES = {"playwright", "default", "deterministic"}
BROWSER_USE_ALIASES = {"browser-use", "browser_use", "browseruse", "intelligent"}


def browser_use_available() -> bool:
    return importlib.util.find_spec("browser_use") is not None


class BrowserBackend(ABC):
    """Execution backend for the browser tool.

    Playwright is the deterministic default. Browser Use is an optional
    intelligent worker for discovery-style tasks.
    """

    name = "abstract"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    @classmethod
    def is_available(cls) -> bool:
        return True

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "available": self.is_available(),
        }

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError


class PlaywrightBackend(BrowserBackend):
    name = "playwright"

    def __init__(self, settings: AppSettings) -> None:
        super().__init__(settings)
        self._lock = asyncio.Lock()
        self._playwright = None
        self._context = None
        self._page = None

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("playwright") is not None

    async def _ensure_page(self, headless: bool):
        if self._page:
            return self._page
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        user_dir = data_dir() / "browser-profile"
        user_dir.mkdir(parents=True, exist_ok=True)
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(user_dir),
            headless=headless,
            accept_downloads=True,
            viewport={"width": 1400, "height": 900},
        )
        pages = list(self._context.pages) or [await self._context.new_page()]
        self._page = pages[0]
        return self._page

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        if action == "task":
            return ToolResult(
                False,
                "",
                error=(
                    "The 'task' action requires the Browser Use backend. "
                    "Set browser.backend to 'browser-use' or pass backend='browser-use'."
                ),
            )
        headless = kwargs.get("headless")
        if headless is None:
            headless = bool(self.settings.browser.headless)
        async with self._lock:
            try:
                page = await self._ensure_page(bool(headless))
                if action == "open":
                    url = kwargs.get("url")
                    if not url:
                        return ToolResult(False, "", error="url is required")
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    return ToolResult(True, f"Opened {page.url}\ntitle={await page.title()}")
                if action == "snapshot":
                    title = await page.title()
                    a11y = await page.locator("body").inner_text()
                    truncated = a11y[:8000]
                    return ToolResult(True, f"URL: {page.url}\nTitle: {title}\n\n{truncated}")
                if action == "click":
                    if kwargs.get("name"):
                        await page.get_by_role("button", name=kwargs["name"]).first.click(timeout=10000)
                    elif kwargs.get("selector"):
                        await page.locator(kwargs["selector"]).first.click(timeout=10000)
                    else:
                        return ToolResult(False, "", error="Provide name or selector")
                    return ToolResult(True, f"Clicked. URL now {page.url}")
                if action in {"type", "fill"}:
                    text = kwargs.get("text") or ""
                    if kwargs.get("selector"):
                        locator = page.locator(kwargs["selector"]).first
                    elif kwargs.get("name"):
                        locator = page.get_by_label(kwargs["name"]).first
                    else:
                        locator = page.locator("input, textarea, [contenteditable=true]").first
                    if action == "fill":
                        await locator.fill(text)
                    else:
                        await locator.click()
                        await locator.type(text)
                    return ToolResult(True, "Typed into field")
                if action == "press":
                    await page.keyboard.press(kwargs.get("key") or "Enter")
                    return ToolResult(True, f"Pressed {kwargs.get('key')}")
                if action == "evaluate":
                    result = await page.evaluate(kwargs.get("script") or "() => document.title")
                    return ToolResult(True, str(result))
                if action == "screenshot":
                    out = Path(kwargs.get("path") or (data_dir() / "screenshots" / "browser.png"))
                    out.parent.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(out), full_page=False)
                    encoded = base64.b64encode(out.read_bytes()).decode("ascii")
                    return ToolResult(
                        True,
                        f"Saved screenshot to {out}",
                        data={"path": str(out), "image_base64": encoded[:80] + "..."},
                    )
                if action == "tabs":
                    pages = page.context.pages
                    listing = "\n".join(f"{i}: {p.url}" for i, p in enumerate(pages))
                    return ToolResult(True, listing or "No tabs")
                if action == "download":
                    async with page.expect_download(timeout=30000) as download_info:
                        if kwargs.get("selector"):
                            await page.locator(kwargs["selector"]).first.click()
                    download = await download_info.value
                    dest = Path(kwargs.get("path") or (data_dir() / "downloads" / download.suggested_filename))
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    await download.save_as(str(dest))
                    return ToolResult(True, f"Downloaded to {dest}")
                if action == "upload":
                    await page.locator(kwargs.get("selector") or "input[type=file]").set_input_files(kwargs.get("path"))
                    return ToolResult(True, "Uploaded file")
                if action == "close":
                    if self._context:
                        await self._context.close()
                    if self._playwright:
                        await self._playwright.stop()
                    self._context = None
                    self._playwright = None
                    self._page = None
                    return ToolResult(True, "Browser closed")
                return ToolResult(False, "", error=f"Unknown action {action}")
            except Exception as exc:
                return ToolResult(False, "", error=str(exc))


class BrowserUseBackend(BrowserBackend):
    name = "browser-use"

    @classmethod
    def is_available(cls) -> bool:
        return browser_use_available()

    def _build_llm(self):
        browser_cfg = self.settings.browser
        model = browser_cfg.browser_use_model or "Qwen3.5-27B"
        inference = self.settings.inference
        base_url = f"http://{inference.host}:{inference.port}/v1"
        try:
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=model,
                base_url=base_url,
                api_key="jarvis-local",
                temperature=0.2,
            )
        except ImportError:
            from browser_use import ChatBrowserUse

            return ChatBrowserUse(model=model)

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        if action != "task":
            return ToolResult(
                False,
                "",
                error=(
                    f"Browser Use only supports the 'task' action for natural-language browser work. "
                    f"Use Playwright for deterministic actions like {action!r}."
                ),
            )
        if not self.is_available():
            return ToolResult(
                False,
                "",
                error="Browser Use is not installed. Install with: pip install browser-use",
            )
        task = kwargs.get("task") or kwargs.get("text")
        if not task:
            return ToolResult(False, "", error="task is required for Browser Use")
        headless = kwargs.get("headless")
        if headless is None:
            headless = bool(self.settings.browser.headless)
        max_steps = int(kwargs.get("max_steps") or 50)
        try:
            from browser_use import Agent, Browser

            browser = Browser(headless=bool(headless))
            agent = Agent(
                task=task,
                llm=self._build_llm(),
                browser=browser,
                use_vision=bool(kwargs.get("use_vision", True)),
            )
            history = await agent.run(max_steps=max_steps)
            final = ""
            if hasattr(history, "final_result"):
                final = history.final_result() or ""
            elif hasattr(history, "is_done") and history.is_done():
                final = str(history)
            success = bool(getattr(history, "is_successful", lambda: True)())
            urls = []
            if hasattr(history, "urls"):
                urls = list(history.urls() or [])
            output = final or "Browser Use task finished."
            if urls:
                output += "\n\nURLs visited:\n" + "\n".join(f"- {url}" for url in urls)
            return ToolResult(success, output, data={"backend": self.name, "urls": urls})
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))


def resolve_browser_backend(settings: AppSettings, requested: str | None = None) -> BrowserBackend:
    name = (requested or settings.browser.backend or "playwright").strip().lower()
    if name in BROWSER_USE_ALIASES:
        return BrowserUseBackend(settings)
    return PlaywrightBackend(settings)


def browser_backend_snapshot(settings: AppSettings | None = None) -> list[dict[str, Any]]:
    settings = settings or AppSettings()
    backends: list[BrowserBackend] = [PlaywrightBackend(settings), BrowserUseBackend(settings)]
    return [backend.describe() for backend in backends]
