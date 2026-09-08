from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..config import data_dir, load_settings
from ..hardware import detect_hardware
from .backends import DEFAULT_PORTS, LMSTUDIO_ALIASES, default_lmstudio_models_root
from .runtime_profiles import (
    PRIVACY_LOCAL_ONLY,
    RuntimeProfile,
    create_runtime_profile,
    get_runtime_profile,
    save_runtime_profile,
    update_runtime_profile,
)

_lock = threading.RLock()
USER_STATE_FILENAME = "lmstudio_catalog_user.json"
CATALOG_FILENAME = "lmstudio_graded_profiles.json"

AXIS_KEYS = (
    "coding",
    "writing",
    "reasoning",
    "speed_cost",
    "vram_fit",
    "instruction",
    "uncensored",
)

VramState = Literal["ok", "warn", "hidden"]

QUANT_RE = re.compile(
    r"\b(IQ\d(?:_[A-Z0-9]+)?|Q\d(?:_[A-Z0-9]+)?)\b",
    re.IGNORECASE,
)


@dataclass
class DiscoveredGguf:
    filename: str
    path: str
    weight_gb: float
    quantization: str


@dataclass
class CatalogSeedProfile:
    id: str
    display_name: str
    match_hint: str
    overall: float
    axes: dict[str, float]
    strength: str
    weakness: str
    source_notes: str
    specialization_tags: tuple[str, ...]


def _catalog_seed_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / CATALOG_FILENAME


def _user_state_path() -> Path:
    return data_dir() / USER_STATE_FILENAME


def _default_user_state() -> dict[str, Any]:
    return {
        "pins": {},
        "favorites": {},
        "overrides": {},
        "runtime_bindings": {},
    }


def _load_user_state_unlocked() -> dict[str, Any]:
    path = _user_state_path()
    if not path.exists():
        return _default_user_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_user_state()
    if not isinstance(raw, dict):
        return _default_user_state()
    state = _default_user_state()
    for key in state:
        value = raw.get(key)
        if isinstance(value, dict):
            state[key] = value
    return state


def _save_user_state_unlocked(state: dict[str, Any]) -> None:
    path = _user_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def models_root() -> Path:
    return default_lmstudio_models_root()


def load_catalog_seed() -> tuple[str, list[CatalogSeedProfile]]:
    path = _catalog_seed_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = str(raw.get("catalog_version") or "unknown")
    profiles: list[CatalogSeedProfile] = []
    for row in raw.get("profiles") or []:
        if not isinstance(row, dict):
            continue
        axes = {key: float((row.get("axes") or {}).get(key, 0)) for key in AXIS_KEYS}
        profiles.append(
            CatalogSeedProfile(
                id=str(row.get("id") or ""),
                display_name=str(row.get("display_name") or ""),
                match_hint=str(row.get("match_hint") or ""),
                overall=float(row.get("overall") or 0),
                axes=axes,
                strength=str(row.get("strength") or ""),
                weakness=str(row.get("weakness") or ""),
                source_notes=str(row.get("source_notes") or ""),
                specialization_tags=tuple(str(tag) for tag in (row.get("specialization_tags") or [])),
            )
        )
    return version, profiles


def parse_quantization(filename: str) -> str:
    match = QUANT_RE.search(filename)
    if not match:
        return ""
    return match.group(1).upper()


def estimate_weight_gb(path: Path) -> float:
    try:
        size = path.stat().st_size
    except OSError:
        return 0.0
    return round(size / (1024**3), 1)


def _normalize_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if token}


def match_score(hint: str, filename: str) -> float:
    hint_tokens = _normalize_tokens(hint)
    file_tokens = _normalize_tokens(Path(filename).stem)
    if not hint_tokens or not file_tokens:
        return 0.0
    overlap = hint_tokens & file_tokens
    if len(overlap) < 2:
        return 0.0
    return len(overlap) / len(hint_tokens)


def fuzzy_match_hint(hint: str, filename: str) -> bool:
    return match_score(hint, filename) >= 0.6


def _best_discovered_match(
    hint: str,
    discovered: list[DiscoveredGguf],
    used_paths: set[str],
) -> DiscoveredGguf | None:
    best: DiscoveredGguf | None = None
    best_score = 0.0
    for gguf in discovered:
        if gguf.path in used_paths:
            continue
        score = match_score(hint, gguf.filename)
        if score > best_score:
            best_score = score
            best = gguf
    if best is None or best_score < 0.6:
        return None
    return best


