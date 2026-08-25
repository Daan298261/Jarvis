from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import psutil

from ..config import AppSettings, load_settings
from ..hardware import detect_hardware
from ..providers.base import ChatMessage, ModelProvider
from .backends import LlamaCppBackend
from .benchmarks import record_benchmark_sample
from .manager import MANAGER
from .profiles import PROFILES, resolve_profile

# Combinations the plan requires. Live runs skip cases whose GGUF/server is missing.
HARNESS_CASES: tuple[dict[str, Any], ...] = (
    {"profile": "fast", "context_size": 8192, "vision": False, "thinking": "off"},
    {"profile": "fast", "context_size": 16384, "vision": False, "thinking": "off"},
    {"profile": "balanced", "context_size": 8192, "vision": False, "thinking": "selective"},
    {"profile": "balanced", "context_size": 16384, "vision": False, "thinking": "selective"},
    {"profile": "balanced", "context_size": 32768, "vision": False, "thinking": "selective"},
    {"profile": "balanced", "context_size": 16384, "vision": True, "thinking": "selective"},
    {"profile": "quality", "context_size": 16384, "vision": False, "thinking": "on"},
    {"profile": "quality", "context_size": 32768, "vision": False, "thinking": "on"},
)

PRIMARY_METRIC = "successful autonomous tasks per wall-clock minute"


@dataclass
class HarnessCaseResult:
    profile: str
    context_size: int
    vision: bool
    thinking: str
    status: str
    skip_reason: str = ""
    load_time_seconds: float | None = None
    time_to_first_token_seconds: float | None = None
    prompt_tokens_per_second: float | None = None
    output_tokens_per_second: float | None = None
    vram_used_mib: int | None = None
    ram_used_gb: float | None = None
    gpu_utilization_percent: float | None = None
    cpu_utilization_percent: float | None = None
    tool_call_latency_ms: float | None = None
    notes: str = ""


@dataclass
class HarnessReport:
    live: bool
    primary_metric: str = PRIMARY_METRIC
    host: dict[str, Any] = field(default_factory=dict)
    cases: list[HarnessCaseResult] = field(default_factory=list)
    warning: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "live": self.live,
            "primary_metric": self.primary_metric,
            "host": self.host,
            "warning": self.warning,
            "cases": [asdict(case) for case in self.cases],
            "planned_cases": len(HARNESS_CASES),
            "measured_cases": sum(1 for case in self.cases if case.status == "measured"),
            "skipped_cases": sum(1 for case in self.cases if case.status == "skipped"),
        }


def _gpu_utilization() -> float | None:
    try:
        import subprocess

        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        if out:
            return float(out.splitlines()[0].strip())
    except Exception:
        return None
    return None


def host_snapshot() -> dict[str, Any]:
    info = detect_hardware()
    return {
        "os": info.os_name,
        "cpu_name": info.cpu_name,
        "cpu_cores": info.cpu_cores,
        "ram_total_gb": info.ram_total_gb,
        "gpu_name": info.gpu_name,
        "vram_total_mib": info.vram_total_mib,
        "vram_free_mib": info.vram_free_mib,
        "cuda_version": info.cuda_version,
        "cpu_utilization_percent": psutil.cpu_percent(interval=0.1),
        "gpu_utilization_percent": _gpu_utilization(),
    }


def _skip_reason(settings: AppSettings, spec: dict[str, Any], live: bool) -> str:
    if not live:
        return "dry-run; live llama.cpp measurement was not requested"
    if os.environ.get("JARVIS_SKIP_MODEL") == "1":
        return "JARVIS_SKIP_MODEL=1"
    profile = resolve_profile(spec["profile"])
    backend = LlamaCppBackend(settings)
    missing = backend.missing_requirements(profile)
    if missing:
        return "; ".join(missing)
    return ""


async def _measure_provider(provider: ModelProvider) -> dict[str, Any]:
    started = time.perf_counter()
    ping = time.perf_counter()
    result = await provider.chat(
        [ChatMessage(role="user", content="Reply with the single word pong and nothing else.")],
        tools=None,
        thinking=False,
        max_tokens=8,
    )
    elapsed = time.perf_counter() - started
    tool_started = time.perf_counter()
    await provider.chat(
        [ChatMessage(role="user", content="Do not call tools. Reply with ok.")],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "filesystem",
                    "description": "unused latency probe",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        thinking=False,
        max_tokens=8,
    )
    tool_ms = round((time.perf_counter() - tool_started) * 1000, 1)
    timings = result.timings or {}
    return {
        "time_to_first_token_seconds": round(elapsed, 4),
        "prompt_tokens_per_second": timings.get("prompt_per_second"),
        "output_tokens_per_second": timings.get("predicted_per_second"),
        "tool_call_latency_ms": tool_ms,
        "load_probe_seconds": round(ping - started, 4),
    }


async def run_harness(
    *,
    live: bool = False,
    settings: AppSettings | None = None,
    provider: ModelProvider | None = None,
    persist: bool = True,
) -> HarnessReport:
    settings = settings or load_settings()
    report = HarnessReport(live=live, host=host_snapshot())
    if live and not (provider or MANAGER.provider):
        report.warning = "No chat provider is loaded; cases will be skipped unless llama.cpp files exist."
    chat = provider or MANAGER.provider

    for spec in HARNESS_CASES:
        skip = _skip_reason(settings, spec, live)
        if live and provider is not None:
            skip = ""
        case = HarnessCaseResult(
            profile=spec["profile"],
            context_size=int(spec["context_size"]),
            vision=bool(spec["vision"]),
            thinking=str(spec["thinking"]),
            status="skipped" if skip else "measured",
            skip_reason=skip,
        )
        if not skip and chat is not None:
            try:
                metrics = await _measure_provider(chat)
                await MANAGER.refresh_resources()
                case.load_time_seconds = MANAGER.state.load_time_seconds
                case.time_to_first_token_seconds = metrics["time_to_first_token_seconds"]
                case.prompt_tokens_per_second = metrics["prompt_tokens_per_second"]
                case.output_tokens_per_second = metrics["output_tokens_per_second"]
                case.tool_call_latency_ms = metrics["tool_call_latency_ms"]
                case.vram_used_mib = MANAGER.state.vram_used_mib
                case.ram_used_gb = MANAGER.state.ram_used_gb
                case.gpu_utilization_percent = report.host.get("gpu_utilization_percent")
                case.cpu_utilization_percent = psutil.cpu_percent(interval=0.05)
                case.notes = (
                    f"vision={'on' if spec['vision'] else 'off'}; thinking={spec['thinking']}; "
                    f"quant={PROFILES[spec['profile']].quant}"
                )
            except Exception as exc:
                case.status = "skipped"
                case.skip_reason = f"measurement failed: {exc}"
        elif not skip and chat is None:
            case.status = "skipped"
            case.skip_reason = "no chat provider loaded"
        report.cases.append(case)
        if persist:
            await record_benchmark_sample(
                profile=case.profile,
                quantization=PROFILES[case.profile].quant,
                context_size=case.context_size,
                prompt_tps=case.prompt_tokens_per_second,
                generation_tps=case.output_tokens_per_second,
                vram_used_mib=case.vram_used_mib,
                ram_used_gb=case.ram_used_gb,
                load_time_seconds=case.load_time_seconds,
                source="harness" if case.status == "measured" else "harness-skip",
                notes=case.skip_reason or case.notes,
            )
    measured = sum(1 for case in report.cases if case.status == "measured")
    if live and measured == 0:
        report.warning = (
            report.warning
            or "Harness did not measure a live case. Tokens/sec must not be used to pick hardware until a live run exists."
        )
    return report
