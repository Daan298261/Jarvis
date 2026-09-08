from __future__ import annotations

import base64
import hashlib
import secrets
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException, Request

from .store import database, get, put, rows

SESSION_SECONDS = 900


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


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
    return hashlib.sha256(key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()


def invite(ttl: int = 3600) -> dict:
    token = secrets.token_urlsafe(32)
    value = {"id": str(uuid.uuid4()), "expires_at": time.time() + ttl, "claimed_by": None}
    with database() as db:
        put(db, "invitation", digest(token), value)
    return {**value, "invitation": token}


def enroll(token: str, encoded_key: str, name: str) -> dict:
    fp = fingerprint(encoded_key)
    with database() as db:
        invitation = get(db, "invitation", digest(token))
        if not invitation or invitation["expires_at"] < time.time():
            raise HTTPException(401, "Invitation expired or invalid. Generate a new pairing invitation on Jarvis.")
        if invitation["claimed_by"]:
            device = get(db, "device", invitation["claimed_by"])
            if device and device["fingerprint"] == fp and device["status"] != "revoked":
                return safe_device(device)
            raise HTTPException(409, "Invitation already claimed")
        device = {"id": str(uuid.uuid4()), "name": name[:100], "public_key": encoded_key,
                  "fingerprint": fp, "status": "pending", "created_at": time.time(),
                  "notifications": True, "critical_calls": False, "push_token": ""}
        put(db, "device", device["id"], device)
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
            public_key(device["public_key"]).verify(base64.b64decode(signature, validate=True), message, ec.ECDSA(hashes.SHA256()))
        except (ValueError, InvalidSignature):
            raise HTTPException(401, "Invalid device proof")
        if device["status"] != "active":
            raise HTTPException(403, "Confirm this phone's fingerprint on Jarvis first")
        db.execute("DELETE FROM records WHERE kind='challenge' AND id=?", (device_id,))
        # One live token per device limits storage and invalidates old sessions.
        token = secrets.token_urlsafe(32)
        put(db, "session", device_id, {"hash": digest(token), "expires_at": time.time() + SESSION_SECONDS})
    return {"access_token": token, "expires_in": SESSION_SECONDS, "device": safe_device(device)}


def authenticate(request: Request) -> dict | None:
    auth = request.headers.get("authorization", "")
    device_id = request.headers.get("x-jarvis-device", "")
    if not device_id or not auth.startswith("Bearer "):
        return None
    with database() as db:
        device = get(db, "device", device_id)
        session = get(db, "session", device_id)
    if device and device["status"] == "active" and session and session["expires_at"] > time.time():
        if secrets.compare_digest(session["hash"], digest(auth[7:])):
            return device
    return None


def require_device(request: Request) -> dict:
    device = authenticate(request)
    if not device:
        raise HTTPException(401, "Paired-device authentication required")
    return device
