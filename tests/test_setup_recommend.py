from __future__ import annotations

from app.hardware import HardwareInfo
from app.setup_recommend import recommend_from_hardware


def _hw(**kwargs) -> HardwareInfo:
    base = dict(
        os_name="Windows",
        os_version="10",
        architecture="AMD64",
        hostname="desk-1",
        cpu_name="Test CPU",
        cpu_cores=8,
        cpu_threads=16,
        ram_total_gb=64.0,
        ram_available_gb=50.0,
        gpu_name="NVIDIA GeForce RTX 5070 Ti",
        vram_total_mib=16384,
        vram_free_mib=14000,
        nvidia_driver="560",
        cuda_version="13.0",
        disk_free_gb=400.0,
        disk_total_gb=1000.0,
        battery_percent=None,
        power_plugged=None,
        network_adapters=["Ethernet"],
        python_version="3.12",
        node_installed=True,
        git_installed=True,
        docker_installed=False,
        office_installed=True,
        wsl_available=True,
    )
    base.update(kwargs)
    return HardwareInfo(**base)


def test_strong_gpu_recommends_leader():
    rec = recommend_from_hardware(_hw())
    assert rec["recommended_class"] == "leader"
    assert "llm_inference" in rec["suitable_for"]
    assert rec["resource_preset"] == "dynamic"
    assert rec["inference_default"] == "local"
    assert "orchestrator" in rec["role_policies"]


def test_no_gpu_prefers_remote():
    rec = recommend_from_hardware(
        _hw(gpu_name=None, vram_total_mib=None, vram_free_mib=None, ram_total_gb=16)
    )
    assert rec["inference_default"] == "remote"
    assert rec["recommended_class"] in {"junior_worker", "senior_worker", "peripheral"}
