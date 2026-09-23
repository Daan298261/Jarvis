"""RFC-0138 custom presence: orb compositions, generation jobs, settings."""

from __future__ import annotations

from dataclasses import dataclass

import base64
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ..config import AppSettings, CustomPresencePreset, data_dir, load_settings, save_settings
from ..inference.manager import MANAGER
from ..media.store import _IMAGE_TYPES, caps_for_kind, detect_kind
from ..persona.named_persona import ROSTER
from ..providers.base import ChatMessage, ChatResult

logger = logging.getLogger(__name__)

ORB_CONSTRAINT = (
    "Return only JSON orb_composition version 1. Every generated object is composed of flowing orbs "
    "using kinds sphere, ring, arc, orbit, sparks, or shape_sample of an already registered presence shape. "
    "Do not return mesh, glTF, GLB, texture, material, HTML, or CSS."
)

_FORBIDDEN_TOKENS = frozenset(
    {"mesh", "gltf", "glb", "texture", "material", "html", "css", "silhouette"}
)
_ALLOWED_KINDS = frozenset({"sphere", "ring", "arc", "orbit", "sparks", "shape_sample"})
_ALLOWED_MOTIONS = frozenset({"pulse", "orbit", "breathe", "static"})
_TOP_KEYS = frozenset({"version", "orb_color", "accent_color", "framing", "layers"})
_FRAMING_KEYS = frozenset({"yaw", "position"})
_LAYER_KEYS = frozenset(
    {"kind", "count_scale", "radius", "y", "gold", "light", "flow", "size", "motion", "tilt", "shape_id"}
)
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PRESET_ID_RE = re.compile(r"^cui_[a-f0-9]{12,32}$")

_BUILTIN_SHAPE_IDS = frozenset(
    {
        "humanoid_bust",
        "energy_core",
        "hex_aegis",
        *(row.presence_shape_id for row in ROSTER),
    }
)
_PROTECTED_SHAPE_IDS = _BUILTIN_SHAPE_IDS

