import platform
import subprocess
from pathlib import Path

from app.hardware import _office_installed
from app.tools.docker_tools import DockerTool
from app.tools.git_tools import GitTool
from app.tools.office import OfficeTool
from app.tools.python_exec import PythonTool
from app.tools.terminal import TerminalTool, default_shell
from app.tools.web_fetch import WebFetchTool


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "readme.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "jarvis@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Jarvis"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


async def test_git_checkpoint_keeps_working_tree(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "readme.txt").write_text("hello\nedited\n", encoding="utf-8")
    tool = GitTool()
    result = await tool.execute(action="checkpoint", path=str(repo))
    assert result.success, result.error
    assert "Working tree was not modified" in result.output
    assert (repo / "readme.txt").read_text(encoding="utf-8") == "hello\nedited\n"
    branches = subprocess.run(["git", "branch"], cwd=repo, check=True, capture_output=True, text=True)
    assert "jarvis-checkpoint-" in branches.stdout


async def test_docker_run_and_inspect_require_targets():
    tool = DockerTool()
    missing_run = await tool.execute(action="run")
    assert missing_run.success is False
    assert "image is required" in missing_run.error
    missing_logs = await tool.execute(action="logs")
    assert missing_logs.success is False
    missing_inspect = await tool.execute(action="inspect")
    assert missing_inspect.success is False


async def test_web_fetch_rejects_non_http_urls():
    tool = WebFetchTool()
    for url in ("file:///etc/passwd", "javascript:alert(1)", "data:text/plain,hi"):
        result = await tool.execute(url=url)
        assert result.success is False
        assert "http/https" in result.error.lower()


async def test_office_info_does_not_dispatch_com(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("hi", encoding="utf-8")
    tool = OfficeTool()
    if platform.system() != "Windows":
        unavailable = await tool.execute(app="word", action="create", destination=str(tmp_path / "x.docx"))
        assert unavailable.success is False
        info = await tool.execute(app="word", action="info", path=str(target))
        assert info.success is False
        assert "unavailable" in info.error.lower()
        return
    info = await tool.execute(app="word", action="info", path=str(target))
    assert info.success is True
    assert "size=" in info.output


def test_office_probe_does_not_require_dispatch():
    assert _office_installed() is False or platform.system() == "Windows"


async def test_python_uses_sys_executable(tmp_path):
    tool = PythonTool()
    result = await tool.execute(action="run_code", code="import sys; print(sys.executable)", working_directory=str(tmp_path))
    assert result.success, result.error
    import sys

    assert sys.executable in result.output


async def test_terminal_defaults_to_bash_on_linux(tmp_path):
    if platform.system() == "Windows":
        assert default_shell() == "powershell"
        return
    assert default_shell() == "bash"
    tool = TerminalTool()
    result = await tool.execute(command="echo hello-qa", working_directory=str(tmp_path))
    assert result.success, result.error
    assert "hello-qa" in result.output
