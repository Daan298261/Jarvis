from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from ..providers.base import ChatMessage
from ..tools.exposure import REQUEST_CAPABILITY, normalize_capability, tools_for_task
from ..tools.registry import REGISTRY
from .compaction import SUMMARY_MARKER, compact_history, estimate_prompt_tokens

CORE_PROMPT_VERSION = "1.0.0"
CORE_TOOL_SURFACE_VERSION = "1.0.0"

CORE_SYSTEM_PROMPT = (
    "You are Jarvis, a compact local agent. Complete the user's task with the tools currently "
    "exposed. Keep reasoning concise. Call request_capability only when a missing tool is "
    "required. The orchestrator retains execution authority."
)

CORE_TOOL_NAMES = frozenset({"filesystem", REQUEST_CAPABILITY})

# Lightweight on-demand skill hints keyed by task class or explicit id.
SKILL_HINTS: dict[str, str] = {
    "filesystem": "Prefer direct filesystem reads/writes inside allowed directories.",
    "shell": "Use terminal for one-shot commands; capture output before retrying.",
    "software engineering": "Read before edit; verify with tests when available.",
    "research": "Fetch sources first, then summarize with citations in observations.",
}

AUTONOMY_SANDBOX_REQUIRED = frozenset({"autonomous"})


@dataclass
class HarnessMetrics:
    core_prompt_version: str
    tool_surface_version: str
    core_prompt_chars: int
    tool_count: int
    skill_count: int
    estimated_prompt_tokens: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HarnessSurface:
    system_prompt: str
    tool_names: list[str]
    tool_schemas: list[dict[str, Any]]
    skill_blocks: list[str]
    metrics: HarnessMetrics

    def as_dict(self) -> dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "tool_names": list(self.tool_names),
            "tool_schemas": self.tool_schemas,
            "skill_blocks": list(self.skill_blocks),
            "metrics": self.metrics.as_dict(),
        }


@dataclass
class CompactionProvenance:
    source_message_count: int
    summarized_indices: list[int]
    summary_lines: list[str]
    method: str = "compact_history"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompactionResult:
    messages: list[ChatMessage]
    summary: str
    provenance: CompactionProvenance
    retained_facts: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "provenance": self.provenance.as_dict(),
            "retained_facts": list(self.retained_facts),
            "message_count": len(self.messages),
        }


@dataclass
class ExecutionGate:
    allowed: bool
    code: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LocalHarnessPolicy:
    task_class: str = "mixed"
    required_tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] | None = None
    disabled_tools: list[str] = field(default_factory=list)
    autonomy: str = "trusted"
    require_sandbox: bool = False
    skill_ids: list[str] = field(default_factory=list)
    max_tool_count: int | None = None


@dataclass
class LocalEscalationSignals:
    consecutive_failures: int = 0
    confidence: float = 1.0
    local_attempts: int = 0
    already_escalated: int = 0
    user_requested: bool = False
    task_class: str = ""


@dataclass
class EscalationPolicy:
    max_cost_usd: float = 0.10
    max_escalations: int = 1
    confidence_threshold: float = 0.55
    failure_threshold: int = 3
    advisor_cost_usd: float = 0.02


@dataclass
class EscalationDecision:
    should_escalate: bool
    reason: str = ""
    code: str = ""
    estimated_cost_usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def sandbox_available() -> bool:
    """Best-effort probe for an execution sandbox (Docker) on this host."""
    return bool(shutil.which("docker"))


def _enabled_tool_names() -> set[str]:
    return {name for name, tool in REGISTRY.tools.items() if tool.enabled}


