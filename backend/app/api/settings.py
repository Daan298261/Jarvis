from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import load_settings, save_settings
from ..inference.backends import suggested_port
from ..tools.registry import REGISTRY

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    autonomy: str | None = None
    allowed_directories: list[str] | None = None
    default_timeout_seconds: int | None = None
    retry_limit: int | None = None
    logging_level: str | None = None
    lan_access: bool | None = None
    auth_required: bool | None = None
    private_key: str | None = None
    bind_host: str | None = None
    bind_port: int | None = None
    backup_enabled: bool | None = None
    profile: str | None = None
    execution_mode: str | None = None
    inference_backend: str | None = None
    inference_host: str | None = None
    inference_port: int | None = None
    inference_vision: bool | None = None
    inference_remote_model: str | None = None
    inference_api_key: str | None = None
    vision_mode: str | None = None
    browser_headless: bool | None = None
    self_dev_max_duration_hours: float | None = None
    self_dev_max_paid_spend_eur: float | None = None
    self_dev_max_paid_invocations: int | None = None
    self_dev_max_consecutive_failures: int | None = None
    self_dev_experimental_port: int | None = None
    social_perception_enabled: bool | None = None
    social_perception_semantic_observer: str | None = Field(default=None, min_length=1, max_length=64)
    social_perception_sample_interval_seconds: float | None = Field(default=None, ge=1.0, le=3600.0)
    social_perception_min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    social_perception_novelty_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    social_perception_comment_cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)
    social_perception_duplicate_ttl_seconds: int | None = Field(default=None, ge=0, le=604800)
    social_perception_baseline_enabled: bool | None = None
    social_perception_retain_observation_summaries: bool | None = None
    social_perception_max_summary_retention_hours: int | None = Field(default=None, ge=1, le=168)
    identity_recognition_enabled: bool | None = None
    identity_recognition_backend: str | None = Field(default=None, min_length=1, max_length=64)
    identity_recognition_match_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)
    identity_recognition_margin_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    identity_recognition_min_face_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    identity_recognition_confirmation_window: int | None = Field(default=None, ge=1, le=20)
    identity_recognition_confirmation_hits: int | None = Field(default=None, ge=1, le=20)
    identity_recognition_lost_timeout_seconds: float | None = Field(default=None, ge=0.0, le=60.0)
    identity_recognition_expose_identity_to_dialogue: bool | None = None


@router.get("")
async def get_settings():
    return load_settings().model_dump()


@router.put("")
async def update_settings(body: SettingsUpdate):
    settings = load_settings()
    if body.autonomy is not None:
        settings.autonomy = body.autonomy
    if body.allowed_directories is not None:
        settings.allowed_directories = body.allowed_directories
    if body.default_timeout_seconds is not None:
        settings.default_timeout_seconds = body.default_timeout_seconds
    if body.retry_limit is not None:
        settings.retry_limit = body.retry_limit
    if body.logging_level is not None:
        settings.logging_level = body.logging_level
    if body.lan_access is not None:
        settings.lan_access = body.lan_access
        settings.bind_host = "0.0.0.0" if body.lan_access else "127.0.0.1"
        settings.auth_required = bool(body.lan_access or settings.auth_required)
    if body.auth_required is not None:
        settings.auth_required = body.auth_required
    if body.private_key is not None:
        key = body.private_key.strip()
        settings.auth_token = key
        from ..auth import private_key_file_path

        try:
            private_key_file_path().write_text(key + "\n", encoding="utf-8")
        except Exception:
            pass
    if body.bind_host is not None:
        settings.bind_host = body.bind_host
    if body.bind_port is not None:
        settings.bind_port = body.bind_port
    if body.backup_enabled is not None:
        settings.backup_enabled = body.backup_enabled
    if body.profile is not None:
        settings.inference.profile = body.profile
    if body.execution_mode is not None:
        settings.execution_mode = body.execution_mode
    if body.inference_backend is not None:
        settings.inference.backend = body.inference_backend
        if body.inference_port is None:
            settings.inference.port = suggested_port(body.inference_backend, settings.inference.port)
    if body.inference_host is not None:
        settings.inference.host = body.inference_host
    if body.inference_port is not None:
        settings.inference.port = body.inference_port
    if body.inference_vision is not None:
        settings.inference.vision = body.inference_vision
    if body.inference_remote_model is not None:
        settings.inference.remote_model = body.inference_remote_model
    if body.inference_api_key is not None:
        settings.inference.api_key = body.inference_api_key
    if body.vision_mode is not None:
        settings.inference.vision_mode = body.vision_mode
        settings.inference.vision = body.vision_mode in {"always", "on"}
    if body.browser_headless is not None:
        settings.browser.headless = body.browser_headless
    if body.self_dev_max_duration_hours is not None:
        settings.self_dev.max_duration_hours = body.self_dev_max_duration_hours
    if body.self_dev_max_paid_spend_eur is not None:
        settings.self_dev.max_paid_spend_eur = body.self_dev_max_paid_spend_eur
    if body.self_dev_max_paid_invocations is not None:
        settings.self_dev.max_paid_invocations = body.self_dev_max_paid_invocations
    if body.self_dev_max_consecutive_failures is not None:
        settings.self_dev.max_consecutive_failures = body.self_dev_max_consecutive_failures
    if body.self_dev_experimental_port is not None:
        settings.self_dev.experimental_port = body.self_dev_experimental_port

    perception = settings.social_perception
    if body.social_perception_enabled is not None:
        perception.enabled = body.social_perception_enabled
    if body.social_perception_semantic_observer is not None:
        perception.semantic_observer = body.social_perception_semantic_observer
    if body.social_perception_sample_interval_seconds is not None:
        perception.sample_interval_seconds = body.social_perception_sample_interval_seconds
    if body.social_perception_min_confidence is not None:
        perception.min_confidence = body.social_perception_min_confidence
    if body.social_perception_novelty_threshold is not None:
        perception.novelty_threshold = body.social_perception_novelty_threshold
    if body.social_perception_comment_cooldown_seconds is not None:
        perception.comment_cooldown_seconds = body.social_perception_comment_cooldown_seconds
    if body.social_perception_duplicate_ttl_seconds is not None:
        perception.duplicate_ttl_seconds = body.social_perception_duplicate_ttl_seconds
    if body.social_perception_baseline_enabled is not None:
        perception.baseline_enabled = body.social_perception_baseline_enabled
    if body.social_perception_retain_observation_summaries is not None:
        perception.retain_observation_summaries = body.social_perception_retain_observation_summaries
    if body.social_perception_max_summary_retention_hours is not None:
        perception.max_summary_retention_hours = body.social_perception_max_summary_retention_hours

    recognition_values = settings.identity_recognition.model_dump()
    recognition_updates = {
        "enabled": body.identity_recognition_enabled,
        "backend": body.identity_recognition_backend,
        "match_threshold": body.identity_recognition_match_threshold,
        "margin_threshold": body.identity_recognition_margin_threshold,
        "min_face_quality": body.identity_recognition_min_face_quality,
        "confirmation_window": body.identity_recognition_confirmation_window,
        "confirmation_hits": body.identity_recognition_confirmation_hits,
        "lost_timeout_seconds": body.identity_recognition_lost_timeout_seconds,
        "expose_identity_to_dialogue": body.identity_recognition_expose_identity_to_dialogue,
    }
    for key, value in recognition_updates.items():
        if value is not None:
            recognition_values[key] = value
    settings.identity_recognition = type(settings.identity_recognition).model_validate(recognition_values)

    save_settings(settings)
    REGISTRY.apply_settings(settings)
    return settings.model_dump()
