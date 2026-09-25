from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings, save_settings
from app.main import app
from app.policy.store import create_profile, reset_policy_store, update_platform_policy
from app.recovery.admission import WriteAdmissionError, assert_write_allowed
from app.recovery.checkpoint import create_checkpoint, verify_and_promote_checkpoint
from app.recovery.hooks import skip_journal, startup_recovery
from app.recovery.journal import (
    corrupt_entry_hash,
    journal_mutate,
    list_journal_entries,
    reconcile_pending_entries,
    simulate_crash_after_apply,
    verify_journal_chain,
)
from app.recovery.redaction import redact_settings_control_plane
from app.recovery.resources import capture_policy_profiles, full_snapshot
from app.recovery.rollback import (
    apply_rollback,
    build_rollback_plan,
    get_rollback_status,
    resume_or_apply_rollback,
    start_rollback_run,
)
from app.recovery.store import configure_recovery_db, reset_recovery_db
from app.recovery.types import CheckpointTag, JournalOperation, RESOURCE_POLICY_PROFILES


@pytest.fixture
def recovery_env(jarvis_env, monkeypatch):
    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.config.data_dir", lambda: tmp)
    monkeypatch.setattr("app.policy.store.data_dir", lambda: tmp)
    monkeypatch.setattr("app.recovery.store.data_dir", lambda: tmp)
    monkeypatch.setattr("app.agent.workflows.data_dir", lambda: tmp)
    monkeypatch.setattr("app.packs.store.data_dir", lambda: tmp)
    configure_recovery_db(tmp / "recovery" / "journal.db")
    reset_recovery_db()
    reset_policy_store()
    yield {"tmp": tmp, "settings": jarvis_env["settings"]}
    reset_recovery_db()
    reset_policy_store()


def test_secret_redaction_in_journal_payload(recovery_env):
    raw = {
        "autonomy": "autonomous",
        "inference": {"api_key": "sk-supersecretvalue123456", "host": "127.0.0.1"},
        "auth_token": "Bearer abc.def.ghi",
    }
    redacted = redact_settings_control_plane(raw)
    assert redacted["inference"]["api_key"]["_ref"] == "redacted"
    assert "sk-super" not in json.dumps(redacted)


def test_journal_mutate_and_chain_integrity(recovery_env):
    seq = journal_mutate(
        resource_class=RESOURCE_POLICY_PROFILES,
        resource_id="test",
        operation=JournalOperation.UPDATE,
        actor="tester",
        before={"profiles": {}},
        after_fn=capture_policy_profiles,
        apply_fn=lambda: None,
        replay_safe=True,
    )
    assert seq >= 1
    ok, detail = verify_journal_chain()
    assert ok, detail
    entries = list_journal_entries()
    assert entries[-1]["replay_safe"] is True


def test_crash_pending_reconcile(recovery_env):
    def apply():
        with skip_journal():
            create_profile(name="crash-profile", interview_answers={"mission": "x"}, actor="test")

    seq = simulate_crash_after_apply(
        resource_class=RESOURCE_POLICY_PROFILES,
        resource_id="crash",
        operation=JournalOperation.CREATE,
        actor="test",
        before=capture_policy_profiles(),
        after=None,
        apply_fn=apply,
    )
    aborted = reconcile_pending_entries()
    assert seq in aborted
    startup = startup_recovery()
    assert startup["aborted_pending_journal_seqs"] == []


def test_corrupt_journal_hash_detected(recovery_env):
    journal_mutate(
        resource_class=RESOURCE_POLICY_PROFILES,
        resource_id="h",
        operation=JournalOperation.UPDATE,
        actor="t",
        before={},
        apply_fn=lambda: None,
    )
    corrupt_entry_hash(1)
    ok, _ = verify_journal_chain()
    assert ok is False


def test_concurrent_mutation_rejected_during_rollback(recovery_env):
    cp = create_checkpoint(tag=CheckpointTag.CANDIDATE, notes="drill")
    good = verify_and_promote_checkpoint(cp["id"])
    create_profile(name="agent-a", interview_answers={"mission": "keep"}, actor="test")
    cp2 = create_checkpoint(tag=CheckpointTag.CANDIDATE, notes="after mutation")
    verify_and_promote_checkpoint(cp2["id"])
    run = start_rollback_run(good["id"])
    resume_or_apply_rollback(run["id"])
    with pytest.raises(WriteAdmissionError):
        assert_write_allowed(RESOURCE_POLICY_PROFILES, "x")
    while get_rollback_status(run["id"]) and not get_rollback_status(run["id"]).get("terminal_status"):
        resume_or_apply_rollback(run["id"])


