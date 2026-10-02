from __future__ import annotations

from datetime import datetime
from typing import Any

from ..policy.cyber_ato import evaluate, licensed_module_allowed, license_blocks
from .lease import SignedLease
from .modules import module_ids, normalize_module_id

_PACK_MODULE_IDS = frozenset({"specialist.security", "domain.finance"})
FEATURE_JEV_PLUS = "decision.jev_plus"


def _config_plus_features() -> list[str]:
    """Owner-config Plus slots merged into the same features list `has_feature` reads (RFC-0116)."""
    try:
        from ..config import load_settings

        extra = list(getattr(load_settings().decision, "plus_features", []) or [])
    except Exception:
        return []
    out: list[str] = []
    for item in extra:
        name = str(item or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def has_feature(lease: SignedLease | None, feature: str) -> bool:
    return feature in evaluate_cluster_entitlements(lease).get("features", [])


def has_pack_entitlement(lease: SignedLease | None, pack_id: str) -> bool:
    if lease is None:
        return False
    key = normalize_module_id(pack_id)
    if licensed_module_allowed(key):
        return True
    return pack_id in lease.payload.pack_entitlements


def has_module(
    module_id: str,
    lease: SignedLease | None = None,
    *,
    now: datetime | None = None,
) -> bool:
    key = normalize_module_id(module_id)
    if licensed_module_allowed(key, now=now):
        return True
    if key in _PACK_MODULE_IDS:
        return has_pack_entitlement(lease, key)
    return False


HEXSTRIKE_ACCESS_LOCKED = "locked"
HEXSTRIKE_ACCESS_BLUE = "blue"  # legacy; RFC-0196 gates on hexstrike module (locked vs full)
HEXSTRIKE_ACCESS_FULL = "full"
HEXSTRIKE_PRO_MESSAGE = (
    "Install a signed license package on the License page that includes the hexstrike module."
)
HEXSTRIKE_MODULE_DENIED_MESSAGE = (
    "The installed license package does not include hexstrike."
)
HEXSTRIKE_OPERATOR_LICENSE_MESSAGE = (
    "Full HexStrike operator tools require the hexstrike module on the installed license package."
)
OWNER_UNRESTRICTED_PACKAGE_CLASS = "owner_unrestricted"


def hexstrike_denied_message(*, now: datetime | None = None) -> str:
    """Owner-visible deny reason that names the missing hexstrike module (RFC-0196 §5)."""
    return module_entitlement_blocked_reason("hexstrike", now=now) or HEXSTRIKE_MODULE_DENIED_MESSAGE


def hexstrike_access_mode(*, now: datetime | None = None) -> str:
    """License-module HexStrike gate: full when hexstrike is entitled, else locked (RFC-0196).

    Law-enforcement / password gates are not used as HexStrike capability unlocks.
    """
    if licensed_module_allowed("hexstrike", now=now):
        return HEXSTRIKE_ACCESS_FULL
    return HEXSTRIKE_ACCESS_LOCKED


def hexstrike_access_payload(*, now: datetime | None = None) -> dict[str, Any]:
    mode = hexstrike_access_mode(now=now)
    entitled = mode == HEXSTRIKE_ACCESS_FULL
    return {
        "access_mode": mode,
        "access_message": "" if entitled else hexstrike_denied_message(now=now),
        "operator_allowed": entitled,
        "blue_allowed": entitled,
        "hexstrike_module": entitled,
    }


def module_entitlement_blocked_reason(module_id: str, *, now: datetime | None = None) -> str | None:
    key = normalize_module_id(module_id)
    if licensed_module_allowed(key, now=now):
        return None
    blocked = license_blocks(key, now=now)
    if blocked:
        return blocked
    status = evaluate(now=now)
    if not status.installed:
        return f"Install a signed license package on the License page that includes {key}."
    return f"The installed license package does not include {key}."


def evaluate_cluster_entitlements(lease: SignedLease | None) -> dict[str, Any]:
    ato = evaluate()
    allowed_modules = [module_id for module_id in module_ids() if has_module(module_id, lease)]
    for pack_id in lease.payload.pack_entitlements if lease is not None else []:
        normalized = normalize_module_id(pack_id)
        if normalized not in allowed_modules and has_pack_entitlement(lease, pack_id):
            allowed_modules.append(normalized)
    extras = _config_plus_features()
    features: list[str] = []
    if lease is not None:
        features.extend(str(item) for item in lease.payload.features if str(item))
    for extra in extras:
        if extra not in features:
            features.append(extra)
    base: dict[str, Any] = {
        "tier": None,
        "features": features,
        "pack_entitlements": [],
        "cluster_wide": True,
        "package": ato.as_dict(),
        "allowed_modules": allowed_modules,
    }
    if lease is None:
        return base
    return {
        **base,
        "tier": lease.payload.tier,
        "features": features,
        "pack_entitlements": list(lease.payload.pack_entitlements),
        "cluster_id": lease.payload.cluster_id,
    }
