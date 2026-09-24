"""Reflex latency / fallback metrics for Control Room (RFC-0171)."""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from .types import DecisionResult

_LOCK = threading.Lock()
_MAX_SAMPLES = 400


@dataclass
class _Bucket:
    totals_ms: deque[float] = field(default_factory=lambda: deque(maxlen=_MAX_SAMPLES))
    inference_ms: deque[float] = field(default_factory=lambda: deque(maxlen=_MAX_SAMPLES))
    confidences: deque[float] = field(default_factory=lambda: deque(maxlen=_MAX_SAMPLES))
    fallbacks: int = 0
    hits: int = 0
    quality_ok: int = 0


_BUCKETS: dict[tuple[str, str, str], _Bucket] = defaultdict(_Bucket)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def record(result: DecisionResult) -> None:
    key = (result.decision_class, result.provider, result.provider_version or result.model or "default")
    with _LOCK:
        bucket = _BUCKETS[key]
        bucket.hits += 1
        bucket.totals_ms.append(float(result.latency.total_ms or 0.0))
        bucket.inference_ms.append(float(result.latency.inference_ms or 0.0))
        if result.fallback_used:
            bucket.fallbacks += 1
        for answer in result.answers.values():
            if answer.confidence is not None:
                bucket.confidences.append(float(answer.confidence))
        # Quality proxy: completed typed answers without deadline strand.
        if result.answers and result.source != "deadline_fallback":
            bucket.quality_ok += 1


def reset_metrics() -> None:
    with _LOCK:
        _BUCKETS.clear()


def snapshot() -> dict[str, Any]:
    with _LOCK:
        rows = []
        for (decision_class, provider, version), bucket in sorted(_BUCKETS.items()):
            totals = list(bucket.totals_ms)
            inferences = list(bucket.inference_ms)
            confs = list(bucket.confidences)
            hits = max(1, bucket.hits)
            rows.append(
                {
                    "decision_class": decision_class,
                    "provider": provider,
                    "provider_version": version,
                    "hits": bucket.hits,
                    "throughput_per_bucket": bucket.hits,
                    "fallback_rate": round(bucket.fallbacks / hits, 4),
                    "quality_rate": round(bucket.quality_ok / hits, 4),
                    "latency_end_to_end_ms": {
                        "p50": _percentile(totals, 50),
                        "p95": _percentile(totals, 95),
                        "p99": _percentile(totals, 99),
                    },
                    "latency_inference_ms": {
                        "p50": _percentile(inferences, 50),
                        "p95": _percentile(inferences, 95),
                        "p99": _percentile(inferences, 99),
                    },
                    "confidence": {
                        "mean": (sum(confs) / len(confs)) if confs else None,
                        "p50": _percentile(confs, 50),
                    },
                }
            )
        return {
            "decision_classes": rows,
            "sample_cap_per_bucket": _MAX_SAMPLES,
        }
