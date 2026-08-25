from app.agent.escalation import context_from_working, persist_escalation_package
from app.agent.planning import WorkingState
from app.agent.loop import AGENT
from app.db.models import EscalationPackage, Task
from app.db.session import SessionLocal
from app.providers.base import ChatResult
import json


def test_escalation_context_is_compact_not_a_transcript():
    working = WorkingState(
        goal="Add EscalationContext packaging",
        acceptance_criteria=["package has goal and reason", "no raw transcript"],
        task_class="software engineering",
        known_failures=["python: pytest failed on test_foo"],
    )
    package = context_from_working(
        "task-1",
        working,
        reason="local worker failed twice",
        relevant_files=["backend/app/agent/escalation.py"],
        current_diff="- old\n+ new",
        failing_tests="FAILED tests/test_foo.py",
        important_logs="exit_code=1",
        attempted_strategies=["python", "filesystem"],
    )
    prompt = package.as_prompt()
    assert "EscalationContext" in prompt
    assert "Add EscalationContext packaging" in prompt
    assert "FAILED tests/test_foo.py" in prompt
    assert "role=assistant" not in prompt
    assert len(prompt) < 8000


async def test_persist_escalation_package(jarvis_env):
    working = WorkingState(goal="fix tests", task_class="software engineering", acceptance_criteria=["green"])
    package = context_from_working("missing-task", working, reason="tests failed")
    await persist_escalation_package(package)
    async with SessionLocal() as session:
        row = await session.get(EscalationPackage, package.id)
    assert row is not None
    payload = json.loads(row.payload_json)
    assert payload["goal"] == "fix tests"
    assert payload["reason"] == "tests failed"


def _tool(name: str, arguments: dict, call_id: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class ScriptedProvider:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def health(self):
        return True

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append(messages)
        if not self.turns:
            return ChatResult(content="Final report.")
        return self.turns.pop(0)


async def test_repeated_software_failures_persist_escalation_package(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "done.txt"
    missing = tmp / "nope.txt"
    provider = ScriptedProvider(
        [
            ChatResult(
                content="END STATE: done.txt exists\nACCEPTANCE CRITERIA:\n- file exists\nPLAN:\n1. read missing"
            ),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(missing)}, "c1")]),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(missing) + "2"}, "c2")]),
            ChatResult(
                tool_calls=[
                    _tool("filesystem", {"action": "write", "path": str(target), "content": "OK", "create_backup": False}, "c3")
                ]
            ),
            ChatResult(content="Recovered."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c4")]),
            ChatResult(content="Verified done.txt."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        "Debug this repository and fix the pytest failure by writing done.txt.",
        autonomy="autonomous",
        profile="fast",
    )
    await AGENT._tasks[created.id]
    async with SessionLocal() as session:
        task = await session.get(Task, created.id)
        from sqlalchemy import select

        packages = (await session.execute(select(EscalationPackage))).scalars().all()
    assert task.status == "completed"
    assert packages, "two consecutive tool failures should persist an EscalationContext"
    assert packages[0].task_id == created.id
