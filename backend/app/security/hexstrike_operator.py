"""HexStrike full operator catalog, jobs, and invoke path (RFC-0106)."""
from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir, default_allowed_directories, load_settings
from ..tools.mcp_runtime import MCP
from .hexstrike import HEXSTRIKE, audit_hexstrike
from .hexstrike_defensive import CAPABILITIES, CAPABILITY_BY_ID, capability_snapshot
from .hexstrike_mcp import HEXSTRIKE_MCP_SERVER_NAME, mcp_registration_status
from .hexstrike_tools import dependency_catalog_rows, missing_host_tools

_JOB_ID_RE = re.compile(r"^[a-f0-9-]{8,64}$", re.IGNORECASE)
_LOCK = threading.RLock()
_CATALOG_CACHE: list[dict[str, Any]] = []


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def jobs_root() -> Path:
    path = data_dir() / "hexstrike" / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_directory(job_id: str) -> Path:
    ident = (job_id or "").strip()
    if not _JOB_ID_RE.fullmatch(ident):
        raise ValueError("invalid job id")
    path = jobs_root() / ident
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifact_path_allowed(candidate: Path) -> bool:
    try:
        resolved = candidate.expanduser().resolve(strict=False)
    except OSError:
        return False
    job_root = jobs_root().resolve(strict=False)
    if resolved == job_root or resolved.is_relative_to(job_root):
        return True
    settings = load_settings()
    roots = settings.allowed_directories or default_allowed_directories()
    allowed = [Path(root).expanduser().resolve(strict=False) for root in roots]
    return any(resolved == root or resolved.is_relative_to(root) for root in allowed)


def _read_jobs_index() -> list[dict[str, Any]]:
    index = jobs_root() / "index.json"
    if not index.is_file():
        return []
    try:
        payload = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("jobs", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _write_jobs_index(rows: list[dict[str, Any]]) -> None:
    index = jobs_root() / "index.json"
    temp = index.with_suffix(".tmp")
    temp.write_text(json.dumps({"version": 1, "jobs": rows[-200:]}, indent=2) + "\n", encoding="utf-8")
    temp.replace(index)


def list_operator_jobs() -> list[dict[str, Any]]:
    with _LOCK:
        return _read_jobs_index()[-100:]


def get_operator_job(job_id: str) -> dict[str, Any]:
    job = next((item for item in list_operator_jobs() if item.get("id") == job_id), None)
    if job is None:
        raise KeyError(job_id)
    return job


def _save_job(job: dict[str, Any]) -> None:
    with _LOCK:
        rows = [item for item in _read_jobs_index() if item.get("id") != job["id"]]
        rows.append(job)
        _write_jobs_index(rows)


def _append_job_log(job_id: str, line: str) -> None:
    log_file = job_directory(job_id) / "job.log"
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def _tail_job_log(job_id: str, *, limit: int = 4000) -> str:
    log_file = job_directory(job_id) / "job.log"
    if not log_file.is_file():
        return ""
    text = log_file.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def list_job_artifacts(job_id: str) -> list[dict[str, Any]]:
    directory = job_directory(job_id)
    artifacts: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if path.name in {"job.log", "result.json"}:
            continue
        if not path.is_file():
            continue
        if not artifact_path_allowed(path):
            continue
        artifacts.append({"name": path.name, "path": str(path), "size": path.stat().st_size})
    return artifacts


def _http_tool_path(tool_name: str) -> str:
    cleaned = (tool_name or "").strip().strip("/")
    if not cleaned or any(part in {".", ".."} for part in cleaned.split("/")):
        raise ValueError("invalid tool name")
    return f"api/tools/{cleaned}"


def _capabilities_from_health(tools: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(tools, dict):
        for key, status in tools.items():
            name = str(key).strip()
            if not name:
                continue
            available = status not in {False, "missing", "unavailable", "absent"}
            if isinstance(status, str):
                available = status.lower() in {"ok", "ready", "available", "installed", "true", "yes"}
            rows.append(
                {
                    "id": f"http:{name}",
                    "source": "http",
                    "title": name.replace("_", " ").replace("-", " ").title(),
                    "upstream_path": _http_tool_path(name),
                    "available": available,
                    "missing_dependencies": [] if available else [name],
                    "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
                }
            )
    elif isinstance(tools, list):
        for item in tools:
            name = str(item).strip()
            if not name:
                continue
            rows.append(
                {
                    "id": f"http:{name}",
                    "source": "http",
                    "title": name,
                    "upstream_path": _http_tool_path(name),
                    "available": True,
                    "missing_dependencies": [],
                    "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
                }
            )
    return rows


def _capabilities_from_mcp() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prefix = f"mcp_{HEXSTRIKE_MCP_SERVER_NAME}_"
    alt_prefix = f"mcp_{HEXSTRIKE_MCP_SERVER_NAME}-stdio_"
    for key, spec in MCP._tools.items():
        if not (key.startswith(prefix) or key.startswith(alt_prefix)):
            continue
        tool = spec.get("tool") or {}
        name = str(tool.get("name") or key.split("_", 2)[-1])
        rows.append(
            {
                "id": f"mcp:{name}",
                "source": "mcp",
                "title": name,
                "mcp_tool_key": key,
                "available": True,
                "missing_dependencies": [],
                "input_schema": tool.get("inputSchema")
                or {"type": "object", "properties": {}, "additionalProperties": True},
            }
        )
    return rows


def _capabilities_from_defensive() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in CAPABILITIES:
        rows.append(
            {
                "id": f"defensive:{item.id}",
                "source": "defensive",
                "title": item.title,
                "defensive_action": item.id,
                "upstream_path": item.upstream_path,
                "available": True,
                "missing_dependencies": [],
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "scope_id": {"type": "string"},
                        "options": {"type": "object"},
                    },
                    "required": ["scope_id"],
                },
            }
        )
    return rows


