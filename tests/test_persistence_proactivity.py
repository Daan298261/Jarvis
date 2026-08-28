from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from app.agent.persistence import (
    PERSISTENCE_CONTINUOUS,
    PERSISTENCE_MODES,
    PERSISTENCE_ONE_SHOT,
    PERSISTENCE_UNTIL_COMPLETE,
    TASK_STATUS_COMPLETE,
    TASK_STATUS_FAILED,
    TASK_STATUS_IDLE,
    TASK_STATUS_RUNNING,
    create_autonomy_profile,
    reset_autonomy_store,
    scheduler_eligible_agents,
    scheduler_tick,
    should_remain_scheduled,
    update_autonomy_profile,
)
from app.agent.proactivity import (
    PROACTIVITY_CREATE_TASKS,
    PROACTIVITY_DISABLED,
    PROACTIVITY_EXECUTE_WITHIN_POLICY,
    PROACTIVITY_MODES,
    PROACTIVITY_SUGGEST_ONLY,
    PROACTIVE_STATUS_PENDING_APPROVAL,
    PROACTIVE_STATUS_QUEUED,
    PROACTIVE_STATUS_SUGGESTED,
    approve_proactive_action,
    can_enqueue_executable_work,
    create_proactive_action,
    effective_behavior,
    get_away_mode,
    reset_proactivity_store,
    set_away_mode,
)
from app.main import app
from app.swarm.nodes import register_localhost_node


@pytest.fixture
def autonomy_store(jarvis_env, monkeypatch):
    root = jarvis_env["tmp"] / "autonomy-profiles"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.agent.persistence.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.agent.proactivity.data_dir", lambda: jarvis_env["tmp"])
    reset_autonomy_store()
    reset_proactivity_store()
    yield jarvis_env["tmp"]
    reset_autonomy_store()
    reset_proactivity_store()


@pytest.fixture
def client(autonomy_store):
    return TestClient(app)


ALL_COMBINATIONS = list(itertools.product(PERSISTENCE_MODES, PROACTIVITY_MODES))


@pytest.mark.parametrize("persistence,proactivity", ALL_COMBINATIONS)
def test_profile_stores_persistence_and_proactivity_independently(
    autonomy_store, persistence, proactivity
):
    profile = create_autonomy_profile(
        name=f"{persistence}-{proactivity}",
        persistence=persistence,
        proactivity=proactivity,
    )
    assert profile.persistence == persistence
    assert profile.proactivity == proactivity

    updated = update_autonomy_profile(
        profile.id,
        persistence=PERSISTENCE_CONTINUOUS if persistence != PERSISTENCE_CONTINUOUS else PERSISTENCE_ONE_SHOT,
    )
    assert updated.persistence != persistence or persistence == PERSISTENCE_CONTINUOUS
    assert updated.proactivity == proactivity


@pytest.mark.parametrize("persistence,proactivity", ALL_COMBINATIONS)
def test_effective_behavior_matrix(autonomy_store, persistence, proactivity):
    behavior = effective_behavior(persistence=persistence, proactivity=proactivity)
    assert behavior["persistence"] == persistence
    assert behavior["configured_proactivity"] == proactivity
    assert behavior["effective_proactivity"] == proactivity


@pytest.mark.parametrize("persistence,proactivity", ALL_COMBINATIONS)
def test_away_mode_pauses_proactivity_without_destroying_persistence(
    autonomy_store, persistence, proactivity
):
    profile = create_autonomy_profile(
        name="away-test",
        persistence=persistence,
        proactivity=proactivity,
    )
    set_away_mode(enabled=True, pause_proactivity=True)

    behavior = effective_behavior(persistence=profile.persistence, proactivity=profile.proactivity)
    assert behavior["persistence"] == persistence
    assert behavior["effective_proactivity"] == PROACTIVITY_DISABLED
    assert behavior["away_mode"]["enabled"] is True

    stored = create_autonomy_profile(name="stored", persistence=persistence, proactivity=proactivity)
    assert stored.persistence == persistence
    assert stored.proactivity == proactivity


