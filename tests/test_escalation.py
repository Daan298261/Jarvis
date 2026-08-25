from app.agent.escalation import (
    EscalationSignals,
    ExpertBrief,
    build_expert_brief,
    consult_expert,
    looks_like_architecture,
    should_escalate,
    user_requested_expert,
)
from app.agent.planning import WorkingState


def test_does_not_escalate_for_a_long_or_single_failure():
    assert not should_escalate(EscalationSignals(consecutive_failures=6, failed_tools=["filesystem"], already_consulted=0))
    assert not should_escalate(EscalationSignals(consecutive_failures=2, failed_tools=["filesystem", "python"]))


def test_escalates_when_several_strategies_fail():
    assert should_escalate(
        EscalationSignals(consecutive_failures=3, failed_tools=["filesystem", "python"], already_consulted=0)
    )


def test_escalates_when_the_user_asks_for_expert():
    assert user_requested_expert("Please use the expert model for a second opinion")
    assert should_escalate(EscalationSignals(user_requested_expert=True, already_consulted=0))
    assert not should_escalate(EscalationSignals(user_requested_expert=True, already_consulted=1))


def test_architecture_plus_repeated_failure_escalates():
    assert looks_like_architecture("Redesign the inference architecture", "software engineering")
    assert should_escalate(
        EscalationSignals(
            consecutive_failures=2,
            failed_tools=["python"],
            architecture_task=True,
            already_consulted=0,
        )
    )


def test_brief_is_compact_and_omits_raw_traces():
    working = WorkingState(
        goal="fix login",
        acceptance_criteria=["tests pass"],
        observations=["filesystem: read /tmp/app/login.py"],
        known_failures=["python: TypeError on line 4"],
        next_action="try a different parser",
        task_class="software engineering",
    )
    brief = build_expert_brief(working)
    prompt = brief.as_prompt()
    assert "fix login" in prompt
    assert "tests pass" in prompt
    assert "TypeError" in prompt
    assert "Do not execute tools" in prompt
    assert len(prompt) < 4000


async def test_consult_restores_primary_after_expert_chat():
    order: list[str] = []

    async def load(name: str):
        order.append(f"load:{name}")

    async def unload():
        order.append("unload")

    async def chat(messages):
        order.append("chat")
        assert "Unresolved problem" in messages[1]["content"]
        return type("R", (), {"content": "ANALYSIS:\nuse git\nNEXT PLAN:\n1. inspect"})()

    brief = ExpertBrief(
        goal="g",
        acceptance_criteria=["ok"],
        observations=[],
        failed_approaches=["python failed"],
        unresolved_problem="stuck parsing",
        relevant_files=[],
        task_class="software engineering",
    )
    advice = await consult_expert(
        brief,
        primary_profile="balanced",
        load=load,
        unload=unload,
        chat=chat,
    )
    assert advice.used is True
    assert "ANALYSIS" in advice.content
    assert order == ["unload", "load:expert", "chat", "unload", "load:balanced"]


async def test_consult_skips_when_expert_cannot_load():
    async def load(name: str):
        if name == "expert":
            raise FileNotFoundError("GGUF missing")

    async def unload():
        return None

    async def chat(_messages):
        raise AssertionError("should not chat")

    advice = await consult_expert(
        ExpertBrief("g", [], [], [], "stuck", [], "mixed"),
        primary_profile="fast",
        load=load,
        unload=unload,
        chat=chat,
    )
    assert advice.used is False
    assert "GGUF missing" in advice.reason
    assert advice.primary_restored is True
