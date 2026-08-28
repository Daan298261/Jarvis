from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .audit import record_policy_change
from .levels import DEFAULT_AGENT_LEVEL, DEFAULT_PLATFORM_CAP, AutonomyLevel, parse_level

_lock = threading.RLock()
PROFILES_FILE = "profiles.json"
PLATFORM_FILE = "platform.json"


def policy_root() -> Path:
    path = data_dir() / "policy"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _profiles_path() -> Path:
    return policy_root() / PROFILES_FILE


def _platform_path() -> Path:
    return policy_root() / PLATFORM_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_profiles() -> dict[str, Any]:
    return {"profiles": {}}


def _default_platform_policy() -> dict[str, Any]:
    return {
        "autonomy_caps": {"*": DEFAULT_PLATFORM_CAP.value},
        "default_agent_autonomy": DEFAULT_AGENT_LEVEL.value,
    }


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return raw if isinstance(raw, dict) else default


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def reset_policy_store() -> None:
    with _lock:
        root = policy_root()
        for child in root.iterdir():
            if child.is_file():
                child.unlink()


def normalize_policy_from_interview(interview: dict[str, Any]) -> dict[str, Any]:
    autonomy: dict[str, str] = {}
    approval_actions = interview.get("approval_required_actions") or []
    if isinstance(approval_actions, list):
        for item in approval_actions:
            text = str(item).strip().lower()
            if text in {"terminal", "shell", "command"}:
                autonomy["terminal"] = AutonomyLevel.L3_EXECUTE_WITH_GATES.value
            elif text in {"git push", "push", "git.push"}:
                autonomy["git.push"] = AutonomyLevel.L3_EXECUTE_WITH_GATES.value
            elif text in {"send", "email", "message", "external"}:
                autonomy["external.send"] = AutonomyLevel.L3_EXECUTE_WITH_GATES.value
            elif text in {"purchase", "spend", "payment"}:
                autonomy["spend.purchase"] = AutonomyLevel.L1_SUGGEST.value
            elif text in {"credentials", "password", "secrets"}:
                autonomy["credentials.change"] = AutonomyLevel.L1_SUGGEST.value
            elif text in {"filesystem.write", "write", "delete"}:
                autonomy["filesystem.write"] = AutonomyLevel.L3_EXECUTE_WITH_GATES.value

    hard_blocks = interview.get("hard_prohibitions") or []
    if isinstance(hard_blocks, list):
        for item in hard_blocks:
            text = str(item).strip().lower()
            if "terminal" in text or "shell" in text:
                autonomy["terminal"] = AutonomyLevel.L0_OBSERVE.value
            if "browser" in text:
                autonomy["browser"] = AutonomyLevel.L0_OBSERVE.value

    default_level = interview.get("default_autonomy")
    if default_level:
        autonomy.setdefault("*", parse_level(str(default_level)).value)

    return {
        "autonomy": autonomy,
        "approval_required_actions": list(approval_actions) if isinstance(approval_actions, list) else [],
        "budgets": dict(interview.get("budgets") or {}),
        "privacy": dict(interview.get("privacy") or {}),
        "scheduling": dict(interview.get("scheduling") or {}),
        "escalation": dict(interview.get("escalation") or {}),
        "channels": list(interview.get("allowed_channels") or []),
        "hard_prohibitions": list(hard_blocks) if isinstance(hard_blocks, list) else [],
    }


def generate_prompt_from_policy(name: str, interview: dict[str, Any], policy: dict[str, Any]) -> str:
    mission = str(interview.get("mission") or "").strip()
    tone = str(interview.get("tone") or "professional").strip()
    success = str(interview.get("success_criteria") or "").strip()
    lines = [f"You are {name}, a Jarvis specialist agent."]
    if mission:
        lines.append(f"Mission: {mission}")
    if success:
        lines.append(f"Success criteria: {success}")
    lines.append(f"Tone: {tone}")
    channels = policy.get("channels") or []
    if channels:
        lines.append("Allowed channels: " + ", ".join(str(item) for item in channels))
    prohibitions = policy.get("hard_prohibitions") or []
    if prohibitions:
        lines.append("Hard prohibitions: " + "; ".join(str(item) for item in prohibitions))
    return "\n".join(lines)


def list_profiles() -> list[dict[str, Any]]:
    with _lock:
        state = _load_json(_profiles_path(), _empty_profiles())
    profiles = state.get("profiles") or {}
    items = [dict(value) for value in profiles.values() if isinstance(value, dict)]
    return sorted(items, key=lambda item: item.get("name") or "")


def get_profile(profile_id: str) -> dict[str, Any] | None:
    with _lock:
        state = _load_json(_profiles_path(), _empty_profiles())
    raw = (state.get("profiles") or {}).get(profile_id)
    return dict(raw) if isinstance(raw, dict) else None


