from app.agent.escalation import (
    EscalationBrief,
    consult_expert,
    should_escalate,
)
from app.providers.base import ChatResult


def test_long_tasks_do_not_escalate_by_themselves():
    assert should_escalate(step_count=40, consecutive_failures=0) is None
    assert should_escalate(already_escalated=True, consecutive_failures=9) is None
    assert should_escalate(verifying=True, consecutive_failures=9) is None


def test_repeated_failures_and_stuck_strategy_escalate():
    assert should_escalate(consecutive_failures=3) == "repeated_failure"
    assert should_escalate(same_tool_streak=4) == "stuck_strategy"
    assert should_escalate(critic_text="I am not confident this will work") == "critic_uncertainty"


def test_user_can_request_expert_without_failures():
    assert should_escalate(prompt="Use the expert model for this architecture decision", step_count=0) == "user_requested_expert"


async def test_consult_expert_uses_compact_brief_not_full_history():
    class Provider:
        def __init__(self):
            self.messages = None

        async def chat(self, messages, tools=None, **kwargs):
            self.messages = messages
            assert tools is None
            assert kwargs.get("thinking") is True
            return ChatResult(content="ANALYSIS:\nInspect first.\nNEXT PLAN:\n1. read the file\nAVOID:\n- repeating the same write")

    provider = Provider()
    brief = EscalationBrief(
        goal="fix login",
        acceptance_criteria=["tests pass"],
        observations=["filesystem: auth.py exists"],
        failed_approaches=["python: syntax error"],
        relevant_files=["auth.py"],
        unresolved_problem="tests still fail",
        reason="repeated_failure",
        task_class="software engineering",
    )
    result = await consult_expert(brief, provider=provider, allow_swap=False)
    assert result.advised
    assert result.swapped is False
    user = provider.messages[1].content
    assert "Goal: fix login" in user
    assert "Failed approaches" in user
    assert "full trajectory" not in user.lower()
    assert "Inspect first" in result.advice
