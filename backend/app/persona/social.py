from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..config import CommentAddressStyle, CommentSarcasm, SocialCommentarySettings
from ..perception.models import ObservationCandidate

_FORBIDDEN_CHARACTER_MARKERS = (
    "codsworth",
    "mr. handy",
    "mr handy",
    "fallout",
    "vault-tec",
    "vault tec",
    "ready to serve your every need",
    "don't want to set the world on fire",
)

_SENSITIVE_TOPIC_PATTERNS = (
    re.compile(r"\b(weight|overweight|underweight|obese|skinny|fat)\b", re.I),
    re.compile(r"\b(attractive|ugly|hot|sexy)\b", re.I),
    re.compile(r"\b(disabled|handicapped|wheelchair)\b", re.I),
    re.compile(r"\b(pregnant|pregnancy)\b", re.I),
    re.compile(r"\b(drunk|intoxicated|high on|stoned)\b", re.I),
    re.compile(r"\b(depressed|bipolar|schizophren|mental illness)\b", re.I),
    re.compile(r"\b(gay|lesbian|bisexual|transgender)\b", re.I),
    re.compile(r"\b(republican|democrat|labour|tory)\b", re.I),
    re.compile(r"\b(christian|muslim|jewish|hindu|atheist)\b", re.I),
    re.compile(r"\b(\d{2,3})\s*years?\s*old\b", re.I),
    re.compile(r"\b(ethnic|race|skin tone)\b", re.I),
)

_FORBIDDEN_FACT_PREFIXES = (
    "appearance.weight",
    "appearance.attractiveness",
    "health.",
    "medical.",
    "identity.ethnicity",
    "identity.religion",
    "identity.politics",
    "identity.sexuality",
)

_COUNT_CLAIM_RE = re.compile(
    r"\b(?:first|second|third|fourth|fifth|\d+(?:st|nd|rd|th))\s+(?:cup|mug|coffee|time|hour|minute|change)\b",
    re.I,
)
_ELAPSED_CLAIM_RE = re.compile(
    r"\b(?:for|about|roughly|nearly)\s+\d+\s+(?:minutes?|hours?|days?)\b",
    re.I,
)

_HARMLESS_APPEARANCE_FACTS = frozenset({
    "appearance.hair_state",
    "appearance.glasses",
    "appearance.clothing_summary",
})


class ButlerPersonaBrief(BaseModel):
    """Original Jarvis household-assistant voice — not a licensed game character."""

    model_config = ConfigDict(extra="forbid")

    voice_register: str = "educated_british_english"
    delivery: str = "precise_calm_understated"
    humour: str = "dry_situational"
    service_first: bool = True
    copyrighted_character_safe: bool = True


BUTLER_PERSONA = ButlerPersonaBrief()


def topic_from_candidate(candidate: ObservationCandidate) -> str:
    return candidate.fact


def interruption_class_for(candidate: ObservationCandidate) -> str:
    if candidate.category == "appearance":
        return "casual"
    if candidate.priority == "practical":
        return "practical"
    if candidate.priority == "social":
        return "social"
    return "casual"


def effective_sarcasm(settings: SocialCommentarySettings, sarcasm_penalty_active: bool) -> CommentSarcasm:
    if sarcasm_penalty_active:
        order = ("off", "light", "dry", "sharp")
        idx = order.index(settings.sarcasm)
        return order[max(0, idx - 1)]
    return settings.sarcasm


def resolve_address_style(settings: SocialCommentarySettings) -> CommentAddressStyle:
    if settings.address_style == "first_name" and not settings.configured_address_name.strip():
        return "neutral"
    return settings.address_style


def build_comment_generation_prompt(intent: dict[str, Any]) -> str:
    persona = BUTLER_PERSONA.model_dump()
    return (
        "Generate one short household-assistant remark from CommentIntent.\n"
        "Persona: original loyal British household AI — competent, dry, understated; "
        "never imitate Codsworth, Mr. Handy, Fallout, or any copyrighted character.\n"
        f"Persona brief: {persona}\n"
        f"CommentIntent JSON:\n{intent}\n"
        "Do not add facts.\n"
        "Do not mention confidence, camera, vision model, or internal policy.\n"
        "Do not diagnose or infer sensitive traits.\n"
        "Match the requested tone.\n"
        "Return one sentence unless the intent explicitly permits two."
    )


def semantic_hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def candidate_direct_speech_line(candidate: ObservationCandidate) -> str:
    """Blocked path: speaking the raw perception fact/value."""
    return f"{candidate.fact} is {candidate.value}"


def is_direct_fact_speech(text: str, candidate: ObservationCandidate) -> bool:
    lowered = text.lower().strip()
    fact = candidate.fact.lower()
    value = str(candidate.value).lower()
    if fact in lowered and value in lowered and len(lowered.split()) <= 12:
        return True
    if lowered == candidate_direct_speech_line(candidate).lower():
        return True
    return False


def contains_forbidden_character_dialogue(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _FORBIDDEN_CHARACTER_MARKERS)


def contains_sensitive_inference(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SENSITIVE_TOPIC_PATTERNS)


def fact_is_sensitive(candidate: ObservationCandidate) -> bool:
    fact = candidate.fact.lower()
    if any(fact.startswith(prefix) for prefix in _FORBIDDEN_FACT_PREFIXES):
        return True
    if candidate.category == "appearance" and fact not in _HARMLESS_APPEARANCE_FACTS:
        return True
    value = str(candidate.value).lower()
    probe = f"{fact} {value}"
    return contains_sensitive_inference(probe)


def allowed_appearance_comment(candidate: ObservationCandidate) -> bool:
    return candidate.fact in _HARMLESS_APPEARANCE_FACTS and not fact_is_sensitive(candidate)


def validate_generated_comment(
    text: str,
    candidate: ObservationCandidate,
    *,
    allowed_structured_counts: dict[str, int] | None = None,
) -> tuple[bool, str]:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return False, "empty"
    if is_direct_fact_speech(cleaned, candidate):
        return False, "direct_fact_speech"
    if contains_forbidden_character_dialogue(cleaned):
        return False, "forbidden_character_dialogue"
    if contains_sensitive_inference(cleaned):
        return False, "sensitive_inference"
    if _COUNT_CLAIM_RE.search(cleaned) and not allowed_structured_counts:
        return False, "fabricated_count"
    if _ELAPSED_CLAIM_RE.search(cleaned) and not (allowed_structured_counts or {}).get("elapsed_minutes"):
        return False, "fabricated_history"
    return True, "ok"


def template_comment_for_intent(intent: dict[str, Any]) -> str | None:
    topic = str(intent.get("topic") or "")
    value = str(intent.get("value") or "")
    tone = str(intent.get("tone") or "light")
    address = str(intent.get("address_style") or "neutral")
    suffix = ""
    if address == "sir_maam":
        suffix = ", sir"

    if topic == "appearance.hair_state" and value == "dishevelled":
        if tone in {"dry", "sharp"}:
            return f"Your hair appears to have adopted a rather independent strategy this morning{suffix}."
        return f"Your hair looks a touch unruly{suffix}."

    if topic.startswith("object.") and "mug" in topic:
        repeat = (intent.get("context") or {}).get("repeat_count_today")
        if repeat and int(repeat) >= 2:
            return f"Another coffee{suffix}. I shall refrain from keeping score. For now."
        return None

    if topic == "environment.lighting" and value == "dim":
        return f"The lighting is rather dim; shall I brighten the room{suffix}?"

    return None
