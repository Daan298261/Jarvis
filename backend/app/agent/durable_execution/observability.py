from __future__ import annotations

"""RFC-0029 observability hooks for RFC-0026 (D1) to wire into execution_status / tasks API.

This module is intentionally separate from execution_status.py and api/tasks.py.
D1 can import these helpers when projecting phases or task detail payloads.
"""

from typing import Any

from .recovery import recover_run_state
from .types import StepStatus

# TaskEvent.kind values emitted by the durable runner (persisted on task_events).
DURABLE_TASK_EVENT_KINDS = frozenset(
    {
        "durable_step",
        "step_reused",
        "ambiguous_effect",
        "durable_recovery",
    }
)

# Suggested ExecutionPhase mapping when D1 extends phase_for_event (RFC-0026).
SUGGESTED_PHASE_FOR_EVENT_KIND: dict[str, str] = {
    "durable_step": "EXECUTING",
    "step_reused": "RECOVERING",
    "ambiguous_effect": "RECOVERING",
    "durable_recovery": "RECOVERING",
}


async def durable_execution_snapshot(run_id: str) -> dict[str, Any]:
    """Read-only recovery snapshot from persisted ExecutionStep rows."""
    return await recover_run_state(run_id)


def step_status_indicators(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compact flags for portal/task detail without coupling to tasks.py."""
    if not snapshot.get("recoverable"):
        return {
            "recoverable": False,
            "reason": snapshot.get("reason", ""),
            "has_ambiguous_effect": False,
            "has_parked_waits": False,
            "reused_step_count": 0,
        }
    ambiguous = snapshot.get("ambiguous_step_keys") or []
    parked = snapshot.get("parked_step_keys") or []
    reusable = snapshot.get("reusable_step_keys") or []
    return {
        "recoverable": True,
        "reason": "",
        "has_ambiguous_effect": bool(ambiguous),
        "has_parked_waits": bool(parked),
        "reused_step_count": len(reusable),
        "ambiguous_step_keys": list(ambiguous),
        "parked_step_keys": list(parked),
        "pending_step_keys": list(snapshot.get("pending_step_keys") or []),
    }


def is_terminal_step_status(status: str) -> bool:
    return status in {
        StepStatus.COMPLETED.value,
        StepStatus.FAILED.value,
        StepStatus.AMBIGUOUS_EFFECT.value,
        StepStatus.SKIPPED.value,
    }
