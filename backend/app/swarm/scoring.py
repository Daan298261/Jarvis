from __future__ import annotations

from pathlib import Path
from typing import Any

WARM_WORKER_STATUS = "ready"
WARM_BONUS = 100
LOCALITY_BONUS_PER_PATH = 50

_LOCAL_LLM_ID = "local-llm"


def _is_worker_warm(worker: dict[str, Any], *, node_is_local: bool) -> bool:
    worker_id = str(worker.get("id") or "")
    status = str(worker.get("status") or "").strip().lower()

    if worker_id == _LOCAL_LLM_ID and node_is_local:
        from ..inference.manager import MANAGER

        return bool(MANAGER.state.loaded)

    return status == WARM_WORKER_STATUS


def probe_node_warm_state(node: dict[str, Any]) -> dict[str, Any]:
    """Return warm workers and loaded models for a node."""
    node_is_local = bool(node.get("is_local"))
    warm_workers: list[str] = []
    loaded_models: list[str] = []

    for worker in node.get("workers", []):
        if not isinstance(worker, dict):
            continue
        worker_id = str(worker.get("id") or "").strip()
        if not worker_id:
            continue
        if _is_worker_warm(worker, node_is_local=node_is_local):
            warm_workers.append(worker_id)
            if worker_id == _LOCAL_LLM_ID:
                from ..inference.manager import MANAGER

                if MANAGER.state.loaded:
                    model_name = (
                        str(MANAGER.state.alias or MANAGER.state.profile or "local-llm").strip()
                        or "local-llm"
                    )
                    loaded_models.append(model_name)

    return {
        "node_id": node.get("id"),
        "warm_workers": sorted(warm_workers),
        "loaded_models": sorted(set(loaded_models)),
    }


def _paths_exist_locally(data_paths: list[str]) -> list[str]:
    present: list[str] = []
    for raw in data_paths:
        path = str(raw).strip()
        if not path:
            continue
        if Path(path).exists():
            present.append(path)
    return present


def paths_present_on_node(node: dict[str, Any], data_paths: list[str]) -> list[str]:
    """Return data_paths that exist on the given node."""
    if not data_paths:
        return []

    if node.get("is_local"):
        return _paths_exist_locally(data_paths)

    advertised = node.get("data_paths_present")
    if isinstance(advertised, list):
        advertised_set = {str(item) for item in advertised}
        return [path for path in data_paths if str(path) in advertised_set]

    return []


def score_candidate(
    node: dict[str, Any],
    worker: dict[str, Any],
    request: dict[str, Any],
    warm_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score an eligible (node, worker) pair for warm-state and data-locality."""
    if warm_state is None:
        warm_state = probe_node_warm_state(node)

    warm_bonus = 0
    locality_bonus = 0
    reasons: list[str] = []

    worker_id = str(worker.get("id") or "")
    worker_kind = str(worker.get("kind") or "")
    warm_workers = set(warm_state.get("warm_workers") or [])
    loaded_models = set(warm_state.get("loaded_models") or [])

    requested_worker_id = request.get("worker_id")
    if requested_worker_id is not None:
        requested_worker_id = str(requested_worker_id).strip() or None
    requested_worker_kind = request.get("worker_kind")
    if requested_worker_kind is not None:
        requested_worker_kind = str(requested_worker_kind).strip() or None
    prefer_model = request.get("prefer_model")
    if prefer_model is not None:
        prefer_model = str(prefer_model).strip() or None

    warm_match = False
    if requested_worker_id and worker_id == requested_worker_id and worker_id in warm_workers:
        warm_match = True
    elif requested_worker_kind and worker_kind == requested_worker_kind and worker_id in warm_workers:
        warm_match = True
    elif not requested_worker_id and not requested_worker_kind:
        if worker_id in warm_workers:
            warm_match = True

    if prefer_model and worker_id == _LOCAL_LLM_ID:
        if prefer_model in loaded_models or (worker_id in warm_workers and not loaded_models):
            warm_match = True

    if warm_match:
        warm_bonus = WARM_BONUS
        reasons.append(f"warm worker {worker_id}")

    data_paths = request.get("data_paths")
    parsed_paths: list[str] = []
    if isinstance(data_paths, list):
        parsed_paths = [str(item) for item in data_paths if str(item).strip()]

    if parsed_paths:
        present = paths_present_on_node(node, parsed_paths)
        if present:
            locality_bonus = LOCALITY_BONUS_PER_PATH * len(present)
            reasons.append(f"local data: {len(present)}/{len(parsed_paths)} path(s)")

    total = warm_bonus + locality_bonus
    return {
        "total": total,
        "warm_bonus": warm_bonus,
        "locality_bonus": locality_bonus,
        "reasons": reasons,
    }
