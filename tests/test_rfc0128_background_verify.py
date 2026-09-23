from __future__ import annotations

import asyncio

import pytest

from app.agent.background_verify import (
    FOLLOWUP_PREFIX,
    VERIFIED_OK_TOKEN,
    answers_equivalent,
    background_verify_enabled,
    build_verification_messages,
    execute_background_verification,
    is_verified_ok,
    materially_different,
    reset_background_verify_state,
    schedule_background_verification,
)
from app.agent.compaction import deserialize_messages
from app.db.models import Task
from app.db.session import SessionLocal
from app.inference.manager import MANAGER
from app.persona.chat_delivery import pending_chat_tts, reset_chat_delivery
from app.persona.owner_chat import (
    append_owner_assistant_message,
    get_conversation,
    reset_owner_conversations,
    stream_owner_chat,
)


@pytest.fixture(autouse=True)
def _reset_state():
    reset_background_verify_state()
    reset_owner_conversations()
    reset_chat_delivery()
    yield
    reset_background_verify_state()
    reset_owner_conversations()
    reset_chat_delivery()


def test_is_verified_ok_and_equivalence():
    assert is_verified_ok("VERIFIED_OK")
    assert is_verified_ok("  verified_ok  ")
    assert is_verified_ok("SAME")
    assert not is_verified_ok("Paris is the capital of France.")
    assert answers_equivalent("Hello there.", "  hello   there. ")
    assert not answers_equivalent("A", "B")


def test_materially_different_detects_change():
    assert materially_different("It is 18 degrees.", "It is 11 degrees.")
    assert not materially_different("Hello sir.", "hello sir.")
    assert not materially_different("Long answer about ports.", "Long answer about ports.")


def test_build_verification_messages_contains_prompt_and_answer():
    messages = build_verification_messages("What is 2+2?", "Four.")
    assert messages[0].role == "system"
    assert "VERIFIED_OK" in messages[0].content
    assert "What is 2+2?" in messages[1].content
    assert "Four." in messages[1].content


def test_background_verify_disabled_via_env(monkeypatch):
    monkeypatch.setenv("JARVIS_BACKGROUND_VERIFY", "0")
    assert background_verify_enabled() is False


@pytest.mark.asyncio
async def test_execute_background_verification_silent_on_verified_ok():
    calls: list[list] = []

    class VerifyProvider:
        async def chat(self, messages, **kwargs):
            calls.append(messages)
            from app.providers.base import ChatResult

            return ChatResult(content=VERIFIED_OK_TOKEN)

    MANAGER.provider = VerifyProvider()
    MANAGER.state.loaded = True

    outcome = await execute_background_verification(
        user_prompt="Capital of France?",
        answer="Paris.",
        source="owner_chat",
        conversation_id="cid-1",
    )
    assert outcome.get("verified_ok") is True
    assert len(calls) == 1
    assert pending_chat_tts() == []


@pytest.mark.asyncio
async def test_execute_background_verification_publishes_correction():
    class VerifyProvider:
        async def chat(self, messages, **kwargs):
            del messages, kwargs
            from app.providers.base import ChatResult

            return ChatResult(content="Lyon.")

    MANAGER.provider = VerifyProvider()
    MANAGER.state.loaded = True

    outcome = await execute_background_verification(
        user_prompt="Capital of France?",
        answer="Paris.",
        source="owner_chat",
        conversation_id="cid-2",
    )
    assert outcome.get("corrected") is True
    assert outcome.get("text") == "Lyon."
    history = get_conversation("cid-2")
    assert len(history) == 1
    assert history[0].content.startswith(FOLLOWUP_PREFIX)
    assert "Lyon." in history[0].content
    tts_items = pending_chat_tts()
    assert tts_items
    assert any(FOLLOWUP_PREFIX in item["text"] for item in tts_items)


@pytest.mark.asyncio
async def test_schedule_background_verification_runs_task():
    seen: dict[str, str] = {}

    class VerifyProvider:
        async def chat(self, messages, **kwargs):
            del kwargs
            seen["user"] = messages[-1].content
            from app.providers.base import ChatResult

            return ChatResult(content=VERIFIED_OK_TOKEN)

    MANAGER.provider = VerifyProvider()
    MANAGER.state.loaded = True

    schedule_background_verification(
        "Hi",
        "Hello.",
        source="owner_chat",
        conversation_id="cid-async",
    )
    await asyncio.sleep(0.05)
    assert "Hello." in seen.get("user", "")


def test_append_owner_assistant_message():
    append_owner_assistant_message("cid-x", "Follow-up line.")
    assert get_conversation("cid-x")[0].content == "Follow-up line."


@pytest.mark.asyncio
async def test_execute_background_verification_task_chat_correction(jarvis_env):
    task_id = "task-bg-verify-correction"
    prompt = "Capital of France?"
    async with SessionLocal() as session:
        session.add(
            Task(
                id=task_id,
                title=prompt,
                prompt=prompt,
                status="completed",
                stage="chat",
                result="Paris.",
                conversation_json='[{"role":"user","content":"Capital of France?"},{"role":"assistant","content":"Paris."}]',
            )
        )
        await session.commit()

    class VerifyProvider:
        async def chat(self, messages, **kwargs):
            del messages, kwargs
            from app.providers.base import ChatResult

            return ChatResult(content="Lyon is the correct answer for your question.")

    MANAGER.provider = VerifyProvider()
    MANAGER.state.loaded = True

    outcome = await execute_background_verification(
        user_prompt=prompt,
        answer="Paris.",
        source="task_chat",
        task_id=task_id,
    )
    assert outcome.get("corrected") is True
    assert outcome.get("text")

    async with SessionLocal() as session:
        row = await session.get(Task, task_id)
        assert row is not None
        messages = deserialize_messages(row.conversation_json or "[]")
        assert messages[-1].role == "assistant"
        assert messages[-1].content.startswith(FOLLOWUP_PREFIX)
        assert (row.result or "").startswith(FOLLOWUP_PREFIX)

    tts_items = pending_chat_tts()
    assert any(item.get("source") == "task_chat" and FOLLOWUP_PREFIX in item["text"] for item in tts_items)


@pytest.mark.asyncio
async def test_schedule_background_verification_does_not_block_owner_publish(jarvis_env, monkeypatch):
    """Initial owner answer is delivered before slow background verify finishes."""
    monkeypatch.setenv("JARVIS_BACKGROUND_VERIFY", "1")
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])

    verify_started = asyncio.Event()
    verify_finished = asyncio.Event()

    async def slow_verify(**kwargs):
        verify_started.set()
        await asyncio.sleep(0.12)
        verify_finished.set()
        return {"verified_ok": True}

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "Four."

    MANAGER.provider = StreamProvider()
    MANAGER.state.loaded = True

    monkeypatch.setattr("app.agent.background_verify.execute_background_verification", slow_verify)

    done_seen = False
    done_event: dict | None = None
    async for event in stream_owner_chat("What is 2+2?"):
        if event.get("type") == "done":
            done_seen = True
            done_event = event
            break

    assert done_seen
    assert done_event is not None and done_event.get("background_verify") is True
    assert not verify_finished.is_set()
    await asyncio.wait_for(verify_started.wait(), timeout=0.5)
    await asyncio.wait_for(verify_finished.wait(), timeout=1.0)
