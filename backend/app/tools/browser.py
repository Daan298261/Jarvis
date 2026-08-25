from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

from ..config import data_dir
from .base import RiskLevel, Tool, ToolResult
from .safety import resolve_allowed_path

_lock = asyncio.Lock()
_playwright = None
_browser = None
_context = None
_page = None
_pages: list[Any] = []
_headless_used: bool | None = None


def _closed_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "target closed",
            "has been closed",
            "browser has been closed",
            "connection closed",
            "context or browser has been closed",
            "page closed",
        )
    )


async def _page_alive() -> bool:
    if _page is None:
        return False
    try:
        return not _page.is_closed()
    except Exception:
        return False


async def reset_browser() -> None:
    async with _lock:
        await _shutdown_unlocked()


async def _shutdown_unlocked() -> None:
    global _playwright, _browser, _context, _page, _pages, _headless_used
    try:
        if _context:
            await _context.close()
    except Exception:
        pass
    try:
        if _browser:
            await _browser.close()
    except Exception:
        pass
    try:
        if _playwright:
            await _playwright.stop()
    except Exception:
        pass
    _playwright = None
    _browser = None
    _context = None
    _page = None
    _pages = []
    _headless_used = None


async def _ensure_page(headless: bool):
    global _playwright, _browser, _context, _page, _pages, _headless_used
    if await _page_alive() and _headless_used is not None and bool(_headless_used) == bool(headless):
        return _page
    if _context or _playwright or _browser:
        await _shutdown_unlocked()
    from playwright.async_api import async_playwright

    _playwright = await async_playwright().start()
    user_dir = data_dir() / "browser-profile"
    user_dir.mkdir(parents=True, exist_ok=True)
    launch_kwargs: dict[str, Any] = {
        "headless": headless,
        "accept_downloads": True,
        "viewport": {"width": 1400, "height": 900},
    }
    try:
        _context = await _playwright.chromium.launch_persistent_context(str(user_dir), **launch_kwargs)
    except Exception:
        _browser = await _playwright.chromium.launch(headless=headless)
        _context = await _browser.new_context(
            accept_downloads=True,
            viewport={"width": 1400, "height": 900},
        )
    _pages = list(_context.pages) or [await _context.new_page()]
    _page = _pages[0]
    _headless_used = bool(headless)
    return _page


async def _goto(page, url: str, timeout: int = 45000, headless: bool = True):
    last: BaseException | None = None
    current = page
    for attempt in range(3):
        try:
            await current.goto(url, wait_until="domcontentloaded", timeout=timeout)
            try:
                await current.wait_for_load_state("load", timeout=8000)
            except Exception:
                pass
            title = (await current.title() or "").strip()
            if not title:
                await current.wait_for_timeout(400)
                title = (await current.title() or "").strip()
            if not title:
                title = str(await current.evaluate("() => document.title") or "").strip()
            return current, title
        except Exception as exc:
            last = exc
            if _closed_error(exc):
                await _shutdown_unlocked()
                current = await _ensure_page(headless)
            await asyncio.sleep(0.5 * (attempt + 1))
    raise last or RuntimeError(f"Failed to open {url}")


async def _click(page, name: str | None, selector: str | None) -> None:
    if selector:
        await page.locator(selector).first.click(timeout=10000)
        return
    if not name:
        raise ValueError("Provide name or selector")
    locators = [
        page.get_by_role("link", name=name),
        page.get_by_role("button", name=name),
        page.get_by_label(name),
        page.get_by_text(name, exact=False),
    ]
    last: BaseException | None = None
    for locator in locators:
        try:
            await locator.first.click(timeout=4000)
            return
        except Exception as exc:
            last = exc
    raise last or RuntimeError(f"No clickable control named {name!r}")


async def capture_page_title(url: str, headless: bool = True) -> tuple[str, str]:
    """Open a URL with retries and return (title, final_url)."""
    timeout_ms = 30000
    try:
        from ..config import load_settings

        timeout_ms = max(1000, min(int(load_settings().browser.timeout_ms), 300000))
    except Exception:
        timeout_ms = 30000
    async with _lock:
        page = await _ensure_page(headless)
        page, title = await _goto(page, url, timeout=timeout_ms, headless=headless)
        return title, page.url


