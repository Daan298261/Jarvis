"""Action gate, Laya-first routing, blue watcher, UFO local endpoint, elevation."""

from __future__ import annotations

from app.decision.adapters import rules
from app.decision.calibration import calibrate, reset as reset_calibration, snapshot as calibration_snapshot
from app.decision.quartermaster import select_provider_order
from app.decision.types import Answer, Question
from app.policy.action_gate import gate_tool_call
from app.policy.authorize import AuthorizationResult
from app.policy.levels import AutonomyLevel
from app.runtime.elevation import is_elevated, snapshot
from app.security.blue_watch import note_tool_outcome
from app.security.red_scenarios import SCENARIOS
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
    monkeypatch.setattr("app.policy.action_gate.authorize", lambda *a, **k: _allow())
    monkeypatch.setattr(
        "app.policy.action_gate.decide",
        lambda *a, **k: type("R", (), {"answers": {}, "fallback_used": True, "provider": "generative"})(),
    )
    result = gate_tool_call("filesystem", action="read", arguments={"path": "notes.txt"})
    assert result.allowed is True


def test_gate_fail_closed_on_destructive_when_unsure(monkeypatch):
    monkeypatch.setattr("app.policy.action_gate.authorize", lambda *a, **k: _allow())
    monkeypatch.setattr(
        "app.policy.action_gate.decide",
        lambda *a, **k: type("R", (), {"answers": {}, "fallback_used": True, "provider": "generative"})(),
    )
    result = gate_tool_call("terminal", action="run", arguments={"command": "rm -rf scratch"}, risk=RiskLevel.IRREVERSIBLE)
    assert result.allowed is False
    assert "approve" in result.reason.lower() or "harm" in result.reason.lower() or "fail closed" in result.reason.lower()


def test_gate_blocks_destructive_even_when_laya_says_safe(monkeypatch):
    monkeypatch.setattr("app.policy.action_gate.authorize", lambda *a, **k: _allow())
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


def test_gate_skips_veto_after_owner_approval(monkeypatch):
    monkeypatch.setattr("app.policy.action_gate.authorize", lambda *a, **k: _allow())
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("veto should not run after approval")

    monkeypatch.setattr("app.policy.action_gate.decide", boom)
    result = gate_tool_call(
        "terminal",
        action="run",
        arguments={"command": "rm -rf scratch"},
        risk=RiskLevel.IRREVERSIBLE,
        approved=True,
    )
    assert result.allowed is True
    assert called["n"] == 0


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
    harm = Question(
        id="cancel",
        type="boolean",
        prompt="Would carrying out this action harm the owner or destroy data? True cancels it.",
    )
    blocked = rules.decide(
        state={"user_message": "format c:"},
        questions=[harm],
        decision_class="harm_veto",
    )
    assert blocked.hard_rule is True
    assert blocked.answers["cancel"].value is True
    allowed = rules.decide(
        state={"user_message": "open steam"},
        questions=[harm],
        decision_class="harm_veto",
    )
    assert allowed.hard_rule is False
    assert allowed.answers["cancel"].value is False


def test_red_scenarios_include_steam_and_format():
    prompts = {row[0] for row in SCENARIOS}
    assert "open steam" in prompts
    assert any(row[1] is True for row in SCENARIOS if "format" in row[0])


def test_ufo_points_at_local_openai_endpoint():
    env = UFOBackend()._openai_env()
    assert env["OPENAI_API_BASE"].endswith("/v1")
    assert env["OPENAI_API_KEY"]


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
    if not snap["logon_task_registered"]:
        assert "RegisterLogonTask" in str(snap["logon_task_hint"])