def test_rollback_plan_preview_fields(recovery_env):
    cp = create_checkpoint(notes="plan")
    verify_and_promote_checkpoint(cp["id"])
    plan = build_rollback_plan(cp["id"], forward_replay=False)
    assert plan["target_checkpoint_id"] == cp["id"]
    assert "affected_resource_classes" in plan
    assert "data_loss_window" in plan
    assert "non_reversible_external_effects" in plan
    assert "reconciliation_entries" in plan


def test_recovery_drill_equivalence(recovery_env):
    cp = create_checkpoint(notes="baseline")
    verify_and_promote_checkpoint(cp["id"])
    baseline = full_snapshot()
    create_profile(name="destruct", interview_answers={"mission": "gone"}, actor="drill")
    update_platform_policy(autonomy_caps={"*": "L0_OBSERVE"}, actor="drill")
    result = apply_rollback(cp["id"])
    assert result["terminal_status"] == "COMPLETE"
    assert full_snapshot() == baseline


def test_failed_verify_never_known_good(recovery_env, monkeypatch):
    cp = create_checkpoint(notes="fail-verify")
    verify_and_promote_checkpoint(cp["id"])
    create_profile(name="x", interview_answers={}, actor="t")
    run = start_rollback_run(cp["id"])

    def boom_snapshot(snapshot):
        return False, {"ok": False, "errors": ["forced"]}

    monkeypatch.setattr("app.recovery.rollback.verify_snapshot", boom_snapshot)
    for _ in range(8):
        st = get_rollback_status(run["id"])
        if st and st.get("terminal_status"):
            break
        resume_or_apply_rollback(run["id"])
    final = get_rollback_status(run["id"])
    assert final["terminal_status"] in {"PARTIAL", "FAILED"}


def test_restart_during_rollback_resumes(recovery_env):
    cp = create_checkpoint(notes="resume")
    verify_and_promote_checkpoint(cp["id"])
    create_profile(name="y", interview_answers={}, actor="t")
    run = start_rollback_run(cp["id"])
    resume_or_apply_rollback(run["id"])
    resumed = get_rollback_status(run["id"])
    assert resumed["phase"] != "PLAN"
    while not get_rollback_status(run["id"]).get("terminal_status"):
        resume_or_apply_rollback(run["id"])
    assert get_rollback_status(run["id"])["terminal_status"] == "COMPLETE"


def test_replay_safe_idempotent_flag(recovery_env):
    journal_mutate(
        resource_class=RESOURCE_POLICY_PROFILES,
        resource_id="idempotent",
        operation=JournalOperation.UPDATE,
        actor="t",
        before={},
        apply_fn=lambda: None,
        replay_safe=True,
    )
    entry = list_journal_entries()[-1]
    assert entry["replay_safe"] is True
    cp = create_checkpoint()
    verify_and_promote_checkpoint(cp["id"])
    plan = build_rollback_plan(cp["id"], forward_replay=True)
    assert isinstance(plan.get("forward_replay_entries"), list)


def test_operator_api_lists_checkpoints_without_secrets(recovery_env):
    settings: AppSettings = recovery_env["settings"]
    settings.inference.api_key = "sk-testkey1234567890"
    with skip_journal():
        save_settings(settings)
    cp = create_checkpoint(notes="api")
    client = TestClient(app)
    resp = client.get("/api/recovery/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "checkpoints" in body
    assert "sk-test" not in resp.text
    assert any(item["id"] == cp["id"] for item in body["checkpoints"])


def test_prune_requires_known_good(recovery_env):
    from app.recovery.prune import prune_journal

    with pytest.raises(ValueError):
        prune_journal()
    cp = create_checkpoint()
    verify_and_promote_checkpoint(cp["id"])
    for _ in range(3):
        journal_mutate(
            resource_class=RESOURCE_POLICY_PROFILES,
            resource_id="p",
            operation=JournalOperation.UPDATE,
            actor="t",
            before={},
            apply_fn=lambda: None,
        )
    result = prune_journal(retain_through_seq=1)
    assert result["pruned"] >= 1
