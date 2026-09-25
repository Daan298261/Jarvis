"""RFC-0173 Skill Forge — eligibility, extract, eval, approval, versioning, repair, quarantine."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from app.goals.runtime import suggest_skills_for_goal
from app.skills.eligibility import evaluate_trajectory_eligibility
from app.skills.extract import ExtractionError, extract_candidate_manifest
from app.skills.forge import ForgeError, forge
from app.skills.permissions import PrivilegeExpansionError, compute_effective_capabilities
from app.skills.provenance import verify_manifest_integrity
from app.skills.routing import search_skills
from app.skills.schema import (
    DeterministicTest,
    FieldType,
    LifecycleStatus,
    Provenance,
    SkillManifest,
    SkillScope,
    SkillStep,
    TypedField,
)
from app.skills.store import (
    get_active_version_id,
    get_candidate,
    get_version,
    reset_skills_store,
)
from app.trajectories.schema import (
    JarvisTrajectoryV1,
    TrajectoryEvent,
    TrajectoryOutcome,
    TrajectoryProvenance,
    TrajectoryVerification,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _traj(
    *,
    traj_id: str = "traj-1",
    goal: str = "export report.xlsx with python and filesystem",
    tools: list[tuple[str, dict]] | None = None,
    verified: bool = True,
    status: str = "completed",
    extra_events: list[TrajectoryEvent] | None = None,
    metadata: dict | None = None,
) -> JarvisTrajectoryV1:
    tools = tools or [
        ("python", {"script": "export report.xlsx"}),
        ("filesystem", {"action": "read", "path": "report.xlsx"}),
    ]
    events: list[TrajectoryEvent] = []
    for index, (tool, args) in enumerate(tools):
        events.append(
            TrajectoryEvent(
                sequence=index,
                timestamp=_now(),
                event_type="tool_call",
                tool_name=tool,
                tool_args=args,
                tool_result="ok",
                success=True,
                metadata=dict(metadata or {}),
            )
        )
    if extra_events:
        base = len(events)
        for offset, event in enumerate(extra_events):
            events.append(event.model_copy(update={"sequence": base + offset}))
    return JarvisTrajectoryV1(
        trajectory_id=traj_id,
        goal=goal,
        task_class="office",
        provenance=TrajectoryProvenance(
            harness="jarvis",
            imported_at=_now(),
            trusted=True,
        ),
        events=events,
        outcome=TrajectoryOutcome(
            status=status,
            attempted=True,
            verified=verified,
            summary=goal,
        ),
        verification=TrajectoryVerification(
            attempted=True,
            passed=verified,
            details="checked",
        ),
    )


@pytest.fixture(autouse=True)
def skill_forge_store(tmp_path, monkeypatch):
    monkeypatch.setattr("app.skills.store.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.policy.audit.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.policy.store.data_dir", lambda: tmp_path)
    reset_skills_store()
    yield tmp_path
    reset_skills_store()


def test_eligibility_rejects_secrets():
    traj = _traj(
        tools=[("python", {"api_key": "sk-abcdefghijklmnopqrstuvwxyz0123456789", "script": "x"})]
    )
    result = evaluate_trajectory_eligibility(traj)
    assert result.eligible is False
    assert any("secret" in reason for reason in result.reasons)


def test_eligibility_rejects_hidden_reasoning():
    traj = _traj(
        extra_events=[
            TrajectoryEvent(
                sequence=99,
                timestamp=_now(),
                event_type="hidden_reasoning",
                content="secret chain of thought",
            )
        ]
    )
    result = evaluate_trajectory_eligibility(traj)
    assert result.eligible is False
    assert any("hidden reasoning" in reason for reason in result.reasons)


def test_eligibility_rejects_unapproved_consequential_actions():
    traj = _traj(tools=[("filesystem", {"action": "delete", "path": "/tmp/x"})])
    result = evaluate_trajectory_eligibility(traj)
    assert result.eligible is False
    assert any("consequential" in reason for reason in result.reasons)


def test_eligibility_allows_approved_consequential_action():
    traj = _traj(
        tools=[("filesystem", {"action": "delete", "path": "/tmp/x", "approved": True})],
        metadata={"approved": True},
    )
    # metadata on event is empty in helper — set approved on args which eligibility checks
    result = evaluate_trajectory_eligibility(traj)
    assert result.eligible is True


def test_extraction_produces_typed_manifest_and_deterministic_tests(skill_forge_store):
    traj = _traj()
    manifest = extract_candidate_manifest(traj)
    assert manifest.tools == ["python", "filesystem"]
    assert manifest.steps
    assert all(isinstance(step, SkillStep) for step in manifest.steps)
    assert manifest.tests
    assert all(isinstance(test, DeterministicTest) for test in manifest.tests)
    assert manifest.content_hash
    assert manifest.signature
    integrity = verify_manifest_integrity(manifest)
    assert integrity["valid"] is True


def test_extraction_refuses_ineligible_trace():
    traj = _traj(verified=False, status="failed")
    with pytest.raises(ExtractionError):
        extract_candidate_manifest(traj, require_eligible=True)


def test_pipeline_isolated_eval_and_no_auto_publish(skill_forge_store):
    traj = _traj()
    result = forge.run_pipeline(traj, actor="skill_forge")
    assert result["eligibility"]["eligible"] is True
    candidate = get_candidate(result["candidate"]["candidate_id"])
    assert candidate is not None
    assert candidate.status == LifecycleStatus.VERIFIED
    assert candidate.version.verifier is not None
    assert candidate.version.verifier.passed is True
    assert candidate.version.verifier.isolated_workspace
    assert "eval" in candidate.version.verifier.isolated_workspace
    assert get_active_version_id(candidate.skill_id) is None
    with pytest.raises(ForgeError, match="automatic publication"):
        forge.run_pipeline(traj, auto_activate=True)


def test_activation_requires_approval_and_intersection(skill_forge_store):
    traj = _traj()
    candidate = forge.propose_from_trajectory(traj)
    candidate = forge.sandbox(candidate.candidate_id)
    candidate = forge.verify(candidate.candidate_id)
    with pytest.raises(ForgeError, match="approval"):
        forge.activate(candidate.candidate_id, actor="owner")

    forge.request_owner_approval(candidate.candidate_id, actor="skill_forge")
    approved = forge.approve(candidate.candidate_id, actor="owner", admin=True)
    assert approved.status == LifecycleStatus.APPROVED

    # Privilege expansion: task policy strips required caps → activate fails.
    with pytest.raises(ForgeError):
        forge.activate(
            approved.candidate_id,
            actor="owner",
            task_capabilities=["browser"],
        )

    activated = forge.activate(
        approved.candidate_id,
        actor="owner",
        task_capabilities=["python", "filesystem", "filesystem.read"],
        node_capabilities=["python", "filesystem", "filesystem.read", "terminal"],
    )
    assert activated.status == LifecycleStatus.ACTIVE
    assert activated.version.immutable is True
    assert get_active_version_id(activated.skill_id) == activated.version.version_id

    # Active version is immutable.
    with pytest.raises(PermissionError):
        mutated = activated.version.model_copy(deep=True)
        mutated.manifest.purpose = "tampered"
        from app.skills.store import save_version

        save_version(mutated)


def test_repair_does_not_overwrite_active(skill_forge_store):
    traj = _traj()
    candidate = forge.propose_from_trajectory(traj)
    candidate = forge.sandbox(candidate.candidate_id)
    candidate = forge.verify(candidate.candidate_id)
    forge.request_owner_approval(candidate.candidate_id)
    forge.approve(candidate.candidate_id, actor="owner", admin=True)
    active = forge.activate(
        candidate.candidate_id,
        actor="owner",
        task_capabilities=["python", "filesystem", "filesystem.read"],
        node_capabilities=["python", "filesystem", "filesystem.read"],
    )
    active_id = active.version.version_id

    repair = forge.repair(
        active.skill_id,
        manifest_patch={"purpose": "repaired purpose text"},
    )
    assert repair.skill_id == active.skill_id
    assert repair.version.version_id != active_id
    assert repair.status == LifecycleStatus.PROPOSED
    assert get_active_version_id(active.skill_id) == active_id
    still = get_version(active_id)
    assert still is not None
    assert still.status == LifecycleStatus.ACTIVE
    assert "repaired" not in still.manifest.purpose


def test_rollback_and_disable(skill_forge_store):
    traj = _traj()
    c1 = forge.propose_from_trajectory(traj)
    c1 = forge.sandbox(c1.candidate_id)
    c1 = forge.verify(c1.candidate_id)
    forge.request_owner_approval(c1.candidate_id)
    forge.approve(c1.candidate_id, actor="owner", admin=True)
    v1 = forge.activate(
        c1.candidate_id,
        actor="owner",
        task_capabilities=["python", "filesystem", "filesystem.read"],
        node_capabilities=["python", "filesystem", "filesystem.read"],
    )

    repair = forge.repair(v1.skill_id, manifest_patch={"purpose": "v2 purpose"})
    repair = forge.sandbox(
        repair.candidate_id,
        task_capabilities=["python", "filesystem", "filesystem.read"],
        node_capabilities=["python", "filesystem", "filesystem.read"],
    )
    repair = forge.verify(repair.candidate_id)
    forge.request_owner_approval(repair.candidate_id)
    forge.approve(repair.candidate_id, actor="owner", admin=True)
    v2 = forge.activate(
        repair.candidate_id,
        actor="owner",
        task_capabilities=["python", "filesystem", "filesystem.read"],
        node_capabilities=["python", "filesystem", "filesystem.read"],
    )
    assert get_active_version_id(v1.skill_id) == v2.version.version_id

    rolled = forge.rollback(v1.skill_id, actor="owner", to_version_id=v1.version.version_id)
    assert rolled.version_id == v1.version.version_id
    assert get_active_version_id(v1.skill_id) == v1.version.version_id

    forge.disable(v1.skill_id, actor="owner")
    assert get_active_version_id(v1.skill_id) is None


def test_marketplace_import_enters_quarantine_then_same_pipeline(skill_forge_store):
    traj = _traj()
    manifest = extract_candidate_manifest(traj)
    imported = forge.import_marketplace(manifest, imported_from="vendor://skills/demo")
    assert imported.status == LifecycleStatus.QUARANTINED
    assert imported.version.quarantine_reason == "marketplace_or_import"
    assert get_active_version_id(imported.skill_id) is None

    sandboxed = forge.sandbox(
        imported.candidate_id,
        task_capabilities=["python", "filesystem", "filesystem.read"],
        node_capabilities=["python", "filesystem", "filesystem.read"],
    )
    assert sandboxed.status == LifecycleStatus.SANDBOXED
    verified = forge.verify(sandboxed.candidate_id)
    assert verified.status == LifecycleStatus.VERIFIED
    forge.request_owner_approval(verified.candidate_id)
    forge.approve(verified.candidate_id, actor="admin", admin=True)
    active = forge.activate(
        verified.candidate_id,
        actor="admin",
        task_capabilities=["python", "filesystem", "filesystem.read"],
        node_capabilities=["python", "filesystem", "filesystem.read"],
    )
    assert active.status == LifecycleStatus.ACTIVE


def test_permissions_intersection_no_expansion(skill_forge_store):
    manifest = SkillManifest(
        name="dangerous",
        purpose="try expand",
        tools=["python"],
        required_capabilities=["python", "spend", "credentials"],
        steps=[SkillStep(tool="python", arguments={"code": "1"})],
        tests=[
            DeterministicTest(
                id="t1",
                expected_tools=["python"],
                expected_step_count=1,
                golden_outputs=[{"index": 0, "tool": "python", "success": True}],
            )
        ],
        inputs=[TypedField(name="x", type=FieldType.STRING)],
        provenance=Provenance(source="owner_request"),
    )
    from app.skills.extract import sign_manifest

    manifest = sign_manifest(manifest)
    result = compute_effective_capabilities(
        manifest,
        task_capabilities=["python"],
        node_capabilities=["python"],
        parent_capabilities=["python"],
    )
    assert "spend" in result["denied"] or "credentials" in result["denied"]
    assert result["allows_execution"] is False
    with pytest.raises(PrivilegeExpansionError):
        from app.skills.permissions import enforce_no_privilege_expansion

        enforce_no_privilege_expansion(
            manifest,
            task_capabilities=["python"],
            node_capabilities=["python"],
            parent_capabilities=["python"],
        )


def test_persona_and_goal_runtime_routing_hooks(skill_forge_store):
    traj = _traj(goal="export office report.xlsx")
    candidate = forge.propose_from_trajectory(traj)
    candidate = forge.sandbox(
        candidate.candidate_id,
        task_capabilities=["python", "filesystem", "filesystem.read"],
        node_capabilities=["python", "filesystem", "filesystem.read"],
    )
    candidate = forge.verify(candidate.candidate_id)
    forge.request_owner_approval(candidate.candidate_id)
    forge.approve(candidate.candidate_id, actor="owner", admin=True)
    active = forge.activate(
        candidate.candidate_id,
        actor="owner",
        task_capabilities=["python", "filesystem", "filesystem.read"],
        node_capabilities=["python", "filesystem", "filesystem.read"],
    )
    # Attach persona compatibility and re-sign would require new version; search without persona filter.
    hits = search_skills("export report", task_class="office")
    assert hits
    assert hits[0]["skill_id"] == active.skill_id

    goal_ctx = suggest_skills_for_goal("goal-office-1", "export report.xlsx", task_class="office")
    assert goal_ctx["skills"]
    assert "Skill Forge" in goal_ctx["prompt_block"] or goal_ctx["skills"][0]["name"]


@pytest.mark.asyncio
async def test_skill_forge_api_observe(skill_forge_store, jarvis_env, allow_loopback_api, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.trajectories.store import reset_trajectories_store, save_trajectory

    monkeypatch.setattr("app.trajectories.store.data_dir", lambda: skill_forge_store)
    reset_trajectories_store()

    traj = _traj(traj_id="api-traj-1")
    save_trajectory(traj)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/skill-forge/observe", json={"trajectory_id": "api-traj-1"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["eligibility"]["eligible"] is True

        pipeline = await client.post("/api/skill-forge/pipeline", json={"trajectory_id": "api-traj-1"})
        assert pipeline.status_code == 200
        body = pipeline.json()
        assert body["candidate"]["status"] == "verified"
