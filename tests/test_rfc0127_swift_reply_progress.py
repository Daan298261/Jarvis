"""RFC-0127: swift front ack and slow-worker progress feedback."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LOOP = REPO_ROOT / "backend" / "app" / "agent" / "loop.py"
from app.agent.front_responder import (
    FrontReply,
    generate_front_reply,
    generate_progress_update,
    progress_template_for_context,
    run_two_lane_chat,
)
from app.agent.loop import AGENT
from app.agent.metrics import LiveTaskMetrics
from app.agent.planning import CONVERSATION_CLASS, WorkingState
from app.agent.worker_progress import (
    WORKER_PROGRESS_FIRST_DELAY_SECONDS,
    clear_worker_progress_for_task,
    emit_worker_progress_update,
    mark_worker_useful_owner_text,
    reset_worker_progress_state,
    run_worker_progress_watchdog,
    worker_useful_text_seen,
)
from app.config import AppSettings, FrontResponderSettings
from app.db.models import Task
from app.db.session import SessionLocal
from app.inference.manager import MANAGER
from app.persona.owner_chat import stream_owner_chat

@pytest.fixture(autouse=True)
def _clean_progress_state():
    reset_worker_progress_state()
    yield
    reset_worker_progress_state()

@pytest.mark.asyncio
async def test_generate_front_reply_fallback_ack_when_no_provider():
    settings = AppSettings(front_responder=FrontResponderSettings(enabled=True, model="tiny-front"))
    with patch("app.agent.front_responder.front_provider", return_value=None):
        reply = await generate_front_reply("Please refactor the auth module and run pytest.", settings=settings)
    assert reply.action in {"ack_continue", "handoff_notice"}
    assert reply.text
    assert (reply.first_text_ms or 0) >= 0
    assert (reply.complete_ms or 0) >= 0


def test_managed_follow_up_turn_starts_swift_lane_and_progress():
    """Task follow-ups use continue_existing=True with extra_prompt; must still ack."""
    text = LOOP.read_text(encoding="utf-8")
    assert 'user_turn = (extra_prompt or "").strip()' in text
    assert "not pending_tool and (not continue_existing or user_turn)" in text


def test_mark_worker_useful_records_task():
    task_id = "task-useful-text"
    clear_worker_progress_for_task(task_id)
    assert not worker_useful_text_seen(task_id)
    mark_worker_useful_owner_text(task_id)
    assert worker_useful_text_seen(task_id)
    clear_worker_progress_for_task(task_id)
    assert not worker_useful_text_seen(task_id)

@pytest.mark.asyncio
async def test_prefetched_front_not_regenerated_in_two_lane():
    settings = AppSettings(front_responder=FrontResponderSettings(enabled=True))
    prefetched = FrontReply(action="ack_continue", text="On it, sir.", model="front", first_text_ms=12.0)
    async def worker_stream():
        yield " deeper answer"
    with patch("app.agent.front_responder.generate_front_reply", new_callable=AsyncMock) as mock_gen:
        events = []
        async for event in run_two_lane_chat("explain the architecture", settings=settings, worker_stream=worker_stream, prefetched_front=prefetched):
            events.append(event)
        mock_gen.assert_not_called()
    assert any(event.get("type") == "done" for event in events)

@pytest.mark.asyncio
async def test_progress_watchdog_emits_after_60s(monkeypatch):
    task_id = "task-progress-1"
    clear_worker_progress_for_task(task_id)
    fake_mono = {"t": 1000.0}
    fake_perf = {"t": 5000.0}
    monkeypatch.setattr("app.agent.worker_progress.time.monotonic", lambda: fake_mono["t"])
    monkeypatch.setattr("app.agent.worker_progress.time.perf_counter", lambda: fake_perf["t"])
    sleep_log: list[float] = []
    async def fake_sleep(seconds: float) -> None:
        sleep_log.append(seconds)
        if seconds >= WORKER_PROGRESS_FIRST_DELAY_SECONDS:
            fake_perf["t"] = 5000.0 + WORKER_PROGRESS_FIRST_DELAY_SECONDS + 1
    emitted = AsyncMock(return_value={"tts_id": "x"})

    class _RunningTask:
        status = "running"

    async def still_running() -> bool:
        return len(sleep_log) < 5

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=_RunningTask())
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_session
    mock_cm.__aexit__.return_value = None

    with patch("app.agent.worker_progress.SessionLocal", return_value=mock_cm):
        with patch("app.agent.worker_progress.emit_worker_progress_update", emitted):
            await run_worker_progress_watchdog(
                task_id,
                turn_started=5000.0,
                should_continue=still_running,
                sleep=fake_sleep,
                monotonic=lambda: fake_mono["t"],
                perf_counter=lambda: fake_perf["t"],
            )
    emitted.assert_awaited()

@pytest.mark.asyncio
async def test_progress_cooldown_blocks_spam():
    task_id = "task-cooldown"
    clear_worker_progress_for_task(task_id)
    now = 2000.0
    with patch("app.agent.worker_progress.time.monotonic", lambda: now):
        with patch("app.agent.worker_progress.generate_progress_update", new_callable=AsyncMock, return_value="Still loading."):
            with patch("app.agent.worker_progress.publish_owner_text", new_callable=AsyncMock, return_value={"tts_id": "1"}):
                with patch("app.agent.worker_progress.BUS.publish", new_callable=AsyncMock):
                    first = await emit_worker_progress_update(task_id, context="Loading local model")
                    now += 10.0
                    second = await emit_worker_progress_update(task_id, context="Loading local model")
    assert first is not None and second is None

@pytest.mark.asyncio
async def test_generate_progress_update_template_when_disabled():
    settings = AppSettings(front_responder=FrontResponderSettings(enabled=False))
    line = await generate_progress_update("Loading local model", settings=settings)
    assert line == progress_template_for_context("Loading local model")


@pytest.mark.asyncio
async def test_stream_owner_chat_front_reply_before_model_load(jarvis_env, monkeypatch):
    """Swift ack must run before MANAGER.load on owner chat turns."""
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    order: list[str] = []
    MANAGER.provider = None
    MANAGER.state.loaded = False

    prefetched = FrontReply(
        action="ack_continue",
        text="On it, sir.",
        model="front",
        first_text_ms=4.0,
        complete_ms=4.0,
    )

    async def track_front(*args, **kwargs):
        order.append("front")
        return prefetched

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "Certainly."

    async def track_load(settings, profile_name=None):
        order.append("load")
        MANAGER.provider = StreamProvider()
        MANAGER.state.loaded = True

    monkeypatch.setattr("app.persona.owner_chat.generate_front_reply", track_front)
    monkeypatch.setattr("app.persona.owner_chat.MANAGER.load", track_load)

    events: list[dict] = []
    async for event in stream_owner_chat("Tell me a quick hello."):
        events.append(event)

    assert "front" in order and "load" in order
    assert order.index("front") < order.index("load")
    assert any(event.get("type") == "done" for event in events)


@pytest.mark.asyncio
async def test_run_conversation_front_reply_before_model_load(jarvis_env, monkeypatch):
    """Conversation lane must prefetch/speak front ack before worker model load."""
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    order: list[str] = []
    MANAGER.provider = None
    MANAGER.state.loaded = False

    task_id = "conv-front-before-load"
    async with SessionLocal() as session:
        session.add(
            Task(
                id=task_id,
                title="How are you?",
                prompt="How are you this evening?",
                status="running",
                stage="act",
                task_class=CONVERSATION_CLASS,
                response_route="conversation",
            )
        )
        await session.commit()

    prefetched = FrontReply(
        action="ack_continue",
        text="All well on my side.",
        model="front",
        first_text_ms=3.0,
        complete_ms=3.0,
    )

    async def track_front(*args, **kwargs):
        order.append("front")
        return prefetched

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "All well here."

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            from app.providers.base import ChatResult

            return ChatResult(content="All well here.")

    async def track_load(settings, profile_name=None):
        order.append("load")
        MANAGER.provider = StreamProvider()
        MANAGER.state.loaded = True
        MANAGER.state.context_size = 16384

    async def noop_progress_watchdog(*args, **kwargs):
        return None

    monkeypatch.setattr("app.agent.loop.generate_front_reply", track_front)
    monkeypatch.setattr("app.agent.loop.MANAGER.load", track_load)
    monkeypatch.setattr("app.agent.loop.run_worker_progress_watchdog", noop_progress_watchdog)

    await AGENT._run_conversation(
        task_id,
        "How are you this evening?",
        None,
        jarvis_env["settings"],
        WorkingState(goal="How are you this evening?", task_class=CONVERSATION_CLASS),
        LiveTaskMetrics(),
    )

    assert order.index("front") < order.index("load")


@pytest.mark.asyncio
async def test_managed_front_lane_fallback_ack_when_front_skipped(jarvis_env, monkeypatch):
    """Managed path must still TTS a template ack when front lane returns silent_skip."""
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    task_id = "managed-front-fallback"
    prompt = "Please refactor the auth module and run pytest."
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

    silent_front = FrontReply(action="silent_skip", text="", model="front", skipped=True)
    monkeypatch.setattr(
        "app.agent.loop.generate_front_reply",
        AsyncMock(return_value=silent_front),
    )

    published: list[tuple[str, dict]] = []

    async def capture_publish(text, **kwargs):
        published.append((text, kwargs))
        return {"tts_id": "ack-1"}

    monkeypatch.setattr("app.agent.loop.publish_owner_text", capture_publish)

    await AGENT._run_managed_front_lane(
        task_id,
        prompt,
        jarvis_env["settings"],
        turn_started=time.perf_counter(),
    )

    assert published
    assert published[0][1].get("source") == "task_chat"
    assert (published[0][0] or "").strip()
    async with SessionLocal() as session:
        row = await session.get(Task, task_id)
        assert row is not None
        assert (row.result or "").strip()
