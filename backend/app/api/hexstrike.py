"""HexStrike AI operator suite API (RFC-0078/0086/0106)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from ..security.hexstrike import HEXSTRIKE, audit_hexstrike, gateway_allows
from ..security.hexstrike_defensive import (
    CAPABILITY_BY_ID,
    capability_snapshot,
    execute_defensive,
    list_jobs as list_defensive_jobs,
    list_scopes,
    stop_managed_job,
    upsert_scope,
)
from ..security.hexstrike_install import HEXSTRIKE_INSTALLER
from ..security.hexstrike_operator import (
    catalog_snapshot,
    get_operator_job,
    list_job_artifacts,
    list_operator_jobs,
    operate,
    operator_status_extras,
    stop_operator_job,
    sync_operator_surface,
)
from ..security.hexstrike_tools import (
    dependency_catalog_rows,
    install_all_missing,
    install_dependency_by_id,
    install_host_tool,
    install_job_overlay,
    missing_host_tools,
    start_dependency_install,
    get_dependency_install_job,
)

router = APIRouter(prefix="/api/hexstrike", tags=["hexstrike"])


class HexStrikeConfigIn(BaseModel):
    install_path: str | None = None
    python_executable: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)


class HexStrikeInstallIn(BaseModel):
    install_path: str | None = None


class HexStrikeScopeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=1000)
    label: str = Field(default="", max_length=120)
    attested_owned: bool = False


class HexStrikeActionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cve: str | None = Field(default=None, pattern=r"^CVE-[0-9]{4}-[0-9]{4,}$")


class HexStrikeActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=80)
    scope_id: str = Field(min_length=1, max_length=80)
    options: HexStrikeActionOptions = Field(default_factory=HexStrikeActionOptions)


class HexStrikeOperateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str = Field(min_length=1, max_length=160)
    arguments: dict[str, Any] = Field(default_factory=dict)


def _permission_ids_to_check(permission_id: str) -> list[str]:
    return list(dict.fromkeys((permission_id, "cyber.hexstrike")))


def _require_permissions_grant(
    permission_ids: list[str],
    *,
    action_kind: str,
    context: dict[str, Any],
) -> None:
    from ..policy.approval_pending import park_action
    from ..policy.computer_permissions import evaluate_permission

    ordered = list(dict.fromkeys(permission_ids))
    asking: list[str] = []
    for required in ordered:
        decision = evaluate_permission(required)
        if decision.status == "deny":
            audit_hexstrike("permission_denied", permission=required, reason=decision.reason)
            raise HTTPException(status_code=403, detail=decision.reason)
        if decision.status == "ask":
            asking.append(required)
    if not asking:
        return
    payload = context.copy()
    payload["_permission_ids"] = asking
    parked = park_action(action_kind=action_kind, permission_ids=asking, context=payload)
    audit_hexstrike("permission_pending", action_kind=action_kind, permissions=asking)
    raise HTTPException(status_code=428, detail=parked)


def _require_operator_grant(
    permission_id: str,
    *,
    action_kind: str,
    context: dict[str, Any],
) -> None:
    _require_permissions_grant(
        _permission_ids_to_check(permission_id),
        action_kind=action_kind,
        context=context,
    )


async def _status_payload() -> dict[str, Any]:
    snapshot = await HEXSTRIKE.status()
    operator_surface: dict[str, Any] = {}
    if snapshot.running:
        operator_surface = await sync_operator_surface(register_mcp=False)
    payload = snapshot.as_dict()
    payload["install"] = HEXSTRIKE_INSTALLER.status().as_dict()
    payload["capabilities"] = capability_snapshot()
    payload.update(operator_status_extras())
    payload["operator"] = operator_surface
    payload["dependencies"] = dependency_catalog_rows(payload.get("install_path") or "")
    payload["missing_dependencies"] = missing_host_tools()
    payload["dependency_install_jobs"] = install_job_overlay()
    payload["managed_jobs"] = list_defensive_jobs()
    payload["operator_jobs"] = list_operator_jobs()
    return payload


@router.get("")
async def hexstrike_status():
    return await _status_payload()


@router.post("/start")
async def hexstrike_start():
    _require_operator_grant("cyber.hexstrike", action_kind="hexstrike.start", context={})
    return (await HEXSTRIKE.ensure_started()).as_dict()


@router.post("/stop")
async def hexstrike_stop():
    return (await HEXSTRIKE.stop()).as_dict()


@router.get("/install")
async def hexstrike_install_status():
    return HEXSTRIKE_INSTALLER.status().as_dict()


@router.post("/install")
async def hexstrike_install(body: HexStrikeInstallIn | None = None):
    install_path = body.install_path if body else None
    _require_operator_grant(
        "blue.static_rules",
        action_kind="hexstrike.install",
        context={"install_path": install_path},
    )
    return HEXSTRIKE_INSTALLER.start(install_path).as_dict()


@router.post("/dependencies/install")
async def hexstrike_install_dependencies(body: dict[str, Any] | None = None):
    tool = (body or {}).get("tool")
    _require_operator_grant(
        "blue.static_rules",
        action_kind="hexstrike.dependencies.install",
        context={"tool": tool},
    )
    if tool:
        return (await install_host_tool(str(tool))).as_dict()
    results = await install_all_missing()
    return {
        "missing_before": missing_host_tools(),
        "results": [item.as_dict() for item in results],
    }


@router.post("/install/cancel")
async def hexstrike_install_cancel():
    _require_operator_grant("cyber.hexstrike", action_kind="hexstrike.stop_install", context={})
    return (await HEXSTRIKE_INSTALLER.cancel()).as_dict()


@router.put("/config")
async def hexstrike_config(body: HexStrikeConfigIn):
    status = await HEXSTRIKE.configure(
        install_path=body.install_path,
        python_executable=body.python_executable,
        port=body.port,
    )
    return status.as_dict()


@router.get("/capabilities")
async def hexstrike_capabilities():
    return {"capabilities": capability_snapshot(), **catalog_snapshot()}


@router.get("/tools")
async def hexstrike_tools_catalog():
    return catalog_snapshot()


@router.post("/tools/refresh")
async def hexstrike_tools_refresh():
    _require_operator_grant("cyber.hexstrike", action_kind="hexstrike.tools.refresh", context={})
    surface = await sync_operator_surface(register_mcp=True)
    if not surface.get("operator_ready"):
        raise HTTPException(
            status_code=503,
            detail=surface.get("mcp", {}).get("error") or "HexStrike operator surface is not ready",
        )
    return {"catalog": discovered_catalog_safe(), "count": surface.get("catalog_count"), "operator": surface}


@router.post("/tools/{tool_id}/install")
async def hexstrike_tool_install(tool_id: str):
    status = await HEXSTRIKE.status(enrich=False)
    _require_operator_grant(
        "blue.static_rules",
        action_kind="hexstrike.tool.install",
        context={"tool_id": tool_id, "install_path": status.install_path},
    )
    try:
        job = start_dependency_install(tool_id, install_path=status.install_path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return job


@router.get("/tools/install-jobs/{job_id}")
async def hexstrike_tool_install_job(job_id: str):
    try:
        return get_dependency_install_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown dependency install job") from exc


@router.post("/operate")
async def hexstrike_operate(body: HexStrikeOperateIn):
    _require_operator_grant(
        "cyber.hexstrike",
        action_kind="hexstrike.operate",
        context={"capability_id": body.capability_id, "arguments": body.arguments},
    )
    snapshot = await HEXSTRIKE.status(enrich=False)
    if snapshot.running:
        surface = await sync_operator_surface(register_mcp=False)
        if not surface.get("operator_ready") and not str(body.capability_id).startswith("defensive:"):
            raise HTTPException(
                status_code=503,
                detail="Refresh operator catalog before invoking discovered capabilities",
            )
    try:
        return await operate(body.capability_id, body.arguments)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/jobs")
async def hexstrike_jobs():
    return {"jobs": list_operator_jobs(), "legacy_jobs": list_defensive_jobs()}


@router.get("/jobs/{job_id}")
async def hexstrike_job_detail(job_id: str):
    try:
        job = get_operator_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown HexStrike job") from exc
    job = dict(job)
    job["artifacts"] = list_job_artifacts(job_id)
    return job


@router.get("/jobs/{job_id}/artifacts")
async def hexstrike_job_artifacts(job_id: str):
    try:
        get_operator_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown HexStrike job") from exc
    return {"artifacts": list_job_artifacts(job_id)}


@router.post("/jobs/{job_id}/stop")
async def hexstrike_job_stop(job_id: str):
    _require_operator_grant(
        "blue.active_response",
        action_kind="hexstrike.job.stop",
        context={"job_id": job_id},
    )
    try:
        return await stop_operator_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown HexStrike job") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/scopes")
async def hexstrike_scopes():
    return {"scopes": list_scopes()}


@router.put("/scopes/{scope_id}")
async def hexstrike_scope_put(scope_id: str, body: HexStrikeScopeIn):
    _require_operator_grant(
        "blue.static_rules",
        action_kind="hexstrike.scope.put",
        context={
            "scope_id": scope_id,
            "kind": body.kind,
            "value": body.value,
            "label": body.label,
            "attested_owned": body.attested_owned,
        },
    )
    try:
        return upsert_scope(
            scope_id,
            kind=body.kind,
            value=body.value,
            label=body.label,
            attested_owned=body.attested_owned,
        )
    except PermissionError as exc:
        audit_hexstrike("scope_denied", scope_id=scope_id, kind=body.kind, reason=str(exc))
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        audit_hexstrike("scope_denied", scope_id=scope_id, kind=body.kind, reason=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/actions")
async def hexstrike_actions():
    return {"jobs": list_defensive_jobs(), "capabilities": capability_snapshot(), "catalog": discovered_catalog_safe()}


@router.post("/actions")
async def hexstrike_action(body: HexStrikeActionIn):
    capability = CAPABILITY_BY_ID.get(body.action)
    if capability is None:
        raise HTTPException(status_code=422, detail="Unknown defensive action")
    permission_ids = [capability.permission]
    if body.action == "threat_intel_lookup":
        permission_ids.append("network.internet")
    _require_permissions_grant(
        permission_ids,
        action_kind="hexstrike.defensive.action",
        context={
            "action": body.action,
            "scope_id": body.scope_id,
            "options": body.options.model_dump(exclude_none=True),
        },
    )
    try:
        return await execute_defensive(body.action, body.scope_id, body.options.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown or disabled HexStrike scope") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/actions/{job_id}/stop")
async def hexstrike_action_stop(job_id: str):
    _require_operator_grant(
        "blue.active_response",
        action_kind="hexstrike.defensive.stop",
        context={"job_id": job_id},
    )
    try:
        return await stop_managed_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown managed HexStrike job") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def discovered_catalog_safe() -> list[dict[str, Any]]:
    from ..security.hexstrike_operator import discovered_catalog

    return discovered_catalog()


@router.api_route("/upstream/{path:path}", methods=["GET", "POST"])
async def hexstrike_upstream(path: str, request: Request):
    if not gateway_allows(request.method, path):
        audit_hexstrike("proxy_denied", method=request.method, path=path)
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
