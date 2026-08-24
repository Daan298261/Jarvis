from app.agent.loop import AGENT
from app.providers.base import ChatResult
from tests.test_verification_loop import ScriptedProvider, _finished, _tool


async def test_balanced_profile_thinks_on_plan_not_on_simple_read(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "note.txt"
    target.write_text("hello", encoding="utf-8")
    provider = ScriptedProvider(
        [
            ChatResult(
                content=(
                    "END STATE: note.txt was read\n"
                    "ACCEPTANCE CRITERIA:\n- file contents known\n"
                    "PLAN:\n1. read the file"
                )
            ),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c1")]),
            ChatResult(content="Read complete."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified note.txt contains hello."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Read {target} and confirm it contains hello.",
        autonomy="autonomous",
        profile="balanced",
        execution_mode="balanced",
    )
    task = await _finished(created.id)
    assert task.status == "completed"
    flags = [call["kwargs"].get("thinking") for call in provider.calls]
    assert flags[0] is True
    # After the first filesystem.read, the next act/verify turn should skip thinking.
    assert False in flags[1:]
