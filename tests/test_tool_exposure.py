from app.agent.planning import classify_task
from app.agent.tool_exposure import (
    allowed_tool_names,
    apply_request,
    exposure_prompt_block,
    resolve_requested_names,
    wants_full_access,
)
from app.tools.registry import REGISTRY


def test_filesystem_task_does_not_expose_browser_or_docker():
    allowed = allowed_tool_names("filesystem")
    assert allowed is not None
    assert "filesystem" in allowed
    assert "python" in allowed
    assert "request_tools" in allowed
    assert "browser" not in allowed
    assert "docker" not in allowed
    assert "ufo" not in allowed


def test_software_engineering_exposes_git_not_office():
    allowed = allowed_tool_names("software engineering")
    assert allowed is not None
    assert {"filesystem", "terminal", "python", "git", "docker"} <= allowed
    assert "office" not in allowed
    assert "browser" not in allowed


def test_windows_gui_exposes_computer_use_workers():
    allowed = allowed_tool_names("windows gui")
    assert allowed is not None
    assert {"desktop", "screenshot", "ufo", "cua"} <= allowed


def test_mixed_and_long_horizon_expose_all_tools():
    assert allowed_tool_names("mixed") is None
    assert allowed_tool_names("long-horizon autonomous") is None
    assert wants_full_access("mixed")
    schemas = REGISTRY.openai_tools(allowed_tool_names("mixed"))
    names = {item["function"]["name"] for item in schemas}
    assert "filesystem" in names
    assert "browser" in names
    assert "ufo" in names
    assert "cua" in names
    assert "request_tools" in names


def test_request_tools_category_expands_set():
    extra = apply_request([], ["browser"])
    allowed = allowed_tool_names("filesystem", extra)
    assert allowed is not None
    assert {"browser", "web_fetch", "screenshot"} <= allowed
    assert "filesystem" in allowed


def test_request_all_unlocks_full_schema():
    extra = apply_request([], ["all"])
    assert allowed_tool_names("filesystem", extra) is None
    assert resolve_requested_names(["coding"]) >= {"git", "docker", "python"}


def test_registry_filters_schemas_without_mcp_unless_requested():
    filtered = REGISTRY.openai_tools(allowed_tool_names("filesystem"))
    names = [item["function"]["name"] for item in filtered]
    assert "filesystem" in names
    assert "request_tools" in names
    assert "docker" not in names
    assert "browser" not in names
    assert "mcp_call" not in names
    expanded = REGISTRY.openai_tools(allowed_tool_names("filesystem", ["mcp"]))
    expanded_names = [item["function"]["name"] for item in expanded]
    assert "mcp_call" in expanded_names


def test_classify_then_expose_matches_prompt_examples():
    assert classify_task("Organize these files on the desktop") == "filesystem"
    assert "browser" not in (allowed_tool_names(classify_task("Organize these files on the desktop")) or set())
    assert classify_task("Open the website and save the page title") == "browser automation"
    browser_set = allowed_tool_names(classify_task("Open the website and save the page title"))
    assert browser_set is not None
    assert "browser" in browser_set
    assert "web_fetch" in browser_set


def test_exposure_prompt_mentions_escape_hatch():
    block = exposure_prompt_block("filesystem")
    assert "request_tools" in block
    assert "filesystem" in block
    full = exposure_prompt_block("mixed")
    assert "every enabled tool" in full


async def test_agent_omits_irrelevant_tools_then_honors_request_tools(jarvis_env):
    import json

    from app.agent.loop import AGENT
    from app.providers.base import ChatResult
    from app.tools.request_tools import RequestToolsTool

    added = await RequestToolsTool().execute(names=["browser"])
    assert added.success
    assert "browser" in added.output

    def _tool(name, arguments, call_id):
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }

    class ScriptedProvider:
        name = "scripted"

        def __init__(self, turns):
            self.turns = list(turns)
            self.calls = []

        async def health(self):
            return True

        async def chat(self, messages, tools=None, **kwargs):
            self.calls.append({"tools": tools})
            if not self.turns:
                return ChatResult(content="Final report after script ended.")
            return self.turns.pop(0)

    tmp = jarvis_env["tmp"]
    target = tmp / "exposed.txt"
    provider = ScriptedProvider(
        [
            ChatResult(
                content="END STATE: file exists\nACCEPTANCE CRITERIA:\n- file exists\nPLAN:\n1. write file"
            ),
            ChatResult(tool_calls=[_tool("request_tools", {"names": ["git"]}, "r1")]),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "ok", "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="Wrote the file."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified exposed.txt exists."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        "Organize these files on the desktop",
        autonomy="autonomous",
        profile="fast",
    )
    runner = AGENT._tasks[created.id]
    await runner
    first_names = {item["function"]["name"] for item in (provider.calls[0]["tools"] or [])}
    assert "filesystem" in first_names
    assert "request_tools" in first_names
    assert "docker" not in first_names
    assert "browser" not in first_names
    later = {item["function"]["name"] for item in (provider.calls[2]["tools"] or [])}
    assert "git" in later
    assert target.read_text() == "ok"

