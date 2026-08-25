from app.agent.tool_exposure import (
    describe_exposure,
    grant_requested_tools,
    is_full_exposure,
    schemas_for,
    tool_names_for,
)
from app.tools.registry import REGISTRY


def test_filesystem_task_exposes_a_small_tool_set():
    names = tool_names_for("filesystem")
    assert names == ["filesystem", "python"]
    schema_names = [item["function"]["name"] for item in schemas_for("filesystem")]
    assert "filesystem" in schema_names
    assert "python" in schema_names
    assert "request_tools" in schema_names
    assert "docker" not in schema_names
    assert "office" not in schema_names
    assert "desktop" not in schema_names


def test_software_engineering_includes_git_and_terminal():
    names = tool_names_for("software engineering")
    assert names == ["filesystem", "terminal", "python", "git"]
    assert "request_tools" in [item["function"]["name"] for item in schemas_for("software engineering")]


def test_browser_research_does_not_include_office_by_default():
    names = set(tool_names_for("research"))
    assert {"web_fetch", "browser", "filesystem"} <= names
    assert "office" not in names
    assert "docker" not in names


def test_mixed_and_long_horizon_get_every_enabled_native_tool():
    mixed = set(tool_names_for("mixed"))
    long_h = set(tool_names_for("long-horizon autonomous"))
    native = {name for name, tool in REGISTRY.tools.items() if tool.enabled and name != "request_tools"}
    assert mixed == native
    assert long_h == native
    assert is_full_exposure("mixed")
    schema_names = [item["function"]["name"] for item in schemas_for("mixed")]
    assert "request_tools" not in schema_names
    assert "filesystem" in schema_names


def test_request_tools_grants_aliases_and_mcp_flag():
    granted = grant_requested_tools({"capabilities": ["web", "gui", "mcp"]})
    assert granted == ["web_fetch", "desktop", "mcp"]
    names = tool_names_for("filesystem", granted)
    assert "web_fetch" in names
    assert "desktop" in names
    schema_names = [item["function"]["name"] for item in schemas_for("filesystem", granted)]
    assert "web_fetch" in schema_names
    assert "desktop" in schema_names


def test_request_tools_maps_optional_worker_aliases():
    granted = grant_requested_tools({"capabilities": ["interpreter", "openhands", "ufo2"]})
    assert granted == ["open_interpreter", "code_worker", "ufo"]
    names = tool_names_for("filesystem", granted)
    assert "open_interpreter" in names
    assert "code_worker" in names
    assert "ufo" in names


def test_request_all_switches_to_full_exposure():
    assert is_full_exposure("filesystem", ["all"])
    names = tool_names_for("filesystem", ["all"])
    assert "docker" in names
    assert "git" in names


def test_exposure_prompt_mentions_the_escape_hatch():
    text = describe_exposure("filesystem")
    assert "filesystem" in text
    assert "request_tools" in text
