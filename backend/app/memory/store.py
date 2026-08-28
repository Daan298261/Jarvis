from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .schema import AgentRepoMeta, ContextRepoVersion, MutationRecord, SCHEMA_VERSION

_lock = threading.RLock()
META_FILE = "meta.json"
HISTORY_FILE = "history.json"


def context_repos_root() -> Path:
    path = data_dir() / "context-repos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _agent_dir(agent_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in agent_id)
    path = context_repos_root() / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _meta_path(agent_id: str) -> Path:
    return _agent_dir(agent_id) / META_FILE


def _history_path(agent_id: str) -> Path:
    return _agent_dir(agent_id) / HISTORY_FILE


def _version_path(agent_id: str, version: int) -> Path:
    return _agent_dir(agent_id) / f"v{version}.json"


def reset_context_repo_store() -> None:
    with _lock:
        root = context_repos_root()
        for child in root.iterdir():
            if child.is_dir():
                for nested in child.glob("*"):
                    if nested.is_file():
                        nested.unlink()
                child.rmdir()
            elif child.is_file():
                child.unlink()
        root.mkdir(parents=True, exist_ok=True)


def load_meta(agent_id: str) -> AgentRepoMeta | None:
    with _lock:
        path = _meta_path(agent_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return AgentRepoMeta.model_validate(raw)


def save_meta(meta: AgentRepoMeta) -> None:
    with _lock:
        _meta_path(meta.agent_id).write_text(
            json.dumps(meta.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )


def save_version(repo: ContextRepoVersion) -> None:
    with _lock:
        _version_path(repo.agent_id, repo.version).write_text(
            json.dumps(repo.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )


def load_version(agent_id: str, version: int) -> ContextRepoVersion | None:
    with _lock:
        path = _version_path(agent_id, version)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return ContextRepoVersion.model_validate(raw)


def list_version_numbers(agent_id: str) -> list[int]:
    with _lock:
        agent_path = _agent_dir(agent_id)
        versions: list[int] = []
        for child in agent_path.glob("v*.json"):
            stem = child.stem
            if stem.startswith("v") and stem[1:].isdigit():
                versions.append(int(stem[1:]))
        return sorted(versions)


def _load_history_unlocked(agent_id: str) -> list[dict[str, Any]]:
    path = _history_path(agent_id)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return raw


def _save_history_unlocked(agent_id: str, history: list[dict[str, Any]]) -> None:
    _history_path(agent_id).write_text(
        json.dumps(history[-500:], indent=2, sort_keys=True),
        encoding="utf-8",
    )


def append_mutation(record: MutationRecord) -> None:
    with _lock:
        history = _load_history_unlocked(record.agent_id)
        history.append(record.model_dump(mode="json"))
        _save_history_unlocked(record.agent_id, history)


def load_history(agent_id: str, *, limit: int = 100) -> list[MutationRecord]:
    with _lock:
        raw = _load_history_unlocked(agent_id)
    items = [MutationRecord.model_validate(item) for item in raw if isinstance(item, dict)]
    return items[-max(1, min(limit, 500)) :]


def get_mutation(agent_id: str, mutation_id: str) -> MutationRecord | None:
    for record in load_history(agent_id, limit=500):
        if record.mutation_id == mutation_id:
            return record
    return None


def mark_mutation_reverted(agent_id: str, mutation_id: str, *, reverted_by: str) -> None:
    with _lock:
        history = _load_history_unlocked(agent_id)
        for item in history:
            if isinstance(item, dict) and item.get("mutation_id") == mutation_id:
                item["reverted_by"] = reverted_by
                break
        _save_history_unlocked(agent_id, history)


def new_mutation_id() -> str:
    return str(uuid.uuid4())


def new_entry_id() -> str:
    return str(uuid.uuid4())


def ensure_initial_repo(agent_id: str) -> ContextRepoVersion:
    meta = load_meta(agent_id)
    if meta is not None:
        current = load_version(agent_id, meta.current_version)
        if current is not None:
            return current

    now = _utc_now()
    repo = ContextRepoVersion(
        agent_id=agent_id,
        version=1,
        created_at=now,
        parent_version=None,
        entries=[],
    )
    with _lock:
        save_version(repo)
        save_meta(
            AgentRepoMeta(
                agent_id=agent_id,
                current_version=1,
                created_at=now,
                updated_at=now,
            )
        )
    return repo
