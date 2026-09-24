"""Agent Room session: participants, protocol, blackboard, deadlock, governor.

Public control surface for RFC-0174. Later portal/websocket wiring should call
these APIs rather than reaching into internals.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .audit import RoomAuditLog
from .blackboard import Blackboard, BlackboardBoundError, BlackboardKind
from .deadlock import DeadlockMonitor, DeadlockResolution, ResolutionAction
from .governor import GovernorDenied, ResourceBudget, ResourceGovernor, build_budget
from .history import PrivateHistoryStore
from .protocol import MessageKind, RoomMessage, build_message, parse_mentions
from .supervisor import SUPERVISOR_ID, Supervisor, SynthesisResult, TaskNode


class RoomError(Exception):
    def __init__(self, message: str, code: str = "room_error") -> None:
        super().__init__(message)
        self.code = code


class RoomTerminated(RoomError):
    def __init__(self, message: str = "room is terminated") -> None:
        super().__init__(message, code="room_terminated")


@dataclass
class Participant:
    agent_id: str
    role: str  # supervisor | specialist
    model: str = ""
    provider: str = "local"  # local | cloud

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "model": self.model,
            "provider": self.provider,
        }


@dataclass
class AgentRoom:
    """Owner-visible multi-agent collaboration session."""

    id: str
    goal: str
    participants: dict[str, Participant] = field(default_factory=dict)
    messages: list[RoomMessage] = field(default_factory=list)
    blackboard: Blackboard = field(default_factory=Blackboard)
    history: PrivateHistoryStore = field(default_factory=PrivateHistoryStore)
    governor: ResourceGovernor = field(default_factory=ResourceGovernor)
    supervisor: Supervisor = field(default_factory=Supervisor)
    deadlock: DeadlockMonitor = field(default_factory=DeadlockMonitor)
    audit: RoomAuditLog = field(default_factory=RoomAuditLog)
    status: str = "open"  # open | terminated | escalated
    synthesis: SynthesisResult | None = None
    active_leases: dict[str, str] = field(default_factory=dict)  # agent_id -> lease_id
    created_at: str = ""
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status,
            "participants": [p.as_dict() for p in self.participants.values()],
            "message_count": len(self.messages),
            "task_graph": self.supervisor.graph.as_dict(),
            "blackboard": self.blackboard.snapshot(),
            "governor": self.governor.usage(),
            "synthesis": self.synthesis.as_dict() if self.synthesis else None,
            "created_at": self.created_at,
        }

    def _ensure_open(self) -> None:
        if self.status != "open":
            raise RoomTerminated(f"room status is {self.status}")

    def add_participant(
        self,
        agent_id: str,
        *,
        role: str = "specialist",
        model: str = "",
        provider: str = "local",
    ) -> Participant:
        with self._lock:
            self._ensure_open()
            aid = str(agent_id or "").strip().lower()
            if not aid:
                raise RoomError("agent_id is required", code="invalid_participant")
            if aid in self.participants:
                return self.participants[aid]
            role_text = "supervisor" if aid == SUPERVISOR_ID or role == "supervisor" else "specialist"
            participant = Participant(
                agent_id=aid,
                role=role_text,
                model=str(model or ""),
                provider="cloud" if str(provider).lower() == "cloud" else "local",
            )
            self.participants[aid] = participant
            self.audit.record(
                room_id=self.id,
                kind="participant_joined",
                summary=f"{aid} joined as {role_text}",
                payload=participant.as_dict(),
            )
            return participant

    def decompose(self) -> list[TaskNode]:
        with self._lock:
            self._ensure_open()
            specialists = [
                p.agent_id
                for p in self.participants.values()
                if p.role == "specialist"
            ]
            budget = self.governor.concurrency_budget()
            self.supervisor.set_concurrency_budget(budget)
            nodes = self.supervisor.decompose(self.goal, specialists)
            for node in nodes:
                self.audit.record(
                    room_id=self.id,
                    kind="task_assigned",
                    summary=f"assigned {node.id} to {node.assignee}",
                    payload=node.as_dict(),
                )
            return nodes

    def acquire_for(self, agent_id: str, **claim_kwargs: Any) -> dict[str, Any]:
        with self._lock:
            self._ensure_open()
            aid = str(agent_id).strip().lower()
            participant = self.participants.get(aid)
            if participant is None:
                raise RoomError(f"unknown participant: {aid}", code="unknown_participant")
            provider = claim_kwargs.pop("provider", participant.provider)
            try:
                lease = self.governor.acquire(agent_id=aid, provider=provider, **claim_kwargs)
            except GovernorDenied as exc:
                self.audit.record(
                    room_id=self.id,
                    kind="governor_denied",
                    summary=str(exc.reason),
                    payload={"agent_id": aid, "code": exc.code, "reason": exc.reason},
                )
                raise
            self.active_leases[aid] = lease.id
            self.audit.record(
                room_id=self.id,
                kind="governor_acquired",
                summary=f"lease {lease.id} for {aid}",
                payload=lease.as_dict(),
            )
            return lease.as_dict()

    def release_for(self, agent_id: str) -> None:
        with self._lock:
            aid = str(agent_id).strip().lower()
            lease_id = self.active_leases.pop(aid, None)
            if not lease_id:
                return
            lease = self.governor.release(lease_id)
            self.audit.record(
                room_id=self.id,
                kind="governor_released",
                summary=f"released lease {lease_id}",
                payload=lease.as_dict(),
            )

    def post_message(
        self,
        *,
        kind: str | MessageKind,
        from_agent: str,
        body: str,
        to_agent: str | None = None,
        rationale: str = "",
        task_id: str | None = None,
        artifact_ids: list[str] | None = None,
        citation_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        private: bool = False,
    ) -> RoomMessage:
        with self._lock:
            self._ensure_open()
            aid = str(from_agent or "").strip().lower()
            if aid not in self.participants:
                raise RoomError(f"unknown participant: {aid}", code="unknown_participant")
            message = build_message(
                room_id=self.id,
                kind=kind,
                from_agent=aid,
                body=body,
                to_agent=to_agent,
                rationale=rationale,
                task_id=task_id,
                artifact_ids=artifact_ids,
                citation_ids=citation_ids,
                metadata=metadata,
            )
            # Validate @mentions / explicit targets are room participants.
            targets = set(message.mentions)
            if message.to_agent:
                targets.add(message.to_agent)
            for target in targets:
                if target not in self.participants:
                    raise RoomError(
                        f"@mention target not in room: {target}",
                        code="unknown_mention",
                    )

            if private:
                self.history.append(
                    aid,
                    role="assistant",
                    content=message.body,
                    metadata={"kind": message.kind.value, "message_id": message.id},
                )
                # Private turns are not room-visible and do not enter deadlock/audit message stream.
                return message

            self.messages.append(message)
            self.audit.record(
                room_id=self.id,
                kind="message_posted",
                summary=f"{message.kind.value} from {aid}",
                payload=message.as_dict(),
            )
            if message.kind == MessageKind.HANDOFF:
                self.audit.record(
                    room_id=self.id,
                    kind="handoff",
                    summary=f"handoff {aid} -> {message.to_agent}",
                    payload={
                        "from_agent": aid,
                        "to_agent": message.to_agent,
                        "task_id": message.task_id,
                        "rationale": message.rationale or message.body,
                        "message_id": message.id,
                    },
                )
                if message.task_id and message.to_agent:
                    if message.task_id in self.supervisor.graph.nodes:
                        self.supervisor.graph.update(
                            message.task_id,
                            assignee=message.to_agent,
                            rationale=message.rationale or "handoff",
                        )

            issues = self.deadlock.observe(message)
            for issue in issues:
                self.audit.record(
                    room_id=self.id,
                    kind="deadlock_detected",
                    summary=issue.detail,
                    payload=issue.as_dict(),
                )
                resolution = self.deadlock.resolve(issue)
                self._apply_resolution(resolution)

            if message.kind == MessageKind.FINAL and aid == SUPERVISOR_ID:
                self.terminate(reason="supervisor FINAL")
            return message

    def _apply_resolution(self, resolution: DeadlockResolution) -> None:
        effects: dict[str, Any] = {}
        if resolution.action == ResolutionAction.APPLY_RULE:
            effects = self.deadlock.apply_rule_side_effects(resolution.issue)
        elif resolution.action == ResolutionAction.SUPERVISOR_INTERVENE:
            # Cancel duplicate/stalled tasks under supervisor authority.
            for agent in resolution.issue.agents:
                for task in list(self.supervisor.graph.nodes.values()):
                    if task.assignee == agent and task.status in {"pending", "running", "blocked"}:
                        self.supervisor.cancel_task(
                            task.id,
                            rationale=f"supervisor intervention: {resolution.issue.kind.value}",
                        )
            effects = {"cancelled_for": list(resolution.issue.agents)}
        self.audit.record(
            room_id=self.id,
            kind="deadlock_resolved",
            summary=resolution.rationale,
            payload={**resolution.as_dict(), "effects": effects},
        )
        if resolution.action == ResolutionAction.OWNER_ESCALATE or resolution.terminate:
            self.audit.record(
                room_id=self.id,
                kind="owner_escalation",
                summary=resolution.rationale,
                payload=resolution.as_dict(),
            )
            # Release leases and mark terminated (avoid re-entering post_message).
            for aid in list(self.active_leases):
                lease_id = self.active_leases.pop(aid, None)
                if lease_id:
                    try:
                        self.governor.release(lease_id)
                    except LookupError:
                        pass
            self.deadlock.mark_terminated()
            self.status = "terminated"
            self.audit.record(
                room_id=self.id,
                kind="room_terminated",
                summary="terminated after owner escalation",
                payload={"reason": resolution.rationale},
            )

    def publish_blackboard(
        self,
        *,
        kind: str | BlackboardKind,
        key: str,
        content: str,
        author: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_open()
            aid = str(author or "").strip().lower()
            if aid not in self.participants:
                raise RoomError(f"unknown participant: {aid}", code="unknown_participant")
            try:
                entry = self.blackboard.publish(
                    kind=kind,
                    key=key,
                    content=content,
                    author=aid,
                    metadata=metadata,
                )
            except BlackboardBoundError:
                raise
            self.audit.record(
                room_id=self.id,
                kind="blackboard_write",
                summary=f"{entry.kind.value}:{entry.key} by {aid}",
                payload=entry.as_dict(),
            )
            return entry.as_dict()

    def handoff(
        self,
        *,
        from_agent: str,
        to_agent: str,
        body: str,
        task_id: str | None = None,
        rationale: str = "",
    ) -> RoomMessage:
        mention_body = body if f"@{to_agent}" in body.lower() else f"@{to_agent} {body}"
        return self.post_message(
            kind=MessageKind.HANDOFF,
            from_agent=from_agent,
            to_agent=to_agent,
            body=mention_body,
            task_id=task_id,
            rationale=rationale or "explicit handoff",
        )

    def synthesize_and_finalize(self) -> SynthesisResult:
        with self._lock:
            self._ensure_open()
            result = self.supervisor.synthesize(self.blackboard, goal=self.goal)
            self.synthesis = result
            self.audit.record(
                room_id=self.id,
                kind="synthesis",
                summary="supervisor synthesis",
                payload=result.as_dict(),
            )
            cite_bits = []
            if result.cited_agents:
                cite_bits.append("agents=" + ",".join(result.cited_agents))
            if result.cited_artifact_ids:
                cite_bits.append(f"artifacts={len(result.cited_artifact_ids)}")
            body = result.summary
            if cite_bits:
                body = f"{body} [{'; '.join(cite_bits)}]"
            self.post_message(
                kind=MessageKind.FINAL,
                from_agent=SUPERVISOR_ID,
                body=body,
                rationale=result.rationale,
                artifact_ids=list(result.cited_artifact_ids),
                citation_ids=list(result.cited_citation_ids),
                metadata={
                    "cited_agents": list(result.cited_agents),
                    "cited_decision_ids": list(result.cited_decision_ids),
                },
            )
            return result

    def terminate(self, *, reason: str = "terminated") -> None:
        with self._lock:
            if self.status == "terminated":
                return
            for aid in list(self.active_leases):
                self.release_for(aid)
            self.deadlock.mark_terminated()
            previous = self.status
            self.status = "terminated"
            self.audit.record(
                room_id=self.id,
                kind="room_terminated",
                summary=reason,
                payload={"reason": reason, "previous_status": previous},
            )

    def replay(self) -> dict[str, Any]:
        return self.audit.replay(self.id)


_REGISTRY_LOCK = threading.RLock()
_ROOMS: dict[str, AgentRoom] = {}


def create_room(
    goal: str,
    specialists: list[str],
    *,
    room_id: str | None = None,
    budget: ResourceBudget | None = None,
    cost_mode: str = "balanced",
    privacy_mode: str = "local_only",
    supervisor_model: str = "",
    specialist_models: dict[str, str] | None = None,
    audit: RoomAuditLog | None = None,
) -> AgentRoom:
    """Create a room with Anzu as supervisor and named specialists."""
    goal_text = str(goal or "").strip()
    if not goal_text:
        raise RoomError("goal is required", code="invalid_goal")
    rid = room_id or str(uuid.uuid4())
    gov = ResourceGovernor(budget or build_budget(cost_mode=cost_mode, privacy_mode=privacy_mode))
    room = AgentRoom(
        id=rid,
        goal=goal_text,
        governor=gov,
        supervisor=Supervisor(concurrency_budget=gov.concurrency_budget()),
        audit=audit or RoomAuditLog(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    room.audit.record(
        room_id=rid,
        kind="room_created",
        summary=f"room created for goal: {goal_text[:120]}",
        payload={"goal": goal_text, "budget": gov.budget.as_dict()},
    )
    room.add_participant(SUPERVISOR_ID, role="supervisor", model=supervisor_model, provider="local")
    models = specialist_models or {}
    for raw in specialists:
        aid = str(raw or "").strip().lower()
        if not aid or aid == SUPERVISOR_ID:
            continue
        room.add_participant(aid, role="specialist", model=models.get(aid, ""), provider="local")
    if len(room.participants) < 2:
        raise RoomError("room requires Anzu plus at least one specialist", code="insufficient_participants")
    with _REGISTRY_LOCK:
        _ROOMS[rid] = room
    return room


def get_room(room_id: str) -> AgentRoom | None:
    with _REGISTRY_LOCK:
        return _ROOMS.get(room_id)


def list_rooms() -> list[dict[str, Any]]:
    with _REGISTRY_LOCK:
        return [room.as_dict() for room in _ROOMS.values()]


def reset_registry() -> None:
    """Test helper: clear in-memory rooms."""
    with _REGISTRY_LOCK:
        _ROOMS.clear()


def mention_targets(text: str) -> list[str]:
    """Public helper for @mention extraction."""
    return parse_mentions(text)
