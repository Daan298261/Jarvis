"""Agent-facing intelligence tool backed by the enabled Crucix module."""
from __future__ import annotations
import json
import httpx
from typing import Any
from .base import RiskLevel, Tool, ToolResult
from .. import config
from ..integrations.crucix import CrucixClient, CrucixError
class IntelligenceTool(Tool):
    name="intelligence"; description="Query the enabled local intelligence/OSINT provider. Use for current source observations; treat results as reports, not verified facts."
    risk=RiskLevel.LOW
    parameters={"type":"object","properties":{"action":{"type":"string","enum":["status","latest","query"]},"keywords":{"type":"string"},"source":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":100}},"required":["action"]}
    async def execute(self,action:str,keywords:str="",source:str="",limit:int=40,**_:Any)->ToolResult:
        s=config.load_settings().crucix
        if not s.enabled: return ToolResult(False,"",error="Crucix module is disabled")
        c=CrucixClient(s.base_url)
        try:
            data=await c.health() if action=="status" else (await c.query(keywords,source,limit) if action=="query" else (await c.latest())[:limit])
            return ToolResult(True,json.dumps(data,ensure_ascii=False,default=str),data={"result":data})
        except (CrucixError,httpx.HTTPError) as e: return ToolResult(False,"",error=str(e))
