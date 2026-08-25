from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent.self_dev import (
    PytestCounts,
    activate_kill_switch,
    budget_exhausted,
    build_report,
    can_dispatch_paid,
    clear_kill_switch,
    evaluate_gate,
    experimental_launch_plan,
    kill_switch_active,
    parse_pytest_output,
    record_usage,
    run_verification_gate,
    save_session,
    start_trial,
)
from app.agent.worktrees import checkpoint_commit
from app.main import app


def _init_pytest_repo(path: Path, failing: bool = False) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=path, check=True, capture_output=True)
    (path / "tests").mkdir()
    (path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    if failing:
        (path / "tests" / "test_bad.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    (path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
def trial_env(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent.worktrees.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.agent.self_dev.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    yield tmp_path
    if (tmp_path / "STOP_JARVIS").exists():
        (tmp_path / "STOP_JARVIS").unlink()


def test_gate_rejects_regression():
    before = PytestCounts(passed=2, failed=0, ok=True)
    after = PytestCounts(passed=1, failed=1, ok=False, returncode=1)
    gate = evaluate_gate(before, after)
    assert gate["passed"] is False
    assert gate["merge_allowed"] is False
    assert any("regression" in item.lower() or "did not pass" in item.lower() for item in gate["reasons"])


def test_gate_accepts_improvement_without_merge():
    before = PytestCounts(passed=1, failed=0, ok=True)
    after = PytestCounts(passed=2, failed=0, ok=True)
    gate = evaluate_gate(before, after)
    assert gate["passed"] is True
    assert gate["merge_allowed"] is False


def test_parse_pytest_summary():
    counts = parse_pytest_output(".....                                                              [100%]\n5 passed in 0.12s", 0)
    assert counts.passed == 5
    assert counts.ok is True


def test_kill_switch_blocks_and_clears(trial_env):
    assert kill_switch_active() is False
    activate_kill_switch("operator stop")
    assert kill_switch_active() is True
    assert (trial_env / "STOP_JARVIS").exists()
    clear_kill_switch()
    assert kill_switch_active() is False


def test_paid_dispatch_blocked_by_default(trial_env):
    assert can_dispatch_paid({"budget": {"max_paid_spend_eur": 0, "max_paid_invocations": 0}, "usage": {}}) is False


def test_budget_stops_after_failures(trial_env):
    save_session(
        {
            "status": "running",
            "budget": {"max_duration_hours": 12, "max_paid_spend_eur": 0, "max_paid_invocations": 0, "max_consecutive_failures": 2},
            "usage": {"consecutive_failures": 2, "paid_spend_eur": 0, "paid_invocations": 0},
        }
    )
    assert "failures" in budget_exhausted().lower()
    record_usage("task_success")
    assert budget_exhausted() == ""


def test_trial_worktree_and_independent_gate(trial_env):
    repo = _init_pytest_repo(trial_env / "repo")
    session = start_trial(repo, run_baseline=True, pytest_timeout=60)
    assert session["status"] == "running"
    assert session["branch"].startswith("jarvis/autonomous-trial-")
    assert Path(session["worktree_path"]).exists()
    assert session["baseline_tests"]["passed"] >= 1
    (Path(session["worktree_path"]) / "tests" / "test_more.py").write_text("def test_more():\n    assert True\n", encoding="utf-8")
    checkpoint_commit(session["worktree_path"], "add test")
    gate = run_verification_gate(session["worktree_id"], pytest_timeout=60)
    assert gate["passed"] is True
    assert gate["merge_allowed"] is False
    report = build_report()
    assert report["experiment_branch"] == session["branch"]
    assert report["auto_merge"] is False
    assert report["starting_commit"] == session["source_commit"]


def test_experimental_launch_uses_other_port():
    plan = experimental_launch_plan("/tmp/example")
    assert ":4780" in plan["trusted"] or plan["trusted"].endswith("4780")
    assert plan["experimental"] != plan["trusted"]
    assert "4781" in plan["experimental"]
    assert "uvicorn" in plan["command"]


def test_self_dev_api_stop_and_status(trial_env, monkeypatch):
    monkeypatch.setattr("app.api.self_dev.activate_kill_switch", activate_kill_switch)
    client = TestClient(app)
    stopped = client.post("/api/self-dev/stop", json={"reason": "test stop"})
    assert stopped.status_code == 200
    assert stopped.json()["kill_switch"] is True
    blocked = client.post("/api/tasks", json={"prompt": "should not start"})
    assert blocked.status_code == 409
    resumed = client.post("/api/self-dev/resume")
    assert resumed.status_code == 200
    status = client.get("/api/self-dev")
    assert status.status_code == 200
    assert status.json()["kill_switch"] is False
    merge = client.post("/api/self-dev/merge", json={"target_branch": "main"})
    assert merge.status_code == 403
