from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from app.agent.coding_contract import (
    applies_coding_execution_contract,
    contract_satisfied,
    evidence_from_working,
    init_coding_execution,
    note_contract_tool,
)
from app.agent.loop import AGENT
from app.agent.planning import WorkingState
from app.agent.tool_exposure import tool_names_for
from app.agent.tool_retrieval import suggest_tools_for_prompt
from app.inference.complexity_scorer import score_question_complexity
from app.tools.registry import REGISTRY
from app.providers.base import ChatResult
from tests.test_verification_loop import ScriptedProvider, _finished, _tool


def test_software_change_contract_requires_edit_run_verify():
    working = WorkingState(task_class="software engineering")
    init_coding_execution(working)
    assert not contract_satisfied(working, "implement a fix in the repo", working.task_class)
    note_contract_tool(
        working,
        "filesystem",
        {"action": "write", "path": "/tmp/x.py", "content": "x=1"},
        "wrote",
        success=True,
    )
    assert not contract_satisfied(working, "implement a fix", working.task_class)
    note_contract_tool(working, "terminal", {"command": "python -c 'print(1)'"}, "ok", success=True)
    assert not contract_satisfied(working, "implement a fix", working.task_class)
    note_contract_tool(working, "verify_code", {"path": "/tmp"}, "tests ok", success=True)
    assert contract_satisfied(working, "implement a fix in the repo", working.task_class)


def test_missing_openhands_still_requires_native_evidence():
    working = WorkingState(task_class="software engineering")
    init_coding_execution(working)
    note_contract_tool(
        working,
        "code_worker",
        {"action": "delegate", "goal": "fix tests"},
        "ERROR: OpenHands is not installed",
        success=False,
    )
    assert not contract_satisfied(working, "fix the failing pytest", working.task_class)
    note_contract_tool(
        working,
        "filesystem",
        {"action": "edit", "path": "a.py", "old_text": "a", "new_text": "b"},
        "ok",
        success=True,
    )
    note_contract_tool(working, "python", {"code": "import main"}, "ok", success=True)
    note_contract_tool(working, "verify_code", {"path": "."}, "ok", success=True)
    assert contract_satisfied(working, "fix pytest", working.task_class)


def test_tool_search_pulls_coding_and_3d_without_full_catalog():
    coding = suggest_tools_for_prompt("refactor this repository and run pytest")
    assert "verify_code" in coding or "git" in coding
    assert "blender" not in coding
    dcc = suggest_tools_for_prompt("model a gear in OpenSCAD and export STL")
    assert "openscad" in dcc
    names = tool_names_for("software engineering", prompt="implement unit tests for the api")
    assert "verify_code" in names
    assert "blender" not in names


def test_coding_prompt_raises_minimum_answer_tier():
    result = score_question_complexity(
        "implement a small refactor and add pytest",
        task_class="software engineering",
    )
    assert result.minimum_answer_tier >= 2
    assert "rfc-0120-coding-worker" in result.signals


async def test_chat_only_software_completion_rejected(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "module.py"
    provider = ScriptedProvider(
        [
            ChatResult(
                content=(
                    "END STATE: module fixed\nACCEPTANCE CRITERIA:\n- tests pass\n"
                    "PLAN:\n1. describe fix in chat"
                )
            ),
            ChatResult(content="I updated the code and all tests pass. Done."),
            ChatResult(content="Verified mentally. Task complete."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Implement a source code fix in repository file {target}: add value=2 and run pytest.",
        autonomy="autonomous",
        profile="fast",
        execution_mode="balanced",
    )
    task = await _finished(created.id)
    assert task.status != "completed"


async def test_software_task_completes_with_edit_run_verify(jarvis_env):
    tmp = jarvis_env["tmp"]
    repo = tmp / "proj"
    repo.mkdir()
    (repo / "tests").mkdir()
    (repo / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    target = repo / "module.py"
    provider = ScriptedProvider(
        [
            ChatResult(
                content="END STATE: module updated\nACCEPTANCE CRITERIA:\n- pytest passes\nPLAN:\n1. edit\n2. verify"
            ),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "VALUE = 2\n", "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="edited"),
            ChatResult(tool_calls=[_tool("terminal", {"command": "echo build-ok", "shell": "bash"}, "c2")]),
            ChatResult(content="ran tests"),
            ChatResult(tool_calls=[_tool("verify_code", {"path": str(repo)}, "c3")]),
            ChatResult(content="verify_code reported success."),
            ChatResult(content="Final report: edited module.py, ran pytest, verify_code ok."),
            ChatResult(content="Final report: all acceptance criteria met."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Refactor repository source code in {target} and run pytest in {repo}",
        autonomy="autonomous",
        profile="fast",
        execution_mode="balanced",
    )
    task = await _finished(created.id)
    assert task.status == "completed"
    assert target.read_text(encoding="utf-8").strip() == "VALUE = 2"


@pytest.fixture
def fake_blender(tmp_path, monkeypatch):
    script = tmp_path / "blender"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--background" ]; then touch "${JARVIS_FAKE_OUT:-/tmp/out.stl}"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
    return script


async def test_blender_missing_is_install_cta_not_success(jarvis_env, monkeypatch):
    monkeypatch.delenv("PATH", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    result = await REGISTRY.execute("blender", {"action": "background_python", "script_path": "/tmp/x.py"})
    assert result.success is False
    assert "not installed" in (result.error or "").lower()


async def test_blender_fake_cli_success(jarvis_env, fake_blender):
    script = jarvis_env["tmp"] / "make.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    result = await REGISTRY.execute(
        "blender",
        {"action": "background_python", "script_path": str(script)},
    )
    assert result.success is True


async def test_openscad_missing_install_cta(jarvis_env, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    result = await REGISTRY.execute(
        "openscad",
        {"input_path": "/tmp/x.scad", "output_path": "/tmp/x.stl"},
    )
    assert result.success is False
    assert "not installed" in (result.error or "").lower()


def test_applies_coding_contract_for_implement_prompt():
    assert applies_coding_execution_contract("please implement a unit test for the api", "mixed")
