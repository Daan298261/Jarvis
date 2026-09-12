"""HexStrike AI cybersecurity suite API (RFC-0078)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..security.hexstrike import HEXSTRIKE, gateway_allows

router = APIRouter(prefix="/api/hexstrike", tags=["hexstrike"])


class HexStrikeConfigIn(BaseModel):
    install_path: str | None = None
    python_executable: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)


@router.get("")
async def hexstrike_status():
    status = await HEXSTRIKE.status()
    return status.as_dict()


@router.post("/start")
async def hexstrike_start():
    from ..policy.computer_permissions import evaluate_permission, operator_intent_grant

    decision = evaluate_permission("cyber.hexstrike")
    if decision.status == "deny":
        raise HTTPException(status_code=403, detail=decision.reason)
    if decision.status == "ask":
        try:
            operator_intent_grant("cyber.hexstrike", "allow_session")
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    status = await HEXSTRIKE.ensure_started()
    return status.as_dict()


@router.post("/stop")
async def hexstrike_stop():
    status = await HEXSTRIKE.stop()
    return status.as_dict()


@router.put("/config")
async def hexstrike_config(body: HexStrikeConfigIn):
    status = await HEXSTRIKE.configure(
        install_path=body.install_path,
        python_executable=body.python_executable,
        port=body.port,
    )
    return status.as_dict()


@router.api_route("/upstream/{path:path}", methods=["GET", "POST"])
async def hexstrike_upstream(path: str, request: Request):
    if not gateway_allows(request.method, path):
        raise HTTPException(status_code=403, detail="HexStrike gateway denied this path")
    body = b""
    if request.method.upper() != "GET":
        body = await request.body()
        if len(body) > 64 * 1024:
            raise HTTPException(status_code=413, detail="Request too large")
    try:
        status_code, content, content_type = await HEXSTRIKE.proxy(request.method, path, body)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:400]) from exc
    return Response(content=content, status_code=status_code, media_type=content_type)
