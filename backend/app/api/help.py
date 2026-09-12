from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..help.assistant import answer_help, help_status
from ..help.topics import get_topic, list_topics, topic_as_dict

router = APIRouter(prefix="/api/help", tags=["help"])


class HelpMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None


@router.get("/status")
async def get_help_status():
    return help_status()


@router.get("/topics")
async def get_help_topics():
    return {"topics": [topic_as_dict(topic) for topic in list_topics()]}


@router.get("/topics/{topic_id}")
async def get_help_topic(topic_id: str):
    topic = get_topic(topic_id)
    if topic is None:
        raise HTTPException(404, "Unknown help topic")
    return topic_as_dict(topic)


@router.post("/chat")
async def post_help_chat(body: HelpMessageIn):
    result = await answer_help(body.message, conversation_id=body.conversation_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Help chat failed")
    return result
