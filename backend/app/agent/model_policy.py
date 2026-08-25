from __future__ import annotations

from typing import Iterable

CONTEXT_TIERS = (8192, 16384, 32768)

SIMPLE_CLASSES = {
    "filesystem",
    "shell",
    "office",
    "document processing",
    "data processing",
}
LONG_CLASSES = {"long-horizon autonomous"}
COMPLEX_CLASSES = {
    "software engineering",
    "system administration",
    "long-horizon autonomous",
    "mixed",
    "windows gui",
}
VISION_CLASSES = {"multimodal", "windows gui"}
VISION_KEYWORDS = (
    "screenshot",
    "screen shot",
    "image",
    "photo",
    "what do you see",
    "look at the screen",
    "vision",
)
SIMPLE_TOOLS = {"filesystem", "git", "python"}


def _tier_index(size: int) -> int:
    for index, tier in enumerate(CONTEXT_TIERS):
        if size <= tier:
            return index
    return len(CONTEXT_TIERS) - 1


def bump_context_tier(size: int) -> int:
    index = min(_tier_index(size) + 1, len(CONTEXT_TIERS) - 1)
    return CONTEXT_TIERS[index]


def select_context_size(
    *,
    task_class: str,
    execution_mode: str,
    profile_name: str,
    profile_cap: int,
    prompt: str = "",
    current: int | None = None,
) -> int:
    """Pick 8K / 16K / 32K from the task, then cap by profile. Never shrink."""
    text = prompt or ""
    category = (task_class or "mixed").strip().lower()
    mode = (execution_mode or "balanced").strip().lower()
    profile = (profile_name or "balanced").strip().lower()
    cap = int(profile_cap or CONTEXT_TIERS[-1])

    if category in LONG_CLASSES:
        size = 32768
    elif category in SIMPLE_CLASSES and len(text) < 1500:
        size = 8192
    elif category == "software engineering" or len(text) > 4000:
        size = 16384
    else:
        size = 16384

    if mode == "reliable":
        size = bump_context_tier(size)
    if mode == "fast" or profile == "fast":
        size = min(size, 16384)
    size = min(size, cap)
    if current and current > 0:
        # Mid-task shrink is forbidden; expand only when the new need is larger.
        size = max(size, min(int(current), cap))
    return size


def default_load_context(profile_name: str, profile_cap: int) -> int:
    """Idle Model-page loads should not open 32K just because the profile allows it."""
    cap = int(profile_cap or 16384)
    if (profile_name or "").lower() == "fast":
        return min(8192, cap)
    return min(16384, cap)


def task_needs_vision(task_class: str, prompt: str, vision_mode: str) -> bool:
    mode = (vision_mode or "lazy").strip().lower()
    if mode in {"off", "never", "disabled"}:
        return False
    if mode in {"always", "on"}:
        return True
    category = (task_class or "").strip().lower()
    if category in VISION_CLASSES:
        return True
    text = (prompt or "").lower()
    return any(keyword in text for keyword in VISION_KEYWORDS)


def should_think(
    *,
    profile_thinking: bool,
    profile_name: str,
    execution_mode: str,
    verifying: bool,
    force_final: bool,
    planning: bool,
    recovering: bool,
    critic_turn: bool,
    consecutive_failures: int,
    last_tool: str,
    task_class: str,
) -> bool:
    """Spend reasoning tokens on planning, recovery, and consequential verification."""
    if force_final:
        return False
    if not profile_thinking or (profile_name or "").lower() == "fast":
        return False
    if recovering or consecutive_failures > 0:
        return True
    if planning or critic_turn:
        return True
    if verifying:
        return (execution_mode or "").lower() == "reliable"
    if last_tool in SIMPLE_TOOLS:
        return False
    if (profile_name or "").lower() == "quality" and (task_class or "") in COMPLEX_CLASSES:
        return True
    return False


def estimate_message_chars(messages: Iterable) -> int:
    total = 0
    for message in messages:
        content = getattr(message, "content", message)
        if isinstance(content, str):
            total += len(content)
        else:
            total += len(str(content))
    return total


def context_under_pressure(message_chars: int, context_size: int, threshold: float = 0.72) -> bool:
    """Rough char→token estimate (~4 chars/token). Expand before the window is full."""
    if context_size <= 0:
        return False
    approx_tokens = message_chars / 4
    return approx_tokens >= context_size * threshold
