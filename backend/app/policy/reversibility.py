"""RFC-0031 reversibility / recovery metadata for side-effecting actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from ..tools.base import RiskLevel
from ..tools.safety import classify_command, is_destructive_operation


class ReversibilityClass(str, Enum):
    REVERSIBLE = "REVERSIBLE"
    COMPENSATABLE = "COMPENSATABLE"
    IRREVERSIBLE = "IRREVERSIBLE"
    UNKNOWN = "UNKNOWN"


# Model-controlled confirmation keys that MUST never satisfy a human gate.
FORGERY_CONFIRMATION_KEYS = frozenset(
    {
        "confirmed",
        "confirm",
        "approve",
        "approved",
        "approval",
        "yes",
        "ok",
        "user_confirmed",
        "i_confirm",
        "human_approved",
        "owner_approved",
        "_approved",
    }
)


@dataclass(frozen=True)
class CompensationSpec:
    """How a COMPENSATABLE action can be compensated after the fact."""

    operation: str
    preconditions: list[str] = field(default_factory=list)
    has_external_effects: bool = False
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionEffectMeta:
    """Effect / recovery contract for one proposed side-effecting action."""

    tool_name: str
    action: str
    reversibility: ReversibilityClass
    external_side_effect: bool = False
    financial_effect: bool = False
    credential_effect: bool = False
    destructive_effect: bool = False
    high_consequence: bool = False
    compensation: CompensationSpec | None = None
    snapshot_required: bool = False
    recovery_summary: str = ""
    target: str = ""
    side_effecting: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "action": self.action,
            "reversibility": self.reversibility.value,
            "external_side_effect": self.external_side_effect,
            "financial_effect": self.financial_effect,
            "credential_effect": self.credential_effect,
            "destructive_effect": self.destructive_effect,
            "high_consequence": self.high_consequence,
            "compensation": self.compensation.as_dict() if self.compensation else None,
            "snapshot_required": self.snapshot_required,
            "recovery_summary": self.recovery_summary,
            "target": self.target,
            "side_effecting": self.side_effecting,
        }

    @property
    def safely_reversible(self) -> bool:
        """UNKNOWN is never treated as safely reversible by default."""
        return (
            self.reversibility == ReversibilityClass.REVERSIBLE
            and not self.high_consequence
            and not self.destructive_effect
            and not self.credential_effect
            and not self.financial_effect
        )

    @property
    def compensatable_auto(self) -> bool:
        return (
            self.reversibility == ReversibilityClass.COMPENSATABLE
            and self.compensation is not None
            and bool(self.compensation.operation)
            and not self.compensation.has_external_effects
            and not self.high_consequence
            and not self.credential_effect
            and not self.financial_effect
            and not self.destructive_effect
        )


def strip_forgery_confirmation_args(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Remove model-forgeable confirmation parameters from tool arguments."""
    if not isinstance(arguments, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        if str(key).strip().lower() in FORGERY_CONFIRMATION_KEYS:
            continue
        cleaned[key] = value
    return cleaned


def model_attempted_self_confirm(arguments: dict[str, Any] | None) -> bool:
    if not isinstance(arguments, dict):
        return False
    for key, value in arguments.items():
        if str(key).strip().lower() not in FORGERY_CONFIRMATION_KEYS:
            continue
        if value in (True, 1, "1", "true", "True", "yes", "YES", "approve", "approved", "ok"):
            return True
        if isinstance(value, str) and value.strip().lower() in {"true", "yes", "approve", "approved", "ok", "confirm"}:
            return True
    return False


_READ_ONLY_FS = frozenset(
    {"list", "search", "read", "hash", "stat", "compare", "recent", "snapshots"}
)
_REVERSIBLE_FS = frozenset({"write", "edit", "mkdir", "copy", "move", "rename"})
_COMPENSATABLE_FS = frozenset({"restore", "snapshot"})
_IRREVERSIBLE_FS = frozenset({"delete"})

_CREDENTIAL_HINTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "ssh_key",
    "bearer",
)
_FINANCIAL_HINTS = ("pay", "purchase", "checkout", "transfer", "invoice", "refund", "charge")
_EXTERNAL_TOOLS = frozenset(
    {
        "web_fetch",
        "browser",
        "browser_use",
        "mobile_call",
        "hexstrike_operator",
        "hexstrike_defensive",
        "mcp_call",
        "office",
        "apps",
    }
)


