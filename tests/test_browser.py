from types import SimpleNamespace

import app.tools.browser as browser_mod
from app.tools.browser import BrowserTool, _click_named


class _FailThenSucceed:
    def __init__(self) -> None:
        self.calls = 0

    async def goto(self, url, wait_until=None, timeout=None):
        self.calls += 1
        if self.calls < 2:
            raise RuntimeError("transient navigation error")
        self.url = url

    async def wait_for_load_state(self, state, timeout=None):
        return None

    async def title(self):
        return "Example Domain"


class _NamedLocator:
    def __init__(self, role: str, should_fail: bool) -> None:
        self.role = role
        self.should_fail = should_fail
        self.first = self

    async def click(self, timeout=None):
        if self.should_fail:
            raise RuntimeError(f"{self.role} missing")


class _NamedPage:
    def __init__(self) -> None:
        self.clicked_role = None

    def get_by_role(self, role, name=None):
        fail = role != "link"
        locator = _NamedLocator(role, fail)
        if role == "link":
            async def click(timeout=None):
                self.clicked_role = role
            locator.click = click  # type: ignore[method-assign]
        return locator

    def get_by_label(self, name):
        return _NamedLocator("label", True)

    def get_by_placeholder(self, name):
        return _NamedLocator("placeholder", True)

    def get_by_text(self, name, exact=False):
        return _NamedLocator("text", True)


async def test_close_and_missing_url_do_not_launch(monkeypatch):
    launched = {"count": 0}

    async def boom(headless: bool):
        launched["count"] += 1
        raise AssertionError("Chromium should not launch")

    monkeypatch.setattr(browser_mod, "_ensure_page", boom)
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    closed = await tool.execute(action="close")
    assert closed.success
    assert "closed" in closed.output.lower()
    missing = await tool.execute(action="open")
    assert missing.success is False
    assert "url is required" in missing.error
    assert launched["count"] == 0


async def test_open_retries_transient_navigation(monkeypatch):
    page = _FailThenSucceed()

    async def fake_ensure(headless: bool):
        return page

    monkeypatch.setattr(browser_mod, "_ensure_page", fake_ensure)
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="open", url="https://example.com")
    assert result.success, result.error
    assert "Example Domain" in result.output
    assert page.calls == 2


async def test_named_click_falls_through_roles():
    page = _NamedPage()
    await _click_named(page, "More information")
    assert page.clicked_role == "link"
