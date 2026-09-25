"""Content hashing and HMAC signatures for skill manifests."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

from .schema import SkillManifest

_ENV_SECRET = "JARVIS_SKILL_FORGE_SIGNING_KEY"
_DEFAULT_DEV_SECRET = "jarvis-skill-forge-dev-key"


def _signing_secret() -> str:
    return os.environ.get(_ENV_SECRET) or _DEFAULT_DEV_SECRET


def canonical_manifest_bytes(manifest: SkillManifest) -> bytes:
    payload = manifest.model_dump(mode="json")
    payload.pop("content_hash", None)
    payload.pop("signature", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_content_hash(manifest: SkillManifest) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def compute_signature(manifest: SkillManifest, *, secret: str | None = None) -> str:
    key = (secret or _signing_secret()).encode("utf-8")
    digest = hmac.new(key, canonical_manifest_bytes(manifest), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


def attach_hash_and_signature(manifest: SkillManifest, *, secret: str | None = None) -> SkillManifest:
    updated = manifest.model_copy(deep=True)
    updated.content_hash = compute_content_hash(updated)
    updated.signature = compute_signature(updated, secret=secret)
    return updated


def verify_manifest_integrity(manifest: SkillManifest, *, secret: str | None = None) -> dict[str, Any]:
    expected_hash = compute_content_hash(manifest)
    hash_ok = hmac.compare_digest(manifest.content_hash or "", expected_hash)
    expected_sig = compute_signature(manifest, secret=secret)
    sig_ok = hmac.compare_digest(manifest.signature or "", expected_sig)
    return {
        "hash_valid": hash_ok,
        "signature_valid": sig_ok,
        "content_hash": expected_hash,
        "valid": hash_ok and sig_ok,
    }
