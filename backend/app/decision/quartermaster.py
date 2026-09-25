"""Quartermaster: per-class Reflex provider selection (RFC-0171 / RFC-0141 seam)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .types import PrivacyMode, ProviderName

_LOCK = threading.Lock()


@dataclass
class ProviderStats:
    ewma_latency_ms: float = 80.0
    ewma_quality: float = 0.75
    samples: int = 0


@dataclass
class ProviderProfile:
    name: ProviderName
    version: str = "default"
    privacy: PrivacyMode = "local_only"
    cost_weight: float = 0.0
    hardware_ok: bool = True
    enabled: bool = True
    stats: ProviderStats = field(default_factory=ProviderStats)


# Explicit starting profiles — measured EWMA updates later.
_PROFILES: dict[str, list[ProviderProfile]] = {
    "default": [
        ProviderProfile("rules", version="heuristic-1", privacy="local_only", cost_weight=0.0),
        ProviderProfile("laya", version="managed", privacy="local_only", cost_weight=0.05),
        ProviderProfile("jev", version="jev-latest", privacy="allow_cloud", cost_weight=0.4),
        ProviderProfile("generative", version="ornith-fallback", privacy="local_only", cost_weight=1.0),
    ],
}


def _clone_default() -> list[ProviderProfile]:
    return [
        ProviderProfile(
            name=p.name,
            version=p.version,
            privacy=p.privacy,
            cost_weight=p.cost_weight,
            hardware_ok=p.hardware_ok,
            enabled=p.enabled,
            stats=ProviderStats(
                ewma_latency_ms=p.stats.ewma_latency_ms,
                ewma_quality=p.stats.ewma_quality,
                samples=p.stats.samples,
            ),
        )
        for p in _PROFILES["default"]
    ]


_CLASS_PROFILES: dict[str, list[ProviderProfile]] = {}


def profiles_for(decision_class: str) -> list[ProviderProfile]:
    with _LOCK:
        if decision_class not in _CLASS_PROFILES:
            _CLASS_PROFILES[decision_class] = _clone_default()
        return list(_CLASS_PROFILES[decision_class])


def record_outcome(
    decision_class: str,
    provider: ProviderName,
    *,
    latency_ms: float,
    quality: float,
    alpha: float = 0.2,
) -> None:
    with _LOCK:
        if decision_class not in _CLASS_PROFILES:
            _CLASS_PROFILES[decision_class] = _clone_default()
        for profile in _CLASS_PROFILES[decision_class]:
            if profile.name != provider:
                continue
            stats = profile.stats
            if stats.samples == 0:
                stats.ewma_latency_ms = float(latency_ms)
                stats.ewma_quality = float(quality)
            else:
                stats.ewma_latency_ms = (1 - alpha) * stats.ewma_latency_ms + alpha * float(latency_ms)
                stats.ewma_quality = (1 - alpha) * stats.ewma_quality + alpha * float(quality)
            stats.samples += 1
            return


def reset_quartermaster() -> None:
    with _LOCK:
        _CLASS_PROFILES.clear()


def _privacy_allows(profile: ProviderProfile, privacy: PrivacyMode) -> bool:
    if privacy == "require_local" and profile.privacy == "allow_cloud":
        return False
    if privacy == "local_only" and profile.privacy == "allow_cloud":
        return False
    return True


def select_provider_order(
    decision_class: str,
    *,
    privacy: PrivacyMode,
    laya_ready: bool,
    jev_ready: bool,
    prefer_rules_only: bool = False,
) -> list[ProviderName]:
    """
    Order: hard rules first, then measured Laya (preferred when installed),
    then opt-in Jev, generative last.
    """
    if prefer_rules_only:
        return ["rules", "generative"]

    scored: list[tuple[float, ProviderName]] = []
    for profile in profiles_for(decision_class):
        if not profile.enabled or not profile.hardware_ok:
            continue
        if not _privacy_allows(profile, privacy):
            continue
        if profile.name == "laya" and not laya_ready:
            continue
        if profile.name == "jev" and not jev_ready:
            continue
        # Lower score is better.
        latency_term = profile.stats.ewma_latency_ms / 100.0
        quality_term = 1.0 - profile.stats.ewma_quality
        cost_term = profile.cost_weight
        # Prefer Laya slightly when available (local low-latency).
        bias = -0.15 if profile.name == "laya" and laya_ready else 0.0
        if profile.name == "rules":
            bias = -1.0  # always try rules first for hard / baseline
        if profile.name == "generative":
            bias = 5.0  # last
        score = latency_term + quality_term + cost_term + bias
        scored.append((score, profile.name))

    scored.sort(key=lambda item: (item[0], item[1]))
    ordered = [name for _score, name in scored]
    # Guarantee rules first, generative last when present.
    if "rules" in ordered:
        ordered = ["rules", *[n for n in ordered if n != "rules"]]
    if "generative" in ordered:
        ordered = [*[n for n in ordered if n != "generative"], "generative"]
    if not ordered:
        return ["rules", "generative"]
    return ordered


def selection_snapshot(decision_class: str = "default") -> dict[str, Any]:
    return {
        "decision_class": decision_class,
        "providers": [
            {
                "name": p.name,
                "version": p.version,
                "privacy": p.privacy,
                "enabled": p.enabled,
                "hardware_ok": p.hardware_ok,
                "cost_weight": p.cost_weight,
                "ewma_latency_ms": p.stats.ewma_latency_ms,
                "ewma_quality": p.stats.ewma_quality,
                "samples": p.stats.samples,
            }
            for p in profiles_for(decision_class)
        ],
    }
