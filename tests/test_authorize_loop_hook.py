from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.agent.loop import AGENT, _authorization_observation
from app.config import AppSettings
from app.policy.authorize import AuthorizationResult
from app.policy.levels import AutonomyLevel
from app.tools.base import RiskLevel, ToolResult


@pytest.fixture
def settings(jarvis_env):
    return jarvis_env["settings"]


def _denied_result() -> AuthorizationResult:
    return AuthorizationResult(
        allowed=False,
        requires_approval=False,
        reason="effective autonomy L1_SUGGEST does not permit tool execution",
        effective_level=AutonomyLevel.L1_SUGGEST,
        capability="filesystem.read",
    )


def _approval_required_result() -> AuthorizationResult:
    return AuthorizationResult(
        allowed=False,
        requires_approval=True,
        reason="high-risk action requires approval at L3_EXECUTE_WITH_GATES",
        effective_level=AutonomyLevel.L3_EXECUTE_WITH_GATES,
        capability="terminal.exec",
    )


def _allowed_result() -> AuthorizationResult:
    return AuthorizationResult(
        allowed=True,
        requires_approval=False,
        reason="low-risk execution permitted",
        effective_level=AutonomyLevel.L3_EXECUTE_WITH_GATES,
        capability="filesystem.read",
    )


@pytest.mark.asyncio
async def test_execute_tool_ex_denies_before_registry_execute(monkeypatch, settings):
    execute_mock = AsyncMock(return_value=ToolResult(True, "should not run"))
    monkeypatch.setattr("app.agent.loop.REGISTRY.execute", execute_mock)
    monkeypatch.setattr(
        "app.agent.loop.authorize",
        lambda *args, **kwargs: _denied_result(),
    )

    observation, attach = await AGENT._execute_tool_ex(
        "task-deny",
        "filesystem",
        {"action": "read", "path": "/tmp/example.txt"},
        "trusted",
        settings,
    )

    execute_mock.assert_not_awaited()
    assert attach is None
    assert observation.startswith("ERROR: Authorization denied:")
    payload = json.loads(observation.split("\n", 1)[1])
    assert payload["authorization"]["allowed"] is False
    assert payload["authorization"]["requires_approval"] is False


@pytest.mark.asyncio
async def test_execute_tool_denies_before_registry_execute(monkeypatch, settings):
    execute_mock = AsyncMock(return_value=ToolResult(True, "should not run"))
    monkeypatch.setattr("app.agent.loop.REGISTRY.execute", execute_mock)
    monkeypatch.setattr(
        "app.agent.loop.authorize",
        lambda *args, **kwargs: _denied_result(),
    )

    observation = await AGENT._execute_tool(
        "task-deny",
        "filesystem",
        {"action": "read", "path": "/tmp/example.txt"},
        "trusted",
        settings,
    )

    execute_mock.assert_not_awaited()
    assert observation.startswith("ERROR: Authorization denied:")


@pytest.mark.asyncio
async def test_execute_tool_ex_allows_and_runs_tool(monkeypatch, settings):
    execute_mock = AsyncMock(return_value=ToolResult(True, "ok"))
    monkeypatch.setattr("app.agent.loop.REGISTRY.execute", execute_mock)
    monkeypatch.setattr(
        "app.agent.loop.authorize",
        lambda *args, **kwargs: _allowed_result(),
    )

    observation, attach = await AGENT._execute_tool_ex(
        "task-allow",
        "filesystem",
        {"action": "read", "path": "/tmp/example.txt"},
        "trusted",
        settings,
    )

    execute_mock.assert_awaited_once_with("filesystem", {"action": "read", "path": "/tmp/example.txt"})
    assert observation == "ok"
    assert attach is None


@pytest.mark.asyncio
async def test_execute_tool_ex_requires_approval_without_execute(monkeypatch, settings):
    execute_mock = AsyncMock(return_value=ToolResult(True, "should not run"))
    monkeypatch.setattr("app.agent.loop.REGISTRY.execute", execute_mock)
    monkeypatch.setattr(
        "app.agent.loop.authorize",
        lambda *args, **kwargs: _approval_required_result(),
    )

    observation, attach = await AGENT._execute_tool_ex(
        "task-approval",
        "terminal",
        {"command": "echo hi"},
        "trusted",
        settings,
    )

    execute_mock.assert_not_awaited()
    assert attach is None
    assert observation.startswith("ERROR: Authorization approval required:")
    payload = json.loads(observation.split("\n", 1)[1])
    assert payload["authorization"]["requires_approval"] is True


@pytest.mark.asyncio
async def test_execute_tool_ex_approved_high_risk_runs_tool(monkeypatch, settings):
    execute_mock = AsyncMock(return_value=ToolResult(True, "ran"))
    monkeypatch.setattr("app.agent.loop.REGISTRY.execute", execute_mock)

    def _authorize(*args, **kwargs):
        if kwargs.get("approved"):
            return AuthorizationResult(
                allowed=True,
                requires_approval=False,
                reason="approved high-risk execution",
                effective_level=AutonomyLevel.L3_EXECUTE_WITH_GATES,
                capability="terminal.exec",
            )
        return _approval_required_result()

    monkeypatch.setattr("app.agent.loop.authorize", _authorize)

    observation, attach = await AGENT._execute_tool_ex(
        "task-approved",
        "terminal",
        {"command": "echo hi"},
        "trusted",
        settings,
        approved=True,
    )

    execute_mock.assert_awaited_once()
    assert observation == "ran"
    assert attach is None


def test_authorization_observation_formats_structured_payload():
    denied = _authorization_observation(_denied_result())
    assert denied.startswith("ERROR: Authorization denied:")
    payload = json.loads(denied.split("\n", 1)[1])
    assert payload["authorization"]["effective_level"] == AutonomyLevel.L1_SUGGEST.value

    pending = _authorization_observation(_approval_required_result())
    assert pending.startswith("ERROR: Authorization approval required:")
    pending_payload = json.loads(pending.split("\n", 1)[1])
    assert pending_payload["authorization"]["requires_approval"] is True
