"""Owner-shell delivery: no duplicate deeper block, one late ack, early retrieval."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from app.agent.front_responder import (
    ACK_HOLD_SECONDS,
    FrontReply,
    apply_disposition,
    infer_arbitration_disposition,
    merge_front_and_worker,
    note_worker_first_sentence,
    wait_for_late_ack,
)
from app.agent.loop import AGENT
from app.agent.metrics import LiveTaskMetrics
from app.agent.planning import WorkingState
from app.agent.task_fastpath import FastpathDecision
from app.db.models import Task
from app.db.session import SessionLocal
from app.inference.front_runtime import FRONT_RUNTIME
from app.inference.manager import MANAGER
from app.persona.owner_chat import reset_owner_conversations, stream_owner_chat

ROOT = Path(__file__).resolve().parents[1]
LABEL = "Deeper" + " result"


@pytest.fixture(autouse=True)
def _reset_front_runtime():
    FRONT_RUNTIME.reset_for_tests()
    yield
    FRONT_RUNTIME.reset_for_tests()


async def _instant_working_set(*_args, **_kwargs):
    from app.agent.turn_working_set import TurnWorkingSet

    return TurnWorkingSet(user_message="weather", task_class="conversation")


def test_ack_hold_default_is_about_one_point_two_seconds():
    assert ACK_HOLD_SECONDS == pytest.approx(1.2)


def test_duplicate_worker_is_suppressed_and_new_info_is_kept():
    front = (
        "Those black bars are just letterboxing. "
        "Tell me your screen resolution and I'll match the viewport."
    )
    duplicate = (
        "Those black bars you're seeing are just my viewport padding. "
        "If they bother you, tell me your screen resolution."
    )
    suppressed = apply_disposition(infer_arbitration_disposition(front, duplicate), front, duplicate)
    assert suppressed == front
    assert LABEL not in suppressed

    extended = merge_front_and_worker(
        "On it. I'll check the details.",
        "Mild rain later, sir.",
        "ack_continue",
    )
    assert extended.startswith("On it.")
    assert "Mild rain later, sir." in extended
    assert LABEL not in extended

    corrected = apply_disposition(
        infer_arbitration_disposition(
            "The meeting is at 3.",
            "The meeting was moved to 4:30, and it's in the north conference room.",
        ),
        "The meeting is at 3.",
        "The meeting was moved to 4:30, and it's in the north conference room.",
    )
    assert "4:30" in corrected
    assert "north conference room" in corrected
    assert LABEL not in corrected


def test_no_deeper_result_label_in_product_sources():
    roots = [ROOT / "backend" / "app", ROOT / "frontend" / "src"]
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx", ".css"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if LABEL in text:
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


@pytest.mark.asyncio
async def test_late_ack_rules():
    ready = asyncio.Event()
    started = time.perf_counter()
    assert await wait_for_late_ack("final_basic", turn_started=started, worker_ready=ready, hold_s=5) is True
    assert time.perf_counter() - started < 0.2

    clarify = asyncio.Event()
    started = time.perf_counter()
    assert await wait_for_late_ack(
        "ask_clarification", turn_started=started, worker_ready=clarify, hold_s=5
    ) is True
    assert time.perf_counter() - started < 0.2

    early = asyncio.Event()
    early.set()
    assert await wait_for_late_ack(
        "ack_continue", turn_started=time.perf_counter(), worker_ready=early, hold_s=5
    ) is False

    late = asyncio.Event()
    started = time.perf_counter()
    assert await wait_for_late_ack(
        "handoff_notice", turn_started=started, worker_ready=late, hold_s=0.05
    ) is True
    assert time.perf_counter() - started >= 0.04


@pytest.mark.asyncio
async def test_owner_chat_suppresses_ack_when_worker_sentence_is_fast(jarvis_env, monkeypatch):
    del jarvis_env
    monkeypatch.setattr("app.agent.front_responder.ACK_HOLD_SECONDS", 0.4)

    class FrontProvider:
        model = "Qwen3.5-2B"

        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "Checking the details."

    async def worker_chat_stream(*_args, **_kwargs):
        yield "It will be mild."

    async def no_weather(_text: str):
        return None

    async def no_hydrate(_conversation_id: str):
        return []

    FRONT_RUNTIME.mark_for_tests(distinct=True, provider=FrontProvider())
    MANAGER.state.loaded = True
    MANAGER.provider = FrontProvider()
    monkeypatch.setattr(MANAGER, "chat_stream", worker_chat_stream)
    monkeypatch.setattr("app.agent.turn_working_set.compose_turn_working_set", _instant_working_set)
    monkeypatch.setattr("app.persona.owner_chat.weather_system_message", no_weather)
    monkeypatch.setattr("app.persona.owner_chat.hydrate_conversation", no_hydrate)
    reset_owner_conversations()

    events = []
    async for event in stream_owner_chat("What's the weather tomorrow?"):
        events.append(event)

    done = events[-1]
    assert done["type"] == "done"
    assert "mild" in (done.get("text") or "").lower()
    assert "Checking the details" not in (done.get("text") or "")
    assert not any(
        event.get("lane") == "front" and "Checking the details" in (event.get("text") or "")
        for event in events
    )
    assert LABEL not in (done.get("text") or "")


@pytest.mark.asyncio
async def test_owner_chat_shows_ack_when_worker_sentence_is_late(jarvis_env, monkeypatch):
    del jarvis_env
    monkeypatch.setattr("app.agent.front_responder.ACK_HOLD_SECONDS", 0.05)

    class FrontProvider:
        model = "Qwen3.5-2B"

        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "Checking the details."

    async def worker_chat_stream(*_args, **_kwargs):
        await asyncio.sleep(0.2)
        yield "It will be mild."

    async def no_weather(_text: str):
        return None

    async def no_hydrate(_conversation_id: str):
        return []

    FRONT_RUNTIME.mark_for_tests(distinct=True, provider=FrontProvider())
    MANAGER.state.loaded = True
    MANAGER.provider = FrontProvider()
    monkeypatch.setattr(MANAGER, "chat_stream", worker_chat_stream)
    monkeypatch.setattr("app.agent.turn_working_set.compose_turn_working_set", _instant_working_set)
    monkeypatch.setattr("app.persona.owner_chat.weather_system_message", no_weather)
    monkeypatch.setattr("app.persona.owner_chat.hydrate_conversation", no_hydrate)
    reset_owner_conversations()

    events = []
    async for event in stream_owner_chat("What's the weather tomorrow?"):
        events.append(event)

    texts = [event.get("text") or "" for event in events if event.get("type") == "delta"]
    assert any("Checking the details" in text for text in texts)
    done = events[-1]["text"]
    assert "mild" in done.lower()
    assert LABEL not in done


@pytest.mark.asyncio
async def test_final_basic_owner_chat_does_not_wait_for_ack_hold(jarvis_env, monkeypatch):
    del jarvis_env
    monkeypatch.setattr("app.agent.front_responder.ACK_HOLD_SECONDS", 5)

    class FrontProvider:
        model = "Qwen3.5-2B"

        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "Hello, sir."

    FRONT_RUNTIME.mark_for_tests(distinct=True, provider=FrontProvider())
    MANAGER.provider = None
    MANAGER.state.loaded = False

    async def boom_load(*_args, **_kwargs):
        raise AssertionError("terminal front must not load the worker")

    monkeypatch.setattr(MANAGER, "load", boom_load)
    reset_owner_conversations()
    started = time.perf_counter()
    events = []
    async for event in stream_owner_chat("Hello there"):
        events.append(event)
    assert time.perf_counter() - started < 1.0
    assert events[-1]["type"] == "done"
    assert events[-1].get("front_terminal") is True
    assert "Hello, sir." in events[-1]["text"]


@pytest.mark.asyncio
async def test_tool_delegation_does_not_emit_a_second_ack(jarvis_env, monkeypatch):
    del jarvis_env
    spoken: list[str] = []

    async def capture(text, **kwargs):
        spoken.append(text)
        return {"tts_id": None, "spoken": False, "text": text}

    class StubTask:
        id = "task-one-ack"

    async def create_task(prompt):
        del prompt
        return StubTask()

    monkeypatch.setattr("app.persona.owner_chat.publish_owner_text", capture)
    monkeypatch.setattr("app.agent.loop.AGENT.create_task", create_task)
    reset_owner_conversations()

    events = []
    async for event in stream_owner_chat("Run the filesystem tool on the notes."):
        events.append(event)

    assert spoken == []
    assert events[-1]["type"] == "done"
    assert events[-1].get("ack") == "loop"
    assert not (events[-1].get("reply") or "").strip()


@pytest.mark.asyncio
async def test_managed_lane_emits_exactly_one_ack_and_only_when_late(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.agent.front_responder.ACK_HOLD_SECONDS", 0.05)
    prompt = "Please refactor the auth module and run pytest."
    task_id = "one-ack-lane"
    async with SessionLocal() as session:
        session.add(
            Task(
                id=task_id,
                title=prompt[:80],
                prompt=prompt,
                status="running",
                stage="understand",
                task_class="software engineering",
                response_route="managed_task",
            )
        )
        await session.commit()

    published: list[str] = []

    async def capture(text, **kwargs):
        published.append(text)
        return {"tts_id": "ack-1", "spoken": True, "text": text}

    monkeypatch.setattr("app.agent.loop.publish_owner_text", capture)
    monkeypatch.setattr(
        "app.agent.loop.generate_front_reply",
        _async_front(FrontReply(action="ack_continue", text="On it.", model="front")),
    )
    await AGENT._run_managed_front_lane(
        task_id,
        prompt,
        jarvis_env["settings"],
        turn_started=time.perf_counter(),
    )
    assert published == ["On it."]

    published.clear()
    task_id = "one-ack-cancelled"
    async with SessionLocal() as session:
        session.add(
            Task(
                id=task_id,
                title=prompt[:80],
                prompt=prompt,
                status="running",
                stage="understand",
                task_class="software engineering",
                response_route="managed_task",
            )
        )
        await session.commit()

    async def beat_the_hold():
        await asyncio.sleep(0.01)
        note_worker_first_sentence(task_id)

    monkeypatch.setattr("app.agent.front_responder.ACK_HOLD_SECONDS", 0.3)
    poke = asyncio.create_task(beat_the_hold())
    await AGENT._run_managed_front_lane(
        task_id,
        prompt,
        jarvis_env["settings"],
        turn_started=time.perf_counter(),
    )
    await poke
    assert published == []


@pytest.mark.asyncio
async def test_retrieval_starts_with_front_and_terminal_skips_it(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    order: list[str] = []

    async def slow_compose(*_args, **_kwargs):
        order.append("compose_start")
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            order.append("compose_cancel")
            raise
        order.append("compose_done")
        from app.agent.turn_working_set import TurnWorkingSet

        return TurnWorkingSet(user_message="weather", task_class="conversation")

    async def front(*_args, **_kwargs):
        await asyncio.sleep(0)
        order.append("front")
        assert "compose_start" in order
        return FrontReply(action="final_basic", text="Hello.", model="front", first_text_ms=1, complete_ms=1)

    async def boom_load(*_args, **_kwargs):
        order.append("load")
        raise AssertionError("cancelled terminal path must not load")

    monkeypatch.setattr("app.agent.loop.compose_turn_working_set", slow_compose)
    monkeypatch.setattr("app.agent.turn_working_set.compose_turn_working_set", slow_compose)
    monkeypatch.setattr("app.agent.loop.generate_front_reply", front)
    monkeypatch.setattr("app.agent.loop.weather_system_message", _async_value(None))
    monkeypatch.setattr(
        "app.agent.loop.admit_fastpath",
        lambda *_a, **_k: FastpathDecision(
            admitted=True,
            reason="terminal_front",
            route_kind="direct_reply",
            stages_skipped=("worker", "verify"),
        ),
    )
    monkeypatch.setattr("app.agent.loop.note_fastpath_decision", lambda *_a, **_k: None)
    monkeypatch.setattr("app.agent.loop.publish_owner_text", _async_value({}))
    monkeypatch.setattr("app.agent.loop.MANAGER.load", boom_load)

    task_id = "retrieval-with-front"
    async with SessionLocal() as session:
        session.add(
            Task(
                id=task_id,
                title="Weather",
                prompt="What is the weather tomorrow?",
                status="running",
                stage="act",
                task_class="conversation",
                response_route="direct_reply",
            )
        )
        await session.commit()

    await AGENT._run_conversation(
        task_id,
        "What is the weather tomorrow?",
        None,
        jarvis_env["settings"],
        WorkingState(),
        LiveTaskMetrics(),
        history=[],
    )
    assert order.index("compose_start") < order.index("front")
    assert "compose_cancel" in order
    assert "load" not in order
    assert "compose_done" not in order


@pytest.mark.asyncio
async def test_owner_chat_starts_retrieval_beside_front_and_drops_it_on_terminal(jarvis_env, monkeypatch):
    del jarvis_env
    order: list[str] = []

    async def slow_compose(*_args, **_kwargs):
        order.append("compose_start")
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            order.append("compose_cancel")
            raise
        from app.agent.turn_working_set import TurnWorkingSet

        return TurnWorkingSet(user_message="weather", task_class="conversation")

    async def hydrate(*_args, **_kwargs):
        return []

    async def front(*_args, **_kwargs):
        # Retrieval is a sibling task: yield until it passes hydrate and enters compose.
        for _ in range(8):
            if "compose_start" in order:
                break
            await asyncio.sleep(0)
        order.append("front")
        assert "compose_start" in order
        return FrontReply(action="final_basic", text="Hello, sir.", model="front")

    async def boom_load(*_args, **_kwargs):
        order.append("load")
        raise AssertionError("terminal front must not load")

    monkeypatch.setattr("app.agent.turn_working_set.compose_turn_working_set", slow_compose)
    monkeypatch.setattr("app.persona.owner_chat.hydrate_conversation", hydrate)
    monkeypatch.setattr("app.persona.owner_chat.generate_front_reply", front)
    monkeypatch.setattr(MANAGER, "load", boom_load)
    MANAGER.provider = None
    MANAGER.state.loaded = False
    reset_owner_conversations()

    events = []
    async for event in stream_owner_chat("What's the weather tomorrow?"):
        events.append(event)

    assert order.index("compose_start") < order.index("front")
    assert "compose_cancel" in order
    assert "load" not in order
    assert events[-1].get("front_terminal") is True


@pytest.mark.asyncio
async def test_owner_chat_hides_worker_paraphrase_of_the_front_line(jarvis_env, monkeypatch):
    del jarvis_env
    monkeypatch.setattr("app.agent.front_responder.ACK_HOLD_SECONDS", 0.05)
    front_line = (
        "Those black bars are just letterboxing. "
        "Tell me your screen resolution and I'll match the viewport."
    )
    paraphrase = (
        "Those black bars you're seeing are just my viewport padding. "
        "If they bother you, tell me your screen resolution."
    )

    class FrontProvider:
        model = "Qwen3.5-2B"

        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield front_line

    async def worker_chat_stream(*_args, **_kwargs):
        await asyncio.sleep(0.2)
        yield paraphrase

    FRONT_RUNTIME.mark_for_tests(distinct=True, provider=FrontProvider())
    MANAGER.state.loaded = True
    MANAGER.provider = FrontProvider()
    monkeypatch.setattr(MANAGER, "chat_stream", worker_chat_stream)
    monkeypatch.setattr("app.agent.turn_working_set.compose_turn_working_set", _instant_working_set)
    monkeypatch.setattr("app.persona.owner_chat.weather_system_message", _async_value(None))
    monkeypatch.setattr("app.persona.owner_chat.hydrate_conversation", _async_value([]))
    reset_owner_conversations()

    events = []
    async for event in stream_owner_chat("Why are there black bars on the screen?"):
        events.append(event)

    done = events[-1]["text"]
    assert "letterboxing" in done
    assert "viewport padding" not in done
    assert LABEL not in done


@pytest.mark.asyncio
async def test_owner_terminal_turn_does_not_retrieve_or_load(jarvis_env, monkeypatch):
    del jarvis_env
    calls: list[str] = []

    async def slow_compose(*_args, **_kwargs):
        calls.append("compose")
        from app.agent.turn_working_set import TurnWorkingSet

        return TurnWorkingSet(user_message="hi", task_class="conversation")

    async def boom_load(*_args, **_kwargs):
        calls.append("load")
        raise AssertionError("terminal front must not load")

    class FrontProvider:
        model = "Qwen3.5-2B"

        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "Hello, sir."

    monkeypatch.setattr("app.agent.turn_working_set.compose_turn_working_set", slow_compose)
    monkeypatch.setattr(MANAGER, "load", boom_load)
    FRONT_RUNTIME.mark_for_tests(distinct=True, provider=FrontProvider())
    MANAGER.provider = None
    MANAGER.state.loaded = False
    reset_owner_conversations()

    events = []
    async for event in stream_owner_chat("Hello there"):
        events.append(event)

    assert calls == []
    assert events[-1].get("front_terminal") is True


def _async_front(reply: FrontReply):
    async def _inner(*_args, **_kwargs):
        return reply

    return _inner


def _async_value(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner


