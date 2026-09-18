import pytest

from app.agent.ingress_gate import run_ingress_gate
from app.memory.ingress_spill import read_ingress, store_ingress_blob


@pytest.mark.asyncio
async def test_size_gate_does_not_pass_full_blob_to_front(jarvis_env):
    blob = "X" * 20_000
    seen: list[str] = []

    async def fake_classify(*, metadata, preview, user_ask, **kwargs):
        seen.append(preview)
        return {
            "size_class": "big",
            "needs_tools": False,
            "complexity_hint": 2,
            "front_action": "ack_continue",
        }

    gate = await run_ingress_gate(
        user_text=blob,
        task_class="mixed",
        task_id="task-ingress-1",
        classify_fn=fake_classify,
    )
    assert gate.size_class == "big"
    assert gate.blob_id
    assert len(seen) == 1
    assert len(seen[0]) < len(blob) / 10


@pytest.mark.asyncio
async def test_spill_then_segmented_read(jarvis_env):
    body = "segment-" + ("A" * 5000) + "-segment-" + ("B" * 5000)
    row = await store_ingress_blob(body=body, task_id="task-ingress-2")
    blob_id = row.root_id or row.id
    first = await read_ingress(blob_id, 0, 1200)
    second = await read_ingress(blob_id, 1200, 1200)
    assert first.startswith("segment-")
    assert second
    assert first != second
