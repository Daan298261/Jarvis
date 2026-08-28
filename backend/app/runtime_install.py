"""Runtime / model component install state for first-run setup.

Downloads are restartable. Valid existing files are not re-downloaded.
Progress is tracked in memory and mirrored into setup_state.component_status.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import tempfile
import threading
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen

from .config import models_dir, repo_root, runtime_dir
from .inference.profiles import (
    EXPERT_DIR,
    EXPERT_GGUF_REPO,
    PRIMARY_DIR,
    PRIMARY_GGUF_REPO,
    PRIMARY_MMPROJ,
    PROFILES,
    profile_gguf,
)
from .setup_state import load_setup_state, save_setup_state

logger = logging.getLogger(__name__)

LLAMA_TAG = "b10516"
LLAMA_SERVER_ZIP = f"llama-{LLAMA_TAG}-bin-win-cuda-13.3-x64.zip"
LLAMA_CUDART_ZIP = "cudart-llama-bin-win-cuda-13.3-x64.zip"
LLAMA_BASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}"

COMPONENT_IDS = (
    "llama_cpp",
    "cuda_runtime",
    "primary_model",
    "vision_projector",
    "expert_model",
    "playwright_chromium",
)


@dataclass
class ComponentState:
    id: str
    label: str
    status: str = "pending"  # pending|ready|downloading|verifying|error|skipped
    bytes_done: int = 0
    bytes_total: int = 0
    error: str = ""
    path: str = ""
    optional: bool = False
    detail: str = ""


_LOCK = threading.Lock()
_STATES: dict[str, ComponentState] = {}
_TASKS: dict[str, asyncio.Task] = {}
_PROGRESS_HOOK: Callable[[str, ComponentState], None] | None = None


def _label(component_id: str) -> str:
    return {
        "llama_cpp": "llama.cpp server",
        "cuda_runtime": "CUDA runtime files",
        "primary_model": "Primary model (9B)",
        "vision_projector": "Vision projector",
        "expert_model": "Expert model (27B, optional)",
        "playwright_chromium": "Playwright Chromium",
    }.get(component_id, component_id)


def _llama_exe() -> Path:
    return runtime_dir() / "llama-server.exe"


def _primary_profile():
    return PROFILES["balanced"]


def _expert_profile():
    return PROFILES["expert"]


def _mmproj_primary() -> Path:
    return models_dir() / PRIMARY_DIR / PRIMARY_MMPROJ


def discover_component_states(*, include_optional_expert: bool | None = None) -> dict[str, ComponentState]:
    setup = load_setup_state()
    want_expert = setup.get("install_expert_27b") if include_optional_expert is None else include_optional_expert
    want_playwright = bool(setup.get("install_playwright", True))

    states: dict[str, ComponentState] = {}
    llama = _llama_exe()
    states["llama_cpp"] = ComponentState(
        id="llama_cpp",
        label=_label("llama_cpp"),
        status="ready" if llama.exists() else "pending",
        path=str(llama),
    )
    # CUDA runtime is bundled with the same extract folder; treat ready when llama exists.
    states["cuda_runtime"] = ComponentState(
        id="cuda_runtime",
        label=_label("cuda_runtime"),
        status="ready" if llama.exists() else "pending",
        path=str(runtime_dir()),
    )
    primary = profile_gguf(_primary_profile())
    states["primary_model"] = ComponentState(
        id="primary_model",
        label=_label("primary_model"),
        status="ready" if primary.exists() else "pending",
        path=str(primary),
    )
    mmproj = _mmproj_primary()
    states["vision_projector"] = ComponentState(
        id="vision_projector",
        label=_label("vision_projector"),
        status="ready" if mmproj.exists() else "pending",
        path=str(mmproj),
        optional=True,
    )
    expert = profile_gguf(_expert_profile())
    if want_expert:
        states["expert_model"] = ComponentState(
            id="expert_model",
            label=_label("expert_model"),
            status="ready" if expert.exists() else "pending",
            path=str(expert),
            optional=True,
        )
    else:
        states["expert_model"] = ComponentState(
            id="expert_model",
            label=_label("expert_model"),
            status="skipped" if not expert.exists() else "ready",
            path=str(expert),
            optional=True,
            detail="Optional — not selected",
        )
    marker = repo_root() / ".venv" / ".playwright-chromium-ready"
    if want_playwright:
        states["playwright_chromium"] = ComponentState(
            id="playwright_chromium",
            label=_label("playwright_chromium"),
            status="ready" if marker.exists() else "pending",
            path=str(marker),
            optional=True,
        )
    else:
        states["playwright_chromium"] = ComponentState(
            id="playwright_chromium",
            label=_label("playwright_chromium"),
            status="skipped",
            optional=True,
            detail="Optional — not selected",
        )

    with _LOCK:
        for key, discovered in states.items():
            current = _STATES.get(key)
            if current and current.status in {"downloading", "verifying", "error"}:
                # Keep live progress / last error unless the file became ready.
                if discovered.status == "ready":
                    _STATES[key] = discovered
                else:
                    continue
            else:
                _STATES[key] = discovered
        return {k: _STATES[k] for k in COMPONENT_IDS if k in _STATES}


def component_status_payload() -> dict[str, Any]:
    states = discover_component_states()
    return {cid: asdict(states[cid]) for cid in states}


def _set_state(component_id: str, **kwargs: Any) -> ComponentState:
    with _LOCK:
        state = _STATES.get(component_id) or ComponentState(id=component_id, label=_label(component_id))
        for key, value in kwargs.items():
            setattr(state, key, value)
        _STATES[component_id] = state
        save_setup_state({"component_status": {component_id: asdict(state)}})
        return state


def _download_file(url: str, dest: Path, component_id: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    _set_state(component_id, status="downloading", error="", bytes_done=0, bytes_total=0)
    with urlopen(url, timeout=120) as resp:  # noqa: S310 — fixed release URLs
        total = int(resp.headers.get("Content-Length") or 0)
        _set_state(component_id, bytes_total=total)
        done = 0
        with open(tmp, "wb") as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                _set_state(component_id, bytes_done=done, bytes_total=total or done)
    tmp.replace(dest)
    _set_state(component_id, status="verifying", path=str(dest))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_zip(zip_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)


def _install_llama_and_cuda() -> None:
    llama = _llama_exe()
    if llama.exists():
        _set_state("llama_cpp", status="ready", path=str(llama), error="")
        _set_state("cuda_runtime", status="ready", path=str(runtime_dir()), error="")
        return
    runtime = runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jarvis-llama-") as tmp:
        tmp_path = Path(tmp)
        server_zip = tmp_path / LLAMA_SERVER_ZIP
        cudart_zip = tmp_path / LLAMA_CUDART_ZIP
        _download_file(f"{LLAMA_BASE}/{LLAMA_SERVER_ZIP}", server_zip, "llama_cpp")
        _extract_zip(server_zip, runtime)
        _set_state("cuda_runtime", status="downloading", error="")
        _download_file(f"{LLAMA_BASE}/{LLAMA_CUDART_ZIP}", cudart_zip, "cuda_runtime")
        _extract_zip(cudart_zip, runtime)
    if not llama.exists():
        raise FileNotFoundError("llama-server.exe missing after extract")
    _set_state("llama_cpp", status="ready", path=str(llama), error="")
    _set_state("cuda_runtime", status="ready", path=str(runtime), error="")


def _hf_download(repo_id: str, filename: str, local_dir: Path, component_id: str) -> Path:
    local_dir.mkdir(parents=True, exist_ok=True)
    target = local_dir / filename
    if target.exists() and target.stat().st_size > 0:
        _set_state(component_id, status="ready", path=str(target), error="")
        return target
    _set_state(component_id, status="downloading", error="", path=str(target))
    try:
        from huggingface_hub import hf_hub_download
    except Exception as exc:  # pragma: no cover - optional dep failure path
        raise RuntimeError(f"huggingface_hub unavailable: {exc}") from exc

    def _hook(progress: Any) -> None:
        try:
            done = int(getattr(progress, "n", 0) or 0)
            total = int(getattr(progress, "total", 0) or 0)
            _set_state(component_id, bytes_done=done, bytes_total=total or done, status="downloading")
        except Exception:
            pass

    # hf_hub_download does not always accept a progress callback the same way; update best-effort.
    path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
    )
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Download finished but {filename} missing")
    # Light verification: non-empty + sha256 computed for diagnostics (not compared to a known digest).
    _set_state(component_id, status="verifying", path=str(resolved))
    size = resolved.stat().st_size
    if size <= 0:
        raise ValueError(f"{filename} is empty after download")
    digest = _sha256(resolved)
    _set_state(
        component_id,
        status="ready",
        path=str(resolved),
        bytes_done=size,
        bytes_total=size,
        detail=f"sha256={digest[:16]}…",
        error="",
    )
    return resolved


def _install_primary() -> None:
    profile = _primary_profile()
    fast = PROFILES["fast"]
    local = models_dir() / PRIMARY_DIR
    _hf_download(PRIMARY_GGUF_REPO, profile.filename, local, "primary_model")
    # Also fetch Q6_K when missing (fast profile) — skip if already present.
    if not profile_gguf(fast).exists():
        try:
            _hf_download(PRIMARY_GGUF_REPO, fast.filename, local, "primary_model")
        except Exception as exc:
            logger.warning("Optional fast quant download skipped: %s", exc)


def _install_mmproj() -> None:
    path = _mmproj_primary()
    if path.exists():
        _set_state("vision_projector", status="ready", path=str(path), error="")
        return
    _hf_download(PRIMARY_GGUF_REPO, PRIMARY_MMPROJ, models_dir() / PRIMARY_DIR, "vision_projector")


def _install_expert() -> None:
    profile = _expert_profile()
    target = profile_gguf(profile)
    if target.exists():
        _set_state("expert_model", status="ready", path=str(target), error="")
        return
    _hf_download(EXPERT_GGUF_REPO, profile.filename, models_dir() / EXPERT_DIR, "expert_model")


def _install_playwright() -> None:
    marker = repo_root() / ".venv" / ".playwright-chromium-ready"
    if marker.exists():
        _set_state("playwright_chromium", status="ready", path=str(marker), error="")
        return
    _set_state("playwright_chromium", status="downloading", error="")
    try:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "playwright install failed")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok\n", encoding="utf-8")
        _set_state("playwright_chromium", status="ready", path=str(marker), error="")
    except Exception as exc:
        # Optional capability — do not crash Jarvis.
        _set_state(
            "playwright_chromium",
            status="error",
            error=str(exc),
            detail="Optional: browser tool may be unavailable until Chromium is installed.",
        )
        raise


_INSTALLERS: dict[str, Callable[[], None]] = {
    "llama_cpp": _install_llama_and_cuda,
    "cuda_runtime": _install_llama_and_cuda,
    "primary_model": _install_primary,
    "vision_projector": _install_mmproj,
    "expert_model": _install_expert,
    "playwright_chromium": _install_playwright,
}


async def start_component_install(component_id: str) -> dict[str, Any]:
    if component_id not in COMPONENT_IDS:
        raise ValueError(f"Unknown component: {component_id}")
    discover_component_states()
    with _LOCK:
        existing = _TASKS.get(component_id)
        if existing and not existing.done():
            return asdict(_STATES[component_id])

    async def _runner() -> None:
        try:
            # cuda_runtime shares installer with llama_cpp
            if component_id == "cuda_runtime":
                await asyncio.to_thread(_install_llama_and_cuda)
            else:
                await asyncio.to_thread(_INSTALLERS[component_id])
        except Exception as exc:
            logger.exception("Component install failed: %s", component_id)
            _set_state(component_id, status="error", error=str(exc))

    task = asyncio.create_task(_runner())
    with _LOCK:
        _TASKS[component_id] = task
    return asdict(_STATES.get(component_id) or ComponentState(id=component_id, label=_label(component_id), status="downloading"))


async def start_selected_installs() -> dict[str, Any]:
    setup = load_setup_state()
    discover_component_states()
    order = ["llama_cpp", "primary_model", "vision_projector"]
    if setup.get("install_expert_27b"):
        order.append("expert_model")
    if setup.get("install_playwright", True):
        order.append("playwright_chromium")
    results = {}
    for cid in order:
        state = discover_component_states().get(cid)
        if state and state.status == "ready":
            results[cid] = asdict(state)
            continue
        if state and state.status == "skipped":
            results[cid] = asdict(state)
            continue
        results[cid] = await start_component_install(cid)
    return results