def _target_from_args(arguments: dict[str, Any]) -> str:
    for key in ("path", "destination", "command", "url", "target", "name", "to", "recipient"):
        value = arguments.get(key)
        if value is not None and str(value).strip():
            text = str(value).strip()
            return text[:500]
    return ""


def _args_suggest_credential(arguments: dict[str, Any]) -> bool:
    blob = " ".join(f"{k}={v}" for k, v in arguments.items()).lower()
    return any(hint in blob for hint in _CREDENTIAL_HINTS)


def _args_suggest_financial(arguments: dict[str, Any]) -> bool:
    blob = " ".join(f"{k}={v}" for k, v in arguments.items()).lower()
    return any(hint in blob for hint in _FINANCIAL_HINTS)


def resolve_action_effect(
    tool_name: str,
    *,
    action: str | None = None,
    arguments: dict[str, Any] | None = None,
    risk: RiskLevel | None = None,
) -> ActionEffectMeta:
    """Derive RFC-0031 effect metadata for a proposed tool invocation."""
    args = strip_forgery_confirmation_args(arguments)
    name = (tool_name or "").strip().lower()
    act = str(action or args.get("action") or "").strip().lower()
    target = _target_from_args(args)
    command = str(args.get("command") or "") if args else ""
    destructive = is_destructive_operation(name, args, command or None)
    credential = _args_suggest_credential(args) or name in {"vault_memory"} and act in {
        "reveal",
        "export_secret",
        "set_secret",
    }
    financial = _args_suggest_financial(args)
    external = name in _EXTERNAL_TOOLS or name.startswith("mcp_")

    if risk is None:
        risk = RiskLevel.MEDIUM
        if command:
            risk = classify_command(command)
        if destructive:
            risk = RiskLevel.IRREVERSIBLE

    # Read-only / non-side-effecting shortcuts
    if name == "filesystem" and act in _READ_ONLY_FS:
        return ActionEffectMeta(
            tool_name=name,
            action=act,
            reversibility=ReversibilityClass.REVERSIBLE,
            side_effecting=False,
            target=target,
            recovery_summary="read-only; no undo required",
        )
    if name in {"screenshot", "read_ingress", "internal_references", "request_tools", "request_capability", "verify_code"}:
        return ActionEffectMeta(
            tool_name=name,
            action=act or "invoke",
            reversibility=ReversibilityClass.REVERSIBLE,
            side_effecting=False,
            target=target,
            recovery_summary="observation-only; no undo required",
        )

    if name == "apps":
        if act in {"find", "running", "list"}:
            return ActionEffectMeta(
                tool_name=name,
                action=act,
                reversibility=ReversibilityClass.REVERSIBLE,
                side_effecting=False,
                target=target,
                recovery_summary="local process inspection; no undo required",
            )
        if act in {"open", "launch", "start", ""}:
            return ActionEffectMeta(
                tool_name=name,
                action=act or "open",
                reversibility=ReversibilityClass.COMPENSATABLE,
                external_side_effect=False,
                high_consequence=False,
                target=target,
                recovery_summary="close the launched local application",
                compensation=CompensationSpec(
                    operation="apps.close",
                    preconditions=["process_still_owned_launch"],
                    has_external_effects=False,
                    notes="Local app launch; compensate by closing the process",
                ),
            )
        if act in {"close", "kill", "quit"}:
            return ActionEffectMeta(
                tool_name=name,
                action=act,
                reversibility=ReversibilityClass.UNKNOWN,
                high_consequence=True,
                target=target,
                recovery_summary="closing an app may lose unsaved state — gate required",
            )

    if name == "filesystem":
        if act in _IRREVERSIBLE_FS or destructive:
            return ActionEffectMeta(
                tool_name=name,
                action=act or "delete",
                reversibility=ReversibilityClass.IRREVERSIBLE,
                destructive_effect=True,
                high_consequence=True,
                target=target,
                recovery_summary="filesystem delete cannot be safely undone without a prior snapshot",
            )
        if act in _COMPENSATABLE_FS:
            return ActionEffectMeta(
                tool_name=name,
                action=act,
                reversibility=ReversibilityClass.COMPENSATABLE,
                compensation=CompensationSpec(
                    operation="filesystem.restore_inverse" if act == "restore" else "noop",
                    preconditions=["snapshot_id_valid", "destination_writable"],
                    has_external_effects=False,
                    notes="restore/snapshot compensation is local-only",
                ),
                snapshot_required=act == "restore",
                target=target,
                recovery_summary=f"compensatable filesystem {act}",
            )
        if act in _REVERSIBLE_FS:
            return ActionEffectMeta(
                tool_name=name,
                action=act,
                reversibility=ReversibilityClass.REVERSIBLE,
                snapshot_required=act in {"write", "edit"},
                target=target,
                recovery_summary=f"restore prior file bytes / reverse {act}",
                compensation=CompensationSpec(
                    operation=f"filesystem.undo_{act}",
                    preconditions=["path_matches_postcondition_digest", "backup_or_prior_state_present"],
                    has_external_effects=False,
                ),
            )
        return ActionEffectMeta(
            tool_name=name,
            action=act or "unknown",
            reversibility=ReversibilityClass.UNKNOWN,
            high_consequence=True,
            target=target,
            recovery_summary="unknown filesystem action defaults to gated",
        )

    if name == "terminal":
        if risk == RiskLevel.IRREVERSIBLE or destructive:
            return ActionEffectMeta(
                tool_name=name,
                action=act or "run",
                reversibility=ReversibilityClass.IRREVERSIBLE,
                destructive_effect=True,
                high_consequence=True,
                external_side_effect=True,
                target=target or command[:500],
                recovery_summary="shell destructive command is irreversible",
            )
        return ActionEffectMeta(
            tool_name=name,
            action=act or "run",
            reversibility=ReversibilityClass.UNKNOWN,
            high_consequence=True,
            external_side_effect=True,
            target=target or command[:500],
            recovery_summary="shell effects are UNKNOWN unless proven reversible",
        )

    if credential:
        return ActionEffectMeta(
            tool_name=name,
            action=act or "invoke",
            reversibility=ReversibilityClass.IRREVERSIBLE,
            credential_effect=True,
            high_consequence=True,
            external_side_effect=external,
            target=target,
            recovery_summary="credential-bearing actions require an ApprovalGrant",
        )

    if financial:
        return ActionEffectMeta(
            tool_name=name,
            action=act or "invoke",
            reversibility=ReversibilityClass.IRREVERSIBLE,
            financial_effect=True,
            high_consequence=True,
            external_side_effect=True,
            target=target,
            recovery_summary="financial effects require an ApprovalGrant",
        )

    if name in {"settings", "config"} or (name == "chat_projects" and act in {"update", "write", "delete"}):
        if act in {"delete", "reset"}:
            return ActionEffectMeta(
                tool_name=name,
                action=act,
                reversibility=ReversibilityClass.IRREVERSIBLE,
                high_consequence=True,
                target=target,
                recovery_summary="destructive settings change",
            )
        return ActionEffectMeta(
            tool_name=name,
            action=act or "update",
            reversibility=ReversibilityClass.REVERSIBLE,
            target=target,
            recovery_summary="restore previous settings value",
            compensation=CompensationSpec(
                operation="settings.restore_previous",
                preconditions=["previous_value_recorded"],
                has_external_effects=False,
            ),
        )

    if external:
        return ActionEffectMeta(
            tool_name=name,
            action=act or "invoke",
            reversibility=ReversibilityClass.UNKNOWN,
            external_side_effect=True,
            high_consequence=True,
            target=target,
            recovery_summary="external / network effects default to UNKNOWN and require a human gate",
        )

    # Default for other mutating tools: UNKNOWN — never auto-treat as reversible.
    tool_risk_irreversible = risk == RiskLevel.IRREVERSIBLE
    return ActionEffectMeta(
        tool_name=name,
        action=act or "invoke",
        reversibility=(
            ReversibilityClass.IRREVERSIBLE
            if tool_risk_irreversible or destructive
            else ReversibilityClass.UNKNOWN
        ),
        destructive_effect=destructive or tool_risk_irreversible,
        high_consequence=True,
        external_side_effect=external,
        target=target,
        recovery_summary="default UNKNOWN/IRREVERSIBLE — human gate required",
    )
