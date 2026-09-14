from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..policy.cyber_ato import (
    AtoError,
    evaluate,
    issue_license,
    install_license,
    renew_license,
    revoke_license,
)

router = APIRouter(prefix="/api/cyber-ato", tags=["cyber-ato"])


class IssueIn(BaseModel):
    law_enforcement: bool = False
    blue_team: bool = True
    red_team: bool = False
    valid_days: int = Field(default=90, ge=1, le=3660)
    renew_in_days: int | None = Field(default=None, ge=1, le=3660)
    case_ref: str = Field(default="", max_length=200)
    install: bool = True


class InstallIn(BaseModel):
    license: dict[str, Any]


class RenewIn(BaseModel):
    valid_days: int = Field(default=90, ge=1, le=3660)
    renew_in_days: int | None = Field(default=None, ge=1, le=3660)
    install: bool = True


@router.get("/status")
def cyber_ato_status():
    return evaluate().as_dict()


@router.post("/issue")
def cyber_ato_issue(body: IssueIn):
    try:
        document = issue_license(
            law_enforcement=body.law_enforcement,
            blue_team=body.blue_team,
            red_team=body.red_team,
            valid_days=body.valid_days,
            renew_in_days=body.renew_in_days,
            case_ref=body.case_ref,
            install=body.install,
        )
    except AtoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"license": document, "status": evaluate().as_dict()}


@router.post("/install")
def cyber_ato_install(body: InstallIn):
    try:
        install_license(body.license)
    except AtoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return evaluate().as_dict()


@router.post("/renew")
def cyber_ato_renew(body: RenewIn):
    try:
        document = renew_license(
            valid_days=body.valid_days,
            renew_in_days=body.renew_in_days,
            install=body.install,
        )
    except AtoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"license": document, "status": evaluate().as_dict()}


@router.post("/revoke")
def cyber_ato_revoke():
    revoke_license()
    return evaluate().as_dict()
