from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import load_settings
from ..hardware import detect_hardware
from .backends import suggested_port
from .runtime_profiles import (
    PRIVACY_LOCAL_ONLY,
    RuntimeProfile,
    create_runtime_profile,
    get_runtime_profile,
    list_runtime_profiles,
    save_runtime_profile,
    update_runtime_profile,
)

_lock = threading.RLock()
USER_STATE_FILE = "user_state.json"
AXIS_KEYS = (
    "coding",
    "writing",
    "reasoning",
    "speed_cost",
    "vram_fit",
    "instruction",
    "uncensored",
)
QUANT_RE = re.compile(
    r"(IQ\d+(?:_XS)?|Q\d+(?:_K(?:_[SM])?)?|FP\d+)",
    re.IGNORECASE,
)

def _user_home() -> Path:
    if os.name == "nt":
        profile = (os.environ.get("USERPROFILE") or "").strip()
        if profile:
            return Path(profile)
    return Path.home()


def _local_catalog_fields(*, kind: str) -> dict[str, Any]:
    return {
        "is_local": True,
        "privacy_class": PRIVACY_LOCAL_ONLY,
        "catalog_kind": kind,
    }


@dataclass
class DiscoveredGguf:
    filename: str
    path: str
    weight_gb: float
    quantization: str


def catalog_data_path() -> Path:
    return Path(__file__).resolve().parent / "lmstudio_graded_profiles.json"


def catalog_store_root() -> Path:
    from ..config import data_dir

    path = data_dir() / "lmstudio-catalog"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _user_state_path() -> Path:
    return catalog_store_root() / USER_STATE_FILE


def default_models_root() -> Path:
    override = (os.environ.get("JARVIS_LMSTUDIO_MODELS_ROOT") or "").strip()
    if override:
        return Path(override)
    return _user_home() / ".lmstudio" / "models"


def resolve_models_root() -> Path:
    settings = load_settings()
    custom = (settings.inference.lmstudio_models_root or "").strip()
    if custom:
        return Path(custom)
    return default_models_root()


def probe_vram_gb() -> float | None:
    info = detect_hardware(force=True)
    if info.vram_total_mib is None:
        return None
    return round(info.vram_total_mib / 1024, 1)


def parse_quantization(filename: str) -> str:
    matches = QUANT_RE.findall(filename)
    if not matches:
        return ""
    return matches[-1].upper()


def file_weight_gb(path: Path) -> float:
    try:
        return round(path.stat().st_size / (1024**3), 1)
    except OSError:
        return 0.0


def discover_ggufs(models_root: Path | None = None) -> list[DiscoveredGguf]:
    root = models_root or resolve_models_root()
    if not root.exists():
        return []
    found: list[DiscoveredGguf] = []
    for path in sorted(root.rglob("*.gguf")):
        name_lower = path.name.lower()
        if "mmproj" in name_lower:
            continue
        found.append(
            DiscoveredGguf(
                filename=path.name,
                path=str(path),
                weight_gb=file_weight_gb(path),
                quantization=parse_quantization(path.name),
            )
        )
    return found


def _load_seed_catalog() -> dict[str, Any]:
    path = catalog_data_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"catalog_version": "unknown", "profiles": []}
    if not isinstance(raw, dict):
        return {"catalog_version": "unknown", "profiles": []}
    return raw


def _empty_user_state() -> dict[str, Any]:
    return {"pins": {}, "favorites": {}, "overrides": {}, "runtime_bindings": {}}


def _load_user_state_unlocked() -> dict[str, Any]:
    path = _user_state_path()
    if not path.exists():
        return _empty_user_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_user_state()
    if not isinstance(raw, dict):
        return _empty_user_state()
    state = _empty_user_state()
    for key in state:
        value = raw.get(key)
        if isinstance(value, dict):
            state[key] = value
    return state


def _save_user_state_unlocked(state: dict[str, Any]) -> None:
    _user_state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


def _match_profile(seed: dict[str, Any], discovered: list[DiscoveredGguf]) -> DiscoveredGguf | None:
    needles = [str(item).lower() for item in (seed.get("match_substrings") or [])]
    if not needles:
        return None
    best: DiscoveredGguf | None = None
    best_score = -1
    for item in discovered:
        hay = f"{item.filename} {item.path}".lower()
        score = sum(1 for needle in needles if needle in hay)
        if score > best_score:
            best_score = score
            best = item
    if best_score <= 0:
        return None
    return best


def vram_state_for_weight(weight_gb: float) -> str:
    if weight_gb > 16:
        return "hidden"
    if weight_gb >= 12:
        return "warn"
    return "ok"


