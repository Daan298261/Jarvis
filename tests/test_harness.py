from app.inference.harness import hardware_gate, measure_tool_call_latency_ms, run_harness
from app.providers.base import ChatMessage, ChatResult


def test_hardware_gate_blocks_purchases_without_desktop_measurements():
    gate = hardware_gate({"gpu_name": None, "vram_total_mib": None}, {}, [])
    assert gate["buy_hardware"] is False
    assert gate["bottleneck"] == "unmeasured"
    assert "Do not buy" in gate["recommendation"]


def test_hardware_gate_flags_vram_pressure_but_still_does_not_buy():
    hardware = {"gpu_name": "RTX 5070 Ti", "vram_total_mib": 16384, "ram_total_gb": 64}
    metrics = {"generation_tps": 20.0, "vram_used_mib": 15800, "load_time_seconds": 8.0, "ttft_ms": 120}
    gate = hardware_gate(hardware, metrics, [{"source": "harness"}])
    assert gate["buy_hardware"] is False
    assert gate["bottleneck"] == "gpu_vram"
    assert "90%" in gate["recommendation"]


def test_tool_probe_is_a_real_stat():
    assert measure_tool_call_latency_ms() >= 0


async def test_harness_dry_run_records_cpu_and_gate(jarvis_env, tmp_path, monkeypatch):
    monkeypatch.setattr("app.inference.harness.data_dir", lambda: tmp_path)
    report = await run_harness(loaded=False, persist=True)
    assert report.model_available is False
    assert report.buy_hardware is False
    assert report.metrics["tool_call_latency_ms"] is not None
    assert report.metrics["cpu_utilization_percent"] is not None
    assert "Do not buy" in report.hardware_recommendation
    saved = (tmp_path / "benchmarks" / "last_harness.json")
    assert saved.exists()


async def test_harness_live_probe_records_ttft(jarvis_env, tmp_path, monkeypatch):
    monkeypatch.setattr("app.inference.harness.data_dir", lambda: tmp_path)

    async def chat(messages, **kwargs):
        assert isinstance(messages[0], ChatMessage)
        return ChatResult(content="pong", timings={"prompt_per_second": 80.0, "predicted_per_second": 22.0})

    report = await run_harness(loaded=True, chat=chat, persist=False)
    assert report.model_available is True
    assert report.metrics["ttft_ms"] is not None
    assert report.metrics["prompt_tps"] == 80.0
    assert report.metrics["generation_tps"] == 22.0
