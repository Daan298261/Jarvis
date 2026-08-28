from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from app.agent.coding_workers import (
    approve_task_integration,
    cleanup_coding_task,
    complete_coding_task,
    integrate_coding_task,
    list_decision_inbox,
    request_task_integration,
    resolve_decision_inbox_item,
    start_coding_task,
)
from app.agent.worktrees import (
    WorktreeError,
    allocate_worktree_for_task,
    assert_task_write_path,
    checkpoint_commit,
    get_coding_task,
    record_task_commit,
    release_worktree_for_task,
)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    (path / "src").mkdir(exist_ok=True)
    (path / "src" / "alpha.py").write_text("alpha = 1\n", encoding="utf-8")
    (path / "src" / "beta.py").write_text("beta = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent.worktrees.data_dir", lambda: tmp_path)
    return _init_repo(tmp_path / "trusted")


def test_parallel_tasks_receive_distinct_worktrees(isolated_repo):
    first = allocate_worktree_for_task("task-a", source=isolated_repo)
    second = allocate_worktree_for_task("task-b", source=isolated_repo)
    assert first.worktree_path != second.worktree_path
    assert first.branch != second.branch
    assert Path(first.worktree_path).exists()
    assert Path(second.worktree_path).exists()


def test_same_task_cannot_allocate_twice(isolated_repo):
    allocate_worktree_for_task("task-a", source=isolated_repo)
    with pytest.raises(WorktreeError, match="already has an active worktree"):
        allocate_worktree_for_task("task-a", source=isolated_repo)


def test_primary_checkout_unmodified_by_parallel_tasks(isolated_repo):
    trusted_readme = (isolated_repo / "README.md").read_text(encoding="utf-8")
    first = allocate_worktree_for_task("task-a", source=isolated_repo)
    second = allocate_worktree_for_task("task-b", source=isolated_repo)
    (Path(first.worktree_path) / "README.md").write_text("task-a edit\n", encoding="utf-8")
    (Path(second.worktree_path) / "README.md").write_text("task-b edit\n", encoding="utf-8")
    assert (isolated_repo / "README.md").read_text(encoding="utf-8") == trusted_readme


def test_task_write_guard_blocks_production_checkout(isolated_repo):
    record = allocate_worktree_for_task("task-a", source=isolated_repo)
    with pytest.raises(WorktreeError, match="trusted production checkout"):
        assert_task_write_path(record.task_id, isolated_repo / "README.md")


def test_task_write_guard_blocks_other_task_worktree(isolated_repo):
    first = allocate_worktree_for_task("task-a", source=isolated_repo)
    second = allocate_worktree_for_task("task-b", source=isolated_repo)
    with pytest.raises(WorktreeError, match="may only write inside its worktree"):
        assert_task_write_path(first.task_id, Path(second.worktree_path) / "README.md")


def test_task_records_metadata_commits_tests_and_diff(isolated_repo):
    record = allocate_worktree_for_task("task-a", source=isolated_repo)
    target = Path(record.worktree_path) / "src" / "alpha.py"
    target.write_text("alpha = 42\n", encoding="utf-8")
    commit = record_task_commit(record.task_id, "update alpha")
    assert commit["created"] is True
    tests = {"passed": 3, "failed": 0, "ok": True}
    result = complete_coding_task(record.task_id, tests=tests)
    task = result["task"]
    assert task["base_sha"]
    assert task["branch"].startswith("jarvis/coding-task-")
    assert task["worktree_path"] == record.worktree_path
    assert task["commits"]
    assert task["tests"] == tests
    assert task["final_diff"]["stat"]


def test_integration_requires_approval_by_default(isolated_repo):
    record = allocate_worktree_for_task("task-a", source=isolated_repo)
    (Path(record.worktree_path) / "src" / "beta.py").write_text("beta = 9\n", encoding="utf-8")
    complete_coding_task(record.task_id, tests={"passed": 1, "ok": True})
    gate = request_task_integration(record.task_id)
    assert gate["integration_status"] == "awaiting_approval"
    assert gate["requires_approval"] is True
    blocked = integrate_coding_task(record.task_id)
    assert blocked["integration_status"] == "awaiting_approval"


def test_integration_after_human_approval(isolated_repo):
    record = allocate_worktree_for_task("task-a", source=isolated_repo)
    (Path(record.worktree_path) / "src" / "beta.py").write_text("beta = 9\n", encoding="utf-8")
    complete_coding_task(record.task_id, tests={"passed": 1, "ok": True})
    approve_task_integration(record.task_id, approver="human")
    result = integrate_coding_task(record.task_id)
    assert result["integration_status"] == "ready"
    assert result["branch"] == record.branch


def test_parallel_conflicts_surface_in_decision_inbox(isolated_repo):
    first = allocate_worktree_for_task("task-a", source=isolated_repo)
    second = allocate_worktree_for_task("task-b", source=isolated_repo)
    (Path(first.worktree_path) / "src" / "alpha.py").write_text("alpha = 100\n", encoding="utf-8")
    (Path(second.worktree_path) / "src" / "alpha.py").write_text("alpha = 200\n", encoding="utf-8")
    complete_coding_task(first.task_id, tests={"passed": 1, "ok": True})
    complete_coding_task(second.task_id, tests={"passed": 1, "ok": True})
    items = list_decision_inbox(open_only=True)
    assert items
    assert any(item["kind"] == "merge_conflict" for item in items)
    conflict = next(item for item in items if item["task_id"] == second.task_id)
    resolve_decision_inbox_item(conflict["id"], resolution="keep both branches separate")
    resolved = list_decision_inbox(open_only=False)
    assert any(item["id"] == conflict["id"] and item["status"] == "resolved" for item in resolved)


def test_cleanup_removes_worktree(isolated_repo):
    record = allocate_worktree_for_task("task-a", source=isolated_repo)
    worktree_path = Path(record.worktree_path)
    assert worktree_path.exists()
    cleaned = cleanup_coding_task(record.task_id)
    assert cleaned["cleaned_up"] is True
    assert not worktree_path.exists()
    listed = subprocess.run(["git", "worktree", "list"], cwd=isolated_repo, capture_output=True, text=True, check=True)
    assert str(worktree_path) not in listed.stdout


def test_concurrent_allocation_is_isolated(isolated_repo):
    errors: list[str] = []
    results: list[str] = []

    def _start(task_id: str) -> None:
        try:
            record = allocate_worktree_for_task(task_id, source=isolated_repo)
            results.append(record.worktree_path)
        except WorktreeError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=_start, args=(f"task-{index}",)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(errors) == 0
    assert len(set(results)) == 4


def test_start_coding_task_api_shape(isolated_repo):
    payload = start_coding_task("api-task", source=isolated_repo)
    assert payload["task_id"] == "api-task"
    stored = get_coding_task("api-task")
    assert stored.worktree_id == payload["worktree_id"]
    release_worktree_for_task("api-task", discard=True)
