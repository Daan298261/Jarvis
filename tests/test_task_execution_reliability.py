"""Regressions from the 'open steam' failure: routing, skills, launcher, step reuse."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from app.agent.coding_contract import applies_coding_execution_contract
from app.agent.planning import app_control_target, classify_task, simple_app_control
from app.agent.skills import sanitize_steps, skill_grounded_in_goal
from app.tools.apps import _score, normalize_app_name


@pytest.mark.parametrize(
    ("prompt", "target"),
    [
        ("open steam", "steam"),
        ("start steam for me", "steam"),
        ("please open spotify", "spotify"),
        ("close snipping tool", "snipping tool"),
        ("jarvis, launch discord", "discord"),
        ("open notepad and type hello", "notepad"),
        ("quit spotify now", "spotify"),
    ],
)
def test_app_requests_route_to_desktop_control(prompt, target):
    assert app_control_target(prompt) == target
    assert classify_task(prompt) == "windows gui"


def test_simple_open_steam_does_not_need_the_model():
    assert simple_app_control("open steam") == ("open", "steam")
    assert simple_app_control("please close Spotify now") == ("close", "Spotify")
    assert simple_app_control("open notepad and type hello") is None
    assert simple_app_control("open the website and save the page title") is None


@pytest.mark.asyncio
async def test_open_steam_task_skips_the_language_model(jarvis_env, monkeypatch):
    from app.agent.loop import AGENT
    from app.tools.base import ToolResult
    from app.tools.registry import REGISTRY
    from tests.test_verification_loop import _finished

    async def fake_execute(name, arguments, **_kw):
        assert name == "apps"
        assert arguments.get("action") == "open"
        assert str(arguments.get("name") or "").lower() == "steam"
        return ToolResult(True, "Started Steam (pid 1).", data={"name": "Steam"})

    original = REGISTRY.execute
    REGISTRY.execute = fake_execute  # type: ignore[assignment]
    monkeypatch.setattr(
        "app.policy.action_gate.decide",
        lambda *a, **k: type("R", (), {"answers": {}, "fallback_used": True, "provider": "generative"})(),
    )
    try:
        task = await AGENT.create_task("open steam")
        finished = await _finished(task.id)
    finally:
        REGISTRY.execute = original  # type: ignore[assignment]
    assert finished.status == "completed"
    assert "Steam is open" in (finished.result or "")
    assert jarvis_env["manager"].provider is None


def test_windows_gui_exposes_the_apps_launcher():
    from app.agent.tool_exposure import tool_names_for

    names = tool_names_for("windows gui", prompt="open steam")
    assert "apps" in names



@pytest.mark.parametrize(
    "prompt",
    ["open the file C:/notes/todo.txt", "open https://example.com", "run the tests", "start a new document", "open the website and save the page title"],
)
def test_non_app_requests_are_not_app_control(prompt):
    assert app_control_target(prompt) is None


def test_coding_session_is_software_engineering():
    assert classify_task("start a coding session on the jarvis repo") == "software engineering"


def test_paths_do_not_decide_the_task_class():
    prompt = r"Write C:\Temp\pytest-of-owner\run1\verified.txt containing VERIFIED and make sure it is there."
    assert classify_task(prompt) != "software engineering"
    assert applies_coding_execution_contract(prompt, classify_task(prompt)) is False
    # Long-horizon work is only held to the coding contract when it is software work.
    assert applies_coding_execution_contract("organize my photos and back them up", "long-horizon autonomous") is False
    assert applies_coding_execution_contract("fix the failing pytest in the api", "long-horizon autonomous") is True


NOTEPAD_SKILL_STEPS = [
    {"tool": "terminal", "arguments": {"action": "start", "command": "notepad", "shell": "cmd"}},
    {"tool": "terminal", "arguments": {"action": "wait", "pid": 49556}},
    {"tool": "terminal", "arguments": {"action": "run", "command": "tasklist | findstr notepad", "shell": "cmd"}},
] * 6


def test_notepad_skill_does_not_run_for_steam():
    steps = sanitize_steps(NOTEPAD_SKILL_STEPS)
    assert skill_grounded_in_goal(steps, {}, "open steam") is False
    assert skill_grounded_in_goal(steps, {}, "open notepad for me") is True


def test_recorded_loops_and_pids_are_not_replayed():
    steps = sanitize_steps(NOTEPAD_SKILL_STEPS)
    assert len(steps) == 2
    assert all("pid" not in step["arguments"] for step in steps)


def test_bound_parameters_ground_a_skill():
    steps = [{"tool": "filesystem", "arguments": {"action": "write", "path": "{path}", "content": "SKILL"}}]
    assert skill_grounded_in_goal(steps, {"path": "C:/x/notes.txt"}, "write SKILL to C:/x/notes.txt") is True


def test_app_name_scoring_prefers_exact_and_prefix():
    assert _score("steam", "Steam") == 100
    assert _score("chrome", "Google Chrome") < 70
    assert normalize_app_name("the Spotify app") == "spotify"


@pytest.mark.skipif(os.name != "nt", reason="Windows Start Menu resolution")
def test_resolves_installed_apps_quickly():
    import time

    from app.tools.apps import resolve_app

    started = time.perf_counter()
    target = resolve_app("notepad")
    assert target is not None
    assert (time.perf_counter() - started) < 2.0


@pytest.mark.asyncio
async def test_repeated_identical_tool_call_runs_again(jarvis_env):
    """A live re-check (is the app running yet?) must not return a stale stored result."""
    from app.agent.loop import AGENT
    from app.db.models import Task
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        session.add(Task(id="repeat-check", title="t", prompt="t", status="running", stage="act"))
        await session.commit()
    calls: list[int] = []

    async def fake_execute(name, arguments, **_kw):
        calls.append(1)
        from app.tools.base import ToolResult

        return ToolResult(True, f"call {len(calls)}")

    from app.tools.registry import REGISTRY

    original = REGISTRY.execute
    REGISTRY.execute = fake_execute  # type: ignore[assignment]
    try:
        settings = SimpleNamespace()
        first, _ = await AGENT._execute_tool_ex("repeat-check", "apps", {"action": "running", "name": "steam"}, "autonomous", settings)
        second, _ = await AGENT._execute_tool_ex("repeat-check", "apps", {"action": "running", "name": "steam"}, "autonomous", settings)
    finally:
        REGISTRY.execute = original  # type: ignore[assignment]
    assert len(calls) == 2
    assert first != second
    assert json.dumps(first)


def test_cmd_search_idioms_are_adapted_and_exit_one_is_ok():
    from app.tools.terminal import adapt_shell, search_miss_ok

    assert adapt_shell("tasklist | findstr steam", "powershell") == "cmd"
    assert adapt_shell("Get-Process | Where-Object {$_.Name -eq 'steam'}", "powershell") == "powershell"
    assert search_miss_ok("tasklist | findstr steam", 1)
    assert not search_miss_ok("python -c 'raise SystemExit(1)'", 1)
    assert not search_miss_ok("findstr steam", 2)


@pytest.mark.asyncio
async def test_search_miss_is_not_a_tool_failure():
    from app.tools.terminal import TerminalTool

    tool = TerminalTool()
    if os.name == "nt":
        result = await tool.execute(
            command="findstr /c:ZZZNOMATCHNOWHERE C:\\Windows\\win.ini",
            shell="cmd",
        )
    else:
        result = await tool.execute(command="grep ZZZNOMATCHNOWHERE /etc/hosts", shell="bash")
    assert result.success, result.error
    assert result.data.get("exit_code") == 1
    assert not result.text().startswith("ERROR:")


@pytest.mark.asyncio
async def test_irreversible_runs_only_after_owner_approval(monkeypatch):
    from app.tools.base import ToolResult
    from app.tools.registry import REGISTRY
    from app.tools.terminal import TerminalTool

    tool = TerminalTool()
    ran: list[int] = []

    async def fake_run(*_a, **_k):
        ran.append(1)
        return ToolResult(True, "ok")

    monkeypatch.setattr(tool, "_run", fake_run)
    REGISTRY._context["approved"] = False
    blocked = await tool.execute(command="rm -rf scratch-dir")
    assert blocked.success is False
    assert "irreversible" in blocked.error.lower()
    assert not ran
    REGISTRY._context["approved"] = True
    allowed = await tool.execute(command="rm -rf scratch-dir")
    assert allowed.success is True
    assert ran
    REGISTRY._context["approved"] = False


@pytest.mark.asyncio
async def test_kill_refuses_protected_process():
    from app.tools.terminal import TerminalTool

    result = await TerminalTool().execute(action="kill", pid=os.getpid())
    assert result.success is False
    assert "protected" in result.error.lower()
