"""HexStrike full operator catalog, jobs, and invoke path (RFC-0106)."""
from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir, default_allowed_directories, load_settings
from ..tools.mcp_runtime import MCP
from .hexstrike import HEXSTRIKE, audit_hexstrike
from .hexstrike_compat import ALWAYS_STUBBED_OPTIONALS, DISABLED_MESSAGE, package_is_stubbed
from .hexstrike_defensive import CAPABILITIES, CAPABILITY_BY_ID, capability_snapshot
from .hexstrike_mcp import HEXSTRIKE_MCP_SERVER_NAME, mcp_registration_error, mcp_registration_status, register_hexstrike_mcp
from .hexstrike_tools import dependency_catalog_rows, missing_host_tools

# Defensive capability → host binary required for an honest "available" claim.
_DEFENSIVE_HOST_TOOLS: dict[str, str] = {
    "lan_inventory": "nmap",
    "container_scan": "trivy",
    "iac_scan": "checkov",
    "host_baseline": "docker",
    "forensic_inspection": "exiftool",
}

_UNAVAILABLE_STATUSES = frozenset(
    {
        "missing",
        "unavailable",
        "absent",
        "stub",
        "stubbed",
        "disabled",
        "error",
        "failed",
        "false",
        "no",
        "not_installed",
        "not-installed",
    }
)
_AVAILABLE_STATUSES = frozenset({"ok", "ready", "available", "installed", "true", "yes"})

_JOB_ID_RE = re.compile(r"^[a-f0-9-]{8,64}$", re.IGNORECASE)
_LOCK = threading.RLock()
_CATALOG_CACHE: list[dict[str, Any]] = []
_CATALOG_PATH_NAME = "hexstrike/catalog.json"


def _catalog_path() -> Path:
    path = data_dir() / _CATALOG_PATH_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _persist_catalog(rows: list[dict[str, Any]]) -> None:
    payload = {"version": 1, "refreshed_at": _utcnow(), "catalog": rows}
    target = _catalog_path()
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)


def _load_persisted_catalog() -> list[dict[str, Any]]:
    path = _catalog_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("catalog", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def catalog_is_stale() -> bool:
    return not _CATALOG_CACHE and not _load_persisted_catalog()


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
    from ..config import LOCAL_NETWORK_SCOPE
    from ..tools.safety import _is_unc_path, _private_lan_unc

    roots = settings.allowed_directories or default_allowed_directories()
    if LOCAL_NETWORK_SCOPE in roots and _is_unc_path(str(candidate)) and _private_lan_unc(str(candidate)):
        return True
    allowed = []
    for root in roots:
        if root == LOCAL_NETWORK_SCOPE:
            continue
        allowed.append(Path(root).expanduser().resolve(strict=False))
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


def _status_means_available(status: Any) -> bool:
    if isinstance(status, bool):
        return status
    if status is None:
        return False
    if isinstance(status, str):
        lowered = status.strip().lower()
        if lowered in _UNAVAILABLE_STATUSES:
            return False
        return lowered in _AVAILABLE_STATUSES
    return False


def _capabilities_from_health(tools: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(tools, dict):
        for key, status in tools.items():
            name = str(key).strip()
            if not name or name == "available":
                continue
            available = _status_means_available(status)
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
        # Bare name lists from upstream are not proof of readiness — mark unavailable
        # until a concrete status probe says otherwise.
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
                    "available": False,
                    "missing_dependencies": [name],
                    "guidance": "Upstream listed this tool without a readiness status; treating as unavailable.",
                    "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
                }
            )
    return rows


