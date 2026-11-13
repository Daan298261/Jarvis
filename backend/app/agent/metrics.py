from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from dataclasses import asdict, dataclass
from typing import Any


async def timed_model_request(request: Awaitable[Any], *, metrics: "LiveTaskMetrics", timeout: float) -> Any:
    """Measure provider work separately from durable preparation/commit time.

    Successful calls are counted by the caller after durable replay handling.
    Failed and cancelled attempts have no ChatResult, so count their time here.
    """
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(request, timeout=timeout)
    except BaseException as exc:
        elapsed = (time.perf_counter() - started) * 1000
        metrics.note_model_elapsed(elapsed)
        logging.getLogger(__name__).info("Model request %s after %.1f ms", type(exc).__name__, elapsed)
        raise
    result.timings = dict(result.timings or {})
    result.timings["provider_wall_ms"] = (time.perf_counter() - started) * 1000
    return result


@dataclass
class LiveTaskMetrics:
    """Wall-clock operational counters for one Jarvis task (P0.8 / P0.9)."""

    model_calls: int = 0
    tool_calls: int = 0
    schema_errors: int = 0
    model_ms: float = 0.0
    tool_ms: float = 0.0
    human_interventions: int = 0

    def note_model(self, timings: dict[str, Any] | None = None) -> None:
        self.model_calls += 1
        payload = timings or {}
        prompt_ms = float(payload.get("prompt_ms") or 0)
        predicted_ms = float(payload.get("predicted_ms") or 0)
        self.model_ms += max(0.0, float(payload.get("provider_wall_ms") or
                                       (prompt_ms + predicted_ms) or
                                       payload.get("total_ms") or payload.get("generation_ms") or 0))

    def note_model_elapsed(self, duration_ms: float) -> None:
        """Record a streamed model call when the provider exposes no timing payload."""
        self.model_calls += 1
        self.model_ms += max(0.0, float(duration_ms or 0))

    def note_tool(self, duration_ms: float, schema_error: bool = False) -> None:
        self.tool_calls += 1
        self.tool_ms += max(0.0, float(duration_ms or 0))
        if schema_error:
            self.schema_errors += 1

    def note_confirmation(self) -> None:
        self.human_interventions += 1

    def as_fields(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "tool_call_count": self.tool_calls,
            "schema_errors": self.schema_errors,
            "model_ms": round(self.model_ms, 1),
            "tool_ms": round(self.tool_ms, 1),
            "human_interventions": self.human_interventions,
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
