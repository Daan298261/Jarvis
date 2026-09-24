"""RFC-0116/0171 decision-tier Settings + Reflex metrics API. Never echoes TypeSafe secrets."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config as app_config
from ..decision.audit import list_events
from ..decision.jev_client import reset_http_post, using_labeled_fixture
from ..decision.laya import enable_and_warm, install_managed, reset_runtime, set_enabled, status as laya_status
from ..decision.metrics import reset_metrics, snapshot as metrics_snapshot
from ..decision.provider_select import public_profiles
from ..decision.tier import bind_typesafe_key, probe_jev, resolve_status, set_decision_tier, set_notify_requested
from ..licensing.inference import InferenceCredentialError

router = APIRouter(prefix="/api/decision", tags=["decision"])


class DecisionTierIn(BaseModel):
    tier: Literal["local", "jev_optional", "jev_plus"]


class TypesafeKeyIn(BaseModel):
    secret: str = Field(min_length=1, max_length=4000)
    label: str = Field(default="TypeSafe Jev", max_length=120)


class LayaEnableIn(BaseModel):
    enabled: bool = True
    warm: bool = True


@router.get("/jev")
async def jev_status() -> dict[str, Any]:
    return resolve_status()


@router.put("/jev")
async def jev_update(body: DecisionTierIn) -> dict[str, Any]:
    try:
        set_decision_tier(body.tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return resolve_status()


@router.post("/jev/notify")
async def jev_notify() -> dict[str, Any]:
    stamp = set_notify_requested()
    status = resolve_status()
    return {**status, "notify_requested_at": stamp, "jev_availability": status["jev_availability"]}


@router.post("/jev/credentials")
async def jev_bind_key(body: TypesafeKeyIn) -> dict[str, Any]:
    try:
        record = bind_typesafe_key(body.secret, label=body.label)
    except InferenceCredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    probed = probe_jev()
    return {
        "credential": {"id": record.get("id"), "provider": record.get("provider"), "label": record.get("label")},
        "status": probed,
    }


@router.post("/jev/probe")
async def jev_probe() -> dict[str, Any]:
    return probe_jev()


@router.get("/jev/audit")
async def jev_audit(limit: int = 40) -> dict[str, Any]:
    return {"events": list_events(limit=limit), "fixture": using_labeled_fixture()}


@router.post("/jev/reset-fixture")
async def jev_reset_fixture() -> dict[str, Any]:
    """Labeled fixtures are process-local; this clears a test double without claiming live success."""
    reset_http_post()
    return {"ok": True, "fixture": using_labeled_fixture()}


@router.get("/reflex/metrics")
async def reflex_metrics() -> dict[str, Any]:
    """Control Room hook: p50/p95/p99 + fallback rate per decision class/provider."""
    return metrics_snapshot()


@router.get("/reflex/providers")
async def reflex_providers(decision_class: str = "persona_model_routing") -> dict[str, Any]:
    return public_profiles(decision_class)


@router.get("/laya")
async def laya_get() -> dict[str, Any]:
    return laya_status()


@router.post("/laya/install")
async def laya_install() -> dict[str, Any]:
    try:
        manifest = install_managed()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "manifest": manifest, "status": laya_status()}


@router.post("/laya/enable")
async def laya_enable(body: LayaEnableIn) -> dict[str, Any]:
    settings = app_config.load_settings()
    values = settings.decision.model_dump()
    try:
        if body.enabled:
            if body.warm:
                status = enable_and_warm()
            else:
                if not laya_status().get("installed"):
                    install_managed()
                set_enabled(True)
                status = laya_status()
            values["laya_enabled"] = True
            values["laya_warm"] = bool(status.get("warm"))
        else:
            set_enabled(False)
            values["laya_enabled"] = False
            values["laya_warm"] = False
            status = laya_status()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings.decision = type(settings.decision).model_validate(values)
    app_config.save_settings(settings)
    return status


@router.post("/laya/reset")
async def laya_reset() -> dict[str, Any]:
    reset_runtime()
    reset_metrics()
    return laya_status()
