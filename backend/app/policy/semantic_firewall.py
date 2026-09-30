"""Thin RFC-0027 SemanticActionFirewall hook used by RFC-0031 ordering.

Full RFC-0027 privacy-gateway / redaction remains a separate ticket. This module
provides the execution-boundary outcomes (ALLOW / REDACT / REQUIRE_APPROVAL /
BLOCK) so reversibility handling can never convert a firewall deny into allow.
Deterministic rules only make execution stricter than ordinary authorization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .reversibility import ActionEffectMeta, ReversibilityClass, strip_forgery_confirmation_args


class FirewallOutcome(str, Enum):
    ALLOW = "ALLOW"
    REDACT = "REDACT"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class FirewallDecision:
    outcome: FirewallOutcome
    reason_codes: list[str] = field(default_factory=list)
    explanation: str = ""
    redacted_arguments: dict[str, Any] | None = None
    evaluator_version: str = "rfc0027-hook-v1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "reason_codes": list(self.reason_codes),
            "explanation": self.explanation,
            "redacted_arguments": self.redacted_arguments,
            "evaluator_version": self.evaluator_version,
        }

    @property
    def blocks(self) -> bool:
        return self.outcome == FirewallOutcome.BLOCK

    @property
    def requires_approval(self) -> bool:
        return self.outcome == FirewallOutcome.REQUIRE_APPROVAL


_SECRET_PATTERNS = (
    "begin private key",
    "aws_secret_access_key",
    "xoxb-",
    "ghp_",
    "sk-live-",
)


def evaluate_semantic_firewall(
    *,
    tool_name: str,
    action: str | None,
    arguments: dict[str, Any] | None,
    effect: ActionEffectMeta,
    task_id: str | None = None,
    goal_hint: str | None = None,
) -> FirewallDecision:
    """Evaluate proposed action. May only tighten policy — never grant new authority."""
    del task_id, goal_hint  # reserved for fuller RFC-0027 context wiring
    args = strip_forgery_confirmation_args(arguments)
    codes: list[str] = []
    blob = " ".join(f"{k}={v}" for k, v in args.items()).lower()

    if any(pat in blob for pat in _SECRET_PATTERNS):
        return FirewallDecision(
            outcome=FirewallOutcome.BLOCK,
            reason_codes=["secret_exfiltration_pattern"],
            explanation="Proposed action appears to move raw secrets across a trust boundary.",
        )

    if effect.credential_effect:
        codes.append("credential_effect")
        return FirewallDecision(
            outcome=FirewallOutcome.REQUIRE_APPROVAL,
            reason_codes=codes,
            explanation="Credential-bearing side effect requires explicit human approval.",
        )

    if effect.financial_effect:
        codes.append("financial_effect")
        return FirewallDecision(
            outcome=FirewallOutcome.REQUIRE_APPROVAL,
            reason_codes=codes,
            explanation="Financial side effect requires explicit human approval.",
        )

    if effect.destructive_effect or effect.reversibility == ReversibilityClass.IRREVERSIBLE:
        codes.append("destructive_or_irreversible")
        return FirewallDecision(
            outcome=FirewallOutcome.REQUIRE_APPROVAL,
            reason_codes=codes,
            explanation="Destructive or irreversible effect requires explicit human approval.",
        )

    if effect.external_side_effect and effect.reversibility in {
        ReversibilityClass.UNKNOWN,
        ReversibilityClass.IRREVERSIBLE,
    }:
        codes.append("external_unknown")
        return FirewallDecision(
            outcome=FirewallOutcome.REQUIRE_APPROVAL,
            reason_codes=codes,
            explanation="External / network effect with unknown recovery requires approval.",
        )

    if effect.reversibility == ReversibilityClass.UNKNOWN and effect.side_effecting:
        codes.append("unknown_reversibility")
        return FirewallDecision(
            outcome=FirewallOutcome.REQUIRE_APPROVAL,
            reason_codes=codes,
            explanation="UNKNOWN reversibility is never treated as safely auto-executable.",
        )

    if not effect.side_effecting:
        return FirewallDecision(
            outcome=FirewallOutcome.ALLOW,
            reason_codes=["read_only"],
            explanation="Observation-only action.",
        )

    return FirewallDecision(
        outcome=FirewallOutcome.ALLOW,
        reason_codes=["low_risk_allow"],
        explanation="Deterministic firewall allows low-risk side effect.",
    )
