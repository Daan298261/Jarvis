"""RFC-0172 Reflex-first browser/computer-use fast loop."""

from __future__ import annotations

import time

import pytest

from app.reflex_loop.adapters import build_browser_action_frame, build_desktop_action_frame
from app.reflex_loop.benchmark import (
    ScriptedDecideClient,
    compare_loops,
    default_benchmark_tasks,
    run_benchmark_suite,
)
from app.reflex_loop.executor import ReflexLoopExecutor, parse_reflex_decision
from app.reflex_loop.reflex_client import (
    BROWSER_OP_TARGET_CLASS,
    DecisionPackageForwarder,
    DecisionQuestion,
    DecisionResult,
    FailClosedDecideClient,
    adapt_decision_result,
    get_reflex_decide_client,
    map_decision_class,
    map_privacy,
    questions_to_0171_map,
    set_reflex_decide_client,
)
from app.reflex_loop.sandbox import gate_decision_payload
from app.reflex_loop.schema import ActionNode, Geometry, NodeState, Operation, ReflexDecision, SurfaceKind
from app.reflex_loop.text_gen import generate_bounded_text, validate_typed_text
from app.reflex_loop.verification import (
    check_frame_freshness,
    resolve_target,
    target_changed,
    verify_postcondition,
)


def test_action_frame_schema_browser_and_desktop():
    browser = build_browser_action_frame(
        [
            {
                "role": "button",
                "name": "OK",
                "dom_id": "ok",
                "geometry": {"x": 1, "y": 2, "width": 10, "height": 5},
            }
        ],
        url="https://example.test",
        title="Example",
    )
    assert browser.surface == SurfaceKind.BROWSER
    assert browser.frame_id.startswith("af_")
    assert browser.nodes[0].target_id == "t0"
    assert Operation.CLICK in browser.nodes[0].supported_operations
    assert "geometry" in browser.nodes[0].as_dict()
    assert "selector" not in browser.nodes[0].backend_ref

    desktop = build_desktop_action_frame(
        [{"name": "Save", "control_type": "Button", "automation_id": "saveBtn"}],
        app_id="Notepad",
        window_title="Untitled",
    )
    assert desktop.surface == SurfaceKind.DESKTOP
    assert desktop.nodes[0].role == "button"
    assert desktop.nodes[0].backend_ref["automation_id"] == "saveBtn"


def test_fail_closed_decide_stub_refuses():
    client = FailClosedDecideClient()
    result = client.decide(
        {"goal": "click Save"},
        [DecisionQuestion(id="operation", kind="choice", prompt="op", options=("CLICK",))],
        "browser_operation_target",
    )
    assert result.ok is False
    assert "not available" in result.error.lower() or "refuse" in result.error.lower()


def test_privacy_and_class_mapping():
    assert map_privacy("local") == "local_only"
    assert map_privacy("local_only") == "local_only"
    assert map_privacy("allow_cloud") == "allow_cloud"
    assert map_privacy("require_local") == "require_local"
    assert map_privacy("garbage") == "local_only"
    assert map_decision_class("browser_computer_op_target") == BROWSER_OP_TARGET_CLASS
    assert map_decision_class("browser_operation_target") == "browser_operation_target"
    assert BROWSER_OP_TARGET_CLASS == "browser_operation_target"


def test_questions_to_0171_map_uses_type_and_choices():
    payload = questions_to_0171_map(
        [
            DecisionQuestion(
                id="operation",
                kind="choice",
                prompt="Which op?",
                options=("CLICK", "DONE"),
            ),
            DecisionQuestion(id="done", kind="boolean", prompt="Done?"),
        ]
    )
    assert payload["operation"]["type"] == "choice"
    assert payload["operation"]["choices"] == ["CLICK", "DONE"]
    assert "options" not in payload["operation"]
    assert "kind" not in payload["operation"]
    assert payload["done"]["type"] == "boolean"


def test_adapt_0171_decision_result_flattens_answers():
    from app.decision.types import Answer, DecisionResult as UpstreamResult, LatencyBreakdown

    upstream = UpstreamResult(
        answers={
            "operation": Answer("operation", "choice", "CLICK", 0.9),
            "target_id": Answer("target_id", "choice", "t0", 0.8),
            "done": Answer("done", "boolean", False, 1.0),
            "block": Answer("block", "boolean", False, 1.0),
        },
        source="rules",
        decision_class="browser_operation_target",
        provider="rules",
        latency=LatencyBreakdown(total_ms=12.5),
    )
    adapted = adapt_decision_result(upstream)
    assert adapted.ok is True
    assert adapted.answers["operation"] == "CLICK"
    assert adapted.answers["target_id"] == "t0"
    assert adapted.provider == "rules"
    assert adapted.source == "rules"
    assert adapted.latency_ms == 12.5
    assert adapted.confidence > 0.0


