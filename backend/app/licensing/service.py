from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .cluster import get_cluster_id
from .lease import (
    LicenseError,
    SignedLease,
    get_stored_lease,
    parse_iso_datetime,
    verify_lease_signature,
)
from .store import load_state, set_lease, update_validation_state

CLOCK_SKEW_SECONDS = 300


def _now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _load_current_lease() -> SignedLease | None:
    return get_stored_lease()


def _effective_expiry(payload) -> datetime:
    expires = parse_iso_datetime(payload.expires_at)
    grace = max(0, int(payload.grace_seconds))
    return expires + timedelta(seconds=grace)


def _detect_clock_tamper(last_validated_at: str | None, now: datetime) -> str | None:
    if not last_validated_at:
        return None
    try:
        previous = parse_iso_datetime(last_validated_at)
    except Exception:
        return None
    if now + timedelta(seconds=CLOCK_SKEW_SECONDS) < previous:
        return "System clock appears to have moved backward since last validation"
    return None


def validate_offline(*, now: datetime | None = None) -> dict[str, Any]:
    """Validate the stored lease offline. Never deletes customer data."""
    current = _now(now)
    state = load_state()
    lease = _load_current_lease()
    cluster_id = get_cluster_id()

    if lease is None:
        result = {
            "valid": False,
            "status": "unlicensed",
            "message": "No active platform lease",
            "cluster_id": cluster_id,
            "in_grace": False,
        }
        update_validation_state(status=result["status"], message=result["message"])
        return result

    tamper = _detect_clock_tamper(state.get("last_validated_at"), current)
    if tamper:
        result = {
            "valid": False,
            "status": "tamper_detected",
            "message": tamper,
            "cluster_id": cluster_id,
            "lease_id": lease.payload.lease_id,
            "in_grace": False,
        }
        update_validation_state(status=result["status"], message=result["message"])
        return result

    if not verify_lease_signature(lease):
        result = {
            "valid": False,
            "status": "invalid_signature",
            "message": "Lease signature verification failed",
            "cluster_id": cluster_id,
            "lease_id": lease.payload.lease_id,
            "in_grace": False,
        }
        update_validation_state(status=result["status"], message=result["message"])
        return result

    if lease.payload.cluster_id != cluster_id:
        result = {
            "valid": False,
            "status": "cluster_mismatch",
            "message": "Lease cluster identity does not match this installation",
            "cluster_id": cluster_id,
            "lease_id": lease.payload.lease_id,
            "in_grace": False,
        }
        update_validation_state(status=result["status"], message=result["message"])
        return result

    issued = parse_iso_datetime(lease.payload.issued_at)
    if current + timedelta(seconds=CLOCK_SKEW_SECONDS) < issued:
        result = {
            "valid": False,
            "status": "not_yet_valid",
            "message": "Lease is not yet valid",
            "cluster_id": cluster_id,
            "lease_id": lease.payload.lease_id,
            "in_grace": False,
        }
        update_validation_state(status=result["status"], message=result["message"])
        return result

    expires = parse_iso_datetime(lease.payload.expires_at)
    effective = _effective_expiry(lease.payload)
    in_grace = expires < current <= effective

    if current > effective:
        result = {
            "valid": False,
            "status": "expired",
            "message": "Platform lease has expired",
            "cluster_id": cluster_id,
            "lease_id": lease.payload.lease_id,
            "expires_at": lease.payload.expires_at,
            "in_grace": False,
        }
        update_validation_state(status=result["status"], message=result["message"])
        return result

    validated_at = current.replace(microsecond=0).isoformat()
    status = "grace" if in_grace else "active"
    message = "Lease is within offline grace period" if in_grace else "Lease is valid"
    update_validation_state(status=status, message=message, validated_at=validated_at)
    return {
        "valid": True,
        "status": status,
        "message": message,
        "cluster_id": cluster_id,
        "lease_id": lease.payload.lease_id,
        "tier": lease.payload.tier,
        "features": list(lease.payload.features),
        "pack_entitlements": list(lease.payload.pack_entitlements),
        "issued_at": lease.payload.issued_at,
        "expires_at": lease.payload.expires_at,
        "grace_seconds": lease.payload.grace_seconds,
        "in_grace": in_grace,
        "last_validated_at": validated_at,
    }


def refresh_lease(lease: SignedLease, *, now: datetime | None = None) -> dict[str, Any]:
    """Accept a refreshed signed lease on reconnect. Does not delete local data."""
    current = _now(now)
    cluster_id = get_cluster_id()

    if not verify_lease_signature(lease):
        raise LicenseError("Lease signature verification failed")

    if lease.payload.cluster_id != cluster_id:
        raise LicenseError("Lease cluster identity does not match this installation")

    issued = parse_iso_datetime(lease.payload.issued_at)
    if current + timedelta(seconds=CLOCK_SKEW_SECONDS) < issued:
        raise LicenseError("Lease is not yet valid")

    set_lease(lease.model_dump(mode="json"))
    return validate_offline(now=current)


def get_license_status() -> dict[str, Any]:
    state = load_state()
    validation = validate_offline()
    lease = _load_current_lease()
    return {
        "cluster_id": get_cluster_id(),
        "validation": validation,
        "lease_present": lease is not None,
        "last_status": state.get("last_status"),
        "last_message": state.get("last_message"),
        "last_validated_at": state.get("last_validated_at"),
    }
