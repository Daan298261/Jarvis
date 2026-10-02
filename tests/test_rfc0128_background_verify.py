from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.agent.background_verify import (
    FOLLOWUP_PREFIX,
    VERIFIED_OK_TOKEN,
    VerificationUnavailable,
    answers_equivalent,
    background_verify_enabled,
    background_verify_stats,
    build_verification_messages,
    decide_verification_admission,
    execute_background_verification,
    is_verified_ok,
    materially_different,
    record_verified_correction,
    reset_background_verify_state,
    run_verification_model_call,
    schedule_background_verification,
    verification_applicable,
)
from app.agent.compaction import deserialize_messages
from app.agent.planning import DIRECT_LOOKUP, DIRECT_REPLY, MANAGED_TASK
from app.agent.task_fastpath import should_skip_background_verify
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
def _reset_state(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent.background_verify.data_dir", lambda: Path(tmp_path))
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
    assert not is_verified_ok("")
    assert not is_verified_ok("   ")
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


def test_policy_skips_greeting_and_direct_routes():
    assert decide_verification_admission(
        user_prompt="Hi",
        answer="Hello there.",
    ).admitted is False
    assert decide_verification_admission(
        user_prompt="thanks",
        answer="You're welcome.",
    ).reason == "greeting"
    assert decide_verification_admission(
        user_prompt="Please research trade-offs of SQLite vs Postgres for local agents.",
        answer="x" * 40,
        route_kind=DIRECT_REPLY,
    ).reason == "direct_route"
    assert decide_verification_admission(
        user_prompt="Weather today?",
        answer="Sunny.",
        route_kind=DIRECT_LOOKUP,
    ).admitted is False
    assert verification_applicable(user_prompt="Hi", answer="Hello.") is False


def test_policy_admits_research_coding_planning_and_managed():
    research = decide_verification_admission(
        user_prompt="Please research and compare product options for local vector DBs.",
        answer="Here is a comparison of three options with trade-offs.",
        route_kind=MANAGED_TASK,
        task_class="research",
    )
    assert research.admitted is True

    coding = decide_verification_admission(
        user_prompt="Refactor the auth module and fix the failing pytest suite.",
        answer="I would start by isolating the token refresh path.",
        task_class="software engineering",
    )
    assert coding.admitted is True

    planning = decide_verification_admission(
        user_prompt="Draft a planning roadmap with acceptance criteria for the quality loop.",
        answer="Phase 1 covers verifier admission; phase 2 covers correction provenance.",
    )
    assert planning.admitted is True
    assert planning.reason in {"consequential", "managed_task", "substantial_answer"} or planning.reason.startswith(
        "task_class:"
    )


def test_fastpath_direct_routes_still_skip_background_verify():
    assert should_skip_background_verify(DIRECT_REPLY) is True
    assert should_skip_background_verify(DIRECT_LOOKUP) is True
    assert should_skip_background_verify(MANAGED_TASK) is False
    # Admission aligns with the fastpath contract for direct lanes.
    assert (
        decide_verification_admission(
            user_prompt="Hello",
            answer="Hi there, how can I help?",
            route_kind=DIRECT_REPLY,
        ).admitted
        is False
    )


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
        user_prompt="Please research the capital of France with sources.",
        answer="Paris is the capital, based on standard geographic references.",
        source="owner_chat",
        conversation_id="cid-1",
        route_kind=MANAGED_TASK,
        task_class="research",
    )
    assert outcome.get("verified_ok") is True
    assert len(calls) == 1
    assert pending_chat_tts() == []
    assert background_verify_stats()["hit"] >= 1
    assert background_verify_stats()["verified_ok"] >= 1


