from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..providers.base import ChatMessage

PERSONA_PACK_VERSION = "1"


class PersonaTtsDefaults(BaseModel):
    voice_profile_id: str = "jarvis-default"
    speak_chat_replies: bool = True


class PersonaPack(BaseModel):
    id: str = "jarvis-default-v1"
    locale: str = "en-GB"
    system_prefix: str = ""
    traits: dict[str, str] = Field(default_factory=dict)
    must: list[str] = Field(default_factory=list)
    must_not: list[str] = Field(default_factory=list)
    tts: PersonaTtsDefaults = Field(default_factory=PersonaTtsDefaults)


def persona_pack_path() -> Path:
    return Path(__file__).resolve().parent / "persona_pack.json"


@lru_cache(maxsize=1)
def load_persona_pack() -> PersonaPack:
    path = persona_pack_path()
    if not path.is_file():
        return PersonaPack()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return PersonaPack.model_validate(payload)


def reload_persona_pack() -> PersonaPack:
    load_persona_pack.cache_clear()
    return load_persona_pack()


def build_persona_instructions(pack: PersonaPack | None = None) -> str:
    chosen = pack or load_persona_pack()
    parts: list[str] = []
    prefix = (chosen.system_prefix or "").strip()
    if prefix:
        parts.append(prefix)
    if chosen.traits:
        trait_lines = [f"- {key}: {value}" for key, value in chosen.traits.items()]
        parts.append("Personality traits:\n" + "\n".join(trait_lines))
    if chosen.must:
        parts.append("You must:\n" + "\n".join(f"- {item}" for item in chosen.must))
    if chosen.must_not:
        parts.append("You must not:\n" + "\n".join(f"- {item}" for item in chosen.must_not))
    return "\n\n".join(parts).strip()


def persona_instructions() -> str:
    return build_persona_instructions()


def inject_persona_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Prepend the portable persona pack as the first system segment.

    Model adapters and normalize_chat_messages may merge system turns, but the
    persona text always remains at the front of the merged block.
    """
    instructions = persona_instructions()
    if not instructions:
        return messages
    persona_message = ChatMessage(role="system", content=instructions)
    return [persona_message, *messages]


def persona_pack_metadata() -> dict[str, Any]:
    pack = load_persona_pack()
    return {
        "id": pack.id,
        "locale": pack.locale,
        "version": PERSONA_PACK_VERSION,
        "path": str(persona_pack_path()),
    }
