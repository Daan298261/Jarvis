"""Owner-scoped defensive HexStrike actions for RFC-0086.

This module intentionally exposes a small, typed action catalog instead of
forwarding arbitrary upstream paths, flags, commands, or MCP tools.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import shutil
import socket
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir, live_allowed_directories, load_settings
from .hexstrike import HEXSTRIKE, audit_hexstrike

_SCOPE_FILE = "hexstrike-scopes.json"
_JOB_FILE = "hexstrike-jobs.json"
_LOCK = threading.RLock()
_CONTAINER_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(?::[a-zA-Z0-9._-]+|@sha256:[a-f0-9]{64})?$")
_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)

SCOPE_KINDS = frozenset({"private_host", "private_cidr", "local_path", "container_image", "local_infrastructure"})
DEFAULT_LAN_SCOPE_ID = "lan"
_RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


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
    DefensiveCapability("lan_inventory", "Private LAN inventory", ("private_host", "private_cidr"), "network.local", "api/tools/nmap"),
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
    roots = live_allowed_directories(settings.allowed_directories)
    from ..config import LOCAL_NETWORK_SCOPE
    from ..tools.safety import _is_unc_path, _private_lan_unc

    if LOCAL_NETWORK_SCOPE in roots and _is_unc_path(value) and _private_lan_unc(value):
        from ..tools.safety import resolve_allowed_path

        return str(resolve_allowed_path(value, roots))
    allowed = [Path(root).expanduser().resolve(strict=False) for root in roots if root != LOCAL_NETWORK_SCOPE]
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
    # RFC-0197: keep owner-attested HexStrike scopes mirrored into the target registry.
    _mirror_scope_to_target_registry(row)
    return row


def _mirror_scope_to_target_registry(scope: dict[str, Any]) -> None:
    """Best-effort bridge from RFC-0086 scopes → RFC-0197 security-targets.json."""
    try:
        from . import security_audit as security_audit_mod
        from . import target_registry as tr
    except Exception:
        return
    kind_map = {
        "private_host": "ipv4",
        "private_cidr": "cidr",
        "local_path": "local_path",
        "container_image": "container_image",
        "local_infrastructure": "hostname",
    }
    scope_kind = str(scope.get("kind") or "")
    registry_kind = kind_map.get(scope_kind)
    if not registry_kind:
        return
    value = str(scope.get("value") or "")
    if scope_kind == "local_infrastructure":
        value = "localhost"
    if not value:
        return
    # Use this module's data_dir so test patches stay isolated.
    previous_tr = tr.data_dir
    previous_audit = security_audit_mod.data_dir
    tr.data_dir = data_dir
    security_audit_mod.data_dir = data_dir
    try:
        if tr.is_registered_value(value):
            return
        target_id = str(scope.get("id") or "")
        if target_id and any(str(row.get("id") or "") == target_id for row in tr.list_targets()):
            target_id = ""
        tr.add_target(
            kind=registry_kind,
            value=value,
            notes=str(scope.get("label") or "hexstrike-scope")[:240],
            target_id=target_id or None,
        )
    except Exception:
        # Registry normalization may reject some private_host forms; ignore bridge failures.
        return
    finally:
        tr.data_dir = previous_tr
        security_audit_mod.data_dir = previous_audit


def get_scope(scope_id: str) -> dict[str, Any]:
    scope = next((row for row in list_scopes() if row.get("id") == scope_id and row.get("enabled", True)), None)
    if scope is None:
        raise KeyError(scope_id)
    return scope


def preferred_lan_cidrs() -> list[str]:
    """RFC1918 interface CIDRs with the default-gateway subnet first (home LAN before VPN)."""
    cidrs = discover_private_lan_cidrs()
    if not cidrs:
        return []
    gw = ""
    try:
        from ..mobile.wan_forward import default_gateway_ipv4

        gw = default_gateway_ipv4()
    except Exception:
        gw = ""
    try:
        gateway = ipaddress.ip_address((gw or "").strip())
    except ValueError:
        return list(cidrs)
    preferred: list[str] = []
    rest: list[str] = []
    for cidr in cidrs:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue
        if gateway in network:
            preferred.append(cidr)
        else:
            rest.append(cidr)
    return preferred + rest


def extra_lan_scope_id(cidr: str) -> str:
    return "lan-" + str(cidr).replace(".", "-").replace("/", "-")


def _upsert_additional_lan_scopes(cidrs: list[str]) -> None:
    for cidr in cidrs:
        ident = extra_lan_scope_id(cidr)
        if ident == DEFAULT_LAN_SCOPE_ID:
            continue
        upsert_scope(
            ident,
            kind="private_cidr",
            value=cidr,
            label=f"This PC's LAN {cidr}",
            attested_owned=True,
        )


def rfc1918_nic_addrs() -> list[tuple[str, ipaddress.IPv4Interface]]:
    """(interface name, IPv4Interface) for every RFC1918 NIC this PC currently holds."""
    try:
        import psutil
    except ImportError:
        return []
    found: list[tuple[str, ipaddress.IPv4Interface]] = []
    try:
        nics = psutil.net_if_addrs().items()
    except Exception:
        return []
    for name, addrs in nics:
        for addr in addrs:
            if getattr(addr, "family", None) != socket.AF_INET:
                continue
            ip_text = (getattr(addr, "address", None) or "").split("%", 1)[0]
            mask = getattr(addr, "netmask", None) or "255.255.255.0"
            try:
                interface = ipaddress.IPv4Interface(f"{ip_text}/{mask}")
            except ValueError:
                continue
            if not any(interface.ip in net for net in _RFC1918):
                continue
            if interface.network.prefixlen < 8 or interface.network.prefixlen > 30:
                continue
            found.append((str(name or ""), interface))
    return found


def discover_private_lan_cidrs() -> list[str]:
    """RFC1918 CIDRs from this PC's interfaces — owner LAN only, never CGNAT or public."""
    found: list[str] = []
    seen: set[str] = set()
    for _name, interface in rfc1918_nic_addrs():
        cidr = str(interface.network)
        if cidr in seen:
            continue
        seen.add(cidr)
        found.append(cidr)
    return found


