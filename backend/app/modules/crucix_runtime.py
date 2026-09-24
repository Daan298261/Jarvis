"""Managed Crucix module lifecycle: install on enable, configure, start, stop."""
from __future__ import annotations
import asyncio, json, os, shutil, subprocess
from pathlib import Path
from typing import Any
import httpx
from .. import config as app_config
from .supervisor import StartSpec, get_supervisor

MODULE_ID="crucix"; MODULE_NAME="Crucix"; UPSTREAM="https://github.com/calesthio/Crucix.git"; PORT=3117
_LOCK=asyncio.Lock(); _TASK=None; _STATUS="idle"; _ERROR=""
def install_dir(): return app_config.repo_root()/"runtime"/"crucix"
def _settings(): return app_config.load_settings().crucix
async def healthy():
    try:
        async with httpx.AsyncClient(timeout=2,trust_env=False,follow_redirects=False) as c: r=await c.get(_settings().base_url+"/api/health")
        return r.status_code==200
    except Exception: return False
async def status()->dict[str,Any]:
    s=_settings(); snap=get_supervisor(MODULE_ID).snapshot().as_dict()
    return {"id":MODULE_ID,"name":MODULE_NAME,"description":"Local multi-source OSINT intelligence provider.","kind":"local_sidecar","enabled":s.enabled,"auto_start":s.auto_start,"installed":(install_dir()/"package.json").is_file(),"install_status":_STATUS,"install_error":_ERROR,"running":snap["running"] or await healthy(),"managed":snap["running"],"healthy":await healthy(),"base_url":s.base_url,"upstream_repository":UPSTREAM,"license":"AGPL-3.0-only","computer_use_ready":True}
def catalog_list_row():
    s=_settings(); return {"id":MODULE_ID,"name":MODULE_NAME,"description":"Local OSINT intelligence engine; installed automatically when enabled.","kind":"local_sidecar","enabled":s.enabled,"installed":(install_dir()/"package.json").is_file(),"downloadable":True}
def _install_sync():
    root=install_dir(); git=shutil.which("git"); npm=shutil.which("npm") or shutil.which("npm.cmd")
    if not git or not npm: raise RuntimeError("Crucix requires Git and Node.js/npm 22+")
    if root.exists(): shutil.rmtree(root)
    root.parent.mkdir(parents=True,exist_ok=True)
    p=subprocess.run([git,"clone","--depth","1",UPSTREAM,str(root)],capture_output=True,text=True,timeout=900)
    if p.returncode: raise RuntimeError((p.stderr or "git clone failed")[-800:])
    pkg=json.loads((root/"package.json").read_text(encoding="utf-8"))
    if str(pkg.get("license"))!="AGPL-3.0-only": raise RuntimeError("Unexpected Crucix license metadata")
    p=subprocess.run([npm,"install","--omit=optional"],cwd=root,capture_output=True,text=True,timeout=900)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout or "npm install failed")[-800:])
    env=root/".env"; env.write_text(f"PORT={PORT}\nREFRESH_INTERVAL_MINUTES=15\nLLM_PROVIDER=\nTELEGRAM_BOT_TOKEN=\nDISCORD_BOT_TOKEN=\n",encoding="utf-8")
async def install_and_start():
    global _STATUS,_ERROR
    async with _LOCK:
        try:
            _STATUS="installing"; _ERROR=""; await asyncio.to_thread(_install_sync); _STATUS="ready"
            s=app_config.load_settings(); s.crucix.enabled=True; s.crucix.auto_start=True; app_config.save_settings(s); return await start()
        except Exception as e: _STATUS="error"; _ERROR=str(e)[:800]; return {**await status(),"ok":False,"detail":_ERROR}
async def set_enabled(enabled: bool):
    s=app_config.load_settings(); s.crucix.enabled=enabled; app_config.save_settings(s)
    if not enabled: return await stop()
    if not (install_dir()/"package.json").is_file(): return await install_and_start()
    return await start()
async def start():
    if not (install_dir()/"server.mjs").is_file(): return {**await status(),"ok":False,"detail":"Crucix is not installed"}
    if await healthy(): return {**await status(),"ok":True,"detail":"Crucix already running"}
    node=shutil.which("node");
    if not node: return {**await status(),"ok":False,"detail":"Node.js 22+ is required"}
    snap=await get_supervisor(MODULE_ID).start(StartSpec(argv=(node,"server.mjs"),cwd=install_dir(),health_url=_settings().base_url,env={"PORT":str(PORT),"BROWSER":"none","NO_OPEN":"1"}))
    return {**await status(),"ok":snap.running,"detail":"Crucix started" if snap.running else snap.last_error}
async def stop(): await get_supervisor(MODULE_ID).stop(); return {**await status(),"ok":True,"detail":"Crucix stopped"}
async def auto_start():
    s=_settings()
    if s.enabled and s.auto_start:
        if not (install_dir()/"package.json").is_file(): await install_and_start()
        else: await start()
async def shutdown(): await get_supervisor(MODULE_ID).stop()
