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
        settings = self.context_getter()
        headless = kwargs.get("headless")
        if headless is None:
            headless = bool((settings.get("browser") or {}).get("headless", False))
        async with _lock:
            try:
                if action == "close":
                    global _playwright, _browser, _context, _page, _pages
                    if _page is None and _context is None:
                        _pages = []
                        return ToolResult(True, "Browser was not open")
                    if _context:
                        await _context.close()
                    if _playwright:
                        await _playwright.stop()
                    _context = None
                    _playwright = None
                    _page = None
                    _browser = None
                    _pages = []
                    return ToolResult(True, "Browser closed")
                page = await _ensure_page(bool(headless))
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
                    return ToolResult(True, f"Typed into field")
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
                    return ToolResult(True, f"Downloaded to {dest}")
                if action == "upload":
                    await page.locator(kwargs.get("selector") or "input[type=file]").set_input_files(kwargs.get("path"))
                    return ToolResult(True, "Uploaded file")
                return ToolResult(False, "", error=f"Unknown action {action}")
            except Exception as exc:
                return ToolResult(False, "", error=str(exc))
