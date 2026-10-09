"""Action gate, Laya-first routing, blue watcher, UFO local endpoint, elevation."""

from __future__ import annotations

from app.decision.adapters import rules
from app.decision.calibration import calibrate, reset as reset_calibration, snapshot as calibration_snapshot
from app.decision.quartermaster import select_provider_order
from app.decision.types import Answer
from app.policy.action_gate import gate_tool_call
from app.policy.authorize import AuthorizationResult
from app.policy.levels import AutonomyLevel
from app.runtime.elevation import is_elevated, snapshot
from app.security.blue_watch import note_tool_outcome
from app.security.red_scenarios import HARM, SCENARIOS
from app.tools.base import RiskLevel
from app.workers.computer import UFOBackend


def _allow(**_k) -> AuthorizationResult:
    return AuthorizationResult(
        True, False, "ok", AutonomyLevel.L3_EXECUTE_WITH_GATES, "filesystem.read"
    )


def test_laya_is_first_when_ready():
    order = select_provider_order("tool_selection", privacy="local_only", laya_ready=True, jev_ready=False)
    assert order[0] == "laya"
    assert "rules" not in order
    assert order[-1] == "generative"
    cloud = select_provider_order("tool_selection", privacy="allow_cloud", laya_ready=True, jev_ready=True)
    assert cloud[0] == "laya"
    assert "jev" in cloud


def test_without_laya_the_model_lane_is_used_not_rules():
    order = select_provider_order("tool_selection", privacy="local_only", laya_ready=False, jev_ready=False)
    assert order[0] == "generative"
    assert "rules" not in order


