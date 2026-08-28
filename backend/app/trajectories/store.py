from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .redaction import redact_trajectory_payload
from .schema import JarvisTrajectoryV1, SCHEMA_VERSION

_lock = threading.RLock()
INDEX_FILE = "index.json"


def trajectories_root() -> Path:
    path = data_dir() / "trajectories"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Path:
    return trajectories_root() / INDEX_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_index_unlocked() -> dict[str, Any]:
    path = _index_path()
    if not path.exists():
        return {"entries": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"entries": []}
    if not isinstance(raw, dict):
        return {"entries": []}
    raw.setdefault("entries", [])
    return raw


def _save_index_unlocked(index: dict[str, Any]) -> None:
    _index_path().write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")


def _trajectory_path(trajectory_id: str) -> Path:
    return trajectories_root() / f"{trajectory_id}.json"


def reset_trajectories_store() -> None:
    with _lock:
        root = trajectories_root()
        for child in root.glob("*.json"):
            child.unlink()
        _save_index_unlocked({"entries": []})


def save_trajectory(trajectory: JarvisTrajectoryV1) -> JarvisTrajectoryV1:
    payload = trajectory.model_dump(mode="json")
    payload = redact_trajectory_payload(payload)
    validated = JarvisTrajectoryV1.model_validate(payload)

    with _lock:
        path = _trajectory_path(validated.trajectory_id)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

        index = _load_index_unlocked()
        entries = index.setdefault("entries", [])
        summary = {
            "trajectory_id": validated.trajectory_id,
            "schema_version": SCHEMA_VERSION,
            "harness": validated.provenance.harness,
            "model": validated.provenance.model,
            "goal": validated.goal,
            "outcome_status": validated.outcome.status,
            "outcome_verified": validated.outcome.verified,
            "trusted": validated.provenance.trusted,
            "imported_at": validated.provenance.imported_at,
            "event_count": len(validated.events),
        }
        replaced = False
        for idx, entry in enumerate(entries):
            if entry.get("trajectory_id") == validated.trajectory_id:
                entries[idx] = summary
                replaced = True
                break
        if not replaced:
            entries.append(summary)
        entries.sort(key=lambda item: item.get("imported_at") or "", reverse=True)
        _save_index_unlocked(index)
    return validated


def list_trajectories(*, limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        entries = list(_load_index_unlocked().get("entries", []))
    return entries[: max(1, min(limit, 500))]


def get_trajectory(trajectory_id: str) -> JarvisTrajectoryV1 | None:
    with _lock:
        path = _trajectory_path(trajectory_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return JarvisTrajectoryV1.model_validate(raw)


def new_trajectory_id() -> str:
    return str(uuid.uuid4())
