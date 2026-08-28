from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..workers import credentials as cred_broker
from ..workers.environments import (
    EnvironmentError,
    EnvironmentNotFound,
    create_environment,
    delete_environment,
    inspect_environment,
    list_audit_events,
    list_environments,
    reset_environment,
    resume_environment,
    revoke_environment_credential,
    start_environment,
    store_environment_credential,
    suspend_environment,
)

router = APIRouter(prefix="/api/worker-environments", tags=["worker-environments"])


class CreateEnvironmentIn(BaseModel):
    name: str
    worker_kind: str = "general"
    agent_profile: str = "default"
    quotas: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StoreCredentialIn(BaseModel):
    capability: str
    label: str
    secret: str
    credential_id: str | None = None


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EnvironmentNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, EnvironmentError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, cred_broker.CredentialError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def list_worker_environments():
    return {"environments": list_environments()}


@router.post("")
async def create_worker_environment(body: CreateEnvironmentIn):
    try:
        return create_environment(
            name=body.name,
            worker_kind=body.worker_kind,
            agent_profile=body.agent_profile,
            quotas=body.quotas,
            metadata=body.metadata,
        )
    except (EnvironmentError, cred_broker.CredentialError) as exc:
        raise _http_error(exc) from exc


@router.get("/audit")
async def worker_environment_audit(environment_id: str | None = None, limit: int = 100):
    return {"events": list_audit_events(environment_id=environment_id, limit=limit)}


@router.get("/{environment_id}")
async def get_worker_environment(environment_id: str):
    try:
        return inspect_environment(environment_id)
    except EnvironmentError as exc:
        raise _http_error(exc) from exc


@router.get("/{environment_id}/status")
async def get_worker_environment_status(environment_id: str):
    try:
        from ..workers.environments import environment_status

        return environment_status(environment_id)
    except EnvironmentError as exc:
        raise _http_error(exc) from exc


@router.post("/{environment_id}/start")
async def start_worker_environment(environment_id: str):
    try:
        return start_environment(environment_id)
    except EnvironmentError as exc:
        raise _http_error(exc) from exc


@router.post("/{environment_id}/suspend")
async def suspend_worker_environment(environment_id: str):
    try:
        return suspend_environment(environment_id)
    except EnvironmentError as exc:
        raise _http_error(exc) from exc


@router.post("/{environment_id}/resume")
async def resume_worker_environment(environment_id: str):
    try:
        return resume_environment(environment_id)
    except EnvironmentError as exc:
        raise _http_error(exc) from exc


@router.post("/{environment_id}/reset")
async def reset_worker_environment(environment_id: str):
    try:
        return reset_environment(environment_id)
    except EnvironmentError as exc:
        raise _http_error(exc) from exc


@router.delete("/{environment_id}")
async def delete_worker_environment(environment_id: str):
    try:
        return delete_environment(environment_id)
    except EnvironmentError as exc:
        raise _http_error(exc) from exc


@router.post("/{environment_id}/credentials")
async def store_worker_credential(environment_id: str, body: StoreCredentialIn):
    try:
        return store_environment_credential(
            environment_id,
            capability=body.capability,
            label=body.label,
            secret=body.secret,
            credential_id=body.credential_id,
        )
    except (EnvironmentError, cred_broker.CredentialError) as exc:
        raise _http_error(exc) from exc


@router.delete("/{environment_id}/credentials/{credential_id}")
async def revoke_worker_credential(environment_id: str, credential_id: str):
    try:
        return revoke_environment_credential(environment_id, credential_id)
    except (EnvironmentError, cred_broker.CredentialError) as exc:
        raise _http_error(exc) from exc
