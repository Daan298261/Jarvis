"""Named persona catalog (RFC-0137): shape, neural voice, appearance, specialists.

Session modes stay HUD + prompt. This module never writes a SAPI / system voice
and never treats HexStrike as a persona.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from ..config import AppSettings, PersonaAppearanceSettings, load_settings, save_settings
from ..voice_profiles.catalog import (
    WINDOWS_NATURAL_VOICE_PROFILE_ID,
    _profile_is_available,
    get_active_voice_profile_id,
    get_catalog,
    set_active_voice_profile_id,
)
from ..voice_profiles.ip_guard import contains_forbidden_ip_term

logger = logging.getLogger(__name__)

_SYSTEM_ENGINES = frozenset({"system", "sapi", "windows", "espeak", "espeak-ng", "pyttsx3"})
_ID_ALIASES = {"eagir": "aegir", "ægir": "aegir"}
_SHAPE_MIGRATION = {"abzu_flow": "code_cube", "root_coil": "serpent_orbit"}

# Function phrases in roster order. The first clause uses "coordinating" for Anzu
# and when Anzu is attached to a non-Anzu main.
_PHRASES = (
    "coordinating",
    "planning",
    "researching",
    "coding",
    "analysing threats",
    "verifying security",
    "handling media",
    "writing",
    "messaging",
    "watching",
    "looking after the house",
    "growing the audience",
    "working the systems",
)


@dataclass(frozen=True)
class PersonaRow:
    id: str
    label: str
    role: str
    presence_shape_id: str
    voice_profile_id: str
    orb: str
    accent: str
    speaking_rate: float
    pitch: float
    glow: float = 0.70
    animation: float = 0.60
    scale: float = 1.0
    phrase: str = ""


def _row(
    persona_id: str,
    label: str,
    role: str,
    shape: str,
    voice: str,
    orb: str,
    accent: str,
    rate: float,
    pitch: float,
    phrase: str,
    *,
    glow: float = 0.70,
    animation: float = 0.60,
    scale: float = 1.0,
) -> PersonaRow:
    return PersonaRow(
        id=persona_id,
        label=label,
        role=role,
        presence_shape_id=shape,
        voice_profile_id=voice,
        orb=orb,
        accent=accent,
        speaking_rate=rate,
        pitch=pitch,
        glow=glow,
        animation=animation,
        scale=scale,
        phrase=phrase,
    )


ROSTER: tuple[PersonaRow, ...] = (
    _row("anzu", "Anzu", "Main assistant, orchestration, swarm control", "stormbird", "butler_original_v1", "#9B1B30", "#D4A017", 1.00, 0, _PHRASES[0], scale=1.15),
    _row("mestor", "Mestor", "Planning, missions and operations", "command_facet", "tactical_aide_original_v1", "#1E3A8A", "#F8FAFC", 0.96, -1, _PHRASES[1]),
    _row("nabu", "Nabu", "Memory, research and knowledge", "memory_rings", "dry_butler_original_v1", "#D97706", "#312E81", 0.92, 0, _PHRASES[2]),
    _row("enki", "Enki", "Coding, engineering and automation", "code_cube", "synthetic_command_original_v1", "#22D3EE", "#2563EB", 1.06, 1, _PHRASES[3]),
    _row("veles", "Veles", "Red Team, threat intelligence and adversarial analysis", "serpent_orbit", "synthetic_command_original_v1", "#5B21B6", "#84CC16", 0.84, -3, _PHRASES[4]),
    _row("themis", "Themis", "Blue Team, defence, policy and auditing", "twin_shield", "tactical_aide_original_v1", "#E0F2FE", "#FFFFFF", 1.10, 1, _PHRASES[5]),
    _row("aegir", "Aegir", "Media, communications, cameras and audio", "ocean_swell", "chatterbox_expressive_en_v1", "#0D9488", "#0C4A6E", 0.98, 0, _PHRASES[6], animation=0.60),
    _row("bragi", "Bragi", "Writing, creativity, manuscripts and dialogue", "waveform_letters", "chatterbox_expressive_en_v1", "#C026D3", "#EAB308", 1.02, 1, _PHRASES[7], animation=0.90),
    _row("hermes", "Hermes", "Browser, messaging, APIs and fast communications", "comet_trail", "chatterbox_expressive_en_v1", "#FACC15", "#06B6D4", 1.22, 2, _PHRASES[8], scale=0.92),
    _row("heimdall", "Heimdall", "Monitoring, sensors, cameras and alerts", "eye_radar", "tactical_aide_original_v1", "#F97316", "#1D4ED8", 1.00, 0, _PHRASES[9]),
    _row("eir", "Eir", "Wellbeing, routines and household care", "breath_leaf", "dry_butler_original_v1", "#6EE7B7", "#FDA4AF", 0.80, -1, _PHRASES[10], glow=0.50, animation=0.35),
    _row("maia", "Maia", "Marketing, social media and audience growth", "star_social", "chatterbox_expressive_en_v1", "#FB7185", "#F472B6", 1.12, 1, _PHRASES[11]),
    _row("vulcan", "Vulcan", "Hardware, infrastructure and physical systems", "forge_core", "synthetic_command_original_v1", "#EA580C", "#DC2626", 0.90, -2, _PHRASES[12], scale=1.05),
)

CATALOG: dict[str, PersonaRow] = {row.id: row for row in ROSTER}
ROSTER_IDS: tuple[str, ...] = tuple(row.id for row in ROSTER)


class NamedPersonaBindError(Exception):
    def __init__(self, code: str, detail: str, profile_id: str = "") -> None:
        self.code = code
        self.detail = detail
        self.profile_id = profile_id
        super().__init__(detail)


def pack_status(profile_id: str) -> str:
    """Return ok, install_required, or tts_unavailable. System packs are never ok."""
    pid = (profile_id or "").strip()
    if not pid or pid == WINDOWS_NATURAL_VOICE_PROFILE_ID or contains_forbidden_ip_term(pid):
        return "tts_unavailable"
    profile = get_catalog().get(pid)
    if profile is None:
        return "install_required"
    if profile.tts.resolved_engine_id() in _SYSTEM_ENGINES:
        return "tts_unavailable"
    available, reason, _hint = _profile_is_available(profile)
    if available:
        return "ok"
    if reason == "install_required":
        return "install_required"
    return "tts_unavailable"


def resolve_persona_id(raw: str | None, *, required: bool = True) -> str:
    text = (raw or "").strip()
    if not text:
        if required:
            raise NamedPersonaBindError("unknown", "Persona id is required")
        return "anzu"
    if contains_forbidden_ip_term(text):
        raise NamedPersonaBindError("unknown", "Unknown persona id")
    key = _ID_ALIASES.get(text.lower(), text.lower())
    if key not in CATALOG:
        raise NamedPersonaBindError("unknown", f"Unknown persona id: {text}")
    return key


def roster_appearance(row: PersonaRow) -> PersonaAppearanceSettings:
    return PersonaAppearanceSettings(
        voice_profile_id="",
        pitch=row.pitch,
        speaking_rate=row.speaking_rate,
        volume=1.0,
        orb_color="",
        accent_color="",
        glow=row.glow,
        animation=row.animation,
        scale=row.scale,
        specialists_auto_speak=False,
    )


def migrate_named_persona_store(settings: AppSettings) -> bool:
    """Rewrite #376 ids on read. Does not register eagir, abzu_flow, or root_coil."""
    store = settings.named_personas
    changed = False
    raw_id = (store.active_id or "").strip()
    aliased = _ID_ALIASES.get(raw_id.lower(), raw_id.lower()) if raw_id else ""
    if raw_id and aliased in CATALOG and aliased != raw_id:
        store.active_id = aliased
        changed = True
    elif raw_id and raw_id not in CATALOG and raw_id.lower() in CATALOG:
        store.active_id = raw_id.lower()
        changed = True
    shape = (store.presence_shape_id or "").strip()
    if shape in _SHAPE_MIGRATION:
        store.presence_shape_id = _SHAPE_MIGRATION[shape]
        changed = True
    if "eagir" in store.profiles:
        existing = store.profiles.pop("eagir")
        store.profiles.setdefault("aegir", existing)
        changed = True
    return changed


