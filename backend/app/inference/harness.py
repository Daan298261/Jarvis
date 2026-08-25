from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import AppSettings, data_dir, load_settings
from .agent_bench import AGENT_TASKS, task_catalog
from .profiles import MODEL_REPO, PROFILES, model_paths

HARNESS_DIR_NAME = "benchmarks"


def harness_dir() -> Path:
    path = data_dir() / HARNESS_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def last_report_path() -> Path:
    return harness_dir() / "last-report.json"


@dataclass
class BenchConfig:
    id: str
    model: str
    quant: str
    filename: str
    repo: str
    context_size: int
    thinking: str
    vision: bool
    profile: str = ""

    def gguf_path(self) -> Path:
        if "9B" in self.model:
            return model_paths()["root"].parent / "Qwen3.5-9B-abliterated-GGUF" / self.filename
        return model_paths()["root"] / self.filename


def benchmark_matrix() -> list[BenchConfig]:
    """Model/quant/context/vision/thinking combinations from the master plan."""
    nine_b = [
        ("qwen3.5-9b-abliterated", "Q8_0", "Qwen3.5-9B-abliterated-Q8_0.gguf", "Abiray/Qwen3.5-9B-abliterated-GGUF"),
        ("qwen3.5-9b-abliterated", "Q6_K", "Qwen3.5-9B-abliterated-Q6_K.gguf", "Abiray/Qwen3.5-9B-abliterated-GGUF"),
        ("qwen3.5-9b-official", "Q8_0", "Qwen3.5-9B-Q8_0.gguf", "Qwen/Qwen3.5-9B-GGUF"),
    ]
    configs: list[BenchConfig] = []
    for model, quant, filename, repo in nine_b:
        for ctx in (8192, 16384, 32768):
            for thinking in ("off", "selective", "on"):
                for vision in (False, True):
                    configs.append(
                        BenchConfig(
                            id=f"{model}-{quant}-c{ctx}-{thinking}-{'vision' if vision else 'text'}",
                            model=model,
                            quant=quant,
                            filename=filename,
                            repo=repo,
                            context_size=ctx,
                            thinking=thinking,
                            vision=vision,
                            profile="fast" if thinking == "off" else "balanced",
                        )
                    )
    for ctx in (8192, 16384, 32768):
        for thinking in ("off", "selective", "on"):
            for vision in (False, True):
                configs.append(
                    BenchConfig(
                        id=f"qwen3.5-27b-Q4_K_M-c{ctx}-{thinking}-{'vision' if vision else 'text'}",
                        model="qwen3.5-27b",
                        quant="Q4_K_M",
                        filename=PROFILES["balanced"].filename,
                        repo=MODEL_REPO,
                        context_size=ctx,
                        thinking=thinking,
                        vision=vision,
                        profile="fast" if thinking == "off" else "balanced",
                    )
                )
    return configs


@dataclass
class ConfigResult:
    id: str
    status: str
    skip_reason: str = ""
    load_time_seconds: float | None = None
    time_to_first_token_ms: float | None = None
    prompt_tokens_per_second: float | None = None
    output_tokens_per_second: float | None = None
    vram_used_mib: int | None = None
    ram_used_gb: float | None = None
    gpu_utilization: int | None = None
    cpu_utilization: float | None = None
    context_size: int = 0
    tool_call_latency_ms: float | None = None
    thinking: str = ""
    vision: bool = False
    model: str = ""
    quant: str = ""


@dataclass
class AgentTaskResult:
    id: str
    name: str
    category: str
    status: str
    skip_reason: str = ""
    success: bool | None = None
    human_intervention: bool = False
    total_seconds: float | None = None
    model_calls: int | None = None
    tool_calls: int | None = None
    retries: int | None = None
    verification: str = ""


@dataclass
class HarnessReport:
    created_at: str
    live: bool
    hardware: dict[str, Any] = field(default_factory=dict)
    configurations: list[ConfigResult] = field(default_factory=list)
    agent_tasks: list[AgentTaskResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    primary_metric: str = "successful autonomous tasks per unit of wall-clock time"

    def as_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "live": self.live,
            "hardware": self.hardware,
            "primary_metric": self.primary_metric,
            "notes": self.notes,
            "configurations": [asdict(row) for row in self.configurations],
            "agent_tasks": [asdict(row) for row in self.agent_tasks],
            "measured": sum(1 for row in self.configurations if row.status == "measured"),
            "skipped": sum(1 for row in self.configurations if row.status == "skipped"),
            "agent_catalog_size": len(AGENT_TASKS),
        }


_STATE: dict[str, Any] = {"running": False, "report": None, "error": ""}


def harness_status() -> dict[str, Any]:
    report = _STATE.get("report")
    if report is None and last_report_path().exists():
        try:
            report = json.loads(last_report_path().read_text(encoding="utf-8"))
            _STATE["report"] = report
        except Exception:
            report = None
    return {
        "running": bool(_STATE.get("running")),
        "error": _STATE.get("error") or "",
        "report": report,
        "catalog": task_catalog(),
        "matrix_size": len(benchmark_matrix()),
    }


def probe_gpu() -> dict[str, Any]:
    import subprocess

    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu,utilization.memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except Exception:
        return {}
    if not out:
        return {}
    parts = [p.strip() for p in out.splitlines()[0].split(",")]
    if len(parts) < 5:
        return {"gpu_name": parts[0] if parts else None}
    return {
        "gpu_name": parts[0],
        "vram_used_mib": int(float(parts[1])),
        "vram_total_mib": int(float(parts[2])),
        "gpu_utilization": int(float(parts[3])),
        "memory_utilization": int(float(parts[4])),
    }


