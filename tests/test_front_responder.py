from __future__ import annotations

import json

import pytest

from app.agent.chat_turns import visible_chat_turns
from app.agent.compaction import serialize_messages
from app.agent.front_responder import (
    FRONT_ACTIONS,
    FRONT_MAX_TOKENS_MAX,
    FRONT_MAX_TOKENS_MIN,
    RUNTIME_ROLE,
    SAFE_ACK,
    classify_front_action,
    clamp_front_max_tokens,
    enforce_front_safety,
    front_lane_config,
    generate_front_reply,
    is_safe_front_speech,
    is_unsafe_front_claim,
    last_front_timing,
    merge_consecutive_assistant_turns,
    merge_front_and_worker,
    parse_front_payload,
    record_front_timing,
    reset_front_responder,
    resolve_front_model_id,
    run_two_lane_chat,
    small_context_envelope,
    worker_required,
)
from app.agent.loop import AGENT
from app.agent.planning import MANAGED_TASK, route_request
from app.config import AppSettings, FrontResponderSettings
from app.diagnostics import build_diagnostics
from app.inference.manager import MANAGER
from app.inference.model_stack import normalize_role
from app.providers.base import ChatMessage, ChatResult


@pytest.fixture(autouse=True)
def _reset_front():
    reset_front_responder()
    yield
    reset_front_responder()


def test_front_lane_config_disables_tools_and_thinking():
    cfg = front_lane_config(AppSettings())
    payload = cfg.as_dict()
    assert payload["runtime_role"] == RUNTIME_ROLE
    assert payload["tools_enabled"] is False
    assert payload["tools"] is None
    assert payload["thinking"] is False
    assert FRONT_MAX_TOKENS_MIN <= payload["max_tokens"] <= FRONT_MAX_TOKENS_MAX
    assert payload["answer_tier"] == 1


def test_front_model_setting_is_configurable_not_vendor_hardcoded():
    settings = AppSettings(front_responder=FrontResponderSettings(model=""))
    assert settings.front_responder.model == ""
    settings.front_responder.model = "local-front-chat"
    assert resolve_front_model_id(settings) == "local-front-chat"
    assert "qwen" not in settings.front_responder.model.lower()
    assert normalize_role("front_responder") == "front-responder"


def test_classify_front_actions():
    assert classify_front_action("Hello there") == "final_basic"
    assert classify_front_action("How are you this evening?") == "final_basic"
    assert classify_front_action("Tell me a quick hello.") == "final_basic"
    assert classify_front_action("do it") == "ask_clarification"
    assert classify_front_action("what is the weather in dinteloord, tomorrow") == "ack_continue"
    assert classify_front_action("Organize these files on my desktop and delete duplicates") == "ack_continue"
    assert classify_front_action("Refactor this architecture and run pytest in the repository") == "handoff_notice"
    assert classify_front_action("") == "silent_skip"


def test_parse_front_payload_json_and_plain_text():
    action, text = parse_front_payload(
        json.dumps({"front_action": "final_basic", "text": "Hi, sir."}),
        fallback_action="ack_continue",
    )
    assert action == "final_basic"
    assert text == "Hi, sir."
    action, text = parse_front_payload("On it.", fallback_action="ack_continue")
    assert action == "ack_continue"
    assert text == "On it."


def test_safety_rejects_fake_done_and_invented_facts():
    assert is_unsafe_front_claim("Done, I fixed it.")
    assert is_unsafe_front_claim("I've completed the patch.")
    assert is_unsafe_front_claim("The repo has 47 failing tests.")
    assert not is_unsafe_front_claim(SAFE_ACK)
    assert not is_safe_front_speech("ack_continue", "Done, I fixed it.")
    action, text, rejected = enforce_front_safety(
        "final_basic",
        "Done, I fixed it.",
        user_text="Refactor the repository",
        heuristic="handoff_notice",
    )
    assert rejected is True
    assert action == "handoff_notice"
    assert "fixed" not in text.lower()
    assert action in FRONT_ACTIONS


