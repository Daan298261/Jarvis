from app.tools.browser import (
    CLICK_ROLES,
    BrowserTool,
    browser_is_running,
    reset_browser_state_for_tests,
)
from app.tools.docker_tools import DockerTool


def test_click_roles_cover_common_page_controls():
    assert "button" in CLICK_ROLES
    assert "link" in CLICK_ROLES
    assert CLICK_ROLES[0] == "button"


async def test_browser_close_does_not_launch_when_idle():
    reset_browser_state_for_tests()
    assert browser_is_running() is False
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="close")
    assert result.success
    assert "not running" in result.output.lower()
    assert browser_is_running() is False


async def test_browser_open_requires_url_without_launching():
    reset_browser_state_for_tests()
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="open")
    assert result.success is False
    assert "url is required" in (result.error or "")
    assert browser_is_running() is False


async def test_browser_title_requires_an_open_page():
    reset_browser_state_for_tests()
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="title")
    assert result.success is False
    assert "open" in (result.error or "").lower()
    assert browser_is_running() is False


async def test_docker_run_logs_inspect_require_targets_without_docker():
    tool = DockerTool()
    run = await tool.execute(action="run")
    assert run.success is False
    assert "image is required" in (run.error or "")

    logs = await tool.execute(action="logs")
    assert logs.success is False
    assert "container is required" in (logs.error or "")

    inspect = await tool.execute(action="inspect")
    assert inspect.success is False
    assert "container or image is required" in (inspect.error or "")
