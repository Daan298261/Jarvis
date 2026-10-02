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


async def test_clone_local_repo_onto_extra_volume(tmp_path):
    src = await _repo(tmp_path)
    extra = tmp_path / "E" / "Projects"
    extra.mkdir(parents=True)
    dest = extra / "copy"
    tool = _tool(tmp_path)
    result = await tool.execute(action="clone", url=str(src), path=str(dest))
    assert result.success, result.error
    assert (dest / "readme.txt").read_text(encoding="utf-8") == "one\n"


async def test_clone_without_path_uses_documents(tmp_path, monkeypatch):
    from app.tools.git_tools import git_repo_name

    src = await _repo(tmp_path)
    docs = tmp_path / "Documents"
    docs.mkdir()
    monkeypatch.setattr("app.tools.owner_paths.Path.home", classmethod(lambda cls: tmp_path))
    tool = _tool(tmp_path)
    result = await tool.execute(action="clone", url=str(src))
    assert result.success, result.error
    dest = docs / git_repo_name(str(src))
    assert (dest / "readme.txt").read_text(encoding="utf-8") == "one\n"


async def test_clone_into_extra_drive_folder_appends_repo_name(tmp_path):
    from app.tools.git_tools import git_repo_name

    src = await _repo(tmp_path)
    extra = tmp_path / "E"
    extra.mkdir()
    tool = _tool(tmp_path)
    result = await tool.execute(action="clone", url=str(src), path=str(extra))
    assert result.success, result.error
    dest = extra / git_repo_name(str(src))
    assert (dest / "readme.txt").read_text(encoding="utf-8") == "one\n"


async def test_status_on_extra_drive_repo(tmp_path):
    extra = tmp_path / "E"
    extra.mkdir()
    repo = await _repo(extra)
    tool = _tool(tmp_path)
    result = await tool.execute(action="status", path=str(repo))
    assert result.success, result.error


def test_git_repo_name_from_url_and_path():
    from app.tools.git_tools import git_repo_name

    assert git_repo_name("https://github.com/example/notes.git") == "notes"
    assert git_repo_name("/home/owner/src/vault/") == "vault"


async def test_clone_rejects_destination_outside_workspace(tmp_path):
    src = await _repo(tmp_path)
    tool = _tool(tmp_path)
    result = await tool.execute(action="clone", url=str(src), path="/etc/jarvis-clone-dest")
    assert result.success is False
    assert "outside allowed directories" in result.error


async def test_clone_https_honors_internet_deny(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    ran = {"n": 0}

    async def _boom(*_args, **_kwargs):
        ran["n"] += 1
        raise AssertionError("git clone must not run when internet is denied")

    monkeypatch.setattr("app.tools.git_tools.GitTool._git", _boom)
    tool = _tool(tmp_path)
    result = await tool.execute(
        action="clone",
        url="https://github.com/example/repo.git",
        path=str(tmp_path / "out"),
    )
    assert result.success is False
    assert ran["n"] == 0
    assert "internet" in (result.error or "").lower() or "permission" in (result.error or "").lower() or "don't allow" in (result.error or "").lower()


async def test_fetch_honors_internet_deny(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    repo = await _repo(tmp_path)
    ran = {"n": 0}

    async def _boom(*_args, **_kwargs):
        ran["n"] += 1
        raise AssertionError("git fetch must not run when internet is denied")

    monkeypatch.setattr("app.tools.git_tools.GitTool._git", _boom)
    tool = _tool(tmp_path)
    result = await tool.execute(action="fetch", path=str(repo))
    assert result.success is False
    assert ran["n"] == 0
    assert "internet" in (result.error or "").lower() or "permission" in (result.error or "").lower() or "don't allow" in (result.error or "").lower()


async def test_git_omitted_path_uses_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Documents"
    docs.mkdir()
    await _git(docs, "init")
    await _git(docs, "config", "user.email", "jarvis@example.test")
    await _git(docs, "config", "user.name", "Jarvis")
    (docs / "readme.txt").write_text("docs-repo\n", encoding="utf-8")
    await _git(docs, "add", "readme.txt")
    await _git(docs, "commit", "-m", "init")
    monkeypatch.setattr("app.tools.owner_paths.Path.home", classmethod(lambda cls: tmp_path))
    tool = GitTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(action="status")
    assert result.success, result.error


async def test_worktree_add_onto_extra_drive(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent.worktrees.data_dir", lambda: tmp_path / "wt-meta")
    extra = tmp_path / "E"
    extra.mkdir()
    repo = await _repo(tmp_path)
    tool = _tool(tmp_path)
    result = await tool.execute(action="worktree_add", path=str(repo), destination=str(extra))
    assert result.success, result.error
    dest = Path(result.data["path"])
    assert dest.exists()
    assert dest.is_dir()
    assert extra == dest.parent or extra in dest.parents
    assert dest.resolve() != repo.resolve()
    outside = await tool.execute(action="worktree_add", path=str(repo), destination="/etc/jarvis-wt")
    assert outside.success is False
    assert "outside allowed" in (outside.error or "").lower()

