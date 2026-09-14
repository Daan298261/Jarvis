"""Owner-scoped defensive HexStrike actions for RFC-0086.

This module intentionally exposes a small, typed action catalog instead of
forwarding arbitrary upstream paths, flags, commands, or MCP tools.
"""
from __future__ import annotations

import ipaddress
import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..config import data_dir, default_allowed_directories, load_settings
from .hexstrike import HEXSTRIKE, audit_hexstrike

_SCOPE_FILE = "hexstrike-scopes.json"
_JOB_FILE = "hexstrike-jobs.json"
_LOCK = threading.RLock()
_CONTAINER_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(?::[a-zA-Z0-9._-]+|@sha256:[a-f0-9]{64})?$")
_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)

SCOPE_KINDS = frozenset({"private_host", "private_cidr", "local_path", "container_image", "local_infrastructure"})


@dataclass(frozen=True)
class DefensiveCapability:
    id: str
    title: str
    scope_kinds: tuple[str, ...]
    permission: str
    upstream_path: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


CAPABILITIES: tuple[DefensiveCapability, ...] = (
    DefensiveCapability("lan_inventory", "Private LAN inventory", ("private_host", "private_cidr"), "blue.active_response", "api/tools/nmap"),
    DefensiveCapability("container_scan", "Container vulnerability scan", ("container_image", "local_path"), "blue.static_rules", "api/tools/trivy"),
    DefensiveCapability("iac_scan", "Infrastructure-as-code scan", ("local_path",), "blue.static_rules", "api/tools/checkov"),
    DefensiveCapability("host_baseline", "Local host benchmark", ("local_infrastructure",), "blue.static_rules", "api/tools/docker-bench-security"),
    DefensiveCapability("forensic_inspection", "Local forensic metadata", ("local_path",), "blue.static_rules", "api/tools/exiftool"),
    DefensiveCapability("threat_intel_lookup", "CVE intelligence lookup", ("local_infrastructure",), "blue.static_rules", "jarvis/nvd-cve"),
)
CAPABILITY_BY_ID = {item.id: item for item in CAPABILITIES}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(name: str) -> Path:
    target = data_dir() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _read(name: str, key: str) -> list[dict[str, Any]]:
    path = _path(name)
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = value.get(key, []) if isinstance(value, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _write(name: str, key: str, rows: list[dict[str, Any]]) -> None:
    path = _path(name)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps({"version": 1, key: rows}, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _private_network(value: str, *, host: bool) -> str:
    try:
        parsed = ipaddress.ip_address(value) if host else ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError("scope must be a literal private IP address or CIDR") from exc
    if not (parsed.is_private or parsed.is_loopback or parsed.is_link_local):
        raise ValueError("public network targets are not allowed in the Blue release")
    return str(parsed)


def _local_path(value: str) -> str:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ValueError("local evidence paths must be absolute")
    resolved = candidate.resolve(strict=False)
    settings = load_settings()
    roots = settings.allowed_directories or default_allowed_directories()
    allowed = [Path(root).expanduser().resolve(strict=False) for root in roots]
    if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
        raise ValueError("local path is outside Jarvis allowed directories")
    if not re.fullmatch(r"[A-Za-z0-9_./:\\-]+", str(resolved)):
        raise ValueError("local path contains characters not safely supported by the pinned upstream interface")
    return str(resolved)


def normalize_scope(kind: str, value: str) -> str:
    normalized_kind = (kind or "").strip().lower()
    cleaned = (value or "").strip()
    if normalized_kind not in SCOPE_KINDS:
        raise ValueError(f"unsupported scope kind: {kind}")
    if normalized_kind == "private_host":
        return _private_network(cleaned, host=True)
    if normalized_kind == "private_cidr":
        return _private_network(cleaned, host=False)
    if normalized_kind == "local_path":
        return _local_path(cleaned)
    if normalized_kind == "container_image":
        if not _CONTAINER_RE.fullmatch(cleaned):
            raise ValueError("invalid container image reference")
        return cleaned
    if cleaned not in {"local", "localhost", "127.0.0.1"}:
        raise ValueError("local infrastructure scope must target this Jarvis host")
    return "local"


def list_scopes() -> list[dict[str, Any]]:
    with _LOCK:
        return _read(_SCOPE_FILE, "scopes")


def upsert_scope(scope_id: str, *, kind: str, value: str, label: str, attested_owned: bool) -> dict[str, Any]:
    if not attested_owned:
        raise PermissionError("the owner must attest that this scope is owned or authorized")
    ident = (scope_id or "").strip() or str(uuid.uuid4())
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", ident):
        raise ValueError("invalid scope id")
    normalized_kind = kind.strip().lower()
    normalized_value = normalize_scope(normalized_kind, value)
    now = _utcnow()
    with _LOCK:
        rows = _read(_SCOPE_FILE, "scopes")
        existing = next((row for row in rows if row.get("id") == ident), None)
        row = {
            "id": ident,
            "kind": normalized_kind,
            "value": normalized_value,
            "label": (label or ident).strip()[:120],
            "attested_owned": True,
            "enabled": True,
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
        }
        rows = [item for item in rows if item.get("id") != ident]
        rows.append(row)
        _write(_SCOPE_FILE, "scopes", rows)
    audit_hexstrike("scope_upserted", scope_id=ident, kind=normalized_kind)
    return row


def get_scope(scope_id: str) -> dict[str, Any]:
    scope = next((row for row in list_scopes() if row.get("id") == scope_id and row.get("enabled", True)), None)
    if scope is None:
        raise KeyError(scope_id)
    return scope


def list_jobs() -> list[dict[str, Any]]:
    with _LOCK:
        return _read(_JOB_FILE, "jobs")[-100:]


def _save_job(job: dict[str, Any]) -> None:
    with _LOCK:
        rows = [item for item in _read(_JOB_FILE, "jobs") if item.get("id") != job["id"]]
        rows.append(job)
        _write(_JOB_FILE, "jobs", rows[-100:])


def _payload(capability: DefensiveCapability, scope: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    value = str(scope["value"])
    if capability.id == "lan_inventory":
        return {"target": value, "scan_type": "-sn", "ports": "", "additional_args": "-T3", "use_recovery": False}
    if capability.id == "container_scan":
        return {"target": value, "scan_type": "fs" if scope.get("kind") == "local_path" else "image", "output_format": "json"}
    if capability.id == "iac_scan":
        return {"directory": value, "framework": "all", "output_format": "json"}
    if capability.id == "host_baseline":
        return {"output_file": ""}
    if capability.id == "forensic_inspection":
        return {"file_path": value, "output_format": "json"}
    cve = str(options.get("cve") or "").upper().strip()
    if not _CVE_RE.fullmatch(cve):
        raise ValueError("threat intelligence lookup requires a CVE identifier")
    return {"cve_id": cve}


async def _lookup_cve(cve_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        response = await client.get(
            "https://services.nvd.nist.gov/rest/json/cves/2.0",
            params={"cveId": cve_id},
        )
    if response.status_code >= 400:
        raise RuntimeError(f"NVD returned HTTP {response.status_code}")
    body = response.json()
    vulnerabilities = body.get("vulnerabilities", []) if isinstance(body, dict) else []
    if not vulnerabilities:
        raise ValueError(f"No NVD record found for {cve_id}")
    cve = vulnerabilities[0].get("cve", {}) if isinstance(vulnerabilities[0], dict) else {}
    return {"source": "NVD", "cve": cve}


async def execute_defensive(action: str, scope_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    capability = CAPABILITY_BY_ID.get((action or "").strip())
    if capability is None:
        audit_hexstrike("defensive_action_denied", capability=action, reason="unknown_action")
        raise ValueError("unknown defensive action")
    scope = get_scope(scope_id)
    if scope.get("kind") not in capability.scope_kinds:
        audit_hexstrike("defensive_action_denied", capability=action, scope_id=scope_id, reason="scope_kind")
        raise PermissionError("scope kind is not valid for this defensive action")
    payload = _payload(capability, scope, options or {})
    job = {
        "id": str(uuid.uuid4()),
        "action": capability.id,
        "scope_id": scope_id,
        "status": "running",
        "started_at": _utcnow(),
        "finished_at": None,
        "upstream_pid": None,
        "result": {},
        "error": "",
    }
    _save_job(job)
    audit_hexstrike("defensive_action_started", job_id=job["id"], capability=capability.id, scope_id=scope_id)
    try:
        if capability.id == "threat_intel_lookup":
            result = await _lookup_cve(str(payload["cve_id"]))
        else:
            result = await HEXSTRIKE.post_defensive(capability.upstream_path, payload)
        if isinstance(result, dict):
            raw_pid = result.get("pid") or result.get("process_id")
            if isinstance(raw_pid, int):
                job["upstream_pid"] = raw_pid
        job["result"] = result if isinstance(result, dict) else {"value": result}
        job["status"] = "completed"
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)[:400]
        raise
    finally:
        job["finished_at"] = _utcnow()
        _save_job(job)
        audit_hexstrike("defensive_action_finished", job_id=job["id"], status=job["status"])
    return job


async def stop_managed_job(job_id: str) -> dict[str, Any]:
    job = next((item for item in list_jobs() if item.get("id") == job_id), None)
    if job is None:
        audit_hexstrike("managed_stop_denied", job_id=job_id, reason="unknown_job")
        raise KeyError(job_id)
    pid = job.get("upstream_pid")
    if not isinstance(pid, int) or pid <= 0:
        audit_hexstrike("managed_stop_denied", job_id=job_id, reason="untracked_pid")
        raise PermissionError("only tracked running HexStrike jobs can be stopped")
    result = await HEXSTRIKE.post_defensive(f"api/processes/terminate/{pid}", {})
    job["status"] = "stopped"
    job["finished_at"] = _utcnow()
    job["result"] = result if isinstance(result, dict) else {"value": result}
    _save_job(job)
    audit_hexstrike("managed_job_stopped", job_id=job_id, pid=pid)
    return job


def capability_snapshot() -> list[dict[str, Any]]:
    return [item.as_dict() for item in CAPABILITIES]
