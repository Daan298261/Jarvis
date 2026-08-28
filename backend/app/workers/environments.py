from __future__ import annotations

import json
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from . import credentials as cred_broker

_lock = threading.RLock()

REGISTRY_NAME = "registry.json"
AUDIT_NAME = "audit.jsonl"

STATUS_CREATED = "created"
STATUS_RUNNING = "running"
STATUS_SUSPENDED = "suspended"

VALID_STATUSES = {STATUS_CREATED, STATUS_RUNNING, STATUS_SUSPENDED}

QUOTA_KEYS = ("disk_mb", "cpu_threads", "ram_gb", "gpu_percent", "max_background_processes")


class EnvironmentError(ValueError):
    """Raised when a worker environment operation is refused or fails."""


class EnvironmentNotFound(EnvironmentError):
    """Raised when a worker environment id does not exist."""


@dataclass
class WorkerEnvironment:
    id: str
    name: str
    worker_kind: str
    agent_profile: str
    status: str
    created_at: str
    last_active_at: str
    suspended_at: str | None = None
    quotas: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def environments_root() -> Path:
    path = data_dir() / "worker-environments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _registry_path() -> Path:
    return environments_root() / REGISTRY_NAME


def _audit_path() -> Path:
    return environments_root() / AUDIT_NAME


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_root(env_id: str) -> Path:
    return environments_root() / env_id


def workspace_dir(env_id: str) -> Path:
    return _env_root(env_id) / "workspace"


def caches_dir(env_id: str) -> Path:
    return _env_root(env_id) / "caches"


def browser_profile_dir(env_id: str) -> Path:
    return _env_root(env_id) / "browser-profile"


def logs_dir(env_id: str) -> Path:
    return _env_root(env_id) / "logs"


def state_path(env_id: str) -> Path:
    return _env_root(env_id) / "state.json"


def _load_registry() -> list[WorkerEnvironment]:
    path = _registry_path()
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out: list[WorkerEnvironment] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            WorkerEnvironment(
                id=str(row.get("id") or ""),
                name=str(row.get("name") or ""),
                worker_kind=str(row.get("worker_kind") or ""),
                agent_profile=str(row.get("agent_profile") or ""),
                status=str(row.get("status") or STATUS_CREATED),
                created_at=str(row.get("created_at") or ""),
                last_active_at=str(row.get("last_active_at") or ""),
                suspended_at=row.get("suspended_at"),
                quotas=dict(row.get("quotas") or {}),
                metadata=dict(row.get("metadata") or {}),
            )
        )
    return out


def _save_registry(items: list[WorkerEnvironment]) -> None:
    _registry_path().write_text(
        json.dumps([item.as_dict() for item in items], indent=2),
        encoding="utf-8",
    )


def audit_log(
    event: str,
    *,
    environment_id: str | None = None,
    credential_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "timestamp": _utcnow(),
        "event": event,
        "environment_id": environment_id,
        "credential_id": credential_id,
        "details": details or {},
    }
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry


