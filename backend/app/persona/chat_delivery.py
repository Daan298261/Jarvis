from __future__ import annotations

import re
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any

from ..config import load_settings
from ..events import BUS
from .quiet import should_speak_chat_reply
from ..tts.reply_class import ReplySpeechClass, classify_reply_for_speech
from ..tts.speak_filter import filter_text_for_speech

OWNER_CHAT_CHANNEL = "__owner_chat__"
_NONCOMMITTAL_ACK = re.compile(
    r"(?i)^(one moment|just a moment|allow me a moment|"
    r"let me check|i(?:'|')?ll check|checking now|"
    r"very well|certainly|of course|right away)[.!?]?$",
)


@dataclass
class ChatTtsItem:
    id: str
    text: str
    source: str
    reply_class: str = "technical"
    partial: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "source": self.source,
            "reply_class": self.reply_class,
            "partial": self.partial,
        }


_pending_tts: deque[ChatTtsItem] = deque(maxlen=32)
_stream_spoken_through: dict[str, int] = {}


async def publish_owner_text(
    text: str,
    *,
    title: str = "Jarvis",
    kind: str = "assistant",
    source: str = "chat",
    speak: bool | None = None,
    user_prompt: str | None = None,
    tts_char_offset: int = 0,
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
    remainder = cleaned[tts_char_offset:].strip() if tts_char_offset else cleaned
    if want_speech and remainder:
        tts_id = enqueue_chat_tts(
            remainder,
            source=source,
            user_prompt=user_prompt,
            full_text_for_class=cleaned,
        )
        if tts_id:
            await BUS.publish_ephemeral(
                OWNER_CHAT_CHANNEL,
                "chat_tts",
                "Speak reply",
                remainder,
                stage=source,
            )

    return {"text": cleaned, "spoken": bool(tts_id), "tts_id": tts_id or None}


def enqueue_chat_tts(
    text: str,
    *,
    source: str = "chat",
    user_prompt: str | None = None,
    full_text_for_class: str | None = None,
    partial: bool = False,
    reply_class: ReplySpeechClass | None = None,
) -> str:
    basis = (full_text_for_class or text or "").strip()
    speech_class = reply_class or classify_reply_for_speech(basis, user_prompt=user_prompt)
    speakable = filter_text_for_speech(
        text,
        source=source,
        reply_class=speech_class,
        user_prompt=user_prompt,
    )
    if not speakable:
        return ""
    item = ChatTtsItem(
        id=str(uuid.uuid4()),
        text=speakable,
        source=source,
        reply_class=speech_class,
        partial=partial,
    )
    _pending_tts.append(item)
    return item.id


def stream_speak_offset(stream_key: str) -> int:
    return _stream_spoken_through.get(stream_key, 0)


def clear_stream_speak_state(stream_key: str | None = None) -> None:
    if stream_key is None:
        _stream_spoken_through.clear()
        return
    _stream_spoken_through.pop(stream_key, None)


def _first_stable_sentence(text: str) -> tuple[str, int] | None:
    stripped = text.strip()
    if not stripped:
        return None
    for index, char in enumerate(stripped):
        if char not in ".!?":
            continue
        end = index + 1
        while end < len(stripped) and stripped[end] in "\"'":
            end += 1
        if end >= len(stripped) or stripped[end] in " \t\n":
            sentence = stripped[:end].strip()
            if len(sentence) < 4:
                return None
            return sentence, end
    return None


def is_semantically_safe_early_social_sentence(
    sentence: str,
    *,
    awaiting_tool_result: bool = False,
) -> bool:
    if awaiting_tool_result:
        return bool(_NONCOMMITTAL_ACK.match(sentence.strip()))
    lowered = sentence.lower()
    if "traceback" in lowered or "http://" in lowered or "https://" in lowered:
        return False
    if "```" in sentence or "**" in sentence:
        return False
    return True


def maybe_enqueue_streaming_social_tts(
    accumulated: str,
    *,
    source: str,
    stream_key: str,
    user_prompt: str | None = None,
    awaiting_tool_result: bool = False,
) -> str | None:
    """RFC-0036 / RFC-0075: enqueue first stable social sentence without waiting for full reply."""
    already = _stream_spoken_through.get(stream_key, 0)
    if already > 0:
        return None

    chunk = accumulated[already:]
    parsed = _first_stable_sentence(chunk)
    if not parsed:
        return None
    sentence, rel_end = parsed
    if not is_semantically_safe_early_social_sentence(
        sentence,
        awaiting_tool_result=awaiting_tool_result,
    ):
        return None

    speech_class = classify_reply_for_speech(sentence, user_prompt=user_prompt)
    if speech_class != "social":
        return None

    item_id = enqueue_chat_tts(
        sentence,
        source=source,
        user_prompt=user_prompt,
        full_text_for_class=accumulated,
        partial=True,
        reply_class="social",
    )
    if not item_id:
        return None

    _stream_spoken_through[stream_key] = already + rel_end
    return item_id


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
    _stream_spoken_through.clear()
