import app.tools.browser as browser_mod
from app.tools.browser import BrowserTool


async def test_browser_close_without_session_does_not_launch():
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="close")
    assert result.success is True
    assert "not open" in result.output.lower()
    assert browser_mod._page is None
    assert browser_mod._context is None
    assert browser_mod._pages == []
