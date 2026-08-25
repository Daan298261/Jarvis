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
from .scoring import probe_node_warm_state, score_candidate


def _reject(reason: str, code: str) -> dict[str, Any]:
    return {"accepted": False, "reason": reason, "code": code}


def _accept(
    node: dict[str, Any],
    worker: dict[str, Any],
    *,
    lease: dict[str, Any] | None = None,
    reason: str,
    score: dict[str, Any] | None = None,
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
    if score is not None:
        payload["score"] = score
    return payload


def _matching_workers(
    workers: list[dict[str, Any]],
    worker_id: str | None,
    worker_kind: str | None,
) -> list[dict[str, Any]]:
    if not workers:
        return []
    if worker_id:
        return [worker for worker in workers if worker.get("id") == worker_id]
    if worker_kind:
        return [worker for worker in workers if worker.get("kind") == worker_kind]
    return list(workers)


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


def _parse_data_paths(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    return [str(item) for item in raw]


def _candidate_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    node = item["node"]
    worker = item["worker"]
    score = item["score"]
    return (
        -int(score.get("total") or 0),
        str(node.get("id") or ""),
        str(worker.get("id") or ""),
    )


async def _collect_eligible_candidates(
    request: dict[str, Any],
    *,
    capabilities: list[str],
    role: str | None,
    worker_id: str | None,
    worker_kind: str | None,
    claim: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    nodes = await list_nodes()
    if not nodes:
        return [], _reject("No eligible node available", "no_node")

    node_count = len(nodes)
    necessary = node_count <= 1
    local_nodes = [node for node in nodes if node.get("is_local")]
    candidates = local_nodes if local_nodes else nodes
    required = set(capabilities)

    eligible: list[dict[str, Any]] = []
    last_reject: dict[str, Any] | None = None

    for node in candidates:
        node_id = node["id"]

        if role is not None:
            policy = await get_node_role_policy(node_id, role)
            if policy is None:
                policy = DEFAULT_LOCALHOST_POLICY
            if not is_eligible_for_role(policy, necessary=necessary):
                last_reject = _reject(
                    f"Role {role} is DISABLED on node {node_id}",
                    "role_disabled",
                )
                continue

        if claim is not None:
            violations = await would_exceed_hard_cap(node_id, claim)
            if violations:
                last_reject = _reject(
                    "Lease would exceed HARD cap for: " + ", ".join(sorted(violations)),
                    "hard_cap",
                )
                continue

        node_caps = {cap.get("id") for cap in node.get("capabilities", [])}
        missing = required - node_caps
        if missing:
            last_reject = _reject(
                "Missing capabilities: " + ", ".join(sorted(missing)),
                "missing_capability",
            )
            continue

        workers = _matching_workers(node.get("workers", []), worker_id, worker_kind)
        if not workers:
            last_reject = _reject("No matching worker found on node", "no_worker")
            continue

        warm_state = probe_node_warm_state(node)
        for worker in workers:
            score = score_candidate(node, worker, request, warm_state)
            eligible.append(
                {
                    "node": node,
                    "worker": worker,
                    "warm_state": warm_state,
                    "score": score,
                }
            )

    if not eligible:
        return [], last_reject or _reject("No eligible node available", "no_node")

    return eligible, None


async def place_work(request: dict[str, Any]) -> dict[str, Any]:
    """Place work on the single-node swarm (localhost). Returns accept or reject payload."""
    capabilities = _parse_capabilities(request.get("capabilities"))
    if capabilities is None:
        return _reject("capabilities must be a list", "invalid_request")

    data_paths = _parse_data_paths(request.get("data_paths"))
    if request.get("data_paths") is not None and data_paths is None:
        return _reject("data_paths must be a list when provided", "invalid_request")

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

    eligible, reject = await _collect_eligible_candidates(
        request,
        capabilities=capabilities,
        role=role,
        worker_id=worker_id,
        worker_kind=worker_kind,
        claim=claim,
    )
    if reject is not None:
        return reject

    chosen = sorted(eligible, key=_candidate_sort_key)[0]
    node = chosen["node"]
    worker = chosen["worker"]
    score = chosen["score"]

    lease: dict[str, Any] | None = None
    if claim is not None:
        try:
            lease = await acquire_lease(node["id"], claim, ttl_seconds=ttl_seconds)
        except ValueError as exc:
            message = str(exc)
            if "HARD cap" in message:
                return _reject(message, "hard_cap")
            return _reject(message, "invalid_request")
        except LookupError as exc:
            return _reject(str(exc), "no_node")

    reason = "placed on localhost" if node.get("is_local") else f"placed on node {node['id']}"
    return _accept(
        node,
        worker,
        lease=lease,
        reason=reason,
        score=score,
    )
