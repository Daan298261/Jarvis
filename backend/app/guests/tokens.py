from __future__ import annotations

import hashlib
import secrets


TOKEN_PREFIX = "jarvis_gp_"


def generate_portal_token() -> str:
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_portal_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_portal_token(value: str) -> bool:
    return value.startswith(TOKEN_PREFIX)
