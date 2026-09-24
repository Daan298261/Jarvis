"""Decision-tier preference, Plus entitlement, availability, and fallback (RFC-0116)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from .. import config as app_config
from ..licensing.entitlements import FEATURE_JEV_PLUS, evaluate_cluster_entitlements, has_feature
from ..licensing.inference import get_secret_by_provider, upsert_inference_credential
from ..licensing.lease import get_stored_lease
from . import audit
from .jev_client import JevHttpError, parse_answer, probe_key, using_labeled_fixture

DecisionTier = Literal["local", "jev_optional", "jev_plus"]
Availability = Literal["unavailable", "waitlisted", "connected", "error"]
TYPESAFE_PROVIDER = "typesafe"
WAITLIST_URL = "https://typesafe.ai/"
MAX_JEV_CHOICES = 255


def plus_entitled(lease=None) -> bool:
    stored = lease if lease is not None else get_stored_lease()
    return has_feature(stored, FEATURE_JEV_PLUS)


def _wan_blocked() -> bool:
    try:
        from ..policy.computer_permissions import persisted_mode

        return persisted_mode("network.internet") == "deny"
    except Exception:
        return False


def _persist_probe(*, availability: Availability, error: str = "", latency_ms: float | None = None, model: str = "") -> None:
    settings = app_config.load_settings()
    values = settings.decision.model_dump()
    values["last_availability"] = availability
    values["last_probe_error"] = error[:400]
    values["last_probe_at"] = datetime.now(timezone.utc).isoformat()
    values["last_probe_latency_ms"] = latency_ms
    values["last_model"] = model
    settings.decision = type(settings.decision).model_validate(values)
    app_config.save_settings(settings)


def set_decision_tier(tier: str) -> DecisionTier:
    cleaned = str(tier or "local").strip().lower()
    if cleaned not in {"local", "jev_optional", "jev_plus"}:
        raise ValueError("decision_tier must be local, jev_optional, or jev_plus")
    settings = app_config.load_settings()
    values = settings.decision.model_dump()
    values["tier"] = cleaned
    if cleaned == "local":
        values["last_availability"] = "unavailable" if not values.get("notify_requested_at") else values.get(
            "last_availability", "unavailable"
        )
    settings.decision = type(settings.decision).model_validate(values)
    app_config.save_settings(settings)
    return cleaned  # type: ignore[return-value]


def set_notify_requested() -> str:
    stamp = datetime.now(timezone.utc).isoformat()
    settings = app_config.load_settings()
    values = settings.decision.model_dump()
    values["notify_requested_at"] = stamp
    if values.get("last_availability") == "unavailable":
        values["last_availability"] = "waitlisted"
    settings.decision = type(settings.decision).model_validate(values)
    app_config.save_settings(settings)
    return stamp


def bind_typesafe_key(secret: str, *, label: str = "TypeSafe Jev") -> dict[str, Any]:
    record = upsert_inference_credential(
        provider=TYPESAFE_PROVIDER,
        label=label or "TypeSafe Jev",
        secret=secret,
        endpoint="https://api.typesafe.ai/v1/systemone",
    )
    return record


def resolve_status() -> dict[str, Any]:
    settings = app_config.load_settings()
    decision = settings.decision
    lease = get_stored_lease()
    entitlements = evaluate_cluster_entitlements(lease)
    plus_ok = has_feature(lease, FEATURE_JEV_PLUS)
    key_present = bool(get_secret_by_provider(TYPESAFE_PROVIDER))
    wan_blocked = _wan_blocked()
    tier: DecisionTier = decision.tier  # type: ignore[assignment]
    availability: Availability = decision.last_availability  # type: ignore[assignment]
    owner_error = ""
    plus_blocked = tier == "jev_plus" and not plus_ok

    if wan_blocked and tier != "local":
        availability = "unavailable"
        owner_error = "Internet permission is denied, so TypeSafe Jev cannot be reached."
    elif plus_blocked:
        availability = "error"
        owner_error = "Plus entitlement required. Attach decision.jev_plus on the signed lease (or merge it into evaluate_cluster_entitlements) before selecting Plus."
    elif tier == "local":
        if decision.notify_requested_at and availability == "connected":
            availability = "waitlisted"
        elif availability == "connected":
            availability = "unavailable"
        if not owner_error and availability in {"unavailable", "waitlisted"}:
            owner_error = ""
    elif not key_present:
        availability = "unavailable" if not decision.notify_requested_at else decision.last_availability
        if availability == "connected":
            availability = "unavailable"
        if availability not in {"unavailable", "waitlisted", "error"}:
            availability = "unavailable"
        # RFC-0171: Jev is publicly usable; still requires real probe + explicit opt-in.
        owner_error = (
            "TypeSafe Jev is available publicly, but cloud decisions stay off until you opt in, "
            "bind a real API key, and a probe succeeds. Local Reflex (rules/Laya) remains the default."
        )
    elif availability == "connected" and not key_present:
        availability = "error"
        owner_error = "Saved probe is stale because the TypeSafe key is missing."

    return {
        "decision_tier": tier,
        "jev_availability": availability,
        "plus_entitled": plus_ok,
        "plus_feature": FEATURE_JEV_PLUS,
        "entitlements_features": list(entitlements.get("features") or []),
        "key_bound": key_present,
        "notify_requested_at": decision.notify_requested_at,
        "waitlist_url": WAITLIST_URL,
        "docs_url": WAITLIST_URL,
        "public_availability_note": (
            "Jev is publicly usable (RFC-0171). Owner cloud opt-in + real probe still required; "
            "no fake-live attribution."
        ),
        "last_probe_at": decision.last_probe_at,
        "last_probe_latency_ms": decision.last_probe_latency_ms,
        "last_probe_error": owner_error or decision.last_probe_error,
        "last_model": decision.last_model,
        "owner_error": owner_error,
        "fixture": using_labeled_fixture(),
        "cta": _cta(availability, plus_blocked, key_present),
    }


def _cta(availability: Availability, plus_blocked: bool, key_present: bool) -> str:
    if plus_blocked:
        return "Plus entitlement required"
    if availability == "connected":
        return ""
    if not key_present:
        return "Bind TypeSafe API key"
    return "Retry probe"


def jev_calls_allowed(status: dict[str, Any] | None = None) -> tuple[bool, str]:
    snapshot = status or resolve_status()
    if snapshot["decision_tier"] == "local":
        return False, "decision_tier is local"
    if snapshot["decision_tier"] == "jev_plus" and not snapshot["plus_entitled"]:
        return False, "plus entitlement missing"
    if snapshot["jev_availability"] != "connected":
        return False, f"jev_availability is {snapshot['jev_availability']}"
    if not snapshot["key_bound"]:
        return False, "typesafe key missing"
    return True, ""


def probe_jev() -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    status = resolve_status()
    if status["decision_tier"] == "local":
        audit.record_event(
            "jev_probe",
            {
                "ok": False,
                "source": "heuristics",
                "fallback_used": True,
                "fallback_reason": "decision_tier is local",
                "decision_tier": "local",
            },
        )
        return {**status, "probed": False, "owner_error": "Local tier never opens a TypeSafe socket."}
    if status["decision_tier"] == "jev_plus" and not status["plus_entitled"]:
        _persist_probe(availability="error", error=status["owner_error"])
        audit.record_event(
            "jev_error",
            {
                "ok": False,
                "source": "heuristics",
                "fallback_used": True,
                "fallback_reason": "plus entitlement missing",
                "decision_tier": "jev_plus",
                "plus_entitled": False,
            },
        )
        return resolve_status() | {"probed": False}
    key = get_secret_by_provider(TYPESAFE_PROVIDER)
    if not key:
        availability: Availability = "waitlisted" if status["notify_requested_at"] else "unavailable"
        _persist_probe(availability=availability, error=status["owner_error"] or "TypeSafe API key is missing")
        return resolve_status() | {"probed": False}
    if _wan_blocked():
        _persist_probe(availability="unavailable", error="Internet permission is denied")
        return resolve_status() | {"probed": False}
    try:
        result = probe_key(key)
    except JevHttpError as exc:
        _persist_probe(availability="error", error=str(exc))
        audit.record_event(
            "jev_error",
            {
                "ok": False,
                "http_status": exc.status_code,
                "source": "heuristics",
                "fallback_used": True,
                "fallback_reason": str(exc),
                "fixture": using_labeled_fixture(),
            },
        )
        return resolve_status() | {"probed": True, "ok": False}
    latency = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
    ready = parse_answer("ready", (result.get("answers") or {}).get("ready"))
    if ready is None:
        _persist_probe(availability="error", error="Probe succeeded HTTP but had no typed noul answer", latency_ms=latency)
        return resolve_status() | {"probed": True, "ok": False}
    _persist_probe(availability="connected", latency_ms=latency, model=str(result.get("model") or ""))
    audit.record_event(
        "jev_probe",
        {
            "ok": True,
            "source": "jev",
            "model": result.get("model"),
            "latency_ms": round(latency, 1),
            "fixture": bool(result.get("fixture")),
            "fallback_used": False,
        },
    )
    return resolve_status() | {"probed": True, "ok": True}


def decide_turn(
    *,
    user_message: str,
    candidate_tools: list[str],
    local_speak: str | None = None,
    local_complexity: int = 1,
    local_escalate: bool = False,
    policy_requires_approval: bool = False,
    policy_deny: bool = False,
) -> dict[str, Any]:
    """RFC-0116 compatibility wrapper over the RFC-0171 Reflex Lane."""
    request_id = uuid4().hex
    status = resolve_status()
    from .wire import compose_turn_decisions

    composed = compose_turn_decisions(
        user_message=user_message,
        candidate_tools=candidate_tools,
        local_speak=local_speak,
        local_complexity=local_complexity,
        local_escalate=local_escalate,
        policy_requires_approval=policy_requires_approval,
        policy_deny=policy_deny,
        cloud_ok=bool(jev_calls_allowed(status)[0]),
    )
    source = composed.get("source") or "rules"
    # Preserve RFC-0116 audit vocabulary for Jev-attributed turns.
    if source == "jev":
        audit_kind = "jev_decision"
        legacy_source = "jev"
        legacy_fallback = bool(composed.get("fallback_used"))
        legacy_reason = composed.get("fallback_reason") or ""
    else:
        # Non-Jev path is always an explicit local/Reflex fallback for RFC-0116 callers.
        audit_kind = "jev_fallback" if status["decision_tier"] != "local" else "reflex_decision"
        if status["decision_tier"] == "local":
            audit_kind = "jev_fallback"
        legacy_source = "heuristics" if source in {"rules", "generative_fallback", "deadline_fallback", "cache"} else source
        if source == "laya":
            legacy_source = "laya"
        legacy_fallback = True
        legacy_reason = composed.get("fallback_reason") or (
            "local default" if status["decision_tier"] == "local" else f"reflex:{source}"
        )

    event = {
        "request_id": request_id,
        "decision_tier": status["decision_tier"],
        "jev_availability": status["jev_availability"],
        "plus_entitled": status["plus_entitled"],
        "source": legacy_source,
        "reflex_source": source,
        "fallback_used": legacy_fallback,
        "fallback_reason": legacy_reason,
        "model": composed.get("model") or "",
        "latency_ms": composed.get("latency_ms"),
        "answers": composed.get("answers") or {},
        "tool_select": composed.get("tool_select"),
        "speak_class": composed.get("speak_class"),
        "complexity_tier": composed.get("complexity_tier"),
        "escalate": composed.get("escalate"),
        "approval_needed": composed.get("approval_needed"),
        "batch_size": composed.get("batch_size"),
        "decision_class": composed.get("decision_class"),
        "provider": composed.get("provider"),
    }
    if source == "jev":
        event["source"] = "jev"
        event["jev_availability"] = "connected"
    audit.record_event(audit_kind, event)
    return event
