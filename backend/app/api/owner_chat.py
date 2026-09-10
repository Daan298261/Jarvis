from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..persona.chat_delivery import OWNER_CHAT_CHANNEL, pending_chat_tts, pop_chat_tts
from ..persona.greeting import maybe_send_launch_greeting
from ..persona.owner_chat import complete_owner_chat, get_conversation, stream_owner_chat

router = APIRouter(prefix="/api/owner/chat", tags=["owner-chat"])


class OwnerMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=32000)
    conversation_id: str | None = None


class GreetingIn(BaseModel):
    startup_id: str = Field(min_length=8, max_length=128)


@router.post("/messages")
async def post_owner_message(body: OwnerMessageIn):
    """Non-streaming owner chat (tests and simple clients)."""
    result = await complete_owner_chat(body.message, conversation_id=body.conversation_id)
    if not result.get("ok", True) and result.get("type") == "error":
        raise HTTPException(503, result.get("detail") or "Chat failed")
    return result


@router.post("/messages/stream")
async def post_owner_message_stream(body: OwnerMessageIn):
    async def event_generator():
        async for event in stream_owner_chat(body.message, conversation_id=body.conversation_id):
            yield {"event": event.get("type", "message"), "data": json.dumps(event)}

    return EventSourceResponse(event_generator())


@router.get("/conversations/{conversation_id}")
async def get_owner_conversation(conversation_id: str) -> dict[str, Any]:
    messages = get_conversation(conversation_id)
    return {
        "conversation_id": conversation_id,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in messages
            if message.role in {"user", "assistant"}
        ],
    }


@router.get("/events")
async def owner_chat_events():
    """SSE feed for greeting and assistant deliveries on the owner channel."""

    async def event_generator():
        from ..events import BUS

        queue = BUS.subscribe(OWNER_CHAT_CHANNEL)
        try:
            while True:
                event = await queue.get()
                yield {"event": event.get("kind", "message"), "data": json.dumps(event)}
        finally:
            BUS.unsubscribe(queue, OWNER_CHAT_CHANNEL)

    return EventSourceResponse(event_generator())


@router.get("/tts/pending")
async def owner_chat_tts_pending(limit: int = 10):
    return {"pending": pending_chat_tts(limit=limit)}


@router.post("/tts/{item_id}/ack")
async def owner_chat_tts_ack(item_id: str):
    item = pop_chat_tts(item_id)
    if item is None:
        raise HTTPException(404, "TTS item not found or already acknowledged")
    return {"acknowledged": item}


@router.post("/greeting")
async def trigger_greeting(body: GreetingIn):
    """Manual greeting trigger (idempotent per startup/day). Used by desktop shell if needed."""
    payload = await maybe_send_launch_greeting(body.startup_id)
    if payload is None:
        return {"sent": False, "reason": "already_sent"}
    return {"sent": True, **payload}
