from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol

from .local_harness import EscalationDecision, EscalationPolicy, LocalEscalationSignals, evaluate_escalation

ADVISOR_INTERFACE_VERSION = "1.0.0"

# Advisor responses must never include execution channels or local capability tokens.
FORBIDDEN_OUTBOUND_KEYS = frozenset(
    {
        "auth_token",
        "private_key",
        "capability_token",
        "jarvis_key",
        "tool_calls",
        "tools",
        "execute",
        "filesystem_paths",
        "allowed_directories",
    }
)

FORBIDDEN_RESPONSE_MARKERS = (
    '"function_call"',
    "capability_token",
    "JARVIS_CAPABILITY",
)


@dataclass
class DisclosureField:
    key: str
    label: str
    value: Any
    bytes_estimate: int
    leaves_local: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdvisorDisclosurePackage:
    id: str
    version: str
    created_at: str
    goal: str
    task_class: str
    fields: list[DisclosureField]
    local_only_retained: list[str]
    outbound: dict[str, Any]
    token_estimate: int
    cost_estimate_usd: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "created_at": self.created_at,
            "goal": self.goal,
            "task_class": self.task_class,
            "fields": [item.as_dict() for item in self.fields],
            "local_only_retained": list(self.local_only_retained),
            "outbound": self.outbound,
            "token_estimate": self.token_estimate,
            "cost_estimate_usd": self.cost_estimate_usd,
        }

    def outbound_preview(self) -> dict[str, Any]:
        """Exactly what would leave the local system for the advisor provider."""
        return dict(self.outbound)


@dataclass
class AdvisorResponse:
    analysis: str
    recommendations: list[str] = field(default_factory=list)
    structured_plan: dict[str, Any] | None = None
    advisor_name: str = ""
    used: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis,
            "recommendations": list(self.recommendations),
            "structured_plan": self.structured_plan,
            "advisor_name": self.advisor_name,
            "used": self.used,
            "reason": self.reason,
            "execution_authority": "orchestrator",
            "tool_calls": None,
        }


class AdvisorError(Exception):
    def __init__(self, message: str, code: str = "advisor_error") -> None:
        super().__init__(message)
        self.code = code


class AdvisorProvider(Protocol):
    name: str

    async def consult(self, outbound: dict[str, Any]) -> AdvisorResponse: ...


ConsultFn = Callable[[dict[str, Any]], Awaitable[AdvisorResponse]]


def _estimate_bytes(value: Any) -> int:
    return len(json.dumps(value, default=str, ensure_ascii=False).encode("utf-8"))


