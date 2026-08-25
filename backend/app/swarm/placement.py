from __future__ import annotations

from typing import Any

from .budgets import acquire_lease, would_exceed_hard_cap
from .nodes import list_nodes
from .roles import (
    DEFAULT_LOCALHOST_POLICY,
    SWARM_ROLES,
    get_node_role_policy,
    is_eligible_for_role,
)


def _reject(reason: str, code: str) -> dict[str, Any]:
    return {"accepted": False, "reason": reason, "code": code}


def _accept(
    node: dict[str, Any],
    worker: dict[str, Any],
    *,
    lease: dict[str, Any] | None = None,
    reason: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "accepted": True,
        "node_id": node["id"],
        "hostname": node.get("hostname") or "",
        "worker": worker,
        "reason": reason,
    }
    if lease is not None:
        payload["lease"] = lease
    return payload


def _select_worker(
    workers: list[dict[str, Any]],
    worker_id: str | None,
    worker_kind: str | None,
) -> dict[str, Any] | None:
    if not workers:
        return None
    if worker_id:
        for worker in workers:
            if worker.get("id") == worker_id:
                return worker
        return None
    if worker_kind:
        matches = [worker for worker in workers if worker.get("kind") == worker_kind]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.get("id") or "")[0]
    return sorted(workers, key=lambda item: item.get("id") or "")[0]


def _parse_capabilities(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    return [str(item) for item in raw]


def _parse_role(raw: Any) -> str | None:
    if raw is None:
        return None
    normalized = str(raw).strip().lower()
    if not normalized:
        return None
    return normalized


async def place_work(request: dict[str, Any]) -> dict[str, Any]:
    """Place work on the single-node swarm (localhost). Returns accept or reject payload."""
    capabilities = _parse_capabilities(request.get("capabilities"))
    if capabilities is None:
        return _reject("capabilities must be a list", "invalid_request")

    role = _parse_role(request.get("role"))
    if role is not None and role not in SWARM_ROLES:
        return _reject(f"Unknown swarm role: {role!r}", "invalid_role")

    worker_id = request.get("worker_id")
    if worker_id is not None:
        worker_id = str(worker_id).strip() or None
    worker_kind = request.get("worker_kind")
    if worker_kind is not None:
        worker_kind = str(worker_kind).strip() or None

    claim = request.get("claim")
    if claim is not None and (not isinstance(claim, dict) or not claim):
        return _reject("claim must be a non-empty object when provided", "invalid_request")

    ttl_seconds = request.get("ttl_seconds")

    nodes = await list_nodes()
    if not nodes:
        return _reject("No eligible node available", "no_node")

    node_count = len(nodes)
    necessary = node_count <= 1
    local_nodes = [node for node in nodes if node.get("is_local")]
    candidates = local_nodes if local_nodes else nodes

    for node in candidates:
        node_id = node["id"]

        if role is not None:
            policy = await get_node_role_policy(node_id, role)
            if policy is None:
                policy = DEFAULT_LOCALHOST_POLICY
            if not is_eligible_for_role(policy, necessary=necessary):
                return _reject(
                    f"Role {role} is DISABLED on node {node_id}",
                    "role_disabled",
                )

        if claim is not None:
            violations = await would_exceed_hard_cap(node_id, claim)
            if violations:
                return _reject(
                    "Lease would exceed HARD cap for: " + ", ".join(sorted(violations)),
                    "hard_cap",
                )

        node_caps = {cap.get("id") for cap in node.get("capabilities", [])}
        required = set(capabilities)
        missing = required - node_caps
        if missing:
            return _reject(
                "Missing capabilities: " + ", ".join(sorted(missing)),
                "missing_capability",
            )

        worker = _select_worker(node.get("workers", []), worker_id, worker_kind)
        if worker is None:
            return _reject("No matching worker found on node", "no_worker")

        lease: dict[str, Any] | None = None
        if claim is not None:
            try:
                lease = await acquire_lease(node_id, claim, ttl_seconds=ttl_seconds)
            except ValueError as exc:
                message = str(exc)
                if "HARD cap" in message:
                    return _reject(message, "hard_cap")
                return _reject(message, "invalid_request")
            except LookupError as exc:
                return _reject(str(exc), "no_node")

        return _accept(
            node,
            worker,
            lease=lease,
            reason="placed on localhost",
        )

    return _reject("No eligible node available", "no_node")
