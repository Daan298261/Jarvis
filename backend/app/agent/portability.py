from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..db.models import AgentPortabilityAudit, AgentProfileRecord, AgentRuntimeLease, utcnow
from ..db.session import SessionLocal
from ..inference.runtime_profiles import RuntimeProfile, get_runtime_profile

PORTABLE_STATE_VERSION = 1

LEASE_ACTIVE = "active"
LEASE_RELEASED = "released"

AGENT_IDLE = "idle"
AGENT_RUNNING = "running"
AGENT_SUSPENDED = "suspended"


class PortabilityError(Exception):
    def __init__(self, message: str, code: str = "portability_error") -> None:
        super().__init__(message)
        self.code = code


class SchedulerError(PortabilityError):
    """Raised when runtime/tool requirements cannot be satisfied."""

    def __init__(self, message: str, code: str = "runtime_incompatible") -> None:
        super().__init__(message, code=code)


@dataclass
class PortableAgentState:
    memory: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    skill_refs: list[str] = field(default_factory=list)
    goals: list[dict[str, Any]] = field(default_factory=list)
    task_state: dict[str, Any] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def serialize_portable_state(state: PortableAgentState) -> str:
    payload = {
        "version": PORTABLE_STATE_VERSION,
        **state.as_dict(),
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def deserialize_portable_state(blob: str) -> PortableAgentState:
    raw = json.loads(blob or "{}")
    if not isinstance(raw, dict):
        raise PortabilityError("invalid portable state payload", code="invalid_state")
    version = int(raw.get("version") or 0)
    if version != PORTABLE_STATE_VERSION:
        raise PortabilityError(
            f"unsupported portable state version: {version}",
            code="unsupported_state_version",
        )
    return PortableAgentState(
        memory=dict(raw.get("memory") or {}),
        policy=dict(raw.get("policy") or {}),
        skill_refs=[str(item) for item in (raw.get("skill_refs") or [])],
        goals=[dict(item) for item in (raw.get("goals") or []) if isinstance(item, dict)],
        task_state=dict(raw.get("task_state") or {}),
        provenance=[dict(item) for item in (raw.get("provenance") or []) if isinstance(item, dict)],
        required_tools=[str(item) for item in (raw.get("required_tools") or [])],
        required_capabilities=[str(item) for item in (raw.get("required_capabilities") or [])],
    )


def check_runtime_compatibility(
    state: PortableAgentState,
    runtime_profile: RuntimeProfile,
) -> None:
    profile_caps = {str(tag) for tag in runtime_profile.capability_tags}
    missing_caps = [cap for cap in state.required_capabilities if cap not in profile_caps]
    if missing_caps:
        raise SchedulerError(
            f"runtime profile {runtime_profile.id} lacks required capabilities: {', '.join(missing_caps)}",
            code="missing_capabilities",
        )
    if state.required_tools:
        # Tool requirements are expressed as capability tags prefixed with tool:
        profile_tools = {tag.split(":", 1)[1] for tag in profile_caps if tag.startswith("tool:")}
        missing_tools = [tool for tool in state.required_tools if tool not in profile_tools]
        if missing_tools:
            raise SchedulerError(
                f"runtime profile {runtime_profile.id} lacks required tools: {', '.join(missing_tools)}",
                code="missing_tools",
            )


def _profile_dict(record: AgentProfileRecord) -> dict[str, Any]:
    state = deserialize_portable_state(record.state_json)
    return {
        "id": record.id,
        "name": record.name,
        "status": record.status,
        "state_version": record.state_version,
        "state": state.as_dict(),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _lease_dict(record: AgentRuntimeLease) -> dict[str, Any]:
    return {
        "id": record.id,
        "agent_id": record.agent_id,
        "runtime_profile_id": record.runtime_profile_id,
        "node_id": record.node_id,
        "model": record.model,
        "endpoint": record.endpoint,
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "released_at": record.released_at.isoformat() if record.released_at else None,
    }


def _audit_dict(record: AgentPortabilityAudit) -> dict[str, Any]:
    return {
        "id": record.id,
        "agent_id": record.agent_id,
        "event": record.event,
        "runtime_profile_id": record.runtime_profile_id,
        "node_id": record.node_id,
        "model": record.model,
        "endpoint": record.endpoint,
        "detail": record.detail,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


async def _append_audit(
    session,
    *,
    agent_id: str,
    event: str,
    runtime_profile_id: str = "",
    node_id: str = "",
    model: str = "",
    endpoint: str = "",
    detail: str = "",
) -> AgentPortabilityAudit:
    row = AgentPortabilityAudit(
        agent_id=agent_id,
        event=event,
        runtime_profile_id=runtime_profile_id,
        node_id=node_id,
        model=model,
        endpoint=endpoint,
        detail=detail,
    )
    session.add(row)
    return row


async def _get_profile_record(session, agent_id: str) -> AgentProfileRecord:
    record = await session.get(AgentProfileRecord, agent_id)
    if record is None:
        raise PortabilityError(f"agent profile not found: {agent_id}", code="agent_not_found")
    return record


async def _active_lease(session, agent_id: str) -> AgentRuntimeLease | None:
    rows = (
        await session.execute(
            select(AgentRuntimeLease)
            .where(AgentRuntimeLease.agent_id == agent_id, AgentRuntimeLease.status == LEASE_ACTIVE)
            .order_by(AgentRuntimeLease.created_at.desc())
        )
    ).scalars().all()
    return rows[0] if rows else None


async def create_agent_profile(
    *,
    name: str,
    memory: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    skill_refs: list[str] | None = None,
    goals: list[dict[str, Any]] | None = None,
    task_state: dict[str, Any] | None = None,
    provenance: list[dict[str, Any]] | None = None,
    required_tools: list[str] | None = None,
    required_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    state = PortableAgentState(
        memory=dict(memory or {}),
        policy=dict(policy or {}),
        skill_refs=list(skill_refs or []),
        goals=list(goals or []),
        task_state=dict(task_state or {}),
        provenance=list(provenance or []),
        required_tools=list(required_tools or []),
        required_capabilities=list(required_capabilities or []),
    )
    agent_id = str(uuid.uuid4())
    now = utcnow()
    record = AgentProfileRecord(
        id=agent_id,
        name=(name or "").strip() or "agent",
        state_version=PORTABLE_STATE_VERSION,
        state_json=serialize_portable_state(state),
        status=AGENT_IDLE,
        created_at=now,
        updated_at=now,
    )
    async with SessionLocal() as session:
        session.add(record)
        await _append_audit(
            session,
            agent_id=agent_id,
            event="created",
            detail=f"name={record.name}",
        )
        await session.commit()
        await session.refresh(record)
    return _profile_dict(record)


async def get_agent_profile(agent_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        record = await _get_profile_record(session, agent_id)
        payload = _profile_dict(record)
        active = await _active_lease(session, agent_id)
        payload["active_lease"] = _lease_dict(active) if active else None
    return payload


async def list_agent_profiles(limit: int = 100) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(AgentProfileRecord).order_by(AgentProfileRecord.created_at.desc()).limit(limit)
            )
        ).scalars().all()
        return [_profile_dict(row) for row in rows]


async def update_agent_state(
    agent_id: str,
    *,
    memory: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    skill_refs: list[str] | None = None,
    goals: list[dict[str, Any]] | None = None,
    task_state: dict[str, Any] | None = None,
    provenance: list[dict[str, Any]] | None = None,
    required_tools: list[str] | None = None,
    required_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    async with SessionLocal() as session:
        record = await _get_profile_record(session, agent_id)
        state = deserialize_portable_state(record.state_json)
        if memory is not None:
            state.memory = dict(memory)
        if policy is not None:
            state.policy = dict(policy)
        if skill_refs is not None:
            state.skill_refs = list(skill_refs)
        if goals is not None:
            state.goals = list(goals)
        if task_state is not None:
            state.task_state = dict(task_state)
        if provenance is not None:
            state.provenance = list(provenance)
        if required_tools is not None:
            state.required_tools = list(required_tools)
        if required_capabilities is not None:
            state.required_capabilities = list(required_capabilities)
        record.state_json = serialize_portable_state(state)
        record.updated_at = utcnow()
        await _append_audit(session, agent_id=agent_id, event="state_updated")
        await session.commit()
        await session.refresh(record)
        return _profile_dict(record)


async def acquire_runtime_lease(
    agent_id: str,
    *,
    runtime_profile_id: str,
    node_id: str = "localhost",
) -> dict[str, Any]:
    runtime = get_runtime_profile(runtime_profile_id)
    if runtime is None:
        raise PortabilityError(
            f"runtime profile not found: {runtime_profile_id}",
            code="runtime_not_found",
        )
    async with SessionLocal() as session:
        record = await _get_profile_record(session, agent_id)
        state = deserialize_portable_state(record.state_json)
        check_runtime_compatibility(state, runtime)
        active = await _active_lease(session, agent_id)
        if active is not None:
            raise PortabilityError(
                f"agent {agent_id} already has active lease {active.id}",
                code="lease_active",
            )
        lease_id = str(uuid.uuid4())
        lease = AgentRuntimeLease(
            id=lease_id,
            agent_id=agent_id,
            runtime_profile_id=runtime.id,
            node_id=node_id,
            model=runtime.model,
            endpoint=runtime.endpoint,
            status=LEASE_ACTIVE,
            created_at=utcnow(),
        )
        record.status = AGENT_RUNNING
        record.updated_at = utcnow()
        session.add(lease)
        await _append_audit(
            session,
            agent_id=agent_id,
            event="lease_acquired",
            runtime_profile_id=runtime.id,
            node_id=node_id,
            model=runtime.model,
            endpoint=runtime.endpoint,
            detail=f"lease_id={lease_id}",
        )
        await session.commit()
        return _lease_dict(lease)


async def release_runtime_lease(lease_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        lease = await session.get(AgentRuntimeLease, lease_id)
        if lease is None:
            raise PortabilityError(f"lease not found: {lease_id}", code="lease_not_found")
        if lease.status != LEASE_ACTIVE:
            raise PortabilityError(f"lease is not active: {lease_id}", code="lease_not_active")
        lease.status = LEASE_RELEASED
        lease.released_at = utcnow()
        record = await _get_profile_record(session, lease.agent_id)
        record.status = AGENT_IDLE
        record.updated_at = utcnow()
        await _append_audit(
            session,
            agent_id=lease.agent_id,
            event="lease_released",
            runtime_profile_id=lease.runtime_profile_id,
            node_id=lease.node_id,
            model=lease.model,
            endpoint=lease.endpoint,
            detail=f"lease_id={lease_id}",
        )
        await session.commit()
        return _lease_dict(lease)


async def migrate_agent(
    agent_id: str,
    *,
    target_runtime_profile_id: str,
    node_id: str = "localhost",
) -> dict[str, Any]:
    runtime = get_runtime_profile(target_runtime_profile_id)
    if runtime is None:
        raise PortabilityError(
            f"runtime profile not found: {target_runtime_profile_id}",
            code="runtime_not_found",
        )
    async with SessionLocal() as session:
        record = await _get_profile_record(session, agent_id)
        state = deserialize_portable_state(record.state_json)
        check_runtime_compatibility(state, runtime)
        active = await _active_lease(session, agent_id)
        previous = _lease_dict(active) if active else None
        if active is not None:
            active.status = LEASE_RELEASED
            active.released_at = utcnow()
            await _append_audit(
                session,
                agent_id=agent_id,
                event="lease_released",
                runtime_profile_id=active.runtime_profile_id,
                node_id=active.node_id,
                model=active.model,
                endpoint=active.endpoint,
                detail=f"migration release lease_id={active.id}",
            )
        lease_id = str(uuid.uuid4())
        lease = AgentRuntimeLease(
            id=lease_id,
            agent_id=agent_id,
            runtime_profile_id=runtime.id,
            node_id=node_id,
            model=runtime.model,
            endpoint=runtime.endpoint,
            status=LEASE_ACTIVE,
            created_at=utcnow(),
        )
        state.provenance.append(
            {
                "event": "migrated",
                "from_runtime": previous["runtime_profile_id"] if previous else None,
                "to_runtime": runtime.id,
                "node_id": node_id,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        record.state_json = serialize_portable_state(state)
        record.status = AGENT_RUNNING
        record.updated_at = utcnow()
        session.add(lease)
        await _append_audit(
            session,
            agent_id=agent_id,
            event="migrated",
            runtime_profile_id=runtime.id,
            node_id=node_id,
            model=runtime.model,
            endpoint=runtime.endpoint,
            detail=json.dumps({"previous": previous, "lease_id": lease_id}),
        )
        await session.commit()
        payload = _profile_dict(record)
        payload["lease"] = _lease_dict(lease)
        payload["previous_lease"] = previous
    return payload


async def suspend_agent(agent_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        record = await _get_profile_record(session, agent_id)
        active = await _active_lease(session, agent_id)
        if active is not None:
            active.status = LEASE_RELEASED
            active.released_at = utcnow()
            await _append_audit(
                session,
                agent_id=agent_id,
                event="lease_released",
                runtime_profile_id=active.runtime_profile_id,
                node_id=active.node_id,
                model=active.model,
                endpoint=active.endpoint,
                detail=f"suspend release lease_id={active.id}",
            )
        record.status = AGENT_SUSPENDED
        record.updated_at = utcnow()
        await _append_audit(session, agent_id=agent_id, event="suspended")
        await session.commit()
        await session.refresh(record)
        return _profile_dict(record)


async def resume_agent(
    agent_id: str,
    *,
    runtime_profile_id: str,
    node_id: str = "localhost",
) -> dict[str, Any]:
    async with SessionLocal() as session:
        record = await _get_profile_record(session, agent_id)
        if record.status not in {AGENT_SUSPENDED, AGENT_IDLE}:
            raise PortabilityError(
                f"agent {agent_id} cannot resume from status {record.status}",
                code="invalid_status",
            )
        state = deserialize_portable_state(record.state_json)
        runtime = get_runtime_profile(runtime_profile_id)
        if runtime is None:
            raise PortabilityError(
                f"runtime profile not found: {runtime_profile_id}",
                code="runtime_not_found",
            )
        check_runtime_compatibility(state, runtime)
        active = await _active_lease(session, agent_id)
        if active is not None:
            raise PortabilityError(
                f"agent {agent_id} already has active lease {active.id}",
                code="lease_active",
            )
        lease_id = str(uuid.uuid4())
        lease = AgentRuntimeLease(
            id=lease_id,
            agent_id=agent_id,
            runtime_profile_id=runtime.id,
            node_id=node_id,
            model=runtime.model,
            endpoint=runtime.endpoint,
            status=LEASE_ACTIVE,
            created_at=utcnow(),
        )
        state.provenance.append(
            {
                "event": "resumed",
                "runtime_profile_id": runtime.id,
                "node_id": node_id,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        record.state_json = serialize_portable_state(state)
        record.status = AGENT_RUNNING
        record.updated_at = utcnow()
        session.add(lease)
        await _append_audit(
            session,
            agent_id=agent_id,
            event="resumed",
            runtime_profile_id=runtime.id,
            node_id=node_id,
            model=runtime.model,
            endpoint=runtime.endpoint,
            detail=f"lease_id={lease_id}",
        )
        await session.commit()
        payload = _profile_dict(record)
        payload["lease"] = _lease_dict(lease)
    return payload


async def list_audit_events(*, agent_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        query = select(AgentPortabilityAudit).order_by(AgentPortabilityAudit.created_at.desc()).limit(limit)
        if agent_id:
            query = query.where(AgentPortabilityAudit.agent_id == agent_id)
        rows = (await session.execute(query)).scalars().all()
        return [_audit_dict(row) for row in rows]