def _estimate_tokens(payload: dict[str, Any]) -> int:
    return max(1, _estimate_bytes(payload) // 4)


def _scrub_outbound(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if lowered in FORBIDDEN_OUTBOUND_KEYS:
            continue
        cleaned[key] = value
    return cleaned


def build_disclosure_package(
    *,
    goal: str,
    task_class: str = "mixed",
    observations: list[str] | None = None,
    failed_approaches: list[str] | None = None,
    unresolved_problem: str = "",
    relevant_files: list[str] | None = None,
    retained_facts: list[str] | None = None,
    escalation: EscalationDecision | None = None,
    package_id: str | None = None,
    cost_estimate_usd: float | None = 0.02,
) -> AdvisorDisclosurePackage:
    """Build a policy-approved outbound disclosure package for advisor review."""
    ident = package_id or f"adv-{uuid.uuid4().hex[:12]}"
    created = datetime.now(timezone.utc).isoformat()
    fields: list[DisclosureField] = []
    outbound: dict[str, Any] = {
        "goal": goal,
        "task_class": task_class,
        "unresolved_problem": unresolved_problem or goal,
        "observations": list(observations or [])[-8:],
        "failed_approaches": list(failed_approaches or [])[-8:],
        "relevant_files": list(relevant_files or [])[:12],
        "retained_facts": list(retained_facts or [])[:12],
    }
    if escalation is not None:
        outbound["escalation"] = escalation.as_dict()
    outbound = _scrub_outbound(outbound)
    for key, value in outbound.items():
        fields.append(
            DisclosureField(
                key=key,
                label=key.replace("_", " ").title(),
                value=value,
                bytes_estimate=_estimate_bytes(value),
                leaves_local=True,
            )
        )
    local_only = [
        "local tool registry",
        "filesystem access tokens",
        "private auth keys",
        "full chat transcript",
        "undeclared environment variables",
    ]
    return AdvisorDisclosurePackage(
        id=ident,
        version=ADVISOR_INTERFACE_VERSION,
        created_at=created,
        goal=goal,
        task_class=task_class,
        fields=fields,
        local_only_retained=local_only,
        outbound=outbound,
        token_estimate=_estimate_tokens(outbound),
        cost_estimate_usd=cost_estimate_usd,
    )


def validate_advisor_response(response: AdvisorResponse | dict[str, Any]) -> None:
    """Ensure the advisor did not return execution authority or tool calls."""
    payload = response if isinstance(response, dict) else response.as_dict()
    if payload.get("tool_calls"):
        raise AdvisorError("advisor returned tool_calls", code="authority_violation")
    raw = json.dumps(payload, default=str)
    for marker in FORBIDDEN_RESPONSE_MARKERS:
        if marker in raw:
            raise AdvisorError(f"advisor response contains forbidden marker: {marker}", code="authority_violation")


def advisor_has_execution_channel(provider: Any) -> bool:
    """Advisors must not expose Jarvis tool execution entry points."""
    forbidden = ("execute_tool", "invoke_tool", "call_tool", "run_tool", "capability_token")
    for name in forbidden:
        if callable(getattr(provider, name, None)):
            return True
    token = getattr(provider, "capability_token", None)
    return bool(token)


class StubAdvisorProvider:
    """Generic advisor for tests and offline development."""

    name = "stub"

    def __init__(self, analysis: str = "Review the retained facts and retry locally.") -> None:
        self.analysis = analysis

    async def consult(self, outbound: dict[str, Any]) -> AdvisorResponse:
        goal = str(outbound.get("goal") or "")
        return AdvisorResponse(
            used=True,
            analysis=self.analysis,
            recommendations=[
                "Break the task into smaller verified steps.",
                f"Focus on unresolved problem: {outbound.get('unresolved_problem') or goal}",
            ],
            structured_plan={"steps": ["restate goal", "apply smallest fix", "verify"]},
            advisor_name=self.name,
            reason="stub advisor response",
        )


class AdvisorOrchestrator:
    """Retain execution authority locally while consulting remote advisors."""

    def __init__(self) -> None:
        self._packages: dict[str, AdvisorDisclosurePackage] = {}

    def preview(
        self,
        *,
        goal: str,
        task_class: str = "mixed",
        observations: list[str] | None = None,
        failed_approaches: list[str] | None = None,
        unresolved_problem: str = "",
        relevant_files: list[str] | None = None,
        retained_facts: list[str] | None = None,
        signals: LocalEscalationSignals | None = None,
        escalation_policy: EscalationPolicy | None = None,
        cost_estimate_usd: float | None = None,
    ) -> AdvisorDisclosurePackage:
        escalation = evaluate_escalation(signals or LocalEscalationSignals(), escalation_policy)
        package = build_disclosure_package(
            goal=goal,
            task_class=task_class,
            observations=observations,
            failed_approaches=failed_approaches,
            unresolved_problem=unresolved_problem,
            relevant_files=relevant_files,
            retained_facts=retained_facts,
            escalation=escalation,
            cost_estimate_usd=cost_estimate_usd,
        )
        self._packages[package.id] = package
        return package

    def get_package(self, package_id: str) -> AdvisorDisclosurePackage | None:
        return self._packages.get(package_id)

    def list_packages(self) -> list[AdvisorDisclosurePackage]:
        return list(self._packages.values())

    async def escalate(
        self,
        package_id: str,
        provider: AdvisorProvider | None = None,
        *,
        escalation_policy: EscalationPolicy | None = None,
        signals: LocalEscalationSignals | None = None,
    ) -> AdvisorResponse:
        package = self._packages.get(package_id)
        if package is None:
            raise AdvisorError(f"unknown advisor package {package_id}", code="package_not_found")
        decision = evaluate_escalation(signals or LocalEscalationSignals(), escalation_policy)
        if not decision.should_escalate and not (signals and signals.user_requested):
            return AdvisorResponse(
                used=False,
                reason=decision.reason or "escalation denied by policy",
                advisor_name=getattr(provider, "name", ""),
            )
        if provider is None:
            return AdvisorResponse(used=False, reason="no advisor provider configured")
        if advisor_has_execution_channel(provider):
            raise AdvisorError("advisor exposes execution channel", code="authority_violation")
        outbound = package.outbound_preview()
        response = await provider.consult(outbound)
        validate_advisor_response(response)
        response.used = True
        response.advisor_name = getattr(provider, "name", response.advisor_name)
        return response


ORCHESTRATOR = AdvisorOrchestrator()
