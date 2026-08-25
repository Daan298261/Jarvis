from app.tools.exposure import ToolExposure, tools_for_task
from app.tools.registry import REGISTRY


def test_filesystem_task_does_not_include_office_or_docker():
    names = tools_for_task("filesystem")
    assert "filesystem" in names
    assert "request_capability" in names
    assert "office" not in names
    assert "docker" not in names
    assert "browser" not in names


def test_software_engineering_includes_git_not_office():
    names = tools_for_task("software engineering")
    assert {"filesystem", "terminal", "python", "git", "request_capability"} <= names
    assert "office" not in names
    assert "desktop" not in names


def test_request_capability_grants_browser_and_web_fetch():
    exposure = ToolExposure("filesystem")
    assert "browser" not in exposure.names()
    ok, message, added = exposure.grant("browser")
    assert ok
    assert "browser" in added
    assert "browser" in exposure.names()
    assert "web_fetch" in exposure.names()
    assert "already" in exposure.grant("browser")[1]


def test_unknown_capability_is_rejected():
    exposure = ToolExposure("mixed")
    ok, message, added = exposure.grant("telepathy")
    assert ok is False
    assert added == []
    assert "Unknown capability" in message


def test_optional_workers_can_be_granted_by_name_and_alias():
    exposure = ToolExposure("filesystem")
    for requested, canonical in (
        ("browser_use", "browser_use"),
        ("openhands", "code_worker"),
        ("interpreter", "open_interpreter"),
        ("ufo", "ufo"),
        ("cua", "cua"),
    ):
        ok, message, added = exposure.grant(requested)
        assert ok, message
        assert canonical in added
        assert canonical in exposure.names()


async def test_agent_sends_only_exposed_tools(jarvis_env):
    from app.agent.loop import AGENT
    from app.providers.base import ChatResult

    class Recorder:
        def __init__(self):
            self.tool_sets = []

        async def health(self):
            return True

        async def chat(self, messages, tools=None, **kwargs):
            self.tool_sets.append([item["function"]["name"] for item in (tools or [])])
            if len(self.tool_sets) == 1:
                return ChatResult(
                    content="END STATE: note.txt exists\nACCEPTANCE CRITERIA:\n- file exists\nPLAN:\n1. write the file"
                )
            target = jarvis_env["tmp"] / "note.txt"
            if len(self.tool_sets) == 2:
                return ChatResult(
                    tool_calls=[
                        {
                            "id": "w1",
                            "type": "function",
                            "function": {
                                "name": "filesystem",
                                "arguments": f'{{"action":"write","path":"{target}","content":"READY","create_backup":false}}',
                            },
                        }
                    ]
                )
            if len(self.tool_sets) == 3:
                return ChatResult(
                    tool_calls=[
                        {
                            "id": "r1",
                            "type": "function",
                            "function": {
                                "name": "filesystem",
                                "arguments": f'{{"action":"read","path":"{target}"}}',
                            },
                        }
                    ]
                )
            return ChatResult(content="Verified note.txt contains READY.")

    provider = Recorder()
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Organize a file named note.txt in {jarvis_env['tmp']} that contains READY.",
        autonomy="autonomous",
        profile="fast",
    )
    await AGENT._tasks[created.id]
    assert provider.tool_sets
    first = set(provider.tool_sets[0])
    assert "filesystem" in first
    assert "request_capability" in first
    assert "office" not in first
    assert "docker" not in first
    assert (jarvis_env["tmp"] / "note.txt").read_text(encoding="utf-8") == "READY"


async def test_request_capability_tool_expands_registry_exposure(jarvis_env):
    from app.tools.exposure import ToolExposure

    exposure = ToolExposure("filesystem")
    REGISTRY.bind_exposure(exposure)
    result = await REGISTRY.execute("request_capability", {"action": "request", "name": "git"})
    assert result.success
    assert "git" in exposure.names()
    listed = await REGISTRY.execute("request_capability", {"action": "list", "task_class": "filesystem"})
    assert listed.success
    assert "filesystem" in listed.output
