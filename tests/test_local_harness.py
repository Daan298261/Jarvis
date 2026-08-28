from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agent.advisor import (
    ORCHESTRATOR,
    AdvisorError,
    AdvisorResponse,
    StubAdvisorProvider,
    advisor_has_execution_channel,
    build_disclosure_package,
    validate_advisor_response,
)
from app.agent.compaction import SUMMARY_MARKER
from app.agent.local_harness import (
    CORE_PROMPT_VERSION,
    CORE_TOOL_SURFACE_VERSION,
    CORE_TOOL_NAMES,
    EscalationPolicy,
    LocalEscalationSignals,
    LocalHarness,
    LocalHarnessPolicy,
    check_autonomous_execution,
    evaluate_escalation,
    sandbox_available,
)
from app.main import app
from app.providers.base import ChatMessage


def _long_history(rounds: int = 12) -> list[ChatMessage]:
    messages = [
        ChatMessage(role="system", content="You are Jarvis."),
        ChatMessage(role="user", content="Do the thing."),
    ]
    for index in range(rounds):
        messages.append(
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[{"id": f"c{index}", "type": "function", "function": {"name": "filesystem", "arguments": "{}"}}],
            )
        )
        messages.append(
            ChatMessage(role="tool", name="filesystem", tool_call_id=f"c{index}", content=f"result {index}")
        )
    return messages


def test_core_prompt_and_tool_surface_are_versioned():
    harness = LocalHarness()
    surface = harness.build_surface(LocalHarnessPolicy(task_class="filesystem"))
    assert surface.metrics.core_prompt_version == CORE_PROMPT_VERSION
    assert surface.metrics.tool_surface_version == CORE_TOOL_SURFACE_VERSION
    assert surface.metrics.tool_count >= len(CORE_TOOL_NAMES)


def test_tool_surface_is_restricted_by_policy():
    harness = LocalHarness()
    policy = LocalHarnessPolicy(
        task_class="filesystem",
        allowed_tools=["filesystem", "python"],
        required_tools=["python"],
    )
    surface = harness.build_surface(policy)
    assert "filesystem" in surface.tool_names
    assert "python" in surface.tool_names
    assert "terminal" not in surface.tool_names
    assert "browser" not in surface.tool_names


def test_skills_load_on_demand_from_task_class():
    harness = LocalHarness()
    surface = harness.build_surface(LocalHarnessPolicy(task_class="shell"), goal="run tests")
    assert any("terminal" in block.lower() for block in surface.skill_blocks)
    assert any("test" in block.lower() for block in surface.skill_blocks)


def test_compaction_produces_provenance_and_retained_facts():
    harness = LocalHarness()
    result = harness.compact_context(
        _long_history(),
        critical_facts=["user wants the report saved"],
        keep_last=4,
    )
    assert result.provenance.source_message_count == len(_long_history())
    assert result.provenance.summarized_indices
    assert result.summary or any(SUMMARY_MARKER in (m.content or "") for m in result.messages if m.role == "system")
    assert "user wants the report saved" in result.retained_facts


def test_autonomous_execution_fails_closed_without_sandbox(monkeypatch):
    monkeypatch.setattr("app.agent.local_harness.sandbox_available", lambda: False)
    gate = check_autonomous_execution(
        LocalHarnessPolicy(autonomy="autonomous", require_sandbox=True),
    )
    assert gate.allowed is False
    assert gate.code == "sandbox_unavailable"


def test_autonomous_execution_allowed_when_sandbox_present(monkeypatch):
    monkeypatch.setattr("app.agent.local_harness.sandbox_available", lambda: True)
    gate = check_autonomous_execution(
        LocalHarnessPolicy(autonomy="autonomous", require_sandbox=True),
    )
    assert gate.allowed is True
    assert gate.code == "sandbox_ready"


def test_router_escalates_under_policy_limits():
    decision = evaluate_escalation(
        LocalEscalationSignals(consecutive_failures=3, confidence=0.4, local_attempts=2),
        EscalationPolicy(max_cost_usd=0.10, advisor_cost_usd=0.02),
    )
    assert decision.should_escalate is True
    assert decision.estimated_cost_usd == 0.02


def test_router_blocks_escalation_when_cost_exceeds_policy():
    decision = evaluate_escalation(
        LocalEscalationSignals(user_requested=True),
        EscalationPolicy(max_cost_usd=0.01, advisor_cost_usd=0.02),
    )
    assert decision.should_escalate is False
    assert decision.code == "cost_exceeded"


def test_advisor_disclosure_lists_exact_outbound_fields():
    package = build_disclosure_package(
        goal="Fix the failing test",
        task_class="software engineering",
        observations=["pytest failed on auth"],
        failed_approaches=["edited wrong file"],
        retained_facts=["must not change models.py"],
    )
    preview = package.outbound_preview()
    assert preview["goal"] == "Fix the failing test"
    assert "auth_token" not in preview
    assert "capability_token" not in preview
    assert any(field.key == "observations" for field in package.fields)
    assert package.local_only_retained


def test_advisor_has_no_execution_channel():
    provider = StubAdvisorProvider()
    assert advisor_has_execution_channel(provider) is False


@pytest.mark.asyncio
async def test_advisor_response_is_analysis_only():
    provider = StubAdvisorProvider("Try a smaller reproduction.")
    package = build_disclosure_package(goal="unblock task")
    response = await provider.consult(package.outbound_preview())
    validate_advisor_response(response)
    assert response.tool_calls is None if hasattr(response, "tool_calls") else True
    payload = response.as_dict()
    assert payload["tool_calls"] is None
    assert payload["execution_authority"] == "orchestrator"


@pytest.mark.asyncio
async def test_advisor_orchestrator_rejects_execution_channel_provider():
    class BadProvider:
        name = "bad"

        capability_token = "secret"

        async def consult(self, outbound):
            return AdvisorResponse(used=True, analysis="noop")

    package = ORCHESTRATOR.preview(
        goal="stuck",
        signals=LocalEscalationSignals(user_requested=True, local_attempts=1),
    )
    with pytest.raises(AdvisorError) as exc:
        await ORCHESTRATOR.escalate(
            package.id,
            BadProvider(),
            signals=LocalEscalationSignals(user_requested=True, local_attempts=1),
        )
    assert exc.value.code == "authority_violation"


def test_advisor_preview_api_returns_outbound_disclosure(jarvis_env):
    client = TestClient(app)
    response = client.post(
        "/api/advisor/preview",
        json={
            "goal": "Summarize notes",
            "task_class": "filesystem",
            "observations": ["file exists"],
            "retained_facts": ["stay inside allowed dirs"],
            "consecutive_failures": 3,
            "confidence": 0.3,
            "local_attempts": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outbound_preview"]["goal"] == "Summarize notes"
    assert "local_only_retained" in body
    assert body["token_estimate"] > 0


@pytest.mark.asyncio
async def test_advisor_escalate_api_uses_stub_provider(jarvis_env):
    client = TestClient(app)
    preview = client.post(
        "/api/advisor/preview",
        json={
            "goal": "Need help",
            "user_requested": True,
            "local_attempts": 1,
        },
    ).json()
    escalated = client.post(
        "/api/advisor/escalate",
        json={
            "package_id": preview["id"],
            "user_requested": True,
            "local_attempts": 1,
        },
    )
    assert escalated.status_code == 200
    body = escalated.json()
    assert body["used"] is True
    assert body["tool_calls"] is None
    assert body["analysis"]


def test_sandbox_probe_is_boolean():
    assert isinstance(sandbox_available(), bool)
