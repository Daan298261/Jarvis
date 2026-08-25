from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agent.worktrees import (
    WorktreeError,
    checkpoint_commit,
    create_worktree,
    discard_worktree,
    is_isolated_worktree,
    is_production_checkout,
    refuse_trusted_merge,
)


def _init_repo(path: Path, extra: str | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    if extra:
        (path / extra).parent.mkdir(parents=True, exist_ok=True)
        (path / extra).write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent.worktrees.data_dir", lambda: tmp_path)
    repo = _init_repo(tmp_path / "trusted")
    return repo


def test_create_worktree_does_not_touch_trusted_checkout(isolated, tmp_path):
    spec = create_worktree(isolated)
    trusted_readme = (isolated / "README.md").read_text(encoding="utf-8")
    (Path(spec.path) / "README.md").write_text("changed in trial\n", encoding="utf-8")
    assert (isolated / "README.md").read_text(encoding="utf-8") == trusted_readme
    assert is_isolated_worktree(spec.path, isolated)
    assert is_production_checkout(isolated, isolated)
    assert not is_production_checkout(spec.path, isolated)
    assert spec.branch.startswith("jarvis/autonomous-trial-")
    assert spec.start_commit


def test_checkpoint_commit_refused_on_production(isolated):
    (isolated / "README.md").write_text("dirty trusted\n", encoding="utf-8")
    with pytest.raises(WorktreeError, match="trusted production"):
        checkpoint_commit(isolated, "nope")


def test_checkpoint_commit_only_in_worktree(isolated):
    spec = create_worktree(isolated)
    (Path(spec.path) / "NEW.txt").write_text("from trial\n", encoding="utf-8")
    result = checkpoint_commit(spec.path, "trial checkpoint")
    assert result["created"] is True
    assert result["commit"]
    assert not (isolated / "NEW.txt").exists()


def test_discard_worktree_leaves_trusted_repo(isolated):
    spec = create_worktree(isolated)
    (Path(spec.path) / "junk.py").write_text("print(1)\n", encoding="utf-8")
    discarded = discard_worktree(spec.id)
    assert discarded.status == "discarded"
    assert isolated.exists()
    assert (isolated / "README.md").exists()
    listed = subprocess.run(["git", "worktree", "list"], cwd=isolated, capture_output=True, text=True, check=True)
    assert spec.path not in listed.stdout


def test_refuse_trusted_merge():
    with pytest.raises(PermissionError, match="must not merge"):
        refuse_trusted_merge("main")