def _apply_overrides(seed: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(seed)
    if "overall" in overrides and overrides["overall"] is not None:
        merged["overall"] = float(overrides["overall"])
    axis_overrides = overrides.get("axes")
    if isinstance(axis_overrides, dict):
        axes = dict(merged.get("axes") or {})
        for key in AXIS_KEYS:
            if key in axis_overrides and axis_overrides[key] is not None:
                axes[key] = int(axis_overrides[key])
        merged["axes"] = axes
    return merged


def _runtime_profile_id_for_catalog(state: dict[str, Any], profile_id: str) -> str | None:
    binding = state.get("runtime_bindings", {}).get(profile_id)
    if isinstance(binding, str) and binding.strip():
        return binding.strip()
    return None


def _build_graded_profile(
    seed: dict[str, Any],
    *,
    state: dict[str, Any],
    discovered_match: DiscoveredGguf | None,
) -> dict[str, Any]:
    profile_id = str(seed.get("id") or "")
    overrides = state.get("overrides", {}).get(profile_id, {})
    merged = _apply_overrides(seed, overrides if isinstance(overrides, dict) else {})
    weight_gb = (
        discovered_match.weight_gb
        if discovered_match is not None
        else float(merged.get("weight_gb") or 0.0)
    )
    quantization = (
        discovered_match.quantization
        if discovered_match is not None and discovered_match.quantization
        else str(merged.get("quantization") or "")
    )
    path = discovered_match.path if discovered_match is not None else ""
    axes = {key: int((merged.get("axes") or {}).get(key, 0)) for key in AXIS_KEYS}
    pinned = bool(state.get("pins", {}).get(profile_id))
    favorite = bool(state.get("favorites", {}).get(profile_id))
    runtime_profile_id = _runtime_profile_id_for_catalog(state, profile_id)
    if runtime_profile_id and get_runtime_profile(runtime_profile_id) is None:
        runtime_profile_id = None
    result: dict[str, Any] = {
        "id": profile_id,
        "display_name": str(merged.get("display_name") or profile_id),
        "overall": float(merged.get("overall") or 0.0),
        "axes": axes,
        "strength": str(merged.get("strength") or ""),
        "weakness": str(merged.get("weakness") or ""),
        "weight_gb": weight_gb,
        "quantization": quantization,
        "path": path,
        "pinned": pinned,
        "favorite": favorite,
        "runtime_profile_id": runtime_profile_id,
        "vram_state": vram_state_for_weight(weight_gb),
        "matched": discovered_match is not None,
    }
    source_notes = merged.get("source_notes")
    if source_notes:
        result["source_notes"] = str(source_notes)
    result.update(_local_catalog_fields(kind="graded"))
    return result


def sort_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        boost = 1 if item.get("pinned") or item.get("favorite") else 0
        return (-boost, -float(item.get("overall") or 0.0), str(item.get("display_name") or ""))

    return sorted(profiles, key=sort_key)


def build_catalog(*, show_hidden: bool = False, models_root: Path | None = None) -> dict[str, Any]:
    seed = _load_seed_catalog()
    root = models_root or resolve_models_root()
    discovered = discover_ggufs(root)
    with _lock:
        state = _load_user_state_unlocked()
        profiles: list[dict[str, Any]] = []
        matched_paths: set[str] = set()
        for row in seed.get("profiles") or []:
            if not isinstance(row, dict):
                continue
            match = _match_profile(row, discovered)
            if match is not None:
                matched_paths.add(match.path)
            profile = _build_graded_profile(row, state=state, discovered_match=match)
            if not show_hidden and profile["vram_state"] == "hidden":
                continue
            profiles.append(profile)
        ungraded = [
            {
                "filename": item.filename,
                "path": item.path,
                "weight_gb": item.weight_gb,
                "quantization": item.quantization,
                **_local_catalog_fields(kind="ungraded"),
            }
            for item in discovered
            if item.path not in matched_paths
        ]
    return {
        "catalog_version": str(seed.get("catalog_version") or "unknown"),
        "models_root": str(root),
        "vram_gb": probe_vram_gb(),
        "profiles": sort_profiles(profiles),
        "ungraded": ungraded,
    }


def get_graded_profile(profile_id: str, *, models_root: Path | None = None) -> dict[str, Any] | None:
    key = (profile_id or "").strip()
    if not key:
        return None
    catalog = build_catalog(show_hidden=True, models_root=models_root)
    for profile in catalog["profiles"]:
        if profile["id"] == key:
            return profile
    return None


def set_profile_pin(profile_id: str, pinned: bool) -> None:
    key = (profile_id or "").strip()
    if not key:
        raise ValueError("profile_id is required")
    with _lock:
        state = _load_user_state_unlocked()
        pins = dict(state.get("pins") or {})
        if pinned:
            pins[key] = True
        else:
            pins.pop(key, None)
        state["pins"] = pins
        _save_user_state_unlocked(state)


def set_profile_override(
    profile_id: str,
    *,
    overall: float | None = None,
    axes: dict[str, int] | None = None,
) -> dict[str, Any]:
    key = (profile_id or "").strip()
    if not key:
        raise ValueError("profile_id is required")
    with _lock:
        state = _load_user_state_unlocked()
        overrides = dict(state.get("overrides") or {})
        current = dict(overrides.get(key) or {})
        if overall is not None:
            current["overall"] = overall
        if axes:
            axis_map = dict(current.get("axes") or {})
            for axis_key, value in axes.items():
                if axis_key in AXIS_KEYS and value is not None:
                    axis_map[axis_key] = int(value)
            current["axes"] = axis_map
        overrides[key] = current
        state["overrides"] = overrides
        _save_user_state_unlocked(state)
    profile = get_graded_profile(key, models_root=None)
    if profile is None:
        raise KeyError(f"catalog profile not found: {key}")
    return profile


def _lmstudio_endpoint() -> str:
    settings = load_settings()
    port = settings.inference.port
    if (settings.inference.backend or "").strip().lower() in {"lmstudio", "lm-studio", "lm_studio"}:
        port = settings.inference.port
    else:
        port = suggested_port("lmstudio", settings.inference.port)
    return f"{settings.inference.host}:{port}"


def _model_stem_from_path(path: str, fallback: str) -> str:
    if path:
        return Path(path).stem
    return fallback


def select_catalog_profile(profile_id: str, *, models_root: Path | None = None) -> RuntimeProfile:
    key = (profile_id or "").strip()
    if not key:
        raise ValueError("profile_id is required")
    seed = _load_seed_catalog()
    seed_row = next(
        (row for row in (seed.get("profiles") or []) if isinstance(row, dict) and row.get("id") == key),
        None,
    )
    if seed_row is None:
        raise KeyError(f"catalog profile not found: {key}")
    graded = get_graded_profile(key, models_root=models_root)
    if graded is None:
        raise KeyError(f"catalog profile not found: {key}")

    endpoint = _lmstudio_endpoint()
    model = _model_stem_from_path(str(graded.get("path") or ""), key)
    specialization = [str(tag) for tag in (seed_row.get("specialization_tags") or [])]
    capability_tags = ["llm_inference", "text", "graded-catalog"]

    with _lock:
        state = _load_user_state_unlocked()
        binding_id = _runtime_profile_id_for_catalog(state, key)
        existing = get_runtime_profile(binding_id) if binding_id else None
        if existing is not None:
            profile = update_runtime_profile(
                existing.id,
                label=str(graded["display_name"]),
                model=model,
                provider="lmstudio",
                endpoint=endpoint,
                quantization=str(graded.get("quantization") or ""),
                privacy_class=PRIVACY_LOCAL_ONLY,
                is_local=True,
                capability_tags=capability_tags,
                specialization_tags=specialization,
                description=f"LM Studio graded catalog profile ({key})",
            )
        else:
            name = f"lm-{key}"
            taken = {item.name for item in list_runtime_profiles()}
            if name in taken:
                profile = next(item for item in list_runtime_profiles() if item.name == name)
                profile = update_runtime_profile(
                    profile.id,
                    label=str(graded["display_name"]),
                    model=model,
                    provider="lmstudio",
                    endpoint=endpoint,
                    quantization=str(graded.get("quantization") or ""),
                    privacy_class=PRIVACY_LOCAL_ONLY,
                    is_local=True,
                    capability_tags=capability_tags,
                    specialization_tags=specialization,
                    description=f"LM Studio graded catalog profile ({key})",
                )
            else:
                profile = create_runtime_profile(
                    name=name,
                    label=str(graded["display_name"]),
                    model=model,
                    provider="lmstudio",
                    endpoint=endpoint,
                    context_limit=32768,
                    quantization=str(graded.get("quantization") or ""),
                    privacy_class=PRIVACY_LOCAL_ONLY,
                    cost_ceiling_usd=0.0,
                    capability_tags=capability_tags,
                    specialization_tags=specialization,
                    is_local=True,
                    description=f"LM Studio graded catalog profile ({key})",
                )
        bindings = dict(state.get("runtime_bindings") or {})
        bindings[key] = profile.id
        state["runtime_bindings"] = bindings
        _save_user_state_unlocked(state)
    return profile


def discovery_payload(*, models_root: Path | None = None) -> dict[str, Any]:
    root = models_root or resolve_models_root()
    items = discover_ggufs(root)
    return {
        "models_root": str(root),
        "count": len(items),
        "models": [
            {
                "filename": item.filename,
                "path": item.path,
                "weight_gb": item.weight_gb,
                "quantization": item.quantization,
                **_local_catalog_fields(kind="discovered"),
            }
            for item in items
        ],
    }
