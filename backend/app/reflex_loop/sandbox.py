"""Minimal in-ticket sandbox posture (RFC-0151 soft; not a full port).

Fail closed for capabilities that would require real isolation we cannot enforce
here. Tool/model outputs remain untrusted data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import FORBIDDEN_FAST_PATH_KEYS, Operation, ReflexDecision


@dataclass(frozen=True)
class SandboxPosture:
    """Declared limits for a reflex-loop invocation."""

    allow_network: bool = False
    allow_shell: bool = False
    allow_evaluate_js: bool = False
    allow_coordinate_click: bool = False
    max_steps: int = 12
    max_typed_chars: int = 500
    profile: str = "reflex_fast_loop"
    notes: tuple[str, ...] = (
        "Fast path forbids model-generated selectors, coordinates, JS, and shell.",
        "Safety/approval remains on existing permission surfaces outside the decision model.",
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "allow_network": self.allow_network,
            "allow_shell": self.allow_shell,
            "allow_evaluate_js": self.allow_evaluate_js,
            "allow_coordinate_click": self.allow_coordinate_click,
            "max_steps": self.max_steps,
            "max_typed_chars": self.max_typed_chars,
            "profile": self.profile,
            "notes": list(self.notes),
        }


DEFAULT_SANDBOX = SandboxPosture()


@dataclass
class SandboxGateResult:
    ok: bool
    reason: str = ""
    violations: list[str] = field(default_factory=list)


def gate_decision_payload(
    decision: ReflexDecision,
    *,
    extra: dict[str, Any] | None = None,
    posture: SandboxPosture = DEFAULT_SANDBOX,
) -> SandboxGateResult:
    """Refuse decisions that smuggle forbidden fast-path execution material."""
    violations: list[str] = []
    payload = extra or {}
    for key in FORBIDDEN_FAST_PATH_KEYS:
        if key in payload and payload[key] not in (None, "", [], {}):
            violations.append(f"forbidden key {key!r} in decision payload")
    if decision.operation == Operation.BLOCK:
        return SandboxGateResult(True, "blocked by decision — no execute")
    if decision.operation == Operation.DONE:
        return SandboxGateResult(True, "done — no execute")
    # TYPE_TEXT text is validated separately; ensure no shell/js in text_hint early.
    if not posture.allow_shell and any(k in payload for k in ("shell", "command")):
        violations.append("shell execution not permitted in reflex sandbox")
    if not posture.allow_evaluate_js and any(k in payload for k in ("js", "javascript", "script")):
        violations.append("JS evaluate not permitted in reflex sandbox")
    if not posture.allow_coordinate_click and any(k in payload for k in ("x", "y", "coordinate", "coordinates")):
        violations.append("coordinate click not permitted in reflex sandbox")
    if violations:
        return SandboxGateResult(False, "; ".join(violations), violations=violations)
    return SandboxGateResult(True)
