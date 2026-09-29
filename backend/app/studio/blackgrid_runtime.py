"""BlackGrid Multimedia Studio — ComfyUI + HR Endless Sampler managed sidecar."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import config as app_config
from ..modules.catalog_download import register_allowlisted_source
from .comfy_client import ComfyClient
from .workflow import build_hr_endless_api_prompt, template_path

logger = logging.getLogger(__name__)

MODULE_ID = "blackgrid-studio"
MODULE_NAME = "BlackGrid Multimedia Studio"
COMFYUI_GIT = "https://github.com/comfyanonymous/ComfyUI.git"
HR_ENDLESS_GIT = "https://github.com/hradec/comfyui-hr-endless-sampler.git"
DEFAULT_PORT = 8188

_LOCK = asyncio.Lock()
_INSTALL_STATUS = "idle"
_INSTALL_ERROR = ""
_JOBS_PATH = lambda: app_config.data_dir() / "blackgrid-jobs.json"


def install_root() -> Path:
    return app_config.repo_root() / "runtime" / "blackgrid"


def comfy_root() -> Path:
    return install_root() / "ComfyUI"


def hr_endless_node_dir() -> Path:
    return comfy_root() / "custom_nodes" / "comfyui-hr-endless-sampler"


def output_dir() -> Path:
    return comfy_root() / "output"


def _settings():
    return app_config.load_settings().blackgrid


def _base_url() -> str:
    s = _settings()
    port = int(s.port or DEFAULT_PORT)
    host = (s.host or "127.0.0.1").strip()
    return f"http://{host}:{port}"


def _client() -> ComfyClient:
    return ComfyClient(_base_url(), timeout=float(_settings().request_timeout_s))


def register_catalog_sources() -> None:
    register_allowlisted_source("comfyui", COMFYUI_GIT, slug="ComfyUI")
    register_allowlisted_source("hr-endless-sampler", HR_ENDLESS_GIT, slug="comfyui-hr-endless-sampler")


register_catalog_sources()


def _read_jobs() -> dict[str, Any]:
    path = _JOBS_PATH()
    if not path.is_file():
        return {"jobs": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"jobs": []}


def _write_jobs(payload: dict[str, Any]) -> None:
    path = _JOBS_PATH()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _append_job(record: dict[str, Any]) -> dict[str, Any]:
    data = _read_jobs()
    jobs = list(data.get("jobs") or [])
    jobs.insert(0, record)
    data["jobs"] = jobs[:50]
    _write_jobs(data)
    return record


def catalog_list_row() -> dict[str, Any]:
    s = _settings()
    installed = (comfy_root() / "main.py").is_file() and hr_endless_node_dir().is_dir()
    return {
        "id": MODULE_ID,
        "name": MODULE_NAME,
        "description": "Local ComfyUI sidecar with HR Endless Sampler (MiniMax H3 long-form video).",
        "kind": "black_grid_media",
        "enabled": s.enabled,
        "installed": installed,
        "downloadable": True,
        "primary_engine": "hr-endless-sampler",
    }


async def status() -> dict[str, Any]:
    s = _settings()
    installed = (comfy_root() / "main.py").is_file()
    hr = hr_endless_node_dir().is_dir()
    healthy = await _client().healthy() if installed else False
    return {
        "id": MODULE_ID,
        "name": MODULE_NAME,
        "provider": "blackgrid",
        "enabled": s.enabled,
        "auto_start": s.auto_start,
        "installed": installed,
        "hr_endless_installed": hr,
        "install_status": _INSTALL_STATUS,
        "install_error": _INSTALL_ERROR,
        "running": healthy,
        "healthy": healthy,
        "base_url": _base_url(),
        "comfy_ui_url": _base_url(),
        "portal_workbench_url": "/studio/blackgrid",
        "primary_tool": "blackgrid_studio",
        "template_workflow": str(template_path().name),
        "upstream": {"comfyui": COMFYUI_GIT, "hr_endless_sampler": HR_ENDLESS_GIT},
    }


def _sync_comfy_healthy() -> bool:
    try:
        import httpx

        r = httpx.get(f"{_base_url()}/system_stats", timeout=1.5, trust_env=False)
        return r.status_code == 200
    except Exception:
        return False


def studio_capabilities() -> dict[str, Any]:
    """Truthful BlackGrid capability contract (RFC-0059), sync-safe."""
    installed = (comfy_root() / "main.py").is_file()
    running = _sync_comfy_healthy() if installed else False
    return _capabilities_payload(installed=installed, running=running, detail=_INSTALL_ERROR)


async def studio_capabilities_async() -> dict[str, Any]:
    snap = await status()
    return _capabilities_payload(
        installed=bool(snap.get("installed")),
        running=bool(snap.get("running")),
        detail=str(snap.get("install_error") or ""),
    )


def _capabilities_payload(*, installed: bool, running: bool, detail: str) -> dict[str, Any]:
    available = installed and running
    operations = {
        "image": available,
        "video": available,
        "audio": False,
        "takes": available,
        "timeline": available,
        "stitch": False,
        "artifacts": available,
        "hr_endless_sampler": available,
    }
    msg = "BlackGrid Multimedia Studio is ready (ComfyUI + HR Endless Sampler)."
    if not installed:
        msg = "Install BlackGrid from the Studio workbench or Setup to enable local video generation."
    elif not running:
        msg = "ComfyUI is installed but not running. Start the studio from the workbench."
    elif detail:
        msg = detail
    return {
        "provider": "blackgrid",
        "available": available,
        "detail": msg,
        "operations": operations,
        "primary_engine": "hr-endless-sampler",
        "workbench_path": "/studio/blackgrid",
        "comfy_ui_url": _base_url(),
        "creative_tools": [
            {
                "id": "hr-endless-sampler",
                "label": "HR Endless Sampler",
                "description": "Chunked MiniMax H3 long video with Gemma4 chunk prompts and live preview.",
                "open_url": _base_url(),
                "workbench_path": "/studio/blackgrid",
            }
        ],
    }


def _install_sync() -> None:
    global _INSTALL_STATUS, _INSTALL_ERROR
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is required to install BlackGrid Multimedia Studio.")
    root = install_root()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [git, "clone", "--depth", "1", COMFYUI_GIT, str(comfy_root())],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout or "ComfyUI clone failed")[-800:])
    custom = comfy_root() / "custom_nodes"
    custom.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [git, "clone", "--depth", "1", HR_ENDLESS_GIT, str(hr_endless_node_dir())],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout or "HR Endless Sampler clone failed")[-800:])
    req_comfy = comfy_root() / "requirements.txt"
    if req_comfy.is_file():
        pip = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req_comfy)]
        proc = subprocess.run(pip, capture_output=True, text=True, timeout=1800)
        if proc.returncode:
            raise RuntimeError((proc.stderr or proc.stdout or "ComfyUI requirements failed")[-800:])
    req_hr = hr_endless_node_dir() / "requirements.txt"
    if req_hr.is_file():
        pip = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req_hr)]
        proc = subprocess.run(pip, capture_output=True, text=True, timeout=1800)
        if proc.returncode:
            raise RuntimeError((proc.stderr or proc.stdout or "HR Endless requirements failed")[-800:])
    wf_dest = comfy_root() / "user" / "default" / "workflows"
    wf_dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_path(), wf_dest / "Jarvis-HR-Endless-Sampler.json")


async def install_and_enable() -> dict[str, Any]:
    global _INSTALL_STATUS, _INSTALL_ERROR
    async with _LOCK:
        try:
            _INSTALL_STATUS = "installing"
            _INSTALL_ERROR = ""
            await asyncio.to_thread(_install_sync)
            _INSTALL_STATUS = "ready"
            s = app_config.load_settings()
            s.blackgrid.enabled = True
            s.blackgrid.auto_start = True
            app_config.save_settings(s)
            return {**(await start()), "install_status": _INSTALL_STATUS}
        except Exception as exc:
            _INSTALL_STATUS = "error"
            _INSTALL_ERROR = str(exc)[:800]
            logger.exception("BlackGrid install failed")
            return {**(await status()), "ok": False, "detail": _INSTALL_ERROR}


async def start() -> dict[str, Any]:
    if not (comfy_root() / "main.py").is_file():
        return {**(await status()), "ok": False, "detail": "BlackGrid is not installed."}
    if await _client().healthy():
        return {**(await status()), "ok": True, "detail": "ComfyUI already running."}
    port = int(_settings().port or DEFAULT_PORT)
    host = (_settings().host or "127.0.0.1").strip()
    from ..modules.supervisor import StartSpec, get_supervisor

    snap = await get_supervisor(MODULE_ID).start(
        StartSpec(
            argv=(sys.executable, "main.py", "--listen", host, "--port", str(port)),
            cwd=comfy_root(),
            health_url=_base_url() + "/system_stats",
            env={"COMFYUI_DISABLE_AUTO_LAUNCH": "1"},
        )
    )
    ok = snap.running or await _client().healthy()
    return {**(await status()), "ok": ok, "detail": "ComfyUI started." if ok else (snap.last_error or "Start failed")}


async def stop() -> dict[str, Any]:
    from ..modules.supervisor import get_supervisor

    await get_supervisor(MODULE_ID).stop()
    return {**(await status()), "ok": True, "detail": "ComfyUI stopped."}


async def auto_start() -> None:
    s = _settings()
    if not s.enabled or not s.auto_start:
        return
    if not (comfy_root() / "main.py").is_file():
        return
    await start()


async def submit_hr_endless_job(
    prompt: str,
    *,
    chunk_frames: int = 39,
    reference_images: list[str] | None = None,
) -> dict[str, Any]:
    snap = await status()
    if not snap.get("running"):
        started = await start()
        if not started.get("ok"):
            raise RuntimeError(started.get("detail") or "ComfyUI is not running.")
    client = _client()
    uploaded: list[str] = []
    for raw in reference_images or []:
        path = Path(raw).expanduser()
        if path.is_file():
            meta = await client.upload_image(path)
            uploaded.append(str(meta.get("name") or path.name))
    api_prompt = build_hr_endless_api_prompt(prompt.strip(), chunk_frames=chunk_frames)
    queued = await client.queue_prompt(api_prompt)
    prompt_id = str(queued.get("prompt_id") or "")
    record = {
        "id": prompt_id or queued.get("client_id"),
        "prompt_id": prompt_id,
        "status": "queued",
        "prompt_excerpt": prompt.strip()[:240],
        "chunk_frames": chunk_frames,
        "reference_images": uploaded,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "comfy_ui_url": _base_url(),
        "workbench_url": "/studio/blackgrid",
    }
    _append_job(record)
    return {"ok": True, "job": record, "queue": queued}


async def list_outputs(limit: int = 20) -> list[dict[str, Any]]:
    out = output_dir()
    if not out.is_dir():
        return []
    files = sorted(out.glob("**/*"), key=lambda p: p.stat().st_mtime, reverse=True)
    rows: list[dict[str, Any]] = []
    for path in files:
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".mp4", ".webm", ".png", ".jpg", ".jpeg", ".gif", ".wav"}:
            continue
        rows.append(
            {
                "path": str(path),
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
        if len(rows) >= limit:
            break
    return rows


async def list_jobs() -> list[dict[str, Any]]:
    return list(_read_jobs().get("jobs") or [])
