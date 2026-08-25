import pytest

from app.config import AppSettings
from app.tools.browser_backends import (
    BrowserUseBackend,
    PlaywrightBackend,
    browser_backend_snapshot,
    browser_use_available,
    resolve_browser_backend,
)


def _settings(**browser) -> AppSettings:
    base = {"backend": "playwright", "headless": True}
    base.update(browser)
    return AppSettings(browser=base)


def test_playwright_is_the_default_backend():
    backend = resolve_browser_backend(_settings())
    assert isinstance(backend, PlaywrightBackend)


@pytest.mark.parametrize("name", ["browser-use", "browser_use", "intelligent"])
def test_browser_use_aliases_resolve_to_browser_use_backend(name):
    backend = resolve_browser_backend(_settings(backend=name))
    assert isinstance(backend, BrowserUseBackend)


def test_explicit_backend_override_wins():
    backend = resolve_browser_backend(_settings(backend="playwright"), requested="browser-use")
    assert isinstance(backend, BrowserUseBackend)


@pytest.mark.asyncio
async def test_playwright_rejects_task_action_without_browser_use():
    backend = PlaywrightBackend(_settings())
    result = await backend.execute(action="task", task="Find the news")
    assert result.success is False
    assert "Browser Use" in result.error


@pytest.mark.asyncio
async def test_browser_use_rejects_deterministic_actions():
    backend = BrowserUseBackend(_settings())
    result = await backend.execute(action="click", selector="#submit")
    assert result.success is False
    assert "only supports the 'task' action" in result.error


@pytest.mark.asyncio
async def test_browser_use_requires_task_text():
    backend = BrowserUseBackend(_settings())
    result = await backend.execute(action="task")
    if browser_use_available():
        assert result.success is False
        assert "task is required" in result.error
    else:
        assert result.success is False
        assert "not installed" in result.error


def test_browser_backend_snapshot_lists_both_backends():
    snap = browser_backend_snapshot(_settings())
    names = {item["backend"] for item in snap}
    assert names == {"playwright", "browser-use"}
    playwright = next(item for item in snap if item["backend"] == "playwright")
    assert playwright["available"] is True
