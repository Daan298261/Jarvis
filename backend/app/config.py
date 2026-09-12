from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    path = repo_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = repo_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = repo_root() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def queue_dir() -> Path:
    path = data_dir() / "queue"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir() -> Path:
    return repo_root() / "runtime" / "llama.cpp"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def default_config_path() -> Path:
    return repo_root() / "config" / "default.json"


class InferenceSettings(BaseModel):
    backend: str = "llama.cpp"
    host: str = "127.0.0.1"
    port: int = 8088
    profile: str = "balanced"
    context_size: int = 16384
    flash_attn: str = "auto"
    fit: bool = True
    fit_target_mib: int = 1024
    cache_type_k: str = "q8_0"
    cache_type_v: str = "q8_0"
    threads: int = 0
    auto_load: bool = True
    vision: bool = False
    vision_mode: str = "lazy"
    remote_model: str = ""
    api_key: str = ""
    lmstudio_models_root: str = ""


class BrowserSettings(BaseModel):
    backend: str = "playwright"
    headless: bool = False
    timeout_ms: int = 30000
    browser_use_model: str = "Qwen3.5-27B"


class VoiceSettings(BaseModel):
    """Persisted active voice profile selection (RFC-0062)."""

    model_config = ConfigDict(validate_assignment=True)

    active_profile_id: str = Field(
        default="butler_original_v1",
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9_]+$",
    )


class CodingSettings(BaseModel):
    composer_model: str = "composer-2.5"
    grok_model: str = "grok-4.6"
    specialist_model: str = ""
    allow_fast_variants: bool = False
    local_max_attempts: int = 2


class SelfDevSettings(BaseModel):
    max_duration_hours: float = 12.0
    max_paid_spend_eur: float = 0.0
    max_paid_invocations: int = 0
    max_consecutive_failures: int = 3
    experimental_port: int = 4781
    auto_merge: bool = False


