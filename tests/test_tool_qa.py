import asyncio
from pathlib import Path

from app.hardware import _office_installed
from app.tools.docker_tools import DockerTool
from app.tools.git_tools import GitTool
from app.tools.office import OfficeTool
from app.tools.python_exec import PythonTool
from app.tools.terminal import TerminalTool, default_shell
from app.tools.web_fetch import WebFetchTool
from app.tools.browser import BrowserTool


async def _run_git(args: list[str], cwd) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace")


async def test_git_checkpoint_keeps_working_tree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    await _run_git(["init"], repo)
    await _run_git(["config", "user.email", "jarvis@example.com"], repo)
    await _run_git(["config", "user.name", "Jarvis"], repo)
    await _run_git(["config", "commit.gpgsign", "false"], repo)
    tracked = repo / "keep.txt"
    tracked.write_text("safe\n", encoding="utf-8")
    await _run_git(["add", "keep.txt"], repo)
    await _run_git(["-c", "commit.gpgsign=false", "commit", "-m", "init"], repo)
    tracked.write_text("dirty working tree\n", encoding="utf-8")
    extra = repo / "untracked.txt"
    extra.write_text("also stay\n", encoding="utf-8")

    result = await GitTool().execute(action="checkpoint", path=str(repo))
    assert result.success, result.error
    assert "Backup branch" in result.output
    assert tracked.read_text(encoding="utf-8") == "dirty working tree\n"
    assert extra.exists()
    assert result.data["branch"].startswith("jarvis-checkpoint-")


async def test_docker_requires_targets_before_invoking_docker():
    run = await DockerTool().execute(action="run")
    assert not run.success
    assert "image" in run.error.lower()
    logs = await DockerTool().execute(action="logs")
    assert "container" in logs.error.lower()
    inspect = await DockerTool().execute(action="inspect")
    assert "container or image" in inspect.error.lower()


async def test_web_fetch_rejects_non_http_urls():
    tool = WebFetchTool()
    for url in ("file:///etc/passwd", "javascript:alert(1)", "data:text/plain,hi"):
        result = await tool.execute(url=url)
        assert not result.success
        assert "http" in result.error.lower()


async def test_office_info_does_not_need_com(tmp_path):
    path = tmp_path / "note.docx"
    path.write_bytes(b"PK\x03\x04fake")
    result = await OfficeTool().execute(app="word", action="info", path=str(path))
    assert result.success
    assert "COM was not launched" in result.output
    missing = await OfficeTool().execute(app="word", action="info")
    assert missing.success
    assert "COM was not launched" in missing.output
    assert _office_installed() is False


async def test_python_uses_sys_executable():
    tool = PythonTool()
    assert "python" in Path(tool._python_bin(None)).name.lower()
    result = await tool.execute(action="run_code", code="print('qa-ok')")
    assert result.success, result.error
    assert "qa-ok" in result.output


async def test_terminal_default_shell_is_platform_native():
    import os

    expected = "powershell" if os.name == "nt" else "bash"
    assert default_shell() == expected
    tool = TerminalTool()
    result = await tool.execute(action="run", command="print('shell-ok')", shell="python")
    assert result.success, result.error
    assert "shell-ok" in result.output


async def test_browser_close_without_session():
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="close")
    assert result.success
    assert "not running" in result.output.lower() or "closed" in result.output.lower()
