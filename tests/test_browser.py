from app.tools import browser as browser_mod
from app.tools.browser import BrowserTool


async def test_browser_close_resets_page_list():
    browser_mod._page = object()
    browser_mod._pages = [object()]
    browser_mod._context = None
    browser_mod._playwright = None
    browser_mod._browser = None
    result = await BrowserTool(lambda: {"browser": {"headless": True}}).execute(action="close")
    assert result.success is True
    assert browser_mod._page is None
    assert browser_mod._pages == []
    assert browser_mod._browser is None
