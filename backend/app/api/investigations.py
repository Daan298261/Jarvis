"""Owner-authenticated investigation setup, lifecycle and evidence downloads."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import load_settings
from ..reverse_engineering import apk_sidecar, provision, store
from ..reverse_engineering.runtime import SERVICE

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/investigations", tags=["investigations"])
_setup_task: asyncio.Task | None = None
_apk_tasks: set[asyncio.Task] = set()


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


class ApkPrepareBody(BaseModel):
    source_type: Literal["file", "device", "ffs"] = "file"
    target: str = Field(default="", max_length=4096)
    device_serial: str | None = Field(default=None, max_length=256)
    package_name: str | None = Field(default=None, max_length=256)
    ffs_investigation_id: str | None = Field(default=None, max_length=64)
    question: str = Field(default="Static APK analysis: manifest, permissions and exported components",
                          min_length=1, max_length=10000)
    task_id: str | None = None


class ApkDecompileBody(BaseModel):
    skip_jadx: bool = False
    decompile_smali_fallback: bool = True
    background: bool = False


def public_row(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in {"manifest", "snapshot", "_claim_token"}}


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
async def readiness(live: bool = False):
    from ..reverse_engineering.android import readiness_dynamic, readiness_static
    out = {"engine": await asyncio.to_thread(provision.readiness),
           "android": readiness_dynamic(),
           "apk_static": await asyncio.to_thread(readiness_static)}
    if live:
        out["apk_live"] = await asyncio.to_thread(apk_sidecar.readiness_live)
    return out


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


@router.post("/apk/prepare")
async def apk_prepare(body: ApkPrepareBody):
    try:
        row = await asyncio.to_thread(
            apk_sidecar.prepare_apk,
            body.target or None,
            body.question,
            load_settings().allowed_directories,
            body.task_id,
            source_type=body.source_type,
            device_serial=body.device_serial,
            package_name=body.package_name,
            ffs_investigation_id=body.ffs_investigation_id,
        )
        return public_row(row)
    except (ValueError, OSError, PermissionError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _apk_decompile_background(ident: str, skip_jadx: bool, decompile_smali_fallback: bool, claimed: dict):
    try:
        await SERVICE.run_apk(ident, "apk_decompile", {
            "skip_jadx": skip_jadx, "decompile_smali_fallback": decompile_smali_fallback}, claimed)
    except asyncio.CancelledError:
        logger.info("APK decompile for investigation %s was cancelled", ident)
        raise
    except Exception:
        # Status and last_error are on the row (decompile or release persisted them); keep the traceback here.
        logger.exception("Background APK decompile failed for investigation %s", ident)
    finally:
        # Covers a task cancelled before run_apk started; a no-op once decompile owns or finished the claim.
        await asyncio.to_thread(apk_sidecar.release, ident, claimed.get("_claim_token"))


@router.post("/{ident}/apk/decompile")
async def apk_decompile(ident: str, body: ApkDecompileBody):
    try:
        row = await asyncio.to_thread(apk_sidecar.preflight, ident)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Unknown investigation") from exc
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.background:
        try:
            task = asyncio.create_task(_apk_decompile_background(ident, body.skip_jadx, body.decompile_smali_fallback, row))
        except BaseException:
            await asyncio.to_thread(apk_sidecar.release, ident, row.get("_claim_token"))
            raise
        _apk_tasks.add(task)
        task.add_done_callback(_apk_tasks.discard)
        return public_row(row)
    try:
        await SERVICE.run_apk(ident, "apk_decompile", {"skip_jadx": body.skip_jadx, "decompile_smali_fallback": body.decompile_smali_fallback}, row)
        return public_row(store.load(ident))
    except (ValueError, OSError, RuntimeError) as exc:
        # run_apk already released any claim decompile() never took over.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{ident}/apk/summary")
async def apk_summary(ident: str):
    try:
        return await asyncio.to_thread(apk_sidecar.summary, ident)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Unknown APK investigation") from exc


@router.post("/{ident}/apk/report")
async def apk_report(ident: str):
    """Synthesize an APK investigation report from recorded evidence (RFC-0207 §9.4)."""
    try:
        row = await asyncio.to_thread(apk_sidecar.apk_synthesize_report, ident)
        return public_row(row)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Unknown investigation") from exc
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{ident}/apk/{document}")
async def apk_metadata(ident: str, document: Literal["manifest", "components", "native", "endpoints", "crypto"]):
    try:
        return await asyncio.to_thread(apk_sidecar.metadata, ident, document)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="APK metadata has not been produced") from exc


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