def _capabilities_from_mcp(*, suite_running: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prefix = f"mcp_{HEXSTRIKE_MCP_SERVER_NAME}_"
    alt_prefix = f"mcp_{HEXSTRIKE_MCP_SERVER_NAME}-stdio_"
    mcp_status = mcp_registration_status()
    mcp_live = suite_running and any(
        (not value.startswith("error:") and value != "disabled" and value != "0 tools")
        for value in mcp_status.values()
    )
    for key, spec in MCP._tools.items():
        if not (key.startswith(prefix) or key.startswith(alt_prefix)):
            continue
        tool = spec.get("tool") or {}
        name = str(tool.get("name") or key.split("_", 2)[-1])
        available = mcp_live and not package_is_stubbed(name)
        rows.append(
            {
                "id": f"mcp:{name}",
                "source": "mcp",
                "title": name,
                "mcp_tool_key": key,
                "available": available,
                "missing_dependencies": [] if available else ([name] if package_is_stubbed(name) else ["hexstrike-mcp"]),
                "guidance": "" if available else (
                    DISABLED_MESSAGE if package_is_stubbed(name) else "HexStrike MCP bridge is not live."
                ),
                "input_schema": tool.get("inputSchema")
                or {"type": "object", "properties": {}, "additionalProperties": True},
            }
        )
    return rows


def _capabilities_from_defensive(*, suite_running: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in CAPABILITIES:
        host_tool = _DEFENSIVE_HOST_TOOLS.get(item.id)
        missing: list[str] = []
        if host_tool and shutil.which(host_tool) is None:
            missing.append(host_tool)
        # threat_intel_lookup needs no local binary; still requires a live suite only for
        # other defensive actions that POST upstream — CVE lookup is Jarvis-side.
        needs_suite = item.id != "threat_intel_lookup"
        available = (not missing) and (suite_running or not needs_suite)
        if needs_suite and not suite_running:
            missing = missing or ["hexstrike-suite"]
        rows.append(
            {
                "id": f"defensive:{item.id}",
                "source": "defensive",
                "title": item.title,
                "defensive_action": item.id,
                "upstream_path": item.upstream_path,
                "available": available,
                "missing_dependencies": missing,
                "guidance": (
                    ""
                    if available
                    else (
                        f"Missing host tool `{host_tool}`."
                        if host_tool and host_tool in missing
                        else "HexStrike suite is not running."
                    )
                ),
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


def _apply_catalog_honesty(
    rows: list[dict[str, Any]],
    *,
    suite_running: bool,
    stubbed: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    """Force stubbed / missing / offline rows to unavailable — never running/available."""
    honest: list[dict[str, Any]] = []
    active_stubs = list(stubbed) or list(ALWAYS_STUBBED_OPTIONALS)
    for row in rows:
        item = dict(row)
        source = str(item.get("source") or "")
        ident = str(item.get("id") or "")
        title = str(item.get("title") or ident)
        missing = list(item.get("missing_dependencies") or [])
        available = bool(item.get("available"))

        if package_is_stubbed(ident, active_stubs) or package_is_stubbed(title, active_stubs):
            available = False
            for stub in active_stubs:
                if package_is_stubbed(ident, [stub]) or package_is_stubbed(title, [stub]):
                    if stub not in missing:
                        missing.append(stub)
            item["stub"] = True
            item["guidance"] = DISABLED_MESSAGE
            item["status"] = "unavailable"

        if source in {"http", "mcp"} and not suite_running:
            available = False
            if "hexstrike-suite" not in missing:
                missing.append("hexstrike-suite")
            item["guidance"] = item.get("guidance") or "HexStrike suite is not running."
            item["status"] = "unavailable"

        # Host binary honesty for http tool names that match known PATH commands.
        tool_name = ""
        if source == "http" and ident.startswith("http:"):
            tool_name = ident.split(":", 1)[1]
        if tool_name and shutil.which(tool_name) is None and tool_name.lower() in {
            "nmap",
            "trivy",
            "checkov",
            "docker",
            "exiftool",
            "git",
            "curl",
            "jq",
            "openssl",
            "wireshark",
        }:
            available = False
            if tool_name not in missing:
                missing.append(tool_name)
            item["guidance"] = item.get("guidance") or f"Host tool `{tool_name}` is not on PATH."
            item["status"] = "unavailable"

        if not available:
            item["available"] = False
            item["missing_dependencies"] = missing
            # Never leave a decorative "running"/"healthy" marker on unavailable rows.
            if str(item.get("status") or "").lower() in {"running", "healthy", "ok", "ready", "available"}:
                item["status"] = "unavailable"
        else:
            item["available"] = True
            item["missing_dependencies"] = missing
        honest.append(item)
    return honest


async def refresh_discovered_catalog(*, force: bool = False) -> list[dict[str, Any]]:
    global _CATALOG_CACHE
    snapshot = await HEXSTRIKE.status(enrich=True)
    suite_running = bool(snapshot.running)
    stubbed = list(getattr(snapshot, "optional_stubs", None) or ALWAYS_STUBBED_OPTIONALS)
    rows: list[dict[str, Any]] = []
    rows.extend(_capabilities_from_defensive(suite_running=suite_running))
    if suite_running:
        rows.extend(_capabilities_from_health(snapshot.tools if isinstance(snapshot.tools, dict) else None))
        if isinstance(snapshot.tools, dict) and snapshot.tools.get("available"):
            rows.extend(_capabilities_from_health(snapshot.tools.get("available")))
    rows.extend(_capabilities_from_mcp(suite_running=suite_running))
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
            dep_row = dep_by_command[command]
            # Dependency row availability wins when host probe says missing.
            if dep_row.get("available") is False:
                row = {
                    **row,
                    "available": False,
                    "missing_dependencies": [command],
                    "guidance": dep_row.get("guidance") or row.get("guidance") or f"Missing dependency `{command}`.",
                }
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
                "status": "unavailable",
                "input_schema": {"type": "object", "properties": {}},
            }
        )
    merged = _apply_catalog_honesty(merged, suite_running=suite_running, stubbed=stubbed)
    _CATALOG_CACHE = merged
    _persist_catalog(merged)
    audit_hexstrike(
        "catalog_refresh",
        count=len(merged),
        mcp=mcp_registration_status(),
        suite_running=suite_running,
        optional_stubs=stubbed,
    )
    return merged


async def sync_operator_surface(*, register_mcp: bool = True) -> dict[str, Any]:
    """Register MCP (when requested) and refresh catalog from the live loopback suite."""
    snapshot = await HEXSTRIKE.status(enrich=True)
    if not snapshot.running:
        return {
            "operator_ready": False,
            "reason": "suite_not_running",
            "catalog_count": len(discovered_catalog()),
            "mcp": {"ok": False, "error": "suite not running"},
            "discovery_ok": False,
            "discovery_error": "HexStrike suite is not running",
        }
    from pathlib import Path

    install = Path(snapshot.install_path)
    mcp_payload: dict[str, Any] = {"ok": False, "error": ""}
    if register_mcp:
        from ..licensing.entitlements import HEXSTRIKE_ACCESS_FULL, hexstrike_access_mode

        if hexstrike_access_mode() != HEXSTRIKE_ACCESS_FULL:
            register_mcp = False
            mcp_payload = {"ok": False, "error": "hexstrike module required for HexStrike MCP"}
        else:
            result = await register_hexstrike_mcp(
                install_path=install,
                python_executable=snapshot.python_executable,
                host=snapshot.host,
                port=snapshot.port,
            )
            mcp_payload = result.as_dict()
    try:
        catalog = await refresh_discovered_catalog(force=True)
    except Exception as exc:
        error = f"catalog discovery failed: {exc}"[:400]
        audit_hexstrike("catalog_refresh_failed", error=error)
        return {
            "operator_ready": False,
            "catalog_count": 0,
            "mcp": mcp_payload,
            "catalog_stale": True,
            "discovery_ok": False,
            "discovery_error": error,
        }
    mcp_ok = bool(mcp_payload.get("ok")) if register_mcp else True
    if register_mcp and not mcp_ok:
        mcp_payload["error"] = mcp_payload.get("error") or mcp_registration_error()
    discovery_error = ""
    if register_mcp and not mcp_ok:
        # Surface MCP handshake failure honestly; HTTP/host rows may still be usable.
        discovery_error = str(mcp_payload.get("error") or "HexStrike MCP handshake failed")
    if not catalog:
        discovery_error = discovery_error or (
            "HexStrike discovery returned an empty catalog while the suite is running"
        )
    # Operator ready when any discoverable rows exist; MCP is additive, not a hard ceiling.
    non_mcp = [row for row in catalog if row.get("source") != "mcp"]
    operator_ready = len(catalog) > 0 and (mcp_ok or len(non_mcp) > 0)
    return {
        "operator_ready": operator_ready,
        "catalog_count": len(catalog),
        "mcp": mcp_payload,
        "catalog_stale": False,
        "discovery_ok": not bool(discovery_error) or len(catalog) > 0,
        "discovery_error": discovery_error,
    }


def discovered_catalog() -> list[dict[str, Any]]:
    suite_running = bool(HEXSTRIKE.is_running)
    try:
        stubbed = list(HEXSTRIKE._base_status().optional_stubs or ALWAYS_STUBBED_OPTIONALS)
    except Exception:
        stubbed = list(ALWAYS_STUBBED_OPTIONALS)
    if _CATALOG_CACHE:
        return _apply_catalog_honesty(list(_CATALOG_CACHE), suite_running=suite_running, stubbed=stubbed)
    persisted = _load_persisted_catalog()
    if persisted:
        return _apply_catalog_honesty(list(persisted), suite_running=suite_running, stubbed=stubbed)
    return _apply_catalog_honesty(
        _capabilities_from_defensive(suite_running=suite_running),
        suite_running=suite_running,
        stubbed=stubbed,
    )


def catalog_snapshot() -> dict[str, Any]:
    from ..licensing.entitlements import (
        HEXSTRIKE_ACCESS_BLUE,
        HEXSTRIKE_ACCESS_FULL,
        HEXSTRIKE_ACCESS_LOCKED,
        hexstrike_access_mode,
        hexstrike_access_payload,
        hexstrike_denied_message,
    )

    catalog = discovered_catalog()
    mode = hexstrike_access_mode()
    discovery_error = ""
    discovery_ok = True
    if mode == HEXSTRIKE_ACCESS_LOCKED:
        catalog = []
        discovery_ok = False
        discovery_error = hexstrike_denied_message()
    elif mode == HEXSTRIKE_ACCESS_BLUE:
        catalog = [row for row in catalog if row.get("source") == "defensive"]
    else:
        mcp_err = mcp_registration_error()
        suite_running = bool(HEXSTRIKE.is_running)
        if suite_running and catalog_is_stale() and not catalog:
            discovery_error = "HexStrike catalog is stale; refresh discovery after suite start or dependency install"
            discovery_ok = False
        elif suite_running and mcp_err:
            # Surface MCP error without pretending empty-ok; keep rows if present.
            discovery_error = mcp_err
            discovery_ok = bool(catalog)
    payload = {
        "catalog": catalog,
        "count": len(catalog),
        "catalog_stale": False if mode != HEXSTRIKE_ACCESS_FULL else catalog_is_stale(),
        "missing_host_tools": missing_host_tools() if mode != HEXSTRIKE_ACCESS_LOCKED else [],
        "legacy_capabilities": capability_snapshot() if mode != HEXSTRIKE_ACCESS_LOCKED else [],
        "mcp": mcp_registration_status() if mode == HEXSTRIKE_ACCESS_FULL else {"ok": False, "error": ""},
        "mcp_error": mcp_registration_error() if mode == HEXSTRIKE_ACCESS_FULL else "",
        "optional_stubs": list(ALWAYS_STUBBED_OPTIONALS),
        "optional_extras_available": False,
        "stub_status": "unavailable",
        "discovery_ok": discovery_ok,
        "discovery_error": discovery_error,
        "truncated": False,
    }
    payload.update(hexstrike_access_payload())
    return payload


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


def _claimed_artifact_paths(result: Any) -> list[Path]:
    """Collect artifact paths declared by an upstream/tool result (never invent)."""
    paths: list[Path] = []
    if not isinstance(result, dict):
        return paths
    for key in ("artifact_paths", "artifacts", "files"):
        raw = result.get(key)
        if isinstance(raw, str) and raw.strip():
            paths.append(Path(raw))
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    paths.append(Path(item))
                elif isinstance(item, dict):
                    candidate = item.get("path") or item.get("file") or item.get("name")
                    if isinstance(candidate, str) and candidate.strip() and ("/" in candidate or "\\" in candidate):
                        paths.append(Path(candidate))
    single = result.get("artifact") or result.get("artifact_path") or result.get("output_path")
    if isinstance(single, str) and single.strip():
        paths.append(Path(single))
    return paths


def _verify_claimed_artifacts(job: dict[str, Any], result: Any) -> None:
    """Missing claimed artifact under allowed roots → failed (RFC-0196 §4.3)."""
    missing: list[str] = []
    allowed_missing_outside = False
    for path in _claimed_artifact_paths(result):
        if not artifact_path_allowed(path):
            # Outside Jarvis-owned roots — do not open; treat as failed claim.
            missing.append(str(path))
            allowed_missing_outside = True
            continue
        try:
            resolved = path.expanduser().resolve(strict=False)
        except OSError:
            missing.append(str(path))
            continue
        if not resolved.is_file():
            missing.append(str(path))
    if missing:
        job["status"] = "failed"
        prefix = "artifact path outside allowed roots" if allowed_missing_outside else "missing artifact"
        job["error"] = f"{prefix}: {', '.join(missing[:8])}"[:400]


async def operate(capability_id: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from ..licensing.entitlements import (
        HEXSTRIKE_ACCESS_FULL,
        HEXSTRIKE_ACCESS_LOCKED,
        HEXSTRIKE_OPERATOR_LICENSE_MESSAGE,
        hexstrike_access_mode,
        hexstrike_denied_message,
    )

    mode = hexstrike_access_mode()
    if mode == HEXSTRIKE_ACCESS_LOCKED:
        raise PermissionError(hexstrike_denied_message())
    if mode != HEXSTRIKE_ACCESS_FULL:
        raise PermissionError(HEXSTRIKE_OPERATOR_LICENSE_MESSAGE)
    capability = _resolve_capability(capability_id)
    source = str(capability.get("source") or "")
    if source == "dependency" or str(capability_id).startswith("dep:"):
        raise ValueError("dependency rows install via POST /api/hexstrike/tools/{id}/install, not operate")
    if capability.get("stub") or package_is_stubbed(str(capability_id)):
        audit_hexstrike("operate_denied", capability=capability_id, reason="optional_stub")
        raise RuntimeError(
            f"capability unavailable: optional stub ({DISABLED_MESSAGE})"
        )
    if capability.get("available") is False:
        missing = capability.get("missing_dependencies") or capability.get("guidance")
        raise RuntimeError(f"capability unavailable: {missing or capability_id}")
    live = await HEXSTRIKE.status(enrich=False)
    if not live.running and source in {"http", "mcp"}:
        raise RuntimeError("capability unavailable: HexStrike suite is not running")
    if (
        not live.running
        and source == "defensive"
        and str(capability.get("defensive_action")) != "threat_intel_lookup"
    ):
        raise RuntimeError("capability unavailable: HexStrike suite is not running")
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
        "daybreak_jobs_hint": f"Open Daybreak → Jobs for job {job_id}",
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
            legacy_status = str(legacy.get("status") or "succeeded")
            if legacy_status in {"completed", "ok", "success", "succeeded"}:
                job["status"] = "succeeded"
            elif legacy_status in {"failed", "error"}:
                job["status"] = "failed"
                job["error"] = str(legacy.get("error") or legacy.get("detail") or "defensive action failed")[:400]
            elif legacy_status in {"cancelled", "canceled", "stopped"}:
                job["status"] = "cancelled"
            else:
                job["status"] = "succeeded" if not legacy.get("error") else "failed"
                if job["status"] == "failed":
                    job["error"] = str(legacy.get("error") or legacy_status)[:400]
            job["upstream_pid"] = legacy.get("upstream_pid")
        elif source == "mcp":
            key = str(capability.get("mcp_tool_key") or "")
            tool_result = await MCP.call(key, args)
            payload = {"ok": tool_result.success, "output": tool_result.output, "error": tool_result.error}
            job["result"] = payload
            job["status"] = "succeeded" if tool_result.success else "failed"
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
                if result.get("error") or result.get("ok") is False:
                    job["status"] = "failed"
                    job["error"] = str(result.get("error") or result.get("message") or "upstream reported failure")[:400]
                else:
                    job["status"] = "succeeded"
            else:
                job["status"] = "succeeded"
        if job["status"] == "succeeded":
            _verify_claimed_artifacts(job, job.get("result"))
        result_path = job_directory(job_id) / "result.json"
        result_path.write_text(json.dumps(job["result"], indent=2, default=str) + "\n", encoding="utf-8")
        artifact_paths = [str(result_path)]
        for claimed in _claimed_artifact_paths(job.get("result")):
            try:
                resolved = claimed.expanduser().resolve(strict=False)
            except OSError:
                continue
            if resolved.is_file() and artifact_path_allowed(resolved):
                artifact_paths.append(str(resolved))
        job["artifact_paths"] = list(dict.fromkeys(artifact_paths))
        _append_job_log(job_id, f"operate finished status={job['status']}")
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)[:400]
        _append_job_log(job_id, f"operate failed: {job['error']}")
        # Persist failed job for Daybreak Jobs / chat — do not soft-omit the job id.
        job["finished_at"] = _utcnow()
        job["log_tail"] = _tail_job_log(job_id)
        _save_job(job)
        audit_hexstrike("operate_finished", job_id=job_id, status=job["status"])
        return job
    finally:
        if job.get("finished_at") is None:
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
    job["status"] = "cancelled"
    job["finished_at"] = _utcnow()
    job["result"] = result if isinstance(result, dict) else {"value": result}
    job["log_tail"] = _tail_job_log(job_id)
    _save_job(job)
    audit_hexstrike("operator_job_stopped", job_id=job_id, pid=pid)
    return job


def operator_status_extras() -> dict[str, Any]:
    snap = catalog_snapshot()
    base = HEXSTRIKE._base_status()
    return {
        "catalog": snap.get("catalog") or [],
        "catalog_count": snap.get("count") or 0,
        "catalog_stale": snap.get("catalog_stale"),
        "jobs": list_operator_jobs(),
        "mcp": snap.get("mcp") or {},
        "mcp_error": snap.get("mcp_error") or "",
        "missing_host_tools": snap.get("missing_host_tools") or [],
        "optional_stubs": list(base.optional_stubs or ALWAYS_STUBBED_OPTIONALS),
        "stub_status": base.stub_status or "unavailable",
        "stub_message": base.stub_message or DISABLED_MESSAGE,
        "optional_extras_available": False,
        "discovery_ok": snap.get("discovery_ok", True),
        "discovery_error": snap.get("discovery_error") or "",
        "truncated": False,
    }
