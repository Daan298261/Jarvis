from __future__ import annotations

SIMPLE = 8192
NORMAL = 16384
LONG = 32768

SIMPLE_CLASSES = {
    "filesystem",
    "shell",
    "office",
    "document processing",
    "data processing",
}
LONG_CLASSES = {
    "long-horizon autonomous",
    "research",
    "browser automation",
    "software engineering",
}


def recommend_context_size(
    task_class: str | None,
    execution_mode: str | None = "balanced",
    profile_default: int = NORMAL,
) -> int:
    """Pick 8K / 16K / 32K from task class instead of always using the profile max.

    Fast mode never opens a 32K window. Reliable mode steps one tier up so
    planning and verification fit. The result is also capped at the profile
    default so a Fast GGUF profile cannot request more than it was loaded for.
    """
    cls = (task_class or "mixed").strip().lower()
    mode = (execution_mode or "balanced").strip().lower()
    ceiling = int(profile_default or NORMAL)

    if cls in SIMPLE_CLASSES:
        size = SIMPLE
    elif cls in LONG_CLASSES:
        size = LONG
    else:
        size = NORMAL

    if mode == "fast":
        size = min(size, NORMAL)
    elif mode == "reliable":
        if size == SIMPLE:
            size = NORMAL
        elif size == NORMAL:
            size = LONG

    return max(SIMPLE, min(size, max(ceiling, SIMPLE)))
