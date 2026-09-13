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
    absolute_path: str = ""


# Community GGUF of wangzhang/Qwen3.5-9B-abliterated (legacy primary model).
PRIMARY_SOURCE = "wangzhang/Qwen3.5-9B-abliterated"
PRIMARY_GGUF_REPO = "Abiray/Qwen3.5-9B-abliterated-GGUF"
PRIMARY_DIR = "Qwen3.5-9B-abliterated-GGUF"
PRIMARY_MMPROJ = "mmproj-f16.gguf"

EXPERT_SOURCE = "Qwen/Qwen3.5-27B"
EXPERT_GGUF_REPO = "unsloth/Qwen3.5-27B-GGUF"
EXPERT_DIR = "Qwen3.5-27B-GGUF"
EXPERT_MMPROJ = "mmproj-F16.gguf"

# Smallest official Ornith 1.5 release. A Q4_K_M GGUF is staged into release
# installers as Jarvis' offline-capable bootstrap model.
BOOTSTRAP_SOURCE = "ornith-ai/Ornith-1.5-9B"
BOOTSTRAP_GGUF_REPO = "ornith-ai/Ornith-1.5-9B-GGUF"
BOOTSTRAP_DIR = "bootstrap"
BOOTSTRAP_FILENAME = "Ornith-1.5-9B-Q4_K_M.gguf"

ORNITH_9B_SOURCE = "ornith-ai/Ornith-1.5-9B"
ORNITH_9B_GGUF_REPO = "ornith-ai/Ornith-1.5-9B-GGUF"
ORNITH_9B_DIR = "Ornith-1.5-9B-GGUF"
ORNITH_9B_MMPROJ = "mmproj-Ornith-1.5-9B-BF16.gguf"

ORNITH_35B_SOURCE = "ornith-ai/Ornith-1.5-35B-A3B"
ORNITH_35B_GGUF_REPO = "ornith-ai/Ornith-1.5-35B-A3B-GGUF"
ORNITH_35B_DIR = "Ornith-1.5-35B-A3B-GGUF"
ORNITH_35B_MMPROJ = "mmproj-Ornith-1.5-35B-BF16.gguf"

HERETIC_27B_GGUF_REPO = "0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF"
HERETIC_27B_DIR = "Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF"
HERETIC_27B_FILENAME = "RVN-Q3_K_S-multilingual.gguf"
HERETIC_27B_SHA256 = "b6419bd23d26ba9f3c2803779171c6e233dbed30631aa8d0350049c4011248a8"

# Backward-compatible names used by older docs and tests.
MODEL_REPO = EXPERT_GGUF_REPO
OFFICIAL_MODEL = EXPERT_SOURCE
MMPROJ_NAME = EXPERT_MMPROJ


def with_context(profile: ModelProfile, context_size: int) -> ModelProfile:
    return replace(profile, context_size=int(context_size))


PROFILES: dict[str, ModelProfile] = {
    "bootstrap": ModelProfile(
        name="bootstrap",
        label="Bootstrap · Ornith 1.5 9B",
        quant="Q4_K_M",
        filename=BOOTSTRAP_FILENAME,
        family="ornith-1.5-9b",
        alias="Ornith-1.5-9B",
        repo=BOOTSTRAP_GGUF_REPO,
        repo_dir=BOOTSTRAP_DIR,
        mmproj_filename="",
        thinking=True,
        thinking_mode="selective",
        context_size=16384,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Bundled local fallback. Good for setup, chat, orchestration, tool routing and recovery; heavier models can take difficult work.",
        vision=False,
        fallbacks=("ornith_9b", "balanced", "quality", "expert"),
    ),
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
        fallbacks=("bootstrap", "quality", "expert"),
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
        description="Legacy 9B Q8_0 primary profile with selective thinking.",
        fallbacks=("bootstrap", "fast", "expert"),
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
        description="9B Abliterated Q8_0 with thinking on and 32K context.",
        fallbacks=("bootstrap", "balanced", "fast", "expert"),
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
        fallbacks=("bootstrap",),
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
        description="Official Ornith 1.5 9B high-quality quant for primary agent/tool workloads.",
        vision=True,
        fallbacks=("bootstrap", "balanced", "quality", "expert"),
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
        fallbacks=("expert", "ornith_9b", "bootstrap", "quality"),
    ),
}


def declared_profiles() -> list[ModelProfile]:
    return list(PROFILES.values())


def profile_gguf(profile: ModelProfile) -> Path:
    if profile.absolute_path:
        return Path(profile.absolute_path)
    return models_dir() / profile.repo_dir / profile.filename


def mmproj_path(profile: ModelProfile) -> Path:
    return models_dir() / profile.repo_dir / profile.mmproj_filename