def test_forwarder_prefers_browser_operation_target_surface():
    calls: list[dict] = []

    def fake_surface(**kwargs):
        calls.append(kwargs)
        from app.decision.types import Answer, DecisionResult as UpstreamResult

        return UpstreamResult(
            answers={
                "operation": Answer("operation", "choice", "CLICK", 1.0),
                "target_id": Answer("target_id", "choice", "t0", 1.0),
            },
            source="rules",
            decision_class="browser_operation_target",
            provider="rules",
        )

    def boom_decide(*args, **kwargs):
        raise AssertionError("decide() must not be called when surface is available")

    client = DecisionPackageForwarder(decide_fn=boom_decide, browser_op_target_fn=fake_surface)
    result = client.decide(
        {"goal": "Click Save", "frame_id": "af_1"},
        [
            DecisionQuestion(
                id="operation",
                kind="choice",
                prompt="op",
                options=("CLICK", "DONE"),
            ),
            DecisionQuestion(
                id="target_id",
                kind="choice",
                prompt="target",
                options=("t0", "none"),
            ),
        ],
        "browser_computer_op_target",  # legacy class name must map
        deadline_ms=80,
        privacy="local",  # alias must map to local_only
    )
    assert result.ok is True
    assert result.answers["operation"] == "CLICK"
    assert result.answers["target_id"] == "t0"
    assert len(calls) == 1
    assert calls[0]["goal"] == "Click Save"
    assert calls[0]["operations"] == ["CLICK", "DONE"]
    assert calls[0]["target_ids"] == ["t0", "none"]
    assert calls[0]["privacy"] == "local_only"
    assert calls[0]["frame_id"] == "af_1"


def test_forwarder_decide_fallback_shapes_questions():
    captured: dict = {}

    def fake_decide(state, questions, decision_class, deadline_ms=None, privacy="local_only"):
        captured["questions"] = questions
        captured["decision_class"] = decision_class
        captured["privacy"] = privacy
        from app.decision.types import Answer, DecisionResult as UpstreamResult

        return UpstreamResult(
            answers={
                "operation": Answer("operation", "choice", "DONE", 1.0),
                "done": Answer("done", "boolean", True, 1.0),
            },
            source="rules",
            decision_class=decision_class,
            provider="rules",
        )

    client = DecisionPackageForwarder(decide_fn=fake_decide, browser_op_target_fn=None)
    result = client.decide(
        {"goal": "finish"},
        [
            DecisionQuestion(
                id="operation",
                kind="choice",
                prompt="op",
                options=("DONE", "BLOCK"),
            ),
        ],
        BROWSER_OP_TARGET_CLASS,
        privacy="local",
    )
    assert result.ok is True
    assert result.answers["operation"] == "DONE"
    assert captured["decision_class"] == "browser_operation_target"
    assert captured["privacy"] == "local_only"
    assert isinstance(captured["questions"], dict)
    assert captured["questions"]["operation"]["type"] == "choice"
    assert captured["questions"]["operation"]["choices"] == ["DONE", "BLOCK"]


def test_live_decision_package_resolves_to_forwarder():
    """On tips where RFC-0171 landed, get_reflex_decide_client must not fail-close."""
    set_reflex_decide_client(None)
    client = get_reflex_decide_client(force_reload=True)
    assert isinstance(client, DecisionPackageForwarder)
    result = client.decide(
        {"goal": "click search", "suggested_operation": "CLICK", "suggested_target_id": "t0"},
        [
            DecisionQuestion(
                id="operation",
                kind="choice",
                prompt="op",
                options=("CLICK", "TYPE_TEXT", "DONE"),
            ),
            DecisionQuestion(
                id="target_id",
                kind="choice",
                prompt="target",
                options=("t0", "t1", "none"),
            ),
        ],
        BROWSER_OP_TARGET_CLASS,
        deadline_ms=100,
        privacy="local_only",
    )
    assert result.ok is True
    assert "operation" in result.answers
    assert result.answers["operation"] in {"CLICK", "TYPE_TEXT", "DONE", "NOOP"}
    set_reflex_decide_client(None)


def test_forwarder_absent_when_decision_cannot_import(monkeypatch):
    import app.reflex_loop.reflex_client as rc

    set_reflex_decide_client(None)
    monkeypatch.setattr(rc, "_try_import_decision_api", lambda: (None, None))
    client = get_reflex_decide_client(force_reload=True)
    assert isinstance(client, FailClosedDecideClient)
    result = client.decide(
        {"goal": "x"},
        [DecisionQuestion(id="operation", kind="choice", prompt="op", options=("CLICK",))],
        BROWSER_OP_TARGET_CLASS,
    )
    assert result.ok is False
    set_reflex_decide_client(None)


