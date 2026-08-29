"""First-run setup state persistence (data/setup_state.json)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import data_dir

SETUP_STATE_FILENAME = "setup_state.json"

WIZARD_STEPS = (
    "welcome",
    "system",
    "role",
    "resources",
    "inference",
    "runtime",
    "desktop",
    "verification",
    "done",
)

DEFAULT_STATE: dict[str, Any] = {
    "version": 1,
    "completed": False,
    "current_step": "welcome",
    "completed_steps": [],
    "jarvis_role": "standalone",
    "recommended_class": "",
    "role_policies": {},
    "resource_preset": "dynamic",
    "global_percent": 50,
    "resource_mode": "dynamic",
    "resource_limits": {},
    "inference_choice": "local",
    "inference_profile": "balanced",
    "remote_host": "127.0.0.1",
    "remote_port": 8088,
    "install_expert_27b": False,
    "install_playwright": True,
    "desktop_prefs": {
        "start_with_windows": False,
        "start_minimized": False,
        "close_to_tray": True,
    },
    "component_status": {},
    "last_error": "",
    "updated_at": "",
}


def setup_state_path() -> Path:
    return data_dir() / SETUP_STATE_FILENAME


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_setup_state() -> dict[str, Any]:
    path = setup_state_path()
    if not path.exists():
        return dict(DEFAULT_STATE)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_STATE)
    if not isinstance(raw, dict):
        return dict(DEFAULT_STATE)
    merged = dict(DEFAULT_STATE)
    merged.update(raw)
    desktop = dict(DEFAULT_STATE["desktop_prefs"])
    if isinstance(raw.get("desktop_prefs"), dict):
        desktop.update(raw["desktop_prefs"])
    merged["desktop_prefs"] = desktop
    if not isinstance(merged.get("completed_steps"), list):
        merged["completed_steps"] = []
    if not isinstance(merged.get("component_status"), dict):
        merged["component_status"] = {}
    if not isinstance(merged.get("role_policies"), dict):
        merged["role_policies"] = {}
    if not isinstance(merged.get("resource_limits"), dict):
        merged["resource_limits"] = {}
    return merged


def save_setup_state(patch: dict[str, Any] | None = None, *, replace: bool = False) -> dict[str, Any]:
    current = dict(DEFAULT_STATE) if replace else load_setup_state()
    if patch:
        for key, value in patch.items():
            if key == "desktop_prefs" and isinstance(value, dict):
                desktop = dict(current.get("desktop_prefs") or {})
                desktop.update(value)
                current["desktop_prefs"] = desktop
            elif key == "component_status" and isinstance(value, dict):
                status = dict(current.get("component_status") or {})
                status.update(value)
                current["component_status"] = status
            elif key == "role_policies" and isinstance(value, dict):
                policies = dict(current.get("role_policies") or {})
                policies.update(value)
                current["role_policies"] = policies
            elif key == "resource_limits" and isinstance(value, dict):
                limits = dict(current.get("resource_limits") or {})
                limits.update(value)
                current["resource_limits"] = limits
            elif key == "completed_steps" and isinstance(value, list):
                current["completed_steps"] = list(dict.fromkeys(value))
            else:
                current[key] = value
    step = str(current.get("current_step") or "welcome")
    if step not in WIZARD_STEPS:
        current["current_step"] = "welcome"
    current["updated_at"] = _utcnow_iso()
    path = setup_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def mark_step_complete(step: str, *, next_step: str | None = None) -> dict[str, Any]:
    state = load_setup_state()
    completed = list(state.get("completed_steps") or [])
    if step not in completed:
        completed.append(step)
    patch: dict[str, Any] = {"completed_steps": completed}
    if next_step:
        patch["current_step"] = next_step
    return save_setup_state(patch)


def complete_setup() -> dict[str, Any]:
    return save_setup_state(
        {
            "completed": True,
            "current_step": "done",
            "completed_steps": list(WIZARD_STEPS),
            "last_error": "",
        }
    )


def needs_setup() -> bool:
    return not bool(load_setup_state().get("completed"))


def wizard_preset_to_budget(preset: str) -> dict[str, Any]:
    """Map setup-wizard resource radios to swarm budget fields."""
    key = str(preset or "").strip().lower()
    if key == "minimal":
        return {"preset": "minimal", "mode": "static", "global_percent": 15}
    if key == "balanced":
        return {"preset": "balanced", "mode": "static", "global_percent": 50}
    if key == "dynamic":
        return {"preset": "balanced", "mode": "dynamic", "global_percent": 50}
    if key == "maximum":
        return {"preset": "maximum", "mode": "static", "global_percent": 100}
    if key == "custom":
        return {"preset": "custom", "mode": "static", "global_percent": 50}
    raise ValueError(f"Unknown resource preset: {preset!r}")