def _load() -> tuple[AppSettings, bool]:
    settings = load_settings()
    changed = migrate_named_persona_store(settings)
    if not (settings.named_personas.active_id or "").strip():
        settings.named_personas.active_id = "anzu"
        changed = True
    if changed:
        save_settings(settings)
    return settings, changed


def _appearance_for(settings: AppSettings, persona_id: str) -> PersonaAppearanceSettings:
    stored = settings.named_personas.profiles.get(persona_id)
    if stored is None:
        return roster_appearance(CATALOG[persona_id])
    return stored


def _resolve_voice(persona_id: str, appearance: PersonaAppearanceSettings) -> tuple[str, str]:
    """Return (voice_to_activate, voice_profile_requested).

    voice_profile_requested is set only for Anzu's dry-butler fallback.
    """
    row = CATALOG[persona_id]
    requested = (appearance.voice_profile_id or "").strip() or row.voice_profile_id
    status = pack_status(requested)
    if status == "ok":
        return requested, ""
    if requested != row.voice_profile_id:
        appearance.voice_profile_id = ""
        if pack_status(row.voice_profile_id) == "ok":
            return row.voice_profile_id, ""
    if persona_id == "anzu" and pack_status(row.voice_profile_id) != "ok" and pack_status("dry_butler_original_v1") == "ok":
        return "dry_butler_original_v1", "butler_original_v1"
    code = status if status in {"install_required", "tts_unavailable"} else "tts_unavailable"
    if requested != row.voice_profile_id and pack_status(row.voice_profile_id) != "ok":
        code = pack_status(row.voice_profile_id)
    raise NamedPersonaBindError(
        code,
        "Neural voice pack is not available. Refusing SAPI and any other pack.",
        requested,
    )


