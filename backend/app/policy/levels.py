from __future__ import annotations

from enum import Enum


class AutonomyLevel(str, Enum):
    L0_OBSERVE = "L0_OBSERVE"
    L1_SUGGEST = "L1_SUGGEST"
    L2_EXECUTE_SAFE = "L2_EXECUTE_SAFE"
    L3_EXECUTE_WITH_GATES = "L3_EXECUTE_WITH_GATES"
    L4_AUTONOMOUS = "L4_AUTONOMOUS"
    L5_OPERATOR = "L5_OPERATOR"


LEVEL_RANK: dict[AutonomyLevel, int] = {
    AutonomyLevel.L0_OBSERVE: 0,
    AutonomyLevel.L1_SUGGEST: 1,
    AutonomyLevel.L2_EXECUTE_SAFE: 2,
    AutonomyLevel.L3_EXECUTE_WITH_GATES: 3,
    AutonomyLevel.L4_AUTONOMOUS: 4,
    AutonomyLevel.L5_OPERATOR: 5,
}


DEFAULT_AGENT_LEVEL = AutonomyLevel.L2_EXECUTE_SAFE
DEFAULT_PLATFORM_CAP = AutonomyLevel.L5_OPERATOR


def parse_level(value: str | AutonomyLevel | None, *, default: AutonomyLevel = DEFAULT_AGENT_LEVEL) -> AutonomyLevel:
    if isinstance(value, AutonomyLevel):
        return value
    if not value:
        return default
    text = str(value).strip().upper()
    for level in AutonomyLevel:
        if level.value == text or level.name == text:
            return level
    raise ValueError(f"unknown autonomy level: {value}")


def min_level(a: AutonomyLevel, b: AutonomyLevel) -> AutonomyLevel:
    return a if LEVEL_RANK[a] <= LEVEL_RANK[b] else b


def max_level(a: AutonomyLevel, b: AutonomyLevel) -> AutonomyLevel:
    return a if LEVEL_RANK[a] >= LEVEL_RANK[b] else b


def can_execute(level: AutonomyLevel) -> bool:
    return LEVEL_RANK[level] >= LEVEL_RANK[AutonomyLevel.L2_EXECUTE_SAFE]
