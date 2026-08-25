from app.tools.browser import BrowserTool
from app.tools.docker_tools import DockerTool


async def test_docker_run_logs_inspect_require_targets():
    tool = DockerTool()
    run = await tool.execute(action="run")
    assert run.success is False
    assert "image" in (run.error or "").lower()
    logs = await tool.execute(action="logs")
    assert logs.success is False
    assert "container" in (logs.error or "").lower()
    inspect = await tool.execute(action="inspect")
    assert inspect.success is False
    assert "container" in (inspect.error or "").lower() or "image" in (inspect.error or "").lower()


async def test_browser_close_does_not_launch_chromium():
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="close")
    assert result.success is True
    assert "not running" in result.output.lower() or "closed" in result.output.lower()
