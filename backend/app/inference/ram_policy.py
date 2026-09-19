"""RAM-aware context ceilings and llama.cpp fit tuning (64 GB class desktops)."""

from __future__ import annotations

from typing import Any

from ..config import AppSettings, load_settings
from ..hardware import detect_hardware, hardware_dict
from ..inference.profiles import ModelProfile

CONTEXT_TIER_8K = 8192
CONTEXT_TIER_16K = 16384
CONTEXT_TIER_32K = 32768
CONTEXT_TIER_64K = 65536

RAM_TIERS = (
    (56.0, CONTEXT_TIER_64K),
    (40.0, CONTEXT_TIER_32K),
    (0.0, CONTEXT_TIER_32K),
)


def _ram_total_gb() -> float:
    cached = hardware_dict()
    if cached.get("ram_total_gb"):
        return float(cached["ram_total_gb"])
    return float(detect_hardware().ram_total_gb or 0)


def _vram_total_mib() -> int | None:
    cached = hardware_dict()
    value = cached.get("vram_total_mib")
    if isinstance(value, int) and value > 0:
        return value
    detected = detect_hardware().vram_total_mib
    return detected if detected and detected > 0 else None


def ram_supported_context_ceiling() -> int:
    """Upper context window justified by installed system RAM (KV cache headroom)."""
    ram_gb = _ram_total_gb()
    for threshold, ceiling in RAM_TIERS:
        if ram_gb >= threshold:
            return ceiling
    return CONTEXT_TIER_16K


def hardware_context_ceiling(profile: ModelProfile | Any, settings: AppSettings | None = None) -> int:
    """Effective n_ctx cap: profile limit raised to RAM-safe ceiling on large-memory PCs."""
    del settings
    declared = int(getattr(profile, "context_size", 0) or 0) or CONTEXT_TIER_32K
    ram_ceiling = ram_supported_context_ceiling()
    if _ram_total_gb() >= 48:
        declared = max(declared, min(ram_ceiling, CONTEXT_TIER_64K))
    return max(CONTEXT_TIER_8K, min(declared, ram_ceiling))


def effective_fit_target_mib(settings: AppSettings | None = None) -> int:
    """Tune llama.cpp --fit-target: spill weights/KV to RAM on large-memory PCs."""
    app = settings or load_settings()
    base = max(256, int(app.inference.fit_target_mib or 1024))
    if not app.inference.fit:
        return base
    ram_gb = _ram_total_gb()
    vram_mib = _vram_total_mib()
    if ram_gb >= 56 and vram_mib:
        # 64 GB RAM + discrete GPU: keep more layers on GPU, let KV grow in RAM.
        return min(max(base, 4096), max(2048, vram_mib - 768))
    if ram_gb >= 48 and not vram_mib:
        # CPU-only / no metrics: conservative fit, large ctx still OK in RAM.
        return min(base, 512)
    if ram_gb >= 40:
        return max(base, 2048)
    return base


def offload_summary(settings: AppSettings | None = None) -> dict[str, Any]:
    app = settings or load_settings()
    ram_gb = _ram_total_gb()
    vram_mib = _vram_total_mib()
    return {
        "ram_total_gb": round(ram_gb, 1),
        "vram_total_mib": vram_mib,
        "ram_context_ceiling": ram_supported_context_ceiling(),
        "fit_enabled": bool(app.inference.fit),
        "fit_target_mib": effective_fit_target_mib(app),
        "kv_in_ram_likely": ram_gb >= 40 and bool(app.inference.fit),
    }
