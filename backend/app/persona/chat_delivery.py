from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any

from ..config import load_settings
from ..events import BUS
from .quiet import should_speak_chat_reply

OWNER_CHAT_CHANNEL = "__owner_chat__"


@dataclass
class ChatTtsItem:
    id: str
    text: str
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "source": self.source}


_pending_tts: deque[ChatTtsItem] = deque(maxlen=32)


async def publish_owner_text(
    text: str,
    *,
    title: str = "Jarvis",
    kind: str = "assistant",
    source: str = "chat",
    speak: bool | None = None,
) -> dict[str, Any]:
    """Deliver assistant text on the owner chat event channel and optionally queue TTS."""
    cleaned = (text or "").strip()
    if not cleaned:
        return {"text": "", "spoken": False, "tts_id": None}

    await BUS.publish_ephemeral(
        OWNER_CHAT_CHANNEL,
        kind,
        title,
        cleaned,
        stage=source,
    )

    settings = load_settings()
    want_speech = should_speak_chat_reply(settings) if speak is None else bool(speak)
    tts_id = None
    if want_speech:
        tts_id = enqueue_chat_tts(cleaned, source=source)
        await BUS.publish_ephemeral(
            OWNER_CHAT_CHANNEL,
            "chat_tts",
            "Speak reply",
            cleaned,
            stage=source,
        )

    return {"text": cleaned, "spoken": want_speech, "tts_id": tts_id}


def enqueue_chat_tts(text: str, *, source: str = "chat") -> str:
    item = ChatTtsItem(id=str(uuid.uuid4()), text=text.strip(), source=source)
    _pending_tts.append(item)
    return item.id


def pending_chat_tts(limit: int = 10) -> list[dict[str, Any]]:
    items = list(_pending_tts)[-limit:]
    return [item.as_dict() for item in items]


def pop_chat_tts(item_id: str) -> dict[str, Any] | None:
    for index, item in enumerate(_pending_tts):
        if item.id == item_id:
            del _pending_tts[index]
            return item.as_dict()
    return None


def reset_chat_delivery() -> None:
    _pending_tts.clear()
