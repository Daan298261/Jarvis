from __future__ import annotations

from typing import Any

IDLE_STATUSES = {"idle", "ready", "online"}
BUSY_STATUSES = {"busy", "running", "working"}
JUNIOR_CLASSES = {"junior_worker", "junior", "helper"}
SENIOR_CLASSES = {"senior_worker", "senior", "leader", "orchestrator"}

IDLE_BONUS = 80
JUNIOR_BONUS = 60
BUSY_PENALTY = 120
SENIOR_PENALTY = 40
LOW_UTILIZATION_BONUS = 30


def _node_class(node: dict[str, Any]) -> str:
    return str(node.get("class") or node.get("node_class") or "senior_worker").strip().lower()


def _node_status(node: dict[str, Any]) -> str:
    return str(node.get("status") or "unknown").strip().lower()


def _utilization(node: dict[str, Any]) -> float:
    resources = node.get("resources")
    if not isinstance(resources, dict):
        return 0.0
    raw = resources.get("utilization")
    if isinstance(raw, (int, float)):
        return float(raw)
    cpu = resources.get("cpu_percent")
    if isinstance(cpu, (int, float)):
        return float(cpu) / 100.0
    return 0.0


def score_consolidation_node(node: dict[str, Any]) -> dict[str, Any]:
    """Prefer idle or junior nodes for low-priority memory consolidation."""
    status = _node_status(node)
    node_class = _node_class(node)
    utilization = _utilization(node)

    score = 0
    reasons: list[str] = []

    if status in IDLE_STATUSES:
        score += IDLE_BONUS
        reasons.append(f"idle status ({status})")
    elif status in BUSY_STATUSES:
        score -= BUSY_PENALTY
        reasons.append(f"busy status ({status})")

    if node_class in JUNIOR_CLASSES:
        score += JUNIOR_BONUS
        reasons.append(f"junior class ({node_class})")
    elif node_class in SENIOR_CLASSES:
        score -= SENIOR_PENALTY
        reasons.append(f"senior class ({node_class})")

    if utilization <= 0.25:
        score += LOW_UTILIZATION_BONUS
        reasons.append("low utilization")
    elif utilization >= 0.75:
        score -= LOW_UTILIZATION_BONUS
        reasons.append("high utilization")

    return {
        "node_id": node.get("id"),
        "hostname": node.get("hostname") or "",
        "score": score,
        "status": status,
        "class": node_class,
        "utilization": utilization,
        "reasons": reasons,
        "preferred": score >= 0,
    }


def rank_nodes_for_consolidation(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [score_consolidation_node(node) for node in nodes]
    return sorted(scored, key=lambda item: item["score"], reverse=True)
