from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from .audit import record_audit
from .schema import GuestAction, PortalLimits, PortalRecord, PortalScope, PortalSession, ResourceType, ScopedGrant
from .scope import build_effective_permissions, is_action_granted, preview_scope
from .store import (
    get_portal,
    get_portal_by_token_hash,
    guests_root,
    list_audit,
    list_portals,
    reset_guest_store,
    save_portal,
)
from .tokens import generate_portal_token, hash_portal_token, is_portal_token


@dataclass
class GuestContext:
    portal: PortalRecord
    session_id: str
    guest_label: str


class GuestPortalError(Exception):
    def __init__(self, code: str, message: str, status: int = 403) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_expiry(expires_at: str | None) -> datetime | None:
    if not expires_at:
        return None
    try:
        return datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_expired(portal: PortalRecord) -> bool:
    expiry = _parse_expiry(portal.expires_at)
    if expiry is None:
        return False
    now = datetime.now(timezone.utc)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return now >= expiry


def extract_guest_token_from_request(request: Request) -> str:
    auth_hdr = request.headers.get("authorization", "")
    if auth_hdr.lower().startswith("bearer "):
        candidate = auth_hdr[7:].strip()
        if is_portal_token(candidate):
            return candidate
    header = request.headers.get("x-jarvis-guest-token")
    if header and is_portal_token(header.strip()):
        return header.strip()
    query = request.query_params.get("guest_token")
    if query and is_portal_token(query.strip()):
        return query.strip()
    return ""


def extract_guest_session_from_request(request: Request) -> str | None:
    header = request.headers.get("x-jarvis-guest-session")
    if header and header.strip():
        return header.strip()
    query = request.query_params.get("guest_session")
    if query and query.strip():
        return query.strip()
    return None


