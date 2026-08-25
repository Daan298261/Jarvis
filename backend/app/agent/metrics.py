from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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
        self.model_ms += prompt_ms + predicted_ms

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
