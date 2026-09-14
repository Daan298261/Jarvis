from app.agent.chat_turns import visible_chat_turns
from app.agent.compaction import serialize_messages
from app.inference.lmstudio_server import ensure_local_lmstudio, is_loopback_host
from app.providers.base import ChatMessage


def test_visible_turns_split_follow_up_blob():
    turns = visible_chat_turns(
        "How are you this evening?\n\nFollow-up: And the weather?",
        "[]",
        "Mild rain later, sir.",
    )
    assert [item["role"] for item in turns] == ["user", "user", "assistant"]
    assert turns[0]["content"] == "How are you this evening?"
    assert turns[1]["content"] == "And the weather?"
    assert "Follow-up:" not in turns[1]["content"]


def test_visible_turns_prefer_conversation_json():
    raw = serialize_messages(
        [
            ChatMessage(role="system", content="You are Jarvis."),
            ChatMessage(role="user", content="How are you this evening?"),
            ChatMessage(role="assistant", content="Quite well, sir."),
            ChatMessage(role="user", content="And the weather?"),
        ]
    )
    turns = visible_chat_turns(
        "How are you this evening?\n\nFollow-up: And the weather?",
        raw,
        "Quite well, sir.",
    )
    assert [item["content"] for item in turns] == [
        "How are you this evening?",
        "Quite well, sir.",
        "And the weather?",
    ]


def test_visible_turns_seed_from_prompt_when_history_empty():
    turns = visible_chat_turns(
        "How are you this evening?",
        "[]",
        "Quite well, sir.",
    )
    assert [item["content"] for item in turns] == [
        "How are you this evening?",
        "Quite well, sir.",
    ]


def test_visible_turns_hide_continue_boilerplate():
    raw = serialize_messages(
        [
            ChatMessage(role="user", content="How are you this evening?"),
            ChatMessage(role="assistant", content="Quite well, sir."),
            ChatMessage(
                role="user",
                content="Continue the existing task. Recover from saved state.\n\nAnd the weather?",
            ),
        ]
    )
    turns = visible_chat_turns("How are you this evening?\n\nFollow-up: And the weather?", raw)
    assert [item["content"] for item in turns] == [
        "How are you this evening?",
        "Quite well, sir.",
        "And the weather?",
    ]


def test_remote_lmstudio_is_not_autostarted():
    assert is_loopback_host("127.0.0.1")
    assert not is_loopback_host("192.168.1.50")


async def test_ensure_skips_remote_hosts():
    result = await ensure_local_lmstudio(host="192.168.1.50", port=1234)
    assert result["ok"] is False
    assert result["method"] == "skipped"
