from __future__ import annotations

from pathlib import Path

from app.hardware import HardwareInfo
from app.setup_interview import (
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
    assert "HF_HOME" not in script


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


def test_mobile_plan_uses_prepare_connection_not_tailscale():
    plan = plan_interview({}, hw=hw())
    assert plan["mobile"]["remote_access"] == "companion TLS 4781"
    assert plan["mobile"]["router_forwarding_required"] is False
    assert "4781" in plan["mobile"]["router_forwarding"]
    assert plan["mobile"]["client"] == "Jarvis Android companion"
    script = render_mobile_script(plan)
    assert "Prepare connection" in script
    assert "UseRouterPortForward" in script
    assert "$Port = 4781" in script
    assert "$BeaconPort = 4782" in script
    assert "profile=any" in script
    assert "upnpc" not in script
    assert "localport=$Port" in script
    assert "localport=$BeaconPort" in script
    assert "protocol=UDP" in script
    assert "Jarvis companion LAN beacon 4782" in script
    assert "profile=private" not in script
    assert "Tailscale" not in script
    assert "winget install --id Tailscale" not in script


def _usage(free_gb: float, total_gb: float = 500.0):
    from types import SimpleNamespace

    free = int(free_gb * (1024**3))
    total = int(total_gb * (1024**3))
    return SimpleNamespace(free=free, total=total, used=max(0, total - free))


def test_setup_marks_extra_drive_expert_gguf_installed(tmp_path, monkeypatch):
    extra = tmp_path / "USB"
    named = extra / "Models"
    named.mkdir(parents=True)
    (named / "Qwen3.5-27B-Q4_K_M.gguf").write_bytes(b"gguf")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.config.extra_volume_roots", lambda: [extra])
    from app.setup_interview import MODEL_MANIFEST, _installed

    assert _installed(MODEL_MANIFEST["expert_qwen_27b"]) is True
    assert _installed(MODEL_MANIFEST["bootstrap_ornith"]) is False


def test_disk_gate_uses_extra_volume_when_os_volume_is_full(tmp_path, monkeypatch):
    extra = tmp_path / "D"
    extra.mkdir()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.config.extra_volume_roots", lambda: [extra])

    def fake_usage(path):
        text = str(path)
        extra_key = str(extra)
        if text == extra_key or text.startswith(str(extra / "Jarvis")):
            return _usage(400)
        return _usage(1)

    monkeypatch.setattr("app.inference.lmstudio_catalog.shutil.disk_usage", fake_usage)
    plan = plan_interview(
        {"use": "Coding and research", "policy": "Local first", "resources": "Balanced", "voice": "No"},
        hw=hw(disk_free=8),
    )
    assert plan["disk"]["enough"] is True
    assert plan["disk"]["using_extra_volume"] is True
    assert "Jarvis" in plan["disk"]["install_root"].replace("\\", "/")
    script = render_download_script(plan)
    assert "Join-Path $Root 'models'" not in script
    assert "Jarvis" in script
    assert "Not enough disk space" in script
    assert "$env:HF_HOME = Join-Path $Models 'huggingface'" in script
    assert "$env:HF_HUB_CACHE = Join-Path $env:HF_HOME 'hub'" in script


def test_discover_component_states_ready_when_primary_is_on_extra_volume(tmp_path, monkeypatch):
    from app.inference.profiles import PROFILES
    from app.runtime_install import discover_component_states

    extra = tmp_path / "USB"
    named = extra / "Models"
    named.mkdir(parents=True)
    gguf = named / PROFILES["balanced"].filename
    gguf.write_bytes(b"gguf")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.config.extra_volume_roots", lambda: [extra])
    states = discover_component_states(include_optional_expert=False)
    assert states["primary_model"].status == "ready"
    assert Path(states["primary_model"].path).resolve() == gguf.resolve()
