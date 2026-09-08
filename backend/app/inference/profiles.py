from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ..config import models_dir


@dataclass
class ModelProfile:
    name: str
    label: str
    quant: str
    filename: str
    family: str
    alias: str
    repo: str
    repo_dir: str
    mmproj_filename: str
    thinking: bool
    thinking_mode: str
    context_size: int
    temperature: float
    top_p: float
    top_k: int
    presence_penalty: float
    description: str
    vision: bool = False
    fallbacks: tuple[str, ...] = ()


# Community GGUF of wangzhang/Qwen3.5-9B-abliterated (preferred primary model).
PRIMARY_SOURCE = "wangzhang/Qwen3.5-9B-abliterated"
PRIMARY_GGUF_REPO = "Abiray/Qwen3.5-9B-abliterated-GGUF"
PRIMARY_DIR = "Qwen3.5-9B-abliterated-GGUF"
PRIMARY_MMPROJ = "mmproj-f16.gguf"

EXPERT_SOURCE = "Qwen/Qwen3.5-27B"
EXPERT_GGUF_REPO = "unsloth/Qwen3.5-27B-GGUF"
EXPERT_DIR = "Qwen3.5-27B-GGUF"
EXPERT_MMPROJ = "mmproj-F16.gguf"

# Official Ornith 1.5 GGUFs are benchmark candidates, not automatic replacements.
ORNITH_9B_SOURCE = "ornith-ai/Ornith-1.5-9B"
ORNITH_9B_GGUF_REPO = "ornith-ai/Ornith-1.5-9B-GGUF"
ORNITH_9B_DIR = "Ornith-1.5-9B-GGUF"
ORNITH_9B_MMPROJ = "mmproj-Ornith-1.5-9B-BF16.gguf"

ORNITH_35B_SOURCE = "ornith-ai/Ornith-1.5-35B-A3B"
ORNITH_35B_GGUF_REPO = "ornith-ai/Ornith-1.5-35B-A3B-GGUF"
ORNITH_35B_DIR = "Ornith-1.5-35B-A3B-GGUF"
ORNITH_35B_MMPROJ = "mmproj-Ornith-1.5-35B-BF16.gguf"

# Backward-compatible names used by older docs and tests.
MODEL_REPO = EXPERT_GGUF_REPO
OFFICIAL_MODEL = EXPERT_SOURCE
MMPROJ_NAME = EXPERT_MMPROJ


def with_context(profile: ModelProfile, context_size: int) -> ModelProfile:
    return replace(profile, context_size=int(context_size))


PROFILES: dict[str, ModelProfile] = {
    "fast": ModelProfile(
        name="fast",
        label="Fast",
        quant="Q6_K",
        filename="Qwen3.5-9B-abliterated-Q6_K.gguf",
        family="9b-abliterated",
        alias="Qwen3.5-9B",
        repo=PRIMARY_GGUF_REPO,
        repo_dir=PRIMARY_DIR,
        mmproj_filename=PRIMARY_MMPROJ,
        thinking=False,
        thinking_mode="off",
        context_size=8192,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        presence_penalty=0.0,
        description="9B Abliterated Q6_K, thinking off, 8K context. Maximum responsiveness.",
        fallbacks=("quality", "expert"),
    ),
    "balanced": ModelProfile(
        name="balanced",
        label="Balanced",
        quant="Q8_0",
        filename="Qwen3.5-9B-abliterated-Q8_0.gguf",
        family="9b-abliterated",
        alias="Qwen3.5-9B",
        repo=PRIMARY_GGUF_REPO,
        repo_dir=PRIMARY_DIR,
        mmproj_filename=PRIMARY_MMPROJ,
        thinking=True,
        thinking_mode="selective",
        context_size=32768,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Default. 9B Abliterated Q8_0, 32K cap with 16K start, thinking only for planning/recovery.",
        fallbacks=("fast", "expert"),
    ),
    "quality": ModelProfile(
        name="quality",
        label="Quality",
        quant="Q8_0",
        filename="Qwen3.5-9B-abliterated-Q8_0.gguf",
        family="9b-abliterated",
        alias="Qwen3.5-9B",
        repo=PRIMARY_GGUF_REPO,
        repo_dir=PRIMARY_DIR,
        mmproj_filename=PRIMARY_MMPROJ,
        thinking=True,
        thinking_mode="on",
        context_size=32768,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="9B Abliterated Q8_0 with thinking on and 32K context. Still the 9B primary model.",
        fallbacks=("balanced", "fast", "expert"),
    ),
    "expert": ModelProfile(
        name="expert",
        label="Expert",
        quant="Q4_K_M",
        filename="Qwen3.5-27B-Q4_K_M.gguf",
        family="27b",
        alias="Qwen3.5-27B",
        repo=EXPERT_GGUF_REPO,
        repo_dir=EXPERT_DIR,
        mmproj_filename=EXPERT_MMPROJ,
        thinking=True,
        thinking_mode="on",
        context_size=32768,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Optional 27B Q4_K_M escalation model. Not for ordinary tasks; may offload to CPU.",
        fallbacks=(),
    ),
    "ornith_9b": ModelProfile(
        name="ornith_9b",
        label="Ornith 1.5 9B",
        quant="Q8_0",
        filename="Ornith-1.5-9B-Q8_0.gguf",
        family="ornith-1.5-9b",
        alias="Ornith-1.5-9B",
        repo=ORNITH_9B_GGUF_REPO,
        repo_dir=ORNITH_9B_DIR,
        mmproj_filename=ORNITH_9B_MMPROJ,
        thinking=True,
        thinking_mode="selective",
        context_size=32768,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Official Ornith 1.5 9B Q8_0 candidate for primary agent/tool workloads. Benchmark before promotion to default routing.",
        vision=True,
        fallbacks=("balanced", "quality", "expert"),
    ),
    "ornith_35b": ModelProfile(
        name="ornith_35b",
        label="Ornith 1.5 35B-A3B",
        quant="Q4_K_M",
        filename="Ornith-1.5-35B-Q4_K_M.gguf",
        family="ornith-1.5-35b-a3b",
        alias="Ornith-1.5-35B-A3B",
        repo=ORNITH_35B_GGUF_REPO,
        repo_dir=ORNITH_35B_DIR,
        mmproj_filename=ORNITH_35B_MMPROJ,
        thinking=True,
        thinking_mode="on",
        context_size=32768,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Official Ornith 1.5 35B-A3B Q4_K_M candidate for Senior Worker/Expert workloads. Requires substantially more model memory than the 9B profile.",
        vision=True,
        fallbacks=("expert", "ornith_9b", "quality"),
    ),
}


