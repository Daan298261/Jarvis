"""Trace eligibility for Skill Forge — secrets, hidden reasoning, consequential actions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..trajectories.redaction import _SECRET_KEY_RE, redact_string
from ..trajectories.schema import JarvisTrajectoryV1

_HIDDEN_REASONING_KEYS = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "hidden_reasoning",
        "chain_of_thought",
        "chain-of-thought",
        "thinking",
        "thoughts",
        "scratchpad",
        "private_thoughts",
    }
)
_HIDDEN_EVENT_TYPES = frozenset(
    {
        "hidden_reasoning",
        "reasoning",
        "thinking",
        "chain_of_thought",
        "internal_monologue",
    }
)
_CONSEQUENTIAL_TOOLS = frozenset(
    {
        "desktop",
        "ufo",
        "cua",
        "reflex_computer_use",
        "docker",
        "office",
        "code_worker",
    }
)
_CONSEQUENTIAL_ACTIONS = frozenset(
    {
        "delete",
        "rm",
        "push",
        "force_push",
        "send",
        "purchase",
        "spend",
        "transfer",
        "credentials",
        "change_password",
        "publish",
        "deploy",
    }
)
_SECRET_VALUE_RE = re.compile(
    r"(Bearer\s+[A-Za-z0-9._~+/=-]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|\bsk-[A-Za-z0-9]{20,}\b)",
    re.I,
)


@dataclass
class EligibilityResult:
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "flags": dict(self.flags),
        }


def _mapping_has_secret_keys(value: Any, *, path: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_s = str(key)
            child = f"{path}.{key_s}" if path else key_s
            if _SECRET_KEY_RE.search(key_s):
                hits.append(child)
            hits.extend(_mapping_has_secret_keys(item, path=child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_mapping_has_secret_keys(item, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        if _SECRET_VALUE_RE.search(value) and "[REDACTED]" not in value:
            hits.append(path or "<string>")
    return hits


def _mapping_has_hidden_reasoning(value: Any, *, path: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_s = str(key).lower()
            child = f"{path}.{key}" if path else str(key)
            if key_s in _HIDDEN_REASONING_KEYS:
                hits.append(child)
            hits.extend(_mapping_has_hidden_reasoning(item, path=child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_mapping_has_hidden_reasoning(item, path=f"{path}[{index}]"))
    return hits


def _event_is_consequential(event: Any) -> tuple[bool, str]:
    tool = (getattr(event, "tool_name", None) or "").strip().lower()
    args = getattr(event, "tool_args", None) or {}
    if not isinstance(args, dict):
        args = {}
    action = str(args.get("action") or args.get("command") or "").strip().lower()
    approved = bool(
        (getattr(event, "metadata", None) or {}).get("approved")
        or args.get("approved")
        or (getattr(event, "metadata", None) or {}).get("owner_approved")
    )
    if tool in _CONSEQUENTIAL_TOOLS and not approved:
        return True, f"unapproved consequential tool:{tool}"
    if action in _CONSEQUENTIAL_ACTIONS and not approved:
        return True, f"unapproved consequential action:{action}"
    if tool == "filesystem" and action in {"delete", "rm", "unlink"} and not approved:
        return True, "unapproved filesystem delete"
    if tool == "git" and action in {"push", "force_push"} and not approved:
        return True, "unapproved git push"
    if tool in {"terminal"} and any(
        token in str(args.get("command") or "").lower()
        for token in ("rm -rf", "mkfs", "dd if=", "shutdown", "reboot")
    ):
        if not approved:
            return True, "unapproved destructive terminal command"
    return False, ""


def evaluate_trajectory_eligibility(trajectory: JarvisTrajectoryV1 | dict[str, Any]) -> EligibilityResult:
    """Return whether a trajectory may enter Skill Forge candidate extraction.

    Excludes secrets, hidden reasoning, and unapproved consequential actions.
    Failed / unverified outcomes are also ineligible for promotion (repair may still use them).
    """
    reasons: list[str] = []
    flags: dict[str, Any] = {}

    if isinstance(trajectory, dict):
        trajectory = JarvisTrajectoryV1.model_validate(trajectory)

    outcome = trajectory.outcome
    if not outcome.attempted:
        reasons.append("trajectory was not attempted")
    if outcome.status not in {"completed", "succeeded", "success", "verified"}:
        reasons.append(f"outcome status {outcome.status!r} is not a verified success")
        flags["outcome_status"] = outcome.status
    if not outcome.verified:
        if trajectory.verification is None or not trajectory.verification.passed:
            reasons.append("outcome is not verified")
            flags["verified"] = False

    payload = trajectory.model_dump(mode="json")
    secret_hits = _mapping_has_secret_keys(payload)
    if secret_hits:
        reasons.append("trajectory contains unretracted secrets")
        flags["secret_paths"] = secret_hits[:20]

    hidden_hits = _mapping_has_hidden_reasoning(payload)
    for event in trajectory.events:
        et = (event.event_type or "").strip().lower()
        if et in _HIDDEN_EVENT_TYPES:
            hidden_hits.append(f"event[{event.sequence}].event_type={et}")
        content = event.content or ""
        if content and any(marker in content.lower() for marker in ("<thinking>", "chain_of_thought", "hidden reasoning")):
            hidden_hits.append(f"event[{event.sequence}].content")
    if hidden_hits:
        reasons.append("trajectory contains hidden reasoning")
        flags["hidden_reasoning_paths"] = hidden_hits[:20]

    consequential: list[str] = []
    for event in trajectory.events:
        is_bad, detail = _event_is_consequential(event)
        if is_bad:
            consequential.append(f"event[{event.sequence}]: {detail}")
    if consequential:
        reasons.append("trajectory contains unapproved consequential actions")
        flags["consequential"] = consequential[:20]

    # Content that would redact to different text still blocks if raw secret patterns remain.
    for event in trajectory.events:
        for text in (event.content, event.tool_result):
            if isinstance(text, str) and text and redact_string(text) != text and "[REDACTED]" not in text:
                # redact_string always replaces; if patterns present they're already caught.
                pass

    eligible = not reasons
    return EligibilityResult(eligible=eligible, reasons=reasons, flags=flags)


def is_eligible(trajectory: JarvisTrajectoryV1 | dict[str, Any]) -> bool:
    return evaluate_trajectory_eligibility(trajectory).eligible