def lan_scan_bind(target: str) -> tuple[str, str]:
    """This PC's (interface name, IPv4) on the same RFC1918 network as *target*.

    LAN inventory must send from that NIC. A VPN default route would otherwise
    make nmap probe the tunnel instead of the owner's LAN.
    """
    cleaned = (target or "").strip()
    if not cleaned:
        return ("", "")
    try:
        if "/" in cleaned:
            needle: ipaddress.IPv4Address | ipaddress.IPv4Network = ipaddress.ip_network(
                cleaned, strict=False
            )
            host_mode = False
        else:
            needle = ipaddress.ip_address(cleaned)
            host_mode = True
    except ValueError:
        return ("", "")
    if getattr(needle, "version", 4) != 4:
        return ("", "")
    matches: list[tuple[int, str, str]] = []
    for name, interface in rfc1918_nic_addrs():
        if host_mode:
            if needle not in interface.network and needle != interface.ip:
                continue
        elif interface.ip not in needle and not needle.overlaps(interface.network):
            continue
        matches.append((interface.network.prefixlen, name, str(interface.ip)))
    if not matches:
        return ("", "")
    matches.sort(key=lambda item: (-item[0], item[1], item[2]))
    return (matches[0][1], matches[0][2])


def nmap_lan_bind_args(target: str) -> list[str]:
    """nmap argv that pins the scan to the on-link RFC1918 NIC for *target*."""
    iface, source = lan_scan_bind(target)
    args: list[str] = []
    if source:
        args.extend(["-S", source])
    if iface:
        args.extend(["-e", iface])
    return args


def nmap_lan_additional_args(target: str, base: str = "-T3") -> str:
    """HexStrike nmap additional_args: timing plus source bind.

    Interface names with whitespace are omitted from the string payload (HexStrike
    splits additional_args); ``-S`` still pins the source address.
    """
    iface, source = lan_scan_bind(target)
    parts = [str(base or "").strip()]
    if source:
        parts.extend(["-S", source])
    if iface and not any(ch.isspace() for ch in iface):
        parts.extend(["-e", iface])
    return " ".join(part for part in parts if part)


