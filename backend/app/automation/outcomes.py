from __future__ import annotations

from enum import Enum


class TerminalOutcome(str, Enum):
    """Normalized cross-run outcomes for the automation failure circuit breaker."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    DUPLICATE_SUPPRESSED = "DUPLICATE_SUPPRESSED"
    APPROVAL_WAIT = "APPROVAL_WAIT"
    NO_OP = "NO_OP"

    def increments_failure_counter(self) -> bool:
        return self is TerminalOutcome.FAILURE

    def resets_failure_counter(self) -> bool:
        return self is TerminalOutcome.SUCCESS

    def is_neutral(self) -> bool:
        return not self.increments_failure_counter() and not self.resets_failure_counter()
