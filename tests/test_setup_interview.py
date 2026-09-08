from __future__ import annotations

from backend.app.hardware import HardwareInfo
from backend.app.setup_interview import (
    plan_interview,
    render_download_script,
    render_lm_studio_script,
    render_mobile_script,
)


def hw(*, ram: float = 64, vram_mib: int | None = 16384, disk_free: float = 200) -> HardwareInfo:
    return HardwareInfo(
        os_name="Windows",
        os_version="11",
        architecture="AMD64",
        hostname="jarvis-test",
        cpu_name="Test CPU",
        cpu_cores=12,
        cpu_threads=20,
        ram_total_gb=ram,
        ram_available_gb=ram - 8,
        gpu_name="RTX Test" if vram_mib else None,
        vram_total_mib=vram_mib,
        vram_free_mib=(vram_mib - 1024) if vram_mib else None,
        nvidia_driver="999.0" if vram_mib else None,
        cuda_version="13.0" if vram_mib else None,
        disk_free_gb=disk_free,
        disk_total_gb=500,
        battery_percent=None,
        power_plugged=None,
        network_adapters=["Ethernet"],
        python_version="3.12",
        node_installed=True,
        git_installed=True,
        docker_installed=False,
        office_installed=False,
        wsl_available=True,
    )


def test_capable_coding_pc_gets_bootstrap_and_expert():
    plan = plan_interview(
        {"use": "Coding and research", "policy": "Local first", "resources": "Balanced (~50%)", "voice": "Yes"},
        hw=hw(),
    )
    selected = {row["id"] for row in plan["recommended_models"] if row["selected"]}
    assert "bootstrap_ornith" in selected
    assert "expert_qwen_27b" in selected
    assert plan["keep_loaded"] == ["bootstrap_ornith"]
    assert plan["disk"]["enough"] is True
    assert plan["answers"]["voice_enabled"] is True


def test_cpu_only_machine_does_not_auto_select_27b():
    plan = plan_interview(
        {"use": "Coding", "policy": "Local first", "resources": "Balanced", "voice": "No"},
        hw=hw(ram=64, vram_mib=None),
    )
    selected = {row["id"] for row in plan["recommended_models"] if row["selected"]}
    assert "expert_qwen_27b" not in selected
    assert "bootstrap_ornith" in selected


def test_disk_gate_reports_shortfall_before_download():
    plan = plan_interview(
        {"use": "A bit of everything", "policy": "Local first", "resources": "Balanced", "voice": "No"},
        hw=hw(disk_free=8),
    )
    assert plan["disk"]["enough"] is False
    assert plan["disk"]["shortfall_gb"] > 0
    script = render_download_script(plan)
    assert "Not enough disk space" in script
    assert "$RequiredGb" in script


def test_lm_studio_is_not_required_for_default_runtime():
    plan = plan_interview({}, hw=hw())
    assert plan["lm_studio"]["required"] is False
    assert "llama.cpp" in plan["lm_studio"]["reason"]
    script = render_lm_studio_script(plan)
    assert "LM Studio is optional" in script
    assert "No installation was performed" in script


def test_security_intent_keeps_red_team_manual_gated():
    plan = plan_interview(
        {"use": "Security monitoring and red team", "policy": "Local first", "resources": "Aggressive", "voice": "No"},
        hw=hw(),
    )
    rows = {row["id"]: row for row in plan["recommended_models"]}
    assert rows["blue_redsage"]["selected"] is True
    assert rows["red_deephat"]["selected"] is False
    assert rows["red_deephat"]["status"] == "manual authorization"


def test_mobile_plan_prefers_private_overlay_not_public_forwarding():
    plan = plan_interview({}, hw=hw())
    assert plan["mobile"]["remote_access"] == "tailscale"
    assert plan["mobile"]["router_forwarding_required"] is False
    script = render_mobile_script(plan)
    assert "Tailscale" in script
    assert "UseRouterPortForward" in script
    assert "profile=private" in script
