"""RFC-0171 Laya backend: pins, sizing, question translation, deadlines, bounds."""

from __future__ import annotations

import json
import threading
import time

import pytest

from app.decision import cache, metrics, quartermaster
from app.decision.laya import pins as laya_pins
from app.decision.laya import runtime as laya_runtime
from app.decision.reflex import decide, decide_many
from app.decision.types import Answer, Question, compact_state


@pytest.fixture(autouse=True)
def _clean(jarvis_env, monkeypatch):
    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.config.data_dir", lambda: tmp)
    monkeypatch.setattr("app.decision.laya.pins.data_dir", lambda: tmp)
    cache.clear()
    metrics.reset_metrics()
    quartermaster.reset_quartermaster()
    laya_runtime.reset_runtime()
    laya_pins.clear_install()
    yield
    cache.clear()
    laya_runtime.reset_runtime()
    laya_pins.clear_install()


def _write_managed_manifest(model_dir, **overrides):
    payload = {
        "provider": "laya",
        "license": laya_pins.LAYA_LICENSE,
        "fixture": False,
        "repo": laya_pins.LAYA_REPO,
        "revision": laya_pins.LAYA_REVISION,
        "model_dir": str(model_dir),
        **overrides,
    }
    laya_pins.manifest_path().write_text(json.dumps(payload), encoding="utf-8")


def test_managed_install_is_checked_against_checked_in_digests_not_the_manifest():
    model_dir = laya_pins.install_root() / "hub" / "fake" / "multilingual"
    for record in laya_pins.pins():
        path = model_dir / record.name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tampered")
    _write_managed_manifest(model_dir)
    ok, reason, _ = laya_pins.verify_installed(allow_fixture=False)
    assert ok is False
    assert "hash mismatch" in reason


