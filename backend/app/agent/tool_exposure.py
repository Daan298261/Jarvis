from __future__ import annotations

from typing import Any, Iterable

from ..tools.mcp_runtime import MCP
from ..tools.registry import REGISTRY
from ..inference.security_gates import gate_is_enabled

# Task class → native tools Jarvis should send to the model.
# Mixed / long-horizon start small; prompt retrieval adds tools for this turn.
CLASS_TOOLS: dict[str, tuple[str, ...]] = {
    "conversation": (),
    "filesystem": ("filesystem", "python"),
    "shell": ("filesystem", "terminal", "python"),
    "system administration": ("filesystem", "terminal", "python", "docker"),
    "software engineering": ("filesystem", "terminal", "python", "git"),
    "research": ("web_fetch", "browser", "filesystem", "python"),
    "browser automation": ("browser", "web_fetch", "filesystem", "screenshot"),
    "windows gui": ("desktop", "screenshot", "filesystem"),
    "office": ("office", "filesystem", "python"),
    "document processing": ("office", "filesystem", "python", "web_fetch"),
    "data processing": ("filesystem", "python", "terminal"),
    "multimodal": ("screenshot", "desktop", "browser", "filesystem"),
    "mixed": ("filesystem", "python"),
    "long-horizon autonomous": ("filesystem", "python", "terminal"),
}

CAPABILITY_ALIASES: dict[str, str] = {
    "web": "web_fetch",
    "http": "web_fetch",
    "fetch": "web_fetch",
    "spreadsheet": "office",
    "excel": "office",
    "word": "office",
    "document": "office",
    "gui": "desktop",
    "windows": "desktop",
    "vision": "screenshot",
    "image": "screenshot",
    "shell": "terminal",
    "powershell": "terminal",
    "bash": "terminal",
    "code": "python",
    "coding": "python",
    "repo": "git",
    "source": "git",
    "openhands": "code_worker",
    "interpreter": "open_interpreter",
    "open-interpreter": "open_interpreter",
    "ufo2": "ufo",
    "hexstrike": "hexstrike_operator",
    "daybreak": "hexstrike_operator",
}

ESCAPE_TOOL = "request_tools"
ESCAPE_TOOLS = ("request_tools", "request_capability")
MCP_CAPABILITY = "mcp"
RESTRICTED_TOOLS = frozenset({"hexstrike_defensive"})


def _enabled_native(security_role: str = "") -> list[str]:
    blue = security_role == "blue-team" and gate_is_enabled("blue-team")
    return [
        name
        for name, tool in REGISTRY.tools.items()
        if tool.enabled
        and name != ESCAPE_TOOL
        and (name not in RESTRICTED_TOOLS or blue)
    ]


def is_full_exposure(task_class: str, extra: Iterable[str] | None = None) -> bool:
    extras = {item.lower() for item in (extra or [])}
    return "all" in extras


def normalize_capabilities(raw: Iterable[str] | str | None) -> list[str]:
    if raw is None:
        return []
    values = [raw] if isinstance(raw, str) else list(raw)
    out: list[str] = []
    seen: set[str] = set()
    native = set(REGISTRY.tools) | {MCP_CAPABILITY, "all"}
    for item in values:
        key = str(item or "").strip().lower()
        if not key:
            continue
        mapped = CAPABILITY_ALIASES.get(key, key)
        if mapped not in native and mapped not in REGISTRY.tools:
            continue
        if mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    return out


def tool_names_for(
    task_class: str,
    extra: Iterable[str] | None = None,
    *,
    security_role: str = "",
    prompt: str | None = None,
) -> list[str]:
    extras = normalize_capabilities(extra)
    if is_full_exposure(task_class, extras):
        return _enabled_native(security_role)
    wanted = list(CLASS_TOOLS.get((task_class or "").strip().lower(), ("filesystem", "python")))
    from .tool_retrieval import suggest_tools_for_prompt

    for name in suggest_tools_for_prompt(prompt or "", security_role=security_role):
        if name not in wanted:
            wanted.append(name)
    for name in extras:
        if name == MCP_CAPABILITY:
            continue
        if name not in wanted:
            wanted.append(name)
    if security_role == "blue-team" and "hexstrike_defensive" not in wanted:
        wanted.append("hexstrike_defensive")
    if "hexstrike_operator" not in wanted and ("hexstrike_operator" in extras or "hexstrike" in {item.lower() for item in extras}):
        wanted.append("hexstrike_operator")
    enabled = set(_enabled_native(security_role))
    names = [name for name in wanted if name in enabled]
    if "filesystem" not in names and "filesystem" in enabled:
        names.insert(0, "filesystem")
    return names


def schemas_for(
    task_class: str,
    extra: Iterable[str] | None = None,
    *,
    security_role: str = "",
    prompt: str | None = None,
) -> list[dict[str, Any]]:
    extras = normalize_capabilities(extra)
    names = tool_names_for(task_class, extras, security_role=security_role, prompt=prompt)
    full = is_full_exposure(task_class, extras)
    schemas: list[dict[str, Any]] = []
    if not full:
        for escape in ESCAPE_TOOLS:
            if escape in REGISTRY.tools and REGISTRY.tools[escape].enabled:
                schemas.append(REGISTRY.tools[escape].schema())
    for name in names:
        if name not in REGISTRY.tools:
            continue
        if any(item.get("function", {}).get("name") == name for item in schemas):
            continue
        schemas.append(REGISTRY.tools[name].schema())
    if full or MCP_CAPABILITY in extras:
        schemas.extend(MCP.openai_tools())
    return schemas


def describe_exposure(
    task_class: str,
    extra: Iterable[str] | None = None,
    *,
    security_role: str = "",
    prompt: str | None = None,
) -> str:
    names = tool_names_for(task_class, extra, security_role=security_role, prompt=prompt)
    full = is_full_exposure(task_class, extra)
    listed = ", ".join(names) or "(none)"
    if full:
        return (
            "Tool exposure: the owner requested every enabled tool for this turn.\n"
            f"Currently enabled: {listed}."
        )
    from .tool_retrieval import suggest_installable_for_prompt

    installable = suggest_installable_for_prompt(prompt or "")
    lines = [
        f"Tool exposure: retrieved for this turn ({task_class or 'task'}): {listed}.",
        "The full tool catalog is not kept in context. If you need another capability "
        "(browser, desktop, office, docker, git, screenshot, terminal, python, web_fetch, mcp), "
        "call request_tools or request_capability with that name rather than inventing a tool.",
    ]
    if installable:
        lines.append(
            "Matching optional workers that are not loaded: "
            + ", ".join(installable)
            + ". Ask the owner to install them or call request_tools with the worker name; do not pretend they are present."
        )
    return "\n".join(lines)


def grant_requested_tools(arguments: dict[str, Any]) -> list[str]:
    raw = arguments.get("capabilities") or arguments.get("tools") or arguments.get("capability")
    return normalize_capabilities(raw)
