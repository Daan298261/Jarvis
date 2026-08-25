from __future__ import annotations

from typing import Any

from ..config import AppSettings, load_settings
from .base import RiskLevel, Tool, ToolResult

_lock = asyncio.Lock()
_playwright = None
_browser = None
_context = None
_page = None
_pages: list[Any] = []

CLICK_ROLES = ("button", "link", "tab", "menuitem", "checkbox", "radio", "option")
PAGE_ACTIONS = {
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
    "title",
    "wait",
}


def browser_is_running() -> bool:
    return _page is not None or _context is not None or _playwright is not None


def reset_browser_state_for_tests() -> None:
    global _playwright, _browser, _context, _page, _pages
    _playwright = None
    _browser = None
    _context = None
    _page = None
    _pages = []


async def _ensure_page(headless: bool):
    global _playwright, _browser, _context, _page, _pages
    if _page:
        return _page
    from playwright.async_api import async_playwright

    _playwright = await async_playwright().start()
    user_dir = data_dir() / "browser-profile"
    user_dir.mkdir(parents=True, exist_ok=True)
    _context = await _playwright.chromium.launch_persistent_context(
        str(user_dir),
        headless=headless,
        accept_downloads=True,
        viewport={"width": 1400, "height": 900},
    )
    _pages = list(_context.pages) or [await _context.new_page()]
    _page = _pages[0]
    return _page


async def _close_browser() -> ToolResult:
    global _playwright, _browser, _context, _page, _pages
    if not browser_is_running():
        return ToolResult(True, "Browser was not running")
    if _context:
        await _context.close()
    if _playwright:
        await _playwright.stop()
    _context = None
    _playwright = None
    _browser = None
    _page = None
    _pages = []
    return ToolResult(True, "Browser closed")


async def _open_with_retry(page: Any, url: str) -> Any:
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
            return page
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return page


async def _click_by_name(page: Any, name: str) -> str:
    last_error: Exception | None = None
    for role in CLICK_ROLES:
        try:
            locator = page.get_by_role(role, name=name)
            if await locator.count() > 0:
                await locator.first.click(timeout=8000)
                return f"role:{role}"
        except Exception as exc:
            last_error = exc
    try:
        locator = page.get_by_text(name, exact=True)
        if await locator.count() > 0:
            await locator.first.click(timeout=8000)
            return "text"
    except Exception as exc:
        last_error = exc
    raise last_error or RuntimeError(f"No clickable control named {name!r}")


def _title_payload(url: str, title: str) -> str:
    return f"URL: {url}\nTitle: {title}\ntitle={title}"


class BrowserTool(Tool):
    name = "browser"
    description = (
        "Automate Chromium with Playwright using accessibility names rather than coordinates. "
        "Actions: open, title, snapshot, wait, click, type, fill, press, evaluate, screenshot, "
        "tabs, download, upload, close. After open, read title= from the result. "
        "Click by accessible name (button/link/tab) or CSS selector. close does nothing if no browser is running."
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
                    "snapshot",
                    "wait",
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
            "task": {"type": "string", "description": "Natural-language browser task for Browser Use"},
            "key": {"type": "string"},
            "script": {"type": "string"},
            "path": {"type": "string"},
            "headless": {"type": "boolean"},
            "timeout_seconds": {"type": "integer", "default": 15},
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
        settings = self.context_getter()
        headless = kwargs.get("headless")
        if headless is None:
            headless = bool((settings.get("browser") or {}).get("headless", False))
        async with _lock:
            try:
                if action == "close":
                    return await _close_browser()
                if action == "open":
                    url = kwargs.get("url")
                    if not url:
                        return ToolResult(False, "", error="url is required")
                    page = await _ensure_page(bool(headless))
                    await _open_with_retry(page, url)
                    title = await page.title()
                    return ToolResult(
                        True,
                        f"Opened {page.url}\n{_title_payload(page.url, title)}",
                        data={"url": page.url, "title": title},
                    )
                if action in PAGE_ACTIONS and not browser_is_running():
                    return ToolResult(False, "", error="No page is open. Use action=open first.")
                page = await _ensure_page(bool(headless))
                if action == "title":
                    title = await page.title()
                    return ToolResult(
                        True,
                        _title_payload(page.url, title),
                        data={"url": page.url, "title": title},
                    )
                if action == "wait":
                    timeout_ms = int(kwargs.get("timeout_seconds") or 15) * 1000
                    if kwargs.get("url"):
                        await page.wait_for_url(kwargs["url"], timeout=timeout_ms)
                    if kwargs.get("selector"):
                        await page.wait_for_selector(kwargs["selector"], timeout=timeout_ms)
                    if kwargs.get("text"):
                        needle = str(kwargs["text"]).lower().replace("'", "\\'")
                        await page.wait_for_function(
                            f"() => document.title.toLowerCase().includes('{needle}')",
                            timeout=timeout_ms,
                        )
                    title = await page.title()
                    return ToolResult(
                        True,
                        f"Wait complete.\n{_title_payload(page.url, title)}",
                        data={"url": page.url, "title": title},
                    )
                if action == "snapshot":
                    title = await page.title()
                    a11y = await page.locator("body").inner_text()
                    truncated = a11y[:8000]
                    return ToolResult(
                        True,
                        f"{_title_payload(page.url, title)}\n\n{truncated}",
                        data={"url": page.url, "title": title},
                    )
                if action == "click":
                    method = "selector"
                    if kwargs.get("name"):
                        method = await _click_by_name(page, kwargs["name"])
                    elif kwargs.get("selector"):
                        await page.locator(kwargs["selector"]).first.click(timeout=10000)
                    else:
                        return ToolResult(False, "", error="Provide name or selector")
                    return ToolResult(True, f"Clicked via {method}. URL now {page.url}", data={"method": method})
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
                return ToolResult(False, "", error=f"Unknown action {action}")
            except Exception as exc:
                return ToolResult(False, "", error=str(exc))
