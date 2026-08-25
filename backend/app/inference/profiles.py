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
        context_size=16384,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Default. 9B Abliterated Q8_0, 16K context, thinking only for planning/recovery.",
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
}


def declared_profiles() -> list[ModelProfile]:
    return list(PROFILES.values())


def profile_gguf(profile: ModelProfile) -> Path:
    return models_dir() / profile.repo_dir / profile.filename


def mmproj_path(profile: ModelProfile) -> Path:
    return models_dir() / profile.repo_dir / profile.mmproj_filename


def model_paths() -> dict[str, Path]:
    """Legacy 27B layout plus the 9B primary tree."""
    expert_root = models_dir() / EXPERT_DIR
    primary_root = models_dir() / PRIMARY_DIR
    return {
        "root": expert_root,
        "primary_root": primary_root,
        "q4": expert_root / "Qwen3.5-27B-Q4_K_M.gguf",
        "q5": expert_root / "Qwen3.5-27B-Q5_K_M.gguf",
        "mmproj": expert_root / EXPERT_MMPROJ,
        "q8_9b": primary_root / "Qwen3.5-9B-abliterated-Q8_0.gguf",
        "q6_9b": primary_root / "Qwen3.5-9B-abliterated-Q6_K.gguf",
        "mmproj_9b": primary_root / PRIMARY_MMPROJ,
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
    if profile_gguf(profile).exists():
        return profile
    for fallback_name in profile.fallbacks:
        alt = PROFILES.get(fallback_name)
        if alt and profile_gguf(alt).exists():
            return _with_alt_weights(profile, alt)
    expert = PROFILES["expert"]
    if profile.name != "expert" and profile_gguf(expert).exists():
        return _with_alt_weights(profile, expert)
    return profile


def expert_profile() -> ModelProfile:
    """Prefer Q5 when present; otherwise the dedicated Expert 27B Q4 consult profile.

    Consults stay compact (16K) even when the Expert weights themselves allow 32K.
    """
    paths = model_paths()
    quality = PROFILES["quality"]
    if (paths["root"] / quality.filename).exists():
        return with_context(quality, 16384)
    return with_context(PROFILES["expert"], 16384)
