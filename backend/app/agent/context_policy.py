from __future__ import annotations

from typing import Any

CONTEXT_SIMPLE = 8192
CONTEXT_NORMAL = 16384
CONTEXT_LONG = 32768

# Start these classes at 8K. Grow to 16K/32K only if the live prompt is under pressure.
SIMPLE_CLASSES = {
    "filesystem",
    "shell",
    "office",
    "document processing",
    "data processing",
}

# Start at 16K even when the profile cap is 32K. Expand later if compaction is not enough.
LONG_CLASSES = {
    "long-horizon autonomous",
    "software engineering",
    "research",
    "mixed",
}


def profile_cap(profile: Any) -> int:
    size = int(getattr(profile, "context_size", 0) or 0)
    return size if size > 0 else CONTEXT_LONG


def initial_context_size(task_class: str | None, profile: Any) -> int:
    """Pick a starting window from the task class. Never exceed the profile cap."""
    cap = profile_cap(profile)
    klass = (task_class or "").strip().lower()
    if klass in SIMPLE_CLASSES:
        return min(CONTEXT_SIMPLE, cap)
    if klass in LONG_CLASSES:
        return min(CONTEXT_NORMAL, cap)
    return min(CONTEXT_NORMAL, cap)


def next_context_size(
    current: int,
    cap: int,
    estimated_tokens: int,
    *,
    compacted: bool = False,
) -> int | None:
    """Return a larger window when the live prompt is filling the current one.

    Mid-task we only grow. Shrinking belongs at task start.
    """
    current = int(current or 0)
    cap = int(cap or 0) or CONTEXT_LONG
    if current >= cap:
        return None
    if estimated_tokens <= 0:
        return None
    hot = estimated_tokens >= int(current * 0.7)
    if compacted and estimated_tokens >= int(current * 0.5):
        hot = True
    if not hot:
        return None
    if current < CONTEXT_NORMAL:
        return min(CONTEXT_NORMAL, cap)
    if current < CONTEXT_LONG:
        return min(CONTEXT_LONG, cap)
    return None


def recommend_context_size(task_class: str | None, execution_mode: str | None, profile_cap: int) -> int:
    """Starting window from the task class, never above the profile cap."""
    dummy = type("Profile", (), {"context_size": int(profile_cap or CONTEXT_LONG)})()
    return initial_context_size(task_class, dummy)
