import os
import sys

from app.hardware import _office_installed
from app.tools.browser import BrowserTool
from app.tools.docker_tools import DockerTool
from app.tools.git_tools import GitTool
from app.tools.python_exec import PythonTool
from app.tools.terminal import default_shell


async def test_docker_run_logs_inspect_require_targets():
    tool = DockerTool()
    run = await tool.execute(action="run")
    assert not run.success
    assert "image is required" in (run.error or "")
    logs = await tool.execute(action="logs")
    assert not logs.success
    assert "container is required" in (logs.error or "")
    inspect = await tool.execute(action="inspect")
    assert not inspect.success
    assert "container or image is required" in (inspect.error or "")


async def test_browser_close_and_open_without_url_do_not_launch():
    from app.tools import browser as browser_mod

    browser_mod._page = None
    browser_mod._context = None
    browser_mod._playwright = None
    browser_mod._pages = []
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    closed = await tool.execute(action="close")
    assert closed.success
    assert "not running" in closed.output.lower()
    missing = await tool.execute(action="open")
    assert not missing.success
    assert "url is required" in (missing.error or "")
    assert browser_mod._page is None
    assert browser_mod._playwright is None


def test_python_tool_uses_current_interpreter():
    tool = PythonTool()
    assert tool._python_bin(None) == sys.executable


def test_terminal_defaults_to_bash_on_linux():
    if os.name == "nt":
        assert default_shell() == "powershell"
    else:
        assert default_shell() == "bash"


def test_office_probe_is_false_on_linux_without_com():
    if os.name != "nt":
        assert _office_installed() is False


async def test_git_checkpoint_keeps_working_tree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tool = GitTool()
    init = await tool._git(["init"], str(repo))
    assert init.success, init.error
    await tool._git(["config", "user.email", "jarvis@test"], str(repo))
    await tool._git(["config", "user.name", "Jarvis"], str(repo))
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    await tool._git(["add", "tracked.txt"], str(repo))
    await tool._git(["commit", "-m", "base"], str(repo))
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    (repo / "extra.txt").write_text("new\n", encoding="utf-8")
    result = await tool.execute(action="checkpoint", path=str(repo))
    assert result.success, result.error
    assert "without changing the working tree" in result.output
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "dirty\n"
    assert (repo / "extra.txt").read_text(encoding="utf-8") == "new\n"
    status = await tool.execute(action="status", path=str(repo))
    assert "tracked.txt" in status.output
    assert "extra.txt" in status.output
    assert result.data["branch"].startswith("jarvis-checkpoint-")
