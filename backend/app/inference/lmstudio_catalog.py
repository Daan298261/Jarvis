from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
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


# Named folders on extra volumes (USB, D:). Do not rglob the whole drive.
_EXTRA_VOLUME_MODEL_RELATIVES = (
    "Models",
    "models",
    "GGUF",
    "gguf",
    "HuggingFace",
    "huggingface",
    "Hugging Face",
    ".lmstudio/models",
    "llama.cpp",
    "Jarvis/models",
    "Jarvis/Models",
    "Jarvis/GGUF",
)


def extra_volume_model_roots() -> list[Path]:
    """Model directories on extra volumes (`D:\\Models`, USB `GGUF`, …)."""
    from ..config import extra_volume_roots

    roots: list[Path] = []
    seen: set[str] = set()
    for volume in extra_volume_roots():
        for relative in _EXTRA_VOLUME_MODEL_RELATIVES:
            candidate = volume / Path(relative)
            try:
                if not candidate.is_dir():
                    continue
                resolved = candidate.resolve()
            except OSError:
                continue
            key = str(resolved).replace("\\", "/").lower()
            if key in seen:
                continue
            seen.add(key)
            roots.append(candidate)
    return roots


def extra_volume_free_bytes() -> int:
    """Largest free space among currently mounted extra volumes."""
    from ..config import extra_volume_roots

    best = 0
    for volume in extra_volume_roots():
        try:
            free = int(shutil.disk_usage(volume).free)
        except OSError:
            continue
        if free > best:
            best = free
    return best


def extra_volume_install_root(*, need_bytes: int = 0) -> Path | None:
    """`Jarvis/models` on the extra volume with the most free space that fits."""
    from ..config import extra_volume_roots

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
            best = volume / "Jarvis" / "models"
    return best


def preferred_gguf_install_dir(relative_dir: str = "", *, need_bytes: int = 0) -> Path:
    """Install under `models/` when that volume fits; otherwise extra-drive `Jarvis/models`."""
    from ..config import models_dir

    local_root = models_dir()
    local = local_root / str(relative_dir or "") if relative_dir else local_root
    required = int(need_bytes or 0)
    try:
        local_free = int(shutil.disk_usage(local_root).free)
    except OSError:
        local_free = 0
    if required <= 0 or local_free >= required:
        return local
    extra = extra_volume_install_root(need_bytes=required)
    if extra is None:
        return local
    return extra / str(relative_dir or "") if relative_dir else extra


def extra_volume_named_model_dir(*relative: str, marker: str = "") -> Path | None:
    """Named folder under extra-volume model roots, if `marker` exists (or the folder is non-empty)."""
    parts = [str(part).strip() for part in relative if str(part).strip()]
    if not parts:
        return None
    needle = str(marker or "").strip()
    for root in extra_volume_model_roots():
        candidate = root.joinpath(*parts)
        try:
            if needle:
                hit = candidate / needle
                if hit.is_file() or hit.is_dir():
                    return candidate
            elif candidate.is_dir() and any(candidate.iterdir()):
                return candidate
        except OSError:
            continue
    return None


def resolved_cache_dir(
    name: str,
    *,
    local: Path,
    markers: tuple[str, ...] = (),
    need_bytes: int,
) -> Path:
    """Keep `local` when that volume fits or already has files; else extra-drive `Jarvis/models/<name>`."""
    slug = str(name or "").strip()
    if not slug:
        return local
    for marker in markers:
        try:
            hit = local / marker
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
        extra = extra_volume_named_model_dir(slug, marker=marker)
        if extra is not None:
            return extra
    required = int(need_bytes or 0)
    try:
        probe = local if local.exists() else local.parent
        if not probe.exists():
            from ..config import repo_root

            probe = repo_root()
        local_free = int(shutil.disk_usage(probe).free)
    except OSError:
        local_free = 0
    extra_root = extra_volume_install_root(need_bytes=required)
    if extra_root is not None and required > 0 and local_free < required:
        return extra_root / slug
    return local


