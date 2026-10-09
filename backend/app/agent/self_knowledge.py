"""RFC-0206 live self-awareness snapshot for the front lane.

Code reading in-memory state. Not a reflex generation and not a tool call.
"""

from __future__ import annotations

import json
import re
from typing import Any

PRODUCT_NAME = "ANZU Superassistant"

# Owner-facing keys that may appear in the snapshot and the prompt.
SNAPSHOT_INCLUDE_KEYS = (
    "product_name",
    "active_persona_id",
    "inference_profile",
    "inference_backend",
    "loaded",
    "model_alias",
    "context_size",
    "server_n_ctx",
    "family",
    "front_lane_enabled",
    "front_profile",
    "front_placement",
    "front_device",
    "front_timeout_ms",
    "front_max_output_tokens",
    "decision_tier",
    "jev_availability",
    "laya_installed",
    "laya_warm",
    "laya_enabled",
    "voice_profile_id",
    "tts_engine",
    "tts_quality_engine",
    "dialogue_verbosity",
    "personality_preset",
    "output_language",
    "address_style",
    "shell",
    "vault_bound",
)

# Must never appear as keys or values in the dict or the rendered prompt.
_SECRET_KEY_FRAGMENTS = (
    "auth_token",
    "api_key",
    "remote_api_key",
    "voicestudio_api_key",
    "typesafe",
    "license",
    "lease",
    "secret",
    "password",
    "credential",
)
_PATH_KEY_FRAGMENTS = (
    "model_path",
    "gguf_path",
    "mmproj_path",
    "vault_path",
    "remote_base_url",
    "path",
)
_ABSENT_ASK = re.compile(
    r"(?i)\b("
    r"api key|secret|token|password|pid|process id|tool catalog|"
    r"vault path|model path|gguf|mmproj|license key|lease"
    r")\b"
)

_FIELD_HINTS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"(?i)\b(?:your |loaded |inference |which |what )?profile(?: is loaded)?\b"), ("inference_profile", "front_profile", "voice_profile_id", "loaded", "model_alias")),
    (
        re.compile(
            r"(?i)("
            r"\byour model\b|"
            r"\bmodel alias\b|"
            r"\b(?:what|which) model(?: is loaded| are you(?: running| using)?| is running)\b|"
            r"\bwhat(?:'s| is) loaded\b|"
            r"\binference (?:profile|model)\b"
            r")"
        ),
        ("model_alias", "inference_profile", "family", "loaded"),
    ),
    (re.compile(r"(?i)\b(?:loaded profile|is loaded|currently loaded)\b"), ("loaded", "inference_profile", "model_alias")),
    (re.compile(r"(?i)\b(?:your |active )?persona\b"), ("active_persona_id",)),
    (
        re.compile(
            r"(?i)("
            r"\byour context (?:size|window|length)\b|"
            r"\b(?:configured |live |server )?n_ctx\b|"
            r"\bcontext (?:size|window)\b"
            r")"
        ),
        ("context_size", "server_n_ctx"),
    ),
    (re.compile(r"(?i)\b(front lane|front responder)\b"), ("front_lane_enabled", "front_profile", "front_device", "front_timeout_ms")),
    (re.compile(r"(?i)\b(jev|laya|decision tier)\b"), ("decision_tier", "jev_availability", "laya_installed", "laya_warm", "laya_enabled")),
    (re.compile(r"(?i)\b(?:your )?voice(?: profile)?\b"), ("voice_profile_id", "tts_engine", "tts_quality_engine")),
    (re.compile(r"(?i)\b(verbosity|personality|language)\b"), ("dialogue_verbosity", "personality_preset", "output_language")),
    (re.compile(r"(?i)\b(?:your )?shell\b"), ("shell",)),
    (re.compile(r"(?i)\b(?:your |knowledge )?vault bound\b"), ("vault_bound",)),
    (re.compile(r"(?i)\b(who are you|what are you(?:\s*[?.!]?\s*$| (?:called|named))|your name|anzu)\b"), ("product_name", "active_persona_id")),
)


def _label(value: Any) -> str:
    text = str(value or "").strip()
    return text


