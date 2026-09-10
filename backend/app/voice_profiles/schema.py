from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class VoiceProfileTTS(BaseModel):
    engine_hint: str = "system"
    speaker_ref: str = ""
    pack_path: str = ""


class VoiceProfilePersonaHooks(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    speech_register: str = Field(default="", alias="register")
    humour: str = ""


class VoiceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    archetype: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    display_name: str = Field(min_length=1, max_length=120)
    license: Literal["original", "licensed", "permissive_stock"] = "original"
    provenance: str = ""
    tts: VoiceProfileTTS = Field(default_factory=VoiceProfileTTS)
    persona_hooks: VoiceProfilePersonaHooks = Field(default_factory=VoiceProfilePersonaHooks)
    sample_utterance: str = "At your service."
    vram_class: Literal["edge", "balanced", "expressive"] = "balanced"
    builtin: bool = False


class VoiceProfileListItem(BaseModel):
    id: str
    archetype: str
    display_name: str
    license: str
    provenance: str
    tts: dict[str, Any]
    persona_hooks: dict[str, str]
    sample_utterance: str
    vram_class: str
    available: bool
    active: bool
    unavailable_reason: str | None = None
    install_hint: str | None = None


class ActiveVoiceProfileIn(BaseModel):
    voice_profile_id: str = Field(min_length=1, max_length=80)


class ActiveVoiceProfileOut(BaseModel):
    voice_profile_id: str
    profile: VoiceProfileListItem | None = None
