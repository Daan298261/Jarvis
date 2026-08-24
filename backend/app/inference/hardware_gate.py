"""P0.12 — hardware purchasing gate.

Do not recommend extra RAM, Tesla/V100 GPUs, NPUs, or other inference hardware
until the desktop benchmark suite has actually run. This module turns current
hardware + stored samples into a bottleneck report and a hard purchase gate.
"""

from __future__ import annotations

from typing import Any

from ..hardware import hardware_dict
from .benchmarks import list_benchmarks, task_outcome_stats

DEFERRED_PURCHASES = (
    "additional RAM",
    "old Tesla GPUs",
    "V100 GPUs",
    "NPUs",
    "additional inference hardware",
)

REQUIRED_BEFORE_PURCHASE = (
    "Qwen3.5-9B Abliterated Q8_0 load on the Windows RTX 5070 Ti",
    "Qwen3.5-9B Abliterated Q6_K comparison sample",
    "current Qwen3.5-27B Q4_K_M baseline sample",
    "context size sweep at 8K, 16K, and 32K",
    "vision disabled vs enabled VRAM delta",
    "reasoning off vs selective vs enabled",
    "20-task agent suite on the desktop (successful tasks per minute)",
)


def _latest_by_profile(samples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for sample in samples:
        key = str(sample.get("profile") or "")
        if key and key not in out:
            out[key] = sample
    return out


def analyze_hardware_gate(
    hardware: dict[str, Any] | None = None,
    samples: list[dict[str, Any]] | None = None,
    *,
    agent_suite_complete: bool = False,
    outcomes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hw = dict(hardware or {})
    rows = list(samples or [])
    gpu_name = hw.get("gpu_name")
    vram_total = hw.get("vram_total_mib")
    vram_free = hw.get("vram_free_mib")
    ram_total = float(hw.get("ram_total_gb") or 0)
    ram_available = float(hw.get("ram_available_gb") or 0)

    vram_used_now = None
    vram_saturated = False
    if isinstance(vram_total, int) and isinstance(vram_free, int):
        vram_used_now = vram_total - vram_free
        vram_saturated = vram_total > 0 and (vram_used_now / vram_total) >= 0.92

    sample_vram = [int(s["vram_used_mib"]) for s in rows if s.get("vram_used_mib") is not None]
    cpu_offload_likely = False
    if vram_total and sample_vram:
        cpu_offload_likely = any(value >= int(vram_total) - 256 for value in sample_vram)
    ram_constrained = ram_available and ram_available < 4
    has_tps = any(s.get("tokens_per_second") for s in rows)
    profiles = {str(s.get("profile") or "") for s in rows if s.get("profile")}
    live_gpu = bool(gpu_name) and bool(vram_total)
    desktop_windows = str(hw.get("os_name") or "").lower() == "windows"

    missing: list[str] = []
    if not live_gpu:
        missing.append("NVIDIA GPU metrics (nvidia-smi)")
    if not desktop_windows:
        missing.append("Windows desktop measurement (this environment is not the target PC)")
    if "fast" not in profiles or "balanced" not in profiles:
        missing.append("stored samples covering Fast and Balanced profiles")
    if not has_tps:
        missing.append("tokens/sec samples from a real model load")
    if not agent_suite_complete:
        missing.append("completed 20-task agent suite on the target desktop")
    if not any((s.get("quantization") or "").upper().startswith("Q8") for s in rows):
        missing.append("9B Q8_0 sample")
    if not any("27B" in str(s.get("profile") or "") or (s.get("quantization") or "").upper().startswith("Q4") for s in rows):
        missing.append("27B Q4_K_M baseline sample")

    bottleneck = "insufficient_data"
    if not live_gpu:
        bottleneck = "no_gpu_metrics"
    elif not has_tps:
        bottleneck = "no_model_throughput_samples"
    elif cpu_offload_likely and vram_saturated:
        bottleneck = "gpu_vram"
    elif ram_constrained:
        bottleneck = "system_ram"
    elif has_tps and live_gpu and not vram_saturated:
        bottleneck = "software_or_unmeasured"
    if missing:
        bottleneck = bottleneck if bottleneck != "software_or_unmeasured" else "software_optimization_incomplete"

    cpu_inference_limiting = None
    if has_tps and cpu_offload_likely:
        cpu_inference_limiting = True
    elif has_tps and live_gpu and not cpu_offload_likely:
        cpu_inference_limiting = False

    purchase_recommended = False
    decision = "defer_purchase"
    reason = (
        "Hardware purchases stay gated until the desktop benchmark suite has run. "
        "Optimize the 9B primary / 27B expert stack first."
    )
    if missing:
        reason = "Missing required evidence: " + "; ".join(missing) + ". " + reason

    estimated_vram = None
    estimated_ram = None
    if vram_saturated:
        estimated_vram = "Possible VRAM benefit, but only after 9B Q8_0 vs Q6_K vs 27B Q4_K_M is measured on this GPU."
    if ram_constrained:
        estimated_ram = "System RAM is tight right now; still defer buying until model-offload cost is measured."

    return {
        "decision": decision,
        "purchase_recommended": purchase_recommended,
        "reason": reason,
        "bottleneck": bottleneck,
        "gpu_name": gpu_name,
        "gpu_present": bool(gpu_name),
        "gpu_vram_saturated": bool(vram_saturated),
        "vram_total_mib": vram_total,
        "vram_free_mib": vram_free,
        "vram_used_mib": vram_used_now,
        "cpu_offload_likely": bool(cpu_offload_likely),
        "system_ram_constrained": bool(ram_constrained),
        "ram_total_gb": ram_total or None,
        "ram_available_gb": ram_available or None,
        "cpu_inference_limiting": cpu_inference_limiting,
        "model_switching_costly": None,
        "estimated_benefit_more_vram": estimated_vram,
        "estimated_benefit_more_ram": estimated_ram,
        "deferred_purchases": list(DEFERRED_PURCHASES),
        "required_before_purchase": list(REQUIRED_BEFORE_PURCHASE),
        "missing_evidence": missing,
        "profiles_sampled": sorted(p for p in profiles if p),
        "sample_count": len(rows),
        "agent_suite_complete": agent_suite_complete,
        "outcomes": outcomes or {},
        "latest_by_profile": _latest_by_profile(rows),
    }


async def hardware_purchase_gate() -> dict[str, Any]:
    from ..agent.agent_benchmark import SUITE_ID, list_results

    hardware = hardware_dict()
    samples = await list_benchmarks(limit=80)
    outcomes = await task_outcome_stats()
    results = await list_results(limit=200)
    suite_cases = {row["case_id"] for row in results if row.get("suite_id") == SUITE_ID and row.get("success")}
    agent_suite_complete = len(suite_cases) >= 20
    report = analyze_hardware_gate(
        hardware,
        samples,
        agent_suite_complete=agent_suite_complete,
        outcomes=outcomes,
    )
    report["agent_suite_successes"] = len(suite_cases)
    return report
