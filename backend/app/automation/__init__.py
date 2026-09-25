"""Durable automation execution helpers (RFC-0071 circuit breaker)."""

from .breaker import (
    BREAKER_ACTIVE,
    BREAKER_DEGRADED,
    BREAKER_DISABLED_BY_FAILURE,
    AutomationBreakerError,
    admit_automatic_trigger,
    bind_run_to_task,
    ensure_automation,
    finalize_run_outcome,
    get_automation_breaker,
    list_automation_breakers,
    normalize_task_terminal,
    reenable_automation,
    reset_automation_breaker_store,
    set_failure_threshold,
)
from .outcomes import TerminalOutcome

__all__ = [
    "BREAKER_ACTIVE",
    "BREAKER_DEGRADED",
    "BREAKER_DISABLED_BY_FAILURE",
    "AutomationBreakerError",
    "TerminalOutcome",
    "admit_automatic_trigger",
    "bind_run_to_task",
    "ensure_automation",
    "finalize_run_outcome",
    "get_automation_breaker",
    "list_automation_breakers",
    "normalize_task_terminal",
    "reenable_automation",
    "reset_automation_breaker_store",
    "set_failure_threshold",
]