def discover_ggufs(root: Path | None = None) -> list[DiscoveredGguf]:
    models_path = root or models_root()
    if not models_path.exists():
        return []
    discovered: list[DiscoveredGguf] = []
    for path in sorted(models_path.rglob("*.gguf")):
        name_lower = path.name.lower()
        if "mmproj" in name_lower:
            continue
        discovered.append(
            DiscoveredGguf(
                filename=path.name,
                path=str(path),
                weight_gb=estimate_weight_gb(path),
                quantization=parse_quantization(path.name),
            )
        )
    return discovered


def vram_state_for_weight(weight_gb: float) -> VramState:
    if weight_gb > 16:
        return "hidden"
    if weight_gb > 12:
        return "warn"
    return "ok"


def node_vram_gb() -> float | None:
    hardware = detect_hardware()
    if hardware.vram_total_mib is None:
        return None
    return round(hardware.vram_total_mib / 1024, 1)


def _apply_overrides(profile_id: str, overall: float, axes: dict[str, float]) -> tuple[float, dict[str, float]]:
    with _lock:
        state = _load_user_state_unlocked()
        override = state.get("overrides", {}).get(profile_id) or {}
    if isinstance(override, dict):
        if override.get("overall") is not None:
            overall = float(override["overall"])
        axis_patch = override.get("axes")
        if isinstance(axis_patch, dict):
            merged = dict(axes)
            for key in AXIS_KEYS:
                if axis_patch.get(key) is not None:
                    merged[key] = float(axis_patch[key])
            axes = merged
    return overall, axes


def _profile_user_flags(profile_id: str) -> tuple[bool, bool, str | None]:
    with _lock:
        state = _load_user_state_unlocked()
    pinned = bool(state.get("pins", {}).get(profile_id))
    favorite = bool(state.get("favorites", {}).get(profile_id))
    runtime_profile_id = state.get("runtime_bindings", {}).get(profile_id)
    if runtime_profile_id is not None:
        runtime_profile_id = str(runtime_profile_id)
    return pinned, favorite, runtime_profile_id


def build_graded_profile(
    seed: CatalogSeedProfile,
    gguf: DiscoveredGguf | None,
) -> dict[str, Any]:
    overall, axes = _apply_overrides(seed.id, seed.overall, dict(seed.axes))
    pinned, favorite, runtime_profile_id = _profile_user_flags(seed.id)
    weight_gb = gguf.weight_gb if gguf else 0.0
    quantization = gguf.quantization if gguf else ""
    path = gguf.path if gguf else ""
    matched = gguf is not None
    return {
        "id": seed.id,
        "display_name": seed.display_name,
        "overall": overall,
        "axes": axes,
        "strength": seed.strength,
        "weakness": seed.weakness,
        "weight_gb": weight_gb,
        "quantization": quantization,
        "path": path,
        "pinned": pinned,
        "favorite": favorite,
        "runtime_profile_id": runtime_profile_id,
        "vram_state": vram_state_for_weight(weight_gb) if matched else "ok",
        "source_notes": seed.source_notes,
        "matched": matched,
    }


def sort_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
        boost = 1 if item.get("pinned") or item.get("favorite") else 0
        return (-boost, -float(item.get("overall") or 0), str(item.get("id") or ""))

    return sorted(profiles, key=sort_key)


def build_catalog(show_hidden: bool = False, root: Path | None = None) -> dict[str, Any]:
    catalog_version, seeds = load_catalog_seed()
    discovered = discover_ggufs(root)
    used_paths: set[str] = set()
    profiles: list[dict[str, Any]] = []

    for seed in seeds:
        match = _best_discovered_match(seed.match_hint, discovered, used_paths)
        if match is not None:
            used_paths.add(match.path)
        profile = build_graded_profile(seed, match)
        if profile["vram_state"] == "hidden" and not show_hidden:
            continue
        profiles.append(profile)

    ungraded = [
        {
            "filename": gguf.filename,
            "path": gguf.path,
            "weight_gb": gguf.weight_gb,
            "quantization": gguf.quantization,
        }
        for gguf in discovered
        if gguf.path not in used_paths
    ]

    return {
        "catalog_version": catalog_version,
        "models_root": str(root or models_root()),
        "vram_gb": node_vram_gb(),
        "profiles": sort_profiles(profiles),
        "ungraded": ungraded,
    }


def set_profile_pinned(profile_id: str, pinned: bool) -> None:
    key = (profile_id or "").strip()
    if not key:
        raise ValueError("profile_id is required")
    with _lock:
        state = _load_user_state_unlocked()
        pins = dict(state.get("pins") or {})
        pins[key] = bool(pinned)
        state["pins"] = pins
        _save_user_state_unlocked(state)


