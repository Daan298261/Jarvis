"""Recommend node class / role policies from detected hardware (one-node swarm)."""

from __future__ import annotations

from typing import Any

from .hardware import HardwareInfo, detect_hardware
from .swarm.roles import (
    ASSIGNMENT_AUTO,
    ASSIGNMENT_FORCED,
    ASSIGNMENT_PREFERRED,
    ROLE_LEADER,
    ROLE_ORCHESTRATOR,
)


def recommend_from_hardware(hw: HardwareInfo | None = None) -> dict[str, Any]:
    """Derive setup recommendations from hardware. Does not hard-code a specific machine."""
    info = hw or detect_hardware()
    vram = int(info.vram_total_mib or 0)
    ram = float(info.ram_total_gb or 0)
    threads = int(info.cpu_threads or 1)
    has_gpu = bool(info.gpu_name) and vram > 0

    capabilities = {
        "llm_inference": has_gpu and vram >= 6000,
        "desktop_automation": info.os_name.lower().startswith("win") or info.os_name == "Windows",
        "multimedia": has_gpu and vram >= 8000,
        "coding_workloads": ram >= 16 and threads >= 8,
        "orchestrator": True,
    }

    # Class recommendation: strongest general-purpose node → Leader when GPU+RAM present.
    if has_gpu and vram >= 12000 and ram >= 32:
        node_class = "leader"
    elif has_gpu and vram >= 6000 and ram >= 16:
        node_class = "senior_worker"
    elif ram >= 8:
        node_class = "junior_worker"
    else:
        node_class = "peripheral"

    role_policies = {
        ROLE_ORCHESTRATOR: ASSIGNMENT_AUTO,
        ROLE_LEADER: ASSIGNMENT_PREFERRED if node_class in {"leader", "senior_worker"} else ASSIGNMENT_AUTO,
    }
    if node_class == "leader":
        role_policies[ROLE_LEADER] = ASSIGNMENT_PREFERRED
        role_policies[ROLE_ORCHESTRATOR] = ASSIGNMENT_AUTO
    if not has_gpu:
        role_policies[ROLE_LEADER] = ASSIGNMENT_AUTO

    resource_preset = "dynamic"
    if ram < 8 or (has_gpu and vram < 6000):
        resource_preset = "minimal"
    elif ram >= 48 and vram >= 12000:
        resource_preset = "dynamic"

    inference_default = "local" if capabilities["llm_inference"] else "remote"
    if not has_gpu:
        inference_default = "remote"

    suitable = [name for name, ok in capabilities.items() if ok and name != "orchestrator"]

    return {
        "recommended_class": node_class,
        "suitable_for": suitable,
        "capabilities": capabilities,
        "role_policies": role_policies,
        "resource_preset": resource_preset,
        "inference_default": inference_default,
        "notes": _notes(info, node_class, capabilities),
        "hardware_summary": {
            "hostname": getattr(info, "hostname", "") or "",
            "os_name": info.os_name,
            "cpu_name": info.cpu_name,
            "cpu_cores": info.cpu_cores,
            "cpu_threads": info.cpu_threads,
            "ram_total_gb": info.ram_total_gb,
            "gpu_name": info.gpu_name,
            "vram_total_mib": info.vram_total_mib,
            "disk_free_gb": info.disk_free_gb,
        },
    }


def _notes(info: HardwareInfo, node_class: str, capabilities: dict[str, bool]) -> list[str]:
    notes: list[str] = []
    if capabilities.get("llm_inference"):
        notes.append("Local LLM inference looks feasible on this GPU.")
    else:
        notes.append("Local LLM inference may be limited; consider remote OpenAI-compatible inference.")
    if node_class == "leader":
        notes.append("Strong GPU + RAM: suitable as Leader in a one-node swarm.")
    elif node_class == "peripheral":
        notes.append("Limited resources: Orchestrator-capable peripheral; prefer remote inference.")
    if info.os_name.lower() != "windows" and info.os_name != "Windows":
        notes.append("Desktop automation tools are Windows-oriented; some tools report unavailable here.")
    return notes


def forced_localhost_defaults() -> dict[str, str]:
    """One-node swarm defaults when the owner accepts recommendations without edits."""
    return {
        ROLE_ORCHESTRATOR: ASSIGNMENT_FORCED,
        ROLE_LEADER: ASSIGNMENT_FORCED,
    }
