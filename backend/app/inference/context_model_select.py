"""RFC-0131: context-size model autoselect."""
from __future__ import annotations
from typing import Any, Iterable, TypeVar
from .profiles import ModelProfile
from .runtime_profiles import RuntimeProfile
ProfileT = TypeVar("ProfileT", RuntimeProfile, ModelProfile, Any)

def profile_context_limit(profile: ProfileT | None) -> int:
    if profile is None: return 0
    if isinstance(profile, RuntimeProfile): return max(0, int(profile.context_limit or 0))
    if isinstance(profile, ModelProfile): return max(0, int(profile.context_size or 0))
    lim = getattr(profile, "context_limit", None)
    if lim is not None: return max(0, int(lim or 0))
    return max(0, int(getattr(profile, "context_size", 0) or 0))

def _profile_identity(profile: ProfileT) -> str:
    if isinstance(profile, RuntimeProfile):
        return (profile.model_profile or profile.name or profile.id or "").strip()
    return str(getattr(profile, "name", "") or "").strip()

def _local_weights_ready(profile: ProfileT) -> bool:
    """Skip catalog rows whose local GGUF is not on disk (bootstrap often is not)."""
    name = _profile_identity(profile)
    if not name:
        return True
    provider = str(getattr(profile, "provider", "") or "").lower()
    # Shared Ollama (including community models) is not a silent fallback.
    # Those runtimes load only when the owner picks them.
    if provider == "ollama":
        return False
    if provider and provider not in {"local-llama", "llama.cpp", "llamacpp"}:
        return True
    from .profiles import PROFILES, profile_gguf

    row = PROFILES.get(name)
    if row is None:
        return True
    return profile_gguf(row).exists()


def select_profile_for_context(
    required_tokens: int,
    profiles: Iterable[ProfileT],
    current_profile: ProfileT | None,
    *,
    minimum_answer_tier: int = 0,
) -> ProfileT | None:
    required = max(1, int(required_tokens or 0))
    current_cap = profile_context_limit(current_profile)
    if current_cap >= required: return None
    current_id = _profile_identity(current_profile) if current_profile is not None else ""
    candidates = []
    for item in profiles:
        if not bool(getattr(item, "enabled", True)): continue
        if not _local_weights_ready(item):
            continue
        tier = int(getattr(item, "answer_tier", 0) or 0)
        if minimum_answer_tier and tier < minimum_answer_tier:
            continue
        cap = profile_context_limit(item)
        if cap < required or (current_cap and cap < current_cap): continue
        candidates.append((cap, item))
    if not candidates: return None
    candidates.sort(key=lambda p: (p[0], _profile_identity(p[1])))
    chosen = candidates[0][1]
    if current_id and _profile_identity(chosen) == current_id and profile_context_limit(chosen) <= current_cap:
        return None
    return chosen
