import json

from app.agent.loop import AGENT
from app.db.models import Task
from app.db.session import SessionLocal
from app.providers.base import ChatResult


def _tool(name: str, arguments: dict, call_id: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class ScriptedProvider:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def health(self):
        return True

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append(messages)
        if not self.turns:
            return ChatResult(content="Final report.")
        return self.turns.pop(0)


async def test_failed_tool_call_gets_alternate_strategy_guidance(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "recovered.txt"
    provider = ScriptedProvider(
        [
            ChatResult(content="END STATE: recovered.txt exists\nACCEPTANCE CRITERIA:\n- file exists\nPLAN:\n1. read a missing file"),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(tmp / "missing.txt")}, "c1")]),
            ChatResult(
                tool_calls=[
                    _tool("filesystem", {"action": "write", "path": str(target), "content": "RECOVERED", "create_backup": False}, "c2")
                ]
            ),
            ChatResult(content="Wrote the file after recovering."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c3")]),
            ChatResult(content="Verified recovered.txt contains RECOVERED."),
        ]
    )
    jarvis_env["manager"].provider = provider

    created = await AGENT.create_task(
        f"Read a file that does not exist, then make {target} say RECOVERED.",
        autonomy="autonomous",
        profile="fast",
    )
    await AGENT._tasks[created.id]

    guidance = [
        message.content
        for call in provider.calls
        for message in call
        if message.role == "user" and isinstance(message.content, str) and "Do not repeat the call that just failed." in message.content
    ]
    assert guidance, "a failed tool call must produce recovery guidance"
    assert "not found" in guidance[0]

    async with SessionLocal() as session:
        task = await session.get(Task, created.id)
    assert task.status == "completed"
    assert target.read_text(encoding="utf-8") == "RECOVERED"
