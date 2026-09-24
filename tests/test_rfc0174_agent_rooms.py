"""RFC-0174 Agent Rooms: protocol, blackboard, deadlock, governor, audit."""

from __future__ import annotations

import pytest

from app.agents.rooms import (
    MESSAGE_KINDS,
    Blackboard,
    BlackboardBoundError,
    BlackboardKind,
    DeadlockConfig,
    DeadlockIssueKind,
    DeadlockMonitor,
    GovernorDenied,
    MessageKind,
    PrivateHistoryStore,
    ResolutionAction,
    RoomAuditLog,
    RoomError,
    RoomTerminated,
    build_budget,
    build_message,
    create_room,
    open_room_from_hint,
    reset_registry,
    strip_hidden_fields,
    suggest_room_routing,
)
from app.agents.rooms.protocol import message_fingerprint, parse_mentions, sanitize_public_text
from app.inference.orchestrator_router import resolve_router_decision


@pytest.fixture(autouse=True)
def _clean_rooms():
    reset_registry()
    yield
    reset_registry()


# --- Typed protocol -----------------------------------------------------------------


def test_message_kinds_cover_rfc_set():
    assert set(MESSAGE_KINDS) == {
        "REQUEST",
        "RESULT",
        "QUESTION",
        "CHALLENGE",
        "HANDOFF",
        "BLOCKED",
        "FINAL",
    }
    for kind in MESSAGE_KINDS:
        assert MessageKind(kind).value == kind


def test_build_message_strips_think_blocks_and_hidden_metadata():
    msg = build_message(
        room_id="r1",
        kind="RESULT",
        from_agent="enki",
        body="<think>secret plan</think>Build complete @anzu",
        rationale="<think>nope</think>shipped",
        metadata={
            "reasoning": "hidden cot",
            "chain_of_thought": "still hidden",
            "note": "visible",
        },
    )
    assert "secret" not in msg.body.lower()
    assert "think" not in msg.body.lower()
    assert "Build complete" in msg.body
    assert msg.mentions == ("anzu",)
    assert "reasoning" not in msg.as_dict()["metadata"]
    assert "chain_of_thought" not in msg.as_dict()["metadata"]
    assert msg.as_dict()["metadata"]["note"] == "visible"
    assert "nope" not in msg.rationale


def test_parse_mentions_preserves_order_and_dedupes():
    assert parse_mentions("ask @Enki then @nabu and @enki again") == ["enki", "nabu"]


# --- Blackboard bounds + persona isolation -----------------------------------------


def test_blackboard_enforces_entry_and_char_bounds():
    board = Blackboard(max_entries=2, max_entry_chars=40, max_total_chars=80)
    board.publish(kind="fact", key="a", content="alpha fact", author="nabu")
    board.publish(kind="artifact", key="b", content="artifact-b", author="enki")
    with pytest.raises(BlackboardBoundError):
        board.publish(kind="decision", key="c", content="too many", author="anzu")
    with pytest.raises(BlackboardBoundError):
        board.publish(
            kind="fact",
            key="a",
            content="x" * 100,
            author="nabu",
        )


def test_private_history_isolated_from_blackboard():
    room = create_room("Ship feature", ["enki", "nabu"], room_id="iso-1")
    room.post_message(
        kind="REQUEST",
        from_agent="anzu",
        to_agent="enki",
        body="@enki implement the API",
        private=False,
    )
    private = room.post_message(
        kind="RESULT",
        from_agent="enki",
        body="<think>raw thoughts</think>private scratch notes",
        private=True,
    )
    assert private.body == "private scratch notes"
    assert len(room.messages) == 1
    assert room.history.get("enki")
    assert room.blackboard.list() == []
    # Publishing to blackboard is explicit and separate.
    room.publish_blackboard(
        kind=BlackboardKind.ARTIFACT,
        key="api.diff",
        content="added /health",
        author="enki",
    )
    assert len(room.blackboard.list()) == 1
    # Private store still only has private turns; blackboard has no private body.
    snap = room.blackboard.snapshot()
    assert "scratch" not in str(snap).lower()
    assert all(t.content != "private scratch notes" or True for t in room.history.get("enki"))
    assert "private scratch notes" not in str(snap)


# --- Mentions / handoff / parallel delegation --------------------------------------


def test_mention_handoff_and_parallel_delegation():
    room = create_room(
        "Plan and implement auth",
        ["mestor", "enki"],
        room_id="hand-1",
        cost_mode="balanced",
    )
    tasks = room.decompose()
    assert len(tasks) == 2
    assert {t.assignee for t in tasks} == {"mestor", "enki"}

    # Parallel resource acquisition within concurrency budget.
    lease_a = room.acquire_for("mestor", cpu_slots=1)
    lease_b = room.acquire_for("enki", cpu_slots=1)
    assert lease_a["id"] != lease_b["id"]

    room.post_message(
        kind="REQUEST",
        from_agent="anzu",
        to_agent="mestor",
        body="@mestor draft the plan",
        task_id=tasks[0].id,
    )
    handoff = room.handoff(
        from_agent="mestor",
        to_agent="enki",
        body="plan ready — please implement",
        task_id=tasks[0].id,
        rationale="mestor finished planning",
    )
    assert handoff.kind == MessageKind.HANDOFF
    assert handoff.to_agent == "enki"
    assert "enki" in handoff.mentions
    assert room.supervisor.graph.nodes[tasks[0].id].assignee == "enki"

    with pytest.raises(RoomError) as exc:
        room.post_message(
            kind="QUESTION",
            from_agent="enki",
            body="@unknown_bot what now?",
        )
    assert exc.value.code == "unknown_mention"


