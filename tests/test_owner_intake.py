"""Owner-chat intake: measure, compress, or chain long pastes as ordered tasks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent import intake
from app.decision.intake import compress_text, split_segments


@pytest.fixture(autouse=True)
def _data_dir(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.agent.intake.data_dir", lambda: jarvis_env["tmp"])
    yield


def test_compress_text_keeps_head_and_tail_and_fits():
    text = "Opening ask: review the plan. " + "Filler sentence number here. " * 500 + "Deadline is Friday."
    result = compress_text(text, 600)
    assert len(result.text) <= 600
    assert result.text.startswith("Opening ask")
    assert result.text.endswith("Deadline is Friday.")
    assert "[…]" in result.text
    assert compress_text(text, 600).text == result.text  # deterministic


def test_compress_text_prefers_sentences_matching_focus():
    middle = " ".join(f"Unrelated item {i} about gardening." for i in range(200))
    text = f"Start. {middle} The invoice total is 4,200 euro. {middle} End."
    result = compress_text(text, 400, focus="what is the invoice total")
    assert "invoice total is 4,200" in result.text


def test_split_segments_respects_limit_and_keeps_content():
    text = "Sentence. " * 1000
    segments = split_segments(text, 500)
    assert all(len(segment) <= 500 for segment in segments)
    assert sum(len(segment) for segment in segments) >= len(text.strip()) * 0.95


def test_short_message_is_direct():
    plan = intake.plan_owner_intake("hello there", context_tokens=8192)
    assert plan.strategy == "direct"
    assert plan.text == "hello there"


def test_long_document_is_compressed_in_ordered_segments_and_original_saved():
    paste = "Log line with details about the service. " * 4000 + "What caused the outage?"
    plan = intake.plan_owner_intake(paste, context_tokens=8192)
    assert plan.strategy == "compress"
    assert plan.tokens > plan.budget_tokens
    assert Path(plan.original_path).read_text(encoding="utf-8") == paste.strip()
    # Every part of the paste reaches the condenser, in order; nothing is skipped.
    assert len(plan.segments) > 1
    assert "".join(plan.segments).replace(" ", "") == paste.strip().replace(" ", "")
    assert plan.segments[-1].endswith("What caused the outage?")
    # Budget-sized segments, not the fixed 2,600-char RFC-0182 floor: few passes.
    assert len(plan.segments) < len(paste) // 2600


def test_long_instruction_list_runs_sequentially():
    steps = "\n".join(
        f"{i}. Update module {i} and write the migration notes. " + "Details about the change. " * 60
        for i in range(1, 7)
    )
    plan = intake.plan_owner_intake(steps, context_tokens=4096)
    assert plan.strategy == "sequential"
    assert 1 < len(plan.segments) <= intake.MAX_SEQUENTIAL_PARTS


class _FakeAgent:
    def __init__(self) -> None:
        self.created: list[tuple[str, str]] = []

    async def create_task(self, prompt, request_id=None, **_kwargs):
        self.created.append((request_id, prompt))
        return SimpleNamespace(id=request_id)


def test_chain_submits_parts_in_order_with_carryover(monkeypatch):
    fake = _FakeAgent()
    monkeypatch.setattr("app.agent.loop.AGENT", fake)
    plan = intake.IntakePlan("sequential", 9000, 1000, "x", segments=["do A", "do B", "do C"])

    async def scenario():
        chain = await intake.start_sequential_chain(plan, conversation_id="c1")
        first = chain["task_ids"][0]
        assert first == intake.part_request_id(chain["id"], 1)
        second = await intake.advance_chain(first, status="completed", result="A is done")
        # A duplicate terminal event for part 1 must not fire part 2 again.
        assert await intake.advance_chain(first, status="completed", result="A is done") is None
        third = await intake.advance_chain(second, status="completed", result="B is done")
        assert await intake.advance_chain(third, status="completed", result="C done") is None
        return chain["id"]

    chain_id = asyncio.run(scenario())
    assert [rid for rid, _ in fake.created] == [intake.part_request_id(chain_id, n) for n in (1, 2, 3)]
    assert "Result of part 1:\nA is done" in fake.created[1][1]
    assert "final part" in fake.created[2][1]
    assert intake.chain_status(chain_id)["status"] == "completed"


def test_chain_stops_when_a_part_fails(monkeypatch):
    fake = _FakeAgent()
    monkeypatch.setattr("app.agent.loop.AGENT", fake)
    plan = intake.IntakePlan("sequential", 9000, 1000, "x", segments=["do A", "do B"])

    async def scenario():
        chain = await intake.start_sequential_chain(plan)
        assert await intake.advance_chain(chain["task_ids"][0], status="failed") is None
        return chain["id"]

    chain_id = asyncio.run(scenario())
    assert len(fake.created) == 1
    status = intake.chain_status(chain_id)
    assert status["status"] == "stopped"
    assert "part 1 failed" in status["stopped_reason"]


def test_unrelated_task_ids_are_ignored():
    assert asyncio.run(intake.advance_chain("some-uuid", status="completed")) is None
    assert intake.chain_status("../../etc") is None
