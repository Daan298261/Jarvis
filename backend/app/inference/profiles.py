from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import models_dir

OFFICIAL_FOLDER = "Qwen3.5-27B-GGUF"
UNRESTRICTED_FOLDER = "Qwen3.5-27B-Unrestricted-GGUF"
ABLITERATED_FOLDER = "Qwen3.5-9B-Abliterated-GGUF"
MMPROJ_NAME = "mmproj-F16.gguf"
UNRESTRICTED_MMPROJ = "mmproj-Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-f16.gguf"
UNRESTRICTED_Q4 = "Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf"
UNRESTRICTED_Q5 = "Qwen3.5-27B-Uncensored-HauhauCS-Aggressive-Q5_K_M.gguf"
ABLITERATED_MMPROJ = "mmproj-f16.gguf"
ABLITERATED_Q6 = "Qwen3.5-9B-abliterated-Q6_K.gguf"
MODEL_REPO = "unsloth/Qwen3.5-27B-GGUF"
OFFICIAL_MODEL = "Qwen/Qwen3.5-27B"
UNRESTRICTED_REPO = "Unrestricted/Qwen3.5-27B-Uncensored-HauhauCS-Aggressive"
ABLITERATED_REPO = "Abiray/Qwen3.5-9B-abliterated-GGUF"


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
    family: str = "official"
    alias: str = "Qwen3.5-27B"
    folder: str = OFFICIAL_FOLDER
    mmproj_file: str = MMPROJ_NAME


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
        description="Official Unsloth Q4_K_M, thinking off, 16K context.",
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
        description="Official Unsloth Q4_K_M, thinking on, 32K context.",
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
        description="Official Unsloth Q5_K_M, thinking on, hybrid GPU/CPU.",
    ),
    "abliterated-fast": ModelProfile(
        name="abliterated-fast",
        label="Abliterated 9B Fast",
        quant="Q6_K",
        filename=ABLITERATED_Q6,
        thinking=False,
        context_size=16384,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        presence_penalty=0.0,
        description="Qwen3.5 9B Abliterated Q6_K, thinking off, fully GPU-resident.",
        family="abliterated",
        alias="Qwen3.5-9B-Abliterated",
        folder=ABLITERATED_FOLDER,
        mmproj_file=ABLITERATED_MMPROJ,
    ),
    "abliterated-balanced": ModelProfile(
        name="abliterated-balanced",
        label="Abliterated 9B Balanced",
        quant="Q6_K",
        filename=ABLITERATED_Q6,
        thinking=True,
        context_size=32768,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Qwen3.5 9B Abliterated Q6_K, thinking on, 32K context.",
        family="abliterated",
        alias="Qwen3.5-9B-Abliterated",
        folder=ABLITERATED_FOLDER,
        mmproj_file=ABLITERATED_MMPROJ,
    ),
    "unrestricted-fast": ModelProfile(
        name="unrestricted-fast",
        label="Unrestricted Fast",
        quant="Q4_K_M",
        filename=UNRESTRICTED_Q4,
        thinking=False,
        context_size=16384,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        presence_penalty=0.0,
        description="Unrestricted HauhauCS Q4_K_M beside the official model. Thinking off.",
        family="unrestricted",
        alias="Qwen3.5-27B-Unrestricted",
        folder=UNRESTRICTED_FOLDER,
        mmproj_file=UNRESTRICTED_MMPROJ,
    ),
    "unrestricted-balanced": ModelProfile(
        name="unrestricted-balanced",
        label="Unrestricted Balanced",
        quant="Q4_K_M",
        filename=UNRESTRICTED_Q4,
        thinking=True,
        context_size=32768,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Unrestricted HauhauCS Q4_K_M beside the official model. Thinking on.",
        family="unrestricted",
        alias="Qwen3.5-27B-Unrestricted",
        folder=UNRESTRICTED_FOLDER,
        mmproj_file=UNRESTRICTED_MMPROJ,
    ),
    "unrestricted-quality": ModelProfile(
        name="unrestricted-quality",
        label="Unrestricted Quality",
        quant="Q5_K_M",
        filename=UNRESTRICTED_Q5,
        thinking=True,
        context_size=32768,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Unrestricted HauhauCS Q5_K_M beside the official model. Thinking on.",
        family="unrestricted",
        alias="Qwen3.5-27B-Unrestricted",
        folder=UNRESTRICTED_FOLDER,
        mmproj_file=UNRESTRICTED_MMPROJ,
    ),
}


def model_paths(profile: ModelProfile | None = None) -> dict[str, Path]:
    spec = profile or PROFILES["balanced"]
    root = models_dir() / spec.folder
    payload = {
        "root": root,
        "gguf": root / spec.filename,
        "mmproj": root / spec.mmproj_file,
        "q4": root / spec.filename,
        "q5": root / spec.filename,
    }
    if spec.family == "official":
        payload["q4"] = root / "Qwen3.5-27B-Q4_K_M.gguf"
        payload["q5"] = root / "Qwen3.5-27B-Q5_K_M.gguf"
        payload["mmproj"] = root / MMPROJ_NAME
    return payload


def available_profiles() -> list[ModelProfile]:
    out: list[ModelProfile] = []
    for profile in PROFILES.values():
        if model_paths(profile)["gguf"].exists():
            out.append(profile)
    return out


def resolve_profile(name: str) -> ModelProfile:
    key = (name or "balanced").lower()
    if key not in PROFILES:
        key = "balanced"
    profile = PROFILES[key]
    gguf = model_paths(profile)["gguf"]
    if gguf.exists():
        return profile
    if profile.family in {"unrestricted", "abliterated"}:
        fallback_name = f"{profile.family}-balanced"
        fallback = PROFILES[fallback_name]
        if model_paths(fallback)["gguf"].exists():
            return fallback
        return PROFILES["balanced"]
    if key == "quality":
        return PROFILES["balanced"]
    return profile


# Names used by older import sites.
ModelProfile = ModelProfile
model_paths = model_paths
resolve_profile = resolve_profile