def apply_grade_override(
    profile_id: str,
    *,
    overall: float | None = None,
    axes: dict[str, float] | None = None,
) -> dict[str, Any]:
    key = (profile_id or "").strip()
    if not key:
        raise ValueError("profile_id is required")
    catalog_version, seeds = load_catalog_seed()
    seed = next((row for row in seeds if row.id == key), None)
    if seed is None:
        raise KeyError(f"catalog profile not found: {key}")

    with _lock:
        state = _load_user_state_unlocked()
        overrides = dict(state.get("overrides") or {})
        current = dict(overrides.get(key) or {})
        if overall is not None:
            current["overall"] = float(overall)
        if axes:
            axis_patch = dict(current.get("axes") or {})
            for axis_key in AXIS_KEYS:
                if axes.get(axis_key) is not None:
                    axis_patch[axis_key] = float(axes[axis_key])
            current["axes"] = axis_patch
        overrides[key] = current
        state["overrides"] = overrides
        _save_user_state_unlocked(state)

    discovered = discover_ggufs()
    match = _best_discovered_match(seed.match_hint, discovered, set())
    return build_graded_profile(seed, match)


def _lmstudio_endpoint() -> str:
    settings = load_settings()
    host = settings.inference.host or "127.0.0.1"
    backend = (settings.inference.backend or "").strip().lower()
    if backend in LMSTUDIO_ALIASES:
        port = settings.inference.port
    else:
        port = DEFAULT_PORTS["lmstudio"]
    return f"{host}:{port}"


def _gguf_model_id(path: str) -> str:
    return Path(path).stem


def select_catalog_profile(profile_id: str) -> dict[str, Any]:
    key = (profile_id or "").strip()
    if not key:
        raise ValueError("profile_id is required")
    catalog_version, seeds = load_catalog_seed()
    seed = next((row for row in seeds if row.id == key), None)
    if seed is None:
        raise KeyError(f"catalog profile not found: {key}")

    discovered = discover_ggufs()
    match = _best_discovered_match(seed.match_hint, discovered, set())
    if match is None:
        raise FileNotFoundError(f"no on-disk GGUF matched catalog profile: {key}")

    capability_tags = ["llm_inference", "text", "graded-catalog"]
    specialization = list(seed.specialization_tags)
    endpoint = _lmstudio_endpoint()
    model_id = _gguf_model_id(match.path)
    profile_name = key

    with _lock:
        state = _load_user_state_unlocked()
        bindings = dict(state.get("runtime_bindings") or {})
        runtime_id = bindings.get(key)
        runtime_profile: RuntimeProfile | None = None
        if runtime_id:
            runtime_profile = get_runtime_profile(str(runtime_id))

    if runtime_profile is None:
        runtime_profile = create_runtime_profile(
            name=profile_name,
            label=seed.display_name,
            model=model_id,
            provider="lmstudio",
            endpoint=endpoint,
            context_limit=32768,
            quantization=match.quantization,
            privacy_class=PRIVACY_LOCAL_ONLY,
            cost_ceiling_usd=0.0,
            capability_tags=capability_tags,
            specialization_tags=specialization,
            is_local=True,
            description=f"LM Studio graded catalog profile ({catalog_version})",
        )
    else:
        runtime_profile = update_runtime_profile(
            runtime_profile.id,
            label=seed.display_name,
            model=model_id,
            provider="lmstudio",
            endpoint=endpoint,
            quantization=match.quantization,
            privacy_class=PRIVACY_LOCAL_ONLY,
            cost_ceiling_usd=0.0,
            capability_tags=capability_tags,
            specialization_tags=specialization,
            is_local=True,
            description=f"LM Studio graded catalog profile ({catalog_version})",
        )

    with _lock:
        state = _load_user_state_unlocked()
        bindings = dict(state.get("runtime_bindings") or {})
        bindings[key] = runtime_profile.id
        state["runtime_bindings"] = bindings
        _save_user_state_unlocked(state)

    return runtime_profile.as_dict()


def get_graded_profile(profile_id: str) -> dict[str, Any] | None:
    key = (profile_id or "").strip()
    if not key:
        return None
    _, seeds = load_catalog_seed()
    seed = next((row for row in seeds if row.id == key), None)
    if seed is None:
        return None
    discovered = discover_ggufs()
    match = _best_discovered_match(seed.match_hint, discovered, set())
    return build_graded_profile(seed, match)
