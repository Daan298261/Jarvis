from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir, repo_root

TRIAL_BRANCH_PREFIX = "jarvis/autonomous-trial-"
REGISTRY_NAME = "worktrees.json"


class WorktreeError(ValueError):
    """Raised when an isolated-worktree operation is refused or fails."""


@dataclass
class WorktreeSpec:
    id: str
    source_repo: str
    path: str
    branch: str
    start_commit: str
    created_at: str
    status: str = "active"
    last_commit: str = ""
    checkpoints: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def worktrees_root() -> Path:
    path = data_dir() / "worktrees"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _registry_path() -> Path:
    return worktrees_root() / REGISTRY_NAME


def load_registry() -> list[WorktreeSpec]:
    path = _registry_path()
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out: list[WorktreeSpec] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            WorktreeSpec(
                id=str(row.get("id") or ""),
                source_repo=str(row.get("source_repo") or ""),
                path=str(row.get("path") or ""),
                branch=str(row.get("branch") or ""),
                start_commit=str(row.get("start_commit") or ""),
                created_at=str(row.get("created_at") or ""),
                status=str(row.get("status") or "active"),
                last_commit=str(row.get("last_commit") or ""),
                checkpoints=list(row.get("checkpoints") or []),
            )
        )
    return out


def save_registry(items: list[WorktreeSpec]) -> None:
    _registry_path().write_text(
        json.dumps([item.as_dict() for item in items], indent=2),
        encoding="utf-8",
    )


def run_git(cwd: str | Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"git {' '.join(args)} failed"
        raise WorktreeError(err)
    return proc


def _git_out(cwd: str | Path, args: list[str]) -> str:
    return run_git(cwd, args).stdout.strip()


def resolve_repo(path: str | Path | None = None) -> Path:
    target = Path(path).expanduser().resolve() if path else repo_root()
    probe = run_git(target, ["rev-parse", "--show-toplevel"], check=False)
    if probe.returncode != 0:
        raise WorktreeError(f"{target} is not a git repository")
    return Path(probe.stdout.strip()).resolve()


def current_commit(repo: Path) -> str:
    return _git_out(repo, ["rev-parse", "HEAD"])


def current_branch(repo: Path) -> str:
    proc = run_git(repo, ["branch", "--show-current"], check=False)
    name = (proc.stdout or "").strip()
    return name or "HEAD"


def listed_worktrees(repo: Path) -> list[Path]:
    proc = run_git(repo, ["worktree", "list", "--porcelain"], check=False)
    if proc.returncode != 0:
        return []
    paths: list[Path] = []
    for line in (proc.stdout or "").splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.split(" ", 1)[1]).resolve())
    return paths


def production_checkout(repo: Path | None = None) -> Path:
    source = resolve_repo(repo) if repo is not None else resolve_repo()
    listed = listed_worktrees(source)
    return listed[0] if listed else source


def is_production_checkout(path: str | Path, repo: Path | None = None) -> bool:
    target = Path(path).expanduser().resolve()
    trusted = production_checkout(repo or target)
    return target == trusted


def is_isolated_worktree(path: str | Path, repo: Path | None = None) -> bool:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return False
    if is_production_checkout(target, repo):
        return False
    try:
        source = resolve_repo(repo or target)
    except WorktreeError:
        return False
    listed = listed_worktrees(source)
    if listed and target in listed[1:]:
        return True
    branch = current_branch(target)
    return branch.startswith(TRIAL_BRANCH_PREFIX) or branch.startswith("jarvis/self-dev-")


def _unique_branch(when: datetime | None = None) -> str:
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    suffix = uuid.uuid4().hex[:8]
    return f"{TRIAL_BRANCH_PREFIX}{stamp}-{suffix}"


def create_worktree(source: str | Path | None = None, dest: str | Path | None = None, branch: str | None = None) -> WorktreeSpec:
    repo = resolve_repo(source)
    trusted = production_checkout(repo)
    start = current_commit(repo)
    branch_name = branch or _unique_branch()
    if not re.match(r"^jarvis/(autonomous-trial|self-dev)-", branch_name):
        raise WorktreeError("Self-development branches must start with jarvis/autonomous-trial- or jarvis/self-dev-")
    dest_path = Path(dest).expanduser().resolve() if dest else worktrees_root() / branch_name.replace("/", "-")
    if dest_path.exists():
        raise WorktreeError(f"Worktree destination already exists: {dest_path}")
    if dest_path == trusted:
        raise WorktreeError("Refusing to create an experimental worktree on the trusted checkout")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    run_git(repo, ["worktree", "add", "-b", branch_name, str(dest_path), "HEAD"])
    run_git(dest_path, ["config", "user.email", "jarvis-self-dev@localhost"], check=False)
    run_git(dest_path, ["config", "user.name", "Jarvis Self-Development"], check=False)
    spec = WorktreeSpec(
        id=uuid.uuid4().hex[:12],
        source_repo=str(repo),
        path=str(dest_path),
        branch=branch_name,
        start_commit=start,
        created_at=datetime.now(timezone.utc).isoformat(),
        last_commit=start,
    )
    items = load_registry()
    items.append(spec)
    save_registry(items)
    return spec


