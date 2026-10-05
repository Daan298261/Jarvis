"""RFC-0200 REA MCP enable / root grant APIs (backend only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..security.rea_mcp import (
    REA_AGENTS_PIN,
    REA_MCP_CATALOG_KEY,
    enable_rea_mcp,
    grant_investigation_root,
    mcp_registration_error,
    mcp_registration_status,
)
from ..security.rea_paths import (
    PathNotAllowed,
    configured_investigation_roots,
    resolve_rea_investigation_path,
)

router = APIRouter(prefix="/api/rea", tags=["rea"])


class ReaEnableIn(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReaRootIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = Field(min_length=1, max_length=4000)


class ReaResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(default=None, max_length=4000)
    lta_job_id: str | None = Field(default=None, max_length=32)


def _pending_or_payload(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") == "pending_approval":
        raise HTTPException(status_code=428, detail=result)
    return result


@router.get("/status")
async def rea_status() -> dict[str, Any]:
    from ..config import load_settings

    settings = load_settings()
    return {
        "enabled": bool(settings.rea.enabled),
        "catalog_key": REA_MCP_CATALOG_KEY,
        "package_version": settings.rea.package_version or REA_AGENTS_PIN,
        "launch": ["npx", "-y", f"rea-agents@{settings.rea.package_version or REA_AGENTS_PIN}", "mcp"],
        "investigation_roots": configured_investigation_roots(),
        "mcp_status": mcp_registration_status(),
        "mcp_error": mcp_registration_error(),
        "process_capture_enabled": bool(settings.rea.process_capture_enabled),
        "browser_scenario_enabled": bool(settings.rea.browser_scenario_enabled),
    }


@router.post("/enable")
async def rea_enable(_body: ReaEnableIn | None = None) -> dict[str, Any]:
    try:
        result = await enable_rea_mcp(context={"source": "api"})
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _pending_or_payload(result)


@router.post("/roots")
async def rea_grant_root(body: ReaRootIn) -> dict[str, Any]:
    try:
        result = grant_investigation_root(body.root, context={"source": "api"})
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _pending_or_payload(result)


@router.post("/resolve")
async def rea_resolve(body: ReaResolveIn) -> dict[str, Any]:
    try:
        resolved = resolve_rea_investigation_path(body.path, lta_job_id=body.lta_job_id)
    except PathNotAllowed as exc:
        raise HTTPException(status_code=403, detail=exc.as_dict()) from exc
    return {"path": str(resolved), "lta_job_id": body.lta_job_id or "", "catalog_key": REA_MCP_CATALOG_KEY}