@pytest.mark.asyncio
async def test_execute_background_verification_publishes_correction(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent.background_verify.data_dir", lambda: Path(tmp_path))

    class VerifyProvider:
        async def chat(self, messages, **kwargs):
            del messages, kwargs
            from app.providers.base import ChatResult

            return ChatResult(content="Lyon.")

    MANAGER.provider = VerifyProvider()
    MANAGER.state.loaded = True

    outcome = await execute_background_verification(
        user_prompt="Please research which city is the capital of France.",
        answer="Paris is listed as the capital in most references.",
        source="owner_chat",
        conversation_id="cid-2",
        route_kind=MANAGED_TASK,
        task_class="research",
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

    correction_meta = outcome.get("correction_record") or {}
    assert correction_meta.get("ok") is True
    record = correction_meta["record"]
    assert record["before"].startswith("Paris")
    assert record["after"] == "Lyon."
    assert record["owner_scope"] == "owner"
    assert record["provenance"]["source_type"] == "background_verify"
    path = Path(correction_meta["path"])
    assert path.is_file()
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[-1]["id"] == record["id"]
    assert background_verify_stats()["correct"] >= 1


@pytest.mark.asyncio
async def test_fail_closed_when_model_unloaded():
    MANAGER.provider = None
    MANAGER.state.loaded = False

    with pytest.raises(VerificationUnavailable):
        await run_verification_model_call("research this", "draft")

    outcome = await execute_background_verification(
        user_prompt="Please research and summarize local agent architectures.",
        answer="A common pattern is planner plus verifier with independent context.",
        source="owner_chat",
        conversation_id="cid-unload",
        route_kind=MANAGED_TASK,
        task_class="research",
    )
    assert outcome.get("fail_closed") is True
    assert outcome.get("error") == "model_unloaded"
    assert outcome.get("verified_ok") is not True
    assert outcome.get("corrected") is not True
    assert background_verify_stats()["error"] >= 1


@pytest.mark.asyncio
async def test_fail_closed_on_empty_verifier_output():
    class EmptyProvider:
        async def chat(self, messages, **kwargs):
            del messages, kwargs
            from app.providers.base import ChatResult

            return ChatResult(content="   ")

    MANAGER.provider = EmptyProvider()
    MANAGER.state.loaded = True

    outcome = await execute_background_verification(
        user_prompt="Analyze and plan a quality-loop verifier admission policy.",
        answer="Admit research and coding; skip greetings and direct routes.",
        source="owner_chat",
        conversation_id="cid-empty",
        route_kind=MANAGED_TASK,
        task_class="research",
    )
    assert outcome.get("fail_closed") is True
    assert outcome.get("error") == "empty_verifier_output"
    assert get_conversation("cid-empty") == []
    assert pending_chat_tts() == []


@pytest.mark.asyncio
async def test_unhelpful_verifier_noise_is_counted():
    class NoiseProvider:
        async def chat(self, messages, **kwargs):
            del messages, kwargs
            from app.providers.base import ChatResult

            # Near-duplicate / non-material — should not invent a correction.
            return ChatResult(content="Admit research and coding; skip greetings and direct routes.")

    MANAGER.provider = NoiseProvider()
    MANAGER.state.loaded = True

    answer = "Admit research and coding; skip greetings and direct routes."
    outcome = await execute_background_verification(
        user_prompt="Analyze and plan a quality-loop verifier admission policy.",
        answer=answer,
        source="owner_chat",
        conversation_id="cid-noise",
        route_kind=MANAGED_TASK,
        task_class="research",
    )
    assert outcome.get("verified_ok") is True
    assert outcome.get("unhelpful") is True
    assert background_verify_stats()["unhelpful"] >= 1
    assert get_conversation("cid-noise") == []


@pytest.mark.asyncio
async def test_schedule_skips_greeting_without_model_call():
    calls: list[object] = []

    class VerifyProvider:
        async def chat(self, messages, **kwargs):
            calls.append(messages)
            from app.providers.base import ChatResult

            return ChatResult(content=VERIFIED_OK_TOKEN)

    MANAGER.provider = VerifyProvider()
    MANAGER.state.loaded = True

    scheduled = schedule_background_verification(
        "Hi",
        "Hello.",
        source="owner_chat",
        conversation_id="cid-async-skip",
        route_kind=DIRECT_REPLY,
    )
    assert scheduled is False
    await asyncio.sleep(0.05)
    assert calls == []
    assert background_verify_stats()["skip"] >= 1


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

    scheduled = schedule_background_verification(
        "Please research local GGUF serving trade-offs for a 27B model.",
        "Q4_K_M is a common balance of quality and VRAM for a 27B GGUF on a single GPU.",
        source="owner_chat",
        conversation_id="cid-async",
        route_kind=MANAGED_TASK,
        task_class="research",
    )
    assert scheduled is True
    await asyncio.sleep(0.05)
    assert "27B" in seen.get("user", "")


def test_append_owner_assistant_message():
    append_owner_assistant_message("cid-x", "Follow-up line.")
    assert get_conversation("cid-x")[0].content == "Follow-up line."


def test_record_verified_correction_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent.background_verify.data_dir", lambda: Path(tmp_path))
    result = record_verified_correction(
        user_prompt="Research X",
        initial_answer="Wrong",
        correction="Right",
        conversation_id="cid-prov",
        source="owner_chat",
        route_kind=MANAGED_TASK,
        task_class="research",
    )
    assert result["ok"] is True
    record = result["record"]
    assert record["before"] == "Wrong"
    assert record["after"] == "Right"
    assert record["provenance"]["owner_scope"] == "owner"
    assert "never auto-rewrites" in record["provenance"]["note"]


@pytest.mark.asyncio
async def test_execute_background_verification_task_chat_correction(jarvis_env, tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent.background_verify.data_dir", lambda: Path(tmp_path))
    task_id = "task-bg-verify-correction"
    prompt = "Please research the capital of France carefully."
    async with SessionLocal() as session:
        session.add(
            Task(
                id=task_id,
                title=prompt,
                prompt=prompt,
                status="completed",
                stage="chat",
                result="Paris.",
                conversation_json='[{"role":"user","content":"Please research the capital of France carefully."},{"role":"assistant","content":"Paris."}]',
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
        route_kind=MANAGED_TASK,
        task_class="research",
    )
    assert outcome.get("corrected") is True
    assert outcome.get("text")
    assert (outcome.get("correction_record") or {}).get("ok") is True

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
            yield "Q4_K_M balances quality and VRAM for local 27B GGUF serving."

    MANAGER.provider = StreamProvider()
    MANAGER.state.loaded = True

    monkeypatch.setattr("app.agent.background_verify.execute_background_verification", slow_verify)

    from app.agent.background_verify import VerificationAdmission

    monkeypatch.setattr(
        "app.agent.background_verify.decide_verification_admission",
        lambda **kwargs: VerificationAdmission(True, "test_force"),
    )

    done_seen = False
    done_event: dict | None = None
    async for event in stream_owner_chat(
        "Please research local GGUF serving trade-offs for a 27B model."
    ):
        if event.get("type") == "done":
            done_seen = True
            done_event = event
            break

    assert done_seen
    assert done_event is not None and done_event.get("background_verify") is True
    assert not verify_finished.is_set()
    await asyncio.wait_for(verify_started.wait(), timeout=0.5)
    await asyncio.wait_for(verify_finished.wait(), timeout=1.0)