class GuestPortalService:
    def configure_data_root(self, path: Any) -> None:
        # Tests monkeypatch guests_root via store module; kept for compatibility.
        guests_root()

    def reset(self) -> None:
        reset_guest_store()

    def preview(
        self,
        scope: PortalScope,
        limits: PortalLimits,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        return preview_scope(scope, limits, expires_at)

    def create_portal(
        self,
        *,
        label: str,
        guest_label: str,
        scope: PortalScope,
        limits: PortalLimits,
        expires_at: str | None = None,
    ) -> tuple[PortalRecord, str]:
        token = generate_portal_token()
        portal_id = str(uuid.uuid4())
        uses_remaining = limits.max_uses
        if limits.single_use:
            uses_remaining = 1
        portal = PortalRecord(
            id=portal_id,
            label=label.strip() or "Guest portal",
            guest_label=guest_label.strip() or "guest",
            scope=scope,
            limits=limits,
            token_hash=hash_portal_token(token),
            created_at=_utc_now(),
            expires_at=expires_at,
            uses_remaining=uses_remaining,
        )
        save_portal(portal)
        record_audit(
            portal_id=portal.id,
            session_id="owner",
            guest_label=portal.guest_label,
            action="portal.create",
            outcome="ok",
            detail=portal.label,
        )
        return portal, token

    def list_portals(self) -> list[PortalRecord]:
        return list_portals()

    def get_portal(self, portal_id: str) -> PortalRecord | None:
        return get_portal(portal_id)

    def revoke_portal(self, portal_id: str) -> PortalRecord:
        portal = get_portal(portal_id)
        if portal is None:
            raise GuestPortalError("portal_not_found", "Portal not found", 404)
        portal.revoked = True
        portal.revoked_at = _utc_now()
        portal.sessions = []
        save_portal(portal)
        record_audit(
            portal_id=portal.id,
            session_id="owner",
            guest_label=portal.guest_label,
            action="portal.revoke",
            outcome="ok",
        )
        return portal

    def portal_public_dict(self, portal: PortalRecord) -> dict[str, Any]:
        return {
            "id": portal.id,
            "label": portal.label,
            "guest_label": portal.guest_label,
            "scope": portal.scope.model_dump(),
            "limits": portal.limits.model_dump(),
            "created_at": portal.created_at,
            "expires_at": portal.expires_at,
            "revoked": portal.revoked,
            "revoked_at": portal.revoked_at,
            "uses_remaining": portal.uses_remaining,
            "active_sessions": len(portal.sessions),
        }

    def _validate_portal_for_token(self, token: str) -> PortalRecord:
        if not token or not is_portal_token(token):
            raise GuestPortalError("invalid_token", "Invalid guest portal token", 401)
        portal = get_portal_by_token_hash(hash_portal_token(token))
        if portal is None:
            raise GuestPortalError("invalid_token", "Invalid guest portal token", 401)
        if portal.revoked:
            raise GuestPortalError("portal_revoked", "Portal access has been revoked", 403)
        if _is_expired(portal):
            raise GuestPortalError("portal_expired", "Portal token has expired", 403)
        if portal.uses_remaining is not None and portal.uses_remaining <= 0:
            raise GuestPortalError("uses_exhausted", "Portal token uses exhausted", 403)
        return portal

    def resolve_guest_context(self, token: str, session_id: str | None = None) -> GuestContext:
        portal = self._validate_portal_for_token(token)
        if session_id:
            for session in portal.sessions:
                if session.session_id == session_id:
                    return GuestContext(
                        portal=portal,
                        session_id=session.session_id,
                        guest_label=session.guest_label,
                    )
        return GuestContext(
            portal=portal,
            session_id="unauthenticated",
            guest_label=portal.guest_label,
        )

    def authenticate_guest(self, token: str, session_id: str | None = None) -> GuestContext:
        portal = self._validate_portal_for_token(token)

        if session_id:
            for session in portal.sessions:
                if session.session_id == session_id:
                    return GuestContext(
                        portal=portal,
                        session_id=session.session_id,
                        guest_label=session.guest_label,
                    )

        if portal.limits.max_sessions is not None and len(portal.sessions) >= portal.limits.max_sessions:
            raise GuestPortalError("session_limit", "Maximum concurrent guest sessions reached", 403)

        new_session_id = str(uuid.uuid4())
        now = _utc_now()
        portal.sessions.append(
            PortalSession(
                session_id=new_session_id,
                guest_label=portal.guest_label,
                created_at=now,
                last_seen_at=now,
            )
        )
        save_portal(portal)
        record_audit(
            portal_id=portal.id,
            session_id=new_session_id,
            guest_label=portal.guest_label,
            action="session.start",
            outcome="ok",
        )
        return GuestContext(portal=portal, session_id=new_session_id, guest_label=portal.guest_label)

    def ensure_guest_session(self, ctx: GuestContext, token: str) -> GuestContext:
        if ctx.session_id != "unauthenticated":
            return ctx
        return self.authenticate_guest(token)

    def touch_session(self, ctx: GuestContext) -> None:
        portal = get_portal(ctx.portal.id)
        if portal is None:
            return
        now = _utc_now()
        for session in portal.sessions:
            if session.session_id == ctx.session_id:
                session.last_seen_at = now
        save_portal(portal)
        ctx.portal = portal

    def consume_use(self, ctx: GuestContext) -> None:
        portal = get_portal(ctx.portal.id)
        if portal is None:
            return
        if portal.uses_remaining is not None:
            portal.uses_remaining = max(0, portal.uses_remaining - 1)
            if portal.limits.single_use or portal.uses_remaining <= 0:
                portal.revoked = True
                portal.revoked_at = _utc_now()
        save_portal(portal)
        ctx.portal = portal

    def authorize(
        self,
        ctx: GuestContext,
        *,
        resource_type: ResourceType,
        resource_id: str,
        action: GuestAction,
        path: str | None = None,
    ) -> None:
        if ctx.portal.revoked or _is_expired(ctx.portal):
            record_audit(
                portal_id=ctx.portal.id,
                session_id=ctx.session_id,
                guest_label=ctx.guest_label,
                action=f"{resource_type}.{action}",
                resource_type=resource_type,
                resource_id=resource_id,
                path=path,
                outcome="denied",
                detail="portal inactive",
            )
            raise GuestPortalError("portal_inactive", "Portal access is no longer valid", 403)

        if not is_action_granted(ctx.portal.scope, resource_type, resource_id, action):
            record_audit(
                portal_id=ctx.portal.id,
                session_id=ctx.session_id,
                guest_label=ctx.guest_label,
                action=f"{resource_type}.{action}",
                resource_type=resource_type,
                resource_id=resource_id,
                path=path,
                outcome="denied",
                detail="scope isolation",
            )
            raise GuestPortalError("scope_denied", "Action not permitted for this portal scope", 403)

        record_audit(
            portal_id=ctx.portal.id,
            session_id=ctx.session_id,
            guest_label=ctx.guest_label,
            action=f"{resource_type}.{action}",
            resource_type=resource_type,
            resource_id=resource_id,
            path=path,
            outcome="ok",
        )
        self.touch_session(ctx)
        if ctx.portal.limits.single_use or ctx.portal.limits.max_uses is not None:
            self.consume_use(ctx)

    def effective_permissions(self, ctx: GuestContext) -> dict[str, Any]:
        return build_effective_permissions(
            ctx.portal.scope,
            ctx.portal.limits,
            ctx.portal.expires_at,
        ).model_dump()

    def list_audit(self, portal_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        return list_audit(portal_id=portal_id, limit=limit)

    def scope_from_grants(self, grants: list[dict[str, Any]]) -> PortalScope:
        parsed: list[ScopedGrant] = []
        for item in grants:
            resource_type = item.get("resource_type")
            resource_id = item.get("resource_id")
            actions = item.get("actions") or []
            if not resource_type or not resource_id:
                continue
            parsed.append(
                ScopedGrant(
                    resource_type=resource_type,
                    resource_id=str(resource_id),
                    actions=[str(a) for a in actions],
                )
            )
        return PortalScope(grants=parsed)


SERVICE = GuestPortalService()


def authenticate_guest_request(request: Request) -> GuestContext | None:
    token = extract_guest_token_from_request(request)
    if not token:
        return None
    session_id = extract_guest_session_from_request(request)
    try:
        return SERVICE.resolve_guest_context(token, session_id=session_id)
    except GuestPortalError:
        return None


def guest_http_error(exc: GuestPortalError) -> HTTPException:
    return HTTPException(
        status_code=exc.status,
        detail={"code": exc.code, "message": exc.message},
    )