def _activate(profile_id: str) -> None:
    status = pack_status(profile_id)
    if status != "ok":
        raise NamedPersonaBindError(status, "Neural voice pack is not available.", profile_id)
    try:
        set_active_voice_profile_id(profile_id)
    except PermissionError as exc:
        code = "tts_unavailable"
        try:
            payload = json.loads(str(exc))
            if isinstance(payload, dict) and payload.get("error"):
                code = str(payload["error"])
        except json.JSONDecodeError:
            pass
        raise NamedPersonaBindError(code, "Neural voice pack is not available.", profile_id) from exc
    except LookupError as exc:
        raise NamedPersonaBindError("install_required", "Unknown voice profile.", profile_id) from exc


def apply_main_persona(raw_id: str, *, reset: bool = False) -> dict:
    """Bind shape + neural voice, then persist. A failed bind leaves the previous id."""
    persona_id = resolve_persona_id(raw_id, required=True)
    settings, _changed = _load()
    store = settings.named_personas
    previous_id = store.active_id if store.active_id in CATALOG else "anzu"
    row = CATALOG[persona_id]
    if reset or persona_id not in store.profiles:
        appearance = roster_appearance(row)
    else:
        appearance = store.profiles[persona_id].model_copy(deep=True)
    voice_id, requested = _resolve_voice(persona_id, appearance)
    _activate(voice_id)
    store.profiles[persona_id] = appearance
    store.active_id = persona_id
    store.presence_shape_id = row.presence_shape_id
    store.activated_voice_profile_id = voice_id
    store.voice_profile_requested = requested
    save_settings(settings)
    logger.info(
        "named_persona_apply %s",
        json.dumps({"id": persona_id, "voice_profile_id": voice_id, "previous": previous_id}),
    )
    return public_state()