class BrowserTool(Tool):
    name = "browser"
    description = (
        "Automate Chromium with Playwright using accessibility snapshots rather than coordinates. "
        "Actions: open, title, save_title, snapshot, click, type, fill, press, evaluate, screenshot, tabs, download, upload, close. "
        "For 'save the page title to a file', use save_title with url and path. "
        "Use snapshot first, then click by accessible name, link, or CSS selector. "
        "If Playwright fails, the agent should fall back to web_fetch."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "open",
                    "title",
                    "save_title",
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
                ],
            },
            "url": {"type": "string"},
            "selector": {"type": "string"},
            "name": {"type": "string", "description": "Accessible name for click/type"},
            "text": {"type": "string"},
            "key": {"type": "string"},
            "script": {"type": "string"},
            "path": {"type": "string"},
            "headless": {"type": "boolean"},
        },
        "required": ["action"],
    }

    def __init__(self, context_getter) -> None:
        self.context_getter = context_getter

    def _headless(self, kwargs: dict[str, Any]) -> bool:
        headless = kwargs.get("headless")
        if headless is None:
            settings = self.context_getter() or {}
            headless = bool((settings.get("browser") or {}).get("headless", False))
        return bool(headless)

    def _timeout_ms(self, kwargs: dict[str, Any]) -> int:
        raw = kwargs.get("timeout_ms")
        if raw is None:
            settings = self.context_getter() or {}
            raw = (settings.get("browser") or {}).get("timeout_ms", 30000)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 30000
        return max(1000, min(value, 300000))

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        headless = self._headless(kwargs)
        timeout_ms = self._timeout_ms(kwargs)
        async with _lock:
            try:
                return await self._run(action, kwargs, headless, timeout_ms)
            except Exception as exc:
                if _closed_error(exc):
                    await _shutdown_unlocked()
                    try:
                        return await self._run(action, kwargs, headless, timeout_ms)
                    except Exception as retry_exc:
                        return ToolResult(False, "", error=str(retry_exc))
                return ToolResult(False, "", error=str(exc))

    async def _run(self, action: str | None, kwargs: dict[str, Any], headless: bool, timeout_ms: int = 30000) -> ToolResult:
        page = await _ensure_page(headless)
        if action == "open":
            url = kwargs.get("url")
            if not url:
                return ToolResult(False, "", error="url is required")
            page, title = await _goto(page, url, timeout=timeout_ms, headless=headless)
            return ToolResult(True, f"Opened {page.url}\ntitle={title}", data={"title": title, "url": page.url})
        if action == "title":
            url = kwargs.get("url")
            if url:
                page, title = await _goto(page, url, timeout=timeout_ms, headless=headless)
            else:
                title = (await page.title() or "").strip()
                if not title:
                    title = str(await page.evaluate("() => document.title") or "").strip()
            if not title:
                return ToolResult(False, "", error="Page title was empty")
            return ToolResult(True, f"title={title}\nurl={page.url}", data={"title": title, "url": page.url})
        if action == "save_title":
            url = kwargs.get("url")
            dest = kwargs.get("path")
            if not dest:
                return ToolResult(False, "", error="path is required")
            allowed = list((self.context_getter() or {}).get("allowed_directories") or [])
            out = resolve_allowed_path(dest, allowed)
            if url:
                page, title = await _goto(page, url, timeout=timeout_ms, headless=headless)
            else:
                title = (await page.title() or "").strip()
            if not title:
                title = str(await page.evaluate("() => document.title") or "").strip()
            if not title:
                return ToolResult(False, "", error="Page title was empty")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(title + "\n", encoding="utf-8")
            return ToolResult(
                True,
                f"Wrote title {title!r} to {out}",
                data={"title": title, "url": page.url, "path": str(out)},
            )
        if action == "snapshot":
            title = await page.title()
            a11y = await page.locator("body").inner_text()
            truncated = a11y[:8000]
            return ToolResult(True, f"URL: {page.url}\nTitle: {title}\n\n{truncated}", data={"title": title, "url": page.url})
        if action == "click":
            await _click(page, kwargs.get("name"), kwargs.get("selector"))
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
                data={"path": str(out), "attach_image": str(out), "image_base64": encoded[:80] + "..."},
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
            return ToolResult(True, f"Downloaded to {dest}", data={"path": str(dest)})
        if action == "upload":
            await page.locator(kwargs.get("selector") or "input[type=file]").set_input_files(kwargs.get("path"))
            return ToolResult(True, "Uploaded file")
        if action == "close":
            await _shutdown_unlocked()
            return ToolResult(True, "Browser closed")
        return ToolResult(False, "", error=f"Unknown action {action}")
