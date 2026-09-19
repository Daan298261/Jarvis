"""First-party session modes (Anzu core, coding, research, concise) with HUD + prompt hints.

Extends PR #334 / RFC-0126 with RFC-0130 prompt addenda and extra modes.
Does not merge Instagram persona_candidate trees (RFC-0104).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import load_settings, save_settings

_CODING_START = re.compile(
    r"(?i)\b("
    r"start(?:\s+a)?\s+coding\s+session|"
    r"let'?s\s+code|"
    r"switch\s+to\s+coding|"
    r"enter\s+coding\s+mode"
    r")\b",
)
_RESEARCH_START = re.compile(
    r"(?i)\b("
    r"start(?:\s+a)?\s+research\s+session|"
    r"switch\s+to\s+research|"
    r"research\s+mode"
    r")\b",
)
_CONCISE_START = re.compile(
    r"(?i)\b("
    r"be\s+concise|"
    r"concise\s+mode|"
    r"short\s+answers\s+only"
    r")\b",
)
_BACK_TO_CORE = re.compile(
    r"(?i)\b("
    r"back to (?:normal|general|jarvis|core|anzu)|"
    r"exit (?:coding|research|concise)|"
    r"stop coding|"
    r"default (?:mode|personality)"
    r")\b"
)

_active_mode: str = "core"


@dataclass(frozen=True)
class SessionMode:
    id: str
    label: str
    hud_theme: str
    dialogue_preset: str
    task_class_hint: str = "mixed"
    system_prefix_addendum: str = ""
    tts_voice_hint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "hud_theme": self.hud_theme,
            "dialogue_preset": self.dialogue_preset,
            "task_class_hint": self.task_class_hint,
            "system_prefix_addendum": self.system_prefix_addendum,
            "tts_voice_hint": self.tts_voice_hint,
        }


MODES: dict[str, SessionMode] = {
    "core": SessionMode(
        "core",
        "Anzu / Core",
        "core",
        "jarvis_dry",
        "mixed",
        "Session mode: Anzu core — calm operations assistant, dry wit when appropriate.",
    ),
    "coding": SessionMode(
        "coding",
        "Coding",
        "coding",
        "professional",
        "software engineering",
        "Session mode: coding. Be precise about code, files, tests, and diffs. "
        "Prefer actionable steps; skip social filler unless the owner asks.",
        "jarvis-default",
    ),
    "research": SessionMode(
        "research",
        "Research",
        "research",
        "professional",
        "mixed",
        "Session mode: research. Cite uncertainty, prefer structured findings, "
        "and separate facts from inference.",
    ),
    "concise": SessionMode(
        "concise",
        "Concise",
        "concise",
        "minimal",
        "mixed",
        "Session mode: concise. Answer in the fewest clear sentences that still help.",
    ),
}

_ALIASES = {"default": "core", "jarvis": "core", "anzu": "core"}


def list_modes() -> list[dict[str, Any]]:
    return [mode.as_dict() for mode in MODES.values()]


def active_mode() -> SessionMode:
    return MODES.get(_active_mode, MODES["core"])


def session_personality_system_addendum() -> str:
    return (active_mode().system_prefix_addendum or "").strip()


def _normalize_mode_id(mode_id: str) -> str:
    key = (mode_id or "core").strip().lower().replace("-", "_")
    return _ALIASES.get(key, key)


def detect_mode_from_text(text: str) -> str | None:
    sample = (text or "").strip()
    if not sample:
        return None
    if _BACK_TO_CORE.search(sample):
        return "core"
    if _CODING_START.search(sample):
        return "coding"
    if _RESEARCH_START.search(sample):
        return "research"
    if _CONCISE_START.search(sample):
        return "concise"
    return None


def set_active_mode(mode_id: str, *, persist_dialogue: bool = True) -> SessionMode:
    global _active_mode
    key = _normalize_mode_id(mode_id)
    if key not in MODES:
        raise KeyError(f"unknown session mode: {mode_id}")
    _active_mode = key
    mode = MODES[key]
    if persist_dialogue:
        settings = load_settings()
        settings.dialogue.personality_preset = mode.dialogue_preset  # type: ignore[assignment]
        save_settings(settings)
    return mode


def maybe_switch_from_owner_message(text: str) -> SessionMode | None:
    detected = detect_mode_from_text(text)
    if not detected or detected == _active_mode:
        return None
    return set_active_mode(detected)


def reset_session_personality_for_tests() -> None:
    global _active_mode
    _active_mode = "core"
