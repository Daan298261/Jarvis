from __future__ import annotations

import shutil
from typing import Any

from ..config import AppSettings, CodingSettings

# Identifiers are configurable because Cursor may rename models.
# Fast variants exist in the catalog so they can be selected explicitly;
# routing never picks them unless allow_fast_variants is on.
CURSOR_MODEL_CATALOG: list[dict[str, Any]] = [
    {
        "id": "local-qwen",
        "label": "Local Jarvis (Qwen)",
        "worker": "local",
        "tier": "local",
        "variant": "standard",
        "paid": False,
        "detail": "LocalJarvisCodingWorker. Effectively zero incremental AI cost.",
    },
    {
        "id": "composer-2.5",
        "label": "Composer 2.5 Standard",
        "worker": "cursor_acp",
        "tier": "paid_default",
        "variant": "standard",
        "paid": True,
        "input_usd_per_m": 0.50,
        "cached_usd_per_m": 0.20,
        "output_usd_per_m": 2.50,
        "detail": "Default paid coding worker. Prefer Standard, not Fast.",
    },
    {
        "id": "composer-2.5-fast",
        "label": "Composer 2.5 Fast",
        "worker": "cursor_acp",
        "tier": "paid_default",
        "variant": "fast",
        "paid": True,
        "input_usd_per_m": 0.50,
        "cached_usd_per_m": 0.20,
        "output_usd_per_m": 2.50,
        "detail": "Higher effective cost. Only when latency is worth it.",
    },
    {
        "id": "grok-4.6",
        "label": "Grok 4.6 Standard",
        "worker": "cursor_acp",
        "tier": "difficult",
        "variant": "standard",
        "paid": True,
        "input_usd_per_m": 2.00,
        "cached_usd_per_m": 0.50,
        "output_usd_per_m": 6.00,
        "detail": "Escalate after Composer stalls. Do not use because it is stronger.",
    },
    {
        "id": "grok-4.6-fast",
        "label": "Grok 4.6 Fast",
        "worker": "cursor_acp",
        "tier": "difficult",
        "variant": "fast",
        "paid": True,
        "input_usd_per_m": 2.00,
        "cached_usd_per_m": 0.50,
        "output_usd_per_m": 6.00,
        "detail": "Fast variant. Disabled unless explicitly allowed.",
    },
]


def _coding_settings(settings: AppSettings | None = None) -> CodingSettings:
    if settings is not None:
        return settings.coding
    from ..config import load_settings

    return load_settings().coding


def resolve_model(model_id: str, settings: AppSettings | None = None) -> dict[str, Any] | None:
    coding = _coding_settings(settings)
    aliases = {
        "composer": coding.composer_model,
        "grok": coding.grok_model,
        "specialist": coding.specialist_model,
        "local": "local-qwen",
    }
    wanted = aliases.get((model_id or "").strip().lower(), model_id)
    for item in CURSOR_MODEL_CATALOG:
        if item["id"] == wanted:
            return dict(item)
    if wanted:
        return {
            "id": wanted,
            "label": wanted,
            "worker": "cursor_acp",
            "tier": "specialist",
            "variant": "standard",
            "paid": True,
            "detail": "Configured specialist identifier. Not in the built-in catalog.",
        }
    return None


def probe_cursor_models(settings: AppSettings | None = None) -> dict[str, Any]:
    """List configured models. Live ACP is not started from this probe."""
    coding = _coding_settings(settings)
    command = shutil.which("agent") or shutil.which("cursor-agent") or shutil.which("cursor")
    status = "found" if command else "not_connected"
    models = []
    for item in CURSOR_MODEL_CATALOG:
        row = dict(item)
        if row["variant"] == "fast" and not coding.allow_fast_variants:
            row["selectable"] = False
            row["blocked_reason"] = "Fast variants are off. Enable allow_fast_variants to use them."
        else:
            row["selectable"] = True
            row["blocked_reason"] = ""
        if row["id"] == coding.composer_model:
            row["role"] = "composer"
        elif row["id"] == coding.grok_model:
            row["role"] = "grok"
        elif coding.specialist_model and row["id"] == coding.specialist_model:
            row["role"] = "specialist"
        else:
            row["role"] = ""
        models.append(row)
    if coding.specialist_model and not any(m["id"] == coding.specialist_model for m in models):
        extra = resolve_model(coding.specialist_model, settings) or {}
        extra["selectable"] = True
        extra["role"] = "specialist"
        extra["blocked_reason"] = ""
        models.append(extra)
    return {
        "status": status,
        "command": command,
        "allow_fast_variants": coding.allow_fast_variants,
        "composer_model": coding.composer_model,
        "grok_model": coding.grok_model,
        "specialist_model": coding.specialist_model,
        "local_max_attempts": coding.local_max_attempts,
        "models": models,
        "note": (
            "Cursor CLI is on PATH. ACP sessions are not started by this probe."
            if command
            else "Cursor `agent acp` is not on PATH. Paid workers stay not_connected."
        ),
    }
