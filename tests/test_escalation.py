from app.agent.escalation import (
    consult_expert,
    expert_packet,
    should_escalate,
    user_requests_expert,
)
from app.agent.loop import AGENT
from app.agent.planning import WorkingState
from app.providers.base import ChatResult
from tests.test_verification_loop import ScriptedProvider, _finished, _tool


def test_user_request_escalates_immediately():
    decision = should_escalate(prompt="Please use the expert model for this architecture decision")
    assert decision.should_escalate
    assert "user requested" in decision.reason
    assert user_requests_expert("give me a second opinion on this")


def test_length_alone_does_not_escalate():
    decision = should_escalate(
        prompt="Keep going through this long checklist of file copies",
        task_class="filesystem",
        consecutive_failures=0,
    )
    assert decision.should_escalate is False


def test_repeated_failures_escalate_once():
    first = should_escalate(consecutive_failures=3, prompt="fix the build")
    assert first.should_escalate
    second = should_escalate(consecutive_failures=5, already_escalated=True)
    assert second.should_escalate is False


def test_multiple_strategies_and_contradictions():
    assert should_escalate(distinct_failed_tools=3).should_escalate
    assert should_escalate(observations=["wrote report.md", "ERROR: file not found"]).should_escalate
    assert should_escalate(critic_rejected=True).should_escalate


def test_expert_packet_is_compact():
    working = WorkingState(
        goal="fix login",
        acceptance_criteria=["tests pass"],
        plan=["inspect auth"],
        known_failures=["browser: timeout"],
        observations=["filesystem: found auth.py"],
        task_class="software engineering",
    )
    packet = expert_packet(working, "repeated tool failure")
    assert "GOAL: fix login" in packet
    assert "UNRESOLVED PROBLEM: repeated tool failure" in packet
    assert "timeout" in packet
    assert len(packet) < 2000


async def test_consult_expert_uses_current_provider_when_gguf_missing(jarvis_env):
    provider = ScriptedProvider([ChatResult(content="PLAN:\n1. read the file\n2. patch it")])
    jarvis_env["manager"].provider = provider
    text = await consult_expert(jarvis_env["settings"], "GOAL: x\nUNRESOLVED PROBLEM: stuck", "balanced", provider=provider)
    assert "read the file" in text
    assert len(provider.turns) == 0


async def test_requested_expert_consult_runs_inside_the_loop(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "expert.txt"
    provider = ScriptedProvider(
        [
            ChatResult(content="PLAN:\n1. write the file with the filesystem tool"),
            ChatResult(content="END STATE: expert.txt exists\nACCEPTANCE CRITERIA:\n- file contains EXPERT\nPLAN:\n1. write"),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "EXPERT", "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="Wrote it."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified expert.txt contains EXPERT."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Use the expert model. Write {target} containing EXPERT.",
        autonomy="autonomous",
        profile="fast",
        execution_mode="fast",
    )
    task = await _finished(created.id)
    assert task.status == "completed"
    assert target.read_text(encoding="utf-8") == "EXPERT"
    injected = any(
        "Expert analysis" in str(getattr(message, "content", ""))
        for call in provider.calls
        for message in call["messages"]
    )
    assert injected
