"""Capability Lab API (RFC-0137)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..capabilities.registry import capability_summary, get_capability, list_capabilities, load_registry
from ..evals.runner import run_capability_tests

router = APIRouter(prefix="/api/capability-lab", tags=["capability-lab"])


class BenchmarkBody(BaseModel):
    capability_ids: list[str] = Field(default_factory=list)
    live: bool = False


@router.get("/registry")
async def registry() -> dict[str, Any]:
    reg = load_registry()
    return {
        "version": reg.version,
        "updated_at": reg.updated_at,
        "capabilities": [row.model_dump() for row in reg.capabilities],
        "summary": capability_summary(),
    }


@router.get("/registry/{capability_id}")
async def registry_entry(capability_id: str) -> dict[str, Any]:
    row = get_capability(capability_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown capability id")
    return {"capability": row.model_dump()}


@router.get("/summary")
async def summary() -> dict[str, Any]:
    return capability_summary()


_BENCHMARK_LOCK = asyncio.Lock()


@router.post("/benchmark")
async def benchmark(body: BenchmarkBody) -> dict[str, Any]:
    if _BENCHMARK_LOCK.locked():
        raise HTTPException(status_code=409, detail="A capability benchmark is already running")
    async with _BENCHMARK_LOCK:
        # pytest runs in a subprocess for minutes; never on the event loop.
        return await asyncio.to_thread(run_capability_tests, body.capability_ids or None, live=body.live)
