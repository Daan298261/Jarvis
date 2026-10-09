"""Owner-authenticated investigation setup, lifecycle and evidence downloads."""
from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import load_settings
from ..reverse_engineering import provision, store
from ..reverse_engineering.runtime import SERVICE

router = APIRouter(prefix="/api/investigations", tags=["investigations"])
_setup_task: asyncio.Task | None = None


class PrepareBody(BaseModel):
    target: str = Field(min_length=1, max_length=4096)
    question: str = Field(min_length=1, max_length=10000)
    task_id: str | None = None
    origins: list[str] = Field(default_factory=list, max_length=20)


class CallBody(BaseModel):
    operation: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    grant_id: str | None = None


class ReportBody(BaseModel):
    findings: list[dict[str, Any]]
    unknowns: list[str] = Field(default_factory=list)


class IngestBody(BaseModel):
    source: str = Field(default="", max_length=4096)
    target: str = Field(default="", max_length=4096)
    investigation_id: str | None = None
    question: str = Field(default="Forensic image ingest and file index", max_length=10000)
    task_id: str | None = None
    source_type: Literal["auto", "folder", "tar", "zip", "raw"] = "auto"
    background: bool = False


def public_row(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in {"manifest", "snapshot"}}


async def _setup(android: bool):
    try:
        await asyncio.to_thread(provision.install)
        if android:
            from ..reverse_engineering.android import install
            await asyncio.to_thread(install)
    except Exception:
        # Both setup implementations persist diagnostics for the UI; task exceptions
        # must not leak into the server's unhandled-task stream.
        return


@router.get("/readiness")
async def readiness():
    from ..reverse_engineering.android import readiness as android_readiness
    return {"engine": await asyncio.to_thread(provision.readiness),
            "android": android_readiness()}


@router.post("/setup")
async def setup(android: bool = True):
    global _setup_task
    if _setup_task is not None and not _setup_task.done():
        return {"status": "installing"}
    _setup_task = asyncio.create_task(_setup(android))
    return {"status": "installing"}


@router.get("")
async def list_investigations(task_id: str | None = None):
    return {"investigations": [public_row(row) for row in store.list_rows(task_id)[:100]]}


@router.post("")
async def prepare(body: PrepareBody):
    try:
        return await SERVICE.prepare(body.target, body.question, load_settings().allowed_directories, body.task_id, body.origins)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/ingest")
async def ingest(body: IngestBody):
    source_target = body.target or body.source
    if not source_target.strip():
        raise HTTPException(status_code=422, detail="Source or target path is required")
    try:
        from ..reverse_engineering.ffs_ingest import FFSIngest
        settings = load_settings()
        ingest_svc = FFSIngest(
            source=source_target,
            investigation_id=body.investigation_id,
            task_id=body.task_id,
            question=body.question,
            source_type=body.source_type,
            allowed_directories=settings.allowed_directories,
        )
        if body.background:
            row = ingest_svc.prepare_investigation()
            asyncio.create_task(ingest_svc.run())
            return public_row(row)
        row = await ingest_svc.run()
        return public_row(row)
    except (ValueError, OSError, PermissionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{ident}")
async def detail(ident: str):
    try:
        return public_row(store.load(ident))
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Unknown investigation") from exc


@router.get("/{ident}/status")
async def investigation_status(ident: str):
    try:
        row = store.load(ident)
        return {
            "id": ident,
            "status": row.get("status"),
            "progress": row.get("progress"),
            "chain_of_custody": row.get("chain_of_custody", []),
            "evidence": row.get("evidence", []),
            "updated_at": row.get("updated_at"),
        }
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Unknown investigation") from exc


@router.post("/{ident}/ingest")
async def ingest_into_investigation(ident: str, body: IngestBody):
    try:
        existing = store.load(ident)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Unknown investigation") from exc
    source_target = body.target or body.source or existing.get("target") or ""
    if not source_target.strip():
        raise HTTPException(status_code=422, detail="Source or target path is required")
    try:
        from ..reverse_engineering.ffs_ingest import FFSIngest
        settings = load_settings()
        ingest_svc = FFSIngest(
            source=source_target,
            investigation_id=ident,
            task_id=body.task_id or existing.get("task_id"),
            question=body.question if body.question != "Forensic image ingest and file index" else existing.get("question", body.question),
            source_type=body.source_type,
            allowed_directories=settings.allowed_directories,
        )
        if body.background:
            row = ingest_svc.prepare_investigation()
            asyncio.create_task(ingest_svc.run())
            return public_row(row)
        row = await ingest_svc.run()
        return public_row(row)
    except (ValueError, OSError, PermissionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{ident}/catalog")
async def catalog(ident: str, operation: str = ""):
    try:
        return await SERVICE.catalog(ident, None, operation)
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{ident}/call")
async def call(ident: str, body: CallBody):
    try:
        row = store.load(ident)
        return await SERVICE.call(ident, body.operation, body.arguments, row.get("task_id"), body.grant_id)
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{ident}/cancel")
async def cancel(ident: str):
    try:
        return await SERVICE.close(ident, None, cancelled=True)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{ident}/report")
async def save_report(ident: str, body: ReportBody):
    try:
        return public_row(await SERVICE.report(ident, body.findings, body.unknowns, None))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{ident}/report")
async def report(ident: str, format: Literal["md", "json"] = "md"):
    try:
        p = store.directory(ident) / f"report.{format}"
        if not p.is_file():
            raise FileNotFoundError
        return FileResponse(p, filename=f"anzu-investigation-{ident}.{format}",
                            media_type="text/markdown" if format == "md" else "application/json")
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Report has not been produced") from exc


@router.get("/{ident}/evidence/{evidence_id}")
async def evidence(ident: str, evidence_id: str):
    try:
        row = store.load(ident)
        if evidence_id not in {e["id"] for e in row["evidence"]}:
            raise FileNotFoundError
        return FileResponse(store.directory(ident) / "evidence" / f"{evidence_id}.json", media_type="application/json")
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Unknown evidence") from exc
