from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import data_dir
from ..swarm.budgets import acquire_lease, get_node_budget

_lock = threading.RLock()

PROACTIVITY_DISABLED = "DISABLED"
PROACTIVITY_SUGGEST_ONLY = "SUGGEST_ONLY"
PROACTIVITY_CREATE_TASKS = "CREATE_TASKS"
PROACTIVITY_EXECUTE_WITHIN_POLICY = "EXECUTE_WITHIN_POLICY"

PROACTIVITY_MODES = (
    PROACTIVITY_DISABLED,
    PROACTIVITY_SUGGEST_ONLY,
    PROACTIVITY_CREATE_TASKS,
    PROACTIVITY_EXECUTE_WITHIN_POLICY,
)

PROACTIVE_STATUS_SUGGESTED = "suggested"
PROACTIVE_STATUS_PENDING_APPROVAL = "pending_approval"
PROACTIVE_STATUS_QUEUED = "queued"
PROACTIVE_STATUS_EXECUTED = "executed"
PROACTIVE_STATUS_REJECTED = "rejected"

AWAY_MODE_FILE = "away-mode.json"
PROACTIVE_LOG_NAME = "proactive-log.jsonl"


class ProactivityError(ValueError):
    """Raised when a proactivity operation is invalid."""


def validate_proactivity(mode: str) -> str:
    normalized = str(mode or "").strip().upper()
    if normalized not in PROACTIVITY_MODES:
        raise ProactivityError(f"Invalid proactivity mode: {mode!r}")
    return normalized


def autonomy_root() -> Path:
    path = data_dir() / "autonomy-profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _away_mode_path() -> Path:
    return autonomy_root() / AWAY_MODE_FILE


def _proactive_log_path() -> Path:
    return autonomy_root() / PROACTIVE_LOG_NAME


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AwayModeState:
    enabled: bool = False
    pause_proactivity: bool = True
    message: str = ""
    updated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProactiveAction:
    id: str
    parent_agent_id: str
    trigger: str
    evidence: dict[str, Any]
    rationale: str
    budget: dict[str, Any]
    proactivity: str
    persistence: str
    status: str
    requires_approval: bool
    created_at: str
    approved_at: str | None = None
    executed_at: str | None = None
    capability: str = ""
    node_id: str = "localhost"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_away_mode() -> AwayModeState:
    path = _away_mode_path()
    if not path.exists():
        return AwayModeState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return AwayModeState()
    if not isinstance(raw, dict):
        return AwayModeState()
    return AwayModeState(
        enabled=bool(raw.get("enabled")),
        pause_proactivity=bool(raw.get("pause_proactivity", True)),
        message=str(raw.get("message") or ""),
        updated_at=str(raw.get("updated_at") or ""),
    )


def set_away_mode(
    *,
    enabled: bool | None = None,
    pause_proactivity: bool | None = None,
    message: str | None = None,
) -> AwayModeState:
    with _lock:
        current = get_away_mode()
        if enabled is not None:
            current.enabled = bool(enabled)
        if pause_proactivity is not None:
            current.pause_proactivity = bool(pause_proactivity)
        if message is not None:
            current.message = str(message)
        current.updated_at = _utcnow()
        _away_mode_path().write_text(json.dumps(current.as_dict(), indent=2), encoding="utf-8")
        return current


def effective_proactivity(
    configured: str,
    *,
    away_mode: AwayModeState | None = None,
) -> str:
    """Away Mode can pause proactivity without changing the stored configuration."""
    mode = validate_proactivity(configured)
    away = away_mode if away_mode is not None else get_away_mode()
    if away.enabled and away.pause_proactivity:
        return PROACTIVITY_DISABLED
    return mode


def can_enqueue_executable_work(
    configured_proactivity: str,
    *,
    away_mode: AwayModeState | None = None,
    approved: bool = False,
) -> bool:
    """SUGGEST_ONLY never enqueues executable work without explicit approval."""
    mode = effective_proactivity(configured_proactivity, away_mode=away_mode)
    if mode == PROACTIVITY_DISABLED:
        return False
    if mode == PROACTIVITY_SUGGEST_ONLY:
        return bool(approved)
    return mode in {PROACTIVITY_CREATE_TASKS, PROACTIVITY_EXECUTE_WITHIN_POLICY}


def effective_behavior(
    *,
    persistence: str,
    proactivity: str,
    away_mode: AwayModeState | None = None,
) -> dict[str, Any]:
    away = away_mode if away_mode is not None else get_away_mode()
    effective_mode = effective_proactivity(proactivity, away_mode=away)
    return {
        "persistence": persistence,
        "configured_proactivity": validate_proactivity(proactivity),
        "effective_proactivity": effective_mode,
        "away_mode": away.as_dict(),
        "can_suggest": effective_mode in {
            PROACTIVITY_SUGGEST_ONLY,
            PROACTIVITY_CREATE_TASKS,
            PROACTIVITY_EXECUTE_WITHIN_POLICY,
        },
        "can_create_tasks": effective_mode in {
            PROACTIVITY_CREATE_TASKS,
            PROACTIVITY_EXECUTE_WITHIN_POLICY,
        },
        "can_execute_within_policy": effective_mode == PROACTIVITY_EXECUTE_WITHIN_POLICY,
        "requires_approval_for_execution": effective_mode
        in {PROACTIVITY_SUGGEST_ONLY, PROACTIVITY_CREATE_TASKS},
    }


