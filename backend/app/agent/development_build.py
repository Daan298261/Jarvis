"""RFC-0211 durable development build jobs, keyed by the development merge SHA.

A build runs the repository's Windows packaging pipeline
(``installer/windows/build-installer.ps1``, never ``-Release``: no stable-release
credentials or vendor issuer material) in a clean detached checkout of the exact
merge SHA. A job is retried without repeating the merge, and a task stays
``build_failed`` until a real ``AnzuSetup.exe`` passes the packaging checks.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil

from ..config import data_dir
from .worktrees import run_git

ARTIFACT = Path("installer/windows/dist/AnzuSetup.exe")
MIN_ARTIFACT_BYTES = 1_000_000


class BuildUnavailable(RuntimeError):
    """This machine cannot run the Windows packaging pipeline."""


def builds_root() -> Path:
    path = data_dir() / "development_builds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def packaging_host_error() -> str:
    if os.name != "nt":
        return "Development builds need the Windows packaging host (PowerShell + Inno Setup); this machine is not Windows"
    if not shutil.which("powershell") and not shutil.which("pwsh"):
        return "PowerShell is required for the Windows packaging pipeline"
    return ""


def new_job(merge_sha: str, item_id: str, pr: int | None) -> dict[str, Any]:
    return {"merge_sha": merge_sha, "item_id": item_id, "pr": pr, "status": "pending", "attempts": 0,
            "created_at": time.time(), "error": "", "artifact": "", "sha256": "", "log": "", "checkout": ""}


def start(repo: str | Path, job: dict[str, Any]) -> dict[str, Any]:
    """Start one attempt; returns the updated job (status ``running``)."""
    problem = packaging_host_error()
    if problem:
        raise BuildUnavailable(problem)
    sha = job["merge_sha"]
    folder = builds_root() / sha
    checkout = folder / "checkout"
    run_git(repo, ["fetch", "--quiet", "origin", sha], check=False)
    if checkout.exists():
        run_git(repo, ["worktree", "remove", "--force", str(checkout)], check=False)
        shutil.rmtree(checkout, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    run_git(repo, ["worktree", "add", "--detach", str(checkout), sha])
    if run_git(checkout, ["rev-parse", "HEAD"]).stdout.strip() != sha:
        raise RuntimeError("Build checkout is not at the merge SHA")
    attempt = job["attempts"] + 1
    log_path = folder / f"build-{attempt}.log"
    shell = shutil.which("powershell") or shutil.which("pwsh")
    script = str(checkout / "installer/windows/build-installer.ps1").replace("'", "''")
    exit_file = folder / f"build-{attempt}.exit"
    exit_file.unlink(missing_ok=True)
    marker = str(exit_file).replace("'", "''")
    # The exit status survives an ANZU restart, so a reconciled job never guesses success.
    wrapper = (f"try {{ & '{script}'; if ($LASTEXITCODE) {{ throw \"build-installer.ps1 exited $LASTEXITCODE\" }}; "
               f"Set-Content -LiteralPath '{marker}' -Value 0 }} catch {{ Write-Output $_; Set-Content -LiteralPath '{marker}' -Value 1; exit 1 }}")
    command = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", wrapper]
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=str(checkout), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return {**job, "status": "running", "attempts": attempt, "pid": process.pid,
            "created": psutil.Process(process.pid).create_time(), "log": str(log_path), "exit_file": str(exit_file), "checkout": str(checkout),
            "started_at": time.time(), "error": ""}


def _alive(job: dict[str, Any]) -> bool:
    try:
        process = psutil.Process(job["pid"])
        return abs(process.create_time() - job["created"]) < 1 and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
        return False


def poll(job: dict[str, Any]) -> dict[str, Any]:
    """Reconcile a running job (also after an ANZU restart) without starting another."""
    if job["status"] != "running" or _alive(job):
        return job
    exit_file = Path(job.get("exit_file", ""))
    code = exit_file.read_text(encoding="utf-8").strip() if exit_file.is_file() else ""
    if code != "0":
        reason = "was interrupted before it finished" if not code else "failed"
        return {**job, "status": "failed", "ended_at": time.time(), "error": f"The packaging pipeline {reason}; see {job['log']}"}
    artifact = Path(job["checkout"]) / ARTIFACT
    if not artifact.is_file() or artifact.stat().st_size < MIN_ARTIFACT_BYTES:
        return {**job, "status": "failed", "ended_at": time.time(),
                "error": f"Packaging reported success without a usable {ARTIFACT.as_posix()}; see {job['log']}"}
    folder = builds_root() / job["merge_sha"]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "AnzuSetup.exe"
    shutil.copy2(artifact, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (folder / "SHA256SUMS").write_text(f"{digest}  AnzuSetup.exe\n", encoding="utf-8")
    (folder / "REVISION").write_text(job["merge_sha"] + "\n", encoding="utf-8")
    return {**job, "status": "succeeded", "ended_at": time.time(), "artifact": str(target), "sha256": digest, "error": ""}
