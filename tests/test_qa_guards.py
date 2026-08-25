import sys

from app.hardware import _office_installed
from app.tools.browser import BrowserTool
from app.tools.docker_tools import DockerTool
from app.tools.python_exec import PythonTool
from app.tools.terminal import TerminalTool


def test_python_tool_uses_current_interpreter():
    assert PythonTool()._python_bin(None) == sys.executable


async def test_docker_requires_targets_before_invoking_cli(monkeypatch):
    monkeypatch.setattr("app.tools.docker_tools.shutil.which", lambda name: "/usr/bin/docker")
    tool = DockerTool()
    run = await tool.execute(action="run")
    assert run.success is False
    assert "image is required" in run.error
    logs = await tool.execute(action="logs")
    assert "container is required" in logs.error
    inspect = await tool.execute(action="inspect")
    assert "container or image is required" in inspect.error


async def test_browser_close_does_not_launch_and_clears_state():
    import app.tools.browser as browser_mod

    browser_mod._page = object()
    browser_mod._browser = object()
    browser_mod._pages = [1]
    browser_mod._context = None
    browser_mod._playwright = None
    result = await BrowserTool(lambda: {}).execute(action="close")
    assert result.success
    assert browser_mod._page is None
    assert browser_mod._browser is None
    assert browser_mod._pages == []


async def test_terminal_default_shell_is_usable_on_linux(tmp_path):
    tool = TerminalTool()
    result = await tool.execute(action="run", command="echo qa-ok", working_directory=str(tmp_path), timeout_seconds=10)
    assert result.success, result.error
    assert "qa-ok" in result.output


def test_office_probe_does_not_claim_office_on_linux():
    assert _office_installed() is False