def test_merge_front_and_worker_is_one_turn():
    merged = merge_front_and_worker(
        "On it. I'll check the details.",
        "Mild rain later, sir.",
        "ack_continue",
    )
    assert merged.startswith("On it.")
    assert "Deeper result" in merged
    assert "Mild rain later, sir." in merged
    assert merge_front_and_worker("Hi, sir.", "", "final_basic") == "Hi, sir."
    turns = merge_consecutive_assistant_turns(
        [
            {"role": "user", "content": "Check the weather"},
            {"role": "assistant", "content": "On it."},
            {"role": "assistant", "content": "Mild rain later, sir."},
        ]
    )
    assert [item["role"] for item in turns] == ["user", "assistant"]
    assert "On it." in turns[-1]["content"]
    assert "Mild rain later" in turns[-1]["content"]


def test_visible_chat_turns_merge_duplicate_assistant_cards():
    raw = serialize_messages(
        [
            ChatMessage(role="user", content="Check the weather"),
            ChatMessage(role="assistant", content="On it. I'll check the details."),
            ChatMessage(role="assistant", content="Mild rain later, sir."),
        ]
    )
    turns = visible_chat_turns("Check the weather", raw, "Mild rain later, sir.")
    assistants = [item for item in turns if item["role"] == "assistant"]
    assert len(assistants) == 1


def test_small_envelope_keeps_short_history():
    history = [
        ChatMessage(role="user", content="Hi"),
        ChatMessage(role="assistant", content="Hello."),
        ChatMessage(role="user", content="Later"),
        ChatMessage(role="assistant", content="Yes."),
        ChatMessage(role="user", content="Again"),
        ChatMessage(role="assistant", content="Still here."),
    ]
    messages = small_context_envelope("Hello", history, action_hint="final_basic", context_turns=2)
    assert messages[0].content.startswith("You are Jarvis")
    assert "front_responder" in messages[0].content
    user_assistant = [item for item in messages if item.role in {"user", "assistant"}]
    assert len(user_assistant) <= 5
    assert user_assistant[-1].content == "Hello"


@pytest.mark.asyncio
async def test_generate_front_reply_final_basic_no_tools_no_thinking():
    seen: list[dict] = []

    class Provider:
        async def chat_stream(self, messages, **kwargs):
            seen.append({"messages": messages, **kwargs})
            assert kwargs.get("tools") is None
            assert kwargs["thinking"] is False
            assert FRONT_MAX_TOKENS_MIN <= kwargs["max_tokens"] <= FRONT_MAX_TOKENS_MAX
            yield "Hi, sir."

    MANAGER.provider = Provider()
    reply = await generate_front_reply("Hello there", settings=AppSettings())
    assert reply.action == "final_basic"
    assert reply.text == "Hi, sir."
    assert reply.thinking is False
    assert reply.tools_enabled is False
    assert worker_required(reply.action) is False
    assert seen and "tools" not in seen[0]


@pytest.mark.asyncio
async def test_generate_front_reply_ack_continue_and_clarification():
    class AckProvider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield json.dumps({"front_action": "ack_continue", "text": "On it. I'll check the details."})

    MANAGER.provider = AckProvider()
    reply = await generate_front_reply(
        "what is the weather in dinteloord, tomorrow",
        settings=AppSettings(),
    )
    assert reply.action == "ack_continue"
    assert "done" not in reply.text.lower()
    assert worker_required(reply.action) is True

    class ClarifyProvider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "What should I take over, sir?"

    MANAGER.provider = ClarifyProvider()
    clarify = await generate_front_reply("do it", settings=AppSettings())
    assert clarify.action == "ask_clarification"
    assert worker_required(clarify.action) is False


@pytest.mark.asyncio
async def test_two_lane_skips_worker_for_final_basic(jarvis_env):
    calls: list[str] = []

    class Provider:
        async def chat_stream(self, messages, **kwargs):
            calls.append("front" if kwargs.get("max_tokens", 999) <= FRONT_MAX_TOKENS_MAX else "worker")
            joined = "\n".join(item.content or "" for item in messages)
            assert "Do not call tools" in joined or "cannot use tools" in joined.lower() or "front_responder" in joined
            yield "Quite well, sir."

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            raise AssertionError("front lane must not use the tool chat() path")

    MANAGER.provider = Provider()
    MANAGER.state.loaded = True
    events = []
    async for event in run_two_lane_chat(
        "How are you this evening?",
        settings=AppSettings(),
        worker_stream=lambda: Provider().chat_stream([], max_tokens=512, thinking=False),
    ):
        events.append(event)
    done = events[-1]
    assert done["type"] == "done"
    assert done["front_action"] == "final_basic"
    assert done["text"] == "Quite well, sir."
    assert calls == ["front"]


