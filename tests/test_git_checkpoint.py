import subprocess
from pathlib import Path

from app.tools.git_tools import GitTool


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


async def test_checkpoint_keeps_working_tree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "jarvis@example.com")
    _git(repo, "config", "user.name", "Jarvis")
    note = repo / "note.txt"
    note.write_text("original\n", encoding="utf-8")
    _git(repo, "add", "note.txt")
    _git(repo, "commit", "-m", "init")
    note.write_text("edited by agent\n", encoding="utf-8")

    tool = GitTool()
    result = await tool.execute(action="checkpoint", path=str(repo))
    assert result.success, result.error
    assert "working tree unchanged" in result.output
    assert "jarvis-checkpoint-" in result.output
    assert note.read_text(encoding="utf-8") == "edited by agent\n"
    branches = subprocess.check_output(["git", "branch"], cwd=repo, text=True)
    assert "jarvis-checkpoint-" in branches
