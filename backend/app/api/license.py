from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..licensing.cluster import get_cluster_id
from ..licensing.entitlements import evaluate_cluster_entitlements
from ..licensing.inference import (
    InferenceCredentialError,
    delete_inference_credential,
    list_inference_credentials,
    upsert_inference_credential,
)
from ..licensing.lease import LicenseError, get_stored_lease, parse_signed_lease
from ..licensing.service import get_license_status, refresh_lease, validate_offline

router = APIRouter(prefix="/api/license", tags=["license"])


class LeaseRefreshIn(BaseModel):
    lease: dict[str, Any]


class InferenceCredentialIn(BaseModel):
    provider: str
    label: str
    secret: str
    endpoint: str | None = None
    credential_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/status")
async def license_status():
    return get_license_status()


@router.get("/cluster")
async def license_cluster():
    return {"cluster_id": get_cluster_id()}


@router.post("/validate")
async def license_validate():
    return validate_offline()


@router.post("/refresh")
async def license_refresh(body: LeaseRefreshIn):
    try:
        lease = parse_signed_lease(body.lease)
        return refresh_lease(lease)
    except LicenseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/entitlements")
async def license_entitlements():
    lease = get_stored_lease()
    validation = validate_offline()
    entitlements = evaluate_cluster_entitlements(lease)
    return {
        "validation": validation,
        "entitlements": entitlements,
    }


@router.get("/inference-credentials")
async def inference_credentials_list():
    return {"credentials": list_inference_credentials()}


@router.post("/inference-credentials")
async def inference_credentials_upsert(body: InferenceCredentialIn):
    try:
        record = upsert_inference_credential(
            provider=body.provider,
            label=body.label,
            secret=body.secret,
            endpoint=body.endpoint,
            credential_id=body.credential_id,
            metadata=body.metadata,
        )
        return {"credential": record}
    except InferenceCredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/inference-credentials/{credential_id}")
async def inference_credentials_delete(credential_id: str):
    deleted = delete_inference_credential(credential_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Inference credential not found")
    return {"deleted": True, "id": credential_id}
