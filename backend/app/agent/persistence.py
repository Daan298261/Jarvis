from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir

_lock = threading.RLock()

PERSISTENCE_ONE_SHOT = "ONE_SHOT"
PERSISTENCE_UNTIL_COMPLETE = "UNTIL_COMPLETE"
PERSISTENCE_CONTINUOUS = "CONTINUOUS"

PERSISTENCE_MODES = (
    PERSISTENCE_ONE_SHOT,
    PERSISTENCE_UNTIL_COMPLETE,
    PERSISTENCE_CONTINUOUS,
)

TASK_STATUS_COMPLETE = "complete"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_IDLE = "idle"
TASK_STATUS_FAILED = "failed"

REGISTRY_NAME = "registry.json"
SCHEDULER_STATE_NAME = "scheduler-state.json"


class PersistenceError(ValueError):
    """Raised when a persistence operation is invalid."""


def validate_persistence(mode: str) -> str:
    normalized = str(mode or "").strip().upper()
    if normalized not in PERSISTENCE_MODES:
        raise PersistenceError(f"Invalid persistence mode: {mode!r}")
    return normalized


def autonomy_root() -> Path:
    path = data_dir() / "autonomy-profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _registry_path() -> Path:
    return autonomy_root() / REGISTRY_NAME


def _scheduler_state_path() -> Path:
    return autonomy_root() / SCHEDULER_STATE_NAME


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentAutonomyProfile:
    id: str
    name: str
    persistence: str
    proactivity: str
    agent_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_registry_unlocked() -> list[AgentAutonomyProfile]:
    path = _registry_path()
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out: list[AgentAutonomyProfile] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            AgentAutonomyProfile(
                id=str(row.get("id") or ""),
                name=str(row.get("name") or ""),
                persistence=validate_persistence(row.get("persistence") or PERSISTENCE_ONE_SHOT),
                proactivity=str(row.get("proactivity") or "DISABLED"),
                agent_id=str(row.get("agent_id") or ""),
                created_at=str(row.get("created_at") or ""),
                updated_at=str(row.get("updated_at") or ""),
                metadata=dict(row.get("metadata") or {}),
            )
        )
    return out


def _save_registry_unlocked(items: list[AgentAutonomyProfile]) -> None:
    _registry_path().write_text(
        json.dumps([item.as_dict() for item in items], indent=2),
        encoding="utf-8",
    )


def list_autonomy_profiles() -> list[AgentAutonomyProfile]:
    with _lock:
        return list(_load_registry_unlocked())


def get_autonomy_profile(profile_id: str) -> AgentAutonomyProfile | None:
    with _lock:
        for item in _load_registry_unlocked():
            if item.id == profile_id:
                return item
    return None


def create_autonomy_profile(
    *,
    name: str,
    persistence: str = PERSISTENCE_ONE_SHOT,
    proactivity: str = "DISABLED",
    agent_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> AgentAutonomyProfile:
    now = _utcnow()
    profile = AgentAutonomyProfile(
        id=str(uuid.uuid4()),
        name=name.strip() or "default",
        persistence=validate_persistence(persistence),
        proactivity=str(proactivity or "DISABLED").strip().upper(),
        agent_id=str(agent_id or ""),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    with _lock:
        items = _load_registry_unlocked()
        items.append(profile)
        _save_registry_unlocked(items)
    return profile


def update_autonomy_profile(
    profile_id: str,
    *,
    name: str | None = None,
    persistence: str | None = None,
    proactivity: str | None = None,
    agent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentAutonomyProfile:
    with _lock:
        items = _load_registry_unlocked()
        for index, item in enumerate(items):
            if item.id != profile_id:
                continue
            if name is not None:
                item.name = name.strip() or item.name
            if persistence is not None:
                item.persistence = validate_persistence(persistence)
            if proactivity is not None:
                item.proactivity = str(proactivity).strip().upper()
            if agent_id is not None:
                item.agent_id = str(agent_id)
            if metadata is not None:
                item.metadata = dict(metadata)
            item.updated_at = _utcnow()
            items[index] = item
            _save_registry_unlocked(items)
            return item
    raise PersistenceError(f"autonomy profile not found: {profile_id}")


def should_remain_scheduled(persistence: str, *, task_status: str = TASK_STATUS_IDLE) -> bool:
    """Return whether an agent should stay on the scheduler based on persistence only."""
    mode = validate_persistence(persistence)
    status = str(task_status or TASK_STATUS_IDLE).strip().lower()
    if mode == PERSISTENCE_CONTINUOUS:
        return True
    if mode == PERSISTENCE_UNTIL_COMPLETE:
        return status not in {TASK_STATUS_COMPLETE, TASK_STATUS_FAILED}
    return status in {TASK_STATUS_RUNNING, TASK_STATUS_IDLE}


def scheduler_eligible_agents(
    profiles: list[AgentAutonomyProfile] | None = None,
    *,
    task_status_by_agent: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Honor continuous agents on the scheduler without granting capability authority."""
    rows = profiles if profiles is not None else list_autonomy_profiles()
    statuses = task_status_by_agent or {}
    eligible: list[dict[str, Any]] = []
    for profile in rows:
        agent_key = profile.agent_id or profile.id
        task_status = statuses.get(agent_key, TASK_STATUS_IDLE)
        if should_remain_scheduled(profile.persistence, task_status=task_status):
            eligible.append(
                {
                    "profile_id": profile.id,
                    "agent_id": profile.agent_id,
                    "name": profile.name,
                    "persistence": profile.persistence,
                    "task_status": task_status,
                    "scheduler_action": "monitor",
                    "capability_authority": "unchanged",
                }
            )
    return eligible


def _load_scheduler_state_unlocked() -> dict[str, Any]:
    path = _scheduler_state_path()
    if not path.exists():
        return {"last_tick": None, "ticks": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"last_tick": None, "ticks": {}}
    if not isinstance(payload, dict):
        return {"last_tick": None, "ticks": {}}
    ticks = payload.get("ticks")
    if not isinstance(ticks, dict):
        ticks = {}
    return {"last_tick": payload.get("last_tick"), "ticks": ticks}


def _save_scheduler_state_unlocked(state: dict[str, Any]) -> None:
    _scheduler_state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


def scheduler_tick(
    *,
    task_status_by_agent: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Record a scheduler tick and return agents that remain scheduled."""
    eligible = scheduler_eligible_agents(task_status_by_agent=task_status_by_agent)
    now = _utcnow()
    with _lock:
        state = _load_scheduler_state_unlocked()
        ticks = dict(state.get("ticks") or {})
        for item in eligible:
            key = item["agent_id"] or item["profile_id"]
            ticks[key] = {"last_seen": now, "persistence": item["persistence"]}
        state["last_tick"] = now
        state["ticks"] = ticks
        _save_scheduler_state_unlocked(state)
    return {
        "tick_at": now,
        "eligible": eligible,
        "count": len(eligible),
    }


def reset_autonomy_store() -> None:
    """Clear persisted autonomy profiles and scheduler state (tests)."""
    with _lock:
        for path in (_registry_path(), _scheduler_state_path()):
            if path.exists():
                path.unlink()