@pytest.mark.asyncio
async def test_two_lane_runs_worker_for_ack_continue(jarvis_env):
    calls: list[str] = []

    class Provider:
        async def chat_stream(self, messages, **kwargs):
            calls.append("front" if kwargs.get("max_tokens", 999) <= FRONT_MAX_TOKENS_MAX else "worker")
            if kwargs.get("max_tokens", 999) <= FRONT_MAX_TOKENS_MAX:
                yield "On it. I'll check the details."
                return
            yield "Mild rain later, sir."

    MANAGER.provider = Provider()

    async def worker():
        async for delta in Provider().chat_stream([], max_tokens=512, thinking=False):
            yield delta

    events = []
    async for event in run_two_lane_chat(
        "what is the weather in dinteloord, tomorrow",
        settings=AppSettings(),
        worker_stream=worker,
    ):
        events.append(event)
    kinds = [item.get("type") for item in events]
    assert "front_response_completed" in kinds
    assert "worker_response_started" in kinds
    assert "worker_response_completed" in kinds
    done = events[-1]
    assert done["front_action"] == "ack_continue"
    assert "On it." in done["text"]
    assert "Mild rain later" in done["text"]
    assert "Deeper result" in done["text"]


@pytest.mark.asyncio
async def test_conversation_task_uses_front_lane_and_one_assistant(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    seen_tokens: list[int] = []

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            seen_tokens.append(int(kwargs["max_tokens"]))
            assert kwargs["thinking"] is False
            assert kwargs.get("tools") in (None, [], False) or "tools" not in kwargs
            yield "All well here."

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            return ChatResult(content="unexpected")

    MANAGER.provider = StreamProvider()
    MANAGER.state.loaded = True
    MANAGER.state.context_size = 16384

    task = await AGENT.create_task("How are you this evening?")
    runner = AGENT._tasks.get(task.id)
    if runner:
        await runner

    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.db.models import Task, TaskEvent

    async with SessionLocal() as session:
        row = await session.get(Task, task.id)
        assert row is not None
        assert row.status == "completed"
        assert "well" in (row.result or "").lower()
        turns = visible_chat_turns(row.prompt, row.conversation_json, row.result or "")
        assert [item["role"] for item in turns if item["role"] == "assistant"] == ["assistant"]
        events = (
            await session.execute(select(TaskEvent).where(TaskEvent.task_id == task.id))
        ).scalars().all()
        kinds = {item.kind for item in events}
        assert "front_response_completed" in kinds or "front_response_skipped" in kinds
        assert any(item.kind == "response_timing" and "First word" in item.detail for item in events)
    assert seen_tokens
    assert all(token <= 512 for token in seen_tokens)
    assert any(token <= FRONT_MAX_TOKENS_MAX for token in seen_tokens)


def test_diagnostics_include_front_timing():
    record_front_timing(
        {
            "front_model": "local-front-chat",
            "front_action": "ack_continue",
            "front_first_text_ms": 640,
            "front_first_audio_ms": 1180,
            "queue_ms": 20,
            "router_ms": 5,
            "worker_first_text_ms": 5600,
            "worker_complete_ms": 12400,
            "tts_first_audio_ms": 1180,
        }
    )
    payload = build_diagnostics()
    front = payload["front_responder"]
    assert front["enabled"] is True
    assert front["last_turn"]["front_action"] == "ack_continue"
    assert front["last_turn"]["front_first_text_ms"] == 640
    assert last_front_timing()["front_model"] == "local-front-chat"


def test_clamp_front_max_tokens():
    assert clamp_front_max_tokens(12) == FRONT_MAX_TOKENS_MIN
    assert clamp_front_max_tokens(999) == FRONT_MAX_TOKENS_MAX
    assert clamp_front_max_tokens(128) == 128


def test_managed_route_is_not_final_authority():
    route = route_request("Refactor this repository and run pytest")
    assert route.kind == MANAGED_TASK
    action, text, rejected = enforce_front_safety(
        "final_basic",
        "All done, the tests pass.",
        user_text="Refactor this repository and run pytest",
        heuristic=classify_front_action("Refactor this repository and run pytest"),
    )
    assert rejected is True
    assert action != "final_basic"
    assert "pass" not in text.lower() or action == "handoff_notice"
