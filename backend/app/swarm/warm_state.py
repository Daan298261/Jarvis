"""Model/worker warm-state and data-locality signals for placement scoring.

Hard constraints (DISABLED, hard caps, missing capabilities) still win.
These signals only rank eligible Nodes so the scheduler prefers a loaded
model, a ready worker, and data that is already on the machine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

WARM_MODEL_BONUS = 40
RELOAD_PENALTY = 35
WARM_WORKER_BONUS = 25
COLD_WORKER_PENALTY = 10
DATA_LOCALITY_BONUS = 30
DATA_REMOTE_PENALTY = 15
LOCAL_NODE_BONUS = 5

READY_WORKER_STATUSES = frozenset({"ready", "loaded", "online", "available"})
COLD_WORKER_STATUSES = frozenset(
    {"not_loaded", "error", "missing", "unavailable", "not_connected", "not_configured", "not_integrated"}
)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def localhost_warm_state(*, workers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Live warm-state for this process's machine (model + local data roots)."""
    from ..config import load_settings
    from ..inference.manager import MANAGER

    settings = load_settings()
    state = MANAGER.state
    data_roots = [str(item) for item in (settings.allowed_directories or []) if str(item).strip()]
    warm_workers: list[str] = []
    if workers:
        warm_workers = [
            str(item.get("id") or "")
            for item in workers
            if str(item.get("id") or "") and _norm(item.get("status")) in READY_WORKER_STATUSES
        ]
    model_id = state.alias or state.family or state.profile
    return {
        "loaded": bool(state.loaded),
        "loading": bool(state.loading),
        "profile": state.profile or "",
        "model_id": model_id or "",
        "model_path": state.model_path or "",
        "quant": state.quant or "",
        "family": state.family or "",
        "vision_loaded": bool(state.vision_loaded),
        "data_roots": data_roots,
        "warm_workers": warm_workers,
        "local_files": True,
    }


def path_is_local(path: str, roots: list[str]) -> bool:
    raw = str(path or "").strip()
    if not raw or not roots:
        return False
    try:
        resolved = Path(raw).expanduser().resolve()
    except Exception:
        return False
    for root in roots:
        try:
            root_resolved = Path(str(root)).expanduser().resolve()
        except Exception:
            continue
        try:
            resolved.relative_to(root_resolved)
            return True
        except ValueError:
            continue
    return False


def model_is_warm(requested: str, warm: dict[str, Any]) -> bool:
    req = _norm(requested)
    if not req or not warm.get("loaded"):
        return False
    if req in {"local-llm", "local", "localhost"}:
        return True
    tokens = [
        warm.get("profile"),
        warm.get("model_id"),
        warm.get("family"),
        warm.get("quant"),
        Path(str(warm.get("model_path") or "")).stem,
    ]
    normalized = [_norm(token) for token in tokens if _norm(token)]
    if req in normalized:
        return True
    haystack = " ".join(normalized)
    return req in haystack


def attach_warm_state(node: dict[str, Any], warm: dict[str, Any] | None = None) -> dict[str, Any]:
    if not node.get("is_local"):
        return node
    payload = dict(node)
    live = warm if warm is not None else localhost_warm_state(workers=node.get("workers") or [])
    payload["warm_state"] = live
    return payload


def score_node(
    node: dict[str, Any],
    request: dict[str, Any],
    *,
    warm: dict[str, Any] | None = None,
    worker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a numeric score plus explainable signals. Never overrides hard policy."""
    score = 0
    signals: dict[str, Any] = {
        "warm_model": False,
        "would_reload_model": False,
        "warm_worker": False,
        "cold_worker": False,
        "data_locality": False,
        "matched_paths": [],
        "unmatched_paths": [],
        "is_local": bool(node.get("is_local")),
    }
    live = warm
    if live is None and node.get("is_local"):
        live = node.get("warm_state") or localhost_warm_state(workers=node.get("workers") or [])
    live = live or {}

    if node.get("is_local"):
        score += LOCAL_NODE_BONUS

    requested_model = str(request.get("model") or "").strip()
    if requested_model:
        if node.get("is_local") and model_is_warm(requested_model, live):
            score += WARM_MODEL_BONUS
            signals["warm_model"] = True
        elif node.get("is_local") and live.get("loaded"):
            score -= RELOAD_PENALTY
            signals["would_reload_model"] = True

    selected = worker
    if selected is None:
        worker_id = str(request.get("worker_id") or "").strip()
        if worker_id:
            for item in node.get("workers") or []:
                if item.get("id") == worker_id:
                    selected = item
                    break
    if selected is not None:
        status = _norm(selected.get("status"))
        if status in READY_WORKER_STATUSES:
            score += WARM_WORKER_BONUS
            signals["warm_worker"] = True
        elif status in COLD_WORKER_STATUSES:
            score -= COLD_WORKER_PENALTY
            signals["cold_worker"] = True

    paths = request.get("paths") or []
    if not isinstance(paths, list):
        paths = []
    roots = list(live.get("data_roots") or []) if node.get("is_local") else []
    matched: list[str] = []
    unmatched: list[str] = []
    for raw in paths:
        path = str(raw or "").strip()
        if not path:
            continue
        if node.get("is_local") and path_is_local(path, roots):
            matched.append(path)
        else:
            unmatched.append(path)
    signals["matched_paths"] = matched
    signals["unmatched_paths"] = unmatched
    if matched or unmatched:
        if matched and not unmatched:
            score += DATA_LOCALITY_BONUS
            signals["data_locality"] = True
        elif unmatched:
            score -= DATA_REMOTE_PENALTY

    return {"score": score, "signals": signals}
