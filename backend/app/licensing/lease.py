from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, Field

# Embedded dev/test vendor keypair. Override public key via JARVIS_LICENSE_PUBLIC_KEY.
TEST_SIGNING_PRIVATE_KEY = Ed25519PrivateKey.generate()
DEFAULT_VENDOR_PUBLIC_KEY_B64 = base64.b64encode(
    TEST_SIGNING_PRIVATE_KEY.public_key().public_bytes_raw()
).decode("ascii")


class LeasePayload(BaseModel):
    lease_id: str
    cluster_id: str
    tier: str
    features: list[str] = Field(default_factory=list)
    pack_entitlements: list[str] = Field(default_factory=list)
    issued_at: str
    expires_at: str
    grace_seconds: int = 0


class SignedLease(BaseModel):
    payload: LeasePayload
    signature: str
    signer_key_id: str = "jarvis-vendor"


class LicenseError(ValueError):
    pass


def get_vendor_public_key() -> Ed25519PublicKey:
    override = os.environ.get("JARVIS_LICENSE_PUBLIC_KEY", "").strip()
    if override:
        raw = base64.b64decode(override)
        return Ed25519PublicKey.from_public_bytes(raw)
    raw = base64.b64decode(DEFAULT_VENDOR_PUBLIC_KEY_B64)
    return Ed25519PublicKey.from_public_bytes(raw)


def _canonical_payload_bytes(payload: LeasePayload) -> bytes:
    return json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_lease(payload: LeasePayload, private_key: Ed25519PrivateKey) -> SignedLease:
    signature = private_key.sign(_canonical_payload_bytes(payload))
    return SignedLease(
        payload=payload,
        signature=base64.b64encode(signature).decode("ascii"),
    )


def verify_lease_signature(lease: SignedLease) -> bool:
    try:
        public_key = get_vendor_public_key()
        signature = base64.b64decode(lease.signature)
        public_key.verify(signature, _canonical_payload_bytes(lease.payload))
        return True
    except Exception:
        return False


def parse_signed_lease(data: dict[str, Any]) -> SignedLease:
    return SignedLease.model_validate(data)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_stored_lease() -> SignedLease | None:
    from .store import load_state

    raw = load_state().get("lease")
    if not raw:
        return None
    try:
        return parse_signed_lease(raw)
    except Exception:
        return None