def update_appearance(raw_id: str, patch: dict | None, *, reset: bool = False) -> dict:
    """Persist per-persona overrides. Pitch/rate/volume do not change the voice id."""
    persona_id = resolve_persona_id(raw_id, required=True)
    settings, _changed = _load()
    store = settings.named_personas
    row = CATALOG[persona_id]
    if reset or persona_id not in store.profiles:
        appearance = roster_appearance(row)
    else:
        appearance = store.profiles[persona_id].model_copy(deep=True)
    data = dict(patch or {})
    voice = data.pop("voice_profile_id", None)
    if voice is not None:
        cleaned = str(voice or "").strip()
        if cleaned and pack_status(cleaned) != "ok":
            raise NamedPersonaBindError(
                pack_status(cleaned),
                "Voice override must be an available neural pack.",
                cleaned,
            )
        appearance.voice_profile_id = cleaned
    try:
        for key in ("pitch", "speaking_rate", "volume", "glow", "animation", "scale"):
            if key in data and data[key] is not None:
                setattr(appearance, key, float(data[key]))
    except (ValidationError, ValueError) as exc:
        raise NamedPersonaBindError("unknown", str(exc)) from exc
    for key in ("orb_color", "accent_color"):
        if key in data and data[key] is not None:
            color = str(data[key] or "").strip()
            if color and not _hex_color(color):
                raise NamedPersonaBindError("unknown", f"{key} must be a #RRGGBB colour")
            setattr(appearance, key, color)
    if "specialists_auto_speak" in data and data["specialists_auto_speak"] is not None:
        appearance.specialists_auto_speak = bool(data["specialists_auto_speak"])
    rebind = bool(reset or voice is not None)
    if rebind and (persona_id == store.active_id or store.active_id not in CATALOG):
        voice_id, requested = _resolve_voice(persona_id, appearance)
        _activate(voice_id)
        store.active_id = persona_id
        store.presence_shape_id = row.presence_shape_id
        store.activated_voice_profile_id = voice_id
        store.voice_profile_requested = requested
    store.profiles[persona_id] = appearance
    save_settings(settings)
    return public_state()


def _hex_color(value: str) -> bool:
    if len(value) != 7 or not value.startswith("#"):
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def _persona_payload(
    row: PersonaRow,
    appearance: PersonaAppearanceSettings,
    *,
    activated: str = "",
    requested: str = "",
) -> dict:
    voice = activated or (appearance.voice_profile_id or "").strip() or row.voice_profile_id
    payload = {
        "id": row.id,
        "label": row.label,
        "role": row.role,
        "presence_shape_id": row.presence_shape_id,
        "voice_profile_id": voice,
        "voice_profile_requested": requested or None,
        "default_colors": {"orb": row.orb, "accent": row.accent},
        "appearance": {
            "voice_profile_id": (appearance.voice_profile_id or "").strip() or row.voice_profile_id,
            "pitch": appearance.pitch,
            "speaking_rate": appearance.speaking_rate,
            "volume": appearance.volume,
            "orb_color": appearance.orb_color or row.orb,
            "accent_color": appearance.accent_color or row.accent,
            "glow": appearance.glow,
            "animation": appearance.animation,
            "scale": appearance.scale,
            "specialists_auto_speak": appearance.specialists_auto_speak,
        },
    }
    return payload


def public_state() -> dict:
    settings, _changed = _load()
    store = settings.named_personas
    known = store.active_id in CATALOG
    active_id = store.active_id if known else ""
    personas = []
    active_payload = None
    for row in ROSTER:
        appearance = _appearance_for(settings, row.id)
        if row.id == active_id:
            payload = _persona_payload(
                row,
                appearance,
                activated=store.activated_voice_profile_id,
                requested=store.voice_profile_requested,
            )
            active_payload = payload
        else:
            payload = _persona_payload(row, appearance)
        personas.append(payload)
    if active_payload is None:
        active_payload = {
            "id": "",
            "label": "",
            "role": "",
            "presence_shape_id": "",
            "voice_profile_id": "",
            "voice_profile_requested": None,
            "default_colors": {"orb": "", "accent": ""},
            "appearance": {},
        }
    return {"active": active_payload, "personas": personas}


