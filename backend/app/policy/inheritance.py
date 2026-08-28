from __future__ import annotations

from .levels import DEFAULT_AGENT_LEVEL, DEFAULT_PLATFORM_CAP, AutonomyLevel, min_level, parse_level

# Parent links for capability inheritance (child -> parent).
CAPABILITY_PARENTS: dict[str, str] = {
    "filesystem.read": "filesystem",
    "filesystem.write": "filesystem",
    "terminal.exec": "terminal",
    "browser.navigate": "browser",
    "git.push": "git",
    "git.commit": "git",
    "external.send": "external",
    "spend.purchase": "spend",
    "credentials.change": "credentials",
    "filesystem": "*",
    "terminal": "*",
    "browser": "*",
    "git": "*",
    "python": "*",
    "docker": "*",
    "desktop": "*",
    "office": "*",
    "screenshot": "*",
    "web_fetch": "*",
    "mcp": "*",
    "external": "*",
    "spend": "*",
    "credentials": "*",
}

TOOL_CAPABILITY_MAP: dict[str, str] = {
    "filesystem": "filesystem",
    "terminal": "terminal",
    "browser": "browser",
    "browser_use": "browser",
    "git": "git",
    "python": "python",
    "docker": "docker",
    "desktop": "desktop",
    "office": "office",
    "screenshot": "screenshot",
    "web_fetch": "web_fetch",
    "mcp": "mcp",
    "code_worker": "python",
    "interpreter": "python",
    "verify_code": "filesystem.read",
    "request_capability": "filesystem.read",
    "request_tools": "filesystem.read",
}

ACTION_CAPABILITY_SUFFIX: dict[str, dict[str, str]] = {
    "filesystem": {
        "read": "filesystem.read",
        "list": "filesystem.read",
        "write": "filesystem.write",
        "delete": "filesystem.write",
        "mkdir": "filesystem.write",
    },
    "terminal": {"exec": "terminal.exec", "run": "terminal.exec"},
    "browser": {"navigate": "browser.navigate", "click": "browser.navigate"},
    "git": {"push": "git.push", "commit": "git.commit"},
}


def capability_chain(capability: str) -> list[str]:
    chain: list[str] = []
    current = capability
    seen: set[str] = set()
    while current and current not in seen:
        chain.append(current)
        seen.add(current)
        current = CAPABILITY_PARENTS.get(current, "*") if current != "*" else ""
    if "*" not in seen:
        chain.append("*")
    return chain


def resolve_capability(tool_name: str, action: str | None = None) -> str:
    base = TOOL_CAPABILITY_MAP.get(tool_name, tool_name)
    if action:
        suffix_map = ACTION_CAPABILITY_SUFFIX.get(base, {})
        mapped = suffix_map.get(action.strip().lower())
        if mapped:
            return mapped
        return f"{base}.{action.strip().lower()}"
    return base


def lookup_level(capability: str, levels: dict[str, str], *, default: AutonomyLevel) -> AutonomyLevel:
    for key in capability_chain(capability):
        raw = levels.get(key)
        if raw:
            return parse_level(raw, default=default)
    return default


def resolve_effective_level(
    capability: str,
    agent_levels: dict[str, str],
    platform_caps: dict[str, str],
    *,
    default_agent: AutonomyLevel = DEFAULT_AGENT_LEVEL,
    default_platform: AutonomyLevel = DEFAULT_PLATFORM_CAP,
) -> AutonomyLevel:
    agent_level = lookup_level(capability, agent_levels, default=default_agent)
    platform_level = lookup_level(capability, platform_caps, default=default_platform)
    return min_level(agent_level, platform_level)
