"""P0.12 — hardware purchasing gate.

Do not recommend buying RAM, extra GPUs, NPUs, or inference boxes until the
local benchmark suite has produced real measurements on this desktop.
"""

from __future__ import annotations

from typing import Any

from ..hardware import HardwareInfo, detect_hardware


MIN_INFERENCE_SAMPLES = 3
MIN_AGENT_RESULTS = 5

DEFERRED_PURCHASES = (
    "additional RAM",
    "old Tesla GPUs",
    "V100 GPUs",
    "NPUs",
    "additional inference hardware",
)


def _bottlenecks(hw: HardwareInfo, samples: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    latest = samples[0] if samples else {}
    vram_used = latest.get("vram_used_mib")
    if hw.vram_total_mib and vram_used is not None:
        headroom = hw.vram_total_mib - int(vram_used)
        if headroom < 1024:
            found.append("GPU VRAM is near capacity on the latest sample.")
        elif int(vram_used) > 0:
            found.append(f"GPU VRAM has about {headroom} MiB free on the latest sample.")
    if hw.vram_total_mib is None:
        found.append("No NVIDIA GPU was visible to nvidia-smi in this environment.")
    if hw.ram_available_gb < 8:
        found.append("System RAM available is under 8 GB right now.")
    tps = latest.get("tokens_per_second") or latest.get("generation_tps")
    if tps is not None and float(tps) < 8:
        found.append("Generation tok/s is low; this may be CPU offload or an oversized model, not missing hardware.")
    if not found:
        found.append("No hardware bottleneck can be claimed until more benchmark samples exist.")
    return found


def evaluate_purchase_gate(
    hardware: HardwareInfo | None = None,
    inference_samples: list[dict[str, Any]] | None = None,
    agent_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    hw = hardware or detect_hardware()
    samples = list(inference_samples or [])
    agent = list(agent_results or [])
    inference_ready = len(samples) >= MIN_INFERENCE_SAMPLES
    agent_ready = len(agent) >= MIN_AGENT_RESULTS
    allowed = inference_ready and agent_ready

    bottlenecks = _bottlenecks(hw, samples)
    latest = samples[0] if samples else {}
    vram_used = latest.get("vram_used_mib")
    vram_saturated = bool(
        hw.vram_total_mib and vram_used is not None and (hw.vram_total_mib - int(vram_used)) < 1024
    )
    cpu_offload = bool(latest.get("gpu_layers") not in (None, "", "all", "99", 99) and samples)
    ram_constrained = hw.ram_available_gb < 8
    cpu_limiting = bool((latest.get("tokens_per_second") or 0) and float(latest.get("tokens_per_second") or 0) < 8)

    if not allowed:
        recommendation = (
            "Do not buy hardware yet. Run the local inference harness and the 20-task agent suite "
            "on the Windows desktop, then re-evaluate from measured bottlenecks."
        )
    elif vram_saturated:
        recommendation = (
            "VRAM is saturated in measured samples. Software options (smaller primary model, "
            "lazy vision, smaller context) must be compared before any purchase."
        )
    else:
        recommendation = (
            "Current measurements do not justify extra GPUs, RAM, NPUs, or a dedicated inference box."
        )

    return {
        "purchase_allowed": allowed,
        "reason": (
            "Enough measured samples exist to discuss bottlenecks."
            if allowed
            else "Hardware purchases are gated on measured inference samples and agent-suite results."
        ),
        "deferred_until_measured": list(DEFERRED_PURCHASES),
        "inference_samples": len(samples),
        "agent_results": len(agent),
        "minimum_inference_samples": MIN_INFERENCE_SAMPLES,
        "minimum_agent_results": MIN_AGENT_RESULTS,
        "bottlenecks": bottlenecks,
        "signals": {
            "gpu_vram_saturated": vram_saturated,
            "cpu_offload_suspected": cpu_offload,
            "system_ram_constrained": ram_constrained,
            "cpu_inference_limiting": cpu_limiting,
            "model_switching_cost_unknown": True,
        },
        "estimated_benefit_more_vram": (
            "Unknown until 9B Q8 vs Q6 vs 27B Q4 task throughput is measured."
            if not allowed
            else "Only relevant if VRAM is the measured bottleneck after software optimization."
        ),
        "estimated_benefit_more_ram": (
            "Unknown until RAM and CPU-offload samples exist."
            if not allowed
            else "Only relevant if system RAM is the measured bottleneck."
        ),
        "recommendation": recommendation,
        "hardware_summary": {
            "os_name": hw.os_name,
            "cpu_name": hw.cpu_name,
            "ram_total_gb": hw.ram_total_gb,
            "gpu_name": hw.gpu_name,
            "vram_total_mib": hw.vram_total_mib,
        },
    }
