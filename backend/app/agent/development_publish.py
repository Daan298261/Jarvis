"""RFC-0211 trusted publication: candidate commit, focused PR, exact-head CI, gated merge.

Only the trusted controller in ANZU's main process calls this module; mission
workers never receive publication authority (their settings keep ``auto_merge=False``).
GitHub access goes through the owner's signed-in ``gh`` CLI. Nothing here force-pushes,
bypasses checks (no ``--admin``) or merges a PR other than the task's own.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .development_queue import rfc_number
from .worktrees import run_git

SELF_DEV_BRANCH_PREFIX = "jarvis/self-dev-"
BOT_IDENTITY = ["-c", "user.name=ANZU self-development", "-c", "user.email=anzu-self-dev@localhost"]


class PublishError(RuntimeError):
    """Publication cannot proceed; the task needs attention (never retried silently)."""


class BaseConflict(PublishError):
    """The development base moved and conflicts with the candidate."""


def _flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def gh(args: list[str], *, cwd: str | Path | None = None, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    binary = shutil.which("gh")
    if not binary:
        raise PublishError("GitHub CLI (gh) is not installed; install it and run `gh auth login` so ANZU can check and publish work")
    try:
        result = subprocess.run([binary, *args], cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout, creationflags=_flags())
    except subprocess.TimeoutExpired as exc:
        raise PublishError(f"gh {args[0]} timed out") from exc
    return result


def gh_ok(args: list[str], **kwargs: Any) -> str:
    result = gh(args, **kwargs)
    if result.returncode != 0:
        raise PublishError(f"gh {' '.join(args[:2])} failed: {(result.stderr or result.stdout).strip()[:500]}")
    return result.stdout


def github_slug(repo: str | Path) -> str:
    url = run_git(repo, ["remote", "get-url", "origin"], check=False).stdout.strip()
    match = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", url)
    if not match:
        raise PublishError("The repository's origin remote is not a GitHub repository")
    return f"{match.group(1)}/{match.group(2)}"


def pr_evidence(repo: str | Path) -> dict[str, Any]:
    """Delivered (merged) and claimed (open) RFC numbers from the repository's PRs."""
    slug = github_slug(repo)
    rows = json.loads(gh_ok(["pr", "list", "--repo", slug, "--state", "all", "--limit", "1000",
                             "--json", "number,title,state,headRefName"], timeout=180) or "[]")
    merged: dict[str, int] = {}
    claimed: dict[str, int] = {}
    for row in rows:
        number = rfc_number(row.get("title", ""))
        if not number:
            continue
        if row.get("state") == "MERGED":
            merged.setdefault(number, int(row["number"]))
        elif row.get("state") == "OPEN" and not str(row.get("headRefName", "")).startswith(SELF_DEV_BRANCH_PREFIX):
            claimed.setdefault(number, int(row["number"]))
    return {"slug": slug, "merged": merged, "open": claimed}


def commit_candidate(worktree: str, message: str, *, exclude: list[str] = ()) -> str:
    """Commit the worker's changes as the controller; returns the head SHA."""
    for relative in exclude:
        (Path(worktree) / relative).unlink(missing_ok=True)
    run_git(worktree, ["add", "-A"])
    if run_git(worktree, ["diff", "--cached", "--quiet"], check=False).returncode != 0:
        run_git(worktree, [*BOT_IDENTITY, "commit", "--no-verify", "-m", message])
    return run_git(worktree, ["rev-parse", "HEAD"]).stdout.strip()


def checkpoint(worktree: str, message: str) -> str:
    """Safe stop: keep in-flight edits on the mission branch, never discard them."""
    return commit_candidate(worktree, message)


def origin_tip(worktree: str, base_ref: str) -> str:
    run_git(worktree, ["fetch", "--quiet", "origin", base_ref])
    return run_git(worktree, ["rev-parse", "FETCH_HEAD"]).stdout.strip()