def _tool_call_latency_ms() -> float:
    started = time.perf_counter()
    list(model_paths().values())
    return round((time.perf_counter() - started) * 1000, 2)


def evaluate_config(config: BenchConfig, *, live: bool) -> ConfigResult:
    path = config.gguf_path()
    if not path.exists():
        return ConfigResult(
            id=config.id,
            status="skipped",
            skip_reason=f"GGUF missing: {path}",
            context_size=config.context_size,
            thinking=config.thinking,
            vision=config.vision,
            model=config.model,
            quant=config.quant,
        )
    if not live:
        return ConfigResult(
            id=config.id,
            status="skipped",
            skip_reason="dry run; pass live=true on a machine with the GGUF loaded to measure",
            context_size=config.context_size,
            thinking=config.thinking,
            vision=config.vision,
            model=config.model,
            quant=config.quant,
        )
    from .manager import MANAGER

    gpu = probe_gpu()
    loaded = MANAGER.state.loaded and MANAGER.state.profile == config.profile and int(MANAGER.state.context_size or 0) == config.context_size
    if not loaded:
        return ConfigResult(
            id=config.id,
            status="skipped",
            skip_reason="GGUF present but this configuration is not the currently loaded model (harness does not swap models mid-run)",
            context_size=config.context_size,
            thinking=config.thinking,
            vision=config.vision,
            model=config.model,
            quant=config.quant,
            vram_used_mib=gpu.get("vram_used_mib"),
            gpu_utilization=gpu.get("gpu_utilization"),
        )
    return ConfigResult(
        id=config.id,
        status="measured",
        context_size=config.context_size,
        thinking=config.thinking,
        vision=config.vision,
        model=config.model,
        quant=config.quant,
        load_time_seconds=MANAGER.state.load_time_seconds,
        prompt_tokens_per_second=MANAGER.state.prompt_tps,
        output_tokens_per_second=MANAGER.state.generation_tps,
        vram_used_mib=MANAGER.state.vram_used_mib or gpu.get("vram_used_mib"),
        ram_used_gb=MANAGER.state.ram_used_gb,
        gpu_utilization=gpu.get("gpu_utilization"),
        tool_call_latency_ms=_tool_call_latency_ms(),
    )


def evaluate_agent_tasks(*, live: bool) -> list[AgentTaskResult]:
    rows: list[AgentTaskResult] = []
    for task in AGENT_TASKS:
        skip = ""
        status = "catalogued"
        if "gpu" in task.requires and not probe_gpu():
            skip = "no NVIDIA GPU in this environment"
            status = "skipped"
        if "windows" in task.requires:
            import platform

            if platform.system() != "Windows":
                skip = skip or "Windows-only task"
                status = "skipped"
        if not live and status != "skipped":
            status = "catalogued"
        rows.append(
            AgentTaskResult(
                id=task.id,
                name=task.name,
                category=task.category,
                status=status,
                skip_reason=skip,
                human_intervention=False,
            )
        )
    return rows


def run_harness(*, live: bool = False, settings: AppSettings | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    from ..hardware import hardware_dict

    report = HarnessReport(
        created_at=datetime.now(timezone.utc).isoformat(),
        live=live,
        hardware=hardware_dict(),
        notes=[
            "Do not pick a winner from tokens/sec alone.",
            "Primary metric is successful autonomous tasks per unit of wall-clock time.",
            "Missing GGUFs are skipped so the harness can run on machines without every quant.",
            f"Inference host {settings.inference.host}:{settings.inference.port}.",
        ],
    )
    report.configurations = [evaluate_config(cfg, live=live) for cfg in benchmark_matrix()]
    report.agent_tasks = evaluate_agent_tasks(live=live)
    payload = report.as_dict()
    last_report_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown = render_markdown(payload)
    (harness_dir() / "last-report.md").write_text(markdown, encoding="utf-8")
    _STATE["report"] = payload
    _STATE["error"] = ""
    return payload


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Jarvis benchmark report",
        "",
        f"Created: {payload.get('created_at')}",
        f"Live: {payload.get('live')}",
        f"Measured configs: {payload.get('measured')} / skipped: {payload.get('skipped')}",
        f"Agent catalog: {payload.get('agent_catalog_size')} tasks",
        "",
        f"Primary metric: {payload.get('primary_metric')}",
        "",
        "## Notes",
    ]
    for note in payload.get("notes") or []:
        lines.append(f"- {note}")
    lines += ["", "## Configurations", "", "| id | status | ctx | thinking | vision | skip |", "| --- | --- | --- | --- | --- | --- |"]
    for row in payload.get("configurations") or []:
        lines.append(
            f"| {row.get('id')} | {row.get('status')} | {row.get('context_size')} | "
            f"{row.get('thinking')} | {row.get('vision')} | {row.get('skip_reason') or ''} |"
        )
    lines += ["", "## Agent tasks", "", "| id | category | status | skip |", "| --- | --- | --- | --- |"]
    for row in payload.get("agent_tasks") or []:
        lines.append(f"| {row.get('id')} | {row.get('category')} | {row.get('status')} | {row.get('skip_reason') or ''} |")
    return "\n".join(lines) + "\n"


async def run_harness_background(*, live: bool = False) -> None:
    if _STATE.get("running"):
        return
    _STATE["running"] = True
    _STATE["error"] = ""
    try:
        await asyncio.to_thread(run_harness, live=live)
    except Exception as exc:
        _STATE["error"] = str(exc)
    finally:
        _STATE["running"] = False