def test_gate_allows_routine_reads(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", lambda *a, **k: _allow())
    monkeypatch.setattr(
        "app.policy.action_gate.decide",
        lambda *a, **k: type("R", (), {"answers": {}, "fallback_used": True, "provider": "generative"})(),
    )
    result = gate_tool_call("filesystem", action="read", arguments={"path": "notes.txt"})
    assert result.allowed is True


def test_harm_veto_deadline_leaves_room_for_warm_laya(monkeypatch):
    """CPU Laya infer is ~100–150 ms; an 80 ms budget guaranteed generative fallback."""
    from app.policy import action_gate as gate

    seen: dict[str, float] = {}

    def _capture(state, questions, decision_class, deadline_ms=None, privacy="local_only", *args, **_k):
        del state, questions, privacy, args
        seen["deadline_ms"] = float(deadline_ms if deadline_ms is not None else 0.0)
        seen["decision_class"] = decision_class
        return type("R", (), {"answers": {}, "fallback_used": False, "provider": "laya"})()

    monkeypatch.setattr("app.policy.reversibility_gate.authorize", lambda *a, **k: _allow())
    monkeypatch.setattr("app.policy.action_gate.decide", _capture)
    result = gate_tool_call("filesystem", action="read", arguments={"path": "notes.txt"})
    assert result.allowed is True
    assert seen["decision_class"] == "harm_veto"
    assert seen["deadline_ms"] >= 800.0
    assert seen["deadline_ms"] == gate.HARM_VETO_DEADLINE_MS


def test_gate_fail_closed_on_destructive_when_unsure(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.policy.approval_grant.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", lambda *a, **k: _allow())
    monkeypatch.setattr(
        "app.policy.action_gate.decide",
        lambda *a, **k: type("R", (), {"answers": {}, "fallback_used": True, "provider": "generative"})(),
    )
    result = gate_tool_call("terminal", action="run", arguments={"command": "rm -rf scratch"}, risk=RiskLevel.IRREVERSIBLE)
    assert result.allowed is False
    assert (
        "approve" in result.reason.lower()
        or "harm" in result.reason.lower()
        or "fail closed" in result.reason.lower()
        or "approval" in result.reason.lower()
        or "irreversible" in result.reason.lower()
    )


def test_gate_blocks_destructive_even_when_laya_says_safe(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.policy.approval_grant.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", lambda *a, **k: _allow())
    safe = type(
        "A",
        (),
        {"value": False, "confidence": 0.95},
    )()
    monkeypatch.setattr(
        "app.policy.action_gate.decide",
        lambda *a, **k: type(
            "R",
            (),
            {"answers": {"cancel": safe}, "fallback_used": False, "provider": "laya"},
        )(),
    )
    result = gate_tool_call(
        "terminal",
        action="run",
        arguments={"command": "format c:"},
        risk=RiskLevel.IRREVERSIBLE,
    )
    assert result.allowed is False


def test_gate_allows_after_real_approval_grant(monkeypatch, tmp_path):
    """approved=True alone is insufficient; a real ApprovalGrant is required."""
    from app.policy.action_gate import gate_side_effect
    from app.policy.approval_grant import decide_approval_request, reset_approval_grants

    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.policy.approval_grant.data_dir", lambda: tmp_path)
    reset_approval_grants()
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", lambda *a, **k: _allow())
    monkeypatch.setattr(
        "app.policy.action_gate.decide",
        lambda *a, **k: type("R", (), {"answers": {}, "fallback_used": True, "provider": "generative"})(),
    )
    blocked = gate_side_effect(
        "terminal",
        action="run",
        arguments={"command": "rm -rf scratch"},
        risk=RiskLevel.IRREVERSIBLE,
        approved=True,  # model-style flag — must not satisfy
        park_if_needed=True,
    )
    assert blocked.allowed is False
    assert blocked.requires_approval is True
    assert blocked.pending_approval_id
    outcome = decide_approval_request(
        blocked.pending_approval_id,
        decision="allow_once",
        origin_channel="ui",
        actor="owner",
    )
    grant_id = outcome["grant"]["id"]
    allowed = gate_side_effect(
        "terminal",
        action="run",
        arguments={"command": "rm -rf scratch"},
        risk=RiskLevel.IRREVERSIBLE,
        grant_id=grant_id,
        park_if_needed=False,
    )
    assert allowed.allowed is True
    assert allowed.grant_id == grant_id


def test_blue_watcher_requests_rollback_on_destructive_failure():
    event = note_tool_outcome(
        "t1",
        "terminal",
        {"command": "rm -rf scratch"},
        "ERROR: failed",
        failed=True,
    )
    assert event is not None
    assert event["action"] == "rollback_requested"
    assert note_tool_outcome("t1", "apps", {"action": "open", "name": "steam"}, "Started Steam", failed=False) is None


def test_obvious_harm_is_a_hard_rule():
    blocked = rules.decide(
        state={"user_message": "format c:"},
        questions=[HARM],
        decision_class="harm_veto",
    )
    assert blocked.hard_rule is True
    assert blocked.answers["cancel"].value == "cancel"
    allowed = rules.decide(
        state={"user_message": "open steam"},
        questions=[HARM],
        decision_class="harm_veto",
    )
    assert allowed.hard_rule is False
    assert allowed.answers["cancel"].value == "allow"


def test_red_scenarios_include_steam_and_format():
    prompts = {row[0] for row in SCENARIOS}
    assert "open steam" in prompts
    assert any(row[1] is True for row in SCENARIOS if "format" in row[0])


def test_ufo_points_at_local_openai_endpoint():
    env = UFOBackend()._openai_env()
    assert env["OPENAI_API_BASE"].endswith("/v1")
    assert env["OPENAI_API_KEY"]


def test_ufo_treats_evaluation_complete_as_success_even_if_exit_nonzero():
    output = (
        "+-----------------------------  Task is complete ------------------------------+\n"
        "| YES                                                                          |\n"
        "| The agent successfully opened the Calculator application.\n"
    )
    assert UFOBackend._ufo_session_completed(output) is True
    assert UFOBackend._ufo_session_completed("AAD API scope base and tenant ID must be specified") is False


def test_ufo_sync_writes_openai_local_agents_yaml(tmp_path):
    checkout = tmp_path / "ufo"
    (checkout / "config" / "ufo").mkdir(parents=True)
    env = {
        "OPENAI_API_BASE": "http://127.0.0.1:8088/v1",
        "OPENAI_API_KEY": "local",
        "JARVIS_UFO_API_MODEL": "Qwen3.5-9B",
    }
    UFOBackend()._sync_local_llm_config(checkout, env)
    text = (checkout / "config" / "ufo" / "agents.yaml").read_text(encoding="utf-8")
    assert 'API_TYPE: "openai"' in text
    assert "Qwen3.5-9B" in text
    assert "8088/v1" in text
    assert "azure_ad" not in text.lower()


def test_calibrate_scores_jev_on_the_same_fixtures():
    reset_calibration()

    def _stub(state, questions, _cls):
        question = questions[0]
        if question.type == "boolean":
            value: object = False
        elif question.type == "choice":
            value = question.choices[0] if question.choices else "none"
        else:
            value = 0.0
        return {question.id: Answer(question.id, question.type, value, 0.8)}

    scores = calibrate(_stub, _stub)
    assert "laya" in scores and "jev" in scores and "rules" in scores
    assert set(scores["laya"]) == set(scores["jev"])
    snap = calibration_snapshot()
    assert "jev" in (snap.get("accuracy") or {}).get("harm_veto", {})


def test_elevation_snapshot_has_pid():
    snap = snapshot()
    assert "elevated" in snap
    assert snap["pid"]
    assert is_elevated() in {True, False}
    assert snap["logon_task"] == "JarvisElevatedBackend"
    assert snap["logon_task_registered"] in {True, False}
    assert "logon_task_hint" in snap
    assert "needs_uac" in snap
    assert "elevation_degraded" in snap
    assert "limited_features" in snap
    assert "run_mode" in snap
    if snap.get("platform") == "nt" and not snap["logon_task_registered"]:
        assert "RegisterLogonTask" not in str(snap["logon_task_hint"])
        assert "nothing to type" in str(snap["logon_task_hint"]).lower() or "allow full pc control" in str(snap["logon_task_hint"]).lower()