def test_parse_reflex_decision_and_sandbox_rejects_forbidden_payload():
    parsed = parse_reflex_decision(
        DecisionResult(
            ok=True,
            answers={"operation": "CLICK", "target_id": "t0"},
            provider="scripted",
        )
    )
    assert parsed is not None
    assert parsed.operation == Operation.CLICK
    assert parsed.target_id == "t0"

    bad = gate_decision_payload(parsed, extra={"selector": "#ok", "js": "alert(1)"})
    assert bad.ok is False
    assert "forbidden" in bad.reason or "not permitted" in bad.reason


def test_stale_frame_and_changed_target_rejected():
    frame = build_browser_action_frame(
        [{"role": "button", "name": "Go", "dom_id": "go"}],
        url="https://example.test",
        timestamp_ms=time.time() * 1000.0 - 10_000,
    )
    stale = check_frame_freshness(frame, max_age_ms=1000)
    assert stale.ok is False
    assert "stale" in stale.reason

    node, reason = resolve_target(frame, "t0")
    assert node is not None
    assert reason == "ok"
    missing, reason = resolve_target(frame, "t99")
    assert missing is None

    prior = ActionNode(
        target_id="t0",
        role="button",
        name="Go",
        state=NodeState(),
        geometry=Geometry(),
        supported_operations=(Operation.CLICK,),
        backend_ref={"dom_id": "go"},
    )
    changed = ActionNode(
        target_id="t0",
        role="button",
        name="Gone",
        state=NodeState(),
        geometry=Geometry(),
        supported_operations=(Operation.CLICK,),
        backend_ref={"dom_id": "other"},
    )
    assert target_changed(prior, changed)


@pytest.mark.asyncio
async def test_type_text_validation_is_only_generative_path():
    ok = validate_typed_text("hello world")
    assert ok.ok and ok.text == "hello world"
    assert validate_typed_text("document.cookie").ok is False
    assert validate_typed_text("12,34").ok is False
    assert validate_typed_text("x" * 600).ok is False

    extracted = await generate_bounded_text('Type "alice@example.com" into Email', field_name="Email")
    assert extracted.ok
    assert extracted.text == "alice@example.com"

    refused = await generate_bounded_text("fill the form somehow", field_name="Email")
    assert refused.ok is False


@pytest.mark.asyncio
async def test_executor_click_with_postcondition_and_done():
    nodes = [
        {"role": "button", "name": "Save", "dom_id": "save"},
        {"role": "button", "name": "Cancel", "dom_id": "cancel"},
    ]
    client = ScriptedDecideClient(
        [
            {"operation": "CLICK", "target_id": "t0"},
            {"operation": "DONE", "done": True},
        ]
    )
    clicks: list[str] = []

    async def observe():
        return build_browser_action_frame(nodes, url="https://app.test", title="App")

    async def act(operation, node, payload):
        assert operation == Operation.CLICK
        assert "selector" not in payload
        assert "x" not in payload
        clicks.append(node.name)
        return {"protocol_calls": 1}

    executor = ReflexLoopExecutor(
        observe=observe,
        act=act,
        decide_client=client,
        max_age_ms=60_000,
    )
    result = await executor.run("Click Save")
    assert result.success is True
    assert result.done is True
    assert clicks == ["Save"]
    assert result.model_calls == 0  # CLICK must not invoke text generation


@pytest.mark.asyncio
async def test_executor_rejects_stale_or_foreign_target_without_fake_success():
    frame = build_browser_action_frame(
        [{"role": "button", "name": "OK", "dom_id": "ok"}],
        url="https://app.test",
        timestamp_ms=time.time() * 1000.0,
    )
    client = ScriptedDecideClient([{"operation": "CLICK", "target_id": "t99"}])

    async def observe():
        return frame

    async def act(operation, node, payload):
        raise AssertionError("act must not run for unknown target")

    executor = ReflexLoopExecutor(
        observe=observe,
        act=act,
        decide_client=client,
        max_age_ms=60_000,
    )
    result = await executor.run("Click missing")
    assert result.success is False
    assert "not in current frame" in result.reason


