"""Durable Skill Forge store (JSON under data_dir/skills/)."""

from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .schema import SkillCandidate, SkillRegistryEntry, SkillVersion

_lock = threading.RLock()
INDEX_FILE = "index.json"
CANDIDATES_DIR = "candidates"
VERSIONS_DIR = "versions"
EVAL_DIR = "eval"
QUARANTINE_DIR = "quarantine"


def skills_root() -> Path:
    path = data_dir() / "skills"
    path.mkdir(parents=True, exist_ok=True)
    (path / CANDIDATES_DIR).mkdir(parents=True, exist_ok=True)
    (path / VERSIONS_DIR).mkdir(parents=True, exist_ok=True)
    (path / EVAL_DIR).mkdir(parents=True, exist_ok=True)
    (path / QUARANTINE_DIR).mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Path:
    return skills_root() / INDEX_FILE


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_index() -> dict[str, Any]:
    return {"skills": {}, "active": {}}


def _load_index_unlocked() -> dict[str, Any]:
    path = _index_path()
    if not path.exists():
        return _empty_index()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_index()
    if not isinstance(raw, dict):
        return _empty_index()
    raw.setdefault("skills", {})
    raw.setdefault("active", {})
    return raw


def _save_index_unlocked(index: dict[str, Any]) -> None:
    _index_path().write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")


def reset_skills_store() -> None:
    with _lock:
        root = skills_root()
        if root.exists():
            shutil.rmtree(root)
        skills_root()


def save_candidate(candidate: SkillCandidate) -> SkillCandidate:
    with _lock:
        path = skills_root() / CANDIDATES_DIR / f"{candidate.candidate_id}.json"
        path.write_text(
            json.dumps(candidate.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        index = _load_index_unlocked()
        skills = index.setdefault("skills", {})
        entry = skills.get(candidate.skill_id)
        if not isinstance(entry, dict):
            entry = SkillRegistryEntry(
                skill_id=candidate.skill_id,
                name=candidate.version.manifest.name,
                versions=[],
                created_at=candidate.created_at,
                updated_at=candidate.updated_at,
            ).model_dump(mode="json")
        versions = list(entry.get("versions") or [])
        vid = candidate.version.version_id
        if vid not in versions:
            versions.append(vid)
        entry["versions"] = versions
        entry["name"] = candidate.version.manifest.name
        entry["updated_at"] = candidate.updated_at
        skills[candidate.skill_id] = entry
        _save_index_unlocked(index)
        save_version(candidate.version)
    return candidate


def get_candidate(candidate_id: str) -> SkillCandidate | None:
    with _lock:
        path = skills_root() / CANDIDATES_DIR / f"{candidate_id}.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return SkillCandidate.model_validate(raw)


def list_candidates(*, status: str | None = None, limit: int = 100) -> list[SkillCandidate]:
    with _lock:
        root = skills_root() / CANDIDATES_DIR
        files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[SkillCandidate] = []
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            candidate = SkillCandidate.model_validate(raw)
        except Exception:
            continue
        if status and candidate.status.value != status:
            continue
        out.append(candidate)
        if len(out) >= limit:
            break
    return out


def save_version(version: SkillVersion) -> SkillVersion:
    with _lock:
        path = skills_root() / VERSIONS_DIR / f"{version.version_id}.json"
        if path.exists():
            existing = SkillVersion.model_validate(json.loads(path.read_text(encoding="utf-8")))
            if existing.immutable:
                raise PermissionError(
                    f"skill version {version.version_id} is immutable; create a new version instead"
                )
        path.write_text(
            json.dumps(version.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return version


def get_version(version_id: str) -> SkillVersion | None:
    with _lock:
        path = skills_root() / VERSIONS_DIR / f"{version_id}.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return SkillVersion.model_validate(raw)


def set_active_version(skill_id: str, version_id: str) -> None:
    with _lock:
        index = _load_index_unlocked()
        active = index.setdefault("active", {})
        active[skill_id] = version_id
        skills = index.setdefault("skills", {})
        entry = skills.get(skill_id)
        if isinstance(entry, dict):
            entry["active_version_id"] = version_id
            entry["updated_at"] = utc_now()
            skills[skill_id] = entry
        _save_index_unlocked(index)


def get_active_version_id(skill_id: str) -> str | None:
    with _lock:
        index = _load_index_unlocked()
        value = (index.get("active") or {}).get(skill_id)
        return str(value) if value else None


def clear_active_version(skill_id: str) -> None:
    with _lock:
        index = _load_index_unlocked()
        active = index.setdefault("active", {})
        active.pop(skill_id, None)
        skills = index.setdefault("skills", {})
        entry = skills.get(skill_id)
        if isinstance(entry, dict):
            entry["active_version_id"] = None
            entry["updated_at"] = utc_now()
            skills[skill_id] = entry
        _save_index_unlocked(index)


def list_skills() -> list[SkillRegistryEntry]:
    with _lock:
        index = _load_index_unlocked()
        skills = index.get("skills") or {}
        active = index.get("active") or {}
    out: list[SkillRegistryEntry] = []
    for skill_id, raw in skills.items():
        if not isinstance(raw, dict):
            continue
        payload = dict(raw)
        payload["skill_id"] = skill_id
        if skill_id in active and not payload.get("active_version_id"):
            payload["active_version_id"] = active[skill_id]
        out.append(SkillRegistryEntry.model_validate(payload))
    return sorted(out, key=lambda item: item.name)


def eval_workspace(candidate_id: str) -> Path:
    path = skills_root() / EVAL_DIR / candidate_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def quarantine_path(import_id: str) -> Path:
    path = skills_root() / QUARANTINE_DIR / import_id
    path.mkdir(parents=True, exist_ok=True)
    return path