@pytest.mark.parametrize("persistence", PERSISTENCE_MODES)
def test_scheduler_honors_continuous_without_capability_escalation(autonomy_store, persistence):
    profile = create_autonomy_profile(
        name="scheduler",
        persistence=persistence,
        proactivity=PROACTIVITY_DISABLED,
        agent_id="agent-scheduler",
    )
    eligible = scheduler_eligible_agents(
        [profile],
        task_status_by_agent={"agent-scheduler": TASK_STATUS_COMPLETE},
    )
    if persistence == PERSISTENCE_CONTINUOUS:
        assert len(eligible) == 1
        assert eligible[0]["capability_authority"] == "unchanged"
    else:
        assert eligible == []


@pytest.mark.parametrize("persistence,proactivity", ALL_COMBINATIONS)
def test_scheduler_tick_records_eligible_agents(autonomy_store, persistence, proactivity):
    profile = create_autonomy_profile(
        name="tick",
        persistence=persistence,
        proactivity=proactivity,
        agent_id=f"agent-{persistence}",
    )
    status = TASK_STATUS_RUNNING if persistence == PERSISTENCE_UNTIL_COMPLETE else TASK_STATUS_COMPLETE
    tick = scheduler_tick(task_status_by_agent={profile.agent_id: status})
    expected = should_remain_scheduled(persistence, task_status=status)
    assert (tick["count"] > 0) is expected
    if expected:
        assert tick["eligible"][0]["scheduler_action"] == "monitor"


@pytest.mark.parametrize("proactivity", PROACTIVITY_MODES)
def test_suggest_only_never_enqueues_without_approval(autonomy_store, proactivity):
    if proactivity != PROACTIVITY_SUGGEST_ONLY:
        return
    assert can_enqueue_executable_work(proactivity, approved=False) is False
    assert can_enqueue_executable_work(proactivity, approved=True) is True


@pytest.mark.parametrize("persistence,proactivity", ALL_COMBINATIONS)
def test_enqueue_matrix(autonomy_store, persistence, proactivity):
    approved = can_enqueue_executable_work(proactivity, approved=False)
    if proactivity == PROACTIVITY_DISABLED:
        assert approved is False
    elif proactivity == PROACTIVITY_SUGGEST_ONLY:
        assert approved is False
    elif proactivity in {PROACTIVITY_CREATE_TASKS, PROACTIVITY_EXECUTE_WITHIN_POLICY}:
        assert approved is True
    else:
        raise AssertionError(f"unexpected proactivity: {proactivity}")


@pytest.mark.parametrize("persistence,proactivity", ALL_COMBINATIONS)
def test_proactive_action_creation_records_required_fields(autonomy_store, persistence, proactivity):
    if proactivity == PROACTIVITY_DISABLED:
        with pytest.raises(ValueError, match="disabled"):
            create_proactive_action(
                parent_agent_id="parent-1",
                trigger="disk_threshold",
                evidence={"usage_percent": 92},
                rationale="Disk nearly full",
                budget={"claim": {"disk_gb": 1}},
                configured_proactivity=proactivity,
                persistence=persistence,
            )
        return

    action = create_proactive_action(
        parent_agent_id="parent-1",
        trigger="disk_threshold",
        evidence={"usage_percent": 92},
        rationale="Disk nearly full",
        budget={"claim": {"disk_gb": 1}},
        configured_proactivity=proactivity,
        persistence=persistence,
        capability="filesystem",
    )
    assert action.parent_agent_id == "parent-1"
    assert action.trigger == "disk_threshold"
    assert action.evidence == {"usage_percent": 92}
    assert action.rationale == "Disk nearly full"
    assert action.budget == {"claim": {"disk_gb": 1}}
    assert action.persistence == persistence

    if proactivity == PROACTIVITY_SUGGEST_ONLY:
        assert action.status == PROACTIVE_STATUS_SUGGESTED
        assert action.requires_approval is True
        assert can_enqueue_executable_work(proactivity, approved=False) is False
    elif proactivity == PROACTIVITY_CREATE_TASKS:
        assert action.status == PROACTIVE_STATUS_PENDING_APPROVAL
        assert action.requires_approval is True
    elif proactivity == PROACTIVITY_EXECUTE_WITHIN_POLICY:
        assert action.status == PROACTIVE_STATUS_QUEUED
        assert action.requires_approval is False


