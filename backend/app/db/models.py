from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(400))
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    stage: Mapped[str] = mapped_column(String(64), default="queued")
    autonomy: Mapped[str] = mapped_column(String(32), default="trusted")
    profile: Mapped[str] = mapped_column(String(32), default="balanced")
    execution_mode: Mapped[str] = mapped_column(String(32), default="balanced")
    task_class: Mapped[str] = mapped_column(String(64), default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="")
    plan_json: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="")
    verification: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    current_action: Mapped[str] = mapped_column(Text, default="")
    current_tool: Mapped[str] = mapped_column(String(80), default="")
    exposed_tools: Mapped[str] = mapped_column(Text, default="")
    retries: Mapped[int] = mapped_column(Integer, default=0)
    compact_memory: Mapped[str] = mapped_column(Text, default="")
    conversation_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    waiting_for_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_payload: Mapped[str] = mapped_column(Text, default="")
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    schema_errors: Mapped[int] = mapped_column(Integer, default=0)
    model_ms: Mapped[float] = mapped_column(Float, default=0)
    tool_ms: Mapped[float] = mapped_column(Float, default=0)
    human_interventions: Mapped[int] = mapped_column(Integer, default=0)

    events: Mapped[list["TaskEvent"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    tool_calls: Mapped[list["ToolCallRecord"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    checkpoints: Mapped[list["Checkpoint"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    kind: Mapped[str] = mapped_column(String(40))
    stage: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(400), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[Task] = relationship(back_populates="events")


class ToolCallRecord(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    tool_name: Mapped[str] = mapped_column(String(80))
    arguments_json: Mapped[str] = mapped_column(Text, default="{}")
    output: Mapped[str] = mapped_column(Text, default="")
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    retry_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[Task] = relationship(back_populates="tool_calls")


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    kind: Mapped[str] = mapped_column(String(40))
    path: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[Task] = relationship(back_populates="checkpoints")


class Trajectory(Base):
    """An actionable summary of how a task actually went.

    Stores tool/worker choices, failures, and recoveries so later tasks can
    reuse what worked. Never stores hidden reasoning.
    """

    __tablename__ = "trajectories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), default="")
    task_class: Mapped[str] = mapped_column(String(64), default="")
    goal: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(32), default="")
    tools_json: Mapped[str] = mapped_column(Text, default="[]")
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    failures: Mapped[str] = mapped_column(Text, default="")
    recovery: Mapped[str] = mapped_column(Text, default="")
    verification: Mapped[str] = mapped_column(Text, default="")
    duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    reuse_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Skill(Base):
    """A reusable workflow promoted from repeated successful trajectories."""

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    task_class: Mapped[str] = mapped_column(String(64), default="")
    parameters_json: Mapped[str] = mapped_column(Text, default="[]")
    tools_json: Mapped[str] = mapped_column(Text, default="[]")
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    verification: Mapped[str] = mapped_column(Text, default="")
    recovery: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(32), default="promoted")
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BenchmarkSample(Base):
    """Persisted model/agent operational metrics for the Model page."""

    __tablename__ = "benchmark_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile: Mapped[str] = mapped_column(String(32), default="")
    quantization: Mapped[str] = mapped_column(String(32), default="")
    context_size: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    generation_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    vram_used_mib: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_used_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    task_success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0)
    tasks_failed: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(32), default="timing")
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CodingUsageSample(Base):
    """Paid/local coding-worker cost and outcome for routing decisions."""

    __tablename__ = "coding_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), default="")
    worker: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    task_class: Mapped[str] = mapped_column(String(64), default="")
    complexity: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    verified_success: Mapped[bool] = mapped_column(Boolean, default=False)
    first_attempt_success: Mapped[bool] = mapped_column(Boolean, default=False)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentBenchmarkResult(Base):
    """One case result from the P0.9 representative agent suite."""

    __tablename__ = "agent_benchmark_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    suite_id: Mapped[str] = mapped_column(String(64), default="")
    case_id: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(64), default="")
    profile: Mapped[str] = mapped_column(String(32), default="")
    quantization: Mapped[str] = mapped_column(String(32), default="")
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    human_intervention: Mapped[bool] = mapped_column(Boolean, default=False)
    total_time_seconds: Mapped[float] = mapped_column(Float, default=0)
    model_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    tool_time_seconds: Mapped[float] = mapped_column(Float, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    schema_errors: Mapped[int] = mapped_column(Integer, default=0)
    incorrect_actions: Mapped[int] = mapped_column(Integer, default=0)
    verification_result: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="scripted")
    workspace: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CodingRoute(Base):
    """Software-development worker routing decision for a task."""

    __tablename__ = "coding_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), default="")
    complexity: Mapped[int] = mapped_column(Integer, default=0)
    tier: Mapped[int] = mapped_column(Integer, default=1)
    tier_name: Mapped[str] = mapped_column(String(32), default="")
    intended_worker: Mapped[str] = mapped_column(String(64), default="")
    selected_worker: Mapped[str] = mapped_column(String(64), default="")
    fallback_worker: Mapped[str] = mapped_column(String(64), default="local-jarvis-coding")
    paid_worker_available: Mapped[bool] = mapped_column(Boolean, default=False)
    independent_verification_required: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(32), default="")
    verification: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), default="")
    title: Mapped[str] = mapped_column(String(400), default="")
    messages_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EscalationPackage(Base):
    """Compact EscalationContext persisted for the next coding worker."""

    __tablename__ = "escalation_packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), default="")
    task_class: Mapped[str] = mapped_column(String(64), default="")
    goal: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AcpSession(Base):
    """Persisted Cursor ACP session so Jarvis can resume after restart."""

    __tablename__ = "acp_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cursor_session_id: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    cwd: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="disconnected")
    last_event: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Node(Base):
    """A physical or virtual machine participating in the Jarvis swarm.

    Distinct from software Workers (CursorACPWorker, BrowserWorker, etc.) which
    execute on eligible Nodes.
    """

    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="online")
    node_class: Mapped[str] = mapped_column(String(64), default="senior_worker")
    roles_json: Mapped[str] = mapped_column(Text, default="[]")
    address: Mapped[str] = mapped_column(String(255), default="127.0.0.1")
    host_alias: Mapped[str] = mapped_column(String(64), default="localhost")
    hardware_json: Mapped[str] = mapped_column(Text, default="{}")
    resources_json: Mapped[str] = mapped_column(Text, default="{}")
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workers: Mapped[list["NodeWorker"]] = relationship(
        back_populates="node",
        cascade="all, delete-orphan",
    )
    capabilities: Mapped[list["NodeCapability"]] = relationship(
        back_populates="node",
        cascade="all, delete-orphan",
    )