def _append_proactive_log(action: ProactiveAction) -> None:
    path = _proactive_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(action.as_dict()) + "\n")


def list_proactive_actions(*, parent_agent_id: str | None = None) -> list[ProactiveAction]:
    path = _proactive_log_path()
    if not path.exists():
        return []
    out: list[ProactiveAction] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        action = ProactiveAction(
            id=str(raw.get("id") or ""),
            parent_agent_id=str(raw.get("parent_agent_id") or ""),
            trigger=str(raw.get("trigger") or ""),
            evidence=dict(raw.get("evidence") or {}),
            rationale=str(raw.get("rationale") or ""),
            budget=dict(raw.get("budget") or {}),
            proactivity=str(raw.get("proactivity") or ""),
            persistence=str(raw.get("persistence") or ""),
            status=str(raw.get("status") or ""),
            requires_approval=bool(raw.get("requires_approval")),
            created_at=str(raw.get("created_at") or ""),
            approved_at=raw.get("approved_at"),
            executed_at=raw.get("executed_at"),
            capability=str(raw.get("capability") or ""),
            node_id=str(raw.get("node_id") or "localhost"),
        )
        if parent_agent_id and action.parent_agent_id != parent_agent_id:
            continue
        out.append(action)
    return out


def _initial_status(mode: str) -> tuple[str, bool]:
    if mode == PROACTIVITY_SUGGEST_ONLY:
        return PROACTIVE_STATUS_SUGGESTED, True
    if mode == PROACTIVITY_CREATE_TASKS:
        return PROACTIVE_STATUS_PENDING_APPROVAL, True
    if mode == PROACTIVITY_EXECUTE_WITHIN_POLICY:
        return PROACTIVE_STATUS_QUEUED, False
    return PROACTIVE_STATUS_REJECTED, True


def create_proactive_action(
    *,
    parent_agent_id: str,
    trigger: str,
    evidence: dict[str, Any] | None = None,
    rationale: str,
    budget: dict[str, Any] | None = None,
    configured_proactivity: str,
    persistence: str,
    capability: str = "",
    node_id: str = "localhost",
    away_mode: AwayModeState | None = None,
) -> ProactiveAction:
    """Record proactive work with trigger/evidence, rationale, budget, and parent agent."""
    mode = effective_proactivity(configured_proactivity, away_mode=away_mode)
    if mode == PROACTIVITY_DISABLED:
        raise ProactivityError("proactivity is disabled")

    status, requires_approval = _initial_status(mode)
    action = ProactiveAction(
        id=str(uuid.uuid4()),
        parent_agent_id=str(parent_agent_id),
        trigger=str(trigger),
        evidence=dict(evidence or {}),
        rationale=str(rationale),
        budget=dict(budget or {}),
        proactivity=mode,
        persistence=str(persistence),
        status=status,
        requires_approval=requires_approval,
        created_at=_utcnow(),
        capability=str(capability or ""),
        node_id=str(node_id or "localhost"),
    )
    with _lock:
        _append_proactive_log(action)
    return action


async def authorize_execute_within_policy(
    *,
    node_id: str,
    capability: str,
    budget: dict[str, Any] | None = None,
    lease_acquire: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Compose EXECUTE_WITHIN_POLICY with existing per-capability budget checks."""
    acquire = lease_acquire or acquire_lease
    budget_payload = dict(budget or {})
    claim = dict(budget_payload.get("claim") or {})
    if not claim:
        resource = str(budget_payload.get("resource") or "cpu")
        amount = float(budget_payload.get("amount") or 1.0)
        claim_field = f"{resource}_threads" if resource == "cpu" else f"{resource}_gb"
        if resource == "cpu":
            claim = {"cpu_threads": max(1, int(amount))}
        elif resource == "ram":
            claim = {"ram_gb": amount}
        else:
            claim = {claim_field: amount}
    ttl_seconds = int(budget_payload.get("ttl_seconds") or 60)

    node_budget = await get_node_budget(node_id)
    if node_budget is None:
        return {
            "authorized": False,
            "reason": "node budget not found",
            "capability": capability,
        }

    try:
        lease = await acquire(node_id, claim, ttl_seconds=ttl_seconds)
    except (ValueError, LookupError) as exc:
        return {
            "authorized": False,
            "reason": str(exc),
            "capability": capability,
            "budget": node_budget,
        }

    return {
        "authorized": True,
        "capability": capability,
        "lease": lease,
        "budget": node_budget,
    }


def approve_proactive_action(action_id: str) -> ProactiveAction:
    actions = list_proactive_actions()
    for action in actions:
        if action.id != action_id:
            continue
        if not action.requires_approval:
            return action
        action.approved_at = _utcnow()
        action.status = PROACTIVE_STATUS_QUEUED
        with _lock:
            path = _proactive_log_path()
            lines = []
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    raw = json.loads(line)
                    if isinstance(raw, dict) and raw.get("id") == action_id:
                        raw["approved_at"] = action.approved_at
                        raw["status"] = action.status
                    lines.append(json.dumps(raw))
            path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return action
    raise ProactivityError(f"proactive action not found: {action_id}")


def reset_proactivity_store() -> None:
    """Clear away-mode and proactive logs (tests)."""
    with _lock:
        for path in (_away_mode_path(), _proactive_log_path()):
            if path.exists():
                path.unlink()
