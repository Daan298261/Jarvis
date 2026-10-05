"""RFC-0198 LTA protected-folder recovery APIs (backend only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..security.lta_archive import (
    THEMIS_PERSONA_HINT,
    cert_candidates_payload,
    get_lta_job,
    list_lta_jobs,
    start_protected_folder_open,
    succeeded_lta_extract_root,
)
from ..security.lta_errors import LtaError, PathDenied

router = APIRouter(prefix="/api/lta", tags=["lta"])


class ProtectedFolderOpenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_path: str = Field(min_length=1, max_length=4000)
    archive_path: str | None = Field(default=None, max_length=4000)
    # Tests / operators may force sync completion; default is background job.
    sync: bool = False


def _http_for_lta(exc: LtaError) -> HTTPException:
    status = 422
    if isinstance(exc, PathDenied):
        status = 403
    elif exc.code == "manifest_not_found":
        status = 404
    elif exc.code == "platform_unsupported":
        status = 501
    return HTTPException(status_code=status, detail=exc.as_dict())


@router.post("/protected-folder/open")
async def open_protected_folder(body: ProtectedFolderOpenIn) -> dict[str, Any]:
    """Start authorized LTA unlock for an owner-scoped manifest/archive."""
    try:
        result = start_protected_folder_open(
            manifest_path=body.manifest_path,
            archive_path=body.archive_path,
            sync=body.sync,
        )
    except PathDenied as exc:
        raise _http_for_lta(exc) from exc
    except LtaError as exc:
        raise _http_for_lta(exc) from exc
    payload = dict(result)
    payload.setdefault("persona_bind_hint", dict(THEMIS_PERSONA_HINT))
    return payload


@router.get("/jobs")
async def lta_jobs() -> dict[str, Any]:
    return {
        "jobs": list_lta_jobs(),
        "persona_bind_hint": dict(THEMIS_PERSONA_HINT),
    }


@router.get("/jobs/{job_id}")
async def lta_job_detail(job_id: str) -> dict[str, Any]:
    try:
        return get_lta_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown LTA job") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/extract-root")
async def lta_extract_root(job_id: str) -> dict[str, Any]:
    """RFC-0200: post-extract path after RFC-0198 open succeeded. No second unlock."""
    try:
        root = succeeded_lta_extract_root(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown LTA job") from exc
    except PathDenied as exc:
        raise _http_for_lta(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "job_id": job_id,
        "extract_root": str(root),
        "persona_bind_hint": dict(THEMIS_PERSONA_HINT),
    }


@router.get("/certs/candidates")
async def lta_cert_candidates() -> dict[str, Any]:
    """Thumbprints/SKIs available for Access match — no private key export."""
    return cert_candidates_payload()
