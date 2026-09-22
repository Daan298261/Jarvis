from __future__ import annotations

from typing import Any, Iterable

from ..licensing.entitlements import HEXSTRIKE_ACCESS_BLUE, HEXSTRIKE_ACCESS_FULL, hexstrike_access_mode
from ..tools.mcp_runtime import MCP
from ..tools.registry import REGISTRY

# Task class → native tools Jarvis should send to the model.
# Mixed / long-horizon start small; prompt retrieval adds tools for this turn.
CLASS_TOOLS: dict[str, tuple[str, ...]] = {
    "conversation": (),
    "filesystem": ("filesystem", "python"),
    "shell": ("filesystem", "terminal", "python"),
    "system administration": ("filesystem", "terminal", "python", "desktop", "screenshot", "docker"),
    "software engineering": ("filesystem", "terminal", "python", "git"),
    "research": ("web_fetch", "browser", "filesystem", "python", "mcp_call"),
    "browser automation": ("browser", "web_fetch", "filesystem", "screenshot"),
    "windows gui": ("desktop", "screenshot", "filesystem", "terminal"),
    "office": ("office", "filesystem", "python"),
    "document processing": ("office", "filesystem", "python", "web_fetch"),
    "data processing": ("filesystem", "python", "terminal"),
    "multimodal": ("screenshot", "desktop", "browser", "filesystem"),
    "mixed": ("filesystem", "python", "terminal", "desktop", "screenshot", "chat_projects", "mcp_call"),
    "long-horizon autonomous": (
        "filesystem",
        "python",
        "terminal",
        "desktop",
        "screenshot",
        "git",
        "browser",
        "web_fetch",
        "office",
        "mcp_call",
        "vault_memory",
    ),
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
    "gmail": "mcp_call",
    "email": "mcp_call",
    "whatsapp": "mcp_call",
    "imap": "mcp_call",
    "smtp": "mcp_call",
}

ESCAPE_TOOL = "request_tools"
ESCAPE_TOOLS = ("request_tools", "request_capability")
MCP_CAPABILITY = "mcp"
RESTRICTED_TOOLS = frozenset({"hexstrike_defensive", "hexstrike_operator"})


def _enabled_native(security_role: str = "") -> list[str]:
    mode = hexstrike_access_mode()
    names: list[str] = []
    for name, tool in REGISTRY.tools.items():
        if not tool.enabled or name == ESCAPE_TOOL:
            continue
        if name == "hexstrike_defensive":
            if mode in {HEXSTRIKE_ACCESS_BLUE, HEXSTRIKE_ACCESS_FULL}:
                names.append(name)
            continue
        if name == "hexstrike_operator":
            if mode == HEXSTRIKE_ACCESS_FULL:
                names.append(name)
            continue
        names.append(name)
    return names


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


def infer_needs_tools(task_class: str, prompt: str | None, *, explicit: bool | None = None) -> bool:
    """RFC-0122: plain Q&A should not ship tool schemas."""
    if explicit is not None:
        return bool(explicit)
    from .ingress_gate import heuristic_needs_tools

    hint = heuristic_needs_tools(prompt or "", task_class)
    if hint is not None:
        return bool(hint)
    if is_full_exposure(task_class, ()):
        return True
    if (task_class or "").strip().lower() == "conversation":
        return False
    return True


def tool_names_for(
    task_class: str,
    extra: Iterable[str] | None = None,
    *,
    security_role: str = "",
    prompt: str | None = None,
    needs_tools: bool | None = None,
) -> list[str]:
    extras = normalize_capabilities(extra)
    if not infer_needs_tools(task_class, prompt, explicit=needs_tools):
        return []
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
    enabled = set(_enabled_native(security_role))
    names = [name for name in wanted if name in enabled]
    if MCP_CAPABILITY in extras and "mcp_call" in enabled and "mcp_call" not in names:
        names.append("mcp_call")
    if MCP.has_tools() and "mcp_call" in enabled and "mcp_call" not in names:
        names.append("mcp_call")
    if (task_class or "").strip().lower() != "conversation":
        if "filesystem" not in names and "filesystem" in enabled:
            names.insert(0, "filesystem")
    return names


def schemas_for(
    task_class: str,
    extra: Iterable[str] | None = None,
    *,
    security_role: str = "",
    prompt: str | None = None,
    needs_tools: bool | None = None,
) -> list[dict[str, Any]]:
    extras = normalize_capabilities(extra)
    if not infer_needs_tools(task_class, prompt, explicit=needs_tools):
        schemas: list[dict[str, Any]] = []
        if "request_capability" in REGISTRY.tools and REGISTRY.tools["request_capability"].enabled:
            schemas.append(REGISTRY.tools["request_capability"].schema())
        return schemas
    names = tool_names_for(
        task_class,
        extras,
        security_role=security_role,
        prompt=prompt,
        needs_tools=needs_tools,
    )
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
    attach_mcp = full or MCP_CAPABILITY in extras or MCP.has_tools()
    if attach_mcp:
        seen = {item.get("function", {}).get("name") for item in schemas}
        for item in MCP.openai_tools():
            fname = item.get("function", {}).get("name")
            if fname in seen:
                continue
            schemas.append(item)
            seen.add(fname)
        if "mcp_call" not in seen and "mcp_call" in REGISTRY.tools and REGISTRY.tools["mcp_call"].enabled:
            schemas.append(REGISTRY.tools["mcp_call"].schema())
    return schemas


def describe_exposure(
    task_class: str,
    extra: Iterable[str] | None = None,
    *,
    security_role: str = "",
    prompt: str | None = None,
    needs_tools: bool | None = None,
) -> str:
    if not infer_needs_tools(task_class, prompt, explicit=needs_tools):
        return "Tool exposure: none for this factual Q&A turn (RFC-0122). Call request_capability only if you must opt into tools."
    names = tool_names_for(
        task_class,
        extra,
        security_role=security_role,
        prompt=prompt,
        needs_tools=needs_tools,
    )
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
    if MCP.has_tools():
        keys = ", ".join(MCP.connected_keys()[:24])
        lines.append(f"Connected MCP tools are attached and must be used when they match the job: {keys}.")
    return "\n".join(lines)


def grant_requested_tools(arguments: dict[str, Any]) -> list[str]:
    raw = arguments.get("capabilities") or arguments.get("tools") or arguments.get("capability")
    return normalize_capabilities(raw)