async def refresh_discovered_catalog(*, force: bool = False) -> list[dict[str, Any]]:
    global _CATALOG_CACHE
    snapshot = await HEXSTRIKE.status(enrich=True)
    rows: list[dict[str, Any]] = []
    rows.extend(_capabilities_from_defensive())
    rows.extend(_capabilities_from_health(snapshot.tools if isinstance(snapshot.tools, dict) else None))
    if isinstance(snapshot.tools, dict) and snapshot.tools.get("available"):
        rows.extend(_capabilities_from_health(snapshot.tools.get("available")))
    rows.extend(_capabilities_from_mcp())
    deps = dependency_catalog_rows(snapshot.install_path)
    dep_by_command = {item["command"]: item for item in deps}
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for row in rows:
        ident = str(row.get("id") or "")
        if not ident or ident in seen:
            continue
        seen.add(ident)
        command = row.get("missing_dependencies", [None])[0] if row.get("missing_dependencies") else None
        if isinstance(command, str) and command in dep_by_command:
            row = {**row, **dep_by_command[command]}
        merged.append(row)
    for dep in deps:
        if dep.get("available"):
            continue
        ident = f"dep:{dep['id']}"
        if ident in seen:
            continue
        seen.add(ident)
        merged.append(
            {
                "id": ident,
                "source": "dependency",
                "title": dep.get("label") or dep["id"],
                "available": False,
                "missing_dependencies": [dep["command"]],
                "install_id": dep["id"],
                "install_method": dep.get("method"),
                "input_schema": {"type": "object", "properties": {}},
            }
        )
    _CATALOG_CACHE = merged
    audit_hexstrike("catalog_refresh", count=len(merged), mcp=mcp_registration_status())
    return merged if force or merged else list(_CATALOG_CACHE)


def discovered_catalog() -> list[dict[str, Any]]:
    if _CATALOG_CACHE:
        return list(_CATALOG_CACHE)
    return [item for item in _capabilities_from_defensive()]


def catalog_snapshot() -> dict[str, Any]:
    catalog = discovered_catalog()
    return {
        "catalog": catalog,
        "count": len(catalog),
        "missing_host_tools": missing_host_tools(),
        "legacy_capabilities": capability_snapshot(),
        "mcp": mcp_registration_status(),
    }


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be a JSON object")
    if schema.get("type") == "object" and schema.get("additionalProperties") is False:
        extras = set(arguments) - set((schema.get("properties") or {}).keys())
        if extras:
            raise ValueError(f"unexpected argument fields: {', '.join(sorted(extras))}")


