"""RFC-0197: managed cyber tasks must execute tools, not narrate completion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .planning import is_defensive_operator_prompt
from ..security.security_agents import is_security_role

_CYBER_TOOLS = frozenset({"hexstrike_operator", "hexstrike_defensive"})

_CYBER_ACTION_MARKERS = (
    "assess",
    "assessment",
    "harden",
    "inventory",
    "operate",
    "probe",
    "purple",
    "red team",
    "blue team",
    "security agent",
    "hexstrike",
    "daybreak",
    "scope",
    "attested target",
    "run defense",
    "defensive",
    "trivy",
    "nmap",
    "container scan",
)


@dataclass
class CyberExecutionEvidence:
    requires_tool_execution: bool = False
    tool_succeeded: bool = False
    job_succeeded: bool = False
    tool_log: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requires_tool_execution": self.requires_tool_execution,
            "tool_succeeded": self.tool_succeeded,
            "job_succeeded": self.job_succeeded,
            "tool_log": list(self.tool_log),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "CyberExecutionEvidence":
        if not isinstance(raw, dict):
            return cls()
        log = raw.get("tool_log") or []
        if not isinstance(log, list):
            log = []
        return cls(
            requires_tool_execution=bool(raw.get("requires_tool_execution")),
            tool_succeeded=bool(raw.get("tool_succeeded")),
            job_succeeded=bool(raw.get("job_succeeded")),
            tool_log=[item for item in log if isinstance(item, dict)],
        )


def is_cyber_action_prompt(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    if is_defensive_operator_prompt(lowered):
        return True
    return any(marker in lowered for marker in _CYBER_ACTION_MARKERS)


def applies_cyber_tool_execution(security_role: str, prompt: str = "") -> bool:
    if not is_security_role(security_role):
        return False
    # Security-agent managed tasks always require tool evidence when the owner
    # asked for an action; plain social chat on a security-role thread may skip.
    if not (prompt or "").strip():
        return True
    if is_cyber_action_prompt(prompt):
        return True
    # Role set via API implies cyber agent mode for the task.
    return True


def init_cyber_execution(working: Any, *, requires_tool_execution: bool = True) -> None:
    working.requires_tool_execution = bool(requires_tool_execution)
    working.cyber_execution = CyberExecutionEvidence(
        requires_tool_execution=bool(requires_tool_execution)
    ).as_dict()


def evidence_from_working(working: Any) -> CyberExecutionEvidence:
    ev = CyberExecutionEvidence.from_dict(getattr(working, "cyber_execution", None))
    if getattr(working, "requires_tool_execution", False):
        ev.requires_tool_execution = True
    return ev


def note_cyber_tool(
    working: Any,
    name: str,
    arguments: dict[str, Any],
    observation: str,
    *,
    success: bool,
) -> None:
    if not getattr(working, "requires_tool_execution", False) and not is_security_role(
        getattr(working, "security_role", "") or ""
    ):
        return
    ev = evidence_from_working(working)
    entry = {
        "tool": name,
        "success": bool(success),
        "arguments": {k: arguments.get(k) for k in list(arguments or {})[:12]},
        "observation": (observation or "")[:1200],
    }
    ev.tool_log = (ev.tool_log + [entry])[-40:]
    if success and name in _CYBER_TOOLS:
        ev.tool_succeeded = True
        lowered = (observation or "").lower()
        if '"status": "succeeded"' in lowered or "status': 'succeeded'" in lowered or "succeeded" in lowered:
            ev.job_succeeded = True
        elif "job" in lowered and "fail" not in lowered:
            ev.job_succeeded = True
        else:
            # A successful cyber tool call counts as job evidence for the verify hook.
            ev.job_succeeded = True
    working.cyber_execution = ev.as_dict()
    working.requires_tool_execution = ev.requires_tool_execution


def cyber_execution_satisfied(working: Any) -> bool:
    ev = evidence_from_working(working)
    if not ev.requires_tool_execution and not getattr(working, "requires_tool_execution", False):
        return True
    return bool(ev.tool_succeeded or ev.job_succeeded)


def cyber_completion_blocked_message(working: Any) -> str:
    return (
        "RFC-0197: this cyber security-agent task cannot complete from assistant text alone.\n"
        "requires_tool_execution=true — call hexstrike_operator / hexstrike_defensive "
        "(or the active phase tool set) against an owner-attested registry target, "
        "then finish only after a succeeded tool/job record."
    )
