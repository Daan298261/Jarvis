from app.agent.context_policy import LONG, NORMAL, SIMPLE, recommend_context_size


def test_simple_filesystem_uses_8k():
    assert recommend_context_size("filesystem", "balanced", LONG) == SIMPLE


def test_software_engineering_uses_32k():
    assert recommend_context_size("software engineering", "balanced", LONG) == LONG


def test_mixed_uses_16k():
    assert recommend_context_size("mixed", "balanced", LONG) == NORMAL


def test_fast_mode_never_opens_32k():
    assert recommend_context_size("software engineering", "fast", LONG) == NORMAL


def test_reliable_mode_steps_up_one_tier():
    assert recommend_context_size("filesystem", "reliable", LONG) == NORMAL
    assert recommend_context_size("mixed", "reliable", LONG) == LONG


def test_fast_profile_ceiling_is_respected():
    assert recommend_context_size("software engineering", "reliable", NORMAL) == NORMAL
