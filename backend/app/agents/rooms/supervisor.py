"""Anzu supervisor for Agent Rooms (RFC-0174).

Owns task decomposition, concurrency budget, merge/synthesis, and termination.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .blackboard import Blackboard, BlackboardKind
from .protocol import sanitize_public_text


SUPERVISOR_ID = "anzu"


@dataclass(frozen=True)
class TaskNode:
    id: str
    title: str
    assignee: str | None = None
    depends_on: tuple[str, ...] = ()
    status: str = "pending"  # pending | running | done | cancelled | blocked
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "assignee": self.assignee,
            "depends_on": list(self.depends_on),
            "status": self.status,
            "rationale": self.rationale,
        }


@dataclass
class TaskGraph:
    nodes: dict[str, TaskNode] = field(default_factory=dict)

    def add(self, node: TaskNode) -> TaskNode:
        self.nodes[node.id] = node
        return node

    def update(self, task_id: str, **changes: Any) -> TaskNode:
        current = self.nodes[task_id]
        data = current.as_dict()
        data.update(changes)
        node = TaskNode(
            id=data["id"],
            title=data["title"],
            assignee=data.get("assignee"),
            depends_on=tuple(data.get("depends_on") or ()),
            status=str(data.get("status") or "pending"),
            rationale=str(data.get("rationale") or ""),
        )
        self.nodes[task_id] = node
        return node

    def as_dict(self) -> dict[str, Any]:
        return {"tasks": [n.as_dict() for n in self.nodes.values()]}


@dataclass(frozen=True)
class SynthesisResult:
    summary: str
    cited_artifact_ids: tuple[str, ...]
    cited_agents: tuple[str, ...]
    cited_decision_ids: tuple[str, ...]
    cited_citation_ids: tuple[str, ...]
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "cited_artifact_ids": list(self.cited_artifact_ids),
            "cited_agents": list(self.cited_agents),
            "cited_decision_ids": list(self.cited_decision_ids),
            "cited_citation_ids": list(self.cited_citation_ids),
            "rationale": self.rationale,
        }


class Supervisor:
    """Anzu-owned control plane for one room."""

    def __init__(
        self,
        *,
        concurrency_budget: int = 3,
        supervisor_id: str = SUPERVISOR_ID,
    ) -> None:
        self.supervisor_id = str(supervisor_id or SUPERVISOR_ID).strip().lower()
        self.concurrency_budget = max(1, int(concurrency_budget))
        self.graph = TaskGraph()

    def decompose(
        self,
        goal: str,
        specialists: list[str],
        *,
        max_tasks: int | None = None,
    ) -> list[TaskNode]:
        """Deterministic decomposition: one task per specialist (capped by budget)."""
        goal_text = sanitize_public_text(goal)
        if not goal_text:
            raise ValueError("goal is required")
        agents = [
            a.strip().lower()
            for a in specialists
            if a and a.strip().lower() != self.supervisor_id
        ]
        if not agents:
            raise ValueError("at least one specialist is required")
        cap = self.concurrency_budget if max_tasks is None else max(1, int(max_tasks))
        chosen = agents[: min(len(agents), cap)]
        nodes: list[TaskNode] = []
        for index, agent in enumerate(chosen):
            node = TaskNode(
                id=str(uuid.uuid4()),
                title=f"[{agent}] contribute to: {goal_text[:160]}",
                assignee=agent,
                depends_on=(),
                status="pending",
                rationale=f"supervisor assigned slice {index + 1}/{len(chosen)}",
            )
            self.graph.add(node)
            nodes.append(node)
        return nodes

    def set_concurrency_budget(self, budget: int) -> int:
        self.concurrency_budget = max(1, int(budget))
        return self.concurrency_budget

    def running_count(self) -> int:
        return sum(1 for n in self.graph.nodes.values() if n.status == "running")

    def can_start(self, task_id: str) -> bool:
        node = self.graph.nodes[task_id]
        if node.status not in {"pending", "blocked"}:
            return False
        if self.running_count() >= self.concurrency_budget:
            return False
        for dep in node.depends_on:
            dep_node = self.graph.nodes.get(dep)
            if dep_node is None or dep_node.status != "done":
                return False
        return True

    def start_task(self, task_id: str) -> TaskNode:
        if not self.can_start(task_id):
            raise RuntimeError(f"cannot start task {task_id} under concurrency/deps")
        return self.graph.update(task_id, status="running")

    def complete_task(self, task_id: str) -> TaskNode:
        return self.graph.update(task_id, status="done")

    def cancel_task(self, task_id: str, *, rationale: str = "") -> TaskNode:
        return self.graph.update(
            task_id,
            status="cancelled",
            rationale=sanitize_public_text(rationale) or "cancelled",
        )

    def synthesize(self, blackboard: Blackboard, *, goal: str = "") -> SynthesisResult:
        """Merge blackboard state into a FINAL-ready synthesis with citations."""
        artifacts = blackboard.list(kind=BlackboardKind.ARTIFACT)
        decisions = blackboard.list(kind=BlackboardKind.DECISION)
        citations = blackboard.list(kind=BlackboardKind.CITATION)
        facts = blackboard.list(kind=BlackboardKind.FACT)
        agents = sorted({e.author for e in artifacts + decisions + citations + facts if e.author != self.supervisor_id})
        parts: list[str] = []
        if goal:
            parts.append(f"Goal: {sanitize_public_text(goal)}")
        if facts:
            parts.append("Facts: " + "; ".join(f.content[:120] for f in facts[:8]))
        if decisions:
            parts.append("Decisions: " + "; ".join(f.content[:120] for f in decisions[:8]))
        if artifacts:
            parts.append("Artifacts: " + "; ".join(f.key for f in artifacts[:8]))
        if not parts:
            parts.append("No shared blackboard contributions yet.")
        summary = sanitize_public_text(" | ".join(parts))
        return SynthesisResult(
            summary=summary,
            cited_artifact_ids=tuple(a.id for a in artifacts),
            cited_agents=tuple(agents),
            cited_decision_ids=tuple(d.id for d in decisions),
            cited_citation_ids=tuple(c.id for c in citations),
            rationale="supervisor merge of approved blackboard state",
        )
