from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import models_dir


@dataclass
class ModelProfile:
    name: str
    label: str
    quant: str
    filename: str
    thinking: bool
    context_size: int
    temperature: float
    top_p: float
    top_k: int
    presence_penalty: float
    description: str


PROFILES: dict[str, ModelProfile] = {
    "fast": ModelProfile(
        name="fast",
        label="Fast",
        quant="Q4_K_M",
        filename="Qwen3.5-27B-Q4_K_M.gguf",
        thinking=False,
        context_size=16384,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        presence_penalty=0.0,
        description="Non-thinking Q4_K_M with a smaller context window.",
    ),
    "balanced": ModelProfile(
        name="balanced",
        label="Balanced",
        quant="Q4_K_M",
        filename="Qwen3.5-27B-Q4_K_M.gguf",
        thinking=True,
        context_size=32768,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Thinking-enabled Q4_K_M for autonomous tool work.",
    ),
    "quality": ModelProfile(
        name="quality",
        label="Quality",
        quant="Q5_K_M",
        filename="Qwen3.5-27B-Q5_K_M.gguf",
        thinking=True,
        context_size=32768,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Higher-quality Q5_K_M hybrid GPU/CPU profile.",
    ),
    "expert": ModelProfile(
        name="expert",
        label="Expert",
        quant="Q4_K_M",
        filename="Qwen3.5-27B-Q4_K_M.gguf",
        thinking=True,
        context_size=16384,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Escalation-only 27B profile. Not used for ordinary tool work.",
    ),
}


MMPROJ_NAME = "mmproj-F16.gguf"
MODEL_REPO = "unsloth/Qwen3.5-27B-GGUF"
OFFICIAL_MODEL = "Qwen/Qwen3.5-27B"


def model_paths() -> dict[str, Path]:
    root = models_dir() / "Qwen3.5-27B-GGUF"
    return {
        "root": root,
        "q4": root / "Qwen3.5-27B-Q4_K_M.gguf",
        "q5": root / "Qwen3.5-27B-Q5_K_M.gguf",
        "mmproj": root / MMPROJ_NAME,
    }


def available_profiles() -> list[ModelProfile]:
    paths = model_paths()
    out: list[ModelProfile] = []
    for profile in PROFILES.values():
        gguf = paths["root"] / profile.filename
        if gguf.exists():
            out.append(profile)
    return out


def resolve_profile(name: str) -> ModelProfile:
    key = (name or "balanced").lower()
    if key not in PROFILES:
        key = "balanced"
    profile = PROFILES[key]
    paths = model_paths()
    gguf = paths["root"] / profile.filename
    if not gguf.exists() and key == "quality":
        return PROFILES["balanced"]
    return profile