def get_worktree(worktree_id: str) -> WorktreeSpec:
    for item in load_registry():
        if item.id == worktree_id:
            return item
    raise WorktreeError(f"Unknown worktree {worktree_id}")


def worktree_status(path: str | Path) -> dict[str, Any]:
    repo = Path(path).expanduser().resolve()
    status = run_git(repo, ["status", "--porcelain=v1", "-b"], check=False)
    log = run_git(repo, ["log", "-n", "8", "--oneline", "--decorate"], check=False)
    return {
        "path": str(repo),
        "branch": current_branch(repo),
        "commit": current_commit(repo) if status.returncode == 0 else "",
        "isolated": is_isolated_worktree(repo),
        "production": is_production_checkout(repo),
        "status": status.stdout.strip() if status.returncode == 0 else (status.stderr or "").strip(),
        "log": log.stdout.strip() if log.returncode == 0 else "",
    }


def diff_summary(path: str | Path, since: str | None = None) -> dict[str, Any]:
    repo = Path(path).expanduser().resolve()
    base = since or "HEAD"
    try:
        spec_commit = ""
        for item in load_registry():
            if Path(item.path).resolve() == repo:
                spec_commit = item.start_commit
                break
        if spec_commit:
            base = spec_commit
    except OSError:
        pass
    proc = run_git(repo, ["diff", "--stat", f"{base}...HEAD"], check=False)
    names = run_git(repo, ["diff", "--name-status", f"{base}...HEAD"], check=False)
    return {
        "base": base,
        "head": current_commit(repo) if proc.returncode == 0 else "",
        "stat": (proc.stdout or "").strip(),
        "files": (names.stdout or "").strip(),
    }


def checkpoint_commit(path: str | Path, message: str) -> dict[str, Any]:
    repo = Path(path).expanduser().resolve()
    if is_production_checkout(repo):
        raise WorktreeError("Refusing to commit on the trusted production checkout. Use an isolated worktree.")
    if not is_isolated_worktree(repo):
        raise WorktreeError("Checkpoint commits are only allowed inside an isolated Jarvis worktree.")
    run_git(repo, ["add", "-A"])
    staged = run_git(repo, ["diff", "--cached", "--quiet"], check=False)
    if staged.returncode == 0:
        return {"commit": current_commit(repo), "created": False, "message": "No changes to commit"}
    msg = (message or "jarvis checkpoint").strip() or "jarvis checkpoint"
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "Jarvis Self-Development")
    env.setdefault("GIT_AUTHOR_EMAIL", "jarvis-self-dev@localhost")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    proc = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        raise WorktreeError((proc.stderr or proc.stdout or "git commit failed").strip())
    sha = current_commit(repo)
    items = load_registry()
    for item in items:
        if Path(item.path).resolve() == repo:
            item.last_commit = sha
            item.checkpoints.append(sha)
            break
    save_registry(items)
    return {"commit": sha, "created": True, "message": msg}


def discard_worktree(worktree_id: str) -> WorktreeSpec:
    spec = get_worktree(worktree_id)
    dest = Path(spec.path).resolve()
    source = Path(spec.source_repo).resolve()
    if is_production_checkout(dest, source):
        raise WorktreeError("Refusing to discard the trusted production checkout")
    listed = listed_worktrees(source)
    if listed and dest == listed[0]:
        raise WorktreeError("Refusing to remove the primary worktree")
    if listed and dest not in listed:
        raise WorktreeError("Path is not a git worktree of the recorded source repository")
    run_git(source, ["worktree", "remove", "--force", str(dest)], check=False)
    run_git(source, ["branch", "-D", spec.branch], check=False)
    spec.status = "discarded"
    items = [item if item.id != spec.id else spec for item in load_registry()]
    save_registry(items)
    return spec


def refuse_trusted_merge(target_branch: str = "main") -> None:
    raise PermissionError(
        f"Autonomous self-development must not merge into trusted branch {target_branch!r}. "
        "Leave a candidate branch for human review."
    )


def list_worktrees() -> list[dict[str, Any]]:
    return [item.as_dict() for item in load_registry()]
