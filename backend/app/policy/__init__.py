"""Policy profiles and authorization — lazy exports for faster vendor-tool builds."""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "AutonomyLevel",
    "AuthorizationResult",
    "authorize",
    "create_profile",
    "delete_profile",
    "get_platform_policy",
    "get_profile",
    "list_profiles",
    "normalize_policy_from_interview",
    "reset_policy_store",
    "update_platform_policy",
    "update_profile",
]

_LAZY: dict[str, tuple[str, str]] = {
    "AuthorizationResult": (".authorize", "AuthorizationResult"),
    "authorize": (".authorize", "authorize"),
    "AutonomyLevel": (".levels", "AutonomyLevel"),
    "create_profile": (".store", "create_profile"),
    "delete_profile": (".store", "delete_profile"),
    "get_platform_policy": (".store", "get_platform_policy"),
    "get_profile": (".store", "get_profile"),
    "list_profiles": (".store", "list_profiles"),
    "normalize_policy_from_interview": (".store", "normalize_policy_from_interview"),
    "reset_policy_store": (".store", "reset_policy_store"),
    "update_platform_policy": (".store", "update_platform_policy"),
    "update_profile": (".store", "update_profile"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = _LAZY[name]
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value
    return value
