from app.tools.browser import BrowserTool
from app.tools.docker_tools import DockerTool
from app.tools.terminal import default_shell


async def test_docker_run_logs_inspect_require_targets():
    tool = DockerTool()
    run = await tool.execute(action="run")
    assert run.success is False
    assert "image is required" in (run.error or "")
    logs = await tool.execute(action="logs")
    assert logs.success is False
    assert "container is required" in (logs.error or "")
    inspect = await tool.execute(action="inspect")
    assert inspect.success is False
    assert "container or image" in (inspect.error or "")


async def test_browser_close_does_not_launch_chromium():
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    closed = await tool.execute(action="close")
    assert closed.success is True
    assert "not running" in closed.output.lower() or "closed" in closed.output.lower()


def test_default_shell_is_native():
    shell = default_shell()
    assert shell in {"bash", "python", "powershell"}
    import sys

    if sys.platform != "win32":
        assert shell != "powershell"
