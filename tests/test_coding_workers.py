from fastapi.testclient import TestClient

from app.agent.coding_workers import (
    coding_worker_catalog,
    format_route_prompt,
    list_coding_routes,
    record_coding_route,
    route_software_task,
    score_complexity,
    should_route,
    tier_for_score,
)
from app.agent.loop import AGENT
from app.agent.planning import WorkingState
from app.db.models import TaskEvent
from app.db.session import SessionLocal
from app.main import app
from app.providers.base import ChatResult
from sqlalchemy import select

from tests.test_verification_loop import ScriptedProvider, _finished, _tool


def test_deterministic_work_stays_on_native_tools():
    decision = route_software_task("Rename file config.json and bump version, then run tests.")
    assert decision.score <= 20
    assert decision.tier == 0
    assert decision.selected_worker == "native-tools"
    assert decision.independent_verification_required is True
    assert decision.worker_success_is_insufficient is True


def test_local_worker_for_small_coding_changes():
    decision = route_software_task(
        "Add a docstring to the small config helper and a unit test.",
        task_class="software engineering",
        files_hint=1,
        has_tests=True,
    )
    assert 21 <= decision.score <= 40
    assert decision.selected_worker == "local-jarvis-coding"
    assert decision.paid_worker_available is False


def test_paid_workers_are_catalogued_but_unavailable():
    catalog = {item["id"]: item for item in coding_worker_catalog()}
    assert catalog["local-jarvis-coding"]["available"] is True
    assert catalog["local-jarvis-coding"]["status"] == "ready"
    for key in ("cursor-composer-2.5", "cursor-grok-4.6", "frontier-specialist"):
        assert catalog[key]["available"] is False
        assert catalog[key]["status"] == "not_configured"
    decision = route_software_task(
        "Implement a multi-file feature with a database migration and new API endpoint.",
        task_class="software engineering",
        files_hint=6,
        architecture_impact=True,
    )
    assert decision.intended_worker in {"cursor-composer-2.5", "cursor-grok-4.6", "frontier-specialist"}
    assert decision.selected_worker == "local-jarvis-coding"
    assert "unavailable" in decision.reason
    prompt = format_route_prompt(decision)
    assert "Independent verification required: yes" in prompt
    assert "Worker-reported success is not completion" in prompt


def test_complexity_tiers_cover_the_policy_ranges():
    assert tier_for_score(10)["tier_name"] == "deterministic"
    assert tier_for_score(30)["tier_name"] == "local"
    assert tier_for_score(55)["tier_name"] == "composer"
    assert tier_for_score(80)["tier_name"] == "grok"
    assert tier_for_score(95)["tier_name"] == "frontier"
    assert 0 <= score_complexity("hello") <= 100


def test_should_route_software_engineering_prompts():
    assert should_route("software engineering", "refactor the repository")
    assert should_route("mixed", "please implement a pytest unit test")
    assert not should_route("filesystem", "organize the desktop folders")


async def test_coding_route_is_recorded_and_completed(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "config.json"
    target.write_text('{"theme": "light"}', encoding="utf-8")
    provider = ScriptedProvider(
        [
            ChatResult(
                content=(
                    "END STATE: theme is dark\n"
                    "ACCEPTANCE CRITERIA:\n- config.json theme dark\n"
                    "PLAN:\n1. edit the json\n2. read it back"
                )
            ),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": '{"theme": "dark"}', "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="Updated the json."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified theme is dark."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Refactor this repository helper: set theme to dark in {target} and add a unit test later if needed.",
        autonomy="autonomous",
        profile="fast",
        execution_mode="balanced",
    )
    task = await _finished(created.id)
    assert task.status == "completed"
    routes = await list_coding_routes()
    assert routes
    assert routes[0]["task_id"] == task.id
    assert routes[0]["independent_verification_required"] is True
    assert routes[0]["outcome"] == "completed"
    assert routes[0]["selected_worker"] in {"native-tools", "local-jarvis-coding"}
    async with SessionLocal() as session:
        events = (await session.execute(select(TaskEvent).where(TaskEvent.task_id == task.id))).scalars().all()
    assert any("Coding worker" in (event.title or "") for event in events)


async def test_record_coding_route_roundtrip(jarvis_env):
    decision = route_software_task("Fix a simple exception in one file.")
    row = await record_coding_route("task-abc", decision)
    assert row.task_id == "task-abc"
    stored = await list_coding_routes()
    assert stored[0]["selected_worker"] == decision.selected_worker


def test_working_state_keeps_coding_fields():
    state = WorkingState(goal="fix", coding_worker="local-jarvis-coding", coding_tier="local")
    loaded = WorkingState.loads(state.dumps())
    assert loaded.coding_worker == "local-jarvis-coding"
    assert loaded.coding_tier == "local"


def test_coding_workers_endpoint(jarvis_env):
    client = TestClient(app)
    res = client.get("/api/tools/coding-workers")
    assert res.status_code == 200
    body = res.json()
    ids = {item["id"] for item in body["workers"]}
    assert "local-jarvis-coding" in ids
    routed = client.get(
        "/api/tools/coding-workers",
        params={"prompt": "Implement a multi-file feature with a database migration", "task_class": "software engineering"},
    )
    assert routed.status_code == 200
    assert routed.json()["route"]["independent_verification_required"] is True
    assert routed.json()["route"]["selected_worker"] in {"local-jarvis-coding", "native-tools"}
