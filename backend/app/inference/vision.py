from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .profiles import ModelProfile

VISION_CLASSES = {"multimodal", "windows gui"}


def should_load_vision(task_class: str | None, force: bool = False) -> bool:
    """Vision projector is opt-in. Ordinary text/tool work stays text-only."""
    if force:
        return True
    return (task_class or "").strip().lower() in VISION_CLASSES


def with_vision(profile: ModelProfile, enabled: bool) -> ModelProfile:
    return replace(profile, vision=bool(enabled))


def messages_need_vision(messages: Iterable[Any]) -> bool:
    """True when a chat turn includes an image part that needs the projector."""
    for message in messages:
        content = getattr(message, "content", message)
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in {"image_url", "image"} or "image_url" in part:
                return True
    return False


def mmproj_args(profile: ModelProfile, mmproj: Path) -> list[str]:
    """Only reserve multimodal VRAM when this load actually needs vision."""
    if not profile.vision:
        return []
    if not mmproj.exists():
        return []
    return ["--mmproj", str(mmproj), "--image-min-tokens", "1024"]
