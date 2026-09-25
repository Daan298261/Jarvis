from __future__ import annotations

from typing import Any

from ...tools.base import Tool
from .types import EffectClass, ReplayPolicy

# Explicit defaults for tools that touch external systems.
_TOOL_DEFAULTS: dict[str, tuple[EffectClass, ReplayPolicy]] = {
    "web_fetch": (EffectClass.EXTERNAL, ReplayPolicy.KEYED),
    "terminal": (EffectClass.EXTERNAL, ReplayPolicy.AT_MOST_ONCE),
    "browser": (EffectClass.EXTERNAL, ReplayPolicy.KEYED),
    "browser_use": (EffectClass.EXTERNAL, ReplayPolicy.KEYED),
    "git": (EffectClass.EXTERNAL, ReplayPolicy.KEYED),
    "docker": (EffectClass.EXTERNAL, ReplayPolicy.AT_MOST_ONCE),
    "mobile_call": (EffectClass.EXTERNAL, ReplayPolicy.AT_MOST_ONCE),
    "office": (EffectClass.EXTERNAL, ReplayPolicy.AT_MOST_ONCE),
    "desktop": (EffectClass.EXTERNAL, ReplayPolicy.AT_MOST_ONCE),
    "reflex_computer_use": (EffectClass.EXTERNAL, ReplayPolicy.AT_MOST_ONCE),
    "ufo": (EffectClass.EXTERNAL, ReplayPolicy.AT_MOST_ONCE),
    "cua": (EffectClass.EXTERNAL, ReplayPolicy.AT_MOST_ONCE),
    "external_ingest": (EffectClass.EXTERNAL, ReplayPolicy.MANUAL_RECOVERY),
    "hexstrike_operator": (EffectClass.EXTERNAL, ReplayPolicy.MANUAL_RECOVERY),
    "hexstrike_defensive": (EffectClass.EXTERNAL, ReplayPolicy.MANUAL_RECOVERY),
    "code_worker": (EffectClass.EXTERNAL, ReplayPolicy.KEYED),
    "mcp_call": (EffectClass.EXTERNAL, ReplayPolicy.MANUAL_RECOVERY),
}


def resolve_tool_replay(tool_name: str, tool: Tool | None) -> tuple[EffectClass, ReplayPolicy]:
    if tool is not None:
        raw_effect = getattr(tool, "effect_class", None) or "internal"
        raw_policy = getattr(tool, "replay_policy", None)
        try:
            effect = EffectClass(str(raw_effect).lower())
        except ValueError:
            effect = EffectClass.INTERNAL
        if raw_policy:
            try:
                return effect, ReplayPolicy(str(raw_policy).upper())
            except ValueError:
                pass
        defaults = _TOOL_DEFAULTS.get(tool_name)
        if defaults:
            return defaults
        if effect == EffectClass.EXTERNAL:
            return effect, ReplayPolicy.MANUAL_RECOVERY
        return effect, ReplayPolicy.IDEMPOTENT

    if tool_name.startswith("mcp_"):
        return EffectClass.EXTERNAL, ReplayPolicy.MANUAL_RECOVERY
    defaults = _TOOL_DEFAULTS.get(tool_name)
    if defaults:
        return defaults
    return EffectClass.INTERNAL, ReplayPolicy.IDEMPOTENT


def stable_idempotency_key(run_id: str, step_key: str, tool_name: str, arguments: dict[str, Any]) -> str:
    import hashlib
    import json

    payload = json.dumps(
        {"run_id": run_id, "step_key": step_key, "tool": tool_name, "args": arguments},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def may_replay_after_crash(effect: EffectClass, policy: ReplayPolicy) -> bool:
    if effect != EffectClass.EXTERNAL:
        return True
    return policy in {ReplayPolicy.IDEMPOTENT, ReplayPolicy.KEYED}


def ambiguous_after_crash(effect: EffectClass, policy: ReplayPolicy) -> bool:
    if effect != EffectClass.EXTERNAL:
        return False
    return not may_replay_after_crash(effect, policy)