def resolved_tts_model_dir(name: str, *, markers: tuple[str, ...] = (), need_bytes: int) -> Path:
    """`models/tts/<name>`, or extra-drive `Jarvis/models/tts/<name>` when C: cannot fit."""
    from ..config import models_dir as live_models_dir

    slug = str(name or "").strip()
    local = live_models_dir() / "tts" / slug if slug else live_models_dir() / "tts"
    if not slug:
        return local
    for marker in markers:
        try:
            hit = local / marker
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
        extra = extra_volume_named_model_dir("tts", slug, marker=marker)
        if extra is not None:
            return extra
    return preferred_gguf_install_dir(f"tts/{slug}", need_bytes=need_bytes)


def default_huggingface_home() -> Path:
    env = (os.environ.get("HF_HOME") or "").strip()
    if env:
        return Path(env)
    return Path.home() / ".cache" / "huggingface"


def resolved_huggingface_home() -> Path:
    """Keep `~/.cache/huggingface` when that volume fits; else extra-drive `Jarvis/models/huggingface`."""
    local = default_huggingface_home()
    if (os.environ.get("HF_HOME") or "").strip():
        return local
    dest = resolved_cache_dir(
        "huggingface",
        local=local,
        markers=("hub",),
        need_bytes=3 * 1024**3,
    )
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def apply_huggingface_home() -> Path:
    """Point Hugging Face Hub at extra-drive cache when C: cannot fit Chatterbox/Kokoro blobs."""
    dest = resolved_huggingface_home()
    dest.mkdir(parents=True, exist_ok=True)
    if (os.environ.get("HF_HOME") or "").strip():
        return dest
    default = Path.home() / ".cache" / "huggingface"
    try:
        same = dest.resolve() == default.resolve()
    except OSError:
        same = dest == default
    if not same:
        os.environ["HF_HOME"] = str(dest)
        os.environ["HF_HUB_CACHE"] = str(dest / "hub")
    return dest


def extra_volume_file_named(filename: str) -> Path | None:
    """Find a named GGUF (including mmproj) on extra-volume model folders or roots."""
    needle = str(filename or "").strip()
    if not needle:
        return None
    lower = needle.lower()
    for root in extra_volume_model_roots():
        try:
            for path in root.rglob(needle):
                if path.is_file():
                    return path
            for path in root.rglob("*.gguf"):
                if path.is_file() and path.name.lower() == lower:
                    return path
        except OSError:
            continue
    for path in extra_volume_loose_ggufs():
        if path.name.lower() == lower:
            return path
    return None


def extra_volume_loose_ggufs() -> list[Path]:
    """`*.gguf` sitting on an extra volume root (not nested in Photos, etc.)."""
    from ..config import extra_volume_roots

    files: list[Path] = []
    seen: set[str] = set()
    for volume in extra_volume_roots():
        try:
            matches = list(volume.glob("*.gguf"))
        except OSError:
            continue
        for path in matches:
            try:
                if not path.is_file():
                    continue
                key = str(path.resolve()).replace("\\", "/").lower()
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            files.append(path)
    return files


def owner_gguf_roots() -> list[Path]:
    """LM Studio root plus named extra-volume model folders."""
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        try:
            if not path.exists():
                return
        except OSError:
            return
        key = str(path).replace("\\", "/").lower()
        if key in seen:
            return
        seen.add(key)
        roots.append(path)

    add(resolve_models_root())
    for extra in extra_volume_model_roots():
        add(extra)
    return roots


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


def _iter_gguf_files(root: Path, *, recursive: bool) -> list[Path]:
    try:
        if not root.exists():
            return []
        iterator = root.rglob("*.gguf") if recursive else root.glob("*.gguf")
        return [path for path in iterator if path.is_file()]
    except OSError:
        return []


def _gguf_record(path: Path) -> DiscoveredGguf | None:
    if "mmproj" in path.name.lower():
        return None
    return DiscoveredGguf(
        filename=path.name,
        path=str(path),
        weight_gb=file_weight_gb(path),
        quantization=parse_quantization(path.name),
    )


def _collect_ggufs(paths: list[Path], *, recursive: bool) -> list[DiscoveredGguf]:
    found: list[DiscoveredGguf] = []
    seen: set[str] = set()
    for root in paths:
        for path in _iter_gguf_files(root, recursive=recursive):
            item = _gguf_record(path)
            if item is None:
                continue
            key = item.path.replace("\\", "/").lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(item)
    return found