def resolve_tool_names(policy: LocalHarnessPolicy) -> list[str]:
    """Load tools dynamically from task requirements and policy constraints."""
    if policy.allowed_tools is not None:
        base = {normalize_capability(name) for name in policy.allowed_tools if name}
    else:
        base = set(tools_for_task(policy.task_class))
    for raw in policy.required_tools:
        base.add(normalize_capability(raw))
    disabled = {normalize_capability(name) for name in policy.disabled_tools if name}
    base -= disabled
    base |= set(CORE_TOOL_NAMES)
    enabled = _enabled_tool_names()
    enabled.add("mcp")
    names = sorted(name for name in base if name in enabled or name == REQUEST_CAPABILITY)
    if policy.max_tool_count is not None and len(names) > policy.max_tool_count:
        # Keep core tools and required tools, trim optional extras deterministically.
        required = {normalize_capability(item) for item in policy.required_tools}
        keep = sorted(set(CORE_TOOL_NAMES) | required)
        optional = [name for name in names if name not in keep]
        names = keep + optional[: max(0, policy.max_tool_count - len(keep))]
        names = sorted(set(names))
    return names


def load_skill_blocks(policy: LocalHarnessPolicy, goal: str = "") -> list[str]:
    """Load compact skill guidance blocks on demand from task class and explicit ids."""
    blocks: list[str] = []
    seen: set[str] = set()
    task_key = (policy.task_class or "").strip().lower()
    if task_key in SKILL_HINTS and task_key not in seen:
        blocks.append(SKILL_HINTS[task_key])
        seen.add(task_key)
    for skill_id in policy.skill_ids:
        key = (skill_id or "").strip().lower()
        if not key or key in seen:
            continue
        if key in SKILL_HINTS:
            blocks.append(SKILL_HINTS[key])
        else:
            blocks.append(f"Skill hint ({key}): apply proven workflow for {key}.")
        seen.add(key)
    if goal and "test" in goal.lower() and "testing" not in seen:
        blocks.append("Run or extend tests after code changes.")
        seen.add("testing")
    return blocks


def build_harness_surface(policy: LocalHarnessPolicy, goal: str = "") -> HarnessSurface:
    tool_names = resolve_tool_names(policy)
    schemas = REGISTRY.openai_tools(names=set(tool_names))
    skill_blocks = load_skill_blocks(policy, goal=goal)
    skill_text = "\n".join(skill_blocks)
    system_prompt = CORE_SYSTEM_PROMPT
    if skill_text:
        system_prompt = f"{CORE_SYSTEM_PROMPT}\n\nOn-demand skills:\n{skill_text}"
    messages = [ChatMessage(role="system", content=system_prompt)]
    metrics = HarnessMetrics(
        core_prompt_version=CORE_PROMPT_VERSION,
        tool_surface_version=CORE_TOOL_SURFACE_VERSION,
        core_prompt_chars=len(CORE_SYSTEM_PROMPT),
        tool_count=len(tool_names),
        skill_count=len(skill_blocks),
        estimated_prompt_tokens=estimate_prompt_tokens(messages),
    )
    return HarnessSurface(
        system_prompt=system_prompt,
        tool_names=tool_names,
        tool_schemas=schemas,
        skill_blocks=skill_blocks,
        metrics=metrics,
    )


def _extract_summary_lines(messages: list[ChatMessage]) -> tuple[str, list[str]]:
    for message in messages:
        if message.role != "system":
            continue
        text = message.content if isinstance(message.content, str) else json.dumps(message.content)
        if text.startswith(SUMMARY_MARKER):
            body = text[len(SUMMARY_MARKER) :].strip()
            lines = [line.strip() for line in body.splitlines() if line.strip()]
            return body, lines
    return "", []


def compact_with_provenance(
    messages: list[ChatMessage],
    *,
    critical_facts: Iterable[str] | None = None,
    keep_last: int = 8,
    working_state_block: str | None = None,
) -> CompactionResult:
    """Compact chat history and attach provenance for summarized spans."""
    original_count = len(messages)
    compacted = compact_history(
        messages,
        keep_last=keep_last,
        working_state_block=working_state_block,
    )
    summary, summary_lines = _extract_summary_lines(compacted)
    start_index = 2  # preserve head system + user
    end_index = max(start_index, original_count - keep_last)
    provenance = CompactionProvenance(
        source_message_count=original_count,
        summarized_indices=list(range(start_index, end_index)),
        summary_lines=summary_lines,
    )
    facts = [fact.strip() for fact in (critical_facts or []) if str(fact).strip()]
    for line in summary_lines[:6]:
        if line.startswith("- "):
            facts.append(line[2:].strip())
    # De-duplicate while preserving order.
    retained: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        if fact not in seen:
            retained.append(fact)
            seen.add(fact)
    return CompactionResult(
        messages=compacted,
        summary=summary,
        provenance=provenance,
        retained_facts=retained,
    )


