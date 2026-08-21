from app.agent.compaction import (
    SUMMARY_MARKER,
    WORKING_STATE_MARKER,
    compact_history,
    deserialize_messages,
    serialize_messages,
)
from app.agent.planning import WorkingState
from app.providers.base import ChatMessage


def _tool_call(name: str, call_id: str):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": "{}"}}


def _long_history(rounds: int = 12) -> list[ChatMessage]:
    messages = [
        ChatMessage(role="system", content="You are Jarvis."),
        ChatMessage(role="user", content="Do the thing."),
    ]
    for index in range(rounds):
        messages.append(ChatMessage(role="assistant", content="", tool_calls=[_tool_call("filesystem", f"c{index}")]))
        messages.append(ChatMessage(role="tool", name="filesystem", tool_call_id=f"c{index}", content=f"result {index}"))
    return messages


def test_compaction_never_orphans_a_tool_result():
    compacted = compact_history(_long_history(), keep_last=5)
    ids_with_calls = {
        call["id"]
        for message in compacted
        if message.role == "assistant" and message.tool_calls
        for call in message.tool_calls
    }
    for message in compacted:
        if message.role == "tool":
            assert message.tool_call_id in ids_with_calls


def test_compaction_preserves_head_and_summarizes_middle():
    compacted = compact_history(_long_history(), keep_last=4)
    assert compacted[0].role == "system" and compacted[0].content == "You are Jarvis."
    assert compacted[1].role == "user"
    assert any(isinstance(m.content, str) and m.content.startswith(SUMMARY_MARKER) for m in compacted)
    assert len(compacted) < len(_long_history())


def test_working_state_block_is_refreshed_not_stacked():
    state = WorkingState(goal="write report", acceptance_criteria=["file exists"], task_class="filesystem")
    history = _long_history()
    once = compact_history(history, keep_last=4, working_state_block=state.as_prompt_block())
    state.current_state = "wrote the file"
    twice = compact_history(once, keep_last=4, working_state_block=state.as_prompt_block())
    blocks = [m for m in twice if isinstance(m.content, str) and m.content.startswith(WORKING_STATE_MARKER)]
    assert len(blocks) == 1
    assert "wrote the file" in blocks[0].content


def test_short_history_is_untouched():
    messages = _long_history(rounds=1)
    assert compact_history(messages, keep_last=8) == messages


def test_serialization_round_trip():
    messages = _long_history(rounds=2)
    restored = deserialize_messages(serialize_messages(messages))
    assert [m.role for m in restored] == [m.role for m in messages]
    assert restored[-1].tool_call_id == messages[-1].tool_call_id
