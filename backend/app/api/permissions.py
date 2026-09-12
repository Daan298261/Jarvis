"""Owner permission catalog API (RFC-0079)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..policy.computer_permissions import (
    CATALOG_BY_ID,
    apply_grant,
    catalog_snapshot,
    describe_permission,
)

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


class GrantBody(BaseModel):
    mode: str = Field(..., min_length=3, max_length=32)


@router.get("")
async def list_permissions():
    return catalog_snapshot()


@router.get("/{permission_id}")
async def get_permission(permission_id: str):
    if permission_id not in CATALOG_BY_ID:
        raise HTTPException(404, "Unknown permission")
    return describe_permission(permission_id)


@router.put("/{permission_id}")
async def set_permission(permission_id: str, body: GrantBody):
    if permission_id not in CATALOG_BY_ID:
        raise HTTPException(404, "Unknown permission")
    try:
        persist = body.mode in {"always", "deny", "ask"}
        return apply_grant(permission_id, body.mode, persist=persist)
    except KeyError:
        raise HTTPException(404, "Unknown permission") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
