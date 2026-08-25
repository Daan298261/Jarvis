from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.agent.metrics import LiveTaskMetrics
from app.agent.verify_code import verify_software
from app.providers.base import parse_tool_arguments, tool_arguments_valid
from app.tools.browser import BrowserTool
from app.tools.docker_tools import DockerTool
from app.tools.filesystem import FilesystemTool
from app.tools.git_tools import GitTool
from app.tools.office import OfficeTool
from app.tools.python_exec import PythonTool
from app.tools.terminal import TerminalTool, default_shell
from app.tools.web_fetch import WebFetchTool
from app.tools.verify_code import VerifyCodeTool


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "jarvis@test.local")
    _git(root, "config", "user.name", "Jarvis Test")
    (root / "readme.txt").write_text("hello\n", encoding="utf-8")
    _git(root, "add", "readme.txt")
    _git(root, "commit", "-m", "init")


async def test_git_checkpoint_keeps_working_tree(tmp_path):
    _init_repo(tmp_path)
    dirty = tmp_path / "readme.txt"
    dirty.write_text("hello\nchanged\n", encoding="utf-8")
    untracked = tmp_path / "scratch.txt"
    untracked.write_text("keep me\n", encoding="utf-8")

    tool = GitTool()
    result = await tool.execute(action="checkpoint", path=str(tmp_path))
    assert result.success, result.error
    assert "Working tree was not modified" in result.output
    assert "jarvis-checkpoint-" in result.output
    assert dirty.read_text(encoding="utf-8") == "hello\nchanged\n"
    assert untracked.read_text(encoding="utf-8") == "keep me\n"
    branches = await tool.execute(action="branch", path=str(tmp_path))
    assert "jarvis-checkpoint-" in branches.output


async def test_filesystem_snapshot_skips_identical_and_restores(tmp_path):
    source = tmp_path / "project"
    source.mkdir()
    (source / "a.txt").write_text("one", encoding="utf-8")
    backups = tmp_path / "backups"
    tool = FilesystemTool(lambda: {"allowed_directories": [str(tmp_path)], "backup_root": str(backups)})

    first = await tool.execute(action="snapshot", path=str(source), note="before")
    assert first.success, first.error
    assert first.data.get("skipped") is False
    snapshot_id = first.data["id"]

    again = await tool.execute(action="snapshot", path=str(source))
    assert again.success
    assert again.data.get("skipped") is True

    (source / "a.txt").write_text("two", encoding="utf-8")
    dest = tmp_path / "restored"
    restored = await tool.execute(action="restore", snapshot_id=snapshot_id, destination=str(dest))
    assert restored.success, restored.error
    assert (dest / "a.txt").read_text(encoding="utf-8") == "one"

    listed = await tool.execute(action="snapshots", path=str(source))
    assert listed.success
    assert snapshot_id in listed.output


async def test_verify_code_runs_pytest_independently(tmp_path):
    _init_repo(tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "tests")

    tool = VerifyCodeTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(path=str(tmp_path), timeout_seconds=60)
    assert result.success, result.output
    assert result.data["ok"] is True
    assert result.data["tests"]["ran"] is True
    assert "principle" in result.output


async def test_verify_code_fails_when_tests_fail(tmp_path):
    _init_repo(tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_bad.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    report = await verify_software(tmp_path, timeout_seconds=60)
    assert report["ok"] is False
    assert report["tests"]["ok"] is False
    assert "worker claiming success" in report["principle"].lower() or "does not constitute" in report["principle"]


async def test_verify_code_rejects_outside_path(tmp_path):
    tool = VerifyCodeTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(path="/etc")
    assert result.success is False
    assert "outside allowed directories" in result.error


def test_live_metrics_and_schema_parse():
    metrics = LiveTaskMetrics()
    metrics.note_model({"prompt_ms": 10, "predicted_ms": 20})
    metrics.note_tool(5, schema_error=True)
    metrics.note_confirmation()
    fields = metrics.as_fields()
    assert fields["model_calls"] == 1
    assert fields["tool_call_count"] == 1
    assert fields["schema_errors"] == 1
    assert fields["model_ms"] == 30
    assert fields["human_interventions"] == 1
    assert tool_arguments_valid('{"action": "list"}') is True
    assert tool_arguments_valid("{not json") is False
    parsed = parse_tool_arguments("{not json")
    assert parsed["_raw"].startswith("{not")


async def test_docker_run_and_logs_require_targets():
    tool = DockerTool()
    run = await tool.execute(action="run")
    assert run.success is False
    assert "image is required" in run.error
    logs = await tool.execute(action="logs")
    assert logs.success is False
    assert "container is required" in logs.error
    inspect = await tool.execute(action="inspect")
    assert inspect.success is False
    assert "container or image is required" in inspect.error


async def test_web_fetch_rejects_non_http():
    tool = WebFetchTool()
    file_url = await tool.execute(url="file:///etc/passwd")
    assert file_url.success is False
    assert "http/https" in file_url.error
    empty = await tool.execute(url="not-a-url")
    assert empty.success is False


async def test_python_uses_current_interpreter():
    tool = PythonTool()
    assert tool._python_bin(None) == sys.executable


def test_terminal_default_shell_is_bash_on_linux():
    if sys.platform.startswith("win"):
        assert default_shell() == "powershell"
    else:
        assert default_shell() == "bash"


async def test_office_info_does_not_need_com(tmp_path):
    doc = tmp_path / "note.docx"
    doc.write_bytes(b"not really docx")
    tool = OfficeTool()
    result = await tool.execute(app="word", action="info", path=str(doc))
    assert result.success
    assert "COM was not started" in result.output
    assert str(doc.resolve()) in result.output


async def test_terminal_run_uses_python_shell(tmp_path):
    tool = TerminalTool()
    result = await tool.execute(shell="python", command="print(2+2)", working_directory=str(tmp_path))
    assert result.success, result.error
    assert "4" in result.output


async def test_browser_close_and_open_guards():
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    closed = await tool.execute(action="close")
    assert closed.success
    assert "not open" in closed.output.lower()
    missing = await tool.execute(action="open")
    assert missing.success is False
    assert "url is required" in missing.error
