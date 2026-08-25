from app.agent.loop import AGENT
from app.agent.planning import classify_task
from app.agent.tooling import apply_capability_request, should_enable_thinking, tools_for_task
from app.db.models import Task
from app.db.session import SessionLocal
from app.inference.profiles import PROFILES
from app.providers.base import ChatResult
from app.tools.registry import REGISTRY


def test_filesystem_task_does_not_expose_docker_or_desktop():
    names = tools_for_task("filesystem")
    assert "filesystem" in names
    assert "request_capability" in names
    assert "docker" not in names
    assert "desktop" not in names
    assert "browser" not in names


def test_software_engineering_exposes_git_and_terminal():
    names = tools_for_task("software engineering")
    assert {"filesystem", "terminal", "python", "git", "request_capability"} <= names
    assert "office" not in names


def test_mixed_and_unknown_classes_keep_the_full_set():
    mixed = tools_for_task("mixed")
    unknown = tools_for_task("not-a-real-class")
    assert "docker" in mixed
    assert "desktop" in unknown
    assert classify_task("Organize these files on the desktop") == "filesystem"


def test_request_capability_adds_registered_tools():
    exposed = tools_for_task("filesystem")
    assert "git" not in exposed
    nxt, added, text = apply_capability_request(exposed, {"capabilities": ["git", "nope"]})
    assert "git" in nxt
    assert added == ["git"]
    assert "git" in text
    assert "Unknown" in text
    assert "git" in REGISTRY.tools
    assert "request_capability" in REGISTRY.tools


def test_selective_thinking_only_on_plan_and_recovery():
    balanced = PROFILES["balanced"]
    assert should_enable_thinking(balanced, turn_index=0) is True
    assert should_enable_thinking(balanced, turn_index=2) is False
    assert should_enable_thinking(balanced, turn_index=2, consecutive_failures=1) is True
    assert should_enable_thinking(balanced, turn_index=0, verifying=True) is False
    assert should_enable_thinking(balanced, turn_index=0, force_final=True) is False
    assert should_enable_thinking(PROFILES["fast"], turn_index=0) is False
    assert should_enable_thinking(PROFILES["quality"], turn_index=4) is True
    assert should_enable_thinking(PROFILES["expert"], turn_index=3, verifying=True) is False


def _tool(name: str, arguments: dict, call_id: str) -> dict:
    import json

    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class _CaptureProvider:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def health(self):
        return True

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"tools": tools or [], "thinking": kwargs.get("thinking")})
        if not self.turns:
            return ChatResult(content="Final report.")
        return self.turns.pop(0)


async def test_filesystem_task_sends_subset_and_skips_thinking_after_plan(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "subset.txt"
    provider = _CaptureProvider(
        [
            ChatResult(content="END STATE: subset.txt exists\nACCEPTANCE CRITERIA:\n- file exists\nPLAN:\n1. write"),
            ChatResult(
                tool_calls=[
                    _tool("filesystem", {"action": "write", "path": str(target), "content": "OK", "create_backup": False}, "c1")
                ]
            ),
            ChatResult(content="Wrote it."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified subset.txt contains OK."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        "Organize files into a folder and write the notes file",
        autonomy="autonomous",
        profile="balanced",
    )
    await AGENT._tasks[created.id]
    async with SessionLocal() as session:
        task = await session.get(Task, created.id)
    assert task.status == "completed"
    names_first = {item["function"]["name"] for item in provider.calls[0]["tools"]}
    assert "filesystem" in names_first
    assert "request_capability" in names_first
    assert "docker" not in names_first
    assert "desktop" not in names_first
    assert provider.calls[0]["thinking"] is True
    later = [call["thinking"] for call in provider.calls[1:] if call["thinking"] is not None]
    assert False in later

