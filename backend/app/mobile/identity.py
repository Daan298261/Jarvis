from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException, Request

from ..auth import get_effective_private_key, load_settings
from .store import database, delete, get, put, rows

SESSION_SECONDS = 900
PAIRING_OWNER = "owner"
DEFAULT_PAIRING_TTL_MINUTES = 10
MIN_PAIRING_TTL_MINUTES = 5
MAX_PAIRING_TTL_MINUTES = 60
ENROLL_RATE_LIMIT = 5
ENROLL_RATE_WINDOW_SECONDS = 15 * 60

OBVIOUS_PAIRING_CODES = frozenset(
    {
        "000000",
        "111111",
        "222222",
        "333333",
        "444444",
        "555555",
        "666666",
        "777777",
        "888888",
        "999999",
        "123456",
        "654321",
        "012345",
        "543210",
        "123123",
        "112233",
    }
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def pairing_secret() -> str:
    key = get_effective_private_key(load_settings())
    if key:
        return key
    with database() as db:
        record = get(db, "secret", "pairing")
        if not record:
            record = {"value": secrets.token_urlsafe(48)}
            put(db, "secret", "pairing", record)
    return record["value"]


def hash_pairing_code(code: str) -> str:
    return hmac.new(pairing_secret().encode(), code.encode(), hashlib.sha256).hexdigest()


def public_key(encoded: str):
    try:
        key = serialization.load_der_public_key(base64.b64decode(encoded, validate=True))
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError()
        return key
    except (ValueError, TypeError):
        raise HTTPException(400, "Expected a P-256 public key in base64 DER format")


def fingerprint(encoded: str) -> str:
    key = public_key(encoded)
    return hashlib.sha256(
        key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()


def _random_pairing_code() -> str:
    for _ in range(64):
        code = f"{secrets.randbelow(1_000_000):06d}"
        if code not in OBVIOUS_PAIRING_CODES:
            return code
    raise HTTPException(503, "Could not generate a pairing code; try again")


def _clamp_pairing_ttl_minutes(ttl_minutes: int) -> int:
    return max(MIN_PAIRING_TTL_MINUTES, min(MAX_PAIRING_TTL_MINUTES, ttl_minutes))


def _invalidate_unclaimed_pairing_codes(db) -> None:
    for record in rows(db, "pairing_code"):
        if not record.get("claimed_by"):
            delete(db, "pairing_code", record["hash"])


def generate_pairing_code(ttl_minutes: int = DEFAULT_PAIRING_TTL_MINUTES) -> dict:
    ttl_minutes = _clamp_pairing_ttl_minutes(ttl_minutes)
    code = _random_pairing_code()
    code_hash = hash_pairing_code(code)
    now = time.time()
    expires_at = now + ttl_minutes * 60
    record = {
        "hash": code_hash,
        "id": str(uuid.uuid4()),
        "expires_at": expires_at,
        "claimed_by": None,
        "created_at": now,
        "ttl_minutes": ttl_minutes,
    }
    with database() as db:
        _invalidate_unclaimed_pairing_codes(db)
        put(db, "pairing_code", code_hash, record)
        put(
            db,
            "pairing_session",
            PAIRING_OWNER,
            {
                "active_hash": code_hash,
                "expires_at": expires_at,
                "updated_at": now,
                "display_code": code,
            },
        )
    return {
        "code": code,
        "expires_at": expires_at,
        "ttl_seconds": ttl_minutes * 60,
        "id": record["id"],
    }


def regenerate_pairing_code(ttl_minutes: int = DEFAULT_PAIRING_TTL_MINUTES) -> dict:
    return generate_pairing_code(ttl_minutes)


def pairing_code_status() -> dict:
    now = time.time()
    with database() as db:
        session = get(db, "pairing_session", PAIRING_OWNER)
        if not session:
            return {"active": False, "claimed": False, "ttl_remaining_seconds": 0}
        record = get(db, "pairing_code", session["active_hash"])
        if not record:
            return {"active": False, "claimed": False, "ttl_remaining_seconds": 0}
        remaining = max(0, int(record["expires_at"] - now))
        claimed = bool(record.get("claimed_by"))
        active = remaining > 0 and not claimed
        result = {
            "active": active,
            "claimed": claimed,
            "expires_at": record["expires_at"],
            "ttl_remaining_seconds": remaining,
            "id": record["id"],
        }
        if active and session.get("display_code"):
            result["code"] = session["display_code"]
        return result


def check_enroll_rate_limit(client_ip: str, device_fingerprint: str = "") -> None:
    key = f"enroll:{client_ip or 'unknown'}:{device_fingerprint[:16]}"
    now = time.time()
    with database() as db:
        bucket = get(db, "rate_limit", key) or {"attempts": []}
        attempts = [stamp for stamp in bucket["attempts"] if stamp > now - ENROLL_RATE_WINDOW_SECONDS]
        if len(attempts) >= ENROLL_RATE_LIMIT:
            raise HTTPException(429, "Too many pairing attempts. Wait and try again.")
        attempts.append(now)
        put(db, "rate_limit", key, {"attempts": attempts})


def _create_pending_device(db, encoded_key: str, name: str) -> dict:
    fp = fingerprint(encoded_key)
    device = {
        "id": str(uuid.uuid4()),
        "name": name[:100],
        "public_key": encoded_key,
        "fingerprint": fp,
        "status": "pending",
        "created_at": time.time(),
        "notifications": True,
        "critical_calls": False,
        "voice_profile_id": "",
        "push_token": "",
    }
    put(db, "device", device["id"], device)
    return device


def enroll_pairing_code(code: str, encoded_key: str, name: str, *, client_ip: str = "") -> dict:
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(400, "Pairing code must be exactly 6 digits")
    code_hash = hash_pairing_code(code)
    fp = fingerprint(encoded_key)
    check_enroll_rate_limit(client_ip, fp)
    with database() as db:
        record = get(db, "pairing_code", code_hash)
        session = get(db, "pairing_session", PAIRING_OWNER)
        if not record or record["expires_at"] < time.time():
            raise HTTPException(401, "Pairing code expired or invalid. Generate a new code on Jarvis.")
        if not session or session.get("active_hash") != code_hash:
            raise HTTPException(401, "Pairing code expired or invalid. Generate a new code on Jarvis.")
        if record["claimed_by"]:
            device = get(db, "device", record["claimed_by"])
            if device and device["fingerprint"] == fp and device["status"] != "revoked":
                return safe_device(device)
            raise HTTPException(409, "Pairing code already claimed")
        device = _create_pending_device(db, encoded_key, name)
        record["claimed_by"] = device["id"]
        put(db, "pairing_code", code_hash, record)
    return safe_device(device)


def invite(ttl: int = 3600) -> dict:
    token = secrets.token_urlsafe(32)
    value = {"id": str(uuid.uuid4()), "expires_at": time.time() + ttl, "claimed_by": None}
    with database() as db:
        put(db, "invitation", digest(token), value)
    return {**value, "invitation": token}


def enroll(token: str, encoded_key: str, name: str, *, client_ip: str = "") -> dict:
    fp = fingerprint(encoded_key)
    check_enroll_rate_limit(client_ip, fp)
    with database() as db:
        invitation = get(db, "invitation", digest(token))
        if not invitation or invitation["expires_at"] < time.time():
            raise HTTPException(401, "Invitation expired or invalid. Generate a new pairing invitation on Jarvis.")
        if invitation["claimed_by"]:
            device = get(db, "device", invitation["claimed_by"])
            if device and device["fingerprint"] == fp and device["status"] != "revoked":
                return safe_device(device)
            raise HTTPException(409, "Invitation already claimed")
        device = _create_pending_device(db, encoded_key, name)
        invitation["claimed_by"] = device["id"]
        put(db, "invitation", digest(token), invitation)
    return safe_device(device)


def safe_device(device: dict) -> dict:
    return {k: v for k, v in device.items() if k not in {"public_key", "push_token"}}


def set_status(device_id: str, status: str, expected_fingerprint: str | None = None):
    with database() as db:
        device = get(db, "device", device_id)
        if not device:
            raise HTTPException(404, "Device not found")
        if status == "active":
            if device["status"] != "pending" or expected_fingerprint != device["fingerprint"]:
                raise HTTPException(409, "Confirm the fingerprint of the pending device")
        device["status"] = status
        put(db, "device", device_id, device)
    return safe_device(device)


def challenge(device_id: str):
    now = time.time()
    with database() as db:
        device = get(db, "device", device_id)
        if not device or device["status"] == "revoked":
            raise HTTPException(401, "Device unavailable; pair again")
        previous = get(db, "challenge", device_id)
        if previous and previous["expires_at"] > now:
            return previous
        value = {"challenge": secrets.token_urlsafe(32), "expires_at": now + 60}
        put(db, "challenge", device_id, value)
        return value


def exchange(device_id: str, signature: str):
    with database() as db:
        device = get(db, "device", device_id)
        value = get(db, "challenge", device_id)
        if not device or not value or value["expires_at"] < time.time() or device["status"] == "revoked":
            raise HTTPException(401, "Challenge expired or device revoked")
        try:
            message = f'jarvis-mobile-v1\n{device_id}\n{value["challenge"]}'.encode()
            public_key(device["public_key"]).verify(
                base64.b64decode(signature, validate=True), message, ec.ECDSA(hashes.SHA256())
            )
        except (ValueError, InvalidSignature):
            raise HTTPException(401, "Invalid device proof")
        if device["status"] != "active":
            raise HTTPException(403, "Confirm this phone's fingerprint on Jarvis first")
        db.execute("DELETE FROM records WHERE kind='challenge' AND id=?", (device_id,))
        token = secrets.token_urlsafe(32)
        put(db, "session", device_id, {"hash": digest(token), "expires_at": time.time() + SESSION_SECONDS})
    return {"access_token": token, "expires_in": SESSION_SECONDS, "device": safe_device(device)}


def authenticate_values(authorization: str, device_id: str) -> dict | None:
    if not device_id or not authorization.startswith("Bearer "):
        return None
    with database() as db:
        device = get(db, "device", device_id)
        session = get(db, "session", device_id)
    if device and device["status"] == "active" and session and session["expires_at"] > time.time():
        if secrets.compare_digest(session["hash"], digest(authorization[7:])):
            return device
    return None


def authenticate(request: Request) -> dict | None:
    return authenticate_values(
        request.headers.get("authorization", ""),
        request.headers.get("x-jarvis-device", ""),
    )


def require_device(request: Request) -> dict:
    device = authenticate(request)
    if not device:
        raise HTTPException(401, "Paired-device authentication required")
    return device
