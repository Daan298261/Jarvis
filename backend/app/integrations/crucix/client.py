"""Bounded, loopback-only Crucix client and normalizer."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

MAX_BYTES = 5_000_000
MAX_OBSERVATIONS = 250

class CrucixError(RuntimeError): pass

def _base(url: str) -> str:
    p=urlparse((url or "").strip())
    if p.scheme!="http" or p.hostname not in {"127.0.0.1","localhost","::1"}:
        raise CrucixError("Crucix endpoint must be loopback HTTP")
    if not p.port: raise CrucixError("Crucix endpoint must include a port")
    return f"http://127.0.0.1:{p.port}"

def _stable(source: str, item: Any) -> str:
    raw=json.dumps(item,sort_keys=True,default=str,separators=(",",":"))
    return hashlib.sha256((source+"\0"+raw).encode()).hexdigest()[:24]

def normalize(payload: dict[str,Any]) -> list[dict[str,Any]]:
    out=[]; fetched=datetime.now(timezone.utc).isoformat()
    for source,value in payload.items():
        if source in {"meta","delta","ideas"}: continue
        rows=value if isinstance(value,list) else [value]
        for row in rows:
            if len(out)>=MAX_OBSERVATIONS: return out
            if not isinstance(row,(dict,str,int,float,bool)): continue
            d=row if isinstance(row,dict) else {"value":row}
            text=str(d.get("title") or d.get("text") or d.get("name") or d.get("value") or "")[:1200]
            url=str(d.get("url") or d.get("link") or "")[:2048]
            ts=d.get("timestamp") or d.get("time") or d.get("date")
            out.append({"source":source,"text":text,"url":url or None,"event_time":ts,"fetched_at":fetched,"verified":bool(url),"dedup_key":_stable(source,d),"raw":d})
    return out

class CrucixClient:
    def __init__(self,base_url: str, timeout: float=8.0): self.base_url=_base(base_url); self.timeout=timeout
    async def _get(self,path: str)->dict[str,Any]:
        async with httpx.AsyncClient(timeout=self.timeout,follow_redirects=False,trust_env=False) as c:
            r=await c.get(self.base_url+path,headers={"Accept":"application/json"})
        if r.status_code==503: raise CrucixError("Crucix is not ready; first sweep is still running")
        r.raise_for_status()
        if len(r.content)>MAX_BYTES: raise CrucixError("Crucix response exceeded size limit")
        data=r.json()
        if not isinstance(data,dict): raise CrucixError("Unexpected Crucix payload")
        return data
    async def health(self): return await self._get("/api/health")
    async def latest(self): return normalize(await self._get("/api/data"))
    async def query(self,keywords: str="",source: str="",limit: int=50):
        rows=await self.latest(); words=[x.lower() for x in keywords.split() if x][:12]; src=source.lower().strip()
        def ok(r): return (not src or src in r["source"].lower()) and (not words or all(w in (r["text"]+" "+str(r["raw"])).lower() for w in words))
        return [r for r in rows if ok(r)][:max(1,min(limit,100))]