def list_audit_events(
    *,
    environment_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    path = _audit_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if environment_id and row.get("environment_id") != environment_id:
            continue
        rows.append(row)
    if limit > 0:
        rows = rows[-limit:]
    return rows


def normalize_quotas(quotas: dict[str, Any] | None) -> dict[str, Any]:
    if not quotas:
        return {}
    normalized: dict[str, Any] = {}
    for key, value in quotas.items():
        name = str(key or "").strip().lower()
        if name not in QUOTA_KEYS:
            raise EnvironmentError(f"Unknown quota key: {key!r}")
        if value is None:
            continue
        if name == "max_background_processes":
            normalized[name] = int(value)
            if normalized[name] < 0:
                raise EnvironmentError("max_background_processes must be non-negative")
        else:
            normalized[name] = float(value)
            if normalized[name] < 0:
                raise EnvironmentError(f"{name} must be non-negative")
    return normalized


def directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    if path.is_file():
        return path.stat().st_size
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def environment_disk_usage_bytes(env_id: str) -> int:
    root = _env_root(env_id)
    if not root.exists():
        return 0
    return directory_size_bytes(root)


def check_quota_violations(env: WorkerEnvironment, usage: dict[str, Any] | None = None) -> list[str]:
    """Thin quota helper — checks configured limits against measured or supplied usage."""
    quotas = env.quotas or {}
    if not quotas:
        return []
    measured = usage or {}
    if "disk_mb" not in measured:
        measured = dict(measured)
        measured["disk_mb"] = environment_disk_usage_bytes(env.id) / (1024 * 1024)
    violations: list[str] = []
    for key in QUOTA_KEYS:
        limit = quotas.get(key)
        if limit is None:
            continue
        used = measured.get(key, 0)
        if float(used) > float(limit) + 1e-9:
            violations.append(key)
    return violations


def _ensure_layout(env_id: str) -> None:
    for folder in (workspace_dir, caches_dir, browser_profile_dir, logs_dir):
        folder(env_id).mkdir(parents=True, exist_ok=True)
    state_file = state_path(env_id)
    if not state_file.exists():
        state_file.write_text(
            json.dumps({"processes": [], "task_state": {}}, indent=2),
            encoding="utf-8",
        )


def _load_state(env_id: str) -> dict[str, Any]:
    path = state_path(env_id)
    if not path.exists():
        return {"processes": [], "task_state": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"processes": [], "task_state": {}}
    return payload if isinstance(payload, dict) else {"processes": [], "task_state": {}}


def _save_state(env_id: str, state: dict[str, Any]) -> None:
    state_path(env_id).write_text(json.dumps(state, indent=2), encoding="utf-8")


def _get_env(env_id: str) -> WorkerEnvironment:
    for item in _load_registry():
        if item.id == env_id:
            return item
    raise EnvironmentNotFound(f"Environment not found: {env_id}")


def _update_env(env_id: str, **changes: Any) -> WorkerEnvironment:
    items = _load_registry()
    updated: WorkerEnvironment | None = None
    for index, item in enumerate(items):
        if item.id != env_id:
            continue
        payload = item.as_dict()
        payload.update(changes)
        updated = WorkerEnvironment(**payload)
        items[index] = updated
        break
    if updated is None:
        raise EnvironmentNotFound(f"Environment not found: {env_id}")
    _save_registry(items)
    return updated


def create_environment(
    *,
    name: str,
    worker_kind: str = "general",
    agent_profile: str = "default",
    quotas: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    environment_id: str | None = None,
) -> dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        raise EnvironmentError("name is required")
    env_id = environment_id or str(uuid.uuid4())
    now = _utcnow()
    normalized_quotas = normalize_quotas(quotas)

    with _lock:
        for item in _load_registry():
            if item.id == env_id:
                raise EnvironmentError(f"Environment already exists: {env_id}")
        env = WorkerEnvironment(
            id=env_id,
            name=name,
            worker_kind=str(worker_kind or "general"),
            agent_profile=str(agent_profile or "default"),
            status=STATUS_CREATED,
            created_at=now,
            last_active_at=now,
            quotas=normalized_quotas,
            metadata=dict(metadata or {}),
        )
        items = _load_registry()
        items.append(env)
        _save_registry(items)
        _ensure_layout(env_id)

    audit_log("environment.created", environment_id=env_id, details={"name": name, "worker_kind": env.worker_kind})
    return environment_status(env_id)


def list_environments() -> list[dict[str, Any]]:
    return [environment_status(item.id) for item in _load_registry()]


def environment_status(env_id: str) -> dict[str, Any]:
    env = _get_env(env_id)
    disk_bytes = environment_disk_usage_bytes(env_id)
    violations = check_quota_violations(env)
    return {
        **env.as_dict(),
        "disk_usage_bytes": disk_bytes,
        "disk_usage_mb": round(disk_bytes / (1024 * 1024), 3),
        "quota_violations": violations,
    }


def inspect_environment(env_id: str) -> dict[str, Any]:
    env = _get_env(env_id)
    state = _load_state(env_id)
    workspace = workspace_dir(env_id)
    workspace_files: list[str] = []
    if workspace.exists():
        for child in sorted(workspace.iterdir()):
            if child.is_file():
                workspace_files.append(child.name)
            elif child.is_dir():
                workspace_files.append(f"{child.name}/")
    log_files: list[str] = []
    logs = logs_dir(env_id)
    if logs.exists():
        log_files = sorted(path.name for path in logs.iterdir() if path.is_file())
    creds = cred_broker.list_credentials(env_id)
    return {
        **environment_status(env_id),
        "workspace_path": str(workspace),
        "workspace_files": workspace_files,
        "caches_path": str(caches_dir(env_id)),
        "browser_profile_path": str(browser_profile_dir(env_id)),
        "logs_path": str(logs_dir(env_id)),
        "log_files": log_files,
        "processes": list(state.get("processes") or []),
        "task_state": dict(state.get("task_state") or {}),
        "credentials": creds,
    }


def _touch_active(env_id: str) -> None:
    _update_env(env_id, last_active_at=_utcnow())


def start_environment(env_id: str) -> dict[str, Any]:
    with _lock:
        env = _get_env(env_id)
        if env.status == STATUS_RUNNING:
            _touch_active(env_id)
            return environment_status(env_id)
        if env.status not in {STATUS_CREATED, STATUS_SUSPENDED}:
            raise EnvironmentError(f"Cannot start environment in status {env.status!r}")
        violations = check_quota_violations(env)
        if violations:
            raise EnvironmentError("Quota exceeded: " + ", ".join(sorted(violations)))
        _ensure_layout(env_id)
        _update_env(env_id, status=STATUS_RUNNING, last_active_at=_utcnow(), suspended_at=None)
    audit_log("environment.started", environment_id=env_id)
    return environment_status(env_id)


def suspend_environment(env_id: str) -> dict[str, Any]:
    with _lock:
        env = _get_env(env_id)
        if env.status == STATUS_SUSPENDED:
            return environment_status(env_id)
        if env.status != STATUS_RUNNING:
            raise EnvironmentError(f"Cannot suspend environment in status {env.status!r}")
        now = _utcnow()
        _update_env(env_id, status=STATUS_SUSPENDED, suspended_at=now, last_active_at=now)
    audit_log("environment.suspended", environment_id=env_id)
    return environment_status(env_id)


def resume_environment(env_id: str) -> dict[str, Any]:
    with _lock:
        env = _get_env(env_id)
        if env.status == STATUS_RUNNING:
            _touch_active(env_id)
            return environment_status(env_id)
        if env.status != STATUS_SUSPENDED:
            raise EnvironmentError(f"Cannot resume environment in status {env.status!r}")
        violations = check_quota_violations(env)
        if violations:
            raise EnvironmentError("Quota exceeded: " + ", ".join(sorted(violations)))
        _update_env(env_id, status=STATUS_RUNNING, last_active_at=_utcnow(), suspended_at=None)
    audit_log("environment.resumed", environment_id=env_id)
    return environment_status(env_id)


def _wipe_runtime_dirs(env_id: str) -> None:
    for resolver in (workspace_dir, caches_dir, browser_profile_dir, logs_dir):
        path = resolver(env_id)
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    _save_state(env_id, {"processes": [], "task_state": {}})


def reset_environment(env_id: str) -> dict[str, Any]:
    with _lock:
        env = _get_env(env_id)
        was_running = env.status == STATUS_RUNNING
        _wipe_runtime_dirs(env_id)
        _update_env(
            env_id,
            status=STATUS_RUNNING if was_running else STATUS_CREATED,
            last_active_at=_utcnow(),
            suspended_at=None,
        )
    audit_log("environment.reset", environment_id=env_id)
    return environment_status(env_id)


def delete_environment(env_id: str) -> dict[str, Any]:
    with _lock:
        items = _load_registry()
        env: WorkerEnvironment | None = None
        remaining: list[WorkerEnvironment] = []
        for item in items:
            if item.id == env_id:
                env = item
            else:
                remaining.append(item)
        if env is None:
            raise EnvironmentNotFound(f"Environment not found: {env_id}")
        _save_registry(remaining)
        root = _env_root(env_id)
        if root.exists():
            shutil.rmtree(root)
        cred_broker.delete_credentials_for_environment(env_id)
    audit_log("environment.deleted", environment_id=env_id, details={"name": env.name})
    return {"deleted": True, "id": env_id, "name": env.name}


def write_workspace_file(env_id: str, relative_path: str, content: str) -> Path:
    relative = Path(str(relative_path or "").replace("\\", "/").lstrip("/"))
    if ".." in relative.parts:
        raise EnvironmentError("Path traversal is not allowed")
    dest = workspace_dir(env_id) / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    _touch_active(env_id)
    return dest


def update_task_state(env_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        _get_env(env_id)
        state = _load_state(env_id)
        task_state = dict(state.get("task_state") or {})
        task_state.update(patch)
        state["task_state"] = task_state
        _save_state(env_id, state)
        _touch_active(env_id)
    return task_state


def store_environment_credential(
    env_id: str,
    *,
    capability: str,
    label: str,
    secret: str,
    credential_id: str | None = None,
) -> dict[str, Any]:
    _get_env(env_id)
    cred = cred_broker.store_credential(
        env_id,
        capability=capability,
        label=label,
        secret=secret,
        credential_id=credential_id,
    )
    audit_log(
        "credential.stored",
        environment_id=env_id,
        credential_id=cred["id"],
        details={"capability": capability, "label": label},
    )
    return cred


def revoke_environment_credential(env_id: str, credential_id: str) -> dict[str, Any]:
    _get_env(env_id)
    cred = cred_broker.revoke_credential(env_id, credential_id)
    audit_log(
        "credential.revoked",
        environment_id=env_id,
        credential_id=credential_id,
        details={"capability": cred.get("capability"), "label": cred.get("label")},
    )
    return cred