@pytest.mark.asyncio
async def test_type_text_invokes_generator_once_and_validates():
    nodes = [{"role": "textbox", "name": "Email", "value": "", "dom_id": "email"}]
    client = ScriptedDecideClient(
        [
            {"operation": "TYPE_TEXT", "target_id": "t0"},
            {"operation": "DONE", "done": True},
        ]
    )
    calls = {"n": 0}

    async def observe():
        return build_browser_action_frame(nodes, url="https://app.test")

    async def gen(goal, state):
        calls["n"] += 1
        return "user@example.com"

    async def act(operation, node, payload):
        assert operation == Operation.TYPE_TEXT
        assert payload["text"] == "user@example.com"
        nodes[0]["value"] = payload["text"]
        return {"protocol_calls": 1}

    executor = ReflexLoopExecutor(
        observe=observe,
        act=act,
        decide_client=client,
        text_generator=gen,
        max_age_ms=60_000,
    )
    result = await executor.run("Fill the email field")
    assert result.success is True
    assert calls["n"] == 1
    assert result.model_calls == 1


@pytest.mark.asyncio
async def test_fail_closed_without_reflex_lane():
    set_reflex_decide_client(FailClosedDecideClient())
    nodes = [{"role": "button", "name": "OK", "dom_id": "ok"}]

    async def observe():
        return build_browser_action_frame(nodes, url="https://app.test")

    async def act(operation, node, payload):
        raise AssertionError("must not act")

    executor = ReflexLoopExecutor(observe=observe, act=act, max_age_ms=60_000)
    result = await executor.run("Click OK")
    assert result.success is False
    assert "refuse" in result.reason.lower() or "not available" in result.reason.lower()
    set_reflex_decide_client(None)


@pytest.mark.asyncio
async def test_deterministic_benchmark_reflex_vs_anzu():
    suite = await run_benchmark_suite()
    assert suite["summary"]["count"] == 2
    assert suite["summary"]["reflex_successes"] == 2
    assert suite["summary"]["total_reflex_model_calls"] <= suite["summary"]["total_anzu_model_calls"]
    assert suite["summary"]["total_reflex_protocol_calls"] < suite["summary"]["total_anzu_protocol_calls"]

    for task in default_benchmark_tasks():
        comparison = await compare_loops(task)
        assert comparison.reflex.success is True
        assert comparison.reflex.model_calls <= comparison.anzu.model_calls
        assert "model_calls" in comparison.reflex.as_dict()
        assert "protocol_calls" in comparison.reflex.as_dict()
        assert "wall_time_ms" in comparison.reflex.as_dict()
        assert "recovery_count" in comparison.reflex.as_dict()


@pytest.mark.asyncio
async def test_browser_use_reflex_mode_fail_closed_without_nodes():
    from app.tools.browser_use import BrowserUseTool

    tool = BrowserUseTool()
    result = await tool.execute(goal="click Save", mode="reflex")
    assert result.success is False
    assert "ActionFrame" in (result.error or "")


@pytest.mark.asyncio
async def test_reflex_computer_use_tool_with_scripted_lane(monkeypatch):
    from app.tools.computer_use import ReflexComputerUseTool

    client = ScriptedDecideClient(
        [
            {"operation": "CLICK", "target_id": "t0"},
            {"operation": "DONE", "done": True},
        ]
    )
    set_reflex_decide_client(client)
    tool = ReflexComputerUseTool()
    monkeypatch.setattr(
        "app.reflex_loop.runtime.permission_gate_for_surface",
        lambda surface: (lambda decision, frame: None),
    )
    result = await tool.execute(
        action="run",
        goal="Click Save",
        app="Notepad",
        nodes=[{"name": "Save", "control_type": "Button", "automation_id": "saveBtn"}],
    )
    assert result.success is True
    assert result.data.get("done") is True
    set_reflex_decide_client(None)


@pytest.mark.asyncio
async def test_postcondition_type_text():
    prior = ActionNode(
        target_id="t0",
        role="textbox",
        name="Email",
        value="",
        supported_operations=(Operation.TYPE_TEXT,),
        backend_ref={"dom_id": "email"},
    )
    post_frame = build_browser_action_frame(
        [{"role": "textbox", "name": "Email", "value": "a@b.c", "dom_id": "email"}],
        url="https://app.test",
    )
    ok = verify_postcondition(
        Operation.TYPE_TEXT,
        prior_node=prior,
        post_frame=post_frame,
        target_id="t0",
        typed_text="a@b.c",
    )
    assert ok.ok


def test_api_reflex_benchmark():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/api/computer-use/reflex/benchmark")
        assert response.status_code == 200
        body = response.json()
        assert body["suite"] == "rfc0172_reflex_vs_anzu"
        assert body["summary"]["reflex_successes"] >= 1


def test_reflex_decision_done_block():
    done = ReflexDecision(operation=Operation.DONE, done=True, reason="complete")
    assert gate_decision_payload(done).ok
    blocked = ReflexDecision(operation=Operation.BLOCK, blocked=True, reason="unsafe")
    assert gate_decision_payload(blocked).ok
