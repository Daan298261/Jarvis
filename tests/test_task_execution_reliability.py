"""Regressions from the 'open steam' failure: routing, skills, launcher, step reuse."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from app.agent.coding_contract import applies_coding_execution_contract
from app.agent.planning import app_control_target, classify_task
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


@pytest.mark.parametrize(
    "prompt",
    ["open the file C:/notes/todo.txt", "open https://example.com", "run the tests", "start a new document"],
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
