from __future__ import annotations

import secrets
import uuid
from typing import Any

from .store import (
    load_inference_credentials,
    new_record_timestamp,
    save_inference_credentials,
)


class InferenceCredentialError(ValueError):
    pass


def list_inference_credentials(*, include_secrets: bool = False) -> list[dict[str, Any]]:
    payload = load_inference_credentials()
    results: list[dict[str, Any]] = []
    for item in payload.get("credentials", []):
        if not isinstance(item, dict):
            continue
        record = dict(item)
        if not include_secrets and "secret" in record:
            record["secret"] = _redact_secret(str(record.get("secret", "")))
        results.append(record)
    return results


def upsert_inference_credential(
    *,
    provider: str,
    label: str,
    secret: str,
    endpoint: str | None = None,
    credential_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = str(provider or "").strip()
    label = str(label or "").strip()
    secret = str(secret or "").strip()
    if not provider:
        raise InferenceCredentialError("provider is required")
    if not label:
        raise InferenceCredentialError("label is required")
    if not secret:
        raise InferenceCredentialError("secret is required")

    payload = load_inference_credentials()
    credentials = payload.setdefault("credentials", [])
    now = new_record_timestamp()
    record_id = credential_id or str(uuid.uuid4())

    for index, existing in enumerate(credentials):
        if not isinstance(existing, dict):
            continue
        if existing.get("id") == record_id:
            credentials[index] = {
                "id": record_id,
                "provider": provider,
                "label": label,
                "secret": secret,
                "endpoint": endpoint,
                "metadata": metadata or {},
                "created_at": existing.get("created_at", now),
                "updated_at": now,
            }
            save_inference_credentials(payload)
            return _public_view(credentials[index])

    credentials.append(
        {
            "id": record_id,
            "provider": provider,
            "label": label,
            "secret": secret,
            "endpoint": endpoint,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
    )
    save_inference_credentials(payload)
    return _public_view(credentials[-1])


def delete_inference_credential(credential_id: str) -> bool:
    credential_id = str(credential_id or "").strip()
    if not credential_id:
        raise InferenceCredentialError("credential_id is required")
    payload = load_inference_credentials()
    credentials = payload.get("credentials", [])
    kept = [item for item in credentials if isinstance(item, dict) and item.get("id") != credential_id]
    if len(kept) == len(credentials):
        return False
    payload["credentials"] = kept
    save_inference_credentials(payload)
    return True


def get_inference_credential(credential_id: str, *, include_secret: bool = False) -> dict[str, Any] | None:
    for item in load_inference_credentials().get("credentials", []):
        if isinstance(item, dict) and item.get("id") == credential_id:
            if include_secret:
                return dict(item)
            return _public_view(item)
    return None


def _public_view(record: dict[str, Any]) -> dict[str, Any]:
    view = dict(record)
    if "secret" in view:
        view["secret"] = _redact_secret(str(view.get("secret", "")))
    return view


def _redact_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 4:
        return secrets.token_hex(2)
    return f"{secret[:2]}…{secret[-2:]}"
