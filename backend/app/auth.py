from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse

from .config import AppSettings, data_dir, load_settings, save_settings


def private_key_file_path() -> Path:
    return data_dir() / "private_key.sec"


def get_effective_private_key(settings: AppSettings | None = None) -> str:
    current = settings or load_settings()
    if current.auth_token:
        return current.auth_token
    key_file = private_key_file_path()
    if key_file.exists():
        try:
            return key_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return ""


def generate_private_key() -> str:
    """Generate a high-entropy 256-bit private key."""
    key = f"jarvis_pk_{secrets.token_hex(24)}"
    key_file = private_key_file_path()
    try:
        key_file.write_text(key + "\n", encoding="utf-8")
    except Exception:
        pass
    settings = load_settings()
    settings.auth_token = key
    save_settings(settings)
    return key


def extract_key_from_request(request: Request) -> str:
    # 1. Bearer token in Authorization header
    auth_hdr = request.headers.get("authorization", "")
    if auth_hdr.lower().startswith("bearer "):
        return auth_hdr[7:].strip()

    # 2. X-Jarvis-Key or X-Jarvis-Token header
    if "x-jarvis-key" in request.headers:
        return request.headers["x-jarvis-key"].strip()
    if "x-jarvis-token" in request.headers:
        return request.headers["x-jarvis-token"].strip()

    # 3. Query parameter (?key=... or ?token=...)
    query_key = request.query_params.get("key") or request.query_params.get("token")
    if query_key:
        return query_key.strip()

    return ""


def extract_key_from_websocket(websocket: WebSocket) -> str:
    # 1. Query parameter (?key=... or ?token=...)
    query_key = websocket.query_params.get("key") or websocket.query_params.get("token")
    if query_key:
        return query_key.strip()

    # 2. Headers
    auth_hdr = websocket.headers.get("authorization", "")
    if auth_hdr.lower().startswith("bearer "):
        return auth_hdr[7:].strip()
    if "x-jarvis-key" in websocket.headers:
        return websocket.headers["x-jarvis-key"].strip()
    if "x-jarvis-token" in websocket.headers:
        return websocket.headers["x-jarvis-token"].strip()

    return ""


def verify_key(provided_key: str, expected_key: str) -> bool:
    if not expected_key or not provided_key:
        return False
    return secrets.compare_digest(provided_key, expected_key)


def is_auth_required_for_request(request: Request, settings: AppSettings) -> bool:
    if not (settings.auth_required or settings.lan_access):
        return False

    # Skip health check & auth status check
    path = request.url.path
    if path in {"/api/health", "/api/auth/status", "/api/auth/verify"}:
        return False

    # Only protect /api routes
    if not path.startswith("/api"):
        return False

    # If LAN access is required, local connections can be exempted only if auth_required is false
    if settings.lan_access and not settings.auth_required:
        host = request.client.host if request.client else ""
        if host in {"127.0.0.1", "::1", "localhost"}:
            return False

    return True


def authenticate_request(request: Request, settings: AppSettings | None = None) -> bool:
    current = settings or load_settings()
    if not is_auth_required_for_request(request, current):
        return True

    expected = get_effective_private_key(current)
    if not expected:
        # Auth is required but no key is configured: deny by default
        return False

    provided = extract_key_from_request(request)
    return verify_key(provided, expected)


def authenticate_websocket(websocket: WebSocket, settings: AppSettings | None = None) -> bool:
    current = settings or load_settings()
    if not (current.auth_required or current.lan_access):
        return True

    if current.lan_access and not current.auth_required:
        host = websocket.client.host if websocket.client else ""
        if host in {"127.0.0.1", "::1", "localhost"}:
            return True

    expected = get_effective_private_key(current)
    if not expected:
        return False

    provided = extract_key_from_websocket(websocket)
    return verify_key(provided, expected)
