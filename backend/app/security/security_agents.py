"""RFC-0197 blue / red / purple security agent modes (backend).

Binds license modules, default personas, and tool exposure maps.
No exploit recipes, PoCs, or attack procedures.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ..config import data_dir
from ..policy.cyber_ato import role_allowed
from .security_audit import audit_security_event

SecurityMode = Literal["blue", "red", "purple"]
SecurityRole = Literal["blue-team", "red-team", "purple-team"]
PurplePhase = Literal["blue", "red"]

SECURITY_MODES: tuple[SecurityMode, ...] = ("blue", "red", "purple")
SECURITY_ROLES: tuple[SecurityRole, ...] = ("blue-team", "red-team", "purple-team")

MODE_TO_ROLE: dict[str, SecurityRole] = {
    "blue": "blue-team",
    "red": "red-team",
    "purple": "purple-team",
    "blue-team": "blue-team",
    "red-team": "red-team",
    "purple-team": "purple-team",
}

ROLE_TO_MODE: dict[str, SecurityMode] = {
    "blue-team": "blue",
    "red-team": "red",
    "purple-team": "purple",
}

DEFAULT_PERSONA_BINDS: dict[str, dict[str, Any]] = {
    "blue": {
        "persona_ids": ["themis"],
        "primary_persona_id": "themis",
        "voice_profile_hint": "tactical_aide_original_v1",
        "presence_shape_hint": "twin_shield",
    },
    "red": {
        "persona_ids": ["veles"],
        "primary_persona_id": "veles",
        "voice_profile_hint": "synthetic_command_original_v1",
        "presence_shape_hint": "serpent_orbit",
    },
    "purple": {
        "persona_ids": ["themis", "veles"],
        "primary_persona_id": "themis",
        "voice_profile_hint": "tactical_aide_original_v1",
        "presence_shape_hint": "twin_shield",
        "note": "Purple coordinates Themis (blue phase) and Veles (red phase); owner may override voice in Appearance.",
    },
}

# Tools the security agent must drive (not narrate-only). Computer-use stays
# permission-gated at execute time (RFC-0079); exposure here unlocks schemas.
BLUE_MODE_TOOLS: tuple[str, ...] = (
    "hexstrike_operator",
    "hexstrike_defensive",
    "lta_protected_folder",
    "rea_investigate",
    "filesystem",
    "terminal",
    "python",
    "screenshot",
    "desktop",
    "web_fetch",
)
RED_MODE_TOOLS: tuple[str, ...] = (
    "hexstrike_operator",
    "filesystem",
    "terminal",
    "python",
    "screenshot",
    "desktop",
)

_LOCK = threading.RLock()


class SecurityAgentError(ValueError):
    pass


class SecurityAgentDenied(PermissionError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_mode(value: str | None) -> SecurityMode | None:
    key = (value or "").strip().lower()
    if not key:
        return None
    if key in MODE_TO_ROLE:
        role = MODE_TO_ROLE[key]
        return ROLE_TO_MODE[role]
    return None


def normalize_role(value: str | None) -> SecurityRole | None:
    mode = normalize_mode(value)
    if mode is None:
        return None
    return MODE_TO_ROLE[mode]


def is_security_role(value: str | None) -> bool:
    return normalize_role(value) is not None


def persona_bind_for_mode(mode: str) -> dict[str, Any]:
    normalized = normalize_mode(mode)
    if normalized is None:
        raise SecurityAgentError(f"unknown security agent mode: {mode}")
    return dict(DEFAULT_PERSONA_BINDS[normalized])


def assert_mode_entitled(mode: str) -> SecurityRole:
    """License gates per RFC-0119/0087 — red requires LE on the same package."""
    normalized = normalize_mode(mode)
    if normalized is None:
        raise SecurityAgentError(f"unknown security agent mode: {mode}")
    role = MODE_TO_ROLE[normalized]
    if normalized == "blue":
        if not role_allowed("blue-team"):
            audit_security_event("invoke_denied", reason="blue_team_not_entitled", mode=normalized)
            raise SecurityAgentDenied("blue-team module is not entitled on the installed license package")
        return role
    if normalized == "red":
        # role_allowed("red-team") already requires law_enforcement on package
        if not role_allowed("red-team"):
            audit_security_event("invoke_denied", reason="red_requires_law_enforcement", mode=normalized)
            raise SecurityAgentDenied(
                "red-team requires the red-team module and law_enforcement=true on the same package"
            )
        return role
    # purple: both blue and red (with LE)
    if not role_allowed("blue-team"):
        audit_security_event("invoke_denied", reason="purple_missing_blue", mode=normalized)
        raise SecurityAgentDenied("purple-team requires blue-team module entitlement")
    if not role_allowed("red-team"):
        audit_security_event("invoke_denied", reason="red_requires_law_enforcement", mode=normalized)
        raise SecurityAgentDenied(
            "purple-team requires red-team module and law_enforcement=true on the same package"
        )
    return role


def mode_tools(role_or_mode: str, *, purple_phase: str | None = None) -> list[str]:
    role = normalize_role(role_or_mode)
    if role is None:
        return []
    if role == "blue-team":
        return list(BLUE_MODE_TOOLS)
    if role == "red-team":
        return list(RED_MODE_TOOLS)
    phase = (purple_phase or "blue").strip().lower()
    if phase == "red":
        return list(RED_MODE_TOOLS)
    return list(BLUE_MODE_TOOLS)


def mode_summary(mode: str) -> dict[str, Any]:
    normalized = normalize_mode(mode)
    if normalized is None:
        raise SecurityAgentError(f"unknown security agent mode: {mode}")
    role = MODE_TO_ROLE[normalized]
    entitled = True
    deny_reason = ""
    try:
        assert_mode_entitled(normalized)
    except SecurityAgentDenied as exc:
        entitled = False
        deny_reason = str(exc)
    bind = persona_bind_for_mode(normalized)
    return {
        "mode": normalized,
        "security_role": role,
        "entitled": entitled,
        "deny_reason": deny_reason,
        "persona_bind": bind,
        "tools": mode_tools(role, purple_phase="blue" if normalized == "purple" else None),
        "requires_law_enforcement": normalized in {"red", "purple"},
    }


def job_dir(task_id: str) -> Path:
    path = data_dir() / "security-jobs" / (task_id or "unknown").strip()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path(task_id: str) -> Path:
    return job_dir(task_id) / "purple-state.json"


@dataclass
class PurpleState:
    task_id: str
    phase: PurplePhase = "blue"
    locked: bool = False
    active_job_id: str = ""
    handoff_count: int = 0
    updated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "phase": self.phase,
            "locked": self.locked,
            "active_job_id": self.active_job_id,
            "handoff_count": self.handoff_count,
            "updated_at": self.updated_at or _utcnow(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None, *, task_id: str) -> "PurpleState":
        data = raw if isinstance(raw, dict) else {}
        phase = str(data.get("phase") or "blue").strip().lower()
        if phase not in {"blue", "red"}:
            phase = "blue"
        return cls(
            task_id=task_id,
            phase=phase,  # type: ignore[arg-type]
            locked=bool(data.get("locked")),
            active_job_id=str(data.get("active_job_id") or ""),
            handoff_count=int(data.get("handoff_count") or 0),
            updated_at=str(data.get("updated_at") or ""),
        )


def load_purple_state(task_id: str) -> PurpleState:
    path = _state_path(task_id)
    if not path.is_file():
        return PurpleState(task_id=task_id, updated_at=_utcnow())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PurpleState(task_id=task_id, updated_at=_utcnow())
    return PurpleState.from_dict(payload if isinstance(payload, dict) else None, task_id=task_id)


def save_purple_state(state: PurpleState) -> PurpleState:
    state.updated_at = _utcnow()
    path = _state_path(state.task_id)
    temp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        temp.write_text(json.dumps(state.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(path)
    return state


def init_purple(task_id: str) -> PurpleState:
    state = PurpleState(task_id=task_id, phase="blue", locked=False, updated_at=_utcnow())
    return save_purple_state(state)


def set_purple_active_job(task_id: str, job_id: str) -> PurpleState:
    state = load_purple_state(task_id)
    if state.locked:
        raise SecurityAgentDenied("purple phase is locked after owner stop")
    state.active_job_id = (job_id or "").strip()
    return save_purple_state(state)


def clear_purple_active_job(task_id: str) -> PurpleState:
    state = load_purple_state(task_id)
    state.active_job_id = ""
    return save_purple_state(state)


def write_handoff(
    task_id: str,
    *,
    from_phase: str,
    to_phase: str,
    findings: list[Any] | None = None,
    evidence_paths: list[Any] | None = None,
    open_questions: list[Any] | None = None,
) -> dict[str, Any]:
    state = load_purple_state(task_id)
    if state.locked:
        raise SecurityAgentDenied("purple phase is locked after owner stop")
    if state.active_job_id:
        raise SecurityAgentDenied("cannot hand off while an active purple job is running")
    artifact = {
        "at": _utcnow(),
        "from_phase": from_phase,
        "to_phase": to_phase,
        "findings": [item for item in (findings or []) if item is not None][:100],
        "evidence_paths": [str(item) for item in (evidence_paths or [])][:100],
        "open_questions": [str(item) for item in (open_questions or [])][:100],
    }
    handoff_dir = job_dir(task_id) / "handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    state.handoff_count += 1
    path = handoff_dir / f"{state.handoff_count:04d}-{from_phase}-to-{to_phase}.json"
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    artifact["path"] = str(path)
    save_purple_state(state)
    audit_security_event(
        "purple_handoff",
        task_id=task_id,
        from_phase=from_phase,
        to_phase=to_phase,
        handoff_count=state.handoff_count,
    )
    return artifact


def advance_purple_phase(
    task_id: str,
    *,
    findings: list[Any] | None = None,
    evidence_paths: list[Any] | None = None,
    open_questions: list[Any] | None = None,
) -> dict[str, Any]:
    state = load_purple_state(task_id)
    if state.locked:
        raise SecurityAgentDenied("purple phase is locked after owner stop")
    if state.active_job_id:
        raise SecurityAgentDenied("cannot switch purple phase while a job is active")
    current = state.phase
    nxt: PurplePhase = "red" if current == "blue" else "blue"
    handoff = write_handoff(
        task_id,
        from_phase=current,
        to_phase=nxt,
        findings=findings,
        evidence_paths=evidence_paths,
        open_questions=open_questions,
    )
    state = load_purple_state(task_id)
    state.phase = nxt
    save_purple_state(state)
    return {"state": state.as_dict(), "handoff": handoff}


def stop_purple(task_id: str, *, cancel_job: bool = True) -> dict[str, Any]:
    """Owner stop: cancel active job hint + lock phase machine."""
    state = load_purple_state(task_id)
    cancelled_job = ""
    if cancel_job and state.active_job_id:
        cancelled_job = state.active_job_id
        try:
            from .hexstrike_operator import stop_operator_job

            stop_operator_job(state.active_job_id)
        except Exception:
            pass
        state.active_job_id = ""
    state.locked = True
    save_purple_state(state)
    audit_security_event("purple_stopped", task_id=task_id, cancelled_job=cancelled_job, locked=True)
    return {"state": state.as_dict(), "cancelled_job": cancelled_job}


def list_handoffs(task_id: str) -> list[dict[str, Any]]:
    handoff_dir = job_dir(task_id) / "handoffs"
    if not handoff_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(handoff_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payload = dict(payload)
            payload.setdefault("path", str(path))
            rows.append(payload)
    return rows


def tools_allowed_in_purple_phase(tool_name: str, phase: str) -> bool:
    """No parallel red+blue tools — only the active phase tool set."""
    allowed = set(mode_tools("purple-team", purple_phase=phase))
    # Escape / capability request always ok
    if tool_name in {"request_tools", "request_capability"}:
        return True
    if tool_name in allowed:
        return True
    # Shared non-cyber tools from the phase map only
    return False
