"""Scan common locations for local GGUF weights and register them with Jarvis."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import data_dir, models_dir, repo_root
from .lmstudio_catalog import DiscoveredGguf, discover_ggufs, file_weight_gb, parse_quantization, resolve_models_root
from .profiles import ModelProfile, PROFILES
from .runtime_profiles import (
    PRIVACY_LOCAL_ONLY,
    RuntimeProfile,
    create_runtime_profile,
    list_runtime_profiles,
    save_runtime_profile,
)

_lock = threading.RLock()
REGISTRY_NAME = "discovered_ggufs.json"
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "installer-build",
    "frontend",
    "android",
}
MAX_GGUF_FILES = 500


@dataclass
class RegisteredGguf:
    id: str
    path: str
    filename: str
    label: str
    weight_gb: float
    quantization: str
    profile_name: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _registry_path() -> Path:
    path = data_dir() / REGISTRY_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_registry_unlocked() -> list[RegisteredGguf]:
    path = _registry_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[RegisteredGguf] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            out.append(RegisteredGguf(**row))
        except TypeError:
            continue
    return out


def _save_registry_unlocked(rows: list[RegisteredGguf]) -> None:
    _registry_path().write_text(
        json.dumps([row.as_dict() for row in rows], indent=2),
        encoding="utf-8",
    )


def list_registered_ggufs() -> list[RegisteredGguf]:
    with _lock:
        return _load_registry_unlocked()


def _slug_id(path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")[:48] or "gguf"
    return f"discovered-{stem}-{digest}"


def _profile_name_for(entry: RegisteredGguf) -> str:
    return entry.profile_name or entry.id


def discovered_model_profiles() -> dict[str, ModelProfile]:
    profiles: dict[str, ModelProfile] = {}
    for row in list_registered_ggufs():
        path = Path(row.path)
        if not path.is_file():
            continue
        quant = row.quantization or parse_quantization(row.filename) or "GGUF"
        profiles[row.id] = ModelProfile(
            name=row.id,
            label=row.label or row.filename,
            quant=quant,
            filename=row.filename,
            family="discovered-local",
            alias=path.stem[:80],
            repo="local/discovered",
            repo_dir="discovered",
            mmproj_filename="",
            thinking=True,
            thinking_mode="selective",
            context_size=32768,
            temperature=0.6,
            top_p=0.95,
            top_k=20,
            presence_penalty=0.0,
            description=f"Discovered local weights at {row.path}",
            vision=False,
            fallbacks=("bootstrap", "balanced"),
            absolute_path=str(path.resolve()),
        )
    return profiles


def resolve_discovered_profile(name: str) -> ModelProfile | None:
    key = (name or "").strip()
    if not key:
        return None
    return discovered_model_profiles().get(key)


def standard_scan_roots(*, include_repo_models: bool = True) -> list[Path]:
    roots: list[Path] = []
    if include_repo_models:
        roots.append(models_dir())
        roots.append(repo_root() / "models")
    roots.append(resolve_models_root())
    custom = (os.environ.get("JARVIS_MODEL_SCAN_ROOTS") or "").strip()
    if custom:
        for part in custom.split(";"):
            part = part.strip()
            if part:
                roots.append(Path(part))
    if os.name == "nt":
        profile = (os.environ.get("USERPROFILE") or "").strip()
        if profile:
            roots.append(Path(profile) / "models")
            roots.append(Path(profile) / "Downloads")
        for env_key in ("LOCALAPPDATA", "PROGRAMDATA"):
            base = (os.environ.get(env_key) or "").strip()
            if base:
                roots.append(Path(base) / "Jarvis" / "models")
                roots.append(Path(base) / "lm-studio" / "models")
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = str(root.expanduser().resolve())
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(Path(resolved))
    return deduped


def _should_skip_dir(path: Path) -> bool:
    return path.name.lower() in SKIP_DIR_NAMES


def _scan_tree(root: Path, *, max_depth: int, found: list[DiscoveredGguf], seen_paths: set[str]) -> None:
    if len(found) >= MAX_GGUF_FILES or max_depth < 0 or not root.exists():
        return
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        if len(found) >= MAX_GGUF_FILES:
            return
        try:
            if entry.is_file() and entry.suffix.lower() == ".gguf":
                if "mmproj" in entry.name.lower():
                    continue
                resolved = str(entry.resolve())
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                found.append(
                    DiscoveredGguf(
                        filename=entry.name,
                        path=resolved,
                        weight_gb=file_weight_gb(entry),
                        quantization=parse_quantization(entry.name),
                    )
                )
            elif entry.is_dir() and not _should_skip_dir(entry):
                _scan_tree(entry, max_depth=max_depth - 1, found=found, seen_paths=seen_paths)
        except OSError:
            continue


def _windows_drive_roots() -> list[Path]:
    if os.name != "nt":
        return []
    roots: list[Path] = []
    for code in range(ord("C"), ord("Z") + 1):
        drive = f"{chr(code)}:\\"
        if Path(drive).exists():
            roots.append(Path(drive))
    return roots


def deep_scan_roots() -> list[Path]:
    """Shallow, bounded scan targets on fixed drives (Windows) or home (Unix)."""
    if os.name == "nt":
        patterns: list[Path] = []
        for drive in _windows_drive_roots():
            patterns.extend(
                [
                    drive / "models",
                    drive / "LLM",
                    drive / "AI",
                    drive / "Jarvis" / "models",
                ]
            )
            users = drive / "Users"
            if users.is_dir():
                try:
                    for user_dir in users.iterdir():
                        if not user_dir.is_dir() or user_dir.name.startswith("."):
                            continue
                        patterns.append(user_dir / "models")
                        patterns.append(user_dir / ".lmstudio" / "models")
                        patterns.append(user_dir / "Downloads")
                except OSError:
                    pass
        return patterns
    home = Path.home()
    return [
        home / "models",
        home / ".lmstudio" / "models",
        home / "Downloads",
    ]


def scan_local_ggufs(*, deep: bool = False) -> dict[str, Any]:
    """Scan standard roots and optionally bounded drive locations for GGUF files."""
    found: list[DiscoveredGguf] = []
    seen_paths: set[str] = set()

    for root in standard_scan_roots():
        if root.is_dir():
            _scan_tree(root, max_depth=8, found=found, seen_paths=seen_paths)

    if deep:
        for root in deep_scan_roots():
            if root.is_dir():
                _scan_tree(root, max_depth=5, found=found, seen_paths=seen_paths)

    # Include single-root discover_ggufs for LM Studio tree (rglob)
    for root in standard_scan_roots():
        for item in discover_ggufs(root):
            if item.path not in seen_paths:
                seen_paths.add(item.path)
                found.append(item)

    found.sort(key=lambda row: row.path.lower())
    registered = {row.path for row in list_registered_ggufs()}
    return {
        "count": len(found),
        "deep_scan": deep,
        "roots": [str(p) for p in standard_scan_roots()],
        "models": [
            {
                "filename": item.filename,
                "path": item.path,
                "weight_gb": item.weight_gb,
                "quantization": item.quantization,
                "already_registered": item.path in registered,
            }
            for item in found[:MAX_GGUF_FILES]
        ],
    }


def register_discovered_paths(paths: list[str]) -> dict[str, Any]:
    """Add GGUF paths to Jarvis discovered registry and runtime profile list."""
    from ..config import load_settings

    settings = load_settings()
    endpoint = f"{settings.inference.host}:{settings.inference.port}"
    added: list[RegisteredGguf] = []
    skipped: list[str] = []

    with _lock:
        registry = _load_registry_unlocked()
        known_paths = {row.path for row in registry}
        known_ids = {row.id for row in registry}

        for raw in paths:
            path = Path(raw).expanduser()
            if not path.is_file() or path.suffix.lower() != ".gguf":
                skipped.append(raw)
                continue
            resolved = str(path.resolve())
            if resolved in known_paths:
                skipped.append(resolved)
                continue
            entry = RegisteredGguf(
                id=_slug_id(path),
                path=resolved,
                filename=path.name,
                label=path.stem.replace("_", " ").replace("-", " ")[:80],
                weight_gb=file_weight_gb(path),
                quantization=parse_quantization(path.name),
                profile_name="",
            )
            while entry.id in known_ids:
                entry.id = f"{entry.id}-x"
            entry.profile_name = entry.id
            registry.append(entry)
            known_paths.add(resolved)
            known_ids.add(entry.id)
            added.append(entry)

        if added:
            _save_registry_unlocked(registry)

    for entry in added:
        try:
            create_runtime_profile(
                name=entry.profile_name,
                label=entry.label,
                model=Path(entry.path).stem[:120],
                provider="local-llama",
                endpoint=endpoint,
                context_limit=32768,
                quantization=entry.quantization or "GGUF",
                privacy_class=PRIVACY_LOCAL_ONLY,
                cost_ceiling_usd=0.0,
                capability_tags=["llm_inference", "text", "discovered-local"],
                model_profile=entry.id,
                specialization_tags=["discovered"],
                is_local=True,
                description=f"Discovered GGUF at {entry.path}",
                enabled=True,
            )
        except ValueError:
            for runtime in list_runtime_profiles():
                if runtime.model_profile == entry.id or runtime.description.endswith(entry.path):
                    updated = RuntimeProfile.from_dict(runtime.as_dict())
                    updated.enabled = True
                    updated.description = f"Discovered GGUF at {entry.path}"
                    save_runtime_profile(updated)
                    break

    return {
        "added": [row.as_dict() for row in added],
        "skipped": skipped,
        "registered_count": len(list_registered_ggufs()),
    }


def register_all_from_scan(*, deep: bool = False) -> dict[str, Any]:
    payload = scan_local_ggufs(deep=deep)
    new_paths = [
        row["path"]
        for row in payload.get("models") or []
        if isinstance(row, dict) and not row.get("already_registered")
    ]
    result = register_discovered_paths(new_paths)
    result["scan"] = {"count": payload.get("count", 0), "deep_scan": deep}
    return result


def merge_builtin_profiles() -> dict[str, ModelProfile]:
    """PROFILES plus discovered entries for UI listing."""
    merged = dict(PROFILES)
    merged.update(discovered_model_profiles())
    return merged