def merge_base_into(worktree: str, tip: str) -> str:
    """Bring a moved development base into the candidate with a normal merge (never rebase)."""
    result = run_git(worktree, [*BOT_IDENTITY, "merge", "--no-edit", "--no-ff", tip], check=False)
    if result.returncode != 0:
        run_git(worktree, ["merge", "--abort"], check=False)
        raise BaseConflict(f"development moved to {tip[:12]} and conflicts with this change: {(result.stdout + result.stderr).strip()[:400]}")
    return run_git(worktree, ["rev-parse", "HEAD"]).stdout.strip()


def push_branch(worktree: str, branch: str) -> None:
    result = run_git(worktree, ["push", "origin", f"HEAD:refs/heads/{branch}"], check=False)
    if result.returncode != 0:
        raise PublishError(f"Push of {branch} failed: {(result.stderr or result.stdout).strip()[:400]}")


def ensure_pr(repo: str | Path, *, branch: str, base: str, title: str, body: str) -> int:
    slug = github_slug(repo)
    existing = json.loads(gh_ok(["pr", "list", "--repo", slug, "--head", branch, "--state", "all", "--json", "number,state"]) or "[]")
    for row in existing:
        if row["state"] in {"OPEN", "MERGED"}:
            return int(row["number"])
    url = gh_ok(["pr", "create", "--repo", slug, "--base", base, "--head", branch, "--title", title, "--body", body]).strip()
    match = re.search(r"/pull/(\d+)", url)
    if not match:
        raise PublishError(f"gh pr create returned no PR URL: {url[:200]}")
    return int(match.group(1))


def pr_state(repo: str | Path, number: int) -> dict[str, Any]:
    slug = github_slug(repo)
    view = json.loads(gh_ok(["pr", "view", str(number), "--repo", slug, "--json", "state,headRefOid,mergeCommit,baseRefName"]))
    return {"state": view["state"], "head": view["headRefOid"], "merge_sha": (view.get("mergeCommit") or {}).get("oid", ""), "base": view.get("baseRefName", "")}


def check_outcome(repo: str | Path, number: int, head_sha: str) -> dict[str, Any]:
    """Exact-head CI result: pending, passed, failed, or head_changed.

    Required checks when the branch defines them; otherwise every reported check.
    """
    slug = github_slug(repo)
    view = pr_state(repo, number)
    if view["head"] != head_sha:
        return {"outcome": "head_changed", "detail": f"PR head is {view['head'][:12]}, approved {head_sha[:12]}"}
    result = gh(["pr", "checks", str(number), "--repo", slug, "--required", "--json", "name,bucket,state"])
    if result.returncode != 0 and "no required checks" in (result.stderr + result.stdout):
        result = gh(["pr", "checks", str(number), "--repo", slug, "--json", "name,bucket,state"])
    text = (result.stderr + result.stdout)
    if result.returncode != 0 and "no checks reported" in text:
        return {"outcome": "pending", "detail": "Waiting for CI to report checks", "checks": []}
    try:
        checks = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise PublishError(f"Could not read PR checks: {text.strip()[:300]}") from exc
    if not checks:
        return {"outcome": "pending", "detail": "Waiting for CI to report checks", "checks": []}
    buckets = {c["bucket"] for c in checks}
    if buckets & {"fail", "cancel"}:
        failed = [c["name"] for c in checks if c["bucket"] in {"fail", "cancel"}]
        return {"outcome": "failed", "detail": "Failing checks: " + ", ".join(failed), "checks": checks}
    if "pending" in buckets:
        return {"outcome": "pending", "detail": "CI is running", "checks": checks}
    return {"outcome": "passed", "detail": "All checks passed at the approved head", "checks": checks}


def merge_pr(repo: str | Path, number: int, head_sha: str) -> str:
    """Merge only if GitHub still has the approved head; returns the merge SHA."""
    slug = github_slug(repo)
    before = pr_state(repo, number)
    if before["state"] != "MERGED":
        if before["head"] != head_sha:
            raise PublishError("The PR head changed after approval; review and validation must run again")
        gh_ok(["pr", "merge", str(number), "--repo", slug, "--merge", "--match-head-commit", head_sha], timeout=300)
    after = pr_state(repo, number)
    if after["state"] != "MERGED" or not after["merge_sha"]:
        raise PublishError("GitHub did not report the PR as merged")
    return after["merge_sha"]
