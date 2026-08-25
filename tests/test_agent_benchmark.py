from app.agent.agent_benchmark import (
    REQUIRED_CATEGORIES,
    SUITE,
    TaskMetrics,
    build_report,
    compare_profiles,
    list_suite,
    record_result,
    suite_coverage,
)


def test_suite_has_at_least_twenty_representative_tasks():
    tasks = list_suite()
    assert len(tasks) >= 20
    assert len({item["id"] for item in tasks}) == len(tasks)
    coverage = suite_coverage()
    assert coverage["required_categories_present"] is True
    assert not coverage["missing_required_categories"]
    assert REQUIRED_CATEGORIES <= {spec.category for spec in SUITE}


def test_compare_profiles_uses_verified_throughput_not_tokens():
    rows = [
        {
            "profile": "9b-q8",
            "success": True,
            "human_intervention": False,
            "total_seconds": 120,
            "retries": 0,
            "incorrect_actions": 0,
            "tool_calls": 4,
            "schema_errors": 0,
        },
        {
            "profile": "9b-q8",
            "success": True,
            "human_intervention": False,
            "total_seconds": 180,
            "retries": 0,
            "incorrect_actions": 0,
            "tool_calls": 5,
            "schema_errors": 0,
        },
        {
            "profile": "27b-q4",
            "success": True,
            "human_intervention": True,
            "total_seconds": 900,
            "retries": 2,
            "incorrect_actions": 1,
            "tool_calls": 8,
            "schema_errors": 1,
        },
        {
            "profile": "27b-q4",
            "success": False,
            "human_intervention": True,
            "total_seconds": 800,
            "retries": 3,
            "incorrect_actions": 2,
            "tool_calls": 6,
            "schema_errors": 0,
        },
    ]
    report = compare_profiles(rows)
    assert report["primary_metric"].startswith("successful autonomous tasks")
    assert report["winner"] == "9b-q8"
    by_name = {item["profile"]: item for item in report["profiles"]}
    assert by_name["9b-q8"]["success_rate"] == 1.0
    assert by_name["9b-q8"]["successful_tasks_per_hour"] == 24.0
    assert by_name["27b-q4"]["success_rate"] == 0.5


async def test_record_result_persists_and_builds_report(jarvis_env):
    await record_result(
        TaskMetrics(
            task_id="fs-organize",
            profile="balanced",
            success=True,
            total_seconds=40,
            tool_calls=3,
            verification="archive exists",
        )
    )
    report = await build_report()
    assert report["results"]
    assert report["results"][0]["task_id"] == "fs-organize"
    assert report["comparison"]["winner"] == "balanced"
    assert "catalog" not in report["live_status"] or report["live_status"].startswith("results")
