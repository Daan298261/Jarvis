"""Quartermaster-lite provider selection for Reflex (RFC-0171 / RFC-0141 profile start)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .types import PrivacyMode

ProviderName = Literal["rules", "laya", "jev", "generative_fallback"]


@dataclass(frozen=True)
class ProviderProfile:
    name: ProviderName
    quality_ewma: float = 0.85
    latency_p50_ms: float = 20.0
    latency_p95_ms: float = 50.0
    privacy_ok: bool = True
    cost_per_1k: float = 0.0
    hardware_fit: float = 1.0
    enabled: bool = True


# Explicit starting profiles (measured EWMA lands later via RFC-0141 Arena).
_DEFAULT_PROFILES: dict[str, dict[ProviderName, ProviderProfile]] = {
    "persona_model_routing": {
        "rules": ProviderProfile("rules", quality_ewma=0.9, latency_p50_ms=1.0, latency_p95_ms=3.0),
        "laya": ProviderProfile("laya", quality_ewma=0.88, latency_p50_ms=35.0, latency_p95_ms=80.0),
        "jev": ProviderProfile("jev", quality_ewma=0.9, latency_p50_ms=180.0, latency_p95_ms=350.0, cost_per_1k=0.042),
        "generative_fallback": ProviderProfile(
            "generative_fallback", quality_ewma=0.55, latency_p50_ms=400.0, latency_p95_ms=1200.0, hardware_fit=0.6
        ),
    },
}


def _profiles_for(decision_class: str) -> dict[ProviderName, ProviderProfile]:
    base = _DEFAULT_PROFILES.get("persona_model_routing", {})
    specific = _DEFAULT_PROFILES.get(decision_class)
    if not specific:
        # Clone routing defaults for other classes with slight quality tweaks.
        return {
            name: ProviderProfile(
                name=name,
                quality_ewma=p.quality_ewma,
                latency_p50_ms=p.latency_p50_ms,
                latency_p95_ms=p.latency_p95_ms,
                privacy_ok=p.privacy_ok,
                cost_per_1k=p.cost_per_1k,
                hardware_fit=p.hardware_fit,
                enabled=p.enabled,
            )
            for name, p in base.items()
        }
    return dict(specific)


def score_provider(profile: ProviderProfile, *, privacy: PrivacyMode, cloud_allowed: bool) -> float:
    if not profile.enabled:
        return -1.0
    if profile.name == "jev" and (privacy != "cloud_ok" or not cloud_allowed):
        return -1.0
    if profile.name == "laya" and privacy == "deny_cloud":
        # Laya is local; always privacy-ok unless disabled elsewhere.
        pass
    # Higher is better: quality + hardware, penalize latency and cost.
    return (
        profile.quality_ewma * 100.0
        + profile.hardware_fit * 20.0
        - profile.latency_p50_ms * 0.05
        - profile.latency_p95_ms * 0.02
        - profile.cost_per_1k * 10.0
    )


def select_provider_order(
    decision_class: str,
    *,
    privacy: PrivacyMode,
    cloud_allowed: bool,
    laya_ready: bool,
    jev_ready: bool,
) -> list[ProviderName]:
    """Return try-order. Rules always first; generative always last."""
    profiles = _profiles_for(decision_class)
    ranked: list[tuple[float, ProviderName]] = []
    for name, profile in profiles.items():
        if name == "rules":
            continue
        if name == "generative_fallback":
            continue
        if name == "laya" and not laya_ready:
            continue
        if name == "jev" and not jev_ready:
            continue
        score = score_provider(profile, privacy=privacy, cloud_allowed=cloud_allowed)
        if score < 0:
            continue
        ranked.append((score, name))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    order: list[ProviderName] = ["rules"]
    order.extend(name for _score, name in ranked)
    order.append("generative_fallback")
    return order


def public_profiles(decision_class: str = "persona_model_routing") -> dict[str, Any]:
    profiles = _profiles_for(decision_class)
    return {
        "decision_class": decision_class,
        "providers": {
            name: {
                "quality_ewma": p.quality_ewma,
                "latency_p50_ms": p.latency_p50_ms,
                "latency_p95_ms": p.latency_p95_ms,
                "cost_per_1k": p.cost_per_1k,
                "hardware_fit": p.hardware_fit,
                "enabled": p.enabled,
            }
            for name, p in profiles.items()
        },
    }
