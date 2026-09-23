"""RFC-0115: default runtime_role and answer_tier for model / runtime profiles."""

from __future__ import annotations

RUNTIME_ROLES = ("orchestrator", "general", "reasoner", "expert", "specialist")

_ORCHESTRATOR = frozenset({"bootstrap", "ornith_9b"})
_REASONER = frozenset({"quality"})
_EXPERT = frozenset(
    {
        "expert",
        "ornith_35b",
        "qwen38_27b_heretic",
        "qwen38-27b",
        "qwen38_27b",
    }
)
_GENERAL = frozenset({"fast", "balanced", "qwen38_9b", "qwen38-9b"})


def infer_runtime_role_and_tier(model_profile_name: str) -> tuple[str, int]:
    """Map a ``ModelProfile.name`` (or runtime name) to RFC-0115 role + tier."""
    key = (model_profile_name or "").strip().lower()
    if key in _ORCHESTRATOR:
        return "orchestrator", 1
    if key in _REASONER:
        return "reasoner", 3
    if key in _EXPERT:
        return "expert", 4
    if key in _GENERAL:
        return "general", 2
    return "general", 2


def orchestrator_profile_names() -> tuple[str, ...]:
    return ("ornith_9b", "bootstrap")


def default_orchestrator_profile_name() -> str:
    return "ornith_9b"
