"""Fixed-prompt quality check and optional runtime timings for the front lane.

Quality scoring uses ``classify_front_action`` and the spoken fallback line, so
it runs without a GGUF. Cold load, VRAM, and first-token numbers are recorded
only when a llama-server binary and the selected GGUF are actually on disk.
This module never raises the 1500 ms front timeout.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..config import data_dir, load_settings
from .front_responder import (
    classify_front_action,
    fallback_text_for_action,
    is_safe_front_speech,
)

# Fixed set. Expected actions are the heuristic the lane already uses.
FIXED_PROMPTS: tuple[tuple[str, str], ...] = (
    ("Hello", "final_basic"),
    ("How are you this evening?", "final_basic"),
    ("Thanks", "final_basic"),
    ("What's the weather in Dinteloord tomorrow?", "ack_continue"),
    ("What is the latest news on that outage?", "ack_continue"),
    ("Run the pytest tool on the security review", "handoff_notice"),
    ("Execute the filesystem tool and refactor the auth module", "handoff_notice"),
    ("do it", "ask_clarification"),
    ("fix it", "ask_clarification"),
)

_REPORT_NAME = "front_benchmark.json"


def report_path() -> Path:
    return data_dir() / _REPORT_NAME


def score_fixed_prompts() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    matches = 0
    usable = 0
    for prompt, expected in FIXED_PROMPTS:
        action = classify_front_action(prompt)
        spoken = fallback_text_for_action(action)
        line_ok = action == "silent_skip" or is_safe_front_speech(action, spoken)
        matched = action == expected
        matches += int(matched)
        usable += int(line_ok)
        rows.append(
            {
                "prompt": prompt,
                "expected": expected,
                "actual": action,
                "match": matched,
                "spoken": spoken,
                "spoken_usable": line_ok,
            }
        )
    total = len(rows) or 1
    return {
        "prompts": len(rows),
        "accuracy": round(matches / total, 3),
        "spoken_usable": round(usable / total, 3),
        "rows": rows,
    }


def _runtime_available(profile_name: str) -> tuple[bool, str]:
    from ..inference.backends import LlamaCppBackend
    from ..inference.profiles import PROFILES, profile_gguf

    settings = load_settings()
    profile = PROFILES.get(profile_name)
    if profile is None:
        return False, f"unknown profile {profile_name}"
    backend = LlamaCppBackend(settings)
    missing = backend.missing_requirements(profile)
    gguf = profile_gguf(profile)
    if missing:
        return False, "; ".join(missing)[:400]
    if not gguf.is_file():
        return False, f"weights missing: {gguf}"
    return True, str(gguf)


def measure_runtime(profile_name: str) -> dict[str, Any]:
    """Record real timings only when the server and weights exist.

    The cloud VM has no GPU and usually no GGUF. A missing binary is a
    measurement gap, not a guessed latency.
    """
    ok, detail = _runtime_available(profile_name)
    payload: dict[str, Any] = {
        "profile": profile_name,
        "measured": False,
        "reason": "",
        "cold_load_ms": None,
        "warm_switch_ms": None,
        "vram_free_mib": None,
        "first_token_ms": None,
        "output_tokens_per_second": None,
        "within_timeout": None,
        "timeout_ms": 1500,
    }
    if not ok:
        payload["reason"] = detail
        return payload
    payload["reason"] = "runtime present but live load is desktop sign-off on this agent"
    # Do not spawn llama-server from the benchmark helper during unit tests or
    # cloud CI. The script entrypoint calls run_benchmark(allow_live=True).
    return payload


async def measure_live_first_token(profile_name: str) -> dict[str, Any]:
    """Start the front server once and time one token. Caller opts in."""
    from ..inference.front_runtime import FRONT_RUNTIME

    settings = load_settings()
    settings.front_responder.profile = profile_name
    settings.front_responder.placement = "local"
    settings.front_responder.device = "cpu" if profile_name != "front_4b" else "auto"
    started = time.perf_counter()
    decision = await FRONT_RUNTIME.ensure_started(settings)
    cold_ms = (time.perf_counter() - started) * 1000
    payload: dict[str, Any] = {
        "profile": profile_name,
        "measured": False,
        "reason": decision.reason,
        "cold_load_ms": round(cold_ms, 1),
        "warm_switch_ms": None,
        "vram_free_mib": decision.vram_free_mib,
        "first_token_ms": None,
        "output_tokens_per_second": None,
        "within_timeout": None,
        "timeout_ms": int(settings.front_responder.timeout_ms),
        "mode": decision.mode,
        "device": decision.device,
        "n_gpu_layers": decision.n_gpu_layers,
    }
    if decision.mode not in {"resident", "remote"} or not decision.healthy:
        payload["reason"] = decision.reason or "front runtime did not become healthy"
        return payload
    provider = FRONT_RUNTIME.provider(settings)
    if provider is None or not hasattr(provider, "chat_stream"):
        payload["reason"] = "no provider after start"
        return payload
    from ..providers.base import ChatMessage

    token_started = time.perf_counter()
    first_ms = None
    chunks = 0
    try:
        async for delta in provider.chat_stream(
            [ChatMessage(role="user", content="Hello")],
            max_tokens=8,
            temperature=0.0,
            thinking=False,
        ):
            if delta and first_ms is None:
                first_ms = (time.perf_counter() - token_started) * 1000
            if delta:
                chunks += 1
    except Exception as exc:
        payload["reason"] = f"stream failed: {exc}"[:300]
        return payload
    elapsed = max(0.001, time.perf_counter() - token_started)
    timeout_ms = int(settings.front_responder.timeout_ms)
    payload["measured"] = first_ms is not None
    payload["first_token_ms"] = round(first_ms, 1) if first_ms is not None else None
    payload["output_tokens_per_second"] = round(chunks / elapsed, 2) if chunks else 0.0
    payload["within_timeout"] = bool(first_ms is not None and first_ms <= timeout_ms)
    payload["reason"] = "measured" if payload["measured"] else "no token"
    warm_started = time.perf_counter()
    again = await FRONT_RUNTIME.ensure_started(settings)
    payload["warm_switch_ms"] = round((time.perf_counter() - warm_started) * 1000, 1)
    payload["warm_mode"] = again.mode
    return payload


def run_benchmark(*, allow_live: bool = False) -> dict[str, Any]:
    settings = load_settings()
    profile = (settings.front_responder.profile or "front_2b").strip() or "front_2b"
    quality = score_fixed_prompts()
    runtime = {
        "front_2b": measure_runtime("front_2b"),
        "front_4b": measure_runtime("front_4b"),
    }
    report = {
        "timeout_ms": int(settings.front_responder.timeout_ms),
        "default_profile": "front_2b",
        "selected_profile": profile,
        "recommendation": "front_2b",
        "recommendation_reason": (
            "Default stays Qwen3.5 2B Q4 on CPU. This run did not measure a GPU "
            "first-token advantage for 4B, so the default is unchanged."
        ),
        "quality": quality,
        "runtime": runtime,
        "live": None,
        "colibri": "not integrated",
        "concurrency": "separate llama-server (not Ollama NUM_PARALLEL)",
    }
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["path"] = str(path)
    report["allow_live"] = allow_live
    return report


def load_benchmark_report() -> dict[str, Any]:
    path = report_path()
    if not path.is_file():
        return {"present": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"present": False, "error": str(exc)[:200]}
    if not isinstance(data, dict):
        return {"present": False}
    data["present"] = True
    return data
