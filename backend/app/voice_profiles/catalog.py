from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import load_settings, repo_root, save_settings
from ..tts.engines import pick_engine_for_profile
from .ip_guard import contains_forbidden_ip_term, validate_profile_ip_fields
from .schema import VoiceProfile, VoiceProfileListItem

DEFAULT_VOICE_PROFILE_ID = "butler_original_v1"


def voice_packs_dir() -> Path:
    return repo_root() / "voice_packs"


def _resolve_pack_path(pack_path: str) -> Path | None:
    raw = (pack_path or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = repo_root() / path
    return path


def _profile_is_available(profile: VoiceProfile) -> tuple[bool, str | None, str | None]:
    if contains_forbidden_ip_term(profile.id) or contains_forbidden_ip_term(profile.display_name):
        return False, "forbidden", "Profile violates IP guardrails."

    pack = _resolve_pack_path(profile.tts.pack_path)
    if pack is not None:
        if not pack.is_dir():
            return (
                False,
                "install_required",
                f"Install this voice from Settings (Get more voices) or run Setup with bundled packs.",
            )
        manifest = pack / "pack.json"
        if not manifest.is_file():
            return (
                False,
                "install_required",
                "One-click install is available in Settings for this voice profile.",
            )

    engine = pick_engine_for_profile(profile)
    if engine is None:
        return (
            False,
            "tts_unavailable",
            "No local TTS engine is available for this profile. Re-run Jarvis Setup or install Kokoro weights.",
        )
    return True, None, None


def _load_profile_file(path: Path) -> VoiceProfile | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        profile = VoiceProfile.model_validate(payload)
        validate_profile_ip_fields(
            profile_id=profile.id,
            display_name=profile.display_name,
            archetype=profile.archetype,
            pack_path=profile.tts.pack_path,
        )
        return profile
    except Exception:
        return None


def _discover_profiles() -> dict[str, VoiceProfile]:
    profiles: dict[str, VoiceProfile] = {}
    root = voice_packs_dir()
    if not root.is_dir():
        return profiles
    for path in sorted(root.glob("*/profile.json")):
        profile = _load_profile_file(path)
        if profile is not None:
            profiles[profile.id] = profile
    return profiles


class VoiceProfileCatalog:
    def __init__(self, profiles: dict[str, VoiceProfile] | None = None) -> None:
        self._profiles = profiles if profiles is not None else _discover_profiles()

    def list_profiles(self, active_id: str) -> list[VoiceProfileListItem]:
        items: list[VoiceProfileListItem] = []
        for profile in sorted(self._profiles.values(), key=lambda item: item.display_name.lower()):
            available, reason, hint = _profile_is_available(profile)
            items.append(
                VoiceProfileListItem(
                    id=profile.id,
                    archetype=profile.archetype,
                    display_name=profile.display_name,
                    license=profile.license,
                    provenance=profile.provenance,
                    tts=profile.tts.model_dump(),
                    persona_hooks=profile.persona_hooks.model_dump(by_alias=True),
                    sample_utterance=profile.sample_utterance,
                    vram_class=profile.vram_class,
                    available=available,
                    active=profile.id == active_id,
                    unavailable_reason=reason,
                    install_hint=hint,
                )
            )
        return items

    def get(self, profile_id: str) -> VoiceProfile | None:
        return self._profiles.get(profile_id)

    def get_available(self, profile_id: str) -> VoiceProfile | None:
        profile = self.get(profile_id)
        if profile is None:
            return None
        available, _reason, _hint = _profile_is_available(profile)
        return profile if available else None


@lru_cache(maxsize=1)
def get_catalog() -> VoiceProfileCatalog:
    return VoiceProfileCatalog()


def reload_catalog() -> VoiceProfileCatalog:
    get_catalog.cache_clear()
    return get_catalog()


def get_active_voice_profile_id() -> str:
    settings = load_settings()
    active = (settings.voice.active_profile_id or "").strip()
    if active and not contains_forbidden_ip_term(active):
        return active
    return DEFAULT_VOICE_PROFILE_ID


def get_active_voice_profile() -> VoiceProfile | None:
    catalog = get_catalog()
    active_id = get_active_voice_profile_id()
    return catalog.get_available(active_id) or catalog.get_available(DEFAULT_VOICE_PROFILE_ID)


def set_active_voice_profile_id(profile_id: str) -> VoiceProfileListItem:
    cleaned = (profile_id or "").strip()
    if not cleaned:
        raise ValueError("voice_profile_id is required")
    validate_profile_ip_fields(
        profile_id=cleaned,
        display_name=cleaned,
        archetype=cleaned,
    )
    catalog = get_catalog()
    profile = catalog.get(cleaned)
    if profile is None:
        raise LookupError(f"Unknown voice profile: {cleaned}")
    available, reason, hint = _profile_is_available(profile)
    if not available:
        detail: dict[str, Any] = {
            "error": reason or "unavailable",
            "detail": hint or "Voice profile is not available.",
            "profile_id": cleaned,
        }
        raise PermissionError(json.dumps(detail))

    settings = load_settings()
    settings.voice.active_profile_id = cleaned
    save_settings(settings)
    items = catalog.list_profiles(cleaned)
    for item in items:
        if item.id == cleaned:
            return item
    raise LookupError(f"Voice profile not listed after activation: {cleaned}")
