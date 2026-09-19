"""RFC-0130: selectable session personalities (HUD + system prompt addendum)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import load_settings, save_settings

SessionPersonalityId = Literal["default", "coding", "research", "concise"]


class SessionPersonalityPack(BaseModel):
    id: SessionPersonalityId
    display_name: str
    system_prefix_addendum: str = ""
    hud_theme: str = "default"
    tts_voice_hint: str | None = None


PERSONALITY_PACKS: dict[SessionPersonalityId, SessionPersonalityPack] = {
    "default": SessionPersonalityPack(
        id="default",
        display_name="Jarvis (default)",
        system_prefix_addendum=(
            "Session mode: default butler register — calm operations assistant, dry wit when appropriate."
        ),
        hud_theme="default",
        tts_voice_hint=None,
    ),
    "coding": SessionPersonalityPack(
        id="coding",
        display_name="Coding session",
        system_prefix_addendum=(
            "Session mode: coding. Be precise about code, files, tests, and diffs. "
            "Prefer actionable steps; skip social filler unless the owner asks."
        ),
        hud_theme="coding",
        tts_voice_hint="jarvis-default",
    ),
    "research": SessionPersonalityPack(
        id="research",
        display_name="Research session",
        system_prefix_addendum=(
            "Session mode: research. Favour sourced facts, uncertainty labels, and concise synthesis. "
            "Do not invent citations or live numbers."
        ),
        hud_theme="research",
        tts_voice_hint=None,
    ),
    "concise": SessionPersonalityPack(
        id="concise",
        display_name="Concise",
        system_prefix_addendum=(
            "Session mode: concise. Minimum words; one clear answer per turn unless detail is requested."
        ),
        hud_theme="concise",
        tts_voice_hint=None,
    ),
}


class SessionPersonalityState(BaseModel):
    active_id: SessionPersonalityId = "default"


def _normalize_id(value: str | None) -> SessionPersonalityId:
    key = (value or "").strip().lower()
    if key in PERSONALITY_PACKS:
        return key  # type: ignore[return-value]
    return "default"


def get_active_personality_id() -> SessionPersonalityId:
    settings = load_settings()
    return _normalize_id(getattr(settings.session_personality, "active_id", "default"))


def get_active_personality_pack() -> SessionPersonalityPack:
    return PERSONALITY_PACKS[get_active_personality_id()]


def set_active_personality(personality_id: str) -> SessionPersonalityPack:
    chosen = _normalize_id(personality_id)
    settings = load_settings()
    settings.session_personality = SessionPersonalityState(active_id=chosen)
    save_settings(settings)
    return PERSONALITY_PACKS[chosen]


def list_personality_packs() -> list[dict[str, Any]]:
    active = get_active_personality_id()
    out: list[dict[str, Any]] = []
    for pack in PERSONALITY_PACKS.values():
        out.append(
            {
                "id": pack.id,
                "display_name": pack.display_name,
                "hud_theme": pack.hud_theme,
                "tts_voice_hint": pack.tts_voice_hint,
                "active": pack.id == active,
            }
        )
    return out


def personality_api_payload() -> dict[str, Any]:
    pack = get_active_personality_pack()
    return {
        "active_id": pack.id,
        "display_name": pack.display_name,
        "hud_theme": pack.hud_theme,
        "personalities": list_personality_packs(),
    }


def session_personality_system_addendum() -> str:
    return (get_active_personality_pack().system_prefix_addendum or "").strip()


_SWITCH_PATTERNS: list[tuple[re.Pattern[str], SessionPersonalityId]] = [
    (
        re.compile(
            r"(?i)\b("
            r"start(?:ing)?\s+(?:a\s+)?coding\s+session|"
            r"switch(?:ing)?\s+to\s+coding(?:\s+mode)?|"
            r"coding\s+mode\s+on|"
            r"let(?:'s| us)\s+code"
            r")\b"
        ),
        "coding",
    ),
    (
        re.compile(
            r"(?i)\b("
            r"start(?:ing)?\s+(?:a\s+)?research\s+session|"
            r"switch(?:ing)?\s+to\s+research(?:\s+mode)?|"
            r"research\s+mode\s+on"
            r")\b"
        ),
        "research",
    ),
    (
        re.compile(
            r"(?i)\b("
            r"switch(?:ing)?\s+to\s+concise(?:\s+mode)?|"
            r"be\s+concise|"
            r"concise\s+mode\s+on"
            r")\b"
        ),
        "concise",
    ),
    (
        re.compile(
            r"(?i)\b("
            r"back\s+to\s+(?:default|normal|jarvis)|"
            r"switch(?:ing)?\s+to\s+default(?:\s+mode)?|"
            r"default\s+(?:butler\s+)?mode"
            r")\b"
        ),
        "default",
    ),
]

_ACK: dict[SessionPersonalityId, str] = {
    "default": "Back to default session mode, sir.",
    "coding": "Coding session mode engaged — I'll keep replies technical and precise.",
    "research": "Research session mode engaged — I'll prioritise sources and synthesis.",
    "concise": "Concise mode engaged — short answers from here.",
}


def detect_personality_switch_intent(user_text: str) -> SessionPersonalityId | None:
    text = (user_text or "").strip()
    if not text:
        return None
    for pattern, personality_id in _SWITCH_PATTERNS:
        if pattern.search(text):
            return personality_id
    return None


def maybe_apply_owner_switch_intent(user_text: str) -> dict[str, Any] | None:
    """If the owner asked to switch session personality, persist and return ack metadata."""
    target = detect_personality_switch_intent(user_text)
    if target is None:
        return None
    previous = get_active_personality_id()
    if previous == target:
        pack = PERSONALITY_PACKS[target]
        return {
            "personality_id": target,
            "display_name": pack.display_name,
            "hud_theme": pack.hud_theme,
            "changed": False,
            "acknowledgement": f"Already in {pack.display_name.lower()}, sir.",
        }
    pack = set_active_personality(target)
    return {
        "personality_id": pack.id,
        "display_name": pack.display_name,
        "hud_theme": pack.hud_theme,
        "changed": True,
        "acknowledgement": _ACK[pack.id],
    }