class NodeWorker(Base):
    """Placement of a software Worker on a Node.

    Workers remain distinct from Nodes: this records which execution services
    are available on a given machine.
    """

    __tablename__ = "node_workers"
    __table_args__ = (UniqueConstraint("node_id", "worker_id", name="uq_node_worker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), index=True)
    worker_id: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(String(32), default="worker")
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    node: Mapped[Node] = relationship(back_populates="workers")


class NodeCapability(Base):
    """Technical capability bound to a Node (distinct from SwarmRole and NodeWorker)."""

    __tablename__ = "node_capabilities"
    __table_args__ = (UniqueConstraint("node_id", "capability_id", name="uq_node_capability"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), index=True)
    capability_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    detail: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    node: Mapped[Node] = relationship(back_populates="capabilities")


class SwarmRole(Base):
    """Distinct swarm role assignment (Orchestrator, Leader, etc.).

    Each role is a separate record with its own holder node_id. A single Node may
    hold multiple roles, but Orchestrator and Leader are never conflated into one
    class or one combined record.
    """

    __tablename__ = "swarm_roles"

    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    node_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"), index=True, nullable=True)
    assignment: Mapped[str] = mapped_column(String(32), default="FORCED")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    node: Mapped[Node | None] = relationship()


class NodeRolePolicy(Base):
    """User intent for a (node, swarm role) pair.

    Distinct from SwarmRole holders: policy records persist across restarts and
    express AUTO/PREFERRED/FORCED/AVOID/DISABLED assignment levels.
    """

    __tablename__ = "node_role_policies"
    __table_args__ = (UniqueConstraint("node_id", "role", name="uq_node_role_policy"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    policy: Mapped[str] = mapped_column(String(32), default="FORCED")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    node: Mapped[Node] = relationship()


class NodeBudget(Base):
    """Configurable Jarvis resource budget for a Node.

    Distinct from Node.resources_json, which is a hardware capacity snapshot.
    """

    __tablename__ = "node_budgets"

    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), primary_key=True)
    preset: Mapped[str] = mapped_column(String(32), default="balanced")
    mode: Mapped[str] = mapped_column(String(32), default="static")
    global_percent: Mapped[int] = mapped_column(Integer, default=50)
    limits_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    node: Mapped[Node] = relationship()


class ResourceLease(Base):
    """Time-bounded claim against a Node's resource budget."""

    __tablename__ = "resource_leases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), index=True)
    claim_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    node: Mapped[Node] = relationship()


class WorkerReport(Base):
    """Worker-reported results and verification requests. Never treated as completion."""

    __tablename__ = "worker_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), default="")
    worker: Mapped[str] = mapped_column(String(80), default="")
    kind: Mapped[str] = mapped_column(String(40), default="worker_result")
    reported_success: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DelegatedWorker(Base):
    """Short-lived child worker spawned by a parent task or parent worker (RFC-0006)."""

    __tablename__ = "delegated_workers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    parent_task_id: Mapped[str] = mapped_column(String(36), index=True)
    parent_worker_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=1)
    task: Mapped[str] = mapped_column(Text)
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    tools_json: Mapped[str] = mapped_column(Text, default="[]")
    budget_json: Mapped[str] = mapped_column(Text, default="{}")
    result_schema_json: Mapped[str] = mapped_column(Text, default="{}")
    autonomy: Mapped[str] = mapped_column(String(32), default="trusted")
    privacy_class: Mapped[str] = mapped_column(String(32), default="internal")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result_json: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    events: Mapped[list["DelegationEvent"]] = relationship(
        back_populates="worker",
        cascade="all, delete-orphan",
    )


class DelegationEvent(Base):
    """Structured child status/result/failure events delivered to the parent."""

    __tablename__ = "delegation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_task_id: Mapped[str] = mapped_column(String(36), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("delegated_workers.id"))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(400), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    worker: Mapped[DelegatedWorker] = relationship(back_populates="events")


class AgentProfileRecord(Base):
    """Durable logical agent identity (RFC-0009).

    Model/runtime/node are execution leases — they do not define identity.
    """

    __tablename__ = "agent_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="idle")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    leases: Mapped[list["AgentRuntimeLease"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list["AgentPortabilityAudit"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )


class AgentRuntimeLease(Base):
    """Time-bounded execution lease binding an agent to a runtime/node (RFC-0009)."""

    __tablename__ = "agent_runtime_leases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_profiles.id"), index=True)
    runtime_profile_id: Mapped[str] = mapped_column(String(64), default="")
    node_id: Mapped[str] = mapped_column(String(64), default="localhost")
    model: Mapped[str] = mapped_column(String(120), default="")
    endpoint: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped[AgentProfileRecord] = relationship(back_populates="leases")


