from __future__ import annotations

from typing import Any, Iterable

from ..tools.mcp_runtime import MCP
from ..tools.registry import REGISTRY

# Task class → native tools Jarvis should send to the model.
# Mixed / long-horizon tasks keep the full enabled set.
CLASS_TOOLS: dict[str, tuple[str, ...]] = {
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
}

FULL_CLASSES = {"mixed", "long-horizon autonomous", ""}

# Capability names the model may pass to request_tools.
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
}

ESCAPE_TOOL = "request_tools"
MCP_CAPABILITY = "mcp"


def _enabled_native() -> list[str]:
    return [name for name, tool in REGISTRY.tools.items() if tool.enabled and name != ESCAPE_TOOL]


def is_full_exposure(task_class: str, extra: Iterable[str] | None = None) -> bool:
    extras = {item.lower() for item in (extra or [])}
    if "all" in extras:
        return True
    return (task_class or "").strip().lower() in FULL_CLASSES


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


def tool_names_for(task_class: str, extra: Iterable[str] | None = None) -> list[str]:
    extras = normalize_capabilities(extra)
    if is_full_exposure(task_class, extras):
        return _enabled_native()
    wanted = list(CLASS_TOOLS.get((task_class or "").strip().lower(), ()))
    for name in extras:
        if name == MCP_CAPABILITY:
            continue
        if name not in wanted:
            wanted.append(name)
    enabled = set(_enabled_native())
    names = [name for name in wanted if name in enabled]
    if "filesystem" not in names and "filesystem" in enabled:
        names.insert(0, "filesystem")
    return names


def schemas_for(task_class: str, extra: Iterable[str] | None = None) -> list[dict[str, Any]]:
    extras = normalize_capabilities(extra)
    names = tool_names_for(task_class, extras)
    schemas = [REGISTRY.tools[name].schema() for name in names if name in REGISTRY.tools]
    full = is_full_exposure(task_class, extras)
    if not full and ESCAPE_TOOL in REGISTRY.tools and REGISTRY.tools[ESCAPE_TOOL].enabled:
        schemas.append(REGISTRY.tools[ESCAPE_TOOL].schema())
    if not full and "request_capability" in REGISTRY.tools and REGISTRY.tools["request_capability"].enabled:
        if all(item.get("function", {}).get("name") != "request_capability" for item in schemas):
            schemas.append(REGISTRY.tools["request_capability"].schema())
    if full or MCP_CAPABILITY in extras:
        schemas.extend(MCP.openai_tools())
    return schemas


def describe_exposure(task_class: str, extra: Iterable[str] | None = None) -> str:
    names = tool_names_for(task_class, extra)
    full = is_full_exposure(task_class, extra)
    listed = ", ".join(names) or "(none)"
    if full:
        return (
            "Tool exposure: this mixed/long-horizon task receives every enabled tool.\n"
            f"Currently enabled: {listed}."
        )
    return (
        f"Tool exposure: this {task_class or 'task'} is limited to: {listed}.\n"
        "If you need another capability (browser, desktop, office, docker, git, screenshot, "
        "terminal, python, web_fetch, mcp), call request_tools with that name rather than inventing a tool."
    )


def grant_requested_tools(arguments: dict[str, Any]) -> list[str]:
    raw = arguments.get("capabilities") or arguments.get("tools") or arguments.get("capability")
    return normalize_capabilities(raw)
