from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import data_dir
from .profiles import PROFILES, ModelProfile

_lock = threading.RLock()
RUNTIME_REGISTRY_NAME = "registry.json"

PRIVACY_LOCAL_ONLY = "local-only"
PRIVACY_TRUSTED_REMOTE = "trusted-remote"
PRIVACY_PUBLIC_REMOTE = "public-remote"

PRIVACY_ORDER = {
    PRIVACY_LOCAL_ONLY: 0,
    PRIVACY_TRUSTED_REMOTE: 1,
    PRIVACY_PUBLIC_REMOTE: 2,
}


@dataclass
class RuntimeProfile:
    """Named inference/runtime profile for policy-aware routing (RFC-0003)."""

    id: str
    name: str
    label: str
    model: str
    provider: str
    endpoint: str
    context_limit: int
    quantization: str
    privacy_class: str
    cost_ceiling_usd: float | None
    capability_tags: tuple[str, ...] = ()
    model_profile: str | None = None
    specialization_tags: tuple[str, ...] = ()
    is_local: bool = True
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RuntimeProfile:
        return cls(
            id=str(raw.get("id") or ""),
            name=str(raw.get("name") or ""),
            label=str(raw.get("label") or raw.get("name") or ""),
            model=str(raw.get("model") or ""),
            provider=str(raw.get("provider") or "local-llama"),
            endpoint=str(raw.get("endpoint") or "127.0.0.1:8088"),
            context_limit=int(raw.get("context_limit") or 16384),
            quantization=str(raw.get("quantization") or ""),
            privacy_class=str(raw.get("privacy_class") or PRIVACY_LOCAL_ONLY),
            cost_ceiling_usd=(
                float(raw["cost_ceiling_usd"])
                if raw.get("cost_ceiling_usd") is not None
                else None
            ),
            capability_tags=tuple(str(tag) for tag in (raw.get("capability_tags") or [])),
            model_profile=raw.get("model_profile"),
            specialization_tags=tuple(str(tag) for tag in (raw.get("specialization_tags") or [])),
            is_local=bool(raw.get("is_local", True)),
            description=str(raw.get("description") or ""),
        )


def runtime_profiles_root() -> Path:
    path = data_dir() / "runtime-profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runtime_registry_path() -> Path:
    return runtime_profiles_root() / RUNTIME_REGISTRY_NAME


def _runtime_profile_from_model(profile: ModelProfile, *, endpoint: str = "127.0.0.1:8088") -> RuntimeProfile:
    tags: list[str] = ["llm_inference", "text"]
    if profile.vision:
        tags.append("vision")
    if profile.family == "27b":
        tags.append("high-quality")
    specialization: list[str] = []
    if profile.thinking_mode == "on":
        specialization.append("reasoning")
    if profile.name == "fast":
        specialization.append("low-latency")
    return RuntimeProfile(
        id=f"builtin-{profile.name}",
        name=profile.name,
        label=profile.label,
        model=profile.alias,
        provider="local-llama",
        endpoint=endpoint,
        context_limit=profile.context_size,
        quantization=profile.quant,
        privacy_class=PRIVACY_LOCAL_ONLY,
        cost_ceiling_usd=0.0,
        capability_tags=tuple(tags),
        model_profile=profile.name,
        specialization_tags=tuple(specialization),
        is_local=True,
        description=profile.description,
    )


def default_runtime_profiles(*, endpoint: str = "127.0.0.1:8088") -> list[RuntimeProfile]:
    return [_runtime_profile_from_model(profile, endpoint=endpoint) for profile in PROFILES.values()]


def _load_runtime_registry_unlocked() -> list[RuntimeProfile]:
    path = _runtime_registry_path()
    if not path.exists():
        return default_runtime_profiles()
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_runtime_profiles()
    if not isinstance(rows, list) or not rows:
        return default_runtime_profiles()
    return [RuntimeProfile.from_dict(row) for row in rows if isinstance(row, dict)]


def _save_runtime_registry_unlocked(items: list[RuntimeProfile]) -> None:
    _runtime_registry_path().write_text(
        json.dumps([item.as_dict() for item in items], indent=2),
        encoding="utf-8",
    )


def list_runtime_profiles() -> list[RuntimeProfile]:
    with _lock:
        return _load_runtime_registry_unlocked()


def get_runtime_profile(profile_id: str) -> RuntimeProfile | None:
    key = (profile_id or "").strip()
    if not key:
        return None
    with _lock:
        for profile in _load_runtime_registry_unlocked():
            if profile.id == key or profile.name == key:
                return profile
    return None


def save_runtime_profile(profile: RuntimeProfile) -> RuntimeProfile:
    with _lock:
        items = _load_runtime_registry_unlocked()
        updated: list[RuntimeProfile] = []
        replaced = False
        for item in items:
            if item.id == profile.id:
                updated.append(profile)
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(profile)
        _save_runtime_registry_unlocked(updated)
        return profile


def create_runtime_profile(
    *,
    name: str,
    label: str | None = None,
    model: str,
    provider: str = "openai-compat",
    endpoint: str,
    context_limit: int = 16384,
    quantization: str = "",
    privacy_class: str = PRIVACY_TRUSTED_REMOTE,
    cost_ceiling_usd: float | None = None,
    capability_tags: list[str] | None = None,
    model_profile: str | None = None,
    specialization_tags: list[str] | None = None,
    is_local: bool = False,
    description: str = "",
) -> RuntimeProfile:
    normalized = (name or "").strip().lower().replace(" ", "-")
    if not normalized:
        raise ValueError("name is required")
    with _lock:
        items = _load_runtime_registry_unlocked()
        if any(item.name == normalized for item in items):
            raise ValueError(f"runtime profile already exists: {normalized}")
        profile = RuntimeProfile(
            id=str(uuid.uuid4()),
            name=normalized,
            label=label or normalized,
            model=model,
            provider=provider,
            endpoint=endpoint,
            context_limit=int(context_limit),
            quantization=quantization,
            privacy_class=privacy_class,
            cost_ceiling_usd=cost_ceiling_usd,
            capability_tags=tuple(capability_tags or []),
            model_profile=model_profile,
            specialization_tags=tuple(specialization_tags or []),
            is_local=is_local,
            description=description,
        )
        items.append(profile)
        _save_runtime_registry_unlocked(items)
        return profile


def update_runtime_profile(profile_id: str, **fields: Any) -> RuntimeProfile:
    with _lock:
        items = _load_runtime_registry_unlocked()
        for index, item in enumerate(items):
            if item.id != profile_id and item.name != profile_id:
                continue
            data = item.as_dict()
            for key, value in fields.items():
                if value is None:
                    continue
                if key in {"capability_tags", "specialization_tags"} and isinstance(value, list):
                    data[key] = value
                elif key in data:
                    data[key] = value
            updated = RuntimeProfile.from_dict(data)
            items[index] = updated
            _save_runtime_registry_unlocked(items)
            return updated
    raise KeyError(f"runtime profile not found: {profile_id}")


def delete_runtime_profile(profile_id: str) -> None:
    with _lock:
        items = _load_runtime_registry_unlocked()
        remaining = [item for item in items if item.id != profile_id and item.name != profile_id]
        if len(remaining) == len(items):
            raise KeyError(f"runtime profile not found: {profile_id}")
        _save_runtime_registry_unlocked(remaining)


def reset_runtime_profiles(*, endpoint: str = "127.0.0.1:8088") -> list[RuntimeProfile]:
    with _lock:
        items = default_runtime_profiles(endpoint=endpoint)
        _save_runtime_registry_unlocked(items)
        return items
