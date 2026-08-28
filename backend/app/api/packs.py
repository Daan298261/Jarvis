from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..packs.manager import (
    PackConflictError,
    PackError,
    export_pack,
    get_installed_pack,
    install_pack,
    list_installed_packs,
    mark_resource_user_modified,
    parse_manifest,
    preview_pack,
    rollback_pack,
    uninstall_pack,
    upgrade_pack,
)
from ..packs.schema import PackManifest
from ..packs.trust import (
    CapabilityPolicyError,
    TrustError,
    add_trusted_key,
    list_trusted_key_ids,
)
from ..packs.store import load_state

router = APIRouter(prefix="/api/packs", tags=["packs"])


class PackManifestIn(BaseModel):
    manifest: dict[str, Any]


class PackPreviewIn(BaseModel):
    manifest: dict[str, Any]
    action: Literal["install", "upgrade", "uninstall"] = "install"
    overrides: dict[str, str] = Field(default_factory=dict)
    require_signature: bool = False


class PackInstallIn(BaseModel):
    manifest: dict[str, Any]
    overrides: dict[str, str] = Field(default_factory=dict)
    require_signature: bool = False
    enforce_policies: bool = True


class PackUpgradeIn(BaseModel):
    manifest: dict[str, Any]
    overrides: dict[str, str] = Field(default_factory=dict)
    require_signature: bool = False
    enforce_policies: bool = True


class PackExportIn(BaseModel):
    pack_id: str
    include_user_modifications: bool = False
    name: str | None = None
    version: str | None = None
    description: str | None = None


class ResourceModifyIn(BaseModel):
    data: dict[str, Any] | None = None


class TrustedKeyIn(BaseModel):
    key_id: str
    secret: str


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PackConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (PackError, TrustError, CapabilityPolicyError, ValueError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def list_packs():
    return {"packs": list_installed_packs()}


@router.get("/history")
async def pack_history():
    state = load_state()
    return {"events": state.get("history") or []}


@router.get("/trust")
async def list_trust_keys():
    return {"key_ids": list_trusted_key_ids()}


@router.post("/trust")
async def create_trust_key(body: TrustedKeyIn):
    keys = add_trusted_key(body.key_id, body.secret)
    return {"key_ids": sorted(keys.keys())}


@router.post("/preview")
async def preview(body: PackPreviewIn):
    try:
        manifest = parse_manifest(body.manifest)
        preview_result = preview_pack(
            manifest,
            action=body.action,
            overrides=body.overrides,
            require_signature=body.require_signature,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return preview_result.model_dump(mode="json")


@router.post("/install")
async def install(body: PackInstallIn):
    try:
        manifest = parse_manifest(body.manifest)
        return install_pack(
            manifest,
            overrides=body.overrides,
            require_signature=body.require_signature,
            enforce_policies=body.enforce_policies,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/upgrade")
async def upgrade(body: PackUpgradeIn):
    try:
        manifest = parse_manifest(body.manifest)
        return upgrade_pack(
            manifest,
            overrides=body.overrides,
            require_signature=body.require_signature,
            enforce_policies=body.enforce_policies,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/export")
async def export(body: PackExportIn):
    try:
        return export_pack(
            body.pack_id,
            include_user_modifications=body.include_user_modifications,
            name=body.name,
            version=body.version,
            description=body.description,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/{pack_id}")
async def get_pack(pack_id: str):
    pack = get_installed_pack(pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"Pack {pack_id!r} not found")
    return pack


@router.post("/{pack_id}/rollback")
async def rollback(pack_id: str):
    try:
        return rollback_pack(pack_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/{pack_id}")
async def uninstall(pack_id: str, keep_user_modified: bool = True):
    try:
        return uninstall_pack(pack_id, keep_user_modified=keep_user_modified)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/resources/{resource_id}/user-modified")
async def mark_user_modified(resource_id: str, body: ResourceModifyIn):
    try:
        record = mark_resource_user_modified(resource_id, body.data)
    except Exception as exc:
        raise _http_error(exc) from exc
    return record.model_dump(mode="json")
