"""RFC-0124 confirm tokens for clean reinstall POST validation."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from pathlib import Path

from ..config import load_settings

CONFIRM_TOKEN_TTL_SECONDS = 15 * 60


def _token_secret() -> bytes:
    settings = load_settings()
    material = (settings.auth_token or "jarvis-clean-reinstall-local").encode("utf-8")
    return hashlib.sha256(material).digest()


def normalize_root_paths(paths: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in paths:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            normalized.append(str(Path(text).resolve()))
        except OSError:
            normalized.append(text)
    return sorted(set(normalized), key=lambda p: p.lower())


def issue_confirm_token(owned_root_paths: list[str]) -> tuple[str, int]:
    expires_at = int(time.time()) + CONFIRM_TOKEN_TTL_SECONDS
    payload = {
        "roots": normalize_root_paths(owned_root_paths),
        "exp": expires_at,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_token_secret(), body, hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=") + "." + signature
    return token, expires_at


def verify_confirm_token(token: str, acknowledged_roots: list[str]) -> str | None:
    if not token or "." not in token:
        return "confirm_token is missing or invalid"
    encoded, signature = token.rsplit(".", 1)
    padding = "=" * (-len(encoded) % 4)
    try:
        body = base64.urlsafe_b64decode(encoded + padding)
    except (ValueError, binascii.Error):
        return "confirm_token is malformed"
    expected = hmac.new(_token_secret(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return "confirm_token signature mismatch"

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return "confirm_token payload is invalid"

    expires_at = int(payload.get("exp") or 0)
    if expires_at < int(time.time()):
        return "confirm_token expired; call GET preview again"

    expected_roots = normalize_root_paths(list(payload.get("roots") or []))
    ack_roots = normalize_root_paths(acknowledged_roots)
    if expected_roots != ack_roots:
        return "acknowledged_roots must exactly match owned_root_entries from GET preview"

    return None
