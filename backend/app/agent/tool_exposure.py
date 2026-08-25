"""Task-class tool exposure (P0.7).

Do not send every Jarvis tool schema on every model turn. Classification
already exists; use it to expose a small relevant set, plus filesystem for
verification, plus an escape hatch (`request_tools`) so the agent can ask
for another capability when the first set is insufficient.

Returning None from `allowed_tool_names` means "every enabled tool", which
is used for mixed and long-horizon work.
"""

from __future__ import annotations

from typing import Iterable

CORE_TOOLS: tuple[str, ...] = ("filesystem", "request_tools")

# Classification names come from `planning.TASK_CATEGORIES`.
CLASS_TOOLS: dict[str, tuple[str, ...]] = {
    "filesystem": ("filesystem", "python"),
    "shell": ("terminal", "python", "filesystem"),
    "system administration": ("terminal", "python", "filesystem"),
    "software engineering": ("filesystem", "terminal", "python", "git", "docker"),
    "research": ("web_fetch", "browser", "filesystem", "python"),
    "browser automation": ("browser", "web_fetch", "filesystem", "screenshot"),
    "windows gui": ("desktop", "screenshot", "terminal", "filesystem", "ufo", "cua"),
    "office": ("office", "python", "filesystem"),
    "document processing": ("filesystem", "python", "office"),
    "data processing": ("filesystem", "python"),
    "multimodal": ("screenshot", "filesystem", "desktop", "browser"),
}

FULL_ACCESS_CLASSES = frozenset({"mixed", "long-horizon autonomous"})

CATEGORY_ALIASES: dict[str, tuple[str, ...] | None] = {
    "all": None,
    "everything": None,
    "browser": ("browser", "web_fetch", "screenshot"),
    "web": ("browser", "web_fetch"),
    "windows": ("desktop", "screenshot", "ufo", "cua"),
    "gui": ("desktop", "screenshot", "ufo", "cua"),
    "computer": ("desktop", "screenshot", "ufo", "cua"),
    "coding": ("filesystem", "terminal", "python", "git", "docker"),
    "code": ("filesystem", "terminal", "python", "git", "docker"),
    "shell": ("terminal", "python", "filesystem"),
    "office": ("office", "python", "filesystem"),
    "vision": ("screenshot", "desktop", "browser"),
    "mcp": ("mcp_call", "mcp"),
}


def _normalize(items: Iterable[str] | str | None) -> list[str]:
    if items is None:
        return []
    if isinstance(items, str):
        parts = [part.strip() for part in items.replace(";", ",").split(",")]
        return [part.lower() for part in parts if part]
    out: list[str] = []
    for item in items:
        if not item:
            continue
        out.append(str(item).strip().lower())
    return [item for item in out if item]


def wants_full_access(task_class: str | None, extra: Iterable[str] | str | None = None) -> bool:
    if (task_class or "").strip().lower() in FULL_ACCESS_CLASSES:
        return True
    requested = _normalize(extra)
    return any(CATEGORY_ALIASES.get(name) is None for name in requested if name in CATEGORY_ALIASES)


def resolve_requested_names(requested: Iterable[str] | str | None) -> set[str]:
    names: set[str] = set()
    for item in _normalize(requested):
        alias = CATEGORY_ALIASES.get(item)
        if alias is None and item in CATEGORY_ALIASES:
            continue
        if alias:
            names.update(alias)
        else:
            names.add(item)
    return names


def apply_request(existing: Iterable[str] | None, requested: Iterable[str] | str | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in list(existing or []) + _normalize(requested):
        key = str(item).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(key)
    return merged


def allowed_tool_names(task_class: str | None, extra: Iterable[str] | None = None) -> set[str] | None:
    """Return the tool names to put in the model schema, or None for all tools."""
    extra_list = list(extra or [])
    if wants_full_access(task_class, extra_list):
        return None
    names = set(CORE_TOOLS)
    names.update(CLASS_TOOLS.get((task_class or "").strip().lower(), ()))
    names.update(resolve_requested_names(extra_list))
    return names


def includes_mcp(allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    return "mcp" in allowed or "mcp_call" in allowed


def schema_names(schemas: list[dict]) -> list[str]:
    names: list[str] = []
    for item in schemas:
        function = item.get("function") if isinstance(item, dict) else None
        if isinstance(function, dict) and function.get("name"):
            names.append(str(function["name"]))
    return names


def exposure_prompt_block(task_class: str | None, extra: Iterable[str] | None = None) -> str:
    allowed = allowed_tool_names(task_class, extra)
    if allowed is None:
        return (
            "Tool exposure: every enabled tool is available for this mixed/long-horizon task.\n"
        )
    listed = ", ".join(sorted(allowed))
    return (
        f"Tool exposure: {listed}.\n"
        "If this set cannot finish the task, call request_tools with extra tool names "
        "or a category (browser, coding, windows, office, mcp, all).\n"
    )
