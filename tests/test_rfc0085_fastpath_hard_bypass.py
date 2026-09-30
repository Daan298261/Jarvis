"""RFC-0085: universal task fast path must hard-bypass the heavy turn pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agent.front_responder import FrontReply
from app.agent.loop import AGENT
from app.agent.planning import CONVERSATION_CLASS, DIRECT_LOOKUP, DIRECT_REPLY, MANAGED_TASK, route_request
from app.agent.task_fastpath import (
    admit_fastpath,
    admit_lookup_fastpath,
    fastpath_stats,
    note_fastpath_decision,
    reset_fastpath_stats,
    resolve_route_kind,
    should_skip_background_verify,
)
from app.db.models import Task, TaskEvent
from app.db.session import SessionLocal
from app.inference.manager import MANAGER
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _reset_fastpath_counters():
    reset_fastpath_stats()
    yield
    reset_fastpath_stats()


def test_admit_fastpath_terminal_direct_reply():
    decision = admit_fastpath(
        "How are you?",
        route_kind=DIRECT_REPLY,
        front_action="final_basic",
        front_text="Hello, sir.",
    )
    assert decision.admitted is True
    assert decision.reason == "direct_reply_terminal_front"
    assert "background_verify" in decision.stages_skipped
    assert "worker_stream" in decision.stages_skipped


def test_admit_fastpath_fails_closed_for_managed_and_worker_actions():
    managed = admit_fastpath(
        "Install the update",
        route_kind=MANAGED_TASK,
        front_action="ack_continue",
        front_text="On it.",
    )
    assert managed.admitted is False
    assert managed.reason == "managed_task"

    needs_worker = admit_fastpath(
        "Explain the architecture briefly",
        route_kind=DIRECT_REPLY,
        front_action="ack_continue",
        front_text="Checking the details.",
    )
    assert needs_worker.admitted is False
    assert needs_worker.reason == "front_requires_worker"

    empty = admit_fastpath(
        "How are you?",
        route_kind=DIRECT_REPLY,
        front_action="final_basic",
        front_text="",
    )
    assert empty.admitted is False
    assert empty.reason == "empty_front_text"


def test_admit_lookup_fastpath_requires_briefing():
    miss = admit_lookup_fastpath("weather in dinteloord", route_kind=DIRECT_LOOKUP, briefing=None)
    assert miss.admitted is False
    hit = admit_lookup_fastpath(
        "weather in dinteloord",
        route_kind=DIRECT_LOOKUP,
        briefing="Live meteorological briefing\nHigh: 16",
    )
    assert hit.admitted is True
    assert "background_verify" in hit.stages_skipped


def test_fastpath_metrics_distinguish_hit_and_miss():
    hit = admit_fastpath(
        "hi",
        route_kind=DIRECT_REPLY,
        front_action="final_basic",
        front_text="Hello, sir.",
    )
    note_fastpath_decision(hit, task_id="t-hit")
    miss = admit_fastpath(
        "refactor the auth module",
        route_kind=MANAGED_TASK,
        front_action="ack_continue",
        front_text="On it.",
    )
    note_fastpath_decision(miss, task_id="t-miss")
    stats = fastpath_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["by_reason"]["direct_reply_terminal_front"] == 1
    assert stats["by_reason"]["managed_task"] == 1
    assert stats["last"]["task_id"] == "t-miss"
    assert should_skip_background_verify(DIRECT_REPLY) is True
    assert should_skip_background_verify(DIRECT_LOOKUP) is True
    assert should_skip_background_verify(MANAGED_TASK) is False


def test_resolve_route_kind_prefers_stored_direct_lanes():
    assert resolve_route_kind("ignored", stored_route=DIRECT_REPLY) == DIRECT_REPLY
    assert resolve_route_kind("Install updates and verify", stored_route="") == MANAGED_TASK
    assert route_request("How are you?").kind == DIRECT_REPLY


@pytest.mark.asyncio
async def test_eligible_direct_reply_bypasses_heavy_stages_even_when_model_warm(jarvis_env, monkeypatch):
    """Warm model must not force worker/verify — that was the soft/decorative path."""
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    heavy_calls: list[str] = []

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            heavy_calls.append("worker_stream")
            yield "Should not run on terminal fast path."

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            from app.providers.base import ChatResult

            heavy_calls.append("worker_chat")
            return ChatResult(content="unexpected")

    MANAGER.provider = StreamProvider()
    MANAGER.state.loaded = True
    MANAGER.state.context_size = 16384

    async def front(*_a, **_k):
        return FrontReply(
            action="final_basic",
            text="Hello, sir.",
            model="front",
            first_text_ms=4.0,
            complete_ms=5.0,
        )

    async def boom_prepare(*_a, **_k):
        heavy_calls.append("prepare_answer_route")
        raise AssertionError("prepare_answer_route must not run on fastpath hit")

    async def boom_verify(*_a, **_k):
        heavy_calls.append("background_verify")
        raise AssertionError("background_verify must not run on fastpath hit")

    async def boom_progress(*_a, **_k):
        heavy_calls.append("progress_watchdog")
        raise AssertionError("progress_watchdog must not run on fastpath hit")

    monkeypatch.setattr("app.agent.loop.generate_front_reply", front)
    monkeypatch.setattr("app.inference.answer_routing.prepare_answer_route", boom_prepare)
    monkeypatch.setattr(
        "app.agent.background_verify.schedule_background_verification",
        boom_verify,
    )
    monkeypatch.setattr("app.agent.loop.run_worker_progress_watchdog", boom_progress)

    task = await AGENT.create_task("How are you?")
    assert task.response_route == DIRECT_REPLY
    runner = AGENT._tasks.get(task.id)
    if runner:
        await runner

    async with SessionLocal() as session:
        row = await session.get(Task, task.id)
        assert row is not None
        assert row.status == "completed"
        assert "Hello" in (row.result or "")
        events = (
            await session.execute(select(TaskEvent).where(TaskEvent.task_id == task.id))
        ).scalars().all()
        kinds = {item.kind for item in events}
        assert "fastpath" in kinds
        assert any(item.kind == "fastpath" and "hit" in (item.title or "").lower() for item in events)
        assert any(item.kind == "response_timing" and "fastpath" in (item.detail or "") for item in events)

    assert heavy_calls == []
    stats = fastpath_stats()
    assert stats["hits"] >= 1
    assert stats["last"]["admitted"] is True
    assert stats["last"]["reason"] == "direct_reply_terminal_front"


@pytest.mark.asyncio
async def test_ineligible_managed_task_misses_fastpath_and_uses_normal_path(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    prepare_calls: list[str] = []

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "Working."

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            from app.providers.base import ChatResult

            return ChatResult(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "filesystem", "arguments": '{"action":"list","path":"."}'},
                    }
                ],
            )

    MANAGER.provider = StreamProvider()
    MANAGER.state.loaded = True
    MANAGER.state.context_size = 16384

    async def track_front(*_a, **_k):
        return FrontReply(
            action="ack_continue",
            text="On it.",
            model="front",
            first_text_ms=2.0,
            complete_ms=2.0,
        )

    monkeypatch.setattr("app.agent.loop.generate_front_reply", track_front)
    monkeypatch.setattr("app.agent.loop.run_worker_progress_watchdog", AsyncMock(return_value=None))

    original_admit = admit_fastpath

    def wrapped_admit(prompt, **kwargs):
        decision = original_admit(prompt, **kwargs)
        prepare_calls.append(decision.reason)
        return decision

    # Managed tasks never enter _run_conversation admission; route stays managed.
    task = await AGENT.create_task("Install the update and verify it works")
    assert task.response_route == MANAGED_TASK
    assert route_request(task.prompt).kind == MANAGED_TASK

    # Conversation-path admission helpers still fail closed for managed.
    decision = admit_fastpath(
        task.prompt,
        route_kind=task.response_route,
        front_action="ack_continue",
        front_text="On it.",
    )
    assert decision.admitted is False
    note_fastpath_decision(decision, task_id=task.id)
    stats = fastpath_stats()
    assert stats["misses"] >= 1
    assert stats["by_reason"].get("managed_task", 0) >= 1
    del wrapped_admit


@pytest.mark.asyncio
async def test_direct_lookup_uses_lean_path_without_background_verify(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    verify_calls: list[str] = []
    streams: list[str] = []

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del kwargs
            streams.append("stream")
            joined = "\n".join(m.content or "" for m in messages if m.role == "system")
            assert "Open-Meteo" in joined
            yield "Mild rain in Dinteloord tomorrow, sir."

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            raise AssertionError("lookup must not enter the tool chat() loop")

    async def briefing(prompt: str):
        assert "dinteloord" in prompt.lower()
        return (
            "Live meteorological briefing (Open-Meteo). Do not write code.\n"
            "Place: Dinteloord\nDay: tomorrow\nHigh: 16°C"
        )

    async def boom_verify(*_a, **_k):
        verify_calls.append("verify")
        raise AssertionError("direct_lookup must skip background verify")

    async def front(*_a, **_k):
        return FrontReply(
            action="ack_continue",
            text="Checking the forecast.",
            model="front",
            first_text_ms=3.0,
            complete_ms=3.0,
        )

    monkeypatch.setattr("app.agent.loop.weather_system_message", briefing)
    monkeypatch.setattr("app.agent.loop.generate_front_reply", front)
    monkeypatch.setattr(
        "app.agent.background_verify.schedule_background_verification",
        boom_verify,
    )
    monkeypatch.setattr("app.agent.loop.run_worker_progress_watchdog", AsyncMock(return_value=None))
    MANAGER.provider = StreamProvider()
    MANAGER.state.loaded = True
    MANAGER.state.context_size = 16384

    task = await AGENT.create_task("what is the weather in dinteloord, tomorrow")
    assert task.response_route == DIRECT_LOOKUP
    runner = AGENT._tasks.get(task.id)
    if runner:
        await runner

    async with SessionLocal() as session:
        row = await session.get(Task, task.id)
        assert row is not None
        assert row.status == "completed"
        assert "dinteloord" in (row.result or "").lower()
        # Answer must not be treated as independent verification evidence.
        from app.agent.execution_status import verification_summary

        assert verification_summary(row)["result"] == "NOT_VERIFIED"
        assert "NOT_VERIFIED" in (row.verification or "")
        events = (
            await session.execute(select(TaskEvent).where(TaskEvent.task_id == task.id))
        ).scalars().all()
        assert any(item.kind == "fastpath" and "hit" in (item.title or "").lower() for item in events)

    assert streams  # one lean answer stream
    assert verify_calls == []
    stats = fastpath_stats()
    assert stats["hits"] >= 1
    assert stats["last"]["reason"] == "direct_lookup_briefing"


@pytest.mark.asyncio
async def test_no_soft_stub_empty_front_falls_through_to_normal_path(jarvis_env, monkeypatch):
    """Empty/unsafe front must fail closed — never invent a completed answer."""
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    worker_ran = {"ok": False}

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            worker_ran["ok"] = True
            yield "A proper worker answer."

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            from app.providers.base import ChatResult

            return ChatResult(content="A proper worker answer.")

    async def empty_front(*_a, **_k):
        return FrontReply(action="final_basic", text="", model="front", skipped=True)

    monkeypatch.setattr("app.agent.loop.generate_front_reply", empty_front)
    monkeypatch.setattr("app.agent.loop.run_worker_progress_watchdog", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.agent.background_verify.schedule_background_verification",
        lambda *_a, **_k: None,
    )
    MANAGER.provider = StreamProvider()
    MANAGER.state.loaded = True
    MANAGER.state.context_size = 16384

    task = await AGENT.create_task("How are you this evening?")
    runner = AGENT._tasks.get(task.id)
    if runner:
        await runner

    async with SessionLocal() as session:
        row = await session.get(Task, task.id)
        assert row is not None
        assert row.status == "completed"
        assert "proper worker answer" in (row.result or "").lower()

    assert worker_ran["ok"] is True
    stats = fastpath_stats()
    assert stats["misses"] >= 1
    assert stats["last"]["admitted"] is False
    assert stats["last"]["reason"] in {"empty_front_text", "unsafe_front_speech", "missing_front_action"}