def check_autonomous_execution(policy: LocalHarnessPolicy) -> ExecutionGate:
    """Fail closed when autonomous execution requires a sandbox that is unavailable."""
    autonomy = (policy.autonomy or "trusted").strip().lower()
    if autonomy not in AUTONOMY_SANDBOX_REQUIRED:
        return ExecutionGate(allowed=True, code="not_autonomous")
    if not policy.require_sandbox:
        return ExecutionGate(allowed=True, code="sandbox_not_required")
    if sandbox_available():
        return ExecutionGate(allowed=True, code="sandbox_ready")
    return ExecutionGate(
        allowed=False,
        code="sandbox_unavailable",
        reason=(
            "Autonomous execution requires an execution sandbox (Docker), but none is "
            "available on this host. Refusing tool execution until sandboxing is enabled."
        ),
    )


def evaluate_escalation(
    signals: LocalEscalationSignals,
    policy: EscalationPolicy | None = None,
) -> EscalationDecision:
    """Decide whether a locally stuck task should escalate to an advisor under policy limits."""
    rules = policy or EscalationPolicy()
    if signals.already_escalated >= rules.max_escalations:
        return EscalationDecision(False, reason="escalation budget exhausted", code="budget_exhausted")
    if signals.user_requested:
        cost = rules.advisor_cost_usd
        if cost > rules.max_cost_usd:
            return EscalationDecision(
                False,
                reason="advisor cost exceeds policy ceiling",
                code="cost_exceeded",
                estimated_cost_usd=cost,
            )
        return EscalationDecision(
            True,
            reason="user requested advisor help",
            code="user_requested",
            estimated_cost_usd=cost,
        )
    low_confidence = signals.confidence < rules.confidence_threshold
    stuck = signals.consecutive_failures >= rules.failure_threshold
    if (low_confidence or stuck) and signals.local_attempts >= 1:
        cost = rules.advisor_cost_usd
        if cost > rules.max_cost_usd:
            return EscalationDecision(
                False,
                reason="advisor cost exceeds policy ceiling",
                code="cost_exceeded",
                estimated_cost_usd=cost,
            )
        reason = "low confidence" if low_confidence else "repeated local failures"
        return EscalationDecision(
            True,
            reason=f"local model {reason}",
            code="local_failure",
            estimated_cost_usd=cost,
        )
    return EscalationDecision(False, reason="local execution still viable", code="continue_local")


class LocalHarness:
    """Compact orchestration harness for smaller local models."""

    def build_surface(self, policy: LocalHarnessPolicy, goal: str = "") -> HarnessSurface:
        return build_harness_surface(policy, goal=goal)

    def compact_context(
        self,
        messages: list[ChatMessage],
        *,
        critical_facts: Iterable[str] | None = None,
        keep_last: int = 8,
        working_state_block: str | None = None,
    ) -> CompactionResult:
        return compact_with_provenance(
            messages,
            critical_facts=critical_facts,
            keep_last=keep_last,
            working_state_block=working_state_block,
        )

    def check_execution(self, policy: LocalHarnessPolicy) -> ExecutionGate:
        return check_autonomous_execution(policy)

    def evaluate_escalation(
        self,
        signals: LocalEscalationSignals,
        policy: EscalationPolicy | None = None,
    ) -> EscalationDecision:
        return evaluate_escalation(signals, policy)


HARNESS = LocalHarness()
