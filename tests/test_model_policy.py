from app.agent.model_policy import (
    bump_context_tier,
    context_under_pressure,
    default_load_context,
    select_context_size,
    should_think,
    task_needs_vision,
)


def _think(**overrides):
    base = dict(
        profile_thinking=True,
        profile_name="balanced",
        execution_mode="balanced",
        verifying=False,
        force_final=False,
        planning=False,
        recovering=False,
        critic_turn=False,
        consecutive_failures=0,
        last_tool="",
        task_class="filesystem",
    )
    base.update(overrides)
    return should_think(**base)


def test_fast_profile_never_thinks():
    assert _think(profile_name="fast", planning=True, recovering=True) is False
    assert _think(profile_thinking=False, planning=True) is False


def test_thinking_on_for_planning_recovery_and_reliable_verify():
    assert _think(planning=True) is True
    assert _think(recovering=True) is True
    assert _think(critic_turn=True) is True
    assert _think(consecutive_failures=2) is True
    assert _think(verifying=True, execution_mode="reliable") is True
    assert _think(verifying=True, execution_mode="balanced") is False


def test_thinking_off_for_routine_tool_follow_ups():
    assert _think(last_tool="filesystem") is False
    assert _think(last_tool="git") is False
    assert _think(force_final=True, planning=True) is False


def test_select_context_simple_normal_long():
    cap = 32768
    simple = select_context_size(
        task_class="filesystem",
        execution_mode="balanced",
        profile_name="balanced",
        profile_cap=cap,
        prompt="rename a file",
    )
    assert simple == 8192
    engineering = select_context_size(
        task_class="software engineering",
        execution_mode="balanced",
        profile_name="balanced",
        profile_cap=cap,
        prompt="fix the tests",
    )
    assert engineering == 16384
    long_task = select_context_size(
        task_class="long-horizon autonomous",
        execution_mode="balanced",
        profile_name="balanced",
        profile_cap=cap,
        prompt="do everything",
    )
    assert long_task == 32768


def test_fast_never_opens_32k_and_reliable_steps_up():
    fast = select_context_size(
        task_class="long-horizon autonomous",
        execution_mode="fast",
        profile_name="fast",
        profile_cap=16384,
        prompt="huge task",
    )
    assert fast == 16384
    reliable = select_context_size(
        task_class="filesystem",
        execution_mode="reliable",
        profile_name="balanced",
        profile_cap=32768,
        prompt="rename a file",
    )
    assert reliable == 16384


def test_context_never_shrinks_mid_task():
    kept = select_context_size(
        task_class="filesystem",
        execution_mode="balanced",
        profile_name="balanced",
        profile_cap=32768,
        prompt="rename",
        current=16384,
    )
    assert kept == 16384


def test_default_idle_load_is_not_32k():
    assert default_load_context("balanced", 32768) == 16384
    assert default_load_context("fast", 16384) == 8192


def test_lazy_vision_only_for_gui_or_screenshot_tasks():
    assert task_needs_vision("filesystem", "organize files", "lazy") is False
    assert task_needs_vision("windows gui", "click Save in Notepad", "lazy") is True
    assert task_needs_vision("mixed", "inspect this screenshot", "lazy") is True
    assert task_needs_vision("multimodal", "anything", "off") is False
    assert task_needs_vision("filesystem", "list files", "always") is True


def test_context_pressure_and_tier_bump():
    assert bump_context_tier(8192) == 16384
    assert bump_context_tier(16384) == 32768
    assert bump_context_tier(32768) == 32768
    assert context_under_pressure(25_000, 8192) is True
    assert context_under_pressure(100, 16384) is False
