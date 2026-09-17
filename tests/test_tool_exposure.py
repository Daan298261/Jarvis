from app.agent.tool_exposure import (
    describe_exposure,
    grant_requested_tools,
    is_full_exposure,
    schemas_for,
    tool_names_for,
    RESTRICTED_TOOLS,
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


def test_mixed_does_not_preload_the_full_catalog():
    mixed = set(tool_names_for("mixed"))
    native = {
        name
        for name, tool in REGISTRY.tools.items()
        if tool.enabled and name != "request_tools" and name not in RESTRICTED_TOOLS
    }
    assert "filesystem" in mixed
    assert "docker" not in mixed
    assert "office" not in mixed
    assert mixed < native
    assert not is_full_exposure("mixed")
    schema_names = [item["function"]["name"] for item in schemas_for("mixed")]
    assert "request_tools" in schema_names
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
    assert "catalog is not kept" in text


def test_prompt_retrieves_office_without_dumping_docker():
    names = tool_names_for("mixed", prompt="Update the excel spreadsheet with this week's numbers")
    assert "office" in names
    assert "filesystem" in names
    assert "docker" not in names
    assert "hexstrike_defensive" not in names


def test_voice_check_does_not_retrieve_the_catalog():
    names = set(tool_names_for("conversation", prompt="do a voice check"))
    native = {
        name
        for name, tool in REGISTRY.tools.items()
        if tool.enabled and name not in {"request_tools", "request_capability"}
    }
    assert names <= {"filesystem", "python"}
    assert len(names) < len(native)


def test_request_capability_grant_appears_in_next_turn_without_full_catalog():
    names = tool_names_for("mixed", ["docker"])
    assert "docker" in names
    assert "office" not in names
    assert "desktop" not in names


def test_file_task_prompt_does_not_retrieve_unrelated_tools():
    names = set(tool_names_for("filesystem", prompt="Organize files into a folder and write the notes file"))
    assert "filesystem" in names
    assert "python" in names
    assert "office" not in names
    assert "docker" not in names
    assert "browser" not in names
    assert "desktop" not in names


def test_openhands_prompt_hints_installable_worker_without_loading_it():
    from app.agent.tool_retrieval import suggest_installable_for_prompt, suggest_tools_for_prompt

    enabled = REGISTRY.tools.get("code_worker")
    if enabled is not None:
        enabled.enabled = False
    try:
        hints = suggest_installable_for_prompt("Use OpenHands on this repository")
        assert "openhands" in hints
        retrieved = suggest_tools_for_prompt("Use OpenHands on this repository")
        assert "code_worker" not in retrieved
    finally:
        if enabled is not None:
            enabled.enabled = True
