from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from ..db.models import Node, NodeBudget, ResourceLease
from ..db.session import SessionLocal

BUDGET_PRESET_MINIMAL = "minimal"
BUDGET_PRESET_BALANCED = "balanced"
BUDGET_PRESET_HIGH = "high"
BUDGET_PRESET_MAXIMUM = "maximum"
BUDGET_PRESET_CUSTOM = "custom"

BUDGET_PRESETS = (
    BUDGET_PRESET_MINIMAL,
    BUDGET_PRESET_BALANCED,
    BUDGET_PRESET_HIGH,
    BUDGET_PRESET_MAXIMUM,
    BUDGET_PRESET_CUSTOM,
)

PRESET_GLOBAL_PERCENT = {
    BUDGET_PRESET_MINIMAL: 15,
    BUDGET_PRESET_BALANCED: 50,
    BUDGET_PRESET_HIGH: 75,
    BUDGET_PRESET_MAXIMUM: 100,
    BUDGET_PRESET_CUSTOM: 50,
}

BUDGET_MODE_STATIC = "static"
BUDGET_MODE_DYNAMIC = "dynamic"

CAP_HARD = "HARD"
CAP_SOFT = "SOFT"

LEASE_STATUS_ACTIVE = "active"
LEASE_STATUS_RELEASED = "released"
LEASE_STATUS_EXPIRED = "expired"

RESOURCE_KEYS = ("cpu", "ram", "gpu", "vram", "disk", "network")

CLAIM_FIELD_BY_RESOURCE = {
    "cpu": "cpu_threads",
    "ram": "ram_gb",
    "gpu": "gpu_percent",
    "vram": "vram_mib",
    "disk": "disk_gb",
    "network": "network_mbps",
}

HOST_FIELD_BY_RESOURCE = {
    "cpu": "cpu_threads",
    "ram": "ram_total_gb",
    "gpu": None,
    "vram": "vram_total_mib",
    "disk": "disk_total_gb",
    "network": None,
}

DEFAULT_HOST_NETWORK_MBPS = 1000.0
DEFAULT_GPU_SCALE = 100.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_preset(preset: str) -> str:
    return str(preset or "").strip().lower()


def validate_preset(preset: str) -> str:
    normalized = normalize_preset(preset)
    if normalized not in BUDGET_PRESETS:
        raise ValueError(f"Invalid budget preset: {preset!r}")
    return normalized


def validate_global_percent(value: int | float | str) -> int:
    try:
        percent = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid global_percent: {value!r}") from exc
    if percent < 0 or percent > 100:
        raise ValueError("global_percent must be between 0 and 100")
    return percent


def normalize_cap(cap: str) -> str:
    normalized = str(cap or CAP_SOFT).strip().upper()
    if normalized not in (CAP_HARD, CAP_SOFT):
        raise ValueError(f"Invalid cap type: {cap!r}")
    return normalized


