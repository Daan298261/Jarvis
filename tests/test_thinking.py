from app.agent.thinking import infer_phase, should_think


def test_fast_profile_stays_off_for_routine_work():
    decision = should_think(profile_thinking=False, execution_mode="fast", phase="act")
    assert decision.enabled is False


def test_balanced_thinks_while_planning_not_while_acting():
    plan = should_think(profile_thinking=True, execution_mode="balanced", phase="plan")
    act = should_think(profile_thinking=True, execution_mode="balanced", phase="act", tool_rounds=2)
    assert plan.enabled is True
    assert act.enabled is False
    assert "planning" in plan.reason or "plan" in plan.reason


def test_recovery_enables_thinking():
    decision = should_think(
        profile_thinking=True,
        execution_mode="balanced",
        phase="act",
        consecutive_failures=1,
    )
    assert decision.enabled is True
    assert "recover" in decision.reason


def test_reliable_verification_thinks_routine_verification_does_not():
    reliable = should_think(profile_thinking=True, execution_mode="reliable", phase="verify")
    balanced = should_think(profile_thinking=True, execution_mode="balanced", phase="verify")
    assert reliable.enabled is True
    assert balanced.enabled is False


def test_final_report_never_thinks():
    decision = should_think(profile_thinking=True, execution_mode="reliable", phase="final")
    assert decision.enabled is False


def test_infer_phase_maps_loop_flags():
    assert infer_phase(
        force_final=True,
        verifying=True,
        awaiting_plan_selection=False,
        best_of_n_complete=True,
        tools_used=True,
        consecutive_failures=0,
    ) == "final"
    assert infer_phase(
        force_final=False,
        verifying=False,
        awaiting_plan_selection=False,
        best_of_n_complete=False,
        tools_used=False,
        consecutive_failures=0,
    ) == "plan"
    assert infer_phase(
        force_final=False,
        verifying=False,
        awaiting_plan_selection=False,
        best_of_n_complete=True,
        tools_used=True,
        consecutive_failures=2,
    ) == "recover"
