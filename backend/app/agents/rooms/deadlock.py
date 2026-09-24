"""Deadlock / loop / stall detection for Agent Rooms (RFC-0174).

Detection covers:
- repeated message cycles
- mutual waits (BLOCKED pairs)
- duplicate work assignments
- stalled dependencies

Resolution order (deterministic):
1. Apply deadlock rules
2. Supervisor intervention
3. Owner escalation
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from .protocol import MessageKind, RoomMessage, message_fingerprint


class DeadlockIssueKind(str, Enum):
    CYCLE = "cycle"
    MUTUAL_WAIT = "mutual_wait"
    DUPLICATE_WORK = "duplicate_work"
    STALL = "stalled_dependency"


class ResolutionAction(str, Enum):
    APPLY_RULE = "apply_rule"
    SUPERVISOR_INTERVENE = "supervisor_intervene"
    OWNER_ESCALATE = "owner_escalate"
    TERMINATE = "terminate"


@dataclass(frozen=True)
class DeadlockIssue:
    kind: DeadlockIssueKind
    agents: tuple[str, ...]
    detail: str
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "agents": list(self.agents),
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class DeadlockResolution:
    action: ResolutionAction
    issue: DeadlockIssue
    rationale: str
    terminate: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "issue": self.issue.as_dict(),
            "rationale": self.rationale,
            "terminate": self.terminate,
        }


@dataclass
class DeadlockConfig:
    cycle_repeat_threshold: int = 3
    stall_blocked_threshold: int = 3
    max_issues_before_escalate: int = 2
    max_interventions_before_escalate: int = 2


@dataclass
class DeadlockMonitor:
    """Stateful detector + deterministic resolver for one room."""

    config: DeadlockConfig = field(default_factory=DeadlockConfig)
    _fingerprints: deque[str] = field(default_factory=lambda: deque(maxlen=128))
    _blocked_on: dict[str, str] = field(default_factory=dict)
    _task_owners: dict[str, str] = field(default_factory=dict)
    _issue_counts: Counter[str] = field(default_factory=Counter)
    _interventions: int = 0
    _escalated: bool = False
    _terminated: bool = False

    def observe(self, message: RoomMessage) -> list[DeadlockIssue]:
        """Ingest a message and return newly detected issues (may be empty)."""
        issues: list[DeadlockIssue] = []
        fp = message_fingerprint(message)
        self._fingerprints.append(fp)

        # Cycle: same fingerprint repeats beyond threshold.
        counts = Counter(self._fingerprints)
        if counts[fp] >= self.config.cycle_repeat_threshold:
            issues.append(
                DeadlockIssue(
                    kind=DeadlockIssueKind.CYCLE,
                    agents=tuple(sorted({message.from_agent, message.to_agent or message.from_agent})),
                    detail=f"repeated message cycle fingerprint seen {counts[fp]} times",
                    evidence=(fp,),
                )
            )

        # Mutual wait tracking via BLOCKED.
        if message.kind == MessageKind.BLOCKED and message.to_agent:
            self._blocked_on[message.from_agent] = message.to_agent
            other = self._blocked_on.get(message.to_agent)
            if other == message.from_agent:
                pair = tuple(sorted((message.from_agent, message.to_agent)))
                issues.append(
                    DeadlockIssue(
                        kind=DeadlockIssueKind.MUTUAL_WAIT,
                        agents=pair,
                        detail=f"mutual wait between {pair[0]} and {pair[1]}",
                        evidence=(f"{pair[0]}->{pair[1]}", f"{pair[1]}->{pair[0]}"),
                    )
                )
        elif message.kind in {MessageKind.RESULT, MessageKind.HANDOFF, MessageKind.FINAL}:
            self._blocked_on.pop(message.from_agent, None)

        # Duplicate work: same task_id claimed by different agents via REQUEST.
        if message.kind == MessageKind.REQUEST and message.task_id:
            owner = self._task_owners.get(message.task_id)
            if owner and owner != message.from_agent and message.to_agent != owner:
                # Two specialists both REQUEST'd for the same task.
                if message.from_agent != owner:
                    issues.append(
                        DeadlockIssue(
                            kind=DeadlockIssueKind.DUPLICATE_WORK,
                            agents=tuple(sorted({owner, message.from_agent})),
                            detail=f"duplicate work on task {message.task_id}",
                            evidence=(message.task_id, owner, message.from_agent),
                        )
                    )
            else:
                # First assignee wins; HANDOFF can reassign later.
                if message.to_agent:
                    self._task_owners[message.task_id] = message.to_agent
                else:
                    self._task_owners[message.task_id] = message.from_agent

        if message.kind == MessageKind.HANDOFF and message.task_id and message.to_agent:
            self._task_owners[message.task_id] = message.to_agent

        # Stall: agent remains BLOCKED without progress for N blocked messages.
        if message.kind == MessageKind.BLOCKED:
            blocked_msgs = [
                m_fp
                for m_fp in self._fingerprints
                if m_fp.startswith("BLOCKED|") and message.from_agent in m_fp
            ]
            if len(blocked_msgs) >= self.config.stall_blocked_threshold:
                issues.append(
                    DeadlockIssue(
                        kind=DeadlockIssueKind.STALL,
                        agents=(message.from_agent,),
                        detail=f"stalled dependency: {message.from_agent} blocked without progress",
                        evidence=tuple(blocked_msgs[-3:]),
                    )
                )

        return self._dedupe_issues(issues)

    def _dedupe_issues(self, issues: Iterable[DeadlockIssue]) -> list[DeadlockIssue]:
        seen: set[tuple[str, tuple[str, ...], str]] = set()
        out: list[DeadlockIssue] = []
        for issue in issues:
            key = (issue.kind.value, issue.agents, issue.detail)
            if key in seen:
                continue
            seen.add(key)
            out.append(issue)
        return out

    def resolve(self, issue: DeadlockIssue) -> DeadlockResolution:
        """Deterministic resolution ladder for one issue."""
        if self._terminated:
            return DeadlockResolution(
                action=ResolutionAction.TERMINATE,
                issue=issue,
                rationale="room already terminated",
                terminate=True,
            )
        if self._escalated:
            return DeadlockResolution(
                action=ResolutionAction.OWNER_ESCALATE,
                issue=issue,
                rationale="owner escalation already active",
                terminate=True,
            )

        self._issue_counts[issue.kind.value] += 1
        total_issues = sum(self._issue_counts.values())

        # Step 1: apply deterministic rule once per kind.
        if self._issue_counts[issue.kind.value] == 1:
            return DeadlockResolution(
                action=ResolutionAction.APPLY_RULE,
                issue=issue,
                rationale=self._rule_rationale(issue),
                terminate=False,
            )

        # Step 2: supervisor intervention.
        if self._interventions < self.config.max_interventions_before_escalate:
            self._interventions += 1
            return DeadlockResolution(
                action=ResolutionAction.SUPERVISOR_INTERVENE,
                issue=issue,
                rationale=f"supervisor intervention #{self._interventions} for {issue.kind.value}",
                terminate=False,
            )

        # Step 3: owner escalation + terminate pathological collaboration.
        self._escalated = True
        self._terminated = True
        return DeadlockResolution(
            action=ResolutionAction.OWNER_ESCALATE,
            issue=issue,
            rationale=(
                f"escalating to owner after {total_issues} issues "
                f"and {self._interventions} interventions"
            ),
            terminate=True,
        )

    def _rule_rationale(self, issue: DeadlockIssue) -> str:
        if issue.kind == DeadlockIssueKind.CYCLE:
            return "break cycle: drop repeated REQUEST/QUESTION pair; keep latest RESULT"
        if issue.kind == DeadlockIssueKind.MUTUAL_WAIT:
            # Lexicographically lower agent yields.
            yielder = min(issue.agents) if issue.agents else "?"
            return f"break mutual wait: {yielder} yields and clears BLOCKED"
        if issue.kind == DeadlockIssueKind.DUPLICATE_WORK:
            keeper = issue.evidence[1] if len(issue.evidence) > 1 else (issue.agents[0] if issue.agents else "?")
            return f"cancel duplicate: keep first owner {keeper}"
        if issue.kind == DeadlockIssueKind.STALL:
            return "unstick stall: supervisor reassigns or cancels blocked task"
        return "apply deadlock rule"

    def apply_rule_side_effects(self, issue: DeadlockIssue) -> dict[str, Any]:
        """Mutate wait/task maps according to the deterministic rule."""
        effects: dict[str, Any] = {"cleared_blocks": [], "cancelled_tasks": []}
        if issue.kind == DeadlockIssueKind.MUTUAL_WAIT and len(issue.agents) >= 2:
            yielder = min(issue.agents)
            self._blocked_on.pop(yielder, None)
            effects["cleared_blocks"].append(yielder)
        elif issue.kind == DeadlockIssueKind.DUPLICATE_WORK and len(issue.evidence) >= 3:
            task_id, keeper, duplicate = issue.evidence[0], issue.evidence[1], issue.evidence[2]
            self._task_owners[task_id] = keeper
            effects["cancelled_tasks"].append({"task_id": task_id, "cancelled_agent": duplicate})
        elif issue.kind == DeadlockIssueKind.STALL and issue.agents:
            self._blocked_on.pop(issue.agents[0], None)
            effects["cleared_blocks"].append(issue.agents[0])
        elif issue.kind == DeadlockIssueKind.CYCLE:
            # Clear recent fingerprint spam so the room can continue once.
            self._fingerprints.clear()
            effects["cleared_fingerprints"] = True
        return effects

    def mark_terminated(self) -> None:
        self._terminated = True

    @property
    def terminated(self) -> bool:
        return self._terminated

    @property
    def escalated(self) -> bool:
        return self._escalated

    def waiting_graph(self) -> dict[str, str]:
        return dict(self._blocked_on)
