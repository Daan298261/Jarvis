from __future__ import annotations

from typing import Any

from .lease import SignedLease


def has_feature(lease: SignedLease | None, feature: str) -> bool:
    if lease is None:
        return False
    return feature in lease.payload.features


def has_pack_entitlement(lease: SignedLease | None, pack_id: str) -> bool:
    if lease is None:
        return False
    return pack_id in lease.payload.pack_entitlements


def evaluate_cluster_entitlements(lease: SignedLease | None) -> dict[str, Any]:
    if lease is None:
        return {
            "tier": None,
            "features": [],
            "pack_entitlements": [],
            "cluster_wide": True,
        }
    return {
        "tier": lease.payload.tier,
        "features": list(lease.payload.features),
        "pack_entitlements": list(lease.payload.pack_entitlements),
        "cluster_wide": True,
        "cluster_id": lease.payload.cluster_id,
    }
