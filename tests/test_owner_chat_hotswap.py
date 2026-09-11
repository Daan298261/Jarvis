from __future__ import annotations

import pytest

from app.inference.manager import MANAGER
from app.persona.owner_chat import (
    complete_owner_chat,
    conversation_ids,
    get_conversation,
    rebind_owner_conversations_after_hotswap,
    reset_owner_conversations,
)
from app.providers.base import ChatMessage


@pytest.fixture(autouse=True)
def clean_conversations():
    reset_owner_conversations()
    yield
    reset_owner_conversations()


class EchoProvider:
    async def chat_stream(self, messages, **kwargs):
        del kwargs
        yield "Acknowledged."

    async def chat(self, messages, **kwargs):
        del messages, kwargs
        from app.providers.base import ChatResult

        return ChatResult(content="Acknowledged.")


@pytest.mark.asyncio
async def test_hotswap_preserves_conversation_id(jarvis_env, monkeypatch):
    del jarvis_env
    MANAGER.provider = EchoProvider()
    MANAGER.state.loaded = True

    first = await complete_owner_chat("Hello there.", conversation_id="cid-keep-me")
    assert first["ok"] is True
    assert first["conversation_id"] == "cid-keep-me"
    assert conversation_ids() == ["cid-keep-me"]

    rebind_owner_conversations_after_hotswap(32768, previous_context_limit=32768)

    second = await complete_owner_chat("Still here?", conversation_id="cid-keep-me")
    assert second["conversation_id"] == "cid-keep-me"
    history = get_conversation("cid-keep-me")
    assert len(history) >= 2
    assert history[0].role == "user"
    assert history[0].content == "Hello there."


def test_rebind_truncates_oldest_turns_when_context_shrinks():
    cid = "truncate-me"
    reset_owner_conversations()
    from app.persona.owner_chat import _conversations

    _conversations[cid] = [
        ChatMessage(role="user", content="A" * 2000),
        ChatMessage(role="assistant", content="reply-a"),
        ChatMessage(role="user", content="B" * 2000),
        ChatMessage(role="assistant", content="reply-b"),
    ]
    rebind_owner_conversations_after_hotswap(4096, previous_context_limit=32768)
    trimmed = get_conversation(cid)
    assert trimmed
    assert trimmed[-1].content == "reply-b"
    assert len(trimmed) < 4
