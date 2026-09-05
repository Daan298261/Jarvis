from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..ingest.orchestrator import IngestError, ingest_url
from ..tools.browser import BrowserTool
from ..tools.browser_use import BrowserUseTool
from ..tools.registry import REGISTRY

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class IngestRequest(BaseModel):
    url: str = Field(..., min_length=1)
    headless: bool = True


@router.post("/url")
async def ingest_external_url(body: IngestRequest):
    ctx = REGISTRY._context
    browser = BrowserTool(lambda: ctx)
    browser_use = BrowserUseTool()
    try:
        return await ingest_url(
            body.url,
            browser_tool=browser,
            browser_use_tool=browser_use,
            headless=body.headless,
        )
    except IngestError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "tiers_attempted": exc.tiers_attempted},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
