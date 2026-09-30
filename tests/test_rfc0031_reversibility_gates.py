"""RFC-0031 reversibility-first action gates — full intent proofs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.policy.approval_grant import (
    decide_approval_request,
    list_grant_audit,
    reject_timeout_pending,
    reset_approval_grants,
    validate_grant_for_action,
)
from app.policy.authorize import AuthorizationResult
from app.policy.levels import AutonomyLevel
from app.policy.reversibility import (
    ReversibilityClass,
    model_attempted_self_confirm,
    resolve_action_effect,
    strip_forgery_confirmation_args,
)
from app.policy.reversibility_gate import (
    evaluate_side_effect,
    register_post_success_undo,
)
from app.policy.semantic_firewall import FirewallOutcome, evaluate_semantic_firewall
from app.policy.undo_journal import (
    apply_undo,
    configure_undo_bound,
    describe_undo,
    get_undo_record,
    list_undo_audit,
    list_undo_records,
    mark_post_state_stale,
    register_composite_undo,
    register_undo_record,
    reset_undo_journal,
)
from app.policy.undo_restore import (
    capture_filesystem_prior,
    capture_prior_for_effect,
    reset_undo_snapshots,
)
from app.tools.base import RiskLevel, ToolResult


@pytest.fixture(autouse=True)
def _rfc0031_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.policy.approval_grant.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.policy.undo_journal.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.policy.undo_restore.data_dir", lambda: tmp_path)
    reset_approval_grants()
    reset_undo_journal()
    reset_undo_snapshots()
    yield
    reset_approval_grants()
    reset_undo_journal()
    reset_undo_snapshots()


def _allow_auth(*_a, **_k) -> AuthorizationResult:
    return AuthorizationResult(
        True, False, "ok", AutonomyLevel.L3_EXECUTE_WITH_GATES, "filesystem.write"
    )


def _deny_auth(*_a, **_k) -> AuthorizationResult:
    return AuthorizationResult(
        False, False, "hard deny", AutonomyLevel.L1_SUGGEST, "filesystem.write"
    )


def test_model_cannot_self_confirm_irreversible(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    decision = evaluate_side_effect(
        "terminal",
        action="run",
        arguments={"command": "rm -rf /important", "confirmed": True, "approve": "yes"},
        risk=RiskLevel.IRREVERSIBLE,
        park_if_needed=True,
    )
    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.self_confirm_attempt is True
    assert decision.pending_approval_id
    assert "ignored" in decision.reason.lower() or decision.parked


def test_forgery_keys_stripped_and_detected():
    raw = {"path": "/tmp/a", "confirmed": True, "approve": "yes", "content": "x"}
    assert model_attempted_self_confirm(raw) is True
    cleaned = strip_forgery_confirmation_args(raw)
    assert "confirmed" not in cleaned
    assert "approve" not in cleaned
    assert cleaned["path"] == "/tmp/a"


def test_unknown_never_treated_as_safely_reversible():
    meta = resolve_action_effect("mystery_tool", action="do", arguments={"target": "x"})
    assert meta.reversibility == ReversibilityClass.UNKNOWN
    assert meta.safely_reversible is False


def test_reversible_filesystem_write_auto_exec_and_undo(monkeypatch, tmp_path):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    target = tmp_path / "notes.txt"
    target.write_text("old-content", encoding="utf-8")
    decision = evaluate_side_effect(
        "filesystem",
        action="write",
        arguments={"action": "write", "path": str(target), "content": "hello"},
        park_if_needed=False,
    )
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.effect.reversibility == ReversibilityClass.REVERSIBLE
    assert decision.effect.snapshot_required is True

    prior = capture_filesystem_prior(str(target))
    assert prior["kind"] == "filesystem_bytes"
    assert prior["existed"] is True
    assert prior["snapshot_path"]
    target.write_text("hello", encoding="utf-8")

    record = register_post_success_undo(
        decision,
        prior_state=prior,
        post_state={"expected_digest": "abc", "current_digest": "abc"},
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
    )
    assert record is not None
    assert record["task_id"] == "task-1"
    assert record["prior_state"]["snapshot_path"]
    preview = describe_undo(record["id"])
    assert "undo" in preview["will_reverse"].lower() or "filesystem" in preview["will_reverse"].lower()

    applied = apply_undo(record["id"])
    assert applied["status"] == "undone"
    assert target.read_text(encoding="utf-8") == "old-content"


def test_settings_path_reversible_restores_previous(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    saved = {"autonomy": "assist"}

    def _load():
        return SimpleNamespace(autonomy=saved["autonomy"])

    def _save(settings):
        saved["autonomy"] = settings.autonomy

    monkeypatch.setattr("app.config.load_settings", _load)
    monkeypatch.setattr("app.config.save_settings", _save)

    decision = evaluate_side_effect(
        "settings",
        action="update",
        arguments={"action": "update", "path": "autonomy", "value": "assist"},
        park_if_needed=False,
    )
    assert decision.allowed is True
    assert decision.effect.reversibility == ReversibilityClass.REVERSIBLE
    prior = {"kind": "settings_value", "key": "autonomy", "previous_value": "autonomous", "existed": True}
    saved["autonomy"] = "assist"
    record = register_post_success_undo(
        decision,
        prior_state=prior,
        post_state={"expected_digest": "v1", "current_digest": "v1"},
        task_id="t-settings",
    )
    assert record["undo_operation"]
    applied = apply_undo(record["id"])
    assert applied["status"] == "undone"
    assert saved["autonomy"] == "autonomous"


def test_apply_undo_refuses_without_restorable_prior():
    """Never mark undone when reverse cannot run."""
    record = register_undo_record(
        tool_name="filesystem",
        action="write",
        target="/tmp/fake.txt",
        reversibility="REVERSIBLE",
        undo_operation="filesystem.undo_write",
        preconditions=[],
        prior_state={"kind": "metadata_only", "restorable": False, "target": "/tmp/fake.txt"},
        post_state={"expected_digest": "x", "current_digest": "x"},
    )
    result = apply_undo(record["id"])
    assert result["status"] == "not_implemented"
    assert "refuse" in result["reason"].lower() or "restorable" in result["reason"].lower()
    still = get_undo_record(record["id"])
    assert still["status"] == "ready"
    assert still.get("undone_at") is None


def test_snapshot_required_refuses_fake_undo_registration(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    decision = evaluate_side_effect(
        "filesystem",
        action="write",
        arguments={"action": "write", "path": "/workspace/x.txt", "content": "n"},
        park_if_needed=False,
    )
    assert decision.effect.snapshot_required is True
    with pytest.raises(ValueError, match="snapshot_required"):
        register_post_success_undo(
            decision,
            prior_state={"target": "/workspace/x.txt", "tool_name": "filesystem"},
            post_state={},
        )


def test_snapshot_required_captures_prior_bytes_before_mutation(tmp_path):
    target = tmp_path / "doc.txt"
    target.write_text("before", encoding="utf-8")
    prior = capture_prior_for_effect(
        "filesystem",
        action="write",
        arguments={"action": "write", "path": str(target), "content": "after"},
        snapshot_required=True,
    )
    assert prior["kind"] == "filesystem_bytes"
    assert prior["existed"] is True
    assert Path(prior["snapshot_path"]).read_text(encoding="utf-8") == "before"
    # Mutate after capture — snapshot must still hold prior bytes.
    target.write_text("after", encoding="utf-8")
    assert Path(prior["snapshot_path"]).read_text(encoding="utf-8") == "before"


def test_destructive_requires_real_approval_grant(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    decision = evaluate_side_effect(
        "filesystem",
        action="delete",
        arguments={"action": "delete", "path": "/workspace/secret.txt", "confirmed": True},
        park_if_needed=True,
    )
    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.effect.reversibility == ReversibilityClass.IRREVERSIBLE
    pending_id = decision.pending_approval_id
    assert pending_id

    # Model channel cannot create a grant
    with pytest.raises(PermissionError):
        decide_approval_request(
            pending_id,
            decision="allow_once",
            origin_channel="model",
            actor="qwen",
        )

    outcome = decide_approval_request(
        pending_id,
        decision="allow_once",
        origin_channel="ui",
        actor="owner",
        session_id="sess-1",
    )
    grant = outcome["grant"]
    assert grant["action_id"] == decision.action_id
    assert grant["origin_channel"] == "ui"
    assert grant["actor"] == "owner"
    assert grant["policy_version"]
    assert grant["expires_at"]
    assert grant["decision"] == "allow_once"

    allowed = evaluate_side_effect(
        "filesystem",
        action="delete",
        arguments={"action": "delete", "path": "/workspace/secret.txt"},
        grant_id=grant["id"],
        park_if_needed=False,
    )
    assert allowed.allowed is True
    assert allowed.grant_id == grant["id"]


def test_credential_and_external_gates(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    cred = evaluate_side_effect(
        "vault_memory",
        action="reveal",
        arguments={"action": "reveal", "path": "api_token", "confirmed": True},
        park_if_needed=True,
    )
    assert cred.requires_approval is True
    assert cred.effect.credential_effect is True

    external = evaluate_side_effect(
        "web_fetch",
        action="get",
        arguments={"url": "https://example.com/pay"},
        park_if_needed=True,
    )
    assert external.requires_approval is True
    assert external.effect.external_side_effect is True or external.effect.high_consequence


def test_timeout_and_reject(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    decision = evaluate_side_effect(
        "terminal",
        arguments={"command": "format C:"},
        risk=RiskLevel.IRREVERSIBLE,
        park_if_needed=True,
    )
    pending_id = decision.pending_approval_id
    rejected = decide_approval_request(
        pending_id,
        decision="deny",
        origin_channel="api",
        actor="owner",
    )
    assert rejected["status"] == "rejected"
    assert rejected["grant"] is None

    decision2 = evaluate_side_effect(
        "terminal",
        arguments={"command": "format D:"},
        risk=RiskLevel.IRREVERSIBLE,
        park_if_needed=True,
    )
    timed = reject_timeout_pending(decision2.pending_approval_id)
    assert timed["status"] == "timeout"
    with pytest.raises(TimeoutError):
        decide_approval_request(
            decision2.pending_approval_id,
            decision="allow_once",
            origin_channel="ui",
            actor="owner",
        )


def test_stale_undo_preconditions_conflict():
    record = register_undo_record(
        tool_name="filesystem",
        action="write",
        target="/tmp/x.txt",
        reversibility="REVERSIBLE",
        undo_operation="filesystem.undo_write",
        preconditions=["post_state_matches"],
        prior_state={"text": "old"},
        post_state={"expected_digest": "aaa", "current_digest": "aaa"},
        task_id="t1",
        run_id="r1",
        step_id="s1",
    )
    mark_post_state_stale(record["id"], current_digest="bbb")
    result = apply_undo(record["id"])
    assert result["status"] == "conflict"
    assert "stale" in result["reason"].lower() or "digest" in result["reason"].lower()


def test_composite_rollback_reverse_order():
    parent = register_composite_undo(
        tool_name="filesystem",
        action="bulk_write",
        target="/workspace/bundle",
        task_id="t-bulk",
        run_id="r-bulk",
        step_id="s-bulk",
        children=[
            {
                "target": "/workspace/a.txt",
                "undo_operation": "restore_a",
                "order": 1,
                "summary": "child a",
                "post_state": {"expected_digest": "1", "current_digest": "1"},
            },
            {
                "target": "/workspace/b.txt",
                "undo_operation": "restore_b",
                "order": 2,
                "summary": "child b",
                "post_state": {"expected_digest": "2", "current_digest": "2"},
            },
            {
                "target": "/workspace/c.txt",
                "undo_operation": "restore_c",
                "order": 3,
                "summary": "child c",
                "post_state": {"expected_digest": "3", "current_digest": "3"},
            },
        ],
    )
    preview = describe_undo(parent["id"])
    assert len(preview["children_reverse_order"]) == 3
    assert preview["children_reverse_order"][0]["undo_operation"] == "restore_c"
    assert preview["children_reverse_order"][-1]["undo_operation"] == "restore_a"

    seen: list[str] = []

    def _exec(row):
        seen.append(row["undo_operation"])
        return {}

    result = apply_undo(parent["id"], executor=_exec)
    assert result["status"] == "undone"
    assert result["order"] == "reverse_dependency"
    assert seen == ["restore_c", "restore_b", "restore_a"]


def test_firewall_deny_not_overridden_by_reversibility(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _deny_auth)
    decision = evaluate_side_effect(
        "filesystem",
        action="write",
        arguments={"action": "write", "path": "/workspace/x.txt", "content": "n"},
        park_if_needed=False,
    )
    assert decision.allowed is False
    assert decision.requires_approval is False
    assert "hard deny" in decision.reason


def test_firewall_runs_before_reversibility_and_can_require_approval(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    effect = resolve_action_effect(
        "filesystem", action="delete", arguments={"action": "delete", "path": "/x"}
    )
    fw = evaluate_semantic_firewall(
        tool_name="filesystem",
        action="delete",
        arguments={"action": "delete", "path": "/x"},
        effect=effect,
    )
    assert fw.outcome == FirewallOutcome.REQUIRE_APPROVAL


def test_compensatable_declares_compensation_metadata():
    meta = resolve_action_effect(
        "filesystem",
        action="restore",
        arguments={"action": "restore", "snapshot_id": "snap1", "destination": "/workspace/out"},
    )
    assert meta.reversibility == ReversibilityClass.COMPENSATABLE
    assert meta.compensation is not None
    assert meta.compensation.operation
    assert meta.compensation.preconditions
    assert meta.compensation.has_external_effects is False


def test_undo_history_bounded_no_secret_blobs():
    configure_undo_bound(5)
    for i in range(12):
        register_undo_record(
            tool_name="settings",
            action="update",
            target=f"key-{i}",
            reversibility="REVERSIBLE",
            undo_operation="settings.restore_previous",
            preconditions=["previous_value_recorded"],
            prior_state={"password": "super-secret", "value": "old"},
            post_state={"value": "new"},
        )
    rows = list_undo_records(limit=100)
    assert len(rows) <= 5
    for row in rows:
        prior = row.get("prior_state") or {}
        if "password" in prior:
            assert prior["password"].get("redacted") is True


def test_audit_records_without_secrets(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    decision = evaluate_side_effect(
        "filesystem",
        action="delete",
        arguments={"action": "delete", "path": "/workspace/a", "password": "nope"},
        park_if_needed=True,
    )
    decide_approval_request(
        decision.pending_approval_id,
        decision="deny",
        origin_channel="decision_inbox",
        actor="owner",
    )
    register_undo_record(
        tool_name="filesystem",
        action="write",
        target="/workspace/b",
        reversibility="REVERSIBLE",
        undo_operation="undo",
        preconditions=[],
        prior_state={"token": "abc"},
    )
    outcome = apply_undo(list_undo_records()[0]["id"])
    # Non-restorable prior must refuse — never fake undone.
    assert outcome["status"] == "not_implemented"
    grant_events = list_grant_audit()
    undo_events = list_undo_audit()
    blob = str(grant_events) + str(undo_events)
    assert "nope" not in blob
    assert "abc" not in blob or "redacted" in str(list_undo_records())
    assert any(e.get("kind") == "undo_not_implemented" for e in undo_events)


def test_grant_validation_rejects_wrong_scope(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    decision = evaluate_side_effect(
        "filesystem",
        action="delete",
        arguments={"action": "delete", "path": "/workspace/one.txt"},
        park_if_needed=True,
    )
    outcome = decide_approval_request(
        decision.pending_approval_id,
        decision="allow_once",
        origin_channel="ui",
        actor="owner",
    )
    grant_id = outcome["grant"]["id"]
    assert (
        validate_grant_for_action(
            grant_id,
            action_id=decision.action_id,
            tool_name="filesystem",
            target="/workspace/other.txt",
        )
        is None
    )


def test_tool_effect_metadata_exposed():
    from app.tools.filesystem import FilesystemTool

    tool = FilesystemTool(lambda: {})
    meta = tool.effect_metadata(action="write", arguments={"action": "write", "path": "/x"})
    assert meta["reversibility"] == "REVERSIBLE"
    delete_meta = tool.effect_metadata(action="delete", arguments={"action": "delete", "path": "/x"})
    assert delete_meta["reversibility"] == "IRREVERSIBLE"


@pytest.mark.asyncio
async def test_loop_snapshot_required_fail_closed_when_capture_fails(jarvis_env, monkeypatch):
    from app.agent.loop import AGENT
    from app.policy.authorize import AuthorizationResult
    from app.policy.levels import AutonomyLevel

    monkeypatch.setattr(
        "app.agent.loop.gate_tool_call",
        lambda *a, **k: AuthorizationResult(
            True, False, "ok", AutonomyLevel.L3_EXECUTE_WITH_GATES, "filesystem.write"
        ),
    )
    monkeypatch.setattr(
        "app.agent.loop.capture_prior_for_effect",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    execute_mock = AsyncMock(return_value=ToolResult(True, "should not run"))
    monkeypatch.setattr("app.agent.loop.REGISTRY.execute", execute_mock)

    observation, _ = await AGENT._execute_tool_ex(
        "task-snap-fail",
        "filesystem",
        {"action": "write", "path": str(jarvis_env["tmp"] / "x.txt"), "content": "n"},
        "autonomous",
        jarvis_env["settings"],
    )
    execute_mock.assert_not_awaited()
    assert observation.startswith("ERROR:")
    assert "snapshot" in observation.lower()
    assert "snapshot_capture_failed" in observation


@pytest.mark.asyncio
async def test_loop_undo_registration_failure_is_not_swallowed(jarvis_env, monkeypatch):
    from app.agent.loop import AGENT
    from app.policy.authorize import AuthorizationResult
    from app.policy.levels import AutonomyLevel

    monkeypatch.setattr(
        "app.agent.loop.gate_tool_call",
        lambda *a, **k: AuthorizationResult(
            True, False, "ok", AutonomyLevel.L3_EXECUTE_WITH_GATES, "filesystem.write"
        ),
    )
    target = jarvis_env["tmp"] / "reg.txt"
    target.write_text("prior", encoding="utf-8")
    monkeypatch.setattr(
        "app.agent.loop.register_post_success_undo",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("journal write failed")),
    )
    execute_mock = AsyncMock(return_value=ToolResult(True, "Wrote file"))
    monkeypatch.setattr("app.agent.loop.REGISTRY.execute", execute_mock)
    published: list[tuple] = []

    async def _pub(task_id, kind, title, detail="", **kw):
        published.append((kind, title, detail))

    monkeypatch.setattr("app.agent.loop.BUS.publish", _pub)

    observation, _ = await AGENT._execute_tool_ex(
        "task-undo-reg-fail",
        "filesystem",
        {"action": "write", "path": str(target), "content": "new"},
        "autonomous",
        jarvis_env["settings"],
    )
    execute_mock.assert_awaited()
    assert "Undo registration failed" in observation
    assert "undo_registration_failed" in observation
    assert any(item[0] == "error" and "Undo registration failed" in item[1] for item in published)


@pytest.mark.asyncio
async def test_loop_filesystem_write_registers_restorable_undo_and_apply(jarvis_env, monkeypatch):
    from app.agent.loop import AGENT
    from app.policy.authorize import AuthorizationResult
    from app.policy.levels import AutonomyLevel

    monkeypatch.setattr(
        "app.agent.loop.gate_tool_call",
        lambda *a, **k: AuthorizationResult(
            True, False, "ok", AutonomyLevel.L3_EXECUTE_WITH_GATES, "filesystem.write"
        ),
    )
    target = jarvis_env["tmp"] / "live.txt"
    target.write_text("alpha", encoding="utf-8")

    async def _execute(name, arguments, **_kw):
        assert name == "filesystem"
        Path(arguments["path"]).write_text(arguments["content"], encoding="utf-8")
        return ToolResult(True, f"Wrote {arguments['path']}")

    monkeypatch.setattr("app.agent.loop.REGISTRY.execute", _execute)
    observation, _ = await AGENT._execute_tool_ex(
        "task-live-undo",
        "filesystem",
        {"action": "write", "path": str(target), "content": "beta"},
        "autonomous",
        jarvis_env["settings"],
    )
    assert "ERROR:" not in observation
    assert target.read_text(encoding="utf-8") == "beta"
    rows = list_undo_records(task_id="task-live-undo", ready_only=True)
    assert rows
    assert rows[0]["prior_state"]["kind"] == "filesystem_bytes"
    assert rows[0]["prior_state"]["snapshot_path"]
    applied = apply_undo(rows[0]["id"])
    assert applied["status"] == "undone"
    assert target.read_text(encoding="utf-8") == "alpha"
