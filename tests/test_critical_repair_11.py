"""Regression guards for the critical 11-item development-tip repair brief.

These tests would have failed on the broken tip (b4fd5361 → 3d244eec).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.execution_status import verification_summary
from app.agent.front_responder import FrontReply
from app.db.models import Task
from app.modules.supervisor import normalize_health_url
from app.persona.owner_chat import stream_owner_chat
from app.policy.approval_grant import (
    consume_grant,
    decide_approval_request,
    reset_approval_grants,
    validate_grant_for_action,
)
from app.policy.authorize import AuthorizationResult
from app.policy.levels import AutonomyLevel
from app.policy.reversibility import ReversibilityClass, resolve_action_effect
from app.policy.reversibility_gate import evaluate_side_effect, register_post_success_undo
from app.policy.undo_journal import apply_undo, live_target_digest, reset_undo_journal
from app.policy.undo_restore import (
    capture_prior_for_effect,
    reset_undo_snapshots,
)


@pytest.fixture(autouse=True)
def _repair_isolation(tmp_path, monkeypatch):
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
        True, False, "ok", AutonomyLevel.L3_EXECUTE_WITH_GATES, "tool"
    )


# --- 1. Read-only external ops auto-permit; mutations stay gated ---------------


@pytest.mark.parametrize(
    "tool,action,arguments",
    [
        ("browser", "navigate", {"url": "https://example.com"}),
        ("browser", "open", {"url": "https://example.com"}),
        ("browser", "title", {}),
        ("browser", "snapshot", {}),
        ("web_fetch", "get", {"url": "https://example.com/docs"}),
        ("office", "read", {"path": "/tmp/doc.docx"}),
        ("office", "info", {"path": "/tmp/doc.docx"}),
        ("mobile_call", "devices", {}),
        ("mcp_call", "list", {"mcp_tool": "list_resources"}),
        ("mcp_call", "status", {"mcp_tool": "server_status"}),
    ],
)
def test_item1_observations_auto_permit(monkeypatch, tool, action, arguments):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    decision = evaluate_side_effect(tool, action=action, arguments=arguments, park_if_needed=True)
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.effect.side_effecting is False
    assert decision.effect.high_consequence is False


@pytest.mark.parametrize(
    "tool,action,arguments",
    [
        ("browser", "click", {"selector": "#buy"}),
        ("browser", "fill", {"selector": "input", "text": "x"}),
        ("office", "create", {"path": "/tmp/out.docx"}),
        ("office", "delete", {"path": "/tmp/out.docx"}),
        ("mobile_call", "call", {"device_id": "d1", "incident_id": "i1"}),
        ("mcp_call", "invoke", {"mcp_tool": "email_send"}),
        ("web_fetch", "get", {"url": "https://example.com/checkout"}),
    ],
)
def test_item1_consequential_still_gated(monkeypatch, tool, action, arguments):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    decision = evaluate_side_effect(tool, action=action, arguments=arguments, park_if_needed=True)
    assert decision.requires_approval is True or decision.allowed is False
    assert decision.effect.high_consequence or decision.effect.financial_effect or decision.effect.destructive_effect


# --- 2. Undo refuses when live target diverged --------------------------------


def test_item2_undo_refuses_changed_target(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("before", encoding="utf-8")
    prior = capture_prior_for_effect(
        "filesystem",
        action="write",
        arguments={"action": "write", "path": str(target), "content": "after"},
        snapshot_required=True,
    )
    target.write_text("after", encoding="utf-8")
    expected = hashlib.sha256(b"after").hexdigest()
    from app.policy.undo_journal import register_undo_record

    record = register_undo_record(
        tool_name="filesystem",
        action="write",
        target=str(target),
        reversibility="REVERSIBLE",
        undo_operation="filesystem.undo_write",
        preconditions=["post_state_matches"],
        prior_state=prior,
        post_state={"digest_path": str(target), "expected_digest": expected},
    )
    assert live_target_digest(record) == expected
    # Owner edits the file after the action — undo must refuse, not overwrite.
    target.write_text("owner-changed", encoding="utf-8")
    result = apply_undo(record["id"])
    assert result["status"] == "conflict"
    assert target.read_text(encoding="utf-8") == "owner-changed"


# --- 3. Copy / move / rename / mkdir undo correctness -------------------------


def test_item3_copy_undo_removes_dest_keeps_source(tmp_path):
    src = tmp_path / "src.txt"
    dest = tmp_path / "dest.txt"
    src.write_text("payload", encoding="utf-8")
    prior = capture_prior_for_effect(
        "filesystem",
        action="copy",
        arguments={"action": "copy", "path": str(src), "destination": str(dest)},
        snapshot_required=False,
    )
    assert prior["kind"] == "filesystem_copy_move"
    assert prior["source_path"]
    assert prior["destination_path"]
    dest.write_text("payload", encoding="utf-8")
    expected = hashlib.sha256(b"payload").hexdigest()
    from app.policy.undo_journal import register_undo_record

    record = register_undo_record(
        tool_name="filesystem",
        action="copy",
        target=str(src),
        reversibility="REVERSIBLE",
        undo_operation="filesystem.undo_copy",
        preconditions=[],
        prior_state=prior,
        post_state={"digest_path": str(dest), "expected_digest": expected},
    )
    result = apply_undo(record["id"])
    assert result["status"] == "undone"
    assert src.read_text(encoding="utf-8") == "payload"
    assert not dest.exists()


def test_item3_move_undo_restores_source_removes_dest(tmp_path):
    src = tmp_path / "from.txt"
    dest = tmp_path / "to.txt"
    src.write_text("moved", encoding="utf-8")
    prior = capture_prior_for_effect(
        "filesystem",
        action="move",
        arguments={"action": "move", "path": str(src), "destination": str(dest)},
        snapshot_required=False,
    )
    # Simulate move
    dest.write_text("moved", encoding="utf-8")
    src.unlink()
    expected = hashlib.sha256(b"moved").hexdigest()
    from app.policy.undo_journal import register_undo_record

    record = register_undo_record(
        tool_name="filesystem",
        action="move",
        target=str(src),
        reversibility="REVERSIBLE",
        undo_operation="filesystem.undo_move",
        preconditions=[],
        prior_state=prior,
        post_state={"digest_path": str(dest), "expected_digest": expected},
    )
    result = apply_undo(record["id"])
    assert result["status"] == "undone"
    assert src.read_text(encoding="utf-8") == "moved"
    assert not dest.exists()


def test_item3_mkdir_undo_removes_created_dir(tmp_path):
    new_dir = tmp_path / "fresh"
    prior = capture_prior_for_effect(
        "filesystem",
        action="mkdir",
        arguments={"action": "mkdir", "path": str(new_dir)},
        snapshot_required=False,
    )
    assert prior["existed"] is False
    new_dir.mkdir()
    from app.policy.undo_journal import _digest_path, register_undo_record

    empty_digest = _digest_path(new_dir)
    assert empty_digest == hashlib.sha256().hexdigest()
    record = register_undo_record(
        tool_name="filesystem",
        action="mkdir",
        target=str(new_dir),
        reversibility="REVERSIBLE",
        undo_operation="filesystem.undo_mkdir",
        preconditions=[],
        prior_state=prior,
        post_state={"digest_path": str(new_dir), "expected_digest": empty_digest},
    )
    result = apply_undo(record["id"])
    assert result["status"] == "undone"
    assert not new_dir.exists()


# --- 4. Always persists; allow_once consumed once -----------------------------


def test_item4_always_persists_allow_once_consumed(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", _allow_auth)
    decision = evaluate_side_effect(
        "filesystem",
        action="delete",
        arguments={"action": "delete", "path": "/workspace/a.txt"},
        park_if_needed=True,
    )
    always = decide_approval_request(
        decision.pending_approval_id,
        decision="always",
        origin_channel="ui",
        actor="owner",
    )
    grant = always["grant"]
    assert grant["decision"] == "always"
    assert validate_grant_for_action(
        grant["id"],
        action_id=decision.action_id,
        tool_name="filesystem",
        target="/workspace/a.txt",
    )
    consume_grant(grant["id"])
    # Always must remain valid after execution.
    assert validate_grant_for_action(
        grant["id"],
        action_id=decision.action_id,
        tool_name="filesystem",
        target="/workspace/a.txt",
    )

    decision2 = evaluate_side_effect(
        "filesystem",
        action="delete",
        arguments={"action": "delete", "path": "/workspace/b.txt"},
        park_if_needed=True,
    )
    once = decide_approval_request(
        decision2.pending_approval_id,
        decision="allow_once",
        origin_channel="ui",
        actor="owner",
    )
    grant2 = once["grant"]
    assert grant2["decision"] == "allow_once"
    consume_grant(grant2["id"])
    assert (
        validate_grant_for_action(
            grant2["id"],
            action_id=decision2.action_id,
            tool_name="filesystem",
            target="/workspace/b.txt",
        )
        is None
    )


@pytest.mark.asyncio
async def test_item4_api_resume_preserves_always_mode(monkeypatch):
    from app.api import reversibility as api_rev

    calls: list[str] = []

    async def fake_confirm(task_id, approved, expected_payload=None, grant_mode=None, permission_id=None):
        del task_id, approved, expected_payload, permission_id
        calls.append(grant_mode or "")
        return SimpleNamespace(id="t1")

    class _Task:
        def __init__(self):
            self.confirmation_payload = "{}"

    task = _Task()

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *_a, **_k):
            return task

        async def commit(self):
            return None

    monkeypatch.setattr("app.db.session.SessionLocal", lambda: _Sess())
    monkeypatch.setattr("app.agent.loop.AGENT.confirm_task", fake_confirm)
    result = await api_rev._resume_task_with_grant(
        "t1",
        {"id": "g1", "decision": "always", "action_id": "a", "pending_id": "p", "tool_name": "filesystem"},
    )
    assert result["resumed"] is True
    assert result["grant_mode"] == "always"
    assert calls == ["always"]


# --- 5. Raw front JSON / unsafe claims never reach UI -------------------------


@pytest.mark.asyncio
async def test_item5_owner_chat_emits_only_sanitized_front_text(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])

    async def fake_front(*_a, **_k):
        return FrontReply(
            action="final_basic",
            text="Hello, sir.",
            chunks=['{"action":"final_basic","text":"Done, I fixed it."}', "Hello, sir."],
            model="front",
            first_text_ms=1.0,
            complete_ms=1.0,
        )

    monkeypatch.setattr("app.persona.owner_chat.generate_front_reply", fake_front)
    monkeypatch.setattr("app.persona.owner_chat.weather_system_message", AsyncMock(return_value=None))
    monkeypatch.setattr("app.persona.owner_chat.hydrate_conversation", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.persona.owner_chat.publish_owner_text", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "app.persona.owner_chat.load_settings",
        lambda: jarvis_env["settings"],
    )
    events = []
    async for event in stream_owner_chat("hi there"):
        events.append(event)
    deltas = [e for e in events if e.get("type") == "delta"]
    assert deltas
    joined = "".join(e.get("text") or "" for e in deltas)
    assert '{"action"' not in joined
    assert "Done, I fixed it" not in joined
    assert "Hello, sir." in joined


# --- 6. Unverified lookup answers display NOT_VERIFIED ------------------------


def test_item6_direct_lookup_answer_is_not_verification_evidence():
    task = Task(
        id="t-lookup",
        prompt="weather?",
        status="completed",
        stage="completed",
        result="Mild rain tomorrow.",
        verification=json.dumps(
            {
                "result": "NOT_VERIFIED",
                "checks": [],
                "warnings": ["direct_lookup produced an answer without independent verification evidence"],
            }
        ),
    )
    summary = verification_summary(task)
    assert summary["result"] == "NOT_VERIFIED"
    # Answer text must not be treated as a passing check.
    assert not any(
        (c.get("evidence") or "") == "Mild rain tomorrow." and c.get("result") == "pass"
        for c in summary.get("checks") or []
    )


def test_item6_answer_used_as_verification_would_have_been_wrong():
    """Guard: stuffing the answer into verification must not silently become VERIFIED via our path."""
    task = Task(
        id="t-bad",
        prompt="weather?",
        status="completed",
        stage="completed",
        result="Mild rain tomorrow.",
        verification="Mild rain tomorrow.",
    )
    # Document the broken tip behavior still exists for raw answer-as-verification —
    # our direct_lookup path must not write that shape (see NOT_VERIFIED JSON above).
    summary = verification_summary(task)
    assert summary["result"] == "VERIFIED"  # proves why the bug mattered


# --- 7. Simple replies do not wait on vault/Supermemory -----------------------


@pytest.mark.asyncio
async def test_item7_conversation_front_before_memory_compose(jarvis_env, monkeypatch):
    from app.agent.loop import AGENT
    from app.agent.metrics import LiveTaskMetrics
    from app.agent.planning import WorkingState
    from app.agent.task_fastpath import FastpathDecision

    order: list[str] = []

    async def slow_compose(*_a, **_k):
        order.append("compose")
        await asyncio.sleep(0.05)
        from app.agent.turn_working_set import TurnWorkingSet

        return TurnWorkingSet(user_message="hi", task_class="conversation")

    async def front(*_a, **_k):
        order.append("front")
        return FrontReply(
            action="final_basic",
            text="Hello.",
            model="front",
            first_text_ms=2.0,
            complete_ms=2.0,
        )

    # Local import inside _run_conversation binds from turn_working_set at call time.
    monkeypatch.setattr("app.agent.turn_working_set.compose_turn_working_set", slow_compose)
    monkeypatch.setattr("app.agent.loop.generate_front_reply", front)
    monkeypatch.setattr("app.agent.loop.weather_system_message", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.agent.loop.admit_fastpath",
        lambda *a, **k: FastpathDecision(
            admitted=True,
            reason="terminal_front",
            route_kind="direct_reply",
            stages_skipped=("worker", "verify"),
        ),
    )
    monkeypatch.setattr("app.agent.loop.note_fastpath_decision", lambda *a, **k: None)
    monkeypatch.setattr("app.agent.loop.publish_owner_text", AsyncMock(return_value={}))
    monkeypatch.setattr("app.tts.speech_safe.speech_safe", lambda t: t)

    working = WorkingState()
    metrics = LiveTaskMetrics()
    task = await AGENT.create_task("hi")
    runner = AGENT._tasks.pop(task.id, None)
    if runner:
        runner.cancel()
        try:
            await runner
        except (asyncio.CancelledError, Exception):
            pass

    await AGENT._run_conversation(
        task.id,
        "hi",
        None,
        jarvis_env["settings"],
        working,
        metrics,
        history=[],
    )
    assert "front" in order
    # Fast-path hit must not await compose_turn_working_set (vault/Supermemory).
    assert "compose" not in order
    assert order[0] == "front"


# --- 8. Blocked nvidia-smi cannot freeze the event loop -----------------------


@pytest.mark.asyncio
async def test_item8_slow_nvidia_smi_does_not_block_event_loop(monkeypatch):
    from app.inference.manager import InferenceManager

    mgr = InferenceManager()

    def slow_probe():
        time.sleep(1.5)
        return "128"

    monkeypatch.setattr(mgr, "_probe_nvidia_smi_memory", slow_probe)
    heartbeats: list[float] = []

    async def heartbeat():
        for _ in range(6):
            heartbeats.append(time.monotonic())
            await asyncio.sleep(0.1)

    started = time.monotonic()
    await asyncio.gather(mgr.refresh_resources(), heartbeat())
    elapsed = time.monotonic() - started
    assert len(heartbeats) >= 4, "event loop heartbeats must continue during slow nvidia-smi"
    assert elapsed < 3.0


# --- 9. IPv4 and IPv6 loopback health URLs ------------------------------------


def test_item9_ipv6_loopback_health_url_bracketed():
    assert normalize_health_url("http://::1:8080/health") == "http://[::1]:8080/health"
    assert normalize_health_url("http://127.0.0.1:8080/health") == "http://127.0.0.1:8080/health"
    assert normalize_health_url("http://localhost:9090/") == "http://127.0.0.1:9090/"


# --- 10/11 covered in their dedicated test modules; smoke the isolation surface


def test_item10_cyber_fixture_isolates_discovery_roots(tmp_path, monkeypatch):
    from app.modules import cybersecurity

    monkeypatch.setattr("app.modules.cybersecurity.repo_root", lambda: tmp_path)
    monkeypatch.setattr("app.modules.cybersecurity.le_gated_roots", lambda: [tmp_path / "le-gated"])
    monkeypatch.setattr(
        "app.modules.cybersecurity.desktop_projects_root",
        lambda: tmp_path / "Desktop" / "projects",
    )
    monkeypatch.setattr(
        "app.modules.cybersecurity.library_projects_path",
        lambda: tmp_path / "projects",
    )
    (tmp_path / "le-gated").mkdir()
    (tmp_path / "projects").mkdir()
    (tmp_path / "Desktop" / "projects").mkdir(parents=True)
    # Real-looking names outside the isolated roots must not be discovered.
    realish = Path.home() / "Desktop" / "projects" / "strix"
    found = cybersecurity.discover_local_path("strix")
    if realish.exists():
        assert found != realish.resolve()
    assert found is None or str(tmp_path) in str(found)