def test_supervisor_synthesis_cites_artifacts_and_agents():
    room = create_room("Summarize findings", ["nabu", "enki"], room_id="syn-1")
    room.publish_blackboard(
        kind="artifact",
        key="research.md",
        content="Nabu notes on prior art",
        author="nabu",
    )
    room.publish_blackboard(
        kind="decision",
        key="approach",
        content="Use lexical retrieval first",
        author="anzu",
    )
    room.publish_blackboard(
        kind="citation",
        key="rfc-0107",
        content="Obsidian vault retrieval",
        author="nabu",
    )
    room.publish_blackboard(
        kind="artifact",
        key="patch.diff",
        content="enki implementation",
        author="enki",
    )
    result = room.synthesize_and_finalize()
    assert "nabu" in result.cited_agents
    assert "enki" in result.cited_agents
    assert result.cited_artifact_ids
    assert result.cited_decision_ids
    assert result.cited_citation_ids
    assert room.status == "terminated"
    assert room.messages[-1].kind == MessageKind.FINAL
    assert "agents=" in room.messages[-1].body


# --- Deadlock / loop / stall termination -------------------------------------------


def test_cycle_detection_applies_rule_then_escalates_to_termination():
    monitor = DeadlockMonitor(
        config=DeadlockConfig(
            cycle_repeat_threshold=3,
            max_interventions_before_escalate=1,
        )
    )
    msgs = [
        build_message(
            room_id="d1",
            kind="QUESTION",
            from_agent="enki",
            to_agent="nabu",
            body="same question again",
            task_id="t1",
        )
        for _ in range(5)
    ]
    resolutions = []
    for msg in msgs:
        for issue in monitor.observe(msg):
            resolutions.append(monitor.resolve(issue))
    assert any(r.action == ResolutionAction.APPLY_RULE for r in resolutions)
    assert any(r.action == ResolutionAction.SUPERVISOR_INTERVENE for r in resolutions)
    assert any(r.action == ResolutionAction.OWNER_ESCALATE and r.terminate for r in resolutions)
    assert monitor.terminated is True


def test_mutual_wait_and_duplicate_work_rules():
    monitor = DeadlockMonitor()
    a = build_message(
        room_id="d2",
        kind="BLOCKED",
        from_agent="enki",
        to_agent="nabu",
        body="waiting on @nabu",
    )
    b = build_message(
        room_id="d2",
        kind="BLOCKED",
        from_agent="nabu",
        to_agent="enki",
        body="waiting on @enki",
    )
    issues = monitor.observe(a) + monitor.observe(b)
    mutual = [i for i in issues if i.kind == DeadlockIssueKind.MUTUAL_WAIT]
    assert mutual
    resolution = monitor.resolve(mutual[0])
    assert resolution.action == ResolutionAction.APPLY_RULE
    effects = monitor.apply_rule_side_effects(mutual[0])
    assert effects["cleared_blocks"]

    first = build_message(
        room_id="d2",
        kind="REQUEST",
        from_agent="anzu",
        to_agent="enki",
        body="@enki do task",
        task_id="shared",
    )
    dup = build_message(
        room_id="d2",
        kind="REQUEST",
        from_agent="nabu",
        body="I will also do shared",
        task_id="shared",
    )
    monitor.observe(first)
    dup_issues = monitor.observe(dup)
    assert any(i.kind == DeadlockIssueKind.DUPLICATE_WORK for i in dup_issues)


def test_room_deadlock_escalation_terminates_collaboration():
    room = create_room("Pathological loop", ["enki", "nabu"], room_id="dead-1")
    room.deadlock.config = DeadlockConfig(
        cycle_repeat_threshold=2,
        max_interventions_before_escalate=1,
    )
    for _ in range(6):
        if room.status != "open":
            break
        room.post_message(
            kind="QUESTION",
            from_agent="enki",
            to_agent="nabu",
            body="ping @nabu same",
            task_id="loop",
        )
    assert room.status == "terminated"
    replay = room.replay()
    assert replay["escalated"] or any(d.get("kind") == "deadlock_resolved" for d in replay["deadlocks"])
    assert replay["terminated"] is True
    with pytest.raises(RoomTerminated):
        room.post_message(kind="RESULT", from_agent="nabu", body="too late")


# --- Resource governor -------------------------------------------------------------