JobStatus = Literal["queued", "running", "succeeded", "failed", "rejected"]
SourceKind = Literal["text_prompt", "image", "text_and_image"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_presence_shape_id(
    suite_active: bool,
    active_preset_shape_id: str | None,
    persona_shape_id: str | None,
) -> str:
    if suite_active:
        return "hex_aegis"
    preset = (active_preset_shape_id or "").strip()
    if preset:
        return preset
    persona = (persona_shape_id or "").strip()
    if persona == "anzu" or not persona:
        return "stormbird"
    return persona


def preset_shape_id(preset_id: str) -> str:
    return f"custom_ui_{preset_id}"


def preview_shape_id(job_id: str) -> str:
    return f"custom_ui_preview_{job_id}"


def _contains_forbidden(value: str) -> bool:
    lower = value.lower()
    return any(token in lower for token in _FORBIDDEN_TOKENS)


def _scan_forbidden(obj: Any) -> list[str]:
    errors: list[str] = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            if _contains_forbidden(str(key)):
                errors.append(f"forbidden token in key: {key}")
            errors.extend(_scan_forbidden(val))
    elif isinstance(obj, list):
        for item in obj:
            errors.extend(_scan_forbidden(item))
    elif isinstance(obj, str):
        if _contains_forbidden(obj):
            errors.append(f"forbidden token in string: {obj[:80]}")
    return errors


def _validate_color(name: str, value: Any, errors: list[str]) -> None:
    if not isinstance(value, str) or not _COLOR_RE.match(value):
        errors.append(f"{name} must be #RRGGBB")


def _validate_range(name: str, value: Any, low: float, high: float, errors: list[str]) -> None:
    if not isinstance(value, (int, float)):
        errors.append(f"{name} must be a number")
        return
    if value < low or value > high:
        errors.append(f"{name} must be between {low} and {high}")


def validate_orb_composition(raw: Any) -> list[str]:
    """Return human-readable validation errors; empty means valid."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return ["orb_composition must be a JSON object"]
    errors.extend(_scan_forbidden(raw))
    extra_top = set(raw.keys()) - _TOP_KEYS
    if extra_top:
        errors.append(f"unknown top-level keys: {sorted(extra_top)}")
    if raw.get("version") != 1:
        errors.append("version must be 1")
    _validate_color("orb_color", raw.get("orb_color"), errors)
    _validate_color("accent_color", raw.get("accent_color"), errors)
    framing = raw.get("framing")
    if not isinstance(framing, dict):
        errors.append("framing must be an object")
    else:
        extra_f = set(framing.keys()) - _FRAMING_KEYS
        if extra_f:
            errors.append(f"unknown framing keys: {sorted(extra_f)}")
        if "yaw" in framing and not isinstance(framing["yaw"], (int, float)):
            errors.append("framing.yaw must be a number")
        pos = framing.get("position")
        if not isinstance(pos, list) or len(pos) != 3 or not all(isinstance(v, (int, float)) for v in pos):
            errors.append("framing.position must be [x, y, z] numbers")
    layers = raw.get("layers")
    if not isinstance(layers, list):
        errors.append("layers must be an array")
        return errors
    if not (1 <= len(layers) <= 24):
        errors.append("layers must contain 1..24 items")
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            errors.append(f"layers[{index}] must be an object")
            continue
        extra_l = set(layer.keys()) - _LAYER_KEYS
        if extra_l:
            errors.append(f"layers[{index}] unknown keys: {sorted(extra_l)}")
        kind = layer.get("kind")
        if kind not in _ALLOWED_KINDS:
            errors.append(f"layers[{index}].kind invalid: {kind!r}")
            continue
        if "count_scale" in layer:
            _validate_range(f"layers[{index}].count_scale", layer["count_scale"], 0.05, 4.0, errors)
        for field in ("gold",):
            if field in layer:
                _validate_range(f"layers[{index}].{field}", layer[field], 0.0, 1.0, errors)
        for field in ("light", "flow", "size", "radius", "y", "tilt"):
            if field in layer and not isinstance(layer[field], (int, float)):
                errors.append(f"layers[{index}].{field} must be a number")
        motion = layer.get("motion", "static")
        if motion not in _ALLOWED_MOTIONS:
            errors.append(f"layers[{index}].motion invalid: {motion!r}")
        if kind == "shape_sample":
            sid = layer.get("shape_id")
            if not isinstance(sid, str) or not sid.strip():
                errors.append(f"layers[{index}].shape_id required for shape_sample")
            elif sid.startswith("custom_ui_"):
                errors.append(f"layers[{index}].shape_id must not be custom_ui_*")
            elif sid not in _BUILTIN_SHAPE_IDS:
                errors.append(f"layers[{index}].shape_id unknown: {sid!r}")
    return errors


def compile_figure_description(orb_composition: dict[str, Any]) -> dict[str, Any]:
    """Validated composition payload the portal registers via buildFigure."""
    errors = validate_orb_composition(orb_composition)
    if errors:
        raise ValueError("; ".join(errors))
    return dict(orb_composition)


_REGISTERED_SHAPES: dict[str, dict[str, Any]] = {}


def register_custom_shape(shape_id: str, orb_composition: dict[str, Any]) -> None:
    if shape_id in _PROTECTED_SHAPE_IDS:
        raise ValueError(f"cannot register protected shape id: {shape_id}")
    compiled = compile_figure_description(orb_composition)
    _REGISTERED_SHAPES[shape_id] = compiled


def unregister_custom_shape(shape_id: str) -> None:
    _REGISTERED_SHAPES.pop(shape_id, None)


def get_registered_shape(shape_id: str) -> dict[str, Any] | None:
    return _REGISTERED_SHAPES.get(shape_id)


def reset_registered_shapes_for_tests() -> None:
    _REGISTERED_SHAPES.clear()


def _new_preset_id() -> str:
    return f"cui_{secrets.token_hex(12)}"


def normalize_custom_presence(settings: AppSettings) -> bool:
    """Sync default flags with default_preset_id. Returns True if settings mutated."""
    store = settings.custom_presence
    changed = False
    default_id = (store.default_preset_id or "").strip()
    for pid, preset in list(store.presets.items()):
        want = bool(default_id and pid == default_id)
        if preset.default != want:
            preset.default = want
            changed = True
        if not preset.shape_id:
            preset.shape_id = preset_shape_id(pid)
            changed = True
    if default_id and default_id not in store.presets:
        store.default_preset_id = ""
        changed = True
    active = (store.active_preset_id or "").strip()
    if active and active not in store.presets:
        store.active_preset_id = ""
        changed = True
    return changed


def _load() -> tuple[AppSettings, bool]:
    settings = load_settings()
    changed = normalize_custom_presence(settings)
    return settings, changed


def _persist(settings: AppSettings) -> None:
    normalize_custom_presence(settings)
    save_settings(settings)


def public_custom_presence_state(settings: AppSettings | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    normalize_custom_presence(settings)
    store = settings.custom_presence
    presets = []
    for pid in sorted(store.presets.keys()):
        row = store.presets[pid]
        presets.append(
            {
                "id": row.id,
                "name": row.name,
                "source": row.source,
                "source_image_ref": row.source_image_ref,
                "prompt_text": row.prompt_text,
                "orb_composition": row.orb_composition,
                "shape_id": row.shape_id or preset_shape_id(row.id),
                "default": row.default,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
    active_id = (store.active_preset_id or "").strip()
    active_shape = ""
    if active_id and active_id in store.presets:
        active_shape = store.presets[active_id].shape_id or preset_shape_id(active_id)
    return {
        "presets": presets,
        "active_preset_id": store.active_preset_id,
        "default_preset_id": store.default_preset_id,
        "active_shape_id": active_shape,
        "registered_shapes": sorted(_REGISTERED_SHAPES.keys()),
    }


def reapply_stored_custom_presence() -> dict[str, Any] | None:
    """After named persona reapply: load default preset shape when active is empty."""
    settings, changed = _load()
    store = settings.custom_presence
    default_id = (store.default_preset_id or "").strip()
    if default_id and default_id in store.presets:
        preset = store.presets[default_id]
        try:
            register_custom_shape(preset.shape_id or preset_shape_id(default_id), preset.orb_composition)
        except ValueError as exc:
            logger.info("custom_presence_register_failed preset=%s err=%s", default_id, exc)
        if not (store.active_preset_id or "").strip():
            store.active_preset_id = default_id
            changed = True
    if changed:
        _persist(settings)
    if not default_id:
        return None
    return public_custom_presence_state(settings)


def _parse_model_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    cleaned = (text or "").strip()
    if not cleaned:
        return None, "empty model response"
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, "model JSON must be an object"
    if parsed.get("rejected") is True:
        reason = str(parsed.get("reason") or "rejected by model")
        return None, f"rejected:{reason}"
    return parsed, None


@dataclass
class CustomPresenceJob:
    id: str
    status: JobStatus
    prompt_text: str
    source: SourceKind
    source_image_ref: str
    orb_composition: dict[str, Any] | None
    preview_shape_id: str
    error: dict[str, str] | None
    created_at: str
    updated_at: str


_JOBS: dict[str, CustomPresenceJob] = {}


def get_job(job_id: str) -> CustomPresenceJob | None:
    return _JOBS.get(job_id)


def _job_dict(job: CustomPresenceJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "prompt_text": job.prompt_text,
        "source": job.source,
        "source_image_ref": job.source_image_ref,
        "orb_composition": job.orb_composition,
        "preview_shape_id": job.preview_shape_id if job.status == "succeeded" else "",
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def custom_ui_uploads_dir() -> Path:
    path = data_dir() / "custom_ui_uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_upload_bytes(filename: str, content_type: str, data: bytes) -> str:
    kind = detect_kind(content_type, filename)
    if kind != "image":
        raise ValueError("invalid_input")
    cap = caps_for_kind("image")
    if len(data) > cap:
        raise ValueError("payload_too_large")
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct and ct not in _IMAGE_TYPES:
        raise ValueError("invalid_input")
    ext = Path(filename or "upload.bin").suffix.lower()
    if not ext or ext == ".bin":
        ext = ".jpg" if "jpeg" in ct or "jpg" in ct else ".png"
    name = f"{uuid.uuid4().hex}{ext}"
    rel = f"custom_ui_uploads/{name}"
    dest = data_dir() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return rel


def _image_message(image_path: Path, prompt: str) -> ChatMessage:
    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    suffix = image_path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    if suffix == ".webp":
        mime = "image/webp"
    return ChatMessage(
        role="user",
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ],
    )


async def _call_model(
    *,
    prompt_text: str,
    image_ref: str,
    validation_errors: str | None,
) -> ChatResult:
    if not MANAGER.state.loaded or not MANAGER.provider:
        raise RuntimeError("model_unavailable")
    owner = (prompt_text or "").strip()
    user_text = f"{ORB_CONSTRAINT}\n\n{owner}".strip()
    if validation_errors:
        user_text = f"{user_text}\n\nPrevious JSON failed validation:\n{validation_errors}"
    messages: list[ChatMessage]
    if image_ref:
        if not MANAGER.state.vision_loaded:
            raise RuntimeError("vision_unavailable")
        image_path = data_dir() / image_ref
        messages = [_image_message(image_path, user_text)]
    else:
        messages = [ChatMessage(role="user", content=user_text)]
    settings = load_settings()
    return await MANAGER.chat(messages, settings=settings, max_tokens=4096)


async def _generate_composition(
    *,
    prompt_text: str,
    image_ref: str,
) -> tuple[dict[str, Any] | None, JobStatus, dict[str, str] | None]:
    validation_feedback: str | None = None
    for attempt in range(2):
        try:
            result = await _call_model(
                prompt_text=prompt_text,
                image_ref=image_ref,
                validation_errors=validation_feedback,
            )
        except RuntimeError as exc:
            code = str(exc)
            if code in {"model_unavailable", "vision_unavailable"}:
                return None, "failed", {"code": code, "message": code}
            return None, "failed", {"code": "model_unavailable", "message": str(exc)}
        except Exception as exc:
            return None, "failed", {"code": "model_unavailable", "message": str(exc)[:500]}
        parsed, err = _parse_model_json(result.content or "")
        if err and err.startswith("rejected:"):
            return None, "rejected", {"code": "constraint_rejected", "message": err.split(":", 1)[1]}
        if parsed is None:
            validation_feedback = err or "invalid JSON"
            if attempt == 1:
                return None, "rejected", {"code": "constraint_rejected", "message": validation_feedback}
            continue
        errors = validate_orb_composition(parsed)
        if errors:
            validation_feedback = "; ".join(errors)
            if attempt == 1:
                return None, "rejected", {"code": "constraint_rejected", "message": validation_feedback}
            continue
        return parsed, "succeeded", None
    return None, "rejected", {"code": "constraint_rejected", "message": validation_feedback or "validation failed"}


async def run_custom_presence_job(
    *,
    prompt_text: str,
    image_bytes: bytes | None,
    image_filename: str,
    image_content_type: str,
) -> CustomPresenceJob:
    text = (prompt_text or "").strip()
    has_image = bool(image_bytes)
    if not text and not has_image:
        raise ValueError("invalid_input")
    job_id = uuid.uuid4().hex
    now = _utc_now()
    source: SourceKind
    image_ref = ""
    if has_image and text:
        source = "text_and_image"
    elif has_image:
        source = "image"
    else:
        source = "text_prompt"
    job = CustomPresenceJob(
        id=job_id,
        status="queued",
        prompt_text=text,
        source=source,
        source_image_ref="",
        orb_composition=None,
        preview_shape_id="",
        error=None,
        created_at=now,
        updated_at=now,
    )
    _JOBS[job_id] = job
    job.status = "running"
    job.updated_at = _utc_now()
    if has_image:
        try:
            image_ref = store_upload_bytes(image_filename, image_content_type, image_bytes or b"")
        except ValueError as exc:
            code = str(exc)
            if code == "payload_too_large":
                raise
            job.status = "failed"
            job.error = {"code": "invalid_input", "message": code}
            job.updated_at = _utc_now()
            return job
        job.source_image_ref = image_ref
    composition, status, error = await _generate_composition(prompt_text=text, image_ref=image_ref)
    job.status = status
    job.error = error
    job.updated_at = _utc_now()
    if status == "succeeded" and composition is not None:
        job.orb_composition = composition
        sid = preview_shape_id(job_id)
        register_custom_shape(sid, composition)
        job.preview_shape_id = sid
    return job


def save_preset_from_job(
    job_id: str,
    name: str,
    *,
    set_default: bool,
) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None or job.status != "succeeded" or not job.orb_composition:
        raise LookupError("job not ready")
    display = (name or "").strip()
    if not display:
        display = (job.prompt_text or "")[:48].strip() or "Custom look"
    settings, _ = _load()
    store = settings.custom_presence
    pid = _new_preset_id()
    shape = preset_shape_id(pid)
    now = _utc_now()
    preset = CustomPresencePreset(
        id=pid,
        name=display[:80],
        source=job.source,
        source_image_ref=job.source_image_ref,
        prompt_text=job.prompt_text,
        orb_composition=job.orb_composition,
        shape_id=shape,
        default=set_default,
        created_at=now,
        updated_at=now,
    )
    store.presets[pid] = preset
    store.active_preset_id = pid
    if set_default:
        store.default_preset_id = pid
    normalize_custom_presence(settings)
    register_custom_shape(shape, job.orb_composition)
    unregister_custom_shape(job.preview_shape_id)
    _persist(settings)
    return public_custom_presence_state(settings)


def set_default_preset(preset_id: str) -> dict[str, Any]:
    settings, _ = _load()
    pid = (preset_id or "").strip()
    if pid not in settings.custom_presence.presets:
        raise LookupError("unknown preset")
    settings.custom_presence.default_preset_id = pid
    settings.custom_presence.active_preset_id = pid
    normalize_custom_presence(settings)
    preset = settings.custom_presence.presets[pid]
    register_custom_shape(preset.shape_id, preset.orb_composition)
    _persist(settings)
    return public_custom_presence_state(settings)


def delete_preset(preset_id: str) -> dict[str, Any]:
    settings, _ = _load()
    pid = (preset_id or "").strip()
    if pid not in settings.custom_presence.presets:
        raise LookupError("unknown preset")
    preset = settings.custom_presence.presets.pop(pid)
    unregister_custom_shape(preset.shape_id)
    if settings.custom_presence.active_preset_id == pid:
        settings.custom_presence.active_preset_id = ""
    if settings.custom_presence.default_preset_id == pid:
        settings.custom_presence.default_preset_id = ""
    normalize_custom_presence(settings)
    _persist(settings)
    return public_custom_presence_state(settings)


def clear_active_preset() -> dict[str, Any]:
    settings, _ = _load()
    settings.custom_presence.active_preset_id = ""
    _persist(settings)
    return public_custom_presence_state(settings)


def discard_preview(job_id: str) -> None:
    job = _JOBS.get(job_id)
    if job and job.preview_shape_id:
        unregister_custom_shape(job.preview_shape_id)


def valid_preset_id(preset_id: str) -> bool:
    return bool(_PRESET_ID_RE.match((preset_id or "").strip()))
