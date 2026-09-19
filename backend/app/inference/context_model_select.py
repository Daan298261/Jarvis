"""RFC-0126: context-size model autoselect."""
from __future__ import annotations
from typing import Any, Iterable, TypeVar
from ..profiles import ModelProfile
from ..runtime_profiles import RuntimeProfile
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

def select_profile_for_context(required_tokens: int, profiles: Iterable[ProfileT], current_profile: ProfileT | None) -> ProfileT | None:
    required = max(1, int(required_tokens or 0))
    current_cap = profile_context_limit(current_profile)
    if current_cap >= required: return None
    current_id = _profile_identity(current_profile) if current_profile is not None else ""
    candidates = []
    for item in profiles:
        if not bool(getattr(item, "enabled", True)): continue
        cap = profile_context_limit(item)
        if cap < required or (current_cap and cap < current_cap): continue
        candidates.append((cap, item))
    if not candidates: return None
    candidates.sort(key=lambda p: (p[0], _profile_identity(p[1])))
    chosen = candidates[0][1]
    if current_id and _profile_identity(chosen) == current_id and profile_context_limit(chosen) <= current_cap:
        return None
    return chosen
