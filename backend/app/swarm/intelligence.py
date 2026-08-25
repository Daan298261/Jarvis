from __future__ import annotations

from typing import Any

from ..agent.planning import classify_task
from .placement import place_work
from .workers import worker_catalog

# Deterministic task-class → capability / worker-kind mapping (no LLM, no node selection).
_INTELLIGENCE_PROFILES: dict[str, dict[str, Any]] = {
    "filesystem": {
        "capabilities": ["filesystem", "tool_execution"],
        "worker_kind": "worker",
    },
    "shell": {
        "capabilities": ["tool_execution"],
        "worker_kind": "worker",
    },
    "system administration": {
        "capabilities": ["tool_execution"],
        "worker_kind": "worker",
    },
    "software engineering": {
        "capabilities": ["coding", "tool_execution"],
        "worker_kind": "coding",
    },
    "research": {
        "capabilities": ["browser", "llm_inference"],
        "worker_kind": "inference",
        "model": "local-llm",
    },
    "browser automation": {
        "capabilities": ["browser"],
        "worker_kind": "worker",
        "worker_id": "browser-use",
    },
    "windows gui": {
        "capabilities": ["desktop_control", "tool_execution"],
        "worker_kind": "worker",
    },
    "office": {
        "capabilities": ["tool_execution"],
        "worker_kind": "worker",
    },
    "document processing": {
        "capabilities": ["tool_execution"],
        "worker_kind": "worker",
    },
    "data processing": {
        "capabilities": ["tool_execution"],
        "worker_kind": "worker",
    },
    "multimodal": {
        "capabilities": ["llm_inference", "gpu"],
        "worker_kind": "inference",
        "model": "local-llm",
    },
    "mixed": {
        "capabilities": ["tool_execution", "llm_inference"],
        "worker_kind": "worker",
    },
    "long-horizon autonomous": {
        "capabilities": ["coding", "tool_execution", "llm_inference"],
        "worker_kind": "coding",
        "model": "local-llm",
    },
}

_DEFAULT_PROFILE: dict[str, Any] = {
    "capabilities": ["tool_execution", "llm_inference"],
    "worker_kind": "worker",
}


def _resolve_worker_id(profile: dict[str, Any], workers: list[dict[str, Any]]) -> str | None:
    explicit = profile.get("worker_id")
    if explicit:
        return str(explicit)
    kind = profile.get("worker_kind")
    if not kind:
        return None
    matches = [worker for worker in workers if worker.get("kind") == kind]
    if not matches:
        return None
    return sorted(matches, key=lambda item: item.get("id") or "")[0]["id"]


def select_intelligence(
    prompt: str,
    *,
    task_class: str | None = None,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    """Choose what to run (worker/model/capabilities) without selecting a Node."""
    del execution_mode  # reserved for future policy hints; selection stays deterministic today.

    resolved_class = (task_class or "").strip().lower() or None
    if not resolved_class:
        resolved_class = classify_task(prompt)

    profile = _INTELLIGENCE_PROFILES.get(resolved_class, _DEFAULT_PROFILE)
    capabilities = list(profile["capabilities"])
    worker_kind = str(profile["worker_kind"])

    worker_id = _resolve_worker_id(profile, worker_catalog())

    result: dict[str, Any] = {
        "task_class": resolved_class,
        "worker_kind": worker_kind,
        "capabilities": capabilities,
    }
    if worker_id:
        result["worker_id"] = worker_id
    model = profile.get("model")
    if model:
        result["model"] = str(model)
    return result


async def dispatch_work(
    prompt: str,
    *,
    task_class: str | None = None,
    execution_mode: str | None = None,
    role: str | None = None,
    claim: dict | None = None,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """Compose intelligence selection with physical placement as separate decisions."""
    intelligence = select_intelligence(
        prompt,
        task_class=task_class,
        execution_mode=execution_mode,
    )

    placement_request: dict[str, Any] = {
        "capabilities": intelligence["capabilities"],
    }
    if intelligence.get("worker_id"):
        placement_request["worker_id"] = intelligence["worker_id"]
    elif intelligence.get("worker_kind") in {"coding", "inference"}:
        placement_request["worker_kind"] = intelligence["worker_kind"]
    if intelligence.get("model"):
        placement_request["model"] = intelligence["model"]
    if role is not None:
        placement_request["role"] = role
    if claim is not None:
        placement_request["claim"] = claim
    if ttl_seconds is not None:
        placement_request["ttl_seconds"] = ttl_seconds

    placement = await place_work(placement_request)

    return {
        "intelligence": intelligence,
        "placement": placement,
    }