class PresentationSettings(BaseModel):
    """Persisted visual-presentation preference. Camera/biometric data is never stored here."""

    model_config = ConfigDict(validate_assignment=True)

    shell: Literal["classic", "hud"] = "hud"
    requested_presence: Literal["none", "neural", "humanoid"] = "neural"
    performance_preset: Literal["auto", "efficient", "balanced", "cinematic"] = "auto"
    attention_mode: Literal["off", "pointer", "camera"] = "pointer"
    reduced_motion: Literal["system", "reduce", "full"] = "system"
    avatar_id: str = Field(default="jarvis_base", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")


class DialogueSettings(BaseModel):
    """Language, verbosity and personality policy from RFC-0063.

    This is presentation policy only. Tool calls, code, commands, paths, JSON,
    hashes and quoted evidence must bypass stylistic rewriting.
    """

    model_config = ConfigDict(validate_assignment=True)

    enabled: bool = True
    worker_profile: str = "qwen35-08b-presentation"
    output_language: str = "auto"
    translate_only_when_needed: bool = True
    verbosity: Literal["very-short", "concise", "balanced", "detailed", "exhaustive", "auto"] = "auto"
    auto_preference: Literal["concise", "balanced", "detailed"] = "concise"
    personality_preset: Literal["minimal", "professional", "jarvis_dry", "friendly", "custom"] = "jarvis_dry"
    humor_frequency: float = Field(default=0.12, ge=0.0, le=1.0)
    warmth: float = Field(default=0.35, ge=0.0, le=1.0)
    formality: float = Field(default=0.65, ge=0.0, le=1.0)
    dryness: float = Field(default=0.35, ge=0.0, le=1.0)
    directness: float = Field(default=0.90, ge=0.0, le=1.0)
    preserve_structured_content: bool = True


class SocialPerceptionSettings(BaseModel):
    """Local semantic-perception policy. Disabled means no semantic frame processing."""

    model_config = ConfigDict(validate_assignment=True)

    enabled: bool = False
    semantic_observer: str = Field(default="none", min_length=1, max_length=64)
    sample_interval_seconds: float = Field(default=5.0, ge=1.0, le=3600.0)
    min_confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    novelty_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    comment_cooldown_seconds: int = Field(default=900, ge=0, le=86400)
    duplicate_ttl_seconds: int = Field(default=3600, ge=0, le=604800)
    baseline_enabled: bool = True
    retain_observation_summaries: bool = False
    max_summary_retention_hours: int = Field(default=24, ge=1, le=168)


class TtsSettings(BaseModel):
    """Text-to-speech preferences for chat replies and voice output."""

    model_config = ConfigDict(validate_assignment=True)

    speak_chat_replies: bool = True
    voice_profile_id: str = ""
    engine: Literal["auto", "chatterbox_multilingual_v3", "kokoro", "chatterbox_turbo", "external"] = "auto"
    quality_engine: str = "chatterbox_multilingual_v3"
    fallback_engine: str = "kokoro"
    loading_policy: Literal["resident", "lazy", "cpu-preferred"] = "lazy"
    language: str = "auto"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    expressiveness: float = Field(default=0.5, ge=0.0, le=1.0)
    prefer_cpu_fallback: bool = True


class HexStrikeSettings(BaseModel):
    """Local HexStrike AI suite (RFC-0078). Loopback only; never a WAN listener."""

    model_config = ConfigDict(validate_assignment=True)

    install_path: str = ""
    python_executable: str = ""
    host: str = "127.0.0.1"
    port: int = Field(default=8888, ge=1, le=65535)


class IdentityRecognitionSettings(BaseModel):
    """Explicit, local-only biometric identity matching. Disabled by default."""

    model_config = ConfigDict(validate_assignment=True)

    enabled: bool = False
    backend: str = Field(default="none", min_length=1, max_length=64)
    match_threshold: float = Field(default=0.45, ge=-1.0, le=1.0)
    margin_threshold: float = Field(default=0.08, ge=0.0, le=1.0)
    min_face_quality: float = Field(default=0.60, ge=0.0, le=1.0)
    confirmation_window: int = Field(default=5, ge=1, le=20)
    confirmation_hits: int = Field(default=3, ge=1, le=20)
    lost_timeout_seconds: float = Field(default=3.0, ge=0.0, le=60.0)
    expose_identity_to_dialogue: bool = True

    @model_validator(mode="after")
    def validate_confirmation_window(self):
        if self.confirmation_hits > self.confirmation_window:
            raise ValueError("confirmation_hits must not exceed confirmation_window")
        return self


class AppSettings(BaseModel):
    bind_host: str = "127.0.0.1"
    bind_port: int = 4780
    lan_access: bool = False
    auth_required: bool = False
    auth_token: str = ""
    inference: InferenceSettings = Field(default_factory=InferenceSettings)
    autonomy: str = "trusted"
    default_timeout_seconds: int = 1800
    retry_limit: int = 4
    execution_mode: str = "balanced"
    logging_level: str = "INFO"
    backup_enabled: bool = True
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    self_dev: SelfDevSettings = Field(default_factory=SelfDevSettings)
    presentation: PresentationSettings = Field(default_factory=PresentationSettings)
    dialogue: DialogueSettings = Field(default_factory=DialogueSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    social_perception: SocialPerceptionSettings = Field(default_factory=SocialPerceptionSettings)
    identity_recognition: IdentityRecognitionSettings = Field(default_factory=IdentityRecognitionSettings)
    tts: TtsSettings = Field(default_factory=TtsSettings)
    hexstrike: HexStrikeSettings = Field(default_factory=HexStrikeSettings)
    allowed_directories: list[str] = Field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    disabled_tools: list[str] = Field(default_factory=list)
    coding: CodingSettings = Field(default_factory=CodingSettings)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_settings() -> AppSettings:
    payload: dict[str, Any] = {}
    if default_config_path().exists():
        payload = json.loads(default_config_path().read_text(encoding="utf-8"))
    if settings_path().exists():
        payload = _deep_merge(payload, json.loads(settings_path().read_text(encoding="utf-8")))

    token = (
        os.environ.get("JARVIS_PRIVATE_KEY")
        or os.environ.get("JARVIS_API_KEY")
        or os.environ.get("JARVIS_AUTH_TOKEN")
        or payload.get("auth_token", "")
    )
    key_file = data_dir() / "private_key.sec"
    if not token and key_file.exists():
        try:
            token = key_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    payload["auth_token"] = token
    inference_key = os.environ.get("JARVIS_INFERENCE_API_KEY")
    if inference_key:
        inference = payload.get("inference")
        if not isinstance(inference, dict):
            inference = {}
            payload["inference"] = inference
        inference["api_key"] = inference_key
    host = os.environ.get("JARVIS_BIND_HOST")
    port = os.environ.get("JARVIS_BIND_PORT")
    if host:
        payload["bind_host"] = host
    if port:
        payload["bind_port"] = int(port)
    return AppSettings.model_validate(payload)


def save_settings(settings: AppSettings) -> None:
    dump = settings.model_dump()
    dump.pop("auth_token", None)
    settings_path().write_text(json.dumps(dump, indent=2), encoding="utf-8")


def default_allowed_directories() -> list[str]:
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        repo_root(),
        data_dir(),
    ]
    return [str(path) for path in candidates if path.exists()]
