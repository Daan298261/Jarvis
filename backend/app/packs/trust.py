from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from .. import __version__ as JARVIS_VERSION
from ..tools.registry import REGISTRY
from .schema import PackManifest, PackTrust, version_satisfies
from .store import load_trusted_keys, save_trusted_keys


class TrustError(ValueError):
    pass


class CapabilityPolicyError(ValueError):
    pass


def _canonical_payload(manifest: PackManifest) -> bytes:
    payload = manifest.model_dump(mode="json")
    trust = dict(payload.get("trust") or {})
    trust.pop("signature", None)
    payload["trust"] = trust
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_signature(manifest: PackManifest, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), _canonical_payload(manifest), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


def verify_signature(manifest: PackManifest, *, allow_user_owned: bool = True) -> dict[str, Any]:
    trust: PackTrust = manifest.trust
    signature = (trust.signature or "").strip()
    signer_key_id = (trust.signer_key_id or "").strip()
    trusted_keys = load_trusted_keys()

    if not signature:
        if trust.trust_level == "user" and allow_user_owned:
            return {
                "signature_valid": True,
                "trust_level": "user",
                "signer_key_id": None,
                "message": "User-owned pack without signature",
            }
        return {
            "signature_valid": False,
            "trust_level": trust.trust_level,
            "signer_key_id": signer_key_id or None,
            "message": "Pack is missing a signature",
        }

    if not signer_key_id or signer_key_id not in trusted_keys:
        return {
            "signature_valid": False,
            "trust_level": trust.trust_level,
            "signer_key_id": signer_key_id or None,
            "message": "Unknown or missing signer key",
        }

    expected = compute_signature(manifest, trusted_keys[signer_key_id])
    valid = hmac.compare_digest(signature, expected)
    return {
        "signature_valid": valid,
        "trust_level": "verified" if valid else "untrusted",
        "signer_key_id": signer_key_id,
        "message": "Signature verified" if valid else "Signature mismatch",
    }


def enforce_trust_policy(manifest: PackManifest, *, require_signature: bool = False) -> dict[str, Any]:
    result = verify_signature(manifest)
    if require_signature and not result["signature_valid"]:
        raise TrustError(result["message"])
    if manifest.trust.trust_level == "untrusted" and not result["signature_valid"]:
        raise TrustError("Pack is marked untrusted and failed signature verification")
    return result


def evaluate_capabilities(manifest: PackManifest) -> dict[str, Any]:
    available = set(REGISTRY.tools.keys())
    required = [str(item) for item in manifest.capabilities.required_tools]
    denied = [str(item) for item in manifest.capabilities.denied_tools]
    missing = sorted(tool for tool in required if tool not in available)
    denied_present = sorted(tool for tool in denied if tool in available)
    allowed = not missing and not denied_present
    return {
        "required_tools": required,
        "denied_tools": denied,
        "missing": missing,
        "denied_present": denied_present,
        "allowed": allowed,
    }


def enforce_capability_policy(manifest: PackManifest) -> dict[str, Any]:
    result = evaluate_capabilities(manifest)
    if result["missing"]:
        raise CapabilityPolicyError(
            "Pack requires unavailable tools: " + ", ".join(result["missing"])
        )
    if result["denied_present"]:
        raise CapabilityPolicyError(
            "Pack denies tools that are currently enabled: " + ", ".join(result["denied_present"])
        )
    return result


def check_jarvis_version(manifest: PackManifest) -> dict[str, Any]:
    satisfied = version_satisfies(JARVIS_VERSION, f">={manifest.min_jarvis_version}")
    return {
        "jarvis_version": JARVIS_VERSION,
        "min_jarvis_version": manifest.min_jarvis_version,
        "satisfied": satisfied,
    }


def add_trusted_key(key_id: str, secret: str) -> dict[str, str]:
    keys = load_trusted_keys()
    keys[key_id] = secret
    save_trusted_keys(keys)
    return keys


def list_trusted_key_ids() -> list[str]:
    return sorted(load_trusted_keys().keys())
