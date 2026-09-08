from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken

from ..config import data_dir

Relationship = Literal["owner", "household_member", "trusted_person"]
_STORE_VERSION = 1


@dataclass(frozen=True)
class IdentityEnrollment:
    identity_id: str
    display_name: str
    relationship: Relationship
    created_at: datetime
    embedding_model: str
    embedding_version: int
    embeddings: list[list[float]]


class IdentityStore:
    """Encrypted-at-rest local biometric embedding store.

    The store contains embedding vectors and minimum enrollment metadata only. It
    intentionally has no image/photo fields and no synchronization hooks.
    """

    encrypted_at_rest = True

    def __init__(self, path: Path | None = None, key_path: Path | None = None) -> None:
        self.path = path or (data_dir() / "identity_embeddings.enc")
        self.key_path = key_path or (data_dir() / "identity_embeddings.key")
        self._lock = threading.RLock()

    def list_all(self) -> list[IdentityEnrollment]:
        with self._lock:
            payload = self._load_unlocked()
            return [self._decode(item) for item in payload.get("enrollments", [])]

    def get(self, identity_id: str) -> IdentityEnrollment | None:
        identity_id = identity_id.strip().lower()
        return next((item for item in self.list_all() if item.identity_id == identity_id), None)

    def count(self) -> int:
        return len(self.list_all())

    def upsert(self, enrollment: IdentityEnrollment) -> None:
        with self._lock:
            payload = self._load_unlocked()
            items = [item for item in payload.get("enrollments", []) if item.get("identity_id") != enrollment.identity_id]
            items.append(self._encode(enrollment))
            payload["enrollments"] = items
            self._save_unlocked(payload)

    def delete(self, identity_id: str) -> bool:
        identity_id = identity_id.strip().lower()
        with self._lock:
            payload = self._load_unlocked()
            before = len(payload.get("enrollments", []))
            payload["enrollments"] = [
                item for item in payload.get("enrollments", []) if item.get("identity_id") != identity_id
            ]
            deleted = len(payload["enrollments"]) != before
            if deleted:
                self._save_unlocked(payload)
            return deleted

    def reset(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    self.path.unlink()
                except OSError:
                    self._save_unlocked(self._empty())

    def _load_unlocked(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            plaintext = self._fernet().decrypt(self.path.read_bytes())
            payload = json.loads(plaintext.decode("utf-8"))
        except (OSError, InvalidToken, json.JSONDecodeError, UnicodeDecodeError):
            return self._empty()
        if not isinstance(payload, dict) or payload.get("version") != _STORE_VERSION:
            return self._empty()
        if not isinstance(payload.get("enrollments"), list):
            return self._empty()
        return payload

    def _save_unlocked(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload["version"] = _STORE_VERSION
        plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        encrypted = self._fernet().encrypt(plaintext)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(encrypted)
        _restrict_permissions(tmp)
        tmp.replace(self.path)
        _restrict_permissions(self.path)

    def _fernet(self) -> Fernet:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            key = Fernet.generate_key()
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(key)
            except Exception:
                try:
                    self.key_path.unlink(missing_ok=True)
                finally:
                    raise
        _restrict_permissions(self.key_path)
        return Fernet(self.key_path.read_bytes().strip())

    @staticmethod
    def _empty() -> dict:
        return {"version": _STORE_VERSION, "enrollments": []}

    @staticmethod
    def _encode(enrollment: IdentityEnrollment) -> dict:
        return {
            "identity_id": enrollment.identity_id,
            "display_name": enrollment.display_name,
            "relationship": enrollment.relationship,
            "created_at": enrollment.created_at.isoformat(),
            "embedding_model": enrollment.embedding_model,
            "embedding_version": enrollment.embedding_version,
            "embeddings": enrollment.embeddings,
        }

    @staticmethod
    def _decode(item: dict) -> IdentityEnrollment:
        return IdentityEnrollment(
            identity_id=str(item["identity_id"]),
            display_name=str(item["display_name"]),
            relationship=item["relationship"],
            created_at=datetime.fromisoformat(str(item["created_at"]).replace("Z", "+00:00")),
            embedding_model=str(item["embedding_model"]),
            embedding_version=int(item["embedding_version"]),
            embeddings=[[float(value) for value in vector] for vector in item.get("embeddings", [])],
        )


def _restrict_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Windows ACLs are not represented by POSIX mode bits; the file remains
        # local to Jarvis's data directory and encrypted independently.
        pass
