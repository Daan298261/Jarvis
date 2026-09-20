"""RFC-0127: swift front ack and slow-worker progress feedback."""
from __future__ import annotations
from unittest.mock import AsyncMock, patch
import pytest
from app.agent.front_responder import (
    SAFE_ACK,
    FrontReply,
    generate_front_reply,
    generate_progress_update,
    progress_template_for_context,
    run_two_lane_chat,
)
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