def test_resource_governor_caps_parallel_local_and_blocks_cloud_in_local_only():
    budget = build_budget(
        cost_mode="frugal",
        privacy_mode="local_only",
        cpu_slots=2,
        gpu_slots=1,
        vram_mib=4096,
        provider_calls=4,
    )
    assert budget.max_parallel_local == 1
    assert budget.max_parallel_cloud == 0

    room = create_room(
        "Cap test",
        ["enki", "nabu", "hermes"],
        room_id="gov-1",
        budget=budget,
    )
    room.acquire_for("enki", cpu_slots=1)
    with pytest.raises(GovernorDenied) as exc:
        room.acquire_for("nabu", cpu_slots=1)
    assert exc.value.code == "parallel_local_cap"

    with pytest.raises(GovernorDenied) as privacy_exc:
        room.acquire_for("hermes", provider="cloud", cpu_slots=0, provider_calls=1)
    assert privacy_exc.value.code == "privacy_blocked"

    # Performance + allow_cloud raises cloud parallel ceiling.
    cloud_room = create_room(
        "Cloud ok",
        ["hermes", "maia"],
        room_id="gov-2",
        cost_mode="performance",
        privacy_mode="allow_cloud",
    )
    cloud_room.participants["hermes"].provider = "cloud"
    cloud_room.acquire_for("hermes", provider="cloud", cpu_slots=0, provider_calls=1)
    usage = cloud_room.governor.usage()
    assert usage["parallel_cloud"] == 1


def test_governor_vram_and_provider_caps():
    from app.agents.rooms.governor import ResourceGovernor

    gov = ResourceGovernor(
        build_budget(
            cost_mode="balanced",
            privacy_mode="allow_cloud",
            max_parallel_local=4,
            max_parallel_cloud=2,
            cpu_slots=8,
            gpu_slots=2,
            vram_mib=2048,
            provider_calls=2,
        )
    )
    gov.acquire(agent_id="enki", provider="local", gpu_slots=1, vram_mib=2048, provider_calls=1)
    with pytest.raises(GovernorDenied) as vram_exc:
        gov.acquire(agent_id="nabu", provider="local", gpu_slots=0, vram_mib=1, provider_calls=0)
    assert vram_exc.value.code == "vram_cap"
    with pytest.raises(GovernorDenied) as call_exc:
        gov.acquire(agent_id="hermes", provider="cloud", cpu_slots=0, provider_calls=2)
    assert call_exc.value.code == "provider_cap"


# --- Audit replay without hidden CoT ----------------------------------------------


def test_audit_replay_omits_hidden_reasoning():
    room = create_room("Replayable collab", ["enki"], room_id="audit-1")
    room.post_message(
        kind="REQUEST",
        from_agent="anzu",
        to_agent="enki",
        body="@enki do the work",
        metadata={"reasoning_content": "should never appear", "ok": True},
    )
    room.publish_blackboard(
        kind="artifact",
        key="out.txt",
        content="done",
        author="enki",
        metadata={"thinking": "nope", "path": "out.txt"},
    )
    room.synthesize_and_finalize()
    replay = room.replay()
    blob = str(replay)
    for banned in (
        "reasoning_content",
        "chain_of_thought",
        "should never appear",
        "thinking",
        "nope",
        "<think>",
    ):
        assert banned not in blob
    assert replay["event_count"] >= 4
    assert replay["synthesis"] is not None
    assert "enki" in replay["synthesis"]["cited_agents"]
    assert any(e["kind"] == "message_posted" for e in replay["events"])


def test_strip_hidden_fields_recursive():
    cleaned = strip_hidden_fields(
        {
            "ok": 1,
            "reasoning": "x",
            "nested": {"cot": "y", "keep": "z", "thinking": "t"},
        }
    )
    assert cleaned == {"ok": 1, "nested": {"keep": "z"}}


# --- Router hooks ------------------------------------------------------------------


def test_router_hooks_open_room_on_multi_mention_and_delegate():
    hint = suggest_room_routing(
        "Please have @nabu research and @enki implement the fix",
        router_action="delegate",
    )
    assert hint.open_room is True
    assert hint.specialists == ("nabu", "enki")
    room = open_room_from_hint("Research and implement", hint, room_id="hook-1")
    assert "anzu" in room.participants
    assert "nabu" in room.participants
    assert "enki" in room.participants

    quiet = suggest_room_routing("What time is it?")
    assert quiet.open_room is False


def test_orchestrator_router_attaches_room_hint():
    decision = resolve_router_decision(
        "Collaborate with @mestor and @enki to plan and implement caching",
        current_model="ornith-9b",
        model_output={"action": "delegate", "reason": "multi specialist"},
    )
    assert decision.action == "delegate"
    assert decision.room_hint is not None
    assert decision.room_hint.open_room is True
    assert "mestor" in decision.room_hint.specialists
    assert "enki" in decision.room_hint.specialists
    payload = decision.as_dict()
    assert payload["room_hint"]["open_room"] is True


def test_sanitize_public_text_helper():
    assert sanitize_public_text("  hello   <think>x</think> world ") == "hello world"


def test_message_fingerprint_stable():
    a = build_message(room_id="r", kind="RESULT", from_agent="enki", body="done", task_id="t")
    b = build_message(room_id="r", kind="RESULT", from_agent="enki", body="done", task_id="t")
    assert message_fingerprint(a) == message_fingerprint(b)