class AgentPortabilityAudit(Base):
    """Executor history for portable agents (RFC-0009)."""

    __tablename__ = "agent_portability_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_profiles.id"), index=True)
    event: Mapped[str] = mapped_column(String(40), default="")
    runtime_profile_id: Mapped[str] = mapped_column(String(64), default="")
    node_id: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    endpoint: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    agent: Mapped[AgentProfileRecord] = relationship(back_populates="audit_events")


class ContextRepository(Base):
    """Versioned curated context repository linked to an agent (RFC-0011)."""

    __tablename__ = "context_repositories"

    agent_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    facts: Mapped[list["ContextFact"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
    )
    mutations: Mapped[list["ContextMutation"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
    )


class ContextFact(Base):
    """Authoritative structured curated memory fact for an agent context repo."""

    __tablename__ = "context_facts"
    __table_args__ = (UniqueConstraint("agent_id", "id", name="uq_context_fact_agent"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("context_repositories.agent_id"), index=True)
    category: Mapped[str] = mapped_column(String(32), default="lessons")
    title: Mapped[str] = mapped_column(String(400), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    title_key: Mapped[str] = mapped_column(String(400), default="", index=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    repo_version: Mapped[int] = mapped_column(Integer, default=1)
    superseded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    repository: Mapped[ContextRepository] = relationship(back_populates="facts")
    provenance_rows: Mapped[list["ContextFactProvenance"]] = relationship(
        back_populates="fact",
        cascade="all, delete-orphan",
    )
    permissions: Mapped[list["ContextFactPermission"]] = relationship(
        back_populates="fact",
        cascade="all, delete-orphan",
    )
    indexes: Mapped[list["ContextFactIndex"]] = relationship(
        back_populates="fact",
        cascade="all, delete-orphan",
    )


class ContextFactProvenance(Base):
    """Source provenance for a curated context fact."""

    __tablename__ = "context_fact_provenance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fact_id: Mapped[str] = mapped_column(ForeignKey("context_facts.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    source_id: Mapped[str] = mapped_column(String(64), default="")
    trajectory_id: Mapped[str] = mapped_column(String(64), default="")
    mutation_id: Mapped[str] = mapped_column(String(36), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    fact: Mapped[ContextFact] = relationship(back_populates="provenance_rows")


class ContextFactPermission(Base):
    """Access control for curated context facts."""

    __tablename__ = "context_fact_permissions"
    __table_args__ = (
        UniqueConstraint("fact_id", "principal_type", "principal_id", "permission", name="uq_context_fact_perm"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fact_id: Mapped[str] = mapped_column(ForeignKey("context_facts.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    principal_type: Mapped[str] = mapped_column(String(32), default="agent")
    principal_id: Mapped[str] = mapped_column(String(64), default="")
    permission: Mapped[str] = mapped_column(String(32), default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    fact: Mapped[ContextFact] = relationship(back_populates="permissions")


class ContextFactIndex(Base):
    """Lookup index for curated context facts."""

    __tablename__ = "context_fact_indexes"
    __table_args__ = (
        UniqueConstraint("agent_id", "index_kind", "index_key", "fact_id", name="uq_context_fact_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    fact_id: Mapped[str] = mapped_column(ForeignKey("context_facts.id"), index=True)
    index_kind: Mapped[str] = mapped_column(String(32), default="title")
    index_key: Mapped[str] = mapped_column(String(400), default="", index=True)
    index_value: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    fact: Mapped[ContextFact] = relationship(back_populates="indexes")


class ContextMutation(Base):
    """Reversible mutation history for curated context repositories."""

    __tablename__ = "context_mutations"

    mutation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("context_repositories.agent_id"), index=True)
    version_before: Mapped[int] = mapped_column(Integer, default=0)
    version_after: Mapped[int] = mapped_column(Integer, default=0)
    action: Mapped[str] = mapped_column(String(32), default="")
    fact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_json: Mapped[str] = mapped_column(Text, default="{}")
    before_json: Mapped[str] = mapped_column(Text, default="")
    after_json: Mapped[str] = mapped_column(Text, default="")
    reversible: Mapped[bool] = mapped_column(Boolean, default=True)
    reverted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    repository: Mapped[ContextRepository] = relationship(back_populates="mutations")


class ContextFactConflict(Base):
    """Flagged conflicting evidence between curated facts (never silently merged)."""

    __tablename__ = "context_fact_conflicts"
    __table_args__ = (UniqueConstraint("agent_id", "fact_id_a", "fact_id_b", name="uq_context_fact_conflict"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    fact_id_a: Mapped[str] = mapped_column(String(36), index=True)
    fact_id_b: Mapped[str] = mapped_column(String(36), index=True)
    reason: Mapped[str] = mapped_column(Text, default="conflicting_evidence")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
