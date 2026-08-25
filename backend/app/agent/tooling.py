from __future__ import annotations

from typing import Any, Iterable

from ..inference.profiles import ModelProfile
from ..tools.registry import REGISTRY

CORE_TOOLS = frozenset({"filesystem", "request_capability"})

ALL_NATIVE = frozenset(
    {
        "filesystem",
        "terminal",
        "python",
        "browser",
        "desktop",
        "office",
        "git",
        "docker",
        "web_fetch",
        "screenshot",
        "request_capability",
        "mcp",
    }
)

# Task class → tools the model should see. Always includes CORE_TOOLS.
TOOL_SETS: dict[str, frozenset[str]] = {
    "filesystem": frozenset({"filesystem", "python", "request_capability"}),
    "shell": frozenset({"filesystem", "terminal", "python", "request_capability"}),
    "system administration": frozenset({"filesystem", "terminal", "python", "request_capability"}),
    "software engineering": frozenset(
        {"filesystem", "terminal", "python", "git", "request_capability", "mcp"}
    ),
    "research": frozenset({"web_fetch", "browser", "filesystem", "request_capability"}),
    "browser automation": frozenset(
        {"browser", "web_fetch", "filesystem", "screenshot", "request_capability"}
    ),
    "windows gui": frozenset({"desktop", "screenshot", "terminal", "filesystem", "request_capability"}),
    "office": frozenset({"office", "filesystem", "python", "request_capability"}),
    "document processing": frozenset({"filesystem", "python", "office", "request_capability"}),
    "data processing": frozenset({"filesystem", "python", "terminal", "request_capability"}),
    "multimodal": frozenset({"screenshot", "desktop", "filesystem", "browser", "request_capability"}),
    "mixed": ALL_NATIVE,
    "long-horizon autonomous": ALL_NATIVE,
}


def tools_for_task(task_class: str | None) -> set[str]:
    names = set(TOOL_SETS.get((task_class or "").strip().lower(), ALL_NATIVE))
    names |= set(CORE_TOOLS)
    known = set(REGISTRY.tools)
    known.add("mcp")
    return {name for name in names if name in known}


def apply_capability_request(exposed: set[str], arguments: dict[str, Any]) -> tuple[set[str], list[str], str]:
    """Expand the live tool set. Returns (new_set, added, observation)."""
    wanted = arguments.get("capabilities") or arguments.get("tools") or []
    if arguments.get("name"):
        if isinstance(wanted, list):
            wanted = list(wanted) + [arguments.get("name")]
        elif wanted:
            wanted = [wanted, arguments.get("name")]
        else:
            wanted = [arguments.get("name")]
    if isinstance(wanted, str):
        wanted = [part.strip() for part in wanted.replace(",", " ").split() if part.strip()]
    if not isinstance(wanted, list):
        wanted = []
    known = set(REGISTRY.tools)
    added: list[str] = []
    next_set = set(exposed)
    unknown: list[str] = []
    for raw in wanted:
        name = str(raw or "").strip()
        if not name:
            continue
        if name in known and name not in next_set:
            next_set.add(name)
            added.append(name)
        elif name == "mcp" and "mcp" not in next_set:
            next_set.add("mcp")
            added.append("mcp")
        elif name not in known and name != "mcp":
            unknown.append(name)
    lines = []
    if added:
        lines.append("Additional tools are now available: " + ", ".join(sorted(added)) + ".")
        lines.append("They will appear in the tool list on the next turn. Use them directly.")
    else:
        lines.append("No new tools were added. Name a registered Jarvis tool such as git, browser, docker, or desktop.")
    if unknown:
        lines.append("Unknown capabilities: " + ", ".join(unknown) + ".")
    return next_set, added, "\n".join(lines)


def expose_called_tool(exposed: set[str], name: str) -> set[str]:
    """Escape hatch: executing an unlisted but real tool expands the set."""
    if name in REGISTRY.tools:
        exposed = set(exposed)
        exposed.add(name)
    return exposed


def schemas_for(exposed: Iterable[str]) -> list[dict[str, Any]]:
    return REGISTRY.openai_tools(names=set(exposed))


def should_enable_thinking(
    profile: ModelProfile,
    *,
    force_final: bool = False,
    verifying: bool = False,
    turn_index: int = 0,
    consecutive_failures: int = 0,
    awaiting_plan_selection: bool = False,
    best_of_n_complete: bool = True,
) -> bool:
    """P0.4: spend reasoning tokens only when they can change the outcome."""
    if force_final or verifying:
        return False
    mode = (profile.thinking_mode or ("on" if profile.thinking else "off")).lower()
    if mode == "off":
        return False
    if mode == "on":
        return True
    # selective (Balanced default)
    if consecutive_failures > 0:
        return True
    if awaiting_plan_selection or not best_of_n_complete:
        return True
    return turn_index == 0
