from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel

from ..auth import (
    ensure_owner_private_key,
    extract_key_from_request,
    generate_private_key,
    get_effective_private_key,
    is_local_owner_host,
    private_key_file_path,
    verify_key,
)
from ..config import load_settings, save_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthVerifyIn(BaseModel):
    key: str | None = None


class AuthConfigIn(BaseModel):
    auth_required: bool | None = None
    lan_access: bool | None = None
    private_key: str | None = None


@router.get("/status")
async def auth_status(request: Request):
    settings = load_settings()
    has_key = bool(get_effective_private_key(settings))
    provided = extract_key_from_request(request)
    authenticated = verify_key(provided, get_effective_private_key(settings)) if has_key else False

    return {
        "auth_required": settings.auth_required,
        "lan_access": settings.lan_access,
        "has_key": has_key,
        "authenticated": authenticated or not (settings.auth_required or settings.lan_access),
    }


@router.post("/verify")
async def verify_auth(request: Request, body: AuthVerifyIn | None = None):
    settings = load_settings()
    expected = get_effective_private_key(settings)
    if not (settings.auth_required or settings.lan_access):
        return {"valid": True, "auth_required": False}

    if not expected:
        return {"valid": False, "auth_required": True, "detail": "No private key configured on server"}

    provided = (body.key if body and body.key else None) or extract_key_from_request(request)
    valid = verify_key(provided, expected)
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid private key")
    return {"valid": True, "auth_required": True}


@router.post("/desktop-session")
async def desktop_session(request: Request):
    """Silently prepare the owner console session on this PC. Never for LAN/remote."""
    host = request.client.host if request.client else ""
    if not is_local_owner_host(host):
        raise HTTPException(status_code=403, detail="Desktop session is only available on this PC")
    ensure_owner_private_key()
    key = get_effective_private_key()
    if not key:
        raise HTTPException(status_code=503, detail="Could not prepare this PC's session")
    return {"ok": True, "private_key": key}


@router.post("/generate-key")
async def generate_new_key():
    key = generate_private_key()
    return {"private_key": key, "message": "New private key generated and saved. Keep this private key secure."}


@router.post("/configure")
async def configure_auth(body: AuthConfigIn):
    settings = load_settings()
    if body.auth_required is not None:
        settings.auth_required = body.auth_required
    if body.lan_access is not None:
        settings.lan_access = body.lan_access
        if body.lan_access:
            settings.bind_host = "0.0.0.0"
    if body.private_key is not None:
        key = body.private_key.strip()
        settings.auth_token = key
        try:
            private_key_file_path().write_text(key + "\n", encoding="utf-8")
        except Exception:
            pass
    save_settings(settings)
    return {
        "auth_required": settings.auth_required,
        "lan_access": settings.lan_access,
        "has_key": bool(get_effective_private_key(settings)),
    }
