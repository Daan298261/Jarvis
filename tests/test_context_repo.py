from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.memory import (
    ContextRepoError,
    add_entry,
    consolidate_agent,
    diff_versions,
    get_repo,
    list_history,
    revert_mutation,
)
from app.memory.scheduler import rank_nodes_for_consolidation, score_consolidation_node
from app.memory.store import reset_context_repo_store
from app.trajectories.schema import (
    JarvisTrajectoryV1,
    TrajectoryOutcome,
    TrajectoryProvenance,
    TrajectoryVerification,
)
from app.trajectories.store import reset_trajectories_store, save_trajectory


AGENT_ID = "agent-context-test"


@pytest.fixture(autouse=True)
def context_repo_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.memory.store.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.trajectories.store.data_dir", lambda: jarvis_env["tmp"])
    reset_context_repo_store()
    reset_trajectories_store()
    yield jarvis_env["tmp"]
    reset_context_repo_store()
    reset_trajectories_store()


def _verified_trajectory(
    *,
    trajectory_id: str,
    goal: str = "Export quarterly spreadsheet",
    recovery: str = "Use python tool instead of office export",
    failures: list[str] | None = None,
) -> JarvisTrajectoryV1:
    now = datetime.now(timezone.utc).isoformat()
    return JarvisTrajectoryV1(
        trajectory_id=trajectory_id,
        goal=goal,
        task_class="office",
        provenance=TrajectoryProvenance(
            harness="jarvis",
            imported_at=now,
            trusted=True,
        ),
        events=[],
        outcome=TrajectoryOutcome(
            status="completed",
            attempted=True,
            verified=True,
            summary=goal,
        ),
        verification=TrajectoryVerification(attempted=True, passed=True, details="checked"),
        failures=failures or [],
        recovery=recovery,
    )


@pytest.mark.asyncio
async def test_deduplication_skips_identical_lessons():
    trajectory = _verified_trajectory(trajectory_id="traj-dedup-1")
    save_trajectory(trajectory)

    first = await consolidate_agent(AGENT_ID, trajectories=[trajectory])
    second = await consolidate_agent(AGENT_ID, trajectories=[trajectory])

    assert first["created_count"] >= 1
    assert second["created_count"] == 0
    assert second["skipped_duplicates"] >= 1


@pytest.mark.asyncio
async def test_conflicting_evidence_is_flagged_not_overwritten():
    first, _, _ = await add_entry(
        AGENT_ID,
        category="lessons",
        title="Recovery for office",
        content="Use office export wizard",
    )
    second, _, _ = await add_entry(
        AGENT_ID,
        category="lessons",
        title="Recovery for office",
        content="Use python tool instead of office export",
    )

    assert first.id != second.id
    assert second.id in first.conflicts_with or first.id in second.conflicts_with
    repo = await get_repo(AGENT_ID)
    active = [entry for entry in repo.entries if entry.active]
    assert len(active) == 2


@pytest.mark.asyncio
async def test_revert_restores_prior_state():
    entry, _, mutation = await add_entry(
        AGENT_ID,
        category="priorities",
        title="Focus",
        content="Ship RFC-0011 backend",
    )
    await revert_mutation(AGENT_ID, mutation.mutation_id)

    repo = await get_repo(AGENT_ID)
    active = [item for item in repo.entries if item.active]
    assert all(item.id != entry.id for item in active)

    history = await list_history(AGENT_ID)
    assert any(record.action == "revert" for record in history)


@pytest.mark.asyncio
async def test_duplicate_manual_entry_rejected():
    await add_entry(AGENT_ID, category="skills", title="pytest", content="Run python3 -m pytest")
    with pytest.raises(ContextRepoError, match="Duplicate"):
        await add_entry(AGENT_ID, category="skills", title="pytest", content="Run python3 -m pytest")


def test_scheduler_prefers_idle_junior_nodes():
    idle_junior = score_consolidation_node(
        {
            "id": "node-junior",
            "hostname": "junior-1",
            "status": "idle",
            "class": "junior_worker",
            "resources": {"utilization": 0.1},
        }
    )
    busy_senior = score_consolidation_node(
        {
            "id": "node-senior",
            "hostname": "senior-1",
            "status": "busy",
            "class": "senior_worker",
            "resources": {"utilization": 0.9},
        }
    )

    ranked = rank_nodes_for_consolidation(
        [
            {"id": "node-senior", "hostname": "senior-1", "status": "busy", "class": "senior_worker", "resources": {"utilization": 0.9}},
            {"id": "node-junior", "hostname": "junior-1", "status": "idle", "class": "junior_worker", "resources": {"utilization": 0.1}},
        ]
    )

    assert idle_junior["score"] > busy_senior["score"]
    assert ranked[0]["node_id"] == "node-junior"


@pytest.mark.asyncio
async def test_version_snapshots_and_diff():
    await add_entry(AGENT_ID, category="identity", title="Name", content="Jarvis")
    await add_entry(AGENT_ID, category="projects", title="Jarvis", content="Local desktop agent")

    repo = await get_repo(AGENT_ID)
    assert repo.version >= 2

    diff = await diff_versions(AGENT_ID, 1, repo.version)
    assert diff.added
    assert diff.from_version == 1
    assert diff.to_version == repo.version


@pytest.mark.asyncio
async def test_api_inspect_pin_delete_revert(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.auth.authenticate_request", lambda request: True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            f"/api/context-repo/{AGENT_ID}/entries",
            json={"category": "procedures", "title": "Deploy", "content": "Run pytest then build"},
        )
        assert created.status_code == 200
        payload = created.json()
        entry_id = payload["entry"]["id"]
        mutation_id = payload["mutation_id"]

        pinned = await client.post(
            f"/api/context-repo/{AGENT_ID}/entries/{entry_id}/pin",
            json={"pinned": True},
        )
        assert pinned.status_code == 200
        assert pinned.json()["pinned"] is True

        blocked = await client.delete(f"/api/context-repo/{AGENT_ID}/entries/{entry_id}")
        assert blocked.status_code == 400

        reverted = await client.post(f"/api/context-repo/{AGENT_ID}/revert/{mutation_id}")
        assert reverted.status_code == 200

        schedule = await client.get("/api/context-repo/consolidate/schedule-preference")
        assert schedule.status_code == 200
        assert "nodes" in schedule.json()


@pytest.mark.asyncio
async def test_consolidation_uses_verified_trajectories_only():
    verified = _verified_trajectory(trajectory_id="verified-1")
    unverified = _verified_trajectory(trajectory_id="unverified-1", recovery="should not import")
    unverified.outcome.verified = False
    unverified.verification = TrajectoryVerification(attempted=True, passed=False)

    save_trajectory(verified)
    save_trajectory(unverified)

    result = await consolidate_agent(AGENT_ID)
    assert "verified-1" in result["processed_trajectories"]
    assert "unverified-1" not in result["processed_trajectories"]
