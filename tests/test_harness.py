from app.inference.harness import HARNESS_CASES, run_harness
from app.providers.base import ChatResult


def test_harness_matrix_covers_context_vision_and_thinking():
    contexts = {case["context_size"] for case in HARNESS_CASES}
    thinking = {case["thinking"] for case in HARNESS_CASES}
    assert {8192, 16384, 32768} <= contexts
    assert {"off", "selective", "on"} <= thinking
    assert any(case["vision"] for case in HARNESS_CASES)
    assert any(not case["vision"] for case in HARNESS_CASES)
    assert any(case["profile"] == "fast" for case in HARNESS_CASES)
    assert any(case["profile"] == "quality" for case in HARNESS_CASES)


async def test_dry_run_harness_skips_live_measurement(jarvis_env):
    report = await run_harness(live=False, persist=True)
    payload = report.as_dict()
    assert payload["planned_cases"] == len(HARNESS_CASES)
    assert payload["measured_cases"] == 0
    assert payload["skipped_cases"] == len(HARNESS_CASES)
    assert payload["primary_metric"].startswith("successful autonomous")
    assert all(case["status"] == "skipped" for case in payload["cases"])
    assert payload["host"]["cpu_cores"] >= 1


async def test_live_harness_with_scripted_provider_records_latency(jarvis_env):
    class FastProvider:
        async def chat(self, messages, tools=None, **kwargs):
            return ChatResult(content="pong", timings={"prompt_per_second": 80.0, "predicted_per_second": 20.0})

    report = await run_harness(live=True, provider=FastProvider(), persist=False)
    measured = [case for case in report.cases if case.status == "measured"]
    skipped = [case for case in report.cases if case.status == "skipped"]
    assert measured or skipped
    if measured:
        assert measured[0].time_to_first_token_seconds is not None
        assert measured[0].tool_call_latency_ms is not None