def declared_profiles() -> list[ModelProfile]:
    return list(PROFILES.values())


def profile_gguf(profile: ModelProfile) -> Path:
    return models_dir() / profile.repo_dir / profile.filename


def mmproj_path(profile: ModelProfile) -> Path:
    return models_dir() / profile.repo_dir / profile.mmproj_filename


def resolve_mmproj(profile: ModelProfile | None = None) -> Path | None:
    """First existing projector: this profile's file, then known primary/expert projectors.

    Used only when a vision request actually starts llama.cpp with vision=True.
    Idle text loads must not attach mmproj.
    """
    candidates: list[Path] = []
    if profile is not None:
        candidates.append(mmproj_path(profile))
    paths = model_paths()
    for key in ("mmproj_9b", "mmproj_ornith_9b", "mmproj_ornith_35b", "mmproj"):
        raw = paths.get(key)
        if raw:
            candidates.append(Path(raw))
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = Path(candidate)
        except TypeError:
            continue
        marker = str(resolved)
        if marker in seen:
            continue
        seen.add(marker)
        if resolved.exists():
            return resolved
    return None


def model_paths() -> dict[str, Path]:
    """Known Qwen and Ornith model trees."""
    expert_root = models_dir() / EXPERT_DIR
    primary_root = models_dir() / PRIMARY_DIR
    ornith_9b_root = models_dir() / ORNITH_9B_DIR
    ornith_35b_root = models_dir() / ORNITH_35B_DIR
    return {
        "root": expert_root,
        "primary_root": primary_root,
        "ornith_9b_root": ornith_9b_root,
        "ornith_35b_root": ornith_35b_root,
        "q4": expert_root / "Qwen3.5-27B-Q4_K_M.gguf",
        "q5": expert_root / "Qwen3.5-27B-Q5_K_M.gguf",
        "mmproj": expert_root / EXPERT_MMPROJ,
        "q8_9b": primary_root / "Qwen3.5-9B-abliterated-Q8_0.gguf",
        "q6_9b": primary_root / "Qwen3.5-9B-abliterated-Q6_K.gguf",
        "mmproj_9b": primary_root / PRIMARY_MMPROJ,
        "ornith_9b_q8": ornith_9b_root / "Ornith-1.5-9B-Q8_0.gguf",
        "ornith_9b_q6": ornith_9b_root / "Ornith-1.5-9B-Q6_K.gguf",
        "ornith_35b_q4": ornith_35b_root / "Ornith-1.5-35B-Q4_K_M.gguf",
        "mmproj_ornith_9b": ornith_9b_root / ORNITH_9B_MMPROJ,
        "mmproj_ornith_35b": ornith_35b_root / ORNITH_35B_MMPROJ,
    }


def available_profiles() -> list[ModelProfile]:
    return [profile for profile in PROFILES.values() if profile_gguf(profile).exists()]


def _with_alt_weights(requested: ModelProfile, alt: ModelProfile) -> ModelProfile:
    return replace(
        requested,
        filename=alt.filename,
        quant=alt.quant,
        family=alt.family,
        alias=alt.alias,
        repo=alt.repo,
        repo_dir=alt.repo_dir,
        mmproj_filename=alt.mmproj_filename,
        description=f"{requested.description} Using {alt.label} weights because the preferred GGUF is not installed.",
    )


def resolve_profile(name: str) -> ModelProfile:
    key = (name or "balanced").lower()
    if key == "reliable":
        key = "quality"
    if key not in PROFILES:
        key = "balanced"
    profile = PROFILES[key]
    gguf = profile_gguf(profile)
    if not gguf.exists():
        expert = PROFILES["expert"]
        expert_path = profile_gguf(expert)
        if expert_path.exists() and key in {"fast", "balanced", "quality"}:
            return _with_alt_weights(profile, expert)
        if key == "expert" and not expert_path.exists():
            return PROFILES["balanced"]
    return profile


def profile_as_dict(profile: ModelProfile) -> dict:
    return {
        "name": profile.name,
        "label": profile.label,
        "quant": profile.quant,
        "thinking": profile.thinking,
        "thinking_mode": profile.thinking_mode,
        "context_size": profile.context_size,
        "description": profile.description,
        "family": profile.family,
        "alias": profile.alias,
        "repo": profile.repo,
        "installed": profile_gguf(profile).exists(),
        "vision": profile.vision,
    }


def expert_profile() -> ModelProfile:
    """Prefer Q5 when present; otherwise the dedicated Expert 27B Q4 consult profile."""
    paths = model_paths()
    quality = PROFILES["quality"]
    if (paths["root"] / quality.filename).exists():
        return with_context(quality, 16384)
    return with_context(PROFILES["expert"], 16384)
