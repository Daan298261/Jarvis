from __future__ import annotations

from enum import Enum


class OperationType(str, Enum):
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    INTERNAL = "internal"
    PARK = "park"


class EffectClass(str, Enum):
    NONE = "none"
    INTERNAL = "internal"
    EXTERNAL = "external"


class ReplayPolicy(str, Enum):
    IDEMPOTENT = "IDEMPOTENT"
    KEYED = "KEYED"
    AT_MOST_ONCE = "AT_MOST_ONCE"
    MANUAL_RECOVERY = "MANUAL_RECOVERY"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    AMBIGUOUS_EFFECT = "AMBIGUOUS_EFFECT"
    PARKED = "parked"
    SKIPPED = "skipped"


class AttemptStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"


class ParkKind(str, Enum):
    APPROVAL = "approval"
    TIMER = "timer"
    RATE_LIMIT = "rate_limit"
    CALLBACK = "callback"


class CrashBoundary(str, Enum):
    BEFORE_EXECUTE = "before_execute"
    AFTER_EXECUTE_BEFORE_COMMIT = "after_execute_before_commit"
    AFTER_COMMIT = "after_commit"


TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})
