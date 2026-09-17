"""Owner-triggered install for optional workers.

Only the five catalogued adapters can be installed. Package names and git URLs
are hardcoded; the API never accepts a pip spec or shell command from the client.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import shutil
import site
import subprocess
import sys
import sysconfig
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import logs_dir, repo_root

logger = logging.getLogger(__name__)

INSTALL_TIMEOUT_SECONDS = 900
UFO_GIT_URL = "https://github.com/microsoft/UFO.git"

OPTIONAL_WORKER_IDS = (
    "browser-use",
    "ufo",
    "cua",
    "open-interpreter",
    "openhands",
)


@dataclass(frozen=True)
class InstallAttempt:
    pip_packages: tuple[str, ...] = ()
    git_url: str = ""
    git_dirname: str = ""
    requirements: bool = False
    extra_modules: tuple[str, ...] = ()


SPECS: dict[str, tuple[InstallAttempt, ...]] = {
    "browser-use": (
        InstallAttempt(
            pip_packages=("browser-use[core]",),
            extra_modules=("playwright",),
        ),
        InstallAttempt(pip_packages=("browser-use",), extra_modules=("playwright",)),
    ),
    "ufo": (
        InstallAttempt(git_url=UFO_GIT_URL, git_dirname="microsoft-ufo", requirements=True),
    ),
    "cua": (
        InstallAttempt(pip_packages=("cua",)),
        InstallAttempt(pip_packages=("cua-computer", "cua-agent")),
        InstallAttempt(pip_packages=("cua-cli",)),
    ),
    "open-interpreter": (InstallAttempt(pip_packages=("open-interpreter",)),),
    "openhands": (
        InstallAttempt(pip_packages=("openhands",)),
        InstallAttempt(pip_packages=("openhands-ai",)),
    ),
}


@dataclass
class InstallJob:
    worker_id: str
    status: str = "idle"  # idle|installing|ready|error
    error: str = ""
    detail: str = ""
    already_installed: bool = False
    already_started: bool = False


_LOCK = threading.Lock()
_JOBS: dict[str, InstallJob] = {}
_TASKS: dict[str, asyncio.Task[None]] = {}


def reset_install_jobs() -> None:
    """Test helper. Does not cancel OS subprocesses."""
    with _LOCK:
        _JOBS.clear()
        _TASKS.clear()


def snapshot_jobs() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return {key: asdict(job) for key, job in _JOBS.items()}


def overlay_install_state(workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    jobs = snapshot_jobs()
    overlaid: list[dict[str, Any]] = []
    for raw in workers:
        item = dict(raw)
        worker_id = str(item.get("id") or "")
        spec = SPECS.get(worker_id)
        job = jobs.get(worker_id)
        available = bool(item.get("available"))
        item["installable"] = bool(spec) and not available
        if job:
            item["install_status"] = job["status"]
            item["install_error"] = job.get("error") or ""
            item["install_detail"] = job.get("detail") or ""
            if job["status"] == "installing" and not available:
                item["status"] = "installing"
        else:
            item["install_status"] = "idle"
            item["install_error"] = ""
            item["install_detail"] = ""
        overlaid.append(item)
    return overlaid


def _backend(worker_id: str) -> Any:
    from .browser import BrowserUseBackend
    from .code import OpenHandsBackend
    from .computer import CuaBackend, UFOBackend
    from .interpreter import OpenInterpreterBackend

    mapping: dict[str, Callable[[], Any]] = {
        "browser-use": BrowserUseBackend,
        "ufo": UFOBackend,
        "cua": CuaBackend,
        "open-interpreter": OpenInterpreterBackend,
        "openhands": OpenHandsBackend,
    }
    factory = mapping.get(worker_id)
    if factory is None:
        return None
    return factory()


def _in_venv() -> bool:
    return getattr(sys, "base_prefix", sys.prefix) != sys.prefix or bool(os.environ.get("VIRTUAL_ENV"))


def _pip_cmd(*packages: str) -> list[str]:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check"]
    if not _in_venv():
        cmd.append("--user")
    cmd.extend(packages)
    return cmd


def _set_job(worker_id: str, **kwargs: Any) -> InstallJob:
    with _LOCK:
        job = _JOBS.get(worker_id) or InstallJob(worker_id=worker_id)
        for key, value in kwargs.items():
            setattr(job, key, value)
        _JOBS[worker_id] = job
        return job


def _tail(text: str, limit: int = 1600) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[-limit:]


def _write_install_log(worker_id: str, output: str) -> Path:
    path = logs_dir() / f"optional-worker-{worker_id}.log"
    path.write_text(output or "", encoding="utf-8")
    return path


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = INSTALL_TIMEOUT_SECONDS) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Timed out after {timeout}s: {' '.join(command[:6])}") from exc
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return proc.returncode or 0, output


def _site_package_dirs() -> list[Path]:
    paths: list[Path] = []
    purelib = sysconfig.get_path("purelib")
    if purelib:
        paths.append(Path(purelib))
    if hasattr(site, "getsitepackages"):
        paths.extend(Path(item) for item in site.getsitepackages())
    user_site = site.getusersitepackages()
    if user_site:
        paths.append(Path(user_site))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _write_pth(name: str, target: Path) -> Path:
    body = str(target.resolve()) + "\n"
    last_error: Exception | None = None
    for directory in _site_package_dirs():
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"jarvis_{name}.pth"
            path.write_text(body, encoding="utf-8")
            return path
        except OSError as exc:
            last_error = exc
            continue
    raise RuntimeError(f"Could not write {name}.pth into site-packages: {last_error}")


def _optional_worker_root() -> Path:
    path = repo_root() / "runtime" / "optional-workers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _clone_repo(url: str, dest: Path) -> None:
    if url != UFO_GIT_URL:
        raise RuntimeError("Refusing to clone an unlisted repository")
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is required to install Microsoft UFO. Install Git for Windows and retry.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if (dest / ".git").is_dir():
        code, output = _run([git, "-C", str(dest), "pull", "--ff-only"])
        if code != 0:
            raise RuntimeError(f"git pull failed:\n{_tail(output)}")
        return
    if dest.exists():
        shutil.rmtree(dest)
    code, output = _run([git, "clone", "--depth", "1", url, str(dest)])
    if code != 0:
        raise RuntimeError(f"git clone failed:\n{_tail(output)}")


def _refresh_import_path() -> None:
    importlib.invalidate_caches()
    scripts = Path(sys.executable).resolve().parent
    current = os.environ.get("PATH", "")
    prefix = str(scripts)
    if prefix and prefix not in current.split(os.pathsep):
        os.environ["PATH"] = prefix + os.pathsep + current


def _playwright_chromium() -> None:
    code, output = _run([sys.executable, "-m", "playwright", "install", "chromium"], timeout=600)
    if code != 0:
        logger.warning("Playwright Chromium extra step failed: %s", _tail(output))


def _install_attempt(worker_id: str, attempt: InstallAttempt) -> None:
    outputs: list[str] = []
    if attempt.git_url:
        dest = _optional_worker_root() / attempt.git_dirname
        _set_job(worker_id, detail=f"Cloning {attempt.git_url}…")
        _clone_repo(attempt.git_url, dest)
        if attempt.requirements:
            requirements = dest / "requirements.txt"
            if not requirements.is_file():
                raise RuntimeError(f"{dest} has no requirements.txt")
            _set_job(worker_id, detail="Installing UFO Python requirements…")
            code, output = _run(_pip_cmd("-r", str(requirements)), cwd=dest)
            outputs.append(output)
            _write_install_log(worker_id, "\n\n".join(outputs))
            if code != 0:
                raise RuntimeError(f"pip install -r requirements.txt failed:\n{_tail(output)}")
        _write_pth(attempt.git_dirname.replace("-", "_"), dest)
    elif attempt.pip_packages:
        _set_job(worker_id, detail=f"Installing {' '.join(attempt.pip_packages)}…")
        code, output = _run(_pip_cmd(*attempt.pip_packages))
        outputs.append(output)
        _write_install_log(worker_id, "\n\n".join(outputs))
        if code != 0:
            raise RuntimeError(f"pip install {' '.join(attempt.pip_packages)} failed:\n{_tail(output)}")
    else:
        raise RuntimeError("Empty install attempt")
    if "playwright" in attempt.extra_modules:
        _playwright_chromium()
    _refresh_import_path()


def _install_worker(worker_id: str) -> None:
    attempts = SPECS.get(worker_id)
    if not attempts:
        raise KeyError(worker_id)
    backend = _backend(worker_id)
    if backend is None:
        raise KeyError(worker_id)
    if backend.available():
        _set_job(worker_id, status="ready", already_installed=True, error="", detail="Already installed")
        return
    errors: list[str] = []
    for index, attempt in enumerate(attempts, start=1):
        try:
            _install_attempt(worker_id, attempt)
        except Exception as exc:
            errors.append(str(exc))
            logger.warning("Optional worker %s attempt %s failed: %s", worker_id, index, exc)
            continue
        if backend.available():
            _set_job(worker_id, status="ready", error="", detail="Installed")
            return
        errors.append("Packages installed but the worker is still not detectable")
    raise RuntimeError(" | ".join(errors) or f"Could not install {worker_id}")


async def start_worker_install(worker_id: str) -> dict[str, Any]:
    if worker_id not in SPECS:
        raise KeyError(worker_id)
    backend = _backend(worker_id)
    if backend is not None and backend.available():
        job = _set_job(worker_id, status="ready", already_installed=True, error="", detail="Already installed")
        return asdict(job)
    with _LOCK:
        existing = _TASKS.get(worker_id)
        if existing is not None and not existing.done():
            job = _JOBS.get(worker_id) or InstallJob(worker_id=worker_id, status="installing")
            job.already_started = True
            _JOBS[worker_id] = job
            return asdict(job)
        _set_job(worker_id, status="installing", error="", detail="Starting install…", already_installed=False, already_started=False)

    async def _runner() -> None:
        try:
            await asyncio.to_thread(_install_worker, worker_id)
        except Exception as exc:
            logger.exception("Optional worker install failed: %s", worker_id)
            _set_job(worker_id, status="error", error=str(exc), detail=str(exc))

    task = asyncio.create_task(_runner())
    with _LOCK:
        _TASKS[worker_id] = task
    return asdict(_JOBS[worker_id])