def _resolve_capability(capability_id: str) -> dict[str, Any]:
    ident = (capability_id or "").strip()
    match = next((item for item in discovered_catalog() if item.get("id") == ident), None)
    if match is None:
        audit_hexstrike("operate_denied", capability=ident, reason="unknown_capability")
        raise ValueError("unknown capability id")
    return match


async def operate(capability_id: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    capability = _resolve_capability(capability_id)
    args = arguments or {}
    schema = capability.get("input_schema") or {"type": "object"}
    _validate_arguments(schema if isinstance(schema, dict) else {"type": "object"}, args)
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "capability_id": capability_id,
        "source": capability.get("source"),
        "status": "running",
        "started_at": _utcnow(),
        "finished_at": None,
        "upstream_pid": None,
        "jarvis_pid": None,
        "log_tail": "",
        "artifact_paths": [],
        "result": {},
        "error": "",
    }
    _save_job(job)
    _append_job_log(job_id, f"operate start capability={capability_id}")
    audit_hexstrike("operate_started", job_id=job_id, capability=capability_id)
    try:
        source = str(capability.get("source") or "")
        if source == "defensive":
            from .hexstrike_defensive import execute_defensive

            action = str(capability.get("defensive_action") or "")
            scope_id = str(args.get("scope_id") or "")
            options = args.get("options") if isinstance(args.get("options"), dict) else {}
            legacy = await execute_defensive(action, scope_id, options)
            job["result"] = legacy
            job["status"] = legacy.get("status", "completed")
            job["upstream_pid"] = legacy.get("upstream_pid")
        elif source == "mcp":
            key = str(capability.get("mcp_tool_key") or "")
            tool_result = await MCP.call(key, args)
            payload = {"ok": tool_result.success, "output": tool_result.output, "error": tool_result.error}
            job["result"] = payload
            job["status"] = "completed" if tool_result.success else "failed"
            if not tool_result.success:
                job["error"] = tool_result.error or "MCP tool failed"
        else:
            path = str(capability.get("upstream_path") or "")
            result = await HEXSTRIKE.post_operator(path, args)
            job["result"] = result if isinstance(result, dict) else {"value": result}
            if isinstance(result, dict):
                raw_pid = result.get("pid") or result.get("process_id")
                if isinstance(raw_pid, int):
                    job["upstream_pid"] = raw_pid
            job["status"] = "completed"
        result_path = job_directory(job_id) / "result.json"
        result_path.write_text(json.dumps(job["result"], indent=2, default=str) + "\n", encoding="utf-8")
        job["artifact_paths"] = [str(result_path)]
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)[:400]
        _append_job_log(job_id, f"operate failed: {job['error']}")
        raise
    finally:
        job["finished_at"] = _utcnow()
        job["log_tail"] = _tail_job_log(job_id)
        _save_job(job)
        audit_hexstrike("operate_finished", job_id=job_id, status=job["status"])
    return job


async def stop_operator_job(job_id: str) -> dict[str, Any]:
    job = get_operator_job(job_id)
    pid = job.get("upstream_pid")
    if not isinstance(pid, int) or pid <= 0:
        audit_hexstrike("operator_stop_denied", job_id=job_id, reason="untracked_pid")
        raise PermissionError("only Jarvis-tracked HexStrike jobs can be stopped")
    result = await HEXSTRIKE.post_operator(f"api/processes/terminate/{pid}", {})
    job["status"] = "stopped"
    job["finished_at"] = _utcnow()
    job["result"] = result if isinstance(result, dict) else {"value": result}
    job["log_tail"] = _tail_job_log(job_id)
    _save_job(job)
    audit_hexstrike("operator_job_stopped", job_id=job_id, pid=pid)
    return job


def operator_status_extras() -> dict[str, Any]:
    return {
        "catalog": discovered_catalog(),
        "catalog_count": len(discovered_catalog()),
        "jobs": list_operator_jobs(),
        "mcp": mcp_registration_status(),
        "missing_host_tools": missing_host_tools(),
    }
