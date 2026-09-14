"""Cluster licensing — lazy exports so vendor tools avoid importing inference/service at startup."""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "LicenseError",
    "SignedLease",
    "delete_inference_credential",
    "ensure_cluster_identity",
    "evaluate_cluster_entitlements",
    "get_cluster_id",
    "get_license_status",
    "has_feature",
    "has_pack_entitlement",
    "list_inference_credentials",
    "refresh_lease",
    "sign_lease",
    "upsert_inference_credential",
    "validate_offline",
]

_LAZY: dict[str, tuple[str, str]] = {
    "ensure_cluster_identity": (".cluster", "ensure_cluster_identity"),
    "get_cluster_id": (".cluster", "get_cluster_id"),
    "evaluate_cluster_entitlements": (".entitlements", "evaluate_cluster_entitlements"),
    "has_feature": (".entitlements", "has_feature"),
    "has_pack_entitlement": (".entitlements", "has_pack_entitlement"),
    "delete_inference_credential": (".inference", "delete_inference_credential"),
    "list_inference_credentials": (".inference", "list_inference_credentials"),
    "upsert_inference_credential": (".inference", "upsert_inference_credential"),
    "SignedLease": (".lease", "SignedLease"),
    "sign_lease": (".lease", "sign_lease"),
    "LicenseError": (".service", "LicenseError"),
    "get_license_status": (".service", "get_license_status"),
    "refresh_lease": (".service", "refresh_lease"),
    "validate_offline": (".service", "validate_offline"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = _LAZY[name]
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value
    return value
