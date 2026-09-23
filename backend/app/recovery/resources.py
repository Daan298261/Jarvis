from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..agent.workflows import load_saved_workflows, workflows_dir
from ..config import load_settings, settings_path
from ..packs.store import load_state as load_packs_state
from ..policy.store import (
    _default_platform_policy,
    _empty_profiles,
    _load_json,
    _platform_path,
    _profiles_path,
    policy_root,
)
from .redaction import redact_mapping, redact_settings_control_plane
from .types import (
    RESOURCE_PACKS_STATE,
    RESOURCE_POLICY_PLATFORM,
    RESOURCE_POLICY_PROFILES,
    RESOURCE_SETTINGS_CONTROL,
    RESOURCE_WORKFLOWS,
)

SnapshotFn = Callable[[], dict[str, Any]]
RestoreFn = Callable[[dict[str, Any]], None]


def capture_policy_profiles() -> dict[str, Any]:
    return _load_json(_profiles_path(), _empty_profiles())


def restore_policy_profiles(snapshot: dict[str, Any]) -> None:
    policy_root().mkdir(parents=True, exist_ok=True)
    _profiles_path().write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")


def capture_policy_platform() -> dict[str, Any]:
    return _load_json(_platform_path(), _default_platform_policy())


def restore_policy_platform(snapshot: dict[str, Any]) -> None:
    policy_root().mkdir(parents=True, exist_ok=True)
    _platform_path().write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")


def capture_workflows() -> dict[str, Any]:
    items = {wf.id: wf.to_dict() for wf in load_saved_workflows()}
    return {"workflows": items}


def restore_workflows(snapshot: dict[str, Any]) -> None:
    root = workflows_dir()
    root.mkdir(parents=True, exist_ok=True)
    for path in root.glob("*.json"):
        path.unlink()
    workflows = snapshot.get("workflows") or {}
    if not isinstance(workflows, dict):
        return
    for wf_id, payload in workflows.items():
        if not isinstance(payload, dict):
            continue
        slug = str(payload.get("id") or wf_id)
        safe = slug.replace("/", "-")[:80] or "workflow"
        (root / f"{safe}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def capture_settings_control() -> dict[str, Any]:
    dump = load_settings().model_dump()
    return redact_settings_control_plane(dump)


def restore_settings_control(snapshot: dict[str, Any]) -> None:
    from ..config import AppSettings

    current = load_settings()
    merged = current.model_dump()
    for key, value in snapshot.items():
        if key == "inference" and isinstance(value, dict):
            inf = dict(merged.get("inference") or {})
            for ik, iv in value.items():
                if ik == "api_key" and isinstance(iv, dict) and iv.get("_ref"):
                    continue
                inf[ik] = iv
            merged["inference"] = inf
        else:
            merged[key] = value
    settings = AppSettings.model_validate(merged)
    dump = settings.model_dump()
    dump.pop("auth_token", None)
    settings_path().write_text(json.dumps(dump, indent=2), encoding="utf-8")


def capture_packs_state() -> dict[str, Any]:
    state = load_packs_state()
    if not isinstance(state, dict):
        return {"state": state}
    return redact_mapping(state)


def restore_packs_state(snapshot: dict[str, Any]) -> None:
    from ..packs.store import save_state

    save_state(snapshot)


RESOURCE_CAPTURE: dict[str, SnapshotFn] = {
    RESOURCE_POLICY_PROFILES: capture_policy_profiles,
    RESOURCE_POLICY_PLATFORM: capture_policy_platform,
    RESOURCE_WORKFLOWS: capture_workflows,
    RESOURCE_SETTINGS_CONTROL: capture_settings_control,
    RESOURCE_PACKS_STATE: capture_packs_state,
}

RESOURCE_RESTORE: dict[str, RestoreFn] = {
    RESOURCE_POLICY_PROFILES: restore_policy_profiles,
    RESOURCE_POLICY_PLATFORM: restore_policy_platform,
    RESOURCE_WORKFLOWS: restore_workflows,
    RESOURCE_SETTINGS_CONTROL: restore_settings_control,
    RESOURCE_PACKS_STATE: restore_packs_state,
}


def full_snapshot() -> dict[str, Any]:
    return {key: fn() for key, fn in RESOURCE_CAPTURE.items()}


def restore_full_snapshot(snapshot: dict[str, Any]) -> None:
    for resource_class, restore_fn in RESOURCE_RESTORE.items():
        block = snapshot.get(resource_class)
        if isinstance(block, dict):
            restore_fn(block)


def resource_path_hint(resource_class: str) -> str:
    if resource_class == RESOURCE_POLICY_PROFILES:
        return str(_profiles_path())
    if resource_class == RESOURCE_POLICY_PLATFORM:
        return str(_platform_path())
    if resource_class == RESOURCE_WORKFLOWS:
        return str(workflows_dir())
    if resource_class == RESOURCE_SETTINGS_CONTROL:
        return str(settings_path())
    if resource_class == RESOURCE_PACKS_STATE:
        return str(Path("packs/state"))
    return resource_class
