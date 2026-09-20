"""Module catalog API (RFC-0095 + RFC-0105 cybersecurity grouping)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..modules import catalog_download, cybersecurity, supermemory_runtime
from ..swarm.capabilities import register_localhost_capabilities
from ..swarm.nodes import register_localhost_node
from ..swarm.workers import bind_workers_to_node

router = APIRouter(prefix="/api/modules", tags=["modules"])


async def _refresh_local_supermemory_registration() -> None:
    """Keep node inventory accurate after a local module lifecycle change."""
    node = await register_localhost_node()
    await bind_workers_to_node(node.id)
    await register_localhost_capabilities(node.id)


async def _refresh_after_supermemory_install() -> None:
    try:
        await supermemory_runtime.wait_for_install()
        await _refresh_local_supermemory_registration()
    except Exception:
        # The install result is retained in module status; an inventory refresh
        # must never turn a successful local install into an API failure.
        pass


class EnableBody(BaseModel):
    enabled: bool


class DownloadBody(BaseModel):
    mode: Literal["clone", "zip"] = "clone"
    dest: Literal["desktop_projects", "library"] = "library"


@router.get("/catalog")
async def list_catalog() -> dict[str, Any]:
    return {"entries": [cybersecurity.catalog_list_row(), supermemory_runtime.catalog_list_row()]}


@router.get("/catalog/{entry_id}")
async def get_catalog_entry(entry_id: str) -> dict[str, Any]:
    if entry_id == cybersecurity.MODULE_ID:
        module = cybersecurity.build_module_payload()
        return {"module": module, **module}
    if entry_id == supermemory_runtime.MODULE_ID:
        module = await supermemory_runtime.module_status()
        return {"module": module, **module}
    source = catalog_download.allowlisted_source(entry_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Unknown catalog entry")
    local = cybersecurity.discover_local_path(entry_id)
    return {
        "id": source.entry_id,
        "source_url": source.source_url,
        "local_path": str(local) if local else None,
        "downloadable": True,
    }


@router.post("/catalog/cybersecurity/enable")
async def enable_cybersecurity_module(body: EnableBody) -> dict[str, Any]:
    module = cybersecurity.set_module_enabled(body.enabled)
    return {"enabled": module["enabled"], "module": module, "detail": "Cybersecurity module updated."}


@router.post("/catalog/cybersecurity/tools/{tool_id}/enable")
async def enable_cybersecurity_tool(tool_id: str, body: EnableBody) -> dict[str, Any]:
    try:
        module = cybersecurity.set_member_enabled(tool_id, body.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown cybersecurity tool") from None
    return {"enabled": body.enabled, "module": module, "detail": "Tool enablement updated."}


@router.post("/catalog/supermemory/enable")
async def enable_supermemory_module(body: EnableBody) -> dict[str, Any]:
    module = await supermemory_runtime.set_enabled(body.enabled)
    await _refresh_local_supermemory_registration()
    return {"enabled": module["enabled"], "module": module, "detail": "Supermemory module updated."}


@router.post("/catalog/supermemory/install")
async def install_supermemory_module() -> dict[str, Any]:
    module = await supermemory_runtime.install_and_start()
    asyncio.create_task(_refresh_after_supermemory_install())
    return {"module": module, **module, "detail": "Supermemory installation started."}


@router.post("/catalog/supermemory/start")
async def start_supermemory_module() -> dict[str, Any]:
    result = await supermemory_runtime.start()
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "Start failed")
    await _refresh_local_supermemory_registration()
    return {"module": result, **result}


@router.post("/catalog/supermemory/stop")
async def stop_supermemory_module() -> dict[str, Any]:
    result = await supermemory_runtime.stop()
    await _refresh_local_supermemory_registration()
    return {"module": result, **result}


@router.post("/catalog/{entry_id}/download")
async def download_catalog_entry(entry_id: str, body: DownloadBody) -> dict[str, Any]:
    try:
        job = await catalog_download.start_download(
            entry_id,
            mode=body.mode,
            dest=body.dest,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if job.local_path:
        cybersecurity.record_member_path(entry_id, Path(job.local_path))
    return {"job_id": job.job_id, "detail": "Download started.", "status": job.status}


@router.get("/jobs/{job_id}")
async def get_download_job(job_id: str) -> dict[str, Any]:
    snapshot = catalog_download.job_snapshot(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    entry_id = str(snapshot.get("entry_id") or "")
    if snapshot.get("status") == "ready" and snapshot.get("local_path") and entry_id in cybersecurity.MEMBERS:
        cybersecurity.record_member_path(entry_id, Path(str(snapshot["local_path"])))
    return snapshot


@router.post("/catalog/cybersecurity/tools/{tool_id}/start")
async def start_cybersecurity_tool(tool_id: str) -> dict[str, Any]:
    try:
        result = await cybersecurity.start_member(tool_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown cybersecurity tool") from None
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "Start failed")
    return result


@router.post("/catalog/cybersecurity/tools/{tool_id}/stop")
async def stop_cybersecurity_tool(tool_id: str) -> dict[str, Any]:
    try:
        result = await cybersecurity.stop_member(tool_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown cybersecurity tool") from None
    return result


@router.post("/catalog/cybersecurity/tools/{tool_id}/open-folder")
async def open_cybersecurity_folder(tool_id: str) -> dict[str, Any]:
    try:
        result = cybersecurity.open_member_folder(tool_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown cybersecurity tool") from None
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "Open folder failed")
    return result
