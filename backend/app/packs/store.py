from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .schema import InstalledPack, ResourceRecord

_lock = threading.RLock()
STATE_FILE = "state.json"
TRUSTED_KEYS_FILE = "trusted_keys.json"


def packs_root() -> Path:
    path = data_dir() / "packs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resources_root() -> Path:
    path = packs_root() / "resources"
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshots_root() -> Path:
    path = packs_root() / "snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path() -> Path:
    return packs_root() / STATE_FILE


def _trusted_keys_path() -> Path:
    return packs_root() / TRUSTED_KEYS_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_state() -> dict[str, Any]:
    return {"installations": {}, "resources": {}, "history": []}


def _load_state_unlocked() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return _empty_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_state()
    if not isinstance(raw, dict):
        return _empty_state()
    raw.setdefault("installations", {})
    raw.setdefault("resources", {})
    raw.setdefault("history", [])
    return raw


def _save_state_unlocked(state: dict[str, Any]) -> None:
    _state_path().write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def reset_packs_store() -> None:
    with _lock:
        root = packs_root()
        for child in root.iterdir():
            if child.is_dir():
                for nested in child.rglob("*"):
                    if nested.is_file():
                        nested.unlink()
                for nested in sorted(child.rglob("*"), reverse=True):
                    if nested.is_dir():
                        nested.rmdir()
                child.rmdir()
            elif child.is_file():
                child.unlink()
        root.mkdir(parents=True, exist_ok=True)


def load_state() -> dict[str, Any]:
    with _lock:
        return _load_state_unlocked()


def save_state(state: dict[str, Any]) -> None:
    with _lock:
        _save_state_unlocked(state)


def list_installations() -> list[InstalledPack]:
    state = load_state()
    installations = state.get("installations") or {}
    items: list[InstalledPack] = []
    for raw in installations.values():
        if isinstance(raw, dict):
            items.append(InstalledPack.model_validate(raw))
    return sorted(items, key=lambda item: item.id)


def get_installation(pack_id: str) -> InstalledPack | None:
    state = load_state()
    raw = (state.get("installations") or {}).get(pack_id)
    if not isinstance(raw, dict):
        return None
    return InstalledPack.model_validate(raw)


def set_installation(record: InstalledPack) -> None:
    with _lock:
        state = _load_state_unlocked()
        installations = state.setdefault("installations", {})
        installations[record.id] = record.model_dump(mode="json")
        _save_state_unlocked(state)


def remove_installation(pack_id: str) -> InstalledPack | None:
    with _lock:
        state = _load_state_unlocked()
        installations = state.setdefault("installations", {})
        raw = installations.pop(pack_id, None)
        _save_state_unlocked(state)
    if not isinstance(raw, dict):
        return None
    return InstalledPack.model_validate(raw)


def list_resource_records() -> list[ResourceRecord]:
    state = load_state()
    resources = state.get("resources") or {}
    items: list[ResourceRecord] = []
    for raw in resources.values():
        if isinstance(raw, dict):
            items.append(ResourceRecord.model_validate(raw))
    return items


def get_resource_record(resource_id: str) -> ResourceRecord | None:
    state = load_state()
    raw = (state.get("resources") or {}).get(resource_id)
    if not isinstance(raw, dict):
        return None
    return ResourceRecord.model_validate(raw)


def set_resource_record(record: ResourceRecord) -> None:
    with _lock:
        state = _load_state_unlocked()
        resources = state.setdefault("resources", {})
        resources[record.resource_id] = record.model_dump(mode="json")
        _save_state_unlocked(state)
        resource_path = resources_root() / f"{record.resource_id}.json"
        resource_path.write_text(
            json.dumps(record.data, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def remove_resource_record(resource_id: str) -> ResourceRecord | None:
    with _lock:
        state = _load_state_unlocked()
        resources = state.setdefault("resources", {})
        raw = resources.pop(resource_id, None)
        _save_state_unlocked(state)
    resource_path = resources_root() / f"{resource_id}.json"
    if resource_path.exists():
        resource_path.unlink()
    if not isinstance(raw, dict):
        return None
    return ResourceRecord.model_validate(raw)


def list_resources_for_pack(pack_id: str) -> list[ResourceRecord]:
    return [item for item in list_resource_records() if item.pack_id == pack_id]


def append_history(event: dict[str, Any]) -> None:
    with _lock:
        state = _load_state_unlocked()
        history = state.setdefault("history", [])
        history.append(event)
        state["history"] = history[-200:]
        _save_state_unlocked(state)


def create_snapshot(pack_id: str, payload: dict[str, Any]) -> str:
    snapshot_id = f"{pack_id}-{uuid.uuid4().hex[:12]}"
    snapshot_dir = snapshots_root() / pack_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"{snapshot_id}.json"
    snapshot_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return snapshot_id


def load_snapshot(pack_id: str, snapshot_id: str) -> dict[str, Any] | None:
    snapshot_path = snapshots_root() / pack_id / f"{snapshot_id}.json"
    if not snapshot_path.exists():
        return None
    try:
        raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def latest_snapshot_id(pack_id: str) -> str | None:
    snapshot_dir = snapshots_root() / pack_id
    if not snapshot_dir.exists():
        return None
    candidates = sorted(snapshot_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    return candidates[0].stem


def load_trusted_keys() -> dict[str, str]:
    path = _trusted_keys_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def save_trusted_keys(keys: dict[str, str]) -> None:
    with _lock:
        _trusted_keys_path().write_text(json.dumps(keys, indent=2, sort_keys=True), encoding="utf-8")


def history_event(
    event_type: str,
    pack_id: str,
    *,
    version: str | None = None,
    snapshot_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "event": event_type,
        "pack_id": pack_id,
        "version": version,
        "snapshot_id": snapshot_id,
        "timestamp": _utc_now(),
        "details": details or {},
    }
