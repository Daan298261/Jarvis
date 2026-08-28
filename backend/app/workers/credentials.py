from __future__ import annotations

import json
import secrets
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir

_lock = threading.RLock()


class CredentialError(ValueError):
    """Raised when a credential operation is refused or fails."""


@dataclass
class WorkerCredential:
    id: str
    environment_id: str
    capability: str
    label: str
    created_at: str
    revoked_at: str | None = None

    def as_dict(self, *, include_secret: bool = False, secret: str | None = None) -> dict[str, Any]:
        payload = asdict(self)
        if include_secret and secret is not None:
            payload["secret"] = secret
        return payload


def credentials_root() -> Path:
    path = data_dir() / "worker-environments" / ".credentials"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _vault_path(environment_id: str) -> Path:
    return credentials_root() / f"{environment_id}.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_vault(environment_id: str) -> dict[str, Any]:
    path = _vault_path(environment_id)
    if not path.exists():
        return {"credentials": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"credentials": []}
    if not isinstance(payload, dict):
        return {"credentials": []}
    if not isinstance(payload.get("credentials"), list):
        payload["credentials"] = []
    return payload


def _save_vault(environment_id: str, payload: dict[str, Any]) -> None:
    path = _vault_path(environment_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def store_credential(
    environment_id: str,
    *,
    capability: str,
    label: str,
    secret: str,
    credential_id: str | None = None,
) -> dict[str, Any]:
    capability = str(capability or "").strip()
    label = str(label or "").strip()
    secret = str(secret or "")
    if not capability:
        raise CredentialError("capability is required")
    if not label:
        raise CredentialError("label is required")
    if not secret:
        raise CredentialError("secret is required")

    cred_id = credential_id or str(uuid.uuid4())
    now = _utcnow()
    with _lock:
        vault = _load_vault(environment_id)
        rows = vault.get("credentials") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("id") == cred_id and not row.get("revoked_at"):
                raise CredentialError(f"Credential already exists: {cred_id}")
        rows.append(
            {
                "id": cred_id,
                "environment_id": environment_id,
                "capability": capability,
                "label": label,
                "secret": secret,
                "created_at": now,
                "revoked_at": None,
            }
        )
        vault["credentials"] = rows
        _save_vault(environment_id, vault)

    return WorkerCredential(
        id=cred_id,
        environment_id=environment_id,
        capability=capability,
        label=label,
        created_at=now,
    ).as_dict()


def list_credentials(environment_id: str, *, include_revoked: bool = False) -> list[dict[str, Any]]:
    with _lock:
        vault = _load_vault(environment_id)
        out: list[dict[str, Any]] = []
        for row in vault.get("credentials") or []:
            if not isinstance(row, dict):
                continue
            if row.get("revoked_at") and not include_revoked:
                continue
            out.append(
                WorkerCredential(
                    id=str(row.get("id") or ""),
                    environment_id=environment_id,
                    capability=str(row.get("capability") or ""),
                    label=str(row.get("label") or ""),
                    created_at=str(row.get("created_at") or ""),
                    revoked_at=row.get("revoked_at"),
                ).as_dict()
            )
        return out


def get_credential_secret(environment_id: str, credential_id: str) -> str | None:
    with _lock:
        vault = _load_vault(environment_id)
        for row in vault.get("credentials") or []:
            if not isinstance(row, dict):
                continue
            if row.get("id") == credential_id and not row.get("revoked_at"):
                return str(row.get("secret") or "")
    return None


def revoke_credential(environment_id: str, credential_id: str) -> dict[str, Any]:
    now = _utcnow()
    with _lock:
        vault = _load_vault(environment_id)
        found: dict[str, Any] | None = None
        for row in vault.get("credentials") or []:
            if not isinstance(row, dict):
                continue
            if row.get("id") != credential_id:
                continue
            if row.get("revoked_at"):
                raise CredentialError(f"Credential already revoked: {credential_id}")
            row["revoked_at"] = now
            found = row
            break
        if found is None:
            raise CredentialError(f"Credential not found: {credential_id}")
        _save_vault(environment_id, vault)
        return WorkerCredential(
            id=str(found.get("id") or ""),
            environment_id=environment_id,
            capability=str(found.get("capability") or ""),
            label=str(found.get("label") or ""),
            created_at=str(found.get("created_at") or ""),
            revoked_at=now,
        ).as_dict()


def delete_credentials_for_environment(environment_id: str) -> None:
    with _lock:
        path = _vault_path(environment_id)
        if path.exists():
            path.unlink()


def generate_credential_secret() -> str:
    return secrets.token_urlsafe(32)