def resolve_mmproj(profile: ModelProfile | None = None) -> Path | None:
    """First existing projector. Used only when a vision request needs it."""
    candidates: list[Path] = []
    if profile is not None and profile.mmproj_filename:
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
    """Known bootstrap, Qwen and Ornith model trees."""
    bootstrap_root = models_dir() / BOOTSTRAP_DIR
    expert_root = models_dir() / EXPERT_DIR
    primary_root = models_dir() / PRIMARY_DIR
    ornith_9b_root = models_dir() / ORNITH_9B_DIR
    ornith_35b_root = models_dir() / ORNITH_35B_DIR
    return {
        "root": expert_root,
        "bootstrap_root": bootstrap_root,
        "bootstrap": bootstrap_root / BOOTSTRAP_FILENAME,
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


def qwen38_9b_profile() -> ModelProfile | None:
    """Local Qwen3.8-9B uncensored (RFC-0078) when a matching GGUF is on disk."""
    from .qwen38_local import discover_qwen38_9b_uncensored

    found = discover_qwen38_9b_uncensored()
    if found is None:
        return None
    quant = found.quantization or "Q4_K_M"
    tag = "uncensored" if found.uncensored else "local"
    return ModelProfile(
        name="qwen38_9b",
        label=f"Qwen3.8 9B {tag}",
        quant=quant,
        filename=found.filename,
        family="qwen38-9b",
        alias="Qwen3.8-9B",
        repo="local/qwen3.8-9b",
        repo_dir=found.path.parent.name,
        mmproj_filename="",
        thinking=True,
        thinking_mode="selective",
        context_size=32768,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Local Qwen3.8-9B (uncensored preferred) used as the everyday default when installed.",
        vision=False,
        fallbacks=("balanced", "fast", "bootstrap", "expert"),
        absolute_path=str(found.path),
    )


def qwen38_27b_heretic_profile() -> ModelProfile | None:
    """Internal llama.cpp profile for the owner-selected RVN Q3 multilingual 27B."""
    from .qwen38_local import discover_qwen38_27b_heretic

    found = discover_qwen38_27b_heretic()
    if found is None:
        return None
    return ModelProfile(
        name="qwen38_27b_heretic",
        label="Qwen3.8 27B Heretic · RVN Q3 multilingual",
        quant=found.quantization or "Q3_K_S",
        filename=found.filename,
        family="qwen38-27b-heretic",
        alias="Qwen3.8-27B-Heretic",
        repo=HERETIC_27B_GGUF_REPO,
        repo_dir=found.path.parent.name,
        mmproj_filename="",
        thinking=True,
        thinking_mode="on",
        context_size=8192,
        temperature=0.6,
        top_p=0.95,
        top_k=20,
        presence_penalty=0.0,
        description="Owner-selected internal 27B reasoning model. Starts at an 8K context to preserve VRAM headroom on a 16 GB GPU.",
        vision=False,
        fallbacks=("qwen38_9b", "quality", "bootstrap"),
        absolute_path=str(found.path),
    )


def available_profiles() -> list[ModelProfile]:
    installed = [profile for profile in PROFILES.values() if profile_gguf(profile).exists()]
    heretic = qwen38_27b_heretic_profile()
    if heretic is not None:
        installed = [heretic, *installed]
    extra = qwen38_9b_profile()
    if extra is not None:
        installed = [extra, *[item for item in installed if item.name != extra.name]]
    return installed


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
        vision=alt.vision,
        description=f"{requested.description} Using {alt.label} weights because the preferred GGUF is not installed.",
    )


def resolve_profile(name: str) -> ModelProfile:
    key = (name or "bootstrap").lower()
    if key == "reliable":
        key = "quality"
    if key in {"qwen38_9b", "qwen3.8-9b", "qwen38-9b"}:
        extra = qwen38_9b_profile()
        if extra is not None:
            return extra
        key = "balanced"
    if key in {"qwen38_27b_heretic", "qwen38-27b-heretic", "heretic-27b", "rvn-q3"}:
        heretic = qwen38_27b_heretic_profile()
        if heretic is not None:
            return heretic
        key = "quality"
    if key not in PROFILES:
        extra = qwen38_9b_profile()
        if extra is not None and key == extra.name:
            return extra
        key = "bootstrap" if profile_gguf(PROFILES["bootstrap"]).exists() else "balanced"
    profile = PROFILES[key]
    if profile_gguf(profile).exists():
        return profile

    bootstrap = PROFILES["bootstrap"]
    if key != "bootstrap" and profile_gguf(bootstrap).exists():
        return _with_alt_weights(profile, bootstrap)

    expert = PROFILES["expert"]
    if key in {"fast", "balanced", "quality"} and profile_gguf(expert).exists():
        return _with_alt_weights(profile, expert)
    if key == "expert" and not profile_gguf(expert).exists():
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
        "absolute_path": profile.absolute_path or "",
    }


def preferred_startup_profile(requested: str | None = None) -> str:
    """Everyday autoload: Qwen3.8-9B uncensored when installed (RFC-0078)."""
    from .qwen38_local import should_prefer_qwen38_default

    name = (requested or "balanced").strip().lower() or "balanced"
    if should_prefer_qwen38_default(name) and qwen38_9b_profile() is not None:
        return "qwen38_9b"
    return name


def expert_profile() -> ModelProfile:
    """Prefer Q5 when present; otherwise the dedicated Expert 27B Q4 consult profile."""
    paths = model_paths()
    quality = PROFILES["quality"]
    if (paths["root"] / quality.filename).exists():
        return with_context(quality, 16384)
    return with_context(PROFILES["expert"], 16384)
