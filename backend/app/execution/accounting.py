from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunCostLedger:
    """Tracks model/tool cost so reused completed steps are not double-counted."""

    billed_model_tokens: int = 0
    billed_model_ms: float = 0.0
    reused_model_tokens: int = 0
    reused_model_ms: float = 0.0
    external_effects_committed: int = 0
    external_effects_reused: int = 0
    notes: list[str] = field(default_factory=list)

    def bill_model(self, tokens: int, ms: float, *, reused: bool) -> None:
        if reused:
            self.reused_model_tokens += tokens
            self.reused_model_ms += ms
            self.notes.append(f"reused_model:{tokens}tok")
        else:
            self.billed_model_tokens += tokens
            self.billed_model_ms += ms

    def bill_external(self, *, reused: bool) -> None:
        if reused:
            self.external_effects_reused += 1
        else:
            self.external_effects_committed += 1

    def as_dict(self) -> dict:
        return {
            "billed_model_tokens": self.billed_model_tokens,
            "billed_model_ms": self.billed_model_ms,
            "reused_model_tokens": self.reused_model_tokens,
            "reused_model_ms": self.reused_model_ms,
            "external_effects_committed": self.external_effects_committed,
            "external_effects_reused": self.external_effects_reused,
            "notes": list(self.notes),
        }


_ledgers: dict[str, RunCostLedger] = {}


def ledger_for_run(run_id: str) -> RunCostLedger:
    if run_id not in _ledgers:
        _ledgers[run_id] = RunCostLedger()
    return _ledgers[run_id]


def reset_ledgers() -> None:
    _ledgers.clear()
