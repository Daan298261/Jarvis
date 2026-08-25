import pytest

from app.agent.recovery import (
    BLOCKED,
    NETWORK,
    NOT_FOUND,
    PERMISSION,
    TIMEOUT,
    UNAVAILABLE,
    UNKNOWN,
    USAGE,
    alternatives_for,
    classify_failure,
    recovery_hint,
)


@pytest.mark.parametrize(
    "observation,expected",
    [
        ("ERROR: Path /etc is outside allowed directories", PERMISSION),
        ("ERROR: File not found", NOT_FOUND),
        ("ERROR: Command timed out after 120s", TIMEOUT),
        ("ERROR: WSL/bash is not available on this machine", UNAVAILABLE),
        ("ERROR: No module named 'openpyxl'", UNAVAILABLE),
        ("ERROR: Unknown action frobnicate", USAGE),
        ("ERROR: connection refused", NETWORK),
        ("ERROR: Blocked irreversible command.", BLOCKED),
        ("ERROR: something strange happened", UNKNOWN),
    ],
)
def test_failure_classification(observation, expected):
    assert classify_failure(observation) == expected


def test_browser_failure_routes_to_more_deterministic_tools():
    options = [item.tool for item in alternatives_for("browser", NOT_FOUND)]
    assert options.index("web_fetch") < options.index("screenshot")


def test_ufo_failure_routes_to_native_desktop():
    options = [item.tool for item in alternatives_for("ufo", UNAVAILABLE)]
    assert options[0] == "desktop"
    cua = [item.tool for item in alternatives_for("cua", UNAVAILABLE)]
    assert cua[0] == "desktop"


def test_permission_failures_do_not_suggest_another_tool():
    assert alternatives_for("filesystem", PERMISSION) == []
    assert alternatives_for("terminal", BLOCKED) == []


def test_mcp_failures_fall_back_to_native_tools():
    assert [item.tool for item in alternatives_for("mcp_files_read", NOT_FOUND)] == ["filesystem", "terminal"]


def test_hint_names_an_alternative_and_forbids_the_same_call():
    hint = recovery_hint("office", "ERROR: Office is not installed")
    assert "python" in hint
    assert "Do not repeat the call that just failed." in hint
    assert "missing on this machine" in hint


def test_code_worker_falls_back_to_native_python():
    options = [item.tool for item in alternatives_for("code_worker", UNAVAILABLE)]
    assert options[0] == "python"
    hint = recovery_hint("code_worker", "ERROR: Open Interpreter is not installed")
    assert "python" in hint


def test_hint_escalates_after_repeated_failures():
    first = recovery_hint("terminal", "ERROR: command not found", attempt=1)
    third = recovery_hint("terminal", "ERROR: command not found", attempt=3)
    assert "Several strategies have now failed" not in first
    assert "Several strategies have now failed" in third
    assert third.count("- ") > first.count("- ")


def test_permission_hint_explains_the_boundary():
    hint = recovery_hint("filesystem", "ERROR: Path /etc/passwd is outside allowed directories")
    assert "sandbox boundary" in hint
    assert "Alternative tools" not in hint
