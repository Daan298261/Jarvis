from app.agent.thinking import should_think


def test_fast_profile_never_thinks_even_while_planning():
    decision = should_think(profile_thinking=False, tools_used=False)
    assert decision.enabled is False
    assert decision.reason == "profile thinking off"


def test_balanced_thinks_during_initial_plan():
    decision = should_think(profile_thinking=True, tools_used=False)
    assert decision.enabled is True
    assert decision.reason == "planning"


def test_balanced_skips_thinking_after_simple_filesystem_read():
    decision = should_think(
        profile_thinking=True,
        execution_mode="balanced",
        tools_used=True,
        last_tool="filesystem",
        last_action="read",
    )
    assert decision.enabled is False
    assert "deterministic" in decision.reason


def test_failure_re_enables_thinking():
    decision = should_think(
        profile_thinking=True,
        tools_used=True,
        consecutive_failures=1,
        last_tool="filesystem",
        last_action="read",
    )
    assert decision.enabled is True
    assert decision.reason == "recovery after failure"


def test_final_report_never_thinks():
    decision = should_think(profile_thinking=True, force_final=True, tools_used=True)
    assert decision.enabled is False


def test_reliable_thinks_on_verification():
    decision = should_think(
        profile_thinking=True,
        execution_mode="reliable",
        tools_used=True,
        verifying=True,
    )
    assert decision.enabled is True
    assert decision.reason == "consequential verification"


def test_balanced_skips_thinking_on_routine_verification():
    decision = should_think(
        profile_thinking=True,
        execution_mode="balanced",
        tools_used=True,
        verifying=True,
    )
    assert decision.enabled is False


def test_complex_task_class_keeps_thinking():
    decision = should_think(
        profile_thinking=True,
        tools_used=True,
        last_tool="python",
        last_action="run_code",
        task_class="software engineering",
    )
    assert decision.enabled is True
    assert decision.reason == "complex task class"
