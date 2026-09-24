"""Reflex latency / fallback metrics for Control Room hooks (RFC-0171)."""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from typing import Any

from .types import DecisionResult

_LOCK = threading.Lock()
_MAX_SAMPLES = 200
# (decision_class, provider, version) -> deque of sample dicts
_SAMPLES: dict[tuple[str, str, str], deque[dict[str, float | bool]]] = defaultdict(
    lambda: deque(maxlen=_MAX_SAMPLES)
)


def record(result: DecisionResult) -> None:
    key = (result.decision_class, result.provider or result.source, result.provider_version or "")
    sample = {
        "total_ms": float(result.latency.total_ms),
        "inference_ms": float(result.latency.inference_ms),
        "fallback": bool(result.fallback_used),
        "deadline_hit": bool(result.deadline_hit),
        "confidence": _mean_confidence(result),
    }
    with _LOCK:
        _SAMPLES[key].append(sample)


def _mean_confidence(result: DecisionResult) -> float:
    vals = [float(a.confidence) for a in result.answers.values() if a.confidence is not None]
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (len(sorted_vals) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_vals[low]
    weight = rank - low
    return sorted_vals[low] * (1.0 - weight) + sorted_vals[high] * weight


def snapshot() -> dict[str, Any]:
    with _LOCK:
        rows = {key: list(samples) for key, samples in _SAMPLES.items()}
    classes: list[dict[str, Any]] = []
    for (decision_class, provider, version), samples in sorted(rows.items()):
        totals = sorted(float(s["total_ms"]) for s in samples)
        inferences = sorted(float(s["inference_ms"]) for s in samples)
        fallbacks = sum(1 for s in samples if s["fallback"])
        deadlines = sum(1 for s in samples if s["deadline_hit"])
        confidences = [float(s["confidence"]) for s in samples]
        classes.append(
            {
                "decision_class": decision_class,
                "provider": provider,
                "provider_version": version,
                "count": len(samples),
                "throughput_per_window": len(samples),
                "p50_total_ms": round(_percentile(totals, 50), 3),
                "p95_total_ms": round(_percentile(totals, 95), 3),
                "p99_total_ms": round(_percentile(totals, 99), 3),
                "p50_inference_ms": round(_percentile(inferences, 50), 3),
                "p95_inference_ms": round(_percentile(inferences, 95), 3),
                "p99_inference_ms": round(_percentile(inferences, 99), 3),
                "fallback_rate": round(fallbacks / max(1, len(samples)), 4),
                "deadline_hit_rate": round(deadlines / max(1, len(samples)), 4),
                "mean_confidence": round(sum(confidences) / max(1, len(confidences)), 4),
            }
        )
    return {"classes": classes, "sample_cap": _MAX_SAMPLES}


def reset_metrics() -> None:
    with _LOCK:
        _SAMPLES.clear()
