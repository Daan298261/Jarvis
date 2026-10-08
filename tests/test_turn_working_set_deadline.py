"""T4a: turn working-set compose must not stall the loop, must overlap vault
and Supermemory, and must report timeout / source failure distinctly.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.agent.turn_working_set import (
    COMPOSITION_OK,
    COMPOSITION_TIMEOUT,
    DEFAULT_WORKING_SET_DEADLINE_MS,
    MEMORY_RETRIEVAL_ERROR,
    MEMORY_RETRIEVAL_HITS,
    MEMORY_RETRIEVAL_MISS,
    MEMORY_RETRIEVAL_SKIPPED,
    MEMORY_RETRIEVAL_TIMEOUT,
    TOOLS_STATUS_OK,
    VAULT_RETRIEVAL_ERROR,
    VAULT_RETRIEVAL_HITS,
    VAULT_RETRIEVAL_IDLE,
    VAULT_RETRIEVAL_MISS,
    VAULT_RETRIEVAL_SKIPPED,
    VAULT_RETRIEVAL_TIMEOUT,
    _MemoryComposeResult,
    _ToolComposeResult,
    _compose_memory_working_set,
    compose_turn_working_set,
)
from app.config import AppSettings
from app.memory import supermemory


def _empty_tools(*_a, **_k) -> _ToolComposeResult:
    return _ToolComposeResult(searched=[], names=[], schemas=[], offers=[], exposure="tools-ok")


@pytest.mark.asyncio
async def test_blocking_vault_work_does_not_stall_event_loop(monkeypatch):
    monkeypatch.setattr("app.agent.turn_working_set._working_set_deadline_seconds", lambda: 2.0)
    monkeypatch.setattr("app.agent.turn_working_set._tools_job", _empty_tools)

    def slow_vault(_prompt: str):
        time.sleep(0.2)
        return "", [], VAULT_RETRIEVAL_IDLE, ""

    monkeypatch.setattr("app.agent.turn_working_set._vault_job", slow_vault)

    ticks: list[int] = []

    async def ticker() -> None:
        for index in range(8):
            ticks.append(index)
            await asyncio.sleep(0.02)

    compose = asyncio.create_task(
        compose_turn_working_set(
            "hello",
            include_memory=False,
            include_vault=True,
            needs_tools=False,
        )
    )
    await asyncio.gather(compose, ticker())
    # A 200ms sleep on the event loop would leave ticks empty until compose finished.
    assert len(ticks) >= 6
    ws = compose.result()
    assert ws.composition_status == COMPOSITION_OK
    assert ws.vault_retrieval == VAULT_RETRIEVAL_IDLE


@pytest.mark.asyncio
async def test_vault_and_supermemory_run_concurrently(monkeypatch):
    monkeypatch.setattr("app.agent.turn_working_set._working_set_deadline_seconds", lambda: 2.0)
    monkeypatch.setattr("app.agent.turn_working_set._tools_job", _empty_tools)
    starts: dict[str, float] = {}

    def slow_vault(_prompt: str):
        starts["vault"] = time.perf_counter()
        time.sleep(0.12)
        return "vault-block", [], VAULT_RETRIEVAL_IDLE, ""

    async def slow_memory(_agent_id: str, _query: str) -> _MemoryComposeResult:
        starts["memory"] = time.perf_counter()
        await asyncio.sleep(0.12)
        return _MemoryComposeResult("memory-block", MEMORY_RETRIEVAL_HITS, source="supermemory")

    monkeypatch.setattr("app.agent.turn_working_set._vault_job", slow_vault)
    monkeypatch.setattr("app.agent.turn_working_set._compose_memory_working_set", slow_memory)

    t0 = time.perf_counter()
    ws = await compose_turn_working_set(
        "what did we decide",
        include_vault=True,
        include_memory=True,
        needs_tools=False,
    )
    elapsed = time.perf_counter() - t0

    assert "vault" in starts and "memory" in starts
    assert abs(starts["vault"] - starts["memory"]) < 0.05
    # Sequential 0.12+0.12 would land near 0.24s+; overlap stays near 0.12s.
    assert elapsed < 0.22
    assert ws.vault_block == "vault-block"
    assert ws.memory_facts_block == "memory-block"
    assert ws.memory_retrieval == MEMORY_RETRIEVAL_HITS
    assert ws.composition_status == COMPOSITION_OK


@pytest.mark.asyncio
async def test_deadline_returns_explicit_timeout_status_not_silent_empty(monkeypatch):
    monkeypatch.setattr("app.agent.turn_working_set._working_set_deadline_seconds", lambda: 0.05)
    monkeypatch.setattr("app.agent.turn_working_set._tools_job", _empty_tools)

    def slow_vault(_prompt: str):
        time.sleep(0.25)
        return "late-vault-hit", [], VAULT_RETRIEVAL_HITS, ""

    monkeypatch.setattr("app.agent.turn_working_set._vault_job", slow_vault)

    t0 = time.perf_counter()
    ws = await compose_turn_working_set(
        "what is our project decision",
        include_vault=True,
        include_memory=False,
        needs_tools=False,
    )
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.2
    assert ws.composition_status == COMPOSITION_TIMEOUT
    assert "vault" in ws.timed_out_sources
    assert ws.vault_retrieval == VAULT_RETRIEVAL_TIMEOUT
    assert ws.vault_retrieval not in {
        VAULT_RETRIEVAL_MISS,
        VAULT_RETRIEVAL_IDLE,
        VAULT_RETRIEVAL_SKIPPED,
        VAULT_RETRIEVAL_HITS,
    }
    assert ws.vault_hits == []
    assert "timed out" in ws.vault_block.lower()
    assert "late-vault-hit" not in ws.vault_block


@pytest.mark.asyncio
async def test_failing_vault_source_is_distinct_from_empty_miss(monkeypatch):
    monkeypatch.setattr("app.agent.turn_working_set._working_set_deadline_seconds", lambda: 2.0)
    monkeypatch.setattr("app.agent.turn_working_set._tools_job", _empty_tools)

    def boom_vault(_prompt: str):
        raise RuntimeError("vault index unreadable")

    monkeypatch.setattr("app.agent.turn_working_set._compose_vault_working_set", boom_vault)

    ws = await compose_turn_working_set(
        "what is our project decision",
        include_vault=True,
        include_memory=False,
        needs_tools=False,
    )
    assert ws.composition_status == COMPOSITION_OK
    assert ws.vault_retrieval == VAULT_RETRIEVAL_ERROR
    assert ws.vault_retrieval != VAULT_RETRIEVAL_MISS
    assert "vault" in ws.source_errors
    assert "unreadable" in ws.source_errors["vault"]
    assert "failed" in ws.vault_block.lower()
    assert ws.timed_out_sources == []


@pytest.mark.asyncio
async def test_failing_memory_source_is_distinct_from_empty_miss(monkeypatch):
    monkeypatch.setattr("app.agent.turn_working_set._working_set_deadline_seconds", lambda: 2.0)
    monkeypatch.setattr("app.agent.turn_working_set._tools_job", _empty_tools)

    async def boom_memory(_agent_id: str, _query: str) -> _MemoryComposeResult:
        return _MemoryComposeResult("", MEMORY_RETRIEVAL_ERROR, error="sidecar refused")

    async def empty_memory(_agent_id: str, _query: str) -> _MemoryComposeResult:
        return _MemoryComposeResult("", MEMORY_RETRIEVAL_MISS)

    monkeypatch.setattr("app.agent.turn_working_set._compose_memory_working_set", boom_memory)
    failed = await compose_turn_working_set(
        "remember my preferences",
        include_vault=False,
        include_memory=True,
        needs_tools=False,
    )
    assert failed.memory_retrieval == MEMORY_RETRIEVAL_ERROR
    assert failed.memory_retrieval != MEMORY_RETRIEVAL_MISS
    assert failed.memory_retrieval != MEMORY_RETRIEVAL_SKIPPED
    assert "memory" in failed.source_errors
    assert "refused" in failed.source_errors["memory"]
    assert "failed" in failed.memory_facts_block.lower()

    monkeypatch.setattr("app.agent.turn_working_set._compose_memory_working_set", empty_memory)
    missed = await compose_turn_working_set(
        "remember my preferences",
        include_vault=False,
        include_memory=True,
        needs_tools=False,
    )
    assert missed.memory_retrieval == MEMORY_RETRIEVAL_MISS
    assert missed.memory_retrieval != MEMORY_RETRIEVAL_ERROR
    assert missed.source_errors == {}
    assert missed.memory_facts_block == ""
    assert missed.composition_status == COMPOSITION_OK
    assert missed.tools_status == TOOLS_STATUS_OK


def test_default_working_set_deadline_fits_front_lane_budget():
    settings = AppSettings()
    assert settings.working_set_deadline_ms == DEFAULT_WORKING_SET_DEADLINE_MS
    assert settings.working_set_deadline_ms == 400
    # Front-lane ack timeout is 1500ms; retrieval must stay a fraction of that.
    assert settings.working_set_deadline_ms < settings.front_responder.timeout_ms
    assert settings.working_set_deadline_ms > settings.decision.reflex_default_deadline_ms


@pytest.mark.asyncio
async def test_compose_reads_deadline_from_settings(monkeypatch):
    settings = AppSettings()
    settings.working_set_deadline_ms = 50
    monkeypatch.setattr("app.config.load_settings", lambda: settings)
    monkeypatch.setattr("app.agent.turn_working_set._tools_job", _empty_tools)

    def slow_vault(_prompt: str):
        time.sleep(0.2)
        return "late", [], VAULT_RETRIEVAL_HITS, ""

    monkeypatch.setattr("app.agent.turn_working_set._vault_job", slow_vault)
    ws = await compose_turn_working_set("ask", include_vault=True, include_memory=False, needs_tools=False)
    assert ws.composition_status == COMPOSITION_TIMEOUT
    assert ws.vault_retrieval == VAULT_RETRIEVAL_TIMEOUT
    assert MEMORY_RETRIEVAL_TIMEOUT not in (ws.memory_retrieval,)
    assert ws.memory_retrieval == MEMORY_RETRIEVAL_SKIPPED


@pytest.mark.asyncio
async def test_supermemory_request_failure_is_not_a_miss(monkeypatch):
    async def failed_search(*_a, **_k):
        raise supermemory.SupermemoryError("offline")

    async def empty_repo(_agent_id):
        return SimpleNamespace(entries=[])

    monkeypatch.setattr(supermemory, "search", failed_search)
    monkeypatch.setattr("app.memory.repository.get_repo", empty_repo)

    result = await _compose_memory_working_set("owner", "What are Taco response preferences?")
    assert result.status == MEMORY_RETRIEVAL_ERROR
    assert result.status != MEMORY_RETRIEVAL_MISS
    assert "offline" in result.error


@pytest.mark.asyncio
async def test_disabled_supermemory_empty_native_is_a_miss(monkeypatch):
    async def not_configured(*_a, **_k):
        raise supermemory.SupermemoryNotConfigured("disabled")

    async def empty_repo(_agent_id):
        return SimpleNamespace(entries=[])

    monkeypatch.setattr(supermemory, "search", not_configured)
    monkeypatch.setattr("app.memory.repository.get_repo", empty_repo)

    result = await _compose_memory_working_set("owner", "What are Taco response preferences?")
    assert result.status == MEMORY_RETRIEVAL_MISS
    assert result.error == ""