def _parse_json_dict(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_limits(limits: dict[str, Any] | None) -> dict[str, Any]:
    if not limits:
        return {}
    normalized: dict[str, Any] = {}
    for resource, value in limits.items():
        key = str(resource or "").strip().lower()
        if key not in RESOURCE_KEYS:
            raise ValueError(f"Unknown resource limit: {resource!r}")
        if not isinstance(value, dict):
            raise ValueError(f"Limit for {key!r} must be an object")
        entry: dict[str, Any] = {}
        if "percent" in value and value["percent"] is not None:
            entry["percent"] = validate_global_percent(value["percent"])
        if "absolute" in value and value["absolute"] is not None:
            entry["absolute"] = float(value["absolute"])
        if "absolute_gb" in value and value["absolute_gb"] is not None:
            entry["absolute"] = float(value["absolute_gb"])
        if "absolute_mib" in value and value["absolute_mib"] is not None:
            entry["absolute"] = float(value["absolute_mib"])
        if "absolute_mbps" in value and value["absolute_mbps"] is not None:
            entry["absolute"] = float(value["absolute_mbps"])
        if "cap" in value and value["cap"] is not None:
            entry["cap"] = normalize_cap(value["cap"])
        normalized[key] = entry
    return normalized


def default_budget_payload() -> dict[str, Any]:
    return {
        "preset": BUDGET_PRESET_BALANCED,
        "mode": BUDGET_MODE_STATIC,
        "global_percent": PRESET_GLOBAL_PERCENT[BUDGET_PRESET_BALANCED],
        "limits": {},
    }


def budget_to_dict(row: NodeBudget) -> dict[str, Any]:
    return {
        "node_id": row.node_id,
        "preset": row.preset,
        "mode": row.mode,
        "global_percent": row.global_percent,
        "limits": _parse_json_dict(row.limits_json),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def lease_to_dict(row: ResourceLease) -> dict[str, Any]:
    return {
        "id": row.id,
        "node_id": row.node_id,
        "claim": _parse_json_dict(row.claim_json),
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "released_at": row.released_at.isoformat() if row.released_at else None,
    }


def _host_capacity(resources: dict[str, Any], resource: str) -> float:
    if resource == "gpu":
        return DEFAULT_GPU_SCALE
    if resource == "network":
        value = resources.get("network_mbps")
        return float(value) if value is not None else DEFAULT_HOST_NETWORK_MBPS
    field = HOST_FIELD_BY_RESOURCE[resource]
    if not field:
        return 0.0
    value = resources.get(field)
    if value is None:
        return 0.0
    return float(value)


def _resource_percent(limit: dict[str, Any], global_percent: int) -> int:
    if "percent" in limit:
        return int(limit["percent"])
    return global_percent


def effective_budget(resources: dict[str, Any], budget: dict[str, Any]) -> dict[str, float]:
    """Compute the effective Jarvis budget from a hardware snapshot and budget config."""
    limits = budget.get("limits") or {}
    global_percent = int(budget.get("global_percent", 50))
    result: dict[str, float] = {}
    for resource in RESOURCE_KEYS:
        host_total = _host_capacity(resources, resource)
        limit = limits.get(resource, {})
        percent = _resource_percent(limit, global_percent)
        amount = host_total * (percent / 100.0)
        if "absolute" in limit:
            amount = min(amount, float(limit["absolute"]))
        result[resource] = amount
    return result


def _claim_amount(claim: dict[str, Any], resource: str) -> float:
    field = CLAIM_FIELD_BY_RESOURCE[resource]
    value = claim.get(field)
    if value is None:
        return 0.0
    return float(value)


def aggregate_lease_claims(leases: list[dict[str, Any]]) -> dict[str, float]:
    totals = {resource: 0.0 for resource in RESOURCE_KEYS}
    for lease in leases:
        claim = lease.get("claim") if isinstance(lease.get("claim"), dict) else lease
        if not isinstance(claim, dict):
            continue
        for resource in RESOURCE_KEYS:
            totals[resource] += _claim_amount(claim, resource)
    return totals


def remaining_budget(
    resources: dict[str, Any],
    budget: dict[str, Any],
    active_leases: list[dict[str, Any]],
) -> dict[str, float]:
    """Effective budget minus active (non-expired) lease claims."""
    effective = effective_budget(resources, budget)
    used = aggregate_lease_claims(active_leases)
    return {resource: max(0.0, effective[resource] - used[resource]) for resource in RESOURCE_KEYS}


def _hard_cap_violations(
    resources: dict[str, Any],
    budget: dict[str, Any],
    active_leases: list[dict[str, Any]],
    new_claim: dict[str, Any],
) -> list[str]:
    limits = budget.get("limits") or {}
    effective = effective_budget(resources, budget)
    used = aggregate_lease_claims(active_leases)
    violations: list[str] = []
    for resource in RESOURCE_KEYS:
        limit = limits.get(resource, {})
        if normalize_cap(limit.get("cap", CAP_SOFT)) != CAP_HARD:
            continue
        proposed = used[resource] + _claim_amount(new_claim, resource)
        if proposed > effective[resource] + 1e-9:
            violations.append(resource)
    return violations


async def ensure_default_node_budget(node_id: str) -> NodeBudget | None:
    """Create a default Balanced / 50% budget when none exists yet."""
    now = _utcnow()
    async with SessionLocal() as session:
        node = await session.get(Node, node_id)
        if node is None:
            return None
        existing = await session.get(NodeBudget, node_id)
        if existing is not None:
            return existing
        defaults = default_budget_payload()
        record = NodeBudget(
            node_id=node_id,
            preset=defaults["preset"],
            mode=defaults["mode"],
            global_percent=defaults["global_percent"],
            limits_json=json.dumps(defaults["limits"]),
            updated_at=now,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


async def get_node_budget(node_id: str) -> dict[str, Any] | None:
    async with SessionLocal() as session:
        node = await session.get(Node, node_id)
        if node is None:
            return None
        row = await session.get(NodeBudget, node_id)
        if row is None:
            return None
        payload = budget_to_dict(row)
        resources = _parse_json_dict(node.resources_json)
        active = await _list_active_leases(session, node_id)
        payload["effective"] = effective_budget(resources, payload)
        payload["remaining"] = remaining_budget(resources, payload, active)
        return payload


async def set_node_budget(node_id: str, body: dict[str, Any]) -> dict[str, Any]:
    now = _utcnow()

    async with SessionLocal() as session:
        node = await session.get(Node, node_id)
        if node is None:
            raise LookupError("Node not found")
        row = await session.get(NodeBudget, node_id)
        existing = budget_to_dict(row) if row is not None else default_budget_payload()

        preset_raw = body.get("preset", existing["preset"])
        preset = validate_preset(preset_raw)
        mode = str(body.get("mode", existing.get("mode", BUDGET_MODE_STATIC))).strip().lower()
        if mode not in (BUDGET_MODE_STATIC, BUDGET_MODE_DYNAMIC):
            raise ValueError(f"Invalid budget mode: {body.get('mode')!r}")

        if "global_percent" in body and body["global_percent"] is not None:
            global_percent = validate_global_percent(body["global_percent"])
        elif preset != BUDGET_PRESET_CUSTOM:
            global_percent = PRESET_GLOBAL_PERCENT[preset]
        elif "global_percent" in existing:
            global_percent = validate_global_percent(existing["global_percent"])
        else:
            raise ValueError("global_percent is required for custom preset")

        if "limits" in body:
            limits = _normalize_limits(body.get("limits"))
        else:
            limits = _normalize_limits(existing.get("limits"))

        if row is None:
            row = NodeBudget(
                node_id=node_id,
                preset=preset,
                mode=mode,
                global_percent=global_percent,
                limits_json=json.dumps(limits),
                updated_at=now,
            )
            session.add(row)
        else:
            row.preset = preset
            row.mode = mode
            row.global_percent = global_percent
            row.limits_json = json.dumps(limits)
            row.updated_at = now
        await session.commit()
        await session.refresh(row)
        payload = budget_to_dict(row)
        resources = _parse_json_dict(node.resources_json)
        active = await _list_active_leases(session, node_id)
        payload["effective"] = effective_budget(resources, payload)
        payload["remaining"] = remaining_budget(resources, payload, active)
        return payload


async def _expire_due_leases(session, node_id: str, *, now: datetime | None = None) -> None:
    current = now or _utcnow()
    rows = (
        await session.execute(
            select(ResourceLease).where(
                ResourceLease.node_id == node_id,
                ResourceLease.status == LEASE_STATUS_ACTIVE,
                ResourceLease.expires_at <= current,
            )
        )
    ).scalars().all()
    for row in rows:
        row.status = LEASE_STATUS_EXPIRED
    if rows:
        await session.commit()


async def _list_active_leases(session, node_id: str, *, now: datetime | None = None) -> list[dict[str, Any]]:
    await _expire_due_leases(session, node_id, now=now)
    rows = (
        await session.execute(
            select(ResourceLease)
            .where(
                ResourceLease.node_id == node_id,
                ResourceLease.status == LEASE_STATUS_ACTIVE,
            )
            .order_by(ResourceLease.created_at.asc())
        )
    ).scalars().all()
    return [lease_to_dict(row) for row in rows]


async def list_node_leases(node_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        node = await session.get(Node, node_id)
        if node is None:
            return []
        await _expire_due_leases(session, node_id)
        rows = (
            await session.execute(
                select(ResourceLease)
                .where(ResourceLease.node_id == node_id)
                .order_by(ResourceLease.created_at.asc())
            )
        ).scalars().all()
        return [lease_to_dict(row) for row in rows]


async def would_exceed_hard_cap(node_id: str, claim: dict[str, Any]) -> list[str]:
    """Return resource keys that would violate HARD caps if claim were acquired."""
    if not isinstance(claim, dict) or not claim:
        raise ValueError("claim must be a non-empty object")

    async with SessionLocal() as session:
        node = await session.get(Node, node_id)
        if node is None:
            raise LookupError("Node not found")
        budget_row = await session.get(NodeBudget, node_id)
        if budget_row is None:
            raise LookupError("Node budget not found")
        budget = budget_to_dict(budget_row)
        resources = _parse_json_dict(node.resources_json)
        active = await _list_active_leases(session, node_id)
        return _hard_cap_violations(resources, budget, active, claim)


async def acquire_lease(
    node_id: str,
    claim: dict[str, Any],
    *,
    ttl_seconds: int | None = 300,
    expires_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(claim, dict) or not claim:
        raise ValueError("claim must be a non-empty object")

    current = now or _utcnow()
    if expires_at is None:
        ttl = 300 if ttl_seconds is None else int(ttl_seconds)
        if ttl <= 0:
            raise ValueError("ttl_seconds must be positive")
        expiry = current + timedelta(seconds=ttl)
    else:
        expiry = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        if expiry <= current:
            raise ValueError("expires_at must be in the future")

    async with SessionLocal() as session:
        node = await session.get(Node, node_id)
        if node is None:
            raise LookupError("Node not found")
        budget_row = await session.get(NodeBudget, node_id)
        if budget_row is None:
            raise LookupError("Node budget not found")
        budget = budget_to_dict(budget_row)
        resources = _parse_json_dict(node.resources_json)
        active = await _list_active_leases(session, node_id, now=current)
        violations = _hard_cap_violations(resources, budget, active, claim)
        if violations:
            raise ValueError(
                "Lease would exceed HARD cap for: " + ", ".join(sorted(violations))
            )

        lease_id = str(uuid.uuid4())
        row = ResourceLease(
            id=lease_id,
            node_id=node_id,
            claim_json=json.dumps(claim),
            status=LEASE_STATUS_ACTIVE,
            created_at=current,
            expires_at=expiry,
            released_at=None,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return lease_to_dict(row)


async def release_lease(node_id: str, lease_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or _utcnow()
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(ResourceLease).where(
                    ResourceLease.id == lease_id,
                    ResourceLease.node_id == node_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise LookupError("Lease not found")
        if row.status == LEASE_STATUS_ACTIVE:
            row.status = LEASE_STATUS_RELEASED
            row.released_at = current
            await session.commit()
            await session.refresh(row)
        return lease_to_dict(row)