def discover_ggufs(models_root: Path | None = None) -> list[DiscoveredGguf]:
    """Index GGUFs under one root, or the owner union when `models_root` is omitted.

    Explicit `models_root` stays a single-tree scan (tests and custom settings).
    The default union is LM Studio plus named folders on extra volumes and
    loose `*.gguf` files on those volume roots — never a full-drive rglob.
    """
    if models_root is not None:
        return sorted(_collect_ggufs([models_root], recursive=True), key=lambda item: item.path.lower())
    found = _collect_ggufs(owner_gguf_roots(), recursive=True)
    seen = {item.path.replace("\\", "/").lower() for item in found}
    for path in extra_volume_loose_ggufs():
        item = _gguf_record(path)
        if item is None:
            continue
        key = item.path.replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(item)
    found.sort(key=lambda item: item.path.lower())
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
    discovered = discover_ggufs(models_root) if models_root is not None else discover_ggufs()
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
    extra_roots = extra_volume_model_roots() if models_root is None else []
    return {
        "catalog_version": str(seed.get("catalog_version") or "unknown"),
        "models_root": str(root),
        "extra_roots": [str(path) for path in extra_roots],
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
    items = discover_ggufs(models_root) if models_root is not None else discover_ggufs()
    extra_roots = extra_volume_model_roots() if models_root is None else []
    return {
        "models_root": str(root),
        "extra_roots": [str(path) for path in extra_roots],
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


def _discovered_runtime_name(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8", errors="replace")).hexdigest()[:10]
    stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")[:24] or "local"
    return f"gguf-{stem}-{digest}"


def select_discovered_gguf(path: str, *, models_root: Path | None = None) -> RuntimeProfile:
    """Bind an owner-discovered GGUF (including extra-drive files) to llama.cpp."""
    raw = str(path or "").strip()
    if not raw:
        raise ValueError("path is required")
    items = discover_ggufs() if models_root is None else discover_ggufs(models_root)
    try:
        target_key = str(Path(raw).expanduser().resolve()).replace("\\", "/").lower()
    except OSError:
        target_key = raw.replace("\\", "/").lower()
    match: DiscoveredGguf | None = None
    for item in items:
        try:
            key = str(Path(item.path).resolve()).replace("\\", "/").lower()
        except OSError:
            key = item.path.replace("\\", "/").lower()
        if key == target_key or item.path == raw:
            match = item
            break
    if match is None:
        raise KeyError(f"gguf not in owner catalog: {raw}")
    resolved = Path(match.path)
    name = _discovered_runtime_name(resolved)
    settings = load_settings()
    endpoint = f"{settings.inference.host}:{suggested_port('llama.cpp', settings.inference.port)}"
    existing = next(
        (item for item in list_runtime_profiles() if (item.gguf_path or "") == str(resolved) or item.name == name),
        None,
    )
    if existing is not None:
        return update_runtime_profile(
            existing.id,
            label=match.filename,
            model=resolved.stem,
            provider="local-llama",
            endpoint=endpoint,
            quantization=match.quantization,
            privacy_class=PRIVACY_LOCAL_ONLY,
            is_local=True,
            capability_tags=["llm_inference", "text", "owner-gguf"],
            description=f"Owner GGUF {match.filename}",
            gguf_path=str(resolved),
        )
    taken = {item.name for item in list_runtime_profiles()}
    if name in taken:
        profile = next(item for item in list_runtime_profiles() if item.name == name)
        return update_runtime_profile(
            profile.id,
            label=match.filename,
            model=resolved.stem,
            provider="local-llama",
            endpoint=endpoint,
            quantization=match.quantization,
            privacy_class=PRIVACY_LOCAL_ONLY,
            is_local=True,
            capability_tags=["llm_inference", "text", "owner-gguf"],
            description=f"Owner GGUF {match.filename}",
            gguf_path=str(resolved),
        )
    return create_runtime_profile(
        name=name,
        label=match.filename,
        model=resolved.stem,
        provider="local-llama",
        endpoint=endpoint,
        context_limit=32768,
        quantization=match.quantization,
        privacy_class=PRIVACY_LOCAL_ONLY,
        cost_ceiling_usd=0.0,
        capability_tags=["llm_inference", "text", "owner-gguf"],
        is_local=True,
        description=f"Owner GGUF {match.filename}",
        gguf_path=str(resolved),
    )
