"""First-party session modes (core vs coding) with lightweight HUD hints."""

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
_CODING_STOP = re.compile(r"(?i)\b(back to (?:normal|general|jarvis)|exit coding|stop coding)\b")

_active_mode: str = "core"


@dataclass(frozen=True)
class SessionMode:
    id: str
    label: str
    hud_theme: str
    dialogue_preset: str
    task_class_hint: str = "mixed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "hud_theme": self.hud_theme,
            "dialogue_preset": self.dialogue_preset,
            "task_class_hint": self.task_class_hint,
        }


MODES: dict[str, SessionMode] = {
    "core": SessionMode("core", "Anzu / Core", "core", "jarvis_dry", "mixed"),
    "coding": SessionMode("coding", "Coding", "coding", "professional", "software engineering"),
}


def list_modes() -> list[dict[str, Any]]:
    return [mode.as_dict() for mode in MODES.values()]


def active_mode() -> SessionMode:
    return MODES.get(_active_mode, MODES["core"])


def detect_mode_from_text(text: str) -> str | None:
    sample = (text or "").strip()
    if not sample:
        return None
    if _CODING_STOP.search(sample):
        return "core"
    if _CODING_START.search(sample):
        return "coding"
    return None


def set_active_mode(mode_id: str, *, persist_dialogue: bool = True) -> SessionMode:
    global _active_mode
    key = (mode_id or "core").strip().lower()
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
