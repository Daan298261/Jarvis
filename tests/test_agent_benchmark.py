from fastapi.testclient import TestClient

from app.agent.agent_benchmark import (
    CASES,
    METRIC_FIELDS,
    REQUIRED_CATEGORIES,
    apply_expected_solution,
    check_case,
    empty_metrics,
    format_prompt,
    list_suite,
    metrics_from_task,
    prepare_case,
    record_case_result,
    summarize_results,
)
from app.main import app
from app.db.models import Task, ToolCallRecord


def test_suite_has_twenty_representative_cases():
    suite = list_suite()
    assert suite["count"] == 20
    assert len(CASES) == 20
    categories = {case.category for case in CASES}
    assert set(REQUIRED_CATEGORIES) <= categories
    ids = [case.id for case in CASES]
    assert len(ids) == len(set(ids))
    for case in CASES:
        public = case.as_public_dict()
        assert public["metrics"] == list(METRIC_FIELDS)
        assert case.expected_tools
        assert "{ " not in case.prompt or any(
            token in case.prompt for token in ("{workspace}", "{project}", "{repo}", "{page}", "{locked}", "{image}", "{a}", "{source}", "{data}", "{config}", "{csv}", "{left}", "{script}", "{file}", "{out}")
        )


def test_unsolved_fixtures_fail_and_solutions_pass(tmp_path):
    failing = 0
    for case in CASES:
        workspace = tmp_path / "fail" / case.id
        ctx = prepare_case(case, workspace)
        ok, _note = check_case(case, workspace, ctx)
        if not ok:
            failing += 1
        prompt = format_prompt(case, ctx)
        assert "{" not in prompt or case.id == "unused"
    assert failing >= 18

    for case in CASES:
        workspace = tmp_path / "ok" / case.id
        ctx = prepare_case(case, workspace)
        apply_expected_solution(case, ctx)
        ok, note = check_case(case, workspace, ctx)
        assert ok, f"{case.id} should pass after the expected solution: {note}"


def test_report_summarizes_primary_metric():
    rows = [
        {**empty_metrics(), "success": True, "total_time_seconds": 30, "tool_calls": 4, "incorrect_actions": 1},
        {**empty_metrics(), "success": True, "total_time_seconds": 30, "tool_calls": 2, "incorrect_actions": 0},
        {**empty_metrics(), "success": False, "total_time_seconds": 60, "tool_calls": 2, "incorrect_actions": 2},
    ]
    report = summarize_results(rows)
    assert report["successes"] == 2
    assert report["failures"] == 1
    assert report["successful_tasks_per_minute"] == 1.0
    assert report["first_pass_completion_rate"] == 0.6667
    assert report["tool_call_accuracy"] == 0.625


def test_metrics_from_task_include_p09_fields():
    task = Task(id="t1", title="t", prompt="t", status="completed", retries=1, duration_seconds=12.5, verification="ok")
    calls = [
        ToolCallRecord(task_id="t1", tool_name="filesystem", success=True, duration_ms=100),
        ToolCallRecord(task_id="t1", tool_name="python", success=False, duration_ms=50, error="schema mismatch"),
    ]
    metrics = metrics_from_task(task, calls)
    for field in METRIC_FIELDS:
        assert field in metrics
    assert metrics["success"] is True
    assert metrics["tool_calls"] == 2
    assert metrics["schema_errors"] == 1
    assert metrics["incorrect_actions"] == 1
    assert metrics["retries"] == 1


async def test_record_case_result_persists(jarvis_env):
    case = CASES[0]
    row = await record_case_result(case=case, metrics={**empty_metrics(), "success": True}, source="test")
    assert row.id
    assert row.case_id == case.id
    assert row.success is True


def test_agent_suite_endpoints(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.api.model.data_dir", lambda: jarvis_env["tmp"])
    client = TestClient(app)
    listed = client.get("/api/model/agent-suite")
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] == 20
    assert body["live_comparison_blocked"] is True
    run = client.post("/api/model/agent-suite/run", json={"case_id": "json-update", "simulate_success": True})
    assert run.status_code == 200
    payload = run.json()
    assert payload["success"] is True
    assert "theme" in payload["prompt"].lower() or "dark" in payload["prompt"].lower()
