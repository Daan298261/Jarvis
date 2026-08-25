import asyncio
from pathlib import Path

from app.tools.git_tools import GitTool


async def _git(cwd: Path, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()
    return stdout.decode()


async def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    await _git(repo, "init")
    await _git(repo, "config", "user.email", "jarvis@example.test")
    await _git(repo, "config", "user.name", "Jarvis")
    (repo / "readme.txt").write_text("one\n", encoding="utf-8")
    await _git(repo, "add", "readme.txt")
    await _git(repo, "commit", "-m", "init")
    return repo


def _tool(tmp_path: Path) -> GitTool:
    return GitTool(lambda: {"allowed_directories": [str(tmp_path)]})


async def test_checkpoint_does_not_remove_working_tree_changes(tmp_path):
    repo = await _repo(tmp_path)
    (repo / "readme.txt").write_text("one\ntwo\n", encoding="utf-8")
    (repo / "extra.txt").write_text("untracked\n", encoding="utf-8")
    tool = _tool(tmp_path)
    result = await tool.execute(action="checkpoint", path=str(repo))
    assert result.success, result.error
    assert result.data["dirty"] is True
    assert result.data["branch"].startswith("jarvis-checkpoint-")
    assert (repo / "readme.txt").read_text(encoding="utf-8") == "one\ntwo\n"
    assert (repo / "extra.txt").read_text(encoding="utf-8") == "untracked\n"
    listed = await tool.execute(action="list_checkpoints", path=str(repo))
    assert result.data["branch"] in listed.output


async def test_restore_overlays_checkpoint_without_switching_branch(tmp_path):
    repo = await _repo(tmp_path)
    tool = _tool(tmp_path)
    first = await tool.execute(action="checkpoint", path=str(repo))
    assert first.success, first.error
    (repo / "readme.txt").write_text("changed\n", encoding="utf-8")
    restored = await tool.execute(action="restore", path=str(repo), ref=first.data["branch"])
    assert restored.success, restored.error
    assert restored.data["current_branch"] != first.data["branch"]
    assert (repo / "readme.txt").read_text(encoding="utf-8") == "one\n"


async def test_git_path_is_sandboxed(tmp_path):
    tool = _tool(tmp_path)
    result = await tool.execute(action="status", path="/")
    assert result.success is False
    assert "outside allowed directories" in result.error


async def test_restore_rejects_arbitrary_refs(tmp_path):
    repo = await _repo(tmp_path)
    tool = _tool(tmp_path)
    result = await tool.execute(action="restore", path=str(repo), ref="main")
    assert result.success is False
    assert "jarvis-checkpoint" in result.error
