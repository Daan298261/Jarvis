"""Effective skill permissions = declaration ∩ profile ∩ task ∩ node (no privilege expansion)."""

from __future__ import annotations

from typing import Any, Iterable

from ..policy.inheritance import resolve_capability
from ..policy.levels import AutonomyLevel, can_execute, parse_level
from ..policy.store import get_agent_autonomy_map, get_platform_autonomy_caps, get_platform_policy
from .schema import SkillManifest


class PrivilegeExpansionError(PermissionError):
    pass


def _as_capability_set(values: Iterable[str] | None) -> set[str]:
    out: set[str] = set()
    for item in values or []:
        text = str(item or "").strip()
        if text:
            out.add(text)
    return out


def capabilities_from_tools(tools: Iterable[str]) -> set[str]:
    caps: set[str] = set()
    for tool in tools:
        caps.add(resolve_capability(str(tool), None))
    return caps


def resolve_policy_capability_set(
    *,
    profile_id: str | None = None,
    task_capabilities: Iterable[str] | None = None,
    node_capabilities: Iterable[str] | None = None,
    declared_capabilities: Iterable[str] | None = None,
) -> set[str]:
    """Capabilities allowed by intersecting profile, task, and node policy layers.

    Profile/platform maps often use ``*`` as a blanket autonomy entry. Effective
    permission is computed per declared capability via inheritance — a skill never
    gains authority beyond what ``resolve_effective_level`` permits.
    """
    from ..policy.inheritance import resolve_effective_level

    platform = get_platform_policy()
    default_agent = parse_level(platform.get("default_agent_autonomy"))
    agent_levels = get_agent_autonomy_map(profile_id)
    platform_levels = get_platform_autonomy_caps()

    candidates = _as_capability_set(declared_capabilities)
    if not candidates:
        # Fallback sample when previewing without a skill declaration.
        candidates = {
            "filesystem",
            "filesystem.read",
            "filesystem.write",
            "terminal",
            "browser",
            "python",
            "web_fetch",
            "git",
            "screenshot",
            "mcp",
            "desktop",
            "office",
            "docker",
            "spend",
            "credentials",
            "external",
        }

    profile_caps: set[str] = set()
    for capability in candidates:
        level = resolve_effective_level(
            capability,
            agent_levels,
            platform_levels,
            default_agent=default_agent,
        )
        if can_execute(level):
            profile_caps.add(capability)

    task_set = _as_capability_set(task_capabilities)
    node_set = _as_capability_set(node_capabilities)

    effective = set(profile_caps)
    if task_set:
        effective &= task_set
    if node_set:
        effective &= node_set
    return effective


def compute_effective_capabilities(
    manifest: SkillManifest,
    *,
    profile_id: str | None = None,
    task_capabilities: Iterable[str] | None = None,
    node_capabilities: Iterable[str] | None = None,
    parent_capabilities: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Intersection of skill declaration with parent/profile/task/node policy."""
    declared = _as_capability_set(manifest.required_capabilities) or capabilities_from_tools(manifest.tools)
    tool_caps = capabilities_from_tools(manifest.tools)
    # When required_capabilities is explicit, tools must not imply undeclared authority.
    undeclared_tools = sorted(tool_caps - declared) if manifest.required_capabilities else []

    policy_caps = resolve_policy_capability_set(
        profile_id=profile_id,
        task_capabilities=task_capabilities,
        node_capabilities=node_capabilities,
        declared_capabilities=declared | tool_caps,
    )
    parent_set = _as_capability_set(parent_capabilities)
    if parent_set:
        policy_caps &= parent_set

    effective = sorted(declared & policy_caps)
    denied = sorted(declared - policy_caps)

    return {
        "declared": sorted(declared),
        "policy": sorted(policy_caps),
        "effective": effective,
        "denied": denied,
        "undeclared_tool_capabilities": undeclared_tools,
        "allows_execution": bool(effective) and not denied,
        "privilege_expansion": bool(denied) or bool(undeclared_tools),
    }


def enforce_no_privilege_expansion(
    manifest: SkillManifest,
    *,
    profile_id: str | None = None,
    task_capabilities: Iterable[str] | None = None,
    node_capabilities: Iterable[str] | None = None,
    parent_capabilities: Iterable[str] | None = None,
) -> list[str]:
    result = compute_effective_capabilities(
        manifest,
        profile_id=profile_id,
        task_capabilities=task_capabilities,
        node_capabilities=node_capabilities,
        parent_capabilities=parent_capabilities,
    )
    if result["undeclared_tool_capabilities"]:
        raise PrivilegeExpansionError(
            "skill tools imply undeclared capabilities: "
            + ", ".join(result["undeclared_tool_capabilities"])
        )
    if result["denied"]:
        raise PrivilegeExpansionError(
            "skill declares capabilities outside intersecting policy: " + ", ".join(result["denied"])
        )
    return list(result["effective"])

def autonomy_gate(level: str | AutonomyLevel | None) -> bool:
    return can_execute(parse_level(level))