def active_persona_id() -> str:
    settings, _changed = _load()
    active = settings.named_personas.active_id
    return active if active in CATALOG else "anzu"


def active_playback_overrides() -> tuple[float, float, float] | None:
    """Persona rate/pitch/volume once a main persona has been bound. None before that."""
    try:
        settings = load_settings()
    except Exception:
        return None
    store = settings.named_personas
    if not store.activated_voice_profile_id and not store.profiles:
        return None
    persona_id = store.active_id if store.active_id in CATALOG else "anzu"
    appearance = store.profiles.get(persona_id) or roster_appearance(CATALOG[persona_id])
    return float(appearance.speaking_rate), float(appearance.pitch), float(appearance.volume)


def card_sentence(main_id: str, specialist_ids: list[str] | tuple[str, ...]) -> str:
    """Locked card copy. Empty when no specialist other than the main persona is attached."""
    try:
        main = resolve_persona_id(main_id, required=True)
    except NamedPersonaBindError:
        main = "anzu"
    cleaned: list[str] = []
    for raw in specialist_ids or []:
        try:
            cleaned.append(resolve_persona_id(str(raw), required=True))
        except NamedPersonaBindError:
            continue
    others = [persona_id for persona_id in ROSTER_IDS if persona_id in cleaned and persona_id != main]
    if not others:
        return ""
    main_row = CATALOG[main]
    anzu_attached = main == "anzu" or "anzu" in cleaned
    if anzu_attached:
        first = f"{main_row.label} is coordinating."
    else:
        first = f"{main_row.label} is {main_row.phrase}."
    parts = [first]
    for persona_id in others:
        row = CATALOG[persona_id]
        parts.append(f"{row.label} is {row.phrase}.")
    return " ".join(parts)


def reapply_stored_main_persona() -> dict | None:
    """Process start: pair the stored persona's shape and neural voice again."""
    try:
        settings, _changed = _load()
        persona_id = settings.named_personas.active_id or "anzu"
        if persona_id not in CATALOG:
            return None
        return apply_main_persona(persona_id, reset=False)
    except NamedPersonaBindError as exc:
        logger.info("named_persona_reapply_failed code=%s profile=%s", exc.code, exc.profile_id)
        return None


async def attach_specialist(raw_id: str, task_id: str) -> dict:
    """Write specialist_persona_ids on the task. Does not replace the main persona."""
    persona_id = resolve_persona_id(raw_id, required=True)
    cleaned_task = (task_id or "").strip()
    if not cleaned_task:
        raise NamedPersonaBindError("unknown", "task_id is required")
    settings, _changed = _load()
    appearance = _appearance_for(settings, persona_id).model_copy(deep=True)
    spoken = False
    if appearance.specialists_auto_speak:
        try:
            voice_id, _requested = _resolve_voice(persona_id, appearance)
            main_voice = settings.named_personas.activated_voice_profile_id
            _activate(voice_id)
            spoken = True
            if main_voice and main_voice != voice_id and pack_status(main_voice) == "ok":
                _activate(main_voice)
        except NamedPersonaBindError:
            spoken = False
    from ..db.models import Task
    from ..db.session import SessionLocal

    async with SessionLocal() as session:
        task = await session.get(Task, cleaned_task)
        if task is None:
            raise LookupError(f"Unknown task: {cleaned_task}")
        try:
            current = json.loads(task.specialist_persona_ids or "[]")
        except json.JSONDecodeError:
            current = []
        if not isinstance(current, list):
            current = []
        ids = [str(item) for item in current if isinstance(item, str)]
        if persona_id not in ids:
            ids.append(persona_id)
        task.specialist_persona_ids = json.dumps(ids)
        await session.commit()
    state = public_state()
    state["task_id"] = cleaned_task
    state["specialist_persona_ids"] = ids
    state["card_sentence"] = card_sentence(state["active"]["id"], ids)
    state["specialist_spoken"] = spoken
    return state
