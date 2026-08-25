import json

from app.agent.loop import AGENT
from app.providers.base import ChatResult
from app.tools.registry import REGISTRY


def _tool(name: str, arguments: dict, call_id: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class RecordingProvider:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def health(self):
        return True

    async def chat(self, messages, tools=None, **kwargs):
        names = [item["function"]["name"] for item in (tools or [])]
        self.calls.append(names)
        if not self.turns:
            return ChatResult(content="Final report.")
        return self.turns.pop(0)


async def test_filesystem_task_sends_a_filtered_schema(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "organized.txt"
    provider = RecordingProvider(
        [
            ChatResult(content="END STATE: organized.txt exists\nACCEPTANCE CRITERIA:\n- file exists\nPLAN:\n1. write"),
            ChatResult(
                tool_calls=[
                    _tool("filesystem", {"action": "write", "path": str(target), "content": "OK", "create_backup": False}, "c1")
                ]
            ),
            ChatResult(content="Wrote it."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified organized.txt exists."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Organize files in this folder on the desktop. Write {target} containing OK.",
        autonomy="autonomous",
        profile="fast",
    )
    await AGENT._tasks[created.id]
    first = provider.calls[0]
    assert "filesystem" in first
    assert "python" in first
    assert "request_tools" in first
    assert "docker" not in first
    assert "office" not in first
    full = {item["function"]["name"] for item in REGISTRY.openai_tools()}
    assert len(first) < len(full)


async def test_request_tools_expands_the_next_schema(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "after-request.txt"
    provider = RecordingProvider(
        [
            ChatResult(content="END STATE: file exists\nACCEPTANCE CRITERIA:\n- file exists\nPLAN:\n1. request browser then write"),
            ChatResult(tool_calls=[_tool("request_tools", {"capabilities": ["browser"]}, "r1")]),
            ChatResult(
                tool_calls=[
                    _tool("filesystem", {"action": "write", "path": str(target), "content": "OK", "create_backup": False}, "c1")
                ]
            ),
            ChatResult(content="Wrote it."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified after-request.txt exists."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Organize files in this folder on the desktop. Write {target} containing OK.",
        autonomy="autonomous",
        profile="fast",
    )
    await AGENT._tasks[created.id]
    assert "browser" not in provider.calls[0]
    expanded = next((names for names in provider.calls if "browser" in names), None)
    assert expanded, "request_tools should add browser to a later schema"
    assert "filesystem" in expanded
    assert "request_tools" in expanded
