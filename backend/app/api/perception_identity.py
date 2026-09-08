from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ..config import load_settings
from ..perception.identity import (
    EnrollmentSession,
    EnrollmentSessionRequest,
    EnrollmentSummary,
    IdentityResolver,
    list_summaries,
)
from ..perception.identity_store import IdentityStore

router = APIRouter(prefix="/api/perception/identity", tags=["perception", "identity"])
STORE = IdentityStore()
RESOLVER = IdentityResolver(load_settings().identity_recognition, STORE)
_SESSIONS: dict[str, tuple[EnrollmentSession, EnrollmentSessionRequest]] = {}
_SESSION_LOCK = RLock()
_SESSION_TTL_MINUTES = 10


def get_identity_resolver() -> IdentityResolver:
    """Return the process-local resolver with current owner settings applied."""
    RESOLVER.settings = load_settings().identity_recognition
    return RESOLVER


@router.get("/status")
async def identity_status():
    resolver = get_identity_resolver()
    return {
        **resolver.status(),
        "local_only": True,
        "raw_image_api": False,
        "enrollment_session_ttl_minutes": _SESSION_TTL_MINUTES,
    }


@router.get("/enrollments", response_model=list[EnrollmentSummary])
async def list_enrollments() -> list[EnrollmentSummary]:
    return list_summaries(STORE)


@router.post("/enrollments", response_model=EnrollmentSession)
async def create_enrollment_session(body: EnrollmentSessionRequest) -> EnrollmentSession:
    """Record explicit owner intent; no image or embedding is accepted over HTTP."""
    now = datetime.now(timezone.utc)
    session = EnrollmentSession(
        session_id=uuid4().hex,
        identity_id=body.identity_id,
        display_name=body.display_name,
        relationship=body.relationship,
        embedding_model=body.embedding_model,
        embedding_version=body.embedding_version,
        created_at=now,
        expires_at=now + timedelta(minutes=_SESSION_TTL_MINUTES),
    )
    with _SESSION_LOCK:
        _prune_sessions(now)
        _SESSIONS[session.session_id] = (session, body)
    return session


@router.delete("/enrollments/{identity_id}")
async def delete_enrollment(identity_id: str):
    resolver = get_identity_resolver()
    if not resolver.delete_identity(identity_id.strip().lower()):
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return {"ok": True, "identity_id": identity_id.strip().lower()}


@router.post("/reset")
async def reset_identity_data():
    get_identity_resolver().reset()
    with _SESSION_LOCK:
        _SESSIONS.clear()
    return {"ok": True, "enrollment_count": 0}


def complete_enrollment_session(session_id: str, embeddings) -> EnrollmentSummary:
    """Trusted local bridge hook; deliberately not exposed as an HTTP endpoint.

    The desktop camera/face backend will call this after converting ephemeral face
    crops to embeddings locally. The image data never enters this module.
    """
    now = datetime.now(timezone.utc)
    with _SESSION_LOCK:
        _prune_sessions(now)
        entry = _SESSIONS.pop(session_id, None)
    if entry is None:
        raise ValueError("unknown or expired enrollment session")
    session, request = entry
    if session.expires_at < now:
        raise ValueError("enrollment session expired")
    return get_identity_resolver().enroll_embeddings(request, embeddings)


def cancel_enrollment_session(session_id: str) -> bool:
    with _SESSION_LOCK:
        return _SESSIONS.pop(session_id, None) is not None


def _prune_sessions(now: datetime) -> None:
    expired = [session_id for session_id, (session, _) in _SESSIONS.items() if session.expires_at < now]
    for session_id in expired:
        _SESSIONS.pop(session_id, None)
