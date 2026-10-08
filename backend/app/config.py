from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def repo_root() -> Path:
    configured = os.environ.get("JARVIS_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    path = repo_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = resolved_data_sidecar_dir(
        "logs",
        local=repo_root() / "logs",
        markers=("jarvis.log", "llama-server.log"),
        need_bytes=256 * 1024**2,
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = repo_root() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def queue_dir() -> Path:
    path = resolved_data_sidecar_dir(
        "queue",
        local=data_dir() / "queue",
        markers=("pending", "processed", "failed"),
        need_bytes=256 * 1024**2,
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir() -> Path:
    """llama.cpp folder. Extra-drive `Jarvis/runtime` when C: cannot fit a fresh install."""
    return named_runtime_dir("llama.cpp", markers=("llama-server.exe", "llama-server"))


def settings_path() -> Path:
    return data_dir() / "settings.json"


def default_config_path() -> Path:
    return repo_root() / "config" / "default.json"


class InferenceSettings(BaseModel):
    backend: str = "llama.cpp"
    host: str = "127.0.0.1"
    port: int = 8088
    profile: str = "fast"
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
    orchestrator_idle_seconds: int = Field(default=120, ge=60, le=180)
    # Streaming stall budgets for manager.chat_stream. providers.base has no defaults.
    stream_first_token_base_ms: int = Field(default=2500, ge=0, le=120000)
    stream_idle_ms: int = Field(default=12000, ge=250, le=300000)
    prompt_tps_fallback: float = Field(default=80.0, gt=0, le=20000)
    stream_first_token_min_ms: int = Field(default=3000, ge=0, le=300000)
    stream_first_token_max_ms: int = Field(default=180000, ge=1000, le=600000)


class FrontResponderSettings(BaseModel):
    """RFC-0117 front lane: interpret, acknowledge, hand off.

    ``model`` is an optional OpenAI-compatible id override. Empty means the
    profile alias (or the loaded worker alias when no dedicated server is up).
    No vendor model name is hard-coded in this class; the shipped choice lives
    in ``config/default.json`` (``profile=front_2b``, CPU).

    ``device=auto`` runs front_2b on CPU (``-ngl 0``) and front_4b on GPU.
    ``device=cpu`` forces ``-ngl 0`` for either profile. ``placement=remote``
    uses a manually configured OpenAI-compatible endpoint and falls back to the
    local CPU server when that endpoint is unhealthy.
    """

    model_config = ConfigDict(validate_assignment=True)

    enabled: bool = True
    model: str = ""
    profile: str = ""
    port: int = Field(default=8089, ge=1, le=65535)
    context_size: int = Field(default=4096, ge=512, le=32768)
    resident: bool = True
    device: Literal["auto", "cpu", "gpu"] = "auto"
    n_gpu_layers: int = Field(default=0, ge=0, le=999)
    placement: Literal["local", "remote"] = "local"
    # Same vocabulary as swarm role policy (AUTO / PREFERRED / FORCED / AVOID / DISABLED).
    placement_policy: str = "AUTO"
    remote_base_url: str = ""
    remote_api_key: str = ""
    prompt_cache: bool = True
    ram_headroom_mib: int = Field(default=2048, ge=0, le=262144)
    max_output_tokens: int = Field(default=128, ge=64, le=1024)
    temperature: float = Field(default=0.25, ge=0.0, le=1.0)
    timeout_ms: int = Field(default=1500, ge=250, le=12000)
    context_turns: int = Field(default=4, ge=0, le=8)
    speak_immediately: bool = True
    parallel_when_distinct_model: bool = True


class BrowserSettings(BaseModel):
    backend: str = "playwright"
    headless: bool = False
    timeout_ms: int = 30000
    browser_use_model: str = "Qwen3.5-27B"


class VoiceSettings(BaseModel):
    """Persisted active voice profile and STT selection (RFC-0062)."""

    model_config = ConfigDict(validate_assignment=True)

    active_profile_id: str = Field(
        default="butler_original_v1",
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9_]+$",
    )
    stt_backend: Literal["auto", "faster-whisper", "whisper.cpp", "openai-whisper", "voicestudio", "windows-sapi"] = "auto"
    whisper_model: str = Field(default="", max_length=260)
    voicestudio_url: str = Field(default="http://127.0.0.1:3900", max_length=200)
    voicestudio_api_key: str = Field(default="", max_length=512)


class CodingSettings(BaseModel):
    composer_model: str = "composer-2.5"
    grok_model: str = "grok-4.6"
    specialist_model: str = ""
    allow_fast_variants: bool = False
    local_max_attempts: int = 2


class AcpAdapterSettings(BaseModel):
    """Local ACP server is opt-in; it never opens a network listener."""

    enabled: bool = False
    allowed_profiles: list[str] = Field(default_factory=lambda: ["balanced"])
    max_replay_events: int = Field(default=40, ge=1, le=200)


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
    requested_presence: Literal["none", "neural", "humanoid", "particle_bust", "galaxy"] = "neural"
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
    background_verify: bool = True


CommentFrequency = Literal["silent", "restrained", "normal", "talkative", "butler"]
CommentSarcasm = Literal["off", "light", "dry", "sharp"]
PersonalObservations = Literal["disabled", "practical_only", "casual", "broad"]
CommentAddressStyle = Literal["neutral", "sir_maam", "first_name", "configured"]


class SocialCommentarySettings(BaseModel):
    """RFC-0055 gate between perception candidates and dialogue wording."""

    model_config = ConfigDict(validate_assignment=True)

    enabled: bool = True
    comment_frequency: CommentFrequency = "restrained"
    sarcasm: CommentSarcasm = "light"
    personal_observations: PersonalObservations = "practical_only"
    address_style: CommentAddressStyle = "neutral"
    configured_address_name: str = Field(default="", max_length=80)
    min_confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    min_novelty: float = Field(default=0.35, ge=0.0, le=1.0)
    do_not_disturb: bool = False
    focus_mode: bool = False
    allow_personal_with_guests: bool = False
    reveal_household_labels_to_guests: bool = False

    @model_validator(mode="after")
    def validate_address_name(self):
        if self.address_style in {"first_name", "configured"} and not self.configured_address_name.strip():
            if self.address_style == "configured":
                raise ValueError("configured_address_name is required when address_style is configured")
        return self


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
    engine: Literal["auto", "kokoro", "voicestudio", "pocket_tts", "chatterbox_multilingual_v3", "chatterbox_turbo", "external"] = "auto"
    quality_engine: str = "kokoro"
    fallback_engine: str = "kokoro"
    loading_policy: Literal["resident", "lazy", "cpu-preferred"] = "lazy"
    language: str = "auto"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    expressiveness: float = Field(default=0.5, ge=0.0, le=1.0)
    prefer_cpu_fallback: bool = True


class KnowledgeVaultSettings(BaseModel):
    """RFC-0107 Obsidian-linked vault binding (path is write-only in API responses)."""

    model_config = ConfigDict(validate_assignment=True)

    vault_path: str = ""
    jarvis_managed_layout: bool = False
    watch_enabled: bool = True


class SupermemorySettings(BaseModel):
    """RFC-0132 optional semantic-recall sidecar.

    The API key is deliberately not part of settings. It comes from
    ``JARVIS_SUPERMEMORY_API_KEY`` or the existing credential store.
    """

    model_config = ConfigDict(validate_assignment=True)

    enabled: bool = False
    auto_start: bool = True
    base_url: str = "http://127.0.0.1:6767"
    container_prefix: str = Field(default="jarvis", min_length=1, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")
    timeout_ms: int = Field(default=1200, ge=100, le=10000)
    max_results: int = Field(default=5, ge=1, le=10)
    minimum_similarity: float = Field(default=0.45, ge=0.0, le=1.0)
    mirror_writes: bool = True
    allow_remote: bool = False


class CrucixSettings(BaseModel):
    """RFC-0127 managed local Crucix OSINT sidecar."""
    model_config = ConfigDict(validate_assignment=True)
    enabled: bool = False
    auto_start: bool = True
    base_url: str = "http://127.0.0.1:3117"
    timeout_ms: int = Field(default=8000, ge=500, le=30000)


class HexStrikeSettings(BaseModel):
    """Local HexStrike AI suite (RFC-0078). Loopback only; never a WAN listener."""

    model_config = ConfigDict(validate_assignment=True)

    install_path: str = ""
    python_executable: str = ""
    host: str = "127.0.0.1"
    port: int = Field(default=8888, ge=1, le=65535)


class ReaSettings(BaseModel):
    """RFC-0200 local REA MCP (pinned rea-agents). Disabled until owner approval."""

    model_config = ConfigDict(validate_assignment=True)

    enabled: bool = False
    package_version: str = Field(default="3.2.1", min_length=1, max_length=32)
    investigation_roots: list[str] = Field(default_factory=list)
    # Upstream process/browser scenario envs stay off unless the owner opts in.
    process_capture_enabled: bool = False
    browser_scenario_enabled: bool = False


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


class PersonaAppearanceSettings(BaseModel):
    """Per-persona appearance and playback overrides (RFC-0137).

    Empty colours and voice id mean "use the roster default". Pitch, rate, and
    volume are applied on the neural PCM path, never via SAPI.
    """

    model_config = ConfigDict(validate_assignment=True)

    voice_profile_id: str = ""
    pitch: float = Field(default=0.0, ge=-6, le=6)
    speaking_rate: float = Field(default=1.0, ge=0.75, le=1.35)
    volume: float = Field(default=1.0, ge=0, le=1)
    orb_color: str = ""
    accent_color: str = ""
    glow: float = Field(default=0.70, ge=0, le=1)
    detail: float = Field(default=0.68, ge=0.35, le=1.0)
    animation: float = Field(default=0.60, ge=0, le=1)
    scale: float = Field(default=1.0, ge=0.5, le=2.0)
    specialists_auto_speak: bool = False


class CustomPresencePreset(BaseModel):
    """Saved custom orb look (RFC-0138). Global — not tied to a named persona."""

    model_config = ConfigDict(validate_assignment=True)

    id: str
    name: str = Field(min_length=1, max_length=80)
    source: Literal["text_prompt", "image", "text_and_image"]
    source_image_ref: str = ""
    prompt_text: str = ""
    orb_composition: dict[str, Any] = Field(default_factory=dict)
    shape_id: str = ""
    default: bool = False
    created_at: str = ""
    updated_at: str = ""


class CustomPresenceSettings(BaseModel):
    """Custom presence presets and active/default selection (RFC-0138)."""

    model_config = ConfigDict(validate_assignment=True)

    presets: dict[str, CustomPresencePreset] = Field(default_factory=dict)
    active_preset_id: str = ""
    default_preset_id: str = ""


class NamedPersonaSettings(BaseModel):
    """Active named persona. Separate from session-mode HUD/prompt settings."""

    model_config = ConfigDict(validate_assignment=True)

    active_id: str = "anzu"
    default_id: str = "anzu"
    pinned_ids: list[str] = Field(default_factory=list)
    # Legacy #376 shape id, migrated on read (abzu_flow / root_coil). Not a live override.
    presence_shape_id: str = ""
    activated_voice_profile_id: str = ""
    voice_profile_requested: str = ""
    profiles: dict[str, PersonaAppearanceSettings] = Field(default_factory=dict)


class DecisionSettings(BaseModel):
    """RFC-0116/0171 decision tier + local Laya Reflex. Default is local-only."""

    model_config = ConfigDict(validate_assignment=True)

    tier: Literal["local", "jev_optional", "jev_plus"] = "local"
    notify_requested_at: str = ""
    plus_features: list[str] = Field(default_factory=list)
    last_availability: Literal["unavailable", "waitlisted", "connected", "error"] = "unavailable"
    last_probe_error: str = ""
    last_probe_at: str = ""
    last_probe_latency_ms: float | None = None
    last_model: str = ""
    laya_enabled: bool = False
    laya_warm: bool = True
    reflex_cache_ttl_s: float = 8.0
    reflex_default_deadline_ms: float = 100.0


class AppSettings(BaseModel):
    bind_host: str = "127.0.0.1"
    bind_port: int = 4780
    lan_access: bool = False
    auth_required: bool = False
    auth_token: str = ""
    inference: InferenceSettings = Field(default_factory=InferenceSettings)
    front_responder: FrontResponderSettings = Field(default_factory=FrontResponderSettings)
    autonomy: str = "trusted"
    default_timeout_seconds: int = 1800
    # Turn working-set composition (vault + tools + Supermemory). Must stay well
    # inside the front-lane ack budget (front_responder.timeout_ms=1500) so
    # retrieval cannot starve first speech. Reflex rerank is ~80–100ms.
    working_set_deadline_ms: int = Field(default=400, ge=50, le=8000)
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
    social_commentary: SocialCommentarySettings = Field(default_factory=SocialCommentarySettings)
    identity_recognition: IdentityRecognitionSettings = Field(default_factory=IdentityRecognitionSettings)
    tts: TtsSettings = Field(default_factory=TtsSettings)
    hexstrike: HexStrikeSettings = Field(default_factory=HexStrikeSettings)
    rea: ReaSettings = Field(default_factory=ReaSettings)
    knowledge_vault: KnowledgeVaultSettings = Field(default_factory=KnowledgeVaultSettings)
    supermemory: SupermemorySettings = Field(default_factory=SupermemorySettings)
    crucix: CrucixSettings = Field(default_factory=CrucixSettings)
    decision: DecisionSettings = Field(default_factory=DecisionSettings)
    named_personas: NamedPersonaSettings = Field(default_factory=NamedPersonaSettings)
    custom_presence: CustomPresenceSettings = Field(default_factory=CustomPresenceSettings)
    allowed_directories: list[str] = Field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    disabled_tools: list[str] = Field(default_factory=list)
    coding: CodingSettings = Field(default_factory=CodingSettings)
    acp_adapter: AcpAdapterSettings = Field(default_factory=AcpAdapterSettings)


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

    # Undo the former slow front-lane defaults without changing customized
    # worker context budgets. The acknowledgement lane is not a second worker.
    front_payload = payload.get("front_responder")
    legacy_front = isinstance(front_payload, dict) and front_payload.get("max_output_tokens") == 512 and front_payload.get("timeout_ms") == 6000
    if legacy_front:
        front_payload["max_output_tokens"] = 128
        front_payload["timeout_ms"] = 1500

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
    payload["allowed_directories"] = sanitize_allowed_directories(payload.get("allowed_directories"))
    settings = AppSettings.model_validate(payload)
    try:
        from .presence.custom_ui import normalize_custom_presence

        normalize_custom_presence(settings)
    except Exception:
        pass
    return settings


def save_settings(settings: AppSettings) -> None:
    dump = settings.model_dump()
    dump.pop("auth_token", None)
    dump["allowed_directories"] = sanitize_allowed_directories(dump.get("allowed_directories"))
    settings.allowed_directories = list(dump["allowed_directories"])

    def _write() -> None:
        settings_path().write_text(json.dumps(dump, indent=2), encoding="utf-8")

    try:
        from .recovery.hooks import wrap_settings_save

        wrap_settings_save(_write)
    except Exception:
        _write()


LOCAL_NETWORK_SCOPE = "<local-network-shares>"

# Virtual Linux filesystems that are not owner "drives".
_POSIX_SKIP_FSTYPES = frozenset(
    {
        "proc",
        "sysfs",
        "cgroup",
        "cgroup2",
        "devtmpfs",
        "devpts",
        "securityfs",
        "pstore",
        "bpf",
        "tracefs",
        "debugfs",
        "configfs",
        "fusectl",
        "mqueue",
        "hugetlbfs",
        "overlay",
        "nsfs",
        "autofs",
        "rpc_pipefs",
        "binfmt_misc",
    }
)


def _windows_owner_drives() -> list[Path]:
    """Expose mounted scannable drives to the local owner within OS account ACLs."""
    if os.name != "nt":
        return []
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.GetLogicalDrives.restype = ctypes.c_uint32
    kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetDriveTypeW.restype = ctypes.c_uint32
    mask = kernel32.GetLogicalDrives()
    roots: list[Path] = []
    for index in range(26):
        if mask & (1 << index):
            root = f"{chr(65 + index)}:\\"
            # removable, fixed, remote/mapped, optical, ramdisk
            if kernel32.GetDriveTypeW(root) in {2, 3, 4, 5, 6}:
                roots.append(Path(root))
    return roots


def _posix_owner_roots() -> list[Path]:
    """Every real mount the owner can already see through the OS account."""
    if os.name == "nt":
        return []
    roots: list[Path] = [Path("/")]
    try:
        import psutil

        for part in psutil.disk_partitions(all=False):
            fstype = (part.fstype or "").lower()
            if fstype in _POSIX_SKIP_FSTYPES:
                continue
            mount = Path(part.mountpoint)
            if mount.exists():
                roots.append(mount)
    except Exception:
        for extra in (Path("/media"), Path("/mnt"), Path("/run/media")):
            if extra.exists():
                roots.append(extra)
    return roots


def os_volume_root() -> Path:
    """System volume (`C:\\` or `/`). Extra-drive scans skip this root."""
    if os.name == "nt":
        return Path(Path.home().anchor or "C:\\")
    return Path("/")


def _posix_volume_parent_children(parent: Path) -> list[Path]:
    """USB labels live under `/media/<user>/<label>` or `/mnt/<label>`."""
    try:
        children = [path for path in parent.iterdir() if path.is_dir()]
    except OSError:
        return []
    two_level = parent in {Path("/media"), Path("/run/media")} or parent.name == "media"
    if not two_level:
        return children
    found: list[Path] = []
    for child in children:
        try:
            grandchildren = [path for path in child.iterdir() if path.is_dir()]
        except OSError:
            grandchildren = []
        if grandchildren:
            found.extend(grandchildren)
        else:
            found.append(child)
    return found


def extra_volume_roots() -> list[Path]:
    """Mounted owner volumes that are not the OS system volume.

    USB sticks, `D:`, mapped drives, `/media` mounts — places an owner copies
    GGUFs or archives when the system volume is full. Does not include `/` or
    `C:\\`, and does not recurse into those trees.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return []
    os_root = os_volume_root()
    try:
        os_resolved = os_root.resolve()
    except OSError:
        os_resolved = os_root
    skip_keys = {
        str(os_root).replace("\\", "/").rstrip("/").lower(),
        str(os_resolved).replace("\\", "/").rstrip("/").lower(),
        "",
        "/",
    }
    raw = _windows_owner_drives() if os.name == "nt" else _posix_owner_roots()
    expanded: list[Path] = []
    posix_parents = {Path("/media"), Path("/mnt"), Path("/run/media")}
    for root in raw:
        if os.name != "nt" and (root in posix_parents or root.name in {"media", "mnt"}):
            expanded.extend(_posix_volume_parent_children(root))
            continue
        expanded.append(root)
    out: list[Path] = []
    seen: set[str] = set()
    for root in expanded:
        try:
            if not root.exists():
                continue
            resolved = root.resolve()
        except OSError:
            continue
        key = str(resolved).replace("\\", "/").rstrip("/").lower()
        if key in skip_keys or key in seen or resolved == os_resolved:
            continue
        seen.add(key)
        out.append(root)
    return out


_RUNTIME_NEED_BYTES = 2 * 1024**3


def extra_volume_runtime_root(*, need_bytes: int = 0) -> Path | None:
    """`Jarvis/runtime` on the extra volume with the most free space that fits."""
    required = int(need_bytes or 0)
    best: Path | None = None
    best_free = 0
    for volume in extra_volume_roots():
        try:
            free = int(shutil.disk_usage(volume).free)
        except OSError:
            continue
        if required and free < required:
            continue
        if free > best_free:
            best_free = free
            best = volume / "Jarvis" / "runtime"
    return best


def extra_volume_named_runtime_dirs(name: str) -> list[Path]:
    """Candidate sidecar folders on extra volumes (`Jarvis/runtime/<name>`)."""
    slug = str(name or "").strip()
    if not slug:
        return []
    out: list[Path] = []
    seen: set[str] = set()
    for volume in extra_volume_roots():
        for rel in (
            Path("Jarvis") / "runtime" / slug,
            Path("runtime") / slug,
            Path("Jarvis") / slug,
        ):
            candidate = volume / rel
            key = str(candidate).replace("\\", "/").lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(candidate)
    return out


def _runtime_marker_path(root: Path, marker: str) -> Path:
    parts = [part for part in str(marker or "").replace("\\", "/").split("/") if part and part != "."]
    return root.joinpath(*parts) if parts else root


def discover_named_runtime_dir(name: str, *, marker: str) -> Path | None:
    """Existing local or extra-drive sidecar that already has `marker`."""
    slug = str(name or "").strip()
    needle = str(marker or "").strip()
    if not slug or not needle:
        return None
    candidates = [repo_root() / "runtime" / slug, *extra_volume_named_runtime_dirs(slug)]
    for root in candidates:
        try:
            hit = _runtime_marker_path(root, needle)
            if hit.is_file() or hit.is_dir():
                return root
        except OSError:
            continue
    return None


def named_runtime_dir(
    name: str,
    *,
    markers: str | tuple[str, ...] = "",
    need_bytes: int = _RUNTIME_NEED_BYTES,
) -> Path:
    """Discover an existing sidecar, else `preferred_runtime_install_dir`."""
    needles = markers if isinstance(markers, tuple) else ((markers,) if markers else ())
    for needle in needles:
        existing = discover_named_runtime_dir(name, marker=needle)
        if existing is not None:
            return existing
    return preferred_runtime_install_dir(name, need_bytes=need_bytes)


def preferred_runtime_install_dir(name: str, *, need_bytes: int = _RUNTIME_NEED_BYTES) -> Path:
    """Install under `runtime/<name>` when that volume fits; else extra-drive `Jarvis/runtime`."""
    slug = str(name or "").strip() or "runtime"
    local = repo_root() / "runtime" / slug
    required = int(need_bytes or 0)
    try:
        local_free = int(shutil.disk_usage(repo_root()).free)
    except OSError:
        local_free = 0
    if required <= 0 or local_free >= required:
        return local
    extra = extra_volume_runtime_root(need_bytes=required)
    if extra is None:
        return local
    return extra / slug


_DATA_SIDECAR_NEED_BYTES = 1024**3
_PLAYWRIGHT_NEED_BYTES = 1024**3


def resolved_data_sidecar_dir(
    name: str,
    *,
    local: Path,
    markers: tuple[str, ...] = (),
    need_bytes: int = _DATA_SIDECAR_NEED_BYTES,
) -> Path:
    """Keep `local` when that volume fits or already has files; else extra-drive `Jarvis/runtime/<name>`."""
    slug = str(name or "").strip()
    if not slug:
        return local
    for marker in markers:
        try:
            hit = _runtime_marker_path(local, marker)
            if hit.is_file() or hit.is_dir():
                return local
        except OSError:
            continue
    if not markers:
        try:
            if local.is_dir() and any(local.iterdir()):
                return local
        except OSError:
            pass
    for marker in markers or ("",):
        for candidate in extra_volume_named_runtime_dirs(slug):
            try:
                if marker:
                    hit = _runtime_marker_path(candidate, marker)
                    if hit.is_file() or hit.is_dir():
                        return candidate
                elif candidate.is_dir() and any(candidate.iterdir()):
                    return candidate
            except OSError:
                continue
    required = int(need_bytes or 0)
    try:
        probe = local if local.exists() else local.parent
        if not probe.exists():
            probe = repo_root()
        local_free = int(shutil.disk_usage(probe).free)
    except OSError:
        local_free = 0
    extra_root = extra_volume_runtime_root(need_bytes=required)
    if extra_root is not None and required > 0 and local_free < required:
        return extra_root / slug
    return local


def playwright_user_data_dir() -> Path:
    """Playwright persistent profile. Extra-drive `Jarvis/runtime/browser-profile` when C: cannot fit."""
    dest = resolved_data_sidecar_dir(
        "browser-profile",
        local=data_dir() / "browser-profile",
        markers=("Local State", "Default"),
        need_bytes=_DATA_SIDECAR_NEED_BYTES,
    )
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def browser_use_user_data_dir() -> Path:
    """Browser Use profile. Extra-drive `Jarvis/runtime/browser-use-profile` when C: cannot fit."""
    dest = resolved_data_sidecar_dir(
        "browser-use-profile",
        local=data_dir() / "browser-use-profile",
        markers=("Local State", "Default"),
        need_bytes=_DATA_SIDECAR_NEED_BYTES,
    )
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def default_playwright_browsers_dir() -> Path:
    """Playwright's own default (`%LOCALAPPDATA%\\ms-playwright` or `~/.cache/ms-playwright`)."""
    if os.name == "nt":
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        root = Path(local) if local else Path.home() / "AppData" / "Local"
        return root / "ms-playwright"
    xdg = (os.environ.get("XDG_CACHE_HOME") or "").strip()
    cache = Path(xdg) if xdg else Path.home() / ".cache"
    return cache / "ms-playwright"


def _playwright_chromium_present(root: Path) -> bool:
    try:
        if not root.is_dir():
            return False
        for child in root.iterdir():
            name = child.name.lower()
            if child.is_dir() and (name.startswith("chromium") or name.startswith("ffmpeg")):
                return True
    except OSError:
        return False
    return False


def extra_volume_playwright_browsers_dir() -> Path | None:
    for candidate in extra_volume_named_runtime_dirs("ms-playwright"):
        if _playwright_chromium_present(candidate):
            return candidate
    return None


def playwright_browsers_dir() -> Path:
    """Chromium folder. Extra-drive `Jarvis/runtime/ms-playwright` when C: cannot fit a fresh install."""
    for raw in (
        os.environ.get("JARVIS_PLAYWRIGHT_BROWSERS"),
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),
    ):
        text = (raw or "").strip()
        if text:
            return Path(text).expanduser()
    extra_existing = extra_volume_playwright_browsers_dir()
    if extra_existing is not None:
        return extra_existing
    local = default_playwright_browsers_dir()
    if _playwright_chromium_present(local):
        return local
    required = _PLAYWRIGHT_NEED_BYTES
    try:
        probe = local if local.exists() else local.parent
        if not probe.exists():
            probe = Path.home()
        local_free = int(shutil.disk_usage(probe).free)
    except OSError:
        local_free = 0
    extra_root = extra_volume_runtime_root(need_bytes=required)
    if extra_root is not None and local_free < required:
        return extra_root / "ms-playwright"
    return local


def apply_playwright_browsers_path() -> Path:
    """Point Playwright at extra-drive Chromium when that is the install dest."""
    dest = playwright_browsers_dir()
    dest.mkdir(parents=True, exist_ok=True)
    default = default_playwright_browsers_dir()
    try:
        same = dest.resolve() == default.resolve()
    except OSError:
        same = False
    if not same:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(dest)
    return dest


def default_allowed_directories() -> list[str]:
    home = Path.home()
    candidates = [
        # The local owner's signed-in profile is the default workspace, so
        # AppData and other ordinary owner folders do not fail the sandbox check.
        home,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        repo_root(),
        data_dir(),
        *_windows_owner_drives(),
        *_posix_owner_roots(),
    ]
    roots: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        if not path.exists():
            continue
        text = str(path)
        key = text.replace("/", "\\").lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(text)
    # Private LAN shares (Windows UNC / POSIX //host/share) for cyberdefense and media.
    roots.append(LOCAL_NETWORK_SCOPE)
    return roots


def is_ephemeral_workspace_path(path: str) -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    normalized = str(path or "").replace("/", "\\").lower()
    return "\\pytest-of-" in normalized or "\\pytest\\" in normalized


def sanitize_allowed_directories(existing: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    testing = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    for raw in existing or []:
        text = str(raw or "").strip()
        if not text:
            continue
        if not testing and is_ephemeral_workspace_path(text):
            continue
        key = text.replace("/", "\\").lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    if testing:
        return cleaned
    if not cleaned:
        return default_allowed_directories()
    for item in default_allowed_directories():
        key = item.replace("/", "\\").lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


def live_allowed_directories(existing: list[str] | None = None) -> list[str]:
    """Saved workspace plus currently mounted owner drives (USB, D:, /media).

    Tool registry already unions on each call. LTA recovery, HexStrike local
    evidence, and the security target registry must use this too so a plugged-in
    volume is usable without a settings save.
    """
    if existing is None:
        existing = list(getattr(load_settings(), "allowed_directories", None) or [])
    return sanitize_allowed_directories(list(existing or []))


def live_workspace_roots_from_context(raw: Any = None) -> list[str]:
    """Tool context or AppSettings → live owner workspace (USB / D: / /media union).

    Browser file:// gates and tools that skip ToolRegistry._live_context still need
    a plugged-in volume without a settings save. A dict with no allowed_directories
    key stays unbound (empty list) so unit tests that construct tools without a
    registry keep the historical unrestricted cwd; pass None to load settings.
    """
    if raw is None:
        return live_allowed_directories()
    if isinstance(raw, AppSettings):
        return live_allowed_directories(list(raw.allowed_directories or []))
    if isinstance(raw, dict):
        if "allowed_directories" not in raw:
            return []
        return live_allowed_directories(list(raw.get("allowed_directories") or []))
    existing = list(getattr(raw, "allowed_directories", None) or [])
    return live_allowed_directories(existing if existing else None)


def live_tool_workspace_roots(raw: Any = None) -> list[str]:
    """Workspace roots for tools that deny paths when the allowlist is empty.

    Terminal/python keep ``live_workspace_roots_from_context({})`` as unbound cwd.
    Desktop screenshots, Browser Use file://, and ingest constructed without a
    registry getter must load settings so a plugged-in USB is still in scope.
    """
    if raw is None or (isinstance(raw, dict) and "allowed_directories" not in raw):
        return live_allowed_directories()
    return live_workspace_roots_from_context(raw)
