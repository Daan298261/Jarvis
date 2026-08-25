import platform
import subprocess
import sys
from pathlib import Path

from app.tools.browser import BrowserTool
from app.tools.docker_tools import DockerTool
from app.tools.git_tools import GitTool
from app.tools.office import OfficeTool, office_library_available
from app.tools.python_exec import PythonTool
from app.tools.terminal import TerminalTool, default_shell
from app.tools.web_fetch import WebFetchTool


async def test_docker_requires_targets_before_invoking_cli():
    tool = DockerTool()
    run = await tool.execute(action="run")
    assert run.success is False
    assert "image is required" in run.error
    logs = await tool.execute(action="logs")
    assert "container is required" in logs.error
    inspect = await tool.execute(action="inspect")
    assert "container or image is required" in inspect.error


async def test_office_info_does_not_require_com():
    tool = OfficeTool()
    result = await tool.execute(app="word", action="info")
    assert result.success
    assert "Office" in (result.output or result.error)
    if platform.system() != "Windows" and not office_library_available("word"):
        create = await tool.execute(app="word", action="create", destination="/tmp/no.docx")
        assert create.success is False
        assert "unavailable" in create.error.lower()


async def test_python_run_code_uses_current_interpreter():
    tool = PythonTool()
    result = await tool.execute(action="run_code", code="import sys; print(sys.executable)")
    assert result.success, result.error
    assert Path(sys.executable).name.split()[0] in result.output or sys.executable in result.output


def test_terminal_defaults_to_bash_off_windows():
    if platform.system() == "Windows":
        assert default_shell() == "powershell"
    else:
        assert default_shell() == "bash"


async def test_git_checkpoint_keeps_working_tree(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "jarvis@example.test"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Jarvis"], cwd=tmp_path, check=True, capture_output=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    tracked.write_text("dirty\n", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text("new\n", encoding="utf-8")

    result = await GitTool().execute(action="checkpoint", path=str(tmp_path))
    assert result.success, result.error
    assert "Working tree left unchanged" in result.output
    assert tracked.read_text(encoding="utf-8") == "dirty\n"
    assert (tmp_path / "untracked.txt").read_text(encoding="utf-8") == "new\n"
    branches = subprocess.run(["git", "branch"], cwd=tmp_path, check=True, capture_output=True, text=True)
    assert "jarvis-checkpoint-" in branches.stdout


async def test_browser_close_and_missing_url_do_not_launch(monkeypatch):
    called = []

    async def boom(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("chromium must not launch")

    monkeypatch.setattr("app.tools.browser._ensure_page", boom)
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    closed = await tool.execute(action="close")
    assert closed.success
    assert "not open" in closed.output
    missing = await tool.execute(action="open")
    assert missing.success is False
    assert "url is required" in missing.error
    assert called == []


async def test_web_fetch_rejects_file_urls():
    tool = WebFetchTool()
    empty = await tool.execute(url="")
    assert empty.success is False
    blocked = await tool.execute(url="file:///etc/passwd")
    assert blocked.success is False
    assert "http" in blocked.error.lower()
