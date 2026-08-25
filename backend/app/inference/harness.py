from __future__ import annotations

import json
import platform
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import psutil

from ..config import data_dir
from ..hardware import hardware_dict
from .benchmarks import list_benchmarks, record_benchmark_sample

ChatFn = Callable[..., Awaitable[Any]]
RefreshFn = Callable[[], Awaitable[Any]]


@dataclass
class HarnessReport:
    ran_at: str
    model_available: bool
    blocked_reason: str = ""
    hardware: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    bottleneck: str = "unmeasured"
    buy_hardware: bool = False
    hardware_recommendation: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _nvidia_util() -> dict[str, Any]:
    query = ""
    try:
        query = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except Exception:
        query = ""
    if not query:
        return {
            "gpu_utilization_percent": None,
            "vram_used_mib": None,
            "vram_total_mib": None,
        }
    gpu_util, _mem_util, used, total = [part.strip() for part in query.split(",", 3)]
    return {
        "gpu_utilization_percent": float(gpu_util),
        "vram_used_mib": int(float(used)),
        "vram_total_mib": int(float(total)),
    }


def collect_resources() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    nvidia = _nvidia_util()
    return {
        "cpu_utilization_percent": psutil.cpu_percent(interval=0.15),
        "ram_used_gb": round((vm.total - vm.available) / (1024**3), 2),
        "ram_total_gb": round(vm.total / (1024**3), 2),
        **nvidia,
        "os": platform.system(),
    }


def measure_tool_call_latency_ms() -> float:
    started = time.perf_counter()
    Path(__file__).stat()
    Path.cwd().stat()
    return round((time.perf_counter() - started) * 1000, 3)


