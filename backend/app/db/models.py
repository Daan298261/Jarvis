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
