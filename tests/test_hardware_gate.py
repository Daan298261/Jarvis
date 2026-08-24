from fastapi.testclient import TestClient

from app.inference.hardware_gate import DEFERRED_PURCHASES, REQUIRED_BEFORE_PURCHASE, analyze_hardware_gate
from app.main import app


def test_gate_defers_purchase_without_desktop_evidence():
    report = analyze_hardware_gate(
        {
            "os_name": "Linux",
            "gpu_name": None,
            "vram_total_mib": None,
            "vram_free_mib": None,
            "ram_total_gb": 16,
            "ram_available_gb": 8,
        },
        samples=[],
        agent_suite_complete=False,
    )
    assert report["purchase_recommended"] is False
    assert report["decision"] == "defer_purchase"
    assert report["bottleneck"] in {"no_gpu_metrics", "insufficient_data"}
    assert "NVIDIA GPU metrics (nvidia-smi)" in report["missing_evidence"]
    for item in DEFERRED_PURCHASES:
        assert item in report["deferred_purchases"]
    assert REQUIRED_BEFORE_PURCHASE[0] in report["required_before_purchase"]


def test_gate_still_defers_when_vram_looks_saturated():
    report = analyze_hardware_gate(
        {
            "os_name": "Windows",
            "gpu_name": "NVIDIA GeForce RTX 5070 Ti",
            "vram_total_mib": 16376,
            "vram_free_mib": 200,
            "ram_total_gb": 32,
            "ram_available_gb": 12,
        },
        samples=[
            {
                "profile": "balanced",
                "quantization": "Q4_K_M",
                "tokens_per_second": 18.0,
                "vram_used_mib": 16200,
            }
        ],
        agent_suite_complete=False,
    )
    assert report["purchase_recommended"] is False
    assert report["gpu_vram_saturated"] is True
    assert report["cpu_offload_likely"] is True
    assert report["estimated_benefit_more_vram"]
    assert "completed 20-task agent suite" in " ".join(report["missing_evidence"])


def test_gate_flags_ram_but_does_not_recommend_buying():
    report = analyze_hardware_gate(
        {
            "os_name": "Windows",
            "gpu_name": "NVIDIA GeForce RTX 5070 Ti",
            "vram_total_mib": 16376,
            "vram_free_mib": 8000,
            "ram_total_gb": 16,
            "ram_available_gb": 1.5,
        },
        samples=[
            {"profile": "fast", "quantization": "Q8_0", "tokens_per_second": 40.0, "vram_used_mib": 7000},
            {"profile": "balanced", "quantization": "Q4_K_M", "tokens_per_second": 18.0, "vram_used_mib": 9000},
        ],
        agent_suite_complete=False,
    )
    assert report["system_ram_constrained"] is True
    assert report["purchase_recommended"] is False
    assert report["model_switching_costly"] is None


def test_hardware_gate_endpoint_defers(jarvis_env):
    client = TestClient(app)
    res = client.get("/api/model/hardware-gate")
    assert res.status_code == 200
    body = res.json()
    assert body["purchase_recommended"] is False
    assert body["decision"] == "defer_purchase"
    assert "additional RAM" in body["deferred_purchases"]
