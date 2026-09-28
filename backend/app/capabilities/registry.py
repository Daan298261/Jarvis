"""Load and query the versioned capability registry (RFC-0137)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import CapabilityRecord, CapabilityRegistry

_REGISTRY_PATH = Path(__file__).with_name("registry_data.json")


@lru_cache(maxsize=1)
def load_registry() -> CapabilityRegistry:
    raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    return CapabilityRegistry.model_validate(raw)


def list_capabilities() -> list[CapabilityRecord]:
    return list(load_registry().capabilities)


def get_capability(capability_id: str) -> CapabilityRecord | None:
    cleaned = str(capability_id or "").strip()
    if not cleaned:
        return None
    for row in load_registry().capabilities:
        if row.id == cleaned:
            return row
    return None


def capability_summary() -> dict[str, Any]:
    rows = list_capabilities()
    by_parity: dict[str, int] = {"missing": 0, "partial": 0, "equivalent": 0}
    by_lifecycle: dict[str, int] = {}
    for row in rows:
        by_parity[row.parity_state] = by_parity.get(row.parity_state, 0) + 1
        by_lifecycle[row.lifecycle] = by_lifecycle.get(row.lifecycle, 0) + 1
    return {
        "version": load_registry().version,
        "updated_at": load_registry().updated_at,
        "total": len(rows),
        "by_parity_state": by_parity,
        "by_lifecycle": by_lifecycle,
    }