def ensure_default_lan_scope() -> dict[str, Any]:
    existing = next(
        (
            row
            for row in list_scopes()
            if row.get("id") == DEFAULT_LAN_SCOPE_ID and row.get("enabled", True)
        ),
        None,
    )
    cidrs = preferred_lan_cidrs()
    if existing and existing.get("kind") in {"private_host", "private_cidr"}:
        value = str(existing.get("value") or "")
        kind = str(existing.get("kind") or "")
        try:
            normalize_scope(kind, value)
        except ValueError:
            existing = None
        else:
            if kind == "private_cidr" and (not cidrs or value != cidrs[0]):
                existing = None
            elif existing is not None:
                _upsert_additional_lan_scopes(cidrs[1:])
                return existing
    if not cidrs:
        raise ValueError("No RFC1918 interface found; register a private LAN scope first")
    row = upsert_scope(
        DEFAULT_LAN_SCOPE_ID,
        kind="private_cidr",
        value=cidrs[0],
        label="This PC's LAN",
        attested_owned=True,
    )
    _upsert_additional_lan_scopes(cidrs[1:])
    return row


def resolve_lan_inventory_scope(scope_id: str) -> str:
    ident = (scope_id or "").strip()
    if not ident or ident in {"default", "local"}:
        return str(ensure_default_lan_scope()["id"])
    try:
        get_scope(ident)
        return ident
    except KeyError:
        if ident == DEFAULT_LAN_SCOPE_ID:
            return str(ensure_default_lan_scope()["id"])
        raise


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
        return {
            "target": value,
            "scan_type": "-sn",
            "ports": "",
            "additional_args": nmap_lan_additional_args(value),
            "use_recovery": False,
        }
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
    from ..policy.network_http import gated_get

    response = await gated_get(
        "https://services.nvd.nist.gov/rest/json/cves/2.0",
        tool="web_fetch",
        timeout=30.0,
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


def parse_nmap_ping_hosts(text: str) -> list[dict[str, str]]:
    hosts: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        if not line.startswith("Nmap scan report for "):
            continue
        rest = line[len("Nmap scan report for ") :].strip()
        hostname = ""
        address = rest
        if rest.endswith(")") and " (" in rest:
            hostname, ip_part = rest.rsplit(" (", 1)
            address = ip_part.rstrip(")")
        hosts.append({"address": address, "hostname": hostname})
    return hosts


def _require_private_lan_target(target: str) -> str:
    """Host nmap and suite nmap may only ping RFC1918 / loopback / link-local."""
    cleaned = (target or "").strip()
    if not cleaned:
        raise ValueError("LAN inventory target is required")
    if "/" in cleaned:
        return _private_network(cleaned, host=False)
    return _private_network(cleaned, host=True)


async def _host_nmap_ping_scan(target: str) -> dict[str, Any]:
    cleaned = _require_private_lan_target(target)
    binary = shutil.which("nmap")
    if not binary:
        raise RuntimeError(
            "HexStrike is not running and nmap is not on PATH. "
            "Install HexStrike or nmap to inventory the private LAN."
        )
    proc = await asyncio.create_subprocess_exec(
        binary,
        "-sn",
        "-T3",
        "--max-retries",
        "1",
        *nmap_lan_bind_args(cleaned),
        "--",
        cleaned,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError("host nmap ping scan timed out") from exc
    text = (stdout or b"").decode("utf-8", errors="replace")
    err = (stderr or b"").decode("utf-8", errors="replace")
    if proc.returncode not in {0, 1}:
        raise RuntimeError((err or text or "nmap failed").strip()[:400])
    return {
        "source": "host-nmap",
        "target": cleaned,
        "hosts": parse_nmap_ping_hosts(text),
        "stdout": text[:4000],
    }


def lan_inventory_targets(scope: dict[str, Any], payload: dict[str, Any] | None = None) -> list[str]:
    """Default `lan` inventory covers every live RFC1918 NIC CIDR, home subnet first."""
    primary = str((scope or {}).get("value") or (payload or {}).get("target") or "").strip()
    extras: list[str] = []
    if str((scope or {}).get("id") or "") == DEFAULT_LAN_SCOPE_ID:
        extras = preferred_lan_cidrs()
    ordered: list[str] = []
    for item in [primary, *extras]:
        if item and item not in ordered:
            ordered.append(item)
    return ordered


def _merge_lan_inventory_results(results: list[dict[str, Any]], targets: list[str]) -> dict[str, Any]:
    hosts: list[dict[str, str]] = []
    seen: set[str] = set()
    stdout_parts: list[str] = []
    source = ""
    for item in results:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or source)
        stdout_parts.append(str(item.get("stdout") or "")[:4000])
        for host in item.get("hosts") or []:
            if not isinstance(host, dict):
                continue
            address = str(host.get("address") or "")
            if not address or address in seen:
                continue
            seen.add(address)
            hosts.append({"address": address, "hostname": str(host.get("hostname") or "")})
    merged: dict[str, Any] = dict(results[0]) if len(results) == 1 and isinstance(results[0], dict) else {}
    merged.update(
        {
            "source": source or merged.get("source") or "host-nmap",
            "target": targets[0] if len(targets) == 1 else ",".join(targets),
            "targets": targets,
            "hosts": hosts if hosts or len(results) > 1 else list(merged.get("hosts") or hosts),
            "stdout": "\n".join(part for part in stdout_parts if part)[:4000] or merged.get("stdout") or "",
        }
    )
    return merged


async def _run_lan_inventory(scope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    targets = lan_inventory_targets(scope, payload)
    if not targets:
        raise ValueError("LAN inventory target is required")
    snapshot = await HEXSTRIKE.status(enrich=False)
    if not snapshot.running:
        snapshot = await HEXSTRIKE.ensure_started()
    results: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for target in targets:
        item_payload = {
            **payload,
            "target": target,
            "additional_args": nmap_lan_additional_args(target),
        }
        try:
            if snapshot.running:
                results.append(await HEXSTRIKE.post_defensive("api/tools/nmap", item_payload))
            else:
                results.append(await _host_nmap_ping_scan(target))
        except Exception as exc:
            last_error = exc
    if not results:
        if last_error is None:
            raise RuntimeError("LAN inventory failed")
        if snapshot.running:
            raise last_error
        suite_err = (snapshot.last_error or "HexStrike is not running").strip()
        raise RuntimeError(f"{suite_err} Host nmap fallback: {last_error}") from last_error
    return _merge_lan_inventory_results(results, targets)


async def execute_defensive(action: str, scope_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    capability = CAPABILITY_BY_ID.get((action or "").strip())
    if capability is None:
        audit_hexstrike("defensive_action_denied", capability=action, reason="unknown_action")
        raise ValueError("unknown defensive action")
    if capability.id == "lan_inventory":
        scope_id = resolve_lan_inventory_scope(scope_id)
    scope = get_scope(scope_id)
    try:
        scope = {
            **scope,
            "value": normalize_scope(str(scope.get("kind") or ""), str(scope.get("value") or "")),
        }
    except ValueError as exc:
        audit_hexstrike("defensive_action_denied", capability=action, scope_id=scope_id, reason="scope_not_private")
        raise PermissionError(str(exc)) from exc
    if scope.get("kind") not in capability.scope_kinds:
        audit_hexstrike("defensive_action_denied", capability=action, scope_id=scope_id, reason="scope_kind")
        raise PermissionError("scope kind is not valid for this defensive action")
    # RFC-0197: default-deny third-party / non-local scopes not in the owner registry.
    # local_infrastructure is this Jarvis host and does not need a registry row.
    from . import security_audit as security_audit_mod
    from . import target_registry as tr

    scope_kind = str(scope.get("kind") or "")
    scope_value = str(scope.get("value") or "")
    if scope_kind != "local_infrastructure" and scope_value:
        # Scopes written before RFC-0197 have no registry row; attested LAN
        # inventory must still run for the owner.
        _mirror_scope_to_target_registry(scope)
        previous_tr = tr.data_dir
        previous_audit = security_audit_mod.data_dir
        tr.data_dir = data_dir
        security_audit_mod.data_dir = data_dir
        try:
            tr.assert_value_allowed(
                scope_value,
                kind=None,
                capability_id=capability.id,
                source="hexstrike_defensive",
            )
        except tr.TargetDenied:
            audit_hexstrike(
                "defensive_action_denied",
                capability=action,
                scope_id=scope_id,
                reason="target_not_registered",
            )
            raise
        finally:
            tr.data_dir = previous_tr
            security_audit_mod.data_dir = previous_audit
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
        elif capability.id == "lan_inventory":
            result = await _run_lan_inventory(scope, payload)
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
