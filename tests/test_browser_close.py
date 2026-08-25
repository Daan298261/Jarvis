import pytest

from app.tools import browser as browser_mod
from app.tools.browser import BrowserTool


@pytest.mark.asyncio
async def test_browser_close_clears_pages_without_launching(monkeypatch):
    launched = []

    async def boom(_headless: bool):
        launched.append(True)
        raise AssertionError("close must not launch Chromium")

    monkeypatch.setattr(browser_mod, "_ensure_page", boom)
    browser_mod._pages = [object()]
    browser_mod._page = object()
    browser_mod._context = None
    browser_mod._browser = None
    browser_mod._playwright = None

    result = await BrowserTool(lambda: {"browser": {"headless": True}}).execute(action="close")
    assert result.success is True
    assert "closed" in result.output.lower()
    assert browser_mod._pages == []
    assert browser_mod._page is None
    assert launched == []
