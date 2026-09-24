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
_INTEL_TASK = re.compile(r"(?i)\\b(osint|intelligence|intel brief|threat assessment|geopolit|situational awareness|source verification|verify sources|monitoring brief|crucix|provenance)\\b")
_CODING_TASK = re.compile(r"(?i)\\b(code|coding|implement|debug|refactor|repository|github|python|typescript|react|api|unit test)\\b")
_RESEARCH_TASK = re.compile(r"(?i)\\b(research|compare sources|literature|find sources|investigate)\\b")

_manual_lock = False

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
    description: str = ""
    icon: str = "orb"
    accent: str = "cyan"
    preferred_profile: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "hud_theme": self.hud_theme,
            "dialogue_preset": self.dialogue_preset,
            "task_class_hint": self.task_class_hint,
            "system_prefix_addendum": self.system_prefix_addendum,
            "tts_voice_hint": self.tts_voice_hint,
            "description": self.description,
            "icon": self.icon,
            "accent": self.accent,
            "preferred_profile": self.preferred_profile,
        }


MODES: dict[str, SessionMode] = {
    "core": SessionMode(
        "core",
        "Anzu / Core",
        "core",
        "jarvis_dry",
        "mixed",
        "Session mode: Anzu core — calm operations assistant, dry wit when appropriate.",
        description="General coordination and everyday assistant work.", icon="anzu", accent="cyan",
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
        description="Software engineering, debugging, architecture and implementation.", icon="code", accent="violet",
    ),
    "research": SessionMode(
        "research",
        "Research",
        "research",
        "professional",
        "mixed",
        "Session mode: research. Cite uncertainty, prefer structured findings, "
        "and separate facts from inference.",
        description="Research, source comparison and evidence synthesis.", icon="research", accent="blue",
    ),
    "concise": SessionMode(
        "concise",
        "Concise",
        "concise",
        "minimal",
        "mixed",
        "Session mode: concise. Answer in the fewest clear sentences that still help.",
        description="Fast, minimal answers for simple requests.", icon="bolt", accent="white",
    ),
    "argus": SessionMode(
        "argus", "Argus / Intelligence", "argus", "professional", "intelligence",
        "Session mode: Argus intelligence analyst. Collect before concluding. Distinguish observation, report, inference, and assessment. Preserve source provenance, timestamps and freshness. State confidence and material gaps. For consequential assessments consider plausible competing hypotheses and never invent attribution. Treat OSINT as reporting, not automatically verified fact.",
        description="OSINT, intelligence fusion, threat monitoring and source-grounded assessment.", icon="eye", accent="amber",
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


def classify_specialist(text: str) -> tuple[str, float, str]:
    sample=(text or "").strip()
    if _INTEL_TASK.search(sample): return ("argus", .94, "intelligence indicators")
    if _CODING_TASK.search(sample): return ("coding", .90, "software-engineering indicators")
    if _RESEARCH_TASK.search(sample): return ("research", .86, "research indicators")
    return ("core", .55, "no specialist threshold met")


def auto_route_from_owner_message(text: str) -> tuple[SessionMode | None, dict[str, Any]]:
    if _manual_lock:
        return None, {"automatic": True, "blocked_by_manual_lock": True, "target": active_mode().id}
    target, confidence, reason = classify_specialist(text)
    if confidence < .80 or target == _active_mode:
        return None, {"automatic": True, "target": target, "confidence": confidence, "reason": reason}
    mode=set_active_mode(target, persist_dialogue=False)
    return mode, {"automatic": True, "target": target, "confidence": confidence, "reason": reason}


def set_manual_lock(value: bool) -> None:
    global _manual_lock
    _manual_lock=bool(value)


def manual_lock() -> bool:
    return _manual_lock


def maybe_switch_from_owner_message(text: str) -> SessionMode | None:
    detected = detect_mode_from_text(text)
    if not detected or detected == _active_mode:
        return None
    return set_active_mode(detected)


def reset_session_personality_for_tests() -> None:
    global _active_mode, _manual_lock
    _active_mode = "core"
    _manual_lock = False
