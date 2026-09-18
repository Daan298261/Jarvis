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
from .jev_client import JevHttpError, parse_answer, post_systemone, probe_key, using_labeled_fixture

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
        availability = "waitlisted" if decision.notify_requested_at else "unavailable"
        owner_error = "Jev is early access. Join the TypeSafe waitlist, then bind a real API key. Notify when ready does not mean connected."
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
        return "Notify when ready"
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
    request_id = uuid4().hex
    status = resolve_status()
    allowed, reason = jev_calls_allowed(status)
    base = {
        "request_id": request_id,
        "decision_tier": status["decision_tier"],
        "jev_availability": status["jev_availability"],
        "plus_entitled": status["plus_entitled"],
        "source": "heuristics",
        "fallback_used": True,
        "fallback_reason": reason or "local default",
        "model": "",
        "latency_ms": None,
        "answers": {},
        "tool_select": None,
        "speak_class": local_speak,
        "complexity_tier": local_complexity,
        "escalate": local_escalate,
        "approval_needed": policy_requires_approval and not policy_deny,
    }
    if status["decision_tier"] == "local" or not allowed:
        if status["decision_tier"] != "local" and not allowed:
            audit.record_event("jev_fallback", {**base, "kind_detail": reason})
        else:
            audit.record_event("jev_fallback", {**base, "kind_detail": "local default"})
        return base

    tools = [name for name in candidate_tools if name][: min(MAX_JEV_CHOICES - 1, 32)]
    questions: dict[str, Any] = {
        "speak_class": {
            "type": "choice",
            "choices": ["social", "technical"],
            "question": "Is the upcoming assistant reply social small-talk or technical?",
        },
        "complexity_tier": {
            "type": "score",
            "question": "Task complexity 1-4 matching Jarvis answer tiers.",
        },
        "escalate": {
            "type": "noul",
            "question": "Does this need a stronger model than the current orchestrator should answer?",
        },
        "approval_needed": {
            "type": "noul",
            "question": "Does this step need Always allow / Allow this time / Deny before it runs?",
        },
    }
    if tools:
        questions["tool_select"] = {
            "type": "choice",
            "choices": [*tools, "none"],
            "question": "Which retrieved tool should this turn use? none if chat-only.",
        }
    started = datetime.now(timezone.utc)
    try:
        result = post_systemone(
            api_key=get_secret_by_provider(TYPESAFE_PROVIDER),
            state={
                "user_message": (user_message or "")[:800],
                "candidate_tools": tools,
                "local_complexity": local_complexity,
            },
            questions=questions,
        )
    except JevHttpError as exc:
        payload = {
            **base,
            "fallback_reason": str(exc),
            "http_status": exc.status_code,
        }
        audit.record_event("jev_error", payload)
        return payload

    latency = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
    answers = result.get("answers") or {}
    parsed = {qid: parse_answer(qid, answers.get(qid)) for qid in questions}
    speak = parsed.get("speak_class")
    complexity = parsed.get("complexity_tier")
    escalate = parsed.get("escalate")
    approval = parsed.get("approval_needed")
    tool = parsed.get("tool_select")

    from .policy import apply_complexity_tier, approval_popup_required, should_escalate

    speak_value = None
    if speak and speak.value in {"social", "technical"}:
        speak_value = str(speak.value)
    complexity_value = apply_complexity_tier(
        local_complexity,
        float(complexity.value) if complexity and complexity.primitive == "score" else None,
    )
    escalate_value = should_escalate(
        local_escalate,
        float(escalate.value) if escalate and escalate.primitive == "noul" else None,
        confidence=escalate.confidence if escalate else None,
    )
    approval_value = approval_popup_required(
        policy_requires=policy_requires_approval,
        policy_deny=policy_deny,
        jev_noul=float(approval.value) if approval and approval.primitive == "noul" else None,
        confidence=approval.confidence if approval else None,
    )
    tool_value = None
    if tool and tool.value != "none" and tool.value in tools:
        tool_value = str(tool.value)

    event = {
        "request_id": request_id,
        "decision_tier": status["decision_tier"],
        "jev_availability": "connected",
        "plus_entitled": status["plus_entitled"],
        "source": "jev",
        "fallback_used": False,
        "fallback_reason": "",
        "model": result.get("model") or "",
        "latency_ms": round(latency, 1),
        "fixture": bool(result.get("fixture")),
        "answers": {
            key: (
                None
                if parsed[key] is None
                else {
                    "type": parsed[key].primitive,
                    parsed[key].primitive: parsed[key].value,
                    "confidence": parsed[key].confidence,
                }
            )
            for key in parsed
        },
        "tool_select": tool_value,
        "speak_class": speak_value or local_speak,
        "complexity_tier": complexity_value,
        "escalate": escalate_value,
        "approval_needed": approval_value,
    }
    audit.record_event("jev_decision", event)
    return event