def create_profile(
    *,
    name: str,
    interview_answers: dict[str, Any],
    policy: dict[str, Any] | None = None,
    generated_prompt: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    profile_id = str(uuid.uuid4())
    normalized = dict(policy or normalize_policy_from_interview(interview_answers))
    prompt = generated_prompt or generate_prompt_from_policy(name, interview_answers, normalized)
    record = {
        "id": profile_id,
        "name": name,
        "interview_answers": dict(interview_answers),
        "policy": normalized,
        "generated_prompt": prompt,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    with _lock:
        state = _load_json(_profiles_path(), _empty_profiles())
        profiles = state.setdefault("profiles", {})
        profiles[profile_id] = record
        _save_json(_profiles_path(), state)
    record_policy_change(
        actor=actor,
        profile_id=profile_id,
        field="profile.created",
        old_value=None,
        new_value={"name": name},
    )
    return record


def update_profile(
    profile_id: str,
    *,
    name: str | None = None,
    interview_answers: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    generated_prompt: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    with _lock:
        state = _load_json(_profiles_path(), _empty_profiles())
        profiles = state.setdefault("profiles", {})
        raw = profiles.get(profile_id)
        if not isinstance(raw, dict):
            raise KeyError(f"profile not found: {profile_id}")
        record = dict(raw)

        if name is not None and name != record.get("name"):
            record_policy_change(actor=actor, profile_id=profile_id, field="name", old_value=record.get("name"), new_value=name)
            record["name"] = name

        if interview_answers is not None:
            old = record.get("interview_answers")
            record_policy_change(
                actor=actor,
                profile_id=profile_id,
                field="interview_answers",
                old_value=old,
                new_value=interview_answers,
            )
            record["interview_answers"] = dict(interview_answers)
            if policy is None:
                policy = normalize_policy_from_interview(interview_answers)

        if policy is not None:
            old = record.get("policy")
            record_policy_change(actor=actor, profile_id=profile_id, field="policy", old_value=old, new_value=policy)
            record["policy"] = dict(policy)
            if generated_prompt is None:
                generated_prompt = generate_prompt_from_policy(
                    record.get("name") or profile_id,
                    record.get("interview_answers") or {},
                    record["policy"],
                )

        if generated_prompt is not None and generated_prompt != record.get("generated_prompt"):
            record_policy_change(
                actor=actor,
                profile_id=profile_id,
                field="generated_prompt",
                old_value=record.get("generated_prompt"),
                new_value=generated_prompt,
            )
            record["generated_prompt"] = generated_prompt

        record["updated_at"] = _utc_now()
        profiles[profile_id] = record
        _save_json(_profiles_path(), state)
    return record


def delete_profile(profile_id: str, *, actor: str = "system") -> None:
    with _lock:
        state = _load_json(_profiles_path(), _empty_profiles())
        profiles = state.setdefault("profiles", {})
        if profile_id not in profiles:
            raise KeyError(f"profile not found: {profile_id}")
        old = profiles.pop(profile_id)
        _save_json(_profiles_path(), state)
    record_policy_change(actor=actor, profile_id=profile_id, field="profile.deleted", old_value=old, new_value=None)


def get_platform_policy() -> dict[str, Any]:
    with _lock:
        return _load_json(_platform_path(), _default_platform_policy())


def update_platform_policy(
    *,
    autonomy_caps: dict[str, str] | None = None,
    default_agent_autonomy: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    with _lock:
        current = _load_json(_platform_path(), _default_platform_policy())
        if autonomy_caps is not None:
            old = current.get("autonomy_caps")
            record_policy_change(
                actor=actor,
                profile_id=None,
                field="platform.autonomy_caps",
                old_value=old,
                new_value=autonomy_caps,
            )
            current["autonomy_caps"] = dict(autonomy_caps)
        if default_agent_autonomy is not None:
            old = current.get("default_agent_autonomy")
            record_policy_change(
                actor=actor,
                profile_id=None,
                field="platform.default_agent_autonomy",
                old_value=old,
                new_value=default_agent_autonomy,
            )
            current["default_agent_autonomy"] = parse_level(default_agent_autonomy).value
        _save_json(_platform_path(), current)
    return current


def get_agent_autonomy_map(profile_id: str | None) -> dict[str, str]:
    default = get_platform_policy().get("default_agent_autonomy") or DEFAULT_AGENT_LEVEL.value
    if not profile_id:
        return {"*": str(default)}
    profile = get_profile(profile_id)
    if not profile:
        return {"*": str(default)}
    policy = profile.get("policy") or {}
    autonomy = dict(policy.get("autonomy") or {})
    autonomy.setdefault("*", str(default))
    return autonomy


def get_platform_autonomy_caps() -> dict[str, str]:
    platform = get_platform_policy()
    caps = dict(platform.get("autonomy_caps") or {})
    caps.setdefault("*", DEFAULT_PLATFORM_CAP.value)
    return caps
