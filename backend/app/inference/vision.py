from __future__ import annotations

from pathlib import Path

from .profiles import ModelProfile

VISION_CLASSES = {"multimodal", "windows gui"}


def should_load_vision(task_class: str | None, force: bool = False) -> bool:
    """Vision projector is opt-in. Ordinary text/tool work stays text-only."""
    if force:
        return True
    return (task_class or "").strip().lower() in VISION_CLASSES


def with_vision(profile: ModelProfile, enabled: bool) -> ModelProfile:
    return ModelProfile(
        name=profile.name,
        label=profile.label,
        quant=profile.quant,
        filename=profile.filename,
        thinking=profile.thinking,
        context_size=profile.context_size,
        temperature=profile.temperature,
        top_p=profile.top_p,
        top_k=profile.top_k,
        presence_penalty=profile.presence_penalty,
        description=profile.description,
        vision=bool(enabled),
    )


def mmproj_args(profile: ModelProfile, mmproj: Path) -> list[str]:
    """Only reserve multimodal VRAM when this load actually needs vision."""
    if not profile.vision:
        return []
    if not mmproj.exists():
        return []
    return ["--mmproj", str(mmproj), "--image-min-tokens", "1024"]