def hardware_gate(hardware: dict[str, Any], metrics: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    """P0.12: do not recommend buying hardware until the desktop harness has real numbers."""
    measured = bool(metrics.get("generation_tps") or metrics.get("load_time_seconds") or metrics.get("ttft_ms"))
    live_gpu = hardware.get("gpu_name") and hardware.get("vram_total_mib")
    if not measured or not live_gpu:
        return {
            "buy_hardware": False,
            "bottleneck": "unmeasured",
            "recommendation": (
                "Do not buy extra RAM, Tesla/V100 GPUs, NPUs, or other inference hardware until "
                "this harness has run on the Windows desktop with the 9B and 27B GGUFs loaded. "
                f"Current probe: gpu={hardware.get('gpu_name') or 'none'}, "
                f"samples={len(samples)}."
            ),
        }
    vram_total = hardware.get("vram_total_mib") or 0
    vram_used = metrics.get("vram_used_mib") or hardware.get("vram_used_mib") or 0
    ram_total = hardware.get("ram_total_gb") or 0
    ram_used = metrics.get("ram_used_gb") or 0
    tps = metrics.get("generation_tps")
    notes = []
    bottleneck = "balanced"
    if vram_total and vram_used and vram_used >= 0.9 * vram_total:
        bottleneck = "gpu_vram"
        notes.append("VRAM is at or above 90% of capacity during this sample.")
    elif ram_total and ram_used and ram_used >= 0.85 * ram_total:
        bottleneck = "system_ram"
        notes.append("System RAM is highly occupied; check CPU offload before buying GPUs.")
    elif tps is not None and tps < 8:
        bottleneck = "generation_speed"
        notes.append("Output tok/s is low; confirm GPU residency before buying more cards.")
    else:
        notes.append("No purchase is justified from this sample. Re-run after the 9B migration.")
    return {
        "buy_hardware": False,
        "bottleneck": bottleneck,
        "recommendation": " ".join(
            [
                "Hardware purchases stay gated on measured bottlenecks.",
                *notes,
                "Do not order additional accelerators from this cloud/Linux probe.",
            ]
        ),
    }


def last_report_path() -> Path:
    folder = data_dir() / "benchmarks"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "last_harness.json"


def load_last_report() -> dict[str, Any] | None:
    path = last_report_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_last_report(report: HarnessReport) -> None:
    last_report_path().write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")


async def run_harness(
    *,
    loaded: bool = False,
    chat: ChatFn | None = None,
    refresh_resources: RefreshFn | None = None,
    state: Any | None = None,
    persist: bool = True,
) -> HarnessReport:
    hardware = hardware_dict()
    resources = collect_resources()
    tool_latency = measure_tool_call_latency_ms()
    metrics: dict[str, Any] = {
        "tool_call_latency_ms": tool_latency,
        "cpu_utilization_percent": resources.get("cpu_utilization_percent"),
        "gpu_utilization_percent": resources.get("gpu_utilization_percent"),
        "vram_used_mib": resources.get("vram_used_mib"),
        "ram_used_gb": resources.get("ram_used_gb"),
        "context_size": getattr(state, "context_size", None) if state is not None else None,
        "load_time_seconds": getattr(state, "load_time_seconds", None) if state is not None else None,
        "prompt_tps": getattr(state, "prompt_tps", None) if state is not None else None,
        "generation_tps": getattr(state, "generation_tps", None) if state is not None else None,
        "ttft_ms": None,
    }
    notes = [
        "Measures load time, tok/s, VRAM/RAM, CPU/GPU utilization, context, and a local tool-stat probe.",
        "Task-duration and 20-task comparison still require the Windows desktop model run.",
    ]
    blocked = ""
    if refresh_resources:
        try:
            await refresh_resources()
            if state is not None:
                metrics["vram_used_mib"] = getattr(state, "vram_used_mib", metrics["vram_used_mib"])
                metrics["ram_used_gb"] = getattr(state, "ram_used_gb", metrics["ram_used_gb"])
                metrics["load_time_seconds"] = getattr(state, "load_time_seconds", None)
                metrics["prompt_tps"] = getattr(state, "prompt_tps", None)
                metrics["generation_tps"] = getattr(state, "generation_tps", None)
                metrics["context_size"] = getattr(state, "context_size", None)
        except Exception as exc:
            notes.append(f"Resource refresh failed: {exc}")
    if loaded and chat is not None:
        started = time.perf_counter()
        try:
            from ..providers.base import ChatMessage

            probe = [ChatMessage(role="user", content="Reply with the single word pong.")]
            result = await chat(probe, tools=None, max_tokens=8, thinking=False)
            metrics["ttft_ms"] = round((time.perf_counter() - started) * 1000, 1)
            timings = getattr(result, "timings", None) or {}
            if timings.get("prompt_per_second"):
                metrics["prompt_tps"] = float(timings["prompt_per_second"])
            if timings.get("predicted_per_second"):
                metrics["generation_tps"] = float(timings["predicted_per_second"])
        except Exception as exc:
            blocked = f"live chat probe failed: {exc}"
            notes.append(blocked)
    elif not loaded:
        blocked = "model not loaded in this process (expected on the Linux cloud VM)"
        notes.append(blocked)

    samples = await list_benchmarks(limit=20)
    gate = hardware_gate(hardware, metrics, samples)
    report = HarnessReport(
        ran_at=datetime.now(timezone.utc).isoformat(),
        model_available=bool(loaded),
        blocked_reason=blocked,
        hardware=hardware,
        metrics=metrics,
        bottleneck=gate["bottleneck"],
        buy_hardware=bool(gate["buy_hardware"]),
        hardware_recommendation=gate["recommendation"],
        notes=notes,
    )
    if persist:
        save_last_report(report)
        try:
            await record_benchmark_sample(
                profile=getattr(state, "profile", "") if state is not None else "",
                quantization=getattr(state, "quant", "") if state is not None else "",
                context_size=int(metrics.get("context_size") or 0),
                prompt_tps=metrics.get("prompt_tps"),
                generation_tps=metrics.get("generation_tps"),
                vram_used_mib=metrics.get("vram_used_mib"),
                ram_used_gb=metrics.get("ram_used_gb"),
                load_time_seconds=metrics.get("load_time_seconds"),
                source="harness",
                metrics={
                    "ttft_ms": metrics.get("ttft_ms"),
                    "tool_call_latency_ms": metrics.get("tool_call_latency_ms"),
                    "cpu_utilization_percent": metrics.get("cpu_utilization_percent"),
                    "gpu_utilization_percent": metrics.get("gpu_utilization_percent"),
                    "bottleneck": report.bottleneck,
                },
            )
        except Exception:
            pass
    return report


def llama_server_present() -> bool:
    exe = shutil.which("llama-server") or shutil.which("llama-server.exe")
    return bool(exe)
