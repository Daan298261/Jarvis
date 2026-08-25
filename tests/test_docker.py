from app.tools.browser import BrowserTool
from app.tools import browser as browser_mod
from app.tools.docker_tools import DockerTool


async def test_docker_run_requires_an_image_even_when_docker_is_missing():
    result = await DockerTool().execute(action="run", args="-it")
    assert result.success is False
    assert "image" in (result.error or "").lower()


async def test_browser_close_clears_pages_without_launching():
    browser_mod._pages = [object()]
    browser_mod._page = object()
    browser_mod._browser = object()
    browser_mod._context = None
    browser_mod._playwright = None
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="close")
    assert result.success
    assert browser_mod._pages == []
    assert browser_mod._page is None
    assert browser_mod._browser is None
    assert "closed" in result.output.lower()
