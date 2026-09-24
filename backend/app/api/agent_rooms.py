"""REST API for Agent Rooms (RFC-0174). Portal calls these routes only.

Wraps the public rooms package. Hidden chain-of-thought stays inside the
library sanitizers; this module does not accept a private-history flag.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agents.rooms import (
    SUPERVISOR_ID,
    AgentRoom,
    BlackboardBoundError,
    GovernorDenied,
    RoomError,
    RoomTerminated,
    create_room,
    get_room,
    list_rooms,
)
from ..persona.named_persona import ROSTER, NamedPersonaBindError, resolve_persona_id

router = APIRouter(prefix="/api/agent-rooms", tags=["agent-rooms"])


class CreateRoomIn(BaseModel):
    goal: str = Field(min_length=1)
    specialists: list[str] = Field(min_length=1)
    cost_mode: str = "balanced"
    privacy_mode: str = "local_only"
    supervisor_model: str = ""
    specialist_models: dict[str, str] = Field(default_factory=dict)


class MessageIn(BaseModel):
    kind: str = Field(min_length=1)
    from_agent: str = Field(min_length=1)
    body: str = Field(min_length=1)
    to_agent: str | None = None
    rationale: str = ""
    task_id: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


class BlackboardIn(BaseModel):
    kind: str = Field(min_length=1)
    key: str = Field(min_length=1)
    content: str = Field(min_length=1)
    author: str = Field(min_length=1)


class HandoffIn(BaseModel):
    from_agent: str = Field(min_length=1)
    to_agent: str = Field(min_length=1)
    body: str = Field(min_length=1)
    task_id: str | None = None
    rationale: str = Field(min_length=1)


class TerminateIn(BaseModel):
    reason: str = "terminated by owner"


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, RoomTerminated):
        return HTTPException(status_code=409, detail={"message": str(exc), "code": exc.code})
    if isinstance(exc, GovernorDenied):
        return HTTPException(status_code=409, detail={"message": exc.reason, "code": exc.code})
    if isinstance(exc, RoomError):
        return HTTPException(status_code=400, detail={"message": str(exc), "code": exc.code})
    if isinstance(exc, BlackboardBoundError):
        return HTTPException(status_code=400, detail={"message": str(exc), "code": "blackboard_bound"})
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid"})
    return HTTPException(status_code=500, detail={"message": str(exc), "code": "error"})


def _roster() -> list[dict[str, str]]:
    """Anzu stays the supervisor. The portal offers the other named specialists."""
    return [
        {"id": row.id, "label": row.label, "role": row.role, "phrase": row.phrase}
        for row in ROSTER
        if row.id != SUPERVISOR_ID
    ]


def _normalize_specialists(raw: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            aid = resolve_persona_id(text, required=True)
        except NamedPersonaBindError as exc:
            raise RoomError(str(exc), code="unknown_specialist") from exc
        if aid == SUPERVISOR_ID or aid in seen:
            continue
        seen.add(aid)
        cleaned.append(aid)
    if not cleaned:
        raise RoomError(
            "room requires Anzu plus at least one specialist",
            code="insufficient_participants",
        )
    return cleaned


def _require_room(room_id: str) -> AgentRoom:
    room = get_room(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail=f"room not found: {room_id}")
    return room


@router.get("")
async def agent_rooms_index() -> dict[str, Any]:
    return {"rooms": list_rooms(), "roster": _roster()}


@router.post("")
async def create_agent_room(body: CreateRoomIn) -> dict[str, Any]:
    try:
        specialists = _normalize_specialists(body.specialists)
        models = {
            aid: str(body.specialist_models.get(aid) or "")
            for aid in specialists
            if aid in body.specialist_models
        }
        room = create_room(
            body.goal,
            specialists,
            cost_mode=body.cost_mode,
            privacy_mode=body.privacy_mode,
            supervisor_model=body.supervisor_model,
            specialist_models=models or None,
        )
        room.decompose()
        return room.as_dict()
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{room_id}")
async def get_agent_room(room_id: str) -> dict[str, Any]:
    return _require_room(room_id).as_dict()


@router.get("/{room_id}/messages")
async def list_messages(room_id: str) -> dict[str, Any]:
    room = _require_room(room_id)
    return {"messages": [message.as_dict() for message in room.messages]}


@router.post("/{room_id}/messages")
async def post_message(room_id: str, body: MessageIn) -> dict[str, Any]:
    room = _require_room(room_id)
    try:
        message = room.post_message(
            kind=body.kind,
            from_agent=body.from_agent,
            body=body.body,
            to_agent=body.to_agent,
            rationale=body.rationale,
            task_id=body.task_id,
            artifact_ids=body.artifact_ids or None,
            citation_ids=body.citation_ids or None,
        )
        return message.as_dict()
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{room_id}/blackboard")
async def get_blackboard(room_id: str) -> dict[str, Any]:
    return _require_room(room_id).blackboard.snapshot()


@router.post("/{room_id}/blackboard")
async def publish_blackboard(room_id: str, body: BlackboardIn) -> dict[str, Any]:
    room = _require_room(room_id)
    try:
        return room.publish_blackboard(
            kind=body.kind,
            key=body.key,
            content=body.content,
            author=body.author,
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{room_id}/audit")
async def replay_audit(room_id: str) -> dict[str, Any]:
    return _require_room(room_id).replay()


@router.post("/{room_id}/handoff")
async def handoff(room_id: str, body: HandoffIn) -> dict[str, Any]:
    room = _require_room(room_id)
    try:
        message = room.handoff(
            from_agent=body.from_agent,
            to_agent=body.to_agent,
            body=body.body,
            task_id=body.task_id,
            rationale=body.rationale,
        )
        return message.as_dict()
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{room_id}/synthesize")
async def synthesize(room_id: str) -> dict[str, Any]:
    room = _require_room(room_id)
    try:
        result = room.synthesize_and_finalize()
        return {"synthesis": result.as_dict(), "room": room.as_dict()}
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{room_id}/terminate")
async def terminate(room_id: str, body: TerminateIn | None = None) -> dict[str, Any]:
    room = _require_room(room_id)
    try:
        reason = (body.reason if body else "") or "terminated by owner"
        room.terminate(reason=reason)
        return room.as_dict()
    except Exception as exc:
        raise _http(exc) from exc