def test_managed_install_outside_root_is_refused(tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere")
    _write_managed_manifest(outside)
    ok, reason, _ = laya_pins.verify_installed(allow_fixture=False)
    assert ok is False
    assert "outside" in reason


def test_managed_install_wrong_revision_is_refused():
    _write_managed_manifest(laya_pins.install_root(), revision="0" * 40)
    ok, reason, _ = laya_pins.verify_installed(allow_fixture=False)
    assert ok is False
    assert "revision" in reason


def test_pins_match_checked_in_document():
    document = json.loads(laya_pins.repo_pin_document_path().read_text(encoding="utf-8"))
    assert document["revision"] == laya_pins.LAYA_REVISION
    assert document["package_version"] == laya_pins.LAYA_PACKAGE_VERSION
    assert {row["name"]: row["sha256"] for row in document["artifacts"]} == laya_pins.expected_digests()
    assert all(len(sha) == 64 for sha in laya_pins.expected_digests().values())


def test_enable_without_install_refuses():
    with pytest.raises(RuntimeError):
        laya_runtime.enable(warm=True, allow_fixture=False)


def test_ensure_package_does_not_pip_under_pytest(monkeypatch):
    monkeypatch.setattr(laya_pins, "package_version", lambda: None)

    def boom(*_args, **_kwargs):
        raise AssertionError("ensure_package must not pip install during pytest")

    monkeypatch.setattr("subprocess.check_call", boom)
    with pytest.raises(RuntimeError, match="not installed"):
        laya_pins.ensure_package()


def test_laya_install_honors_internet_deny(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    monkeypatch.setattr(laya_pins, "ensure_package", lambda: "0.3.21")
    called = {"n": 0}

    def boom(*_args, **_kwargs):
        called["n"] += 1
        raise AssertionError("must not download Laya when internet is denied")

    monkeypatch.setattr("huggingface_hub.snapshot_download", boom)
    with pytest.raises(PermissionError):
        laya_pins.install_managed()
    assert called["n"] == 0


def test_choice_shortlist_keeps_hints_and_none_within_option_budget():
    choices = tuple(f"tool_{i}" for i in range(40)) + ("none",)
    question = Question(id="tool_select", type="choice", prompt="Which tool?", choices=choices)
    payload, effective = laya_runtime._to_laya_questions(
        [question], {"user_message": "use tool_33 please", "preferred_profile": "tool_7"}
    )
    kept = effective["tool_select"].choices
    assert len(kept) <= laya_runtime.MAX_CHOICE_OPTIONS
    assert {"none", "tool_7", "tool_33"} <= set(kept)
    assert list(payload["tool_select"]["criteria"]) == list(kept)


def test_answer_translation_maps_score_levels_and_booleans():
    questions = {
        "tier": Question(id="tier", type="score", prompt="tier", min_score=1.0, max_score=4.0),
        "done": Question(id="done", type="boolean", prompt="done?"),
        "pick": Question(id="pick", type="choice", prompt="pick", choices=("a", "b")),
    }
    raw = {
        "tier": {"score": 2.0, "answer_confidence": 0.7},
        "done": {"noul": 0.2, "answer_confidence": 0.8},
        "pick": {"choice": "zzz", "answer_confidence": 0.99},
    }
    answers = laya_runtime._from_laya_answers(raw, questions)
    assert answers["tier"].value == pytest.approx(2.5)
    assert answers["done"].value is False
    assert "pick" not in answers  # out-of-domain choice is dropped, never passed through


def test_plan_input_single_windowed_and_compressed():
    small = laya_runtime.plan_input({"user_message": "hi"}, deadline_ms=100)
    assert small["strategy"] == "single"
    big_state = {"user_message": "word " * 20000}
    assert laya_runtime.plan_input(big_state, deadline_ms=100)["strategy"] == "compressed"
    laya_runtime._STATE.window_ms_ewma = 0.01
    assert laya_runtime.plan_input(big_state, deadline_ms=100)["strategy"] == "windowed"


class _SlowAgent:
    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s
        self.seen_states: list = []

    def tok(self, text, add_special_tokens=False):
        return {"input_ids": text.split()}

    def predict(self, state, questions, **_kwargs):
        self.seen_states.append(state)
        time.sleep(self.delay_s)
        return {"answers": {qid: {"noul": 0.9, "answer_confidence": 0.9} for qid in questions}, "usage": {}}

    predict_long = predict


def _enable_fake_agent(monkeypatch, agent) -> None:
    monkeypatch.setattr(laya_pins, "verify_installed", lambda **_kw: (True, "", {"fixture": False}))
    laya_runtime._STATE.enabled = True
    laya_runtime._STATE.warm = True
    laya_runtime._STATE.fixture = False
    monkeypatch.setattr(laya_runtime, "_AGENT", agent)


def test_decide_local_returns_at_deadline_and_clears_busy(monkeypatch):
    agent = _SlowAgent(0.4)
    _enable_fake_agent(monkeypatch, agent)
    started = time.perf_counter()
    with pytest.raises(TimeoutError):
        laya_runtime.decide_local(
            state={"user_message": "x"},
            questions=[Question(id="q", type="noul", prompt="q?")],
            decision_class="probe",
            deadline_ms=50,
        )
    assert (time.perf_counter() - started) < 0.3
    assert laya_runtime.is_ready() is False  # busy: next request falls back instead of queueing
    deadline = time.time() + 2
    while laya_runtime._STATE.busy and time.time() < deadline:
        time.sleep(0.02)
    assert laya_runtime.is_ready() is True
    assert laya_runtime._STATE.window_ms_ewma is not None  # late pass still recorded


def test_oversized_state_is_compressed_before_reaching_laya(monkeypatch):
    agent = _SlowAgent(0.0)
    _enable_fake_agent(monkeypatch, agent)
    paste = "Background filler sentence about nothing much. " * 3000 + "Final ask: summarize the budget."
    answers, _elapsed, _fixture = laya_runtime.decide_local(
        state={"document": paste},
        questions=[Question(id="q", type="noul", prompt="Is there an ask?")],
        decision_class="intake_strategy",
        deadline_ms=2000,
    )
    assert answers["q"].value == pytest.approx(0.9)
    sent = json.dumps(agent.seen_states[-1])
    assert len(sent.split()) <= laya_runtime.state_token_budget()
    assert "summarize the budget" in sent


def test_reflex_drops_out_of_domain_provider_answers():
    laya_pins.write_test_install()
    laya_runtime.enable(warm=True)
    laya_runtime.set_decide_fn(
        lambda **_kw: {"tool_select": Answer("tool_select", "choice", "rm -rf /", 0.99)}
    )
    result = decide(
        {"user_message": "read the file"},
        {"tool_select": {"type": "choice", "question": "tool?", "choices": ["filesystem", "none"]}},
        "tool_selection",
        200.0,
        "local_only",
    )
    assert result.provider != "laya"
    assert result.answers["tool_select"].value in {"filesystem", "none"}


def test_failed_provider_lowers_quartermaster_quality():
    laya_pins.write_test_install()
    laya_runtime.enable(warm=True)

    def boom(**_kw):
        raise RuntimeError("encoder crashed")

    laya_runtime.set_decide_fn(boom)
    decide(
        {"user_message": "x"},
        {"a": {"type": "score", "question": "a"}},
        "memory_relevance",
        200.0,
        "local_only",
    )
    laya = next(p for p in quartermaster.profiles_for("memory_relevance") if p.name == "laya")
    assert laya.stats.samples == 1
    assert laya.stats.ewma_quality == 0.0


def test_decide_many_does_not_merge_conflicting_question_ids():
    jobs = [
        {
            "state": {"user_message": "same"},
            "questions": {"q": {"type": "score", "question": "relevance", "min": 0, "max": 1}},
            "decision_class": "memory_relevance",
        },
        {
            "state": {"user_message": "same"},
            "questions": {"q": {"type": "score", "question": "urgency", "min": 0, "max": 10}},
            "decision_class": "memory_relevance",
        },
    ]
    first, second = decide_many(jobs)
    assert first.meta.get("batched") is not True
    assert 0.0 <= first.answers["q"].value <= 1.0
    assert 0.0 <= second.answers["q"].value <= 10.0


def test_calibration_routes_classes_to_the_measured_better_provider():
    from app.decision import calibration

    def laya_answers(state, questions, decision_class):
        question = questions[0]
        # Perfect on tool selection, always wrong elsewhere.
        if decision_class == "tool_selection":
            expected = next(f.expected for f in calibration.FIXTURES if f.state == state)
            return {question.id: Answer(question.id, question.type, expected, 0.9)}
        return {question.id: Answer(question.id, question.type, "__wrong__", 0.99)}

    def jev_answers(state, questions, decision_class):
        question = questions[0]
        if decision_class == "speak_class":
            expected = next(f.expected for f in calibration.FIXTURES if f.state == state)
            return {question.id: Answer(question.id, question.type, expected, 0.9)}
        return {question.id: Answer(question.id, question.type, "__wrong__", 0.99)}

    scores = calibration.calibrate(laya_answers, jev_answers)
    assert scores["laya"]["tool_selection"] == 1.0
    assert scores["jev"]["speak_class"] == 1.0
    assert calibration.laya_qualified("tool_selection") is True
    assert calibration.laya_qualified("complexity_escalation") is False  # measured 0
    assert calibration.laya_qualified("memory_relevance") is True  # unmeasured stays eligible
    order = quartermaster.select_provider_order(
        "complexity_escalation", privacy="local_only", laya_ready=True, jev_ready=False
    )
    assert order[0] == "laya"
    assert "rules" not in order
    assert "laya" in quartermaster.select_provider_order(
        "tool_selection", privacy="local_only", laya_ready=True, jev_ready=False
    )


def test_compact_state_keeps_the_closing_instruction_of_a_long_paste():
    paste = "Context line that repeats. " * 400 + "Please send this to finance today."
    projected = compact_state({"user_message": paste})
    assert len(projected["user_message"]) <= 800
    assert "finance today" in projected["user_message"]


def test_status_does_not_import_torch_heavy_package(monkeypatch):
    imported = threading.Event()
    real_import = __import__

    def guard(name, *args, **kwargs):
        if name == "laya":
            imported.set()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guard)
    laya_runtime.status()
    assert not imported.is_set()