def test_suggest_only_approval_enables_enqueue(autonomy_store):
    action = create_proactive_action(
        parent_agent_id="parent-approve",
        trigger="anomaly",
        evidence={"score": 0.9},
        rationale="Unusual pattern",
        budget={},
        configured_proactivity=PROACTIVITY_SUGGEST_ONLY,
        persistence=PERSISTENCE_CONTINUOUS,
    )
    assert can_enqueue_executable_work(PROACTIVITY_SUGGEST_ONLY, approved=False) is False
    approved = approve_proactive_action(action.id)
    assert approved.status == PROACTIVE_STATUS_QUEUED
    assert can_enqueue_executable_work(PROACTIVITY_SUGGEST_ONLY, approved=True) is True


async def test_execute_within_policy_uses_budget_checks(autonomy_store, monkeypatch):
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: autonomy_store)
    node = await register_localhost_node()

    from app.agent.proactivity import authorize_execute_within_policy

    result = await authorize_execute_within_policy(
        node_id=node.id,
        capability="filesystem",
        budget={"claim": {"cpu_threads": 1}, "ttl_seconds": 30},
    )
    assert result["authorized"] is True
    assert result["capability"] == "filesystem"
    assert "lease" in result
    assert "budget" in result


def test_api_profile_crud_and_effective(client, autonomy_store):
    created = client.post(
        "/api/autonomy/profiles",
        json={
            "name": "monitor",
            "persistence": PERSISTENCE_CONTINUOUS,
            "proactivity": PROACTIVITY_SUGGEST_ONLY,
            "agent_id": "agent-api",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["persistence"] == PERSISTENCE_CONTINUOUS
    assert body["proactivity"] == PROACTIVITY_SUGGEST_ONLY
    assert body["effective"]["can_suggest"] is True
    assert body["effective"]["can_execute_within_policy"] is False

    profile_id = body["id"]
    fetched = client.get(f"/api/autonomy/profiles/{profile_id}")
    assert fetched.status_code == 200
    assert "effective" in fetched.json()


def test_api_away_mode_preserves_persistence_config(client, autonomy_store):
    created = client.post(
        "/api/autonomy/profiles",
        json={
            "name": "away",
            "persistence": PERSISTENCE_CONTINUOUS,
            "proactivity": PROACTIVITY_CREATE_TASKS,
        },
    )
    profile_id = created.json()["id"]

    away = client.put(
        "/api/autonomy/away-mode",
        json={"enabled": True, "pause_proactivity": True, "message": "On vacation"},
    )
    assert away.status_code == 200
    assert away.json()["enabled"] is True

    effective = client.get(f"/api/autonomy/profiles/{profile_id}/effective")
    assert effective.json()["persistence"] == PERSISTENCE_CONTINUOUS
    assert effective.json()["effective_proactivity"] == PROACTIVITY_DISABLED

    profile = client.get(f"/api/autonomy/profiles/{profile_id}")
    assert profile.json()["proactivity"] == PROACTIVITY_CREATE_TASKS


@pytest.mark.parametrize("persistence,proactivity", ALL_COMBINATIONS)
def test_api_modes_endpoint_lists_axes(client, autonomy_store, persistence, proactivity):
    modes = client.get("/api/autonomy/modes")
    assert modes.status_code == 200
    payload = modes.json()
    assert persistence in payload["persistence_modes"]
    assert proactivity in payload["proactivity_modes"]


def test_persistence_until_complete_stops_after_terminal_status(autonomy_store):
    assert should_remain_scheduled(PERSISTENCE_UNTIL_COMPLETE, task_status=TASK_STATUS_RUNNING) is True
    assert should_remain_scheduled(PERSISTENCE_UNTIL_COMPLETE, task_status=TASK_STATUS_COMPLETE) is False
    assert should_remain_scheduled(PERSISTENCE_UNTIL_COMPLETE, task_status=TASK_STATUS_FAILED) is False


def test_persistence_one_shot_not_scheduled_after_complete(autonomy_store):
    assert should_remain_scheduled(PERSISTENCE_ONE_SHOT, task_status=TASK_STATUS_COMPLETE) is False
    assert should_remain_scheduled(PERSISTENCE_ONE_SHOT, task_status=TASK_STATUS_IDLE) is True


def test_away_mode_defaults(autonomy_store):
    away = get_away_mode()
    assert away.enabled is False
    assert away.pause_proactivity is True