def build_self_knowledge_snapshot(settings: Any, inference_state: Any | None = None) -> dict[str, Any]:
    """Live in-memory readings. Secrets, paths, pids, and tool catalogs are omitted."""
    state = inference_state
    if state is None:
        try:
            from ..inference.manager import MANAGER

            state = MANAGER.state
        except Exception:
            state = None

    inference = getattr(settings, "inference", None)
    front = getattr(settings, "front_responder", None)
    voice = getattr(settings, "voice", None)
    tts = getattr(settings, "tts", None)
    dialogue = getattr(settings, "dialogue", None)
    social = getattr(settings, "social_commentary", None)
    presentation = getattr(settings, "presentation", None)
    vault = getattr(settings, "knowledge_vault", None)
    personas = getattr(settings, "named_personas", None)
    decision = getattr(settings, "decision", None)

    # In-memory labels only. Never call resolve_status() / load_settings() / lease /
    # secret-store here — those belong off the owner-turn decision path (RFC-0206 §1).
    jev_label = _label(getattr(decision, "last_availability", "") or "unavailable")
    laya_installed = False
    laya_warm = False
    laya_enabled = bool(getattr(decision, "laya_enabled", False))
    try:
        from ..decision.laya import runtime as laya_runtime

        laya = laya_runtime.status()
        laya_installed = bool(laya.get("installed"))
        laya_warm = bool(laya.get("warm"))
        laya_enabled = bool(laya.get("enabled")) if laya.get("enabled") is not None else laya_enabled
    except Exception:
        pass

    server_n_ctx = int(getattr(state, "server_n_ctx", 0) or 0) if state is not None else 0
    snapshot: dict[str, Any] = {
        "product_name": PRODUCT_NAME,
        "active_persona_id": _label(getattr(personas, "active_id", "") or "anzu"),
        "inference_profile": _label(getattr(state, "profile", None) or getattr(inference, "profile", "") or ""),
        "inference_backend": _label(getattr(state, "backend", None) or getattr(inference, "backend", "") or ""),
        "loaded": bool(getattr(state, "loaded", False)) if state is not None else False,
        "model_alias": _label(getattr(state, "alias", "") or ""),
        "context_size": int(getattr(state, "context_size", 0) or getattr(inference, "context_size", 0) or 0),
        "family": _label(getattr(state, "family", "") or ""),
        "front_lane_enabled": bool(getattr(front, "enabled", True)),
        "front_profile": _label(getattr(front, "profile", "") or ""),
        "front_placement": _label(getattr(front, "placement", "") or ""),
        "front_device": _label(getattr(front, "device", "") or ""),
        "front_timeout_ms": int(getattr(front, "timeout_ms", 0) or 0),
        "front_max_output_tokens": int(getattr(front, "max_output_tokens", 0) or 0),
        "decision_tier": _label(getattr(decision, "tier", "") or "local"),
        "jev_availability": jev_label,
        "laya_installed": laya_installed,
        "laya_warm": laya_warm,
        "laya_enabled": laya_enabled,
        "voice_profile_id": _label(getattr(voice, "active_profile_id", "") or ""),
        "tts_engine": _label(getattr(tts, "engine", "") or ""),
        "tts_quality_engine": _label(getattr(tts, "quality_engine", "") or ""),
        "dialogue_verbosity": _label(getattr(dialogue, "verbosity", "") or ""),
        "personality_preset": _label(getattr(dialogue, "personality_preset", "") or ""),
        "output_language": _label(getattr(dialogue, "output_language", "") or ""),
        "address_style": _label(getattr(social, "address_style", "") or ""),
        "shell": _label(getattr(presentation, "shell", "") or ""),
        "vault_bound": bool(str(getattr(vault, "vault_path", "") or "").strip()),
    }
    if server_n_ctx:
        snapshot["server_n_ctx"] = server_n_ctx
    return {key: snapshot[key] for key in SNAPSHOT_INCLUDE_KEYS if key in snapshot}


def snapshot_prompt_addendum(snapshot: dict[str, Any]) -> str:
    """Owner-facing ANZU addendum. The model may only read this JSON."""
    body = json.dumps(snapshot, ensure_ascii=True, sort_keys=True)
    return (
        "You are ANZU Superassistant answering a question about your own live setup.\n"
        "Use only the self-knowledge snapshot JSON below. Do not invent fields.\n"
        "If a reading is not in the snapshot, say that reading is not in the self snapshot, "
        "in one sentence, and do not guess.\n"
        f"{body}"
    )


def snapshot_covers_question(
    user_message: str,
    settings: Any = None,
    inference_state: Any | None = None,
    snapshot: dict[str, Any] | None = None,
) -> bool:
    """True when the snapshot schema (or a provided snapshot) has the asked field.

    Does not call ``load_settings``, ``resolve_status``, or the secret store.
    ``settings`` / ``inference_state`` are accepted for call-site compatibility
    and unused unless a caller already built ``snapshot``.
    """
    del settings, inference_state
    text = (user_message or "").strip()
    if not text:
        return False
    if _ABSENT_ASK.search(text):
        return False
    available = snapshot if snapshot is not None else {key: True for key in SNAPSHOT_INCLUDE_KEYS}
    if not available:
        return False
    for pattern, keys in _FIELD_HINTS:
        if pattern.search(text) and any(key in available for key in keys):
            return True
    return False


def snapshot_blob(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return ""
    return json.dumps(snapshot, ensure_ascii=True, default=str)


def snapshot_numeric_tokens(snapshot: dict[str, Any] | None) -> set[str]:
    """Exact numeric field values, not digit substrings of the JSON blob."""
    tokens: set[str] = set()
    for value in (snapshot or {}).values():
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int):
            tokens.add(str(value))
        elif isinstance(value, float):
            tokens.add(str(value))
            if value.is_integer():
                tokens.add(str(int(value)))
    return tokens
