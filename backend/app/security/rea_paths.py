"""RFC-0200 REA investigation path policy (fail-closed, intersection with RFC-0079)."""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
from typing import Any

from ..config import LOCAL_NETWORK_SCOPE, default_allowed_directories, load_settings
from ..tools.safety import path_is_under_root, reject_unsafe_path_text, resolve_allowed_path
from .lta_archive import jobs_root, succeeded_lta_extract_root
from .lta_errors import PathDenied

REA_ROOTS_ENV = "REA_INVESTIGATION_INPUT_ROOTS_JSON"
PATH_NOT_ALLOWED = "path_not_allowed"

_DYNAMIC_REA_ENVS = (
    "REA_PROCESS_EXECUTABLE_ROOTS_JSON",
    "REA_PROCESS_WORKING_ROOTS_JSON",
    "REA_BROWSER_SCENARIO_EXECUTABLE_ROOTS_JSON",
)


class PathNotAllowed(Exception):
    """Honest fail-closed denial for REA investigation targets."""

    code = PATH_NOT_ALLOWED

    def __init__(self, message: str = "", *, detail: str = "") -> None:
        text = (message or self.code).strip()
        super().__init__(text)
        self.detail = (detail or "").strip()

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.code, "message": str(self)}
        if self.detail:
            payload["detail"] = self.detail
        return payload


def is_absolute_owner_path(raw: str) -> bool:
    text = str(raw or "").strip()
    if not text:
        return False
    if text.startswith(("/", "\\")):
        return True
    posix = Path(text)
    if posix.is_absolute():
        return True
    win = PureWindowsPath(text.replace("/", "\\"))
    return win.is_absolute() or text.startswith("\\\\")


def configured_investigation_roots() -> list[str]:
    """Owner investigation roots from env (wins if set) or settings. May be empty."""
    if REA_ROOTS_ENV in os.environ:
        raw = os.environ.get(REA_ROOTS_ENV) or ""
        try:
            payload = json.loads(raw) if raw.strip() else []
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        out: list[str] = []
        for item in payload:
            text = str(item or "").strip()
            if text:
                out.append(text)
        return out
    settings = load_settings()
    return [str(item).strip() for item in (settings.rea.investigation_roots or []) if str(item).strip()]


def jarvis_allowed_roots() -> list[str]:
    settings = load_settings()
    return list(settings.allowed_directories or default_allowed_directories())


def intersect_roots(candidates: list[str], allowed: list[str] | None = None) -> list[str]:
    allowed_roots = allowed if allowed is not None else jarvis_allowed_roots()
    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        text = str(raw or "").strip()
        if not text or text == LOCAL_NETWORK_SCOPE:
            continue
        try:
            resolved = resolve_allowed_path(text, allowed_roots)
        except PermissionError:
            continue
        key = str(resolved).replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(str(resolved))
    return out


def succeeded_lta_extract_dirs() -> list[str]:
    root = jobs_root()
    if not root.is_dir():
        return []
    out: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name in {"index.json"}:
            continue
        try:
            job_root = succeeded_lta_extract_root(child.name)
        except (KeyError, PathDenied, ValueError):
            continue
        out.append(str(job_root))
    return out


def mcp_investigation_roots_json() -> str:
    """Env payload for the REA process: configured ∩ allowed, plus succeeded LTA extracts."""
    configured = intersect_roots(configured_investigation_roots())
    extras = succeeded_lta_extract_dirs()
    merged: list[str] = []
    seen: set[str] = set()
    for item in configured + extras:
        key = item.replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return json.dumps(merged)


def suppressed_dynamic_rea_envs() -> dict[str, str]:
    """RFC-0200 §4: do not silently enable process/browser scenario roots."""
    settings = load_settings()
    if settings.rea.process_capture_enabled or settings.rea.browser_scenario_enabled:
        return {}
    return {name: "" for name in _DYNAMIC_REA_ENVS}


def _under_succeeded_lta_extract(resolved: Path) -> Path | None:
    root = jobs_root().resolve()
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    try:
        return succeeded_lta_extract_root(parts[0])
    except (KeyError, PathDenied, ValueError):
        return None


def resolve_rea_investigation_path(
    path: str | None = None,
    *,
    lta_job_id: str | None = None,
) -> Path:
    """Resolve an owner REA target. Fail closed with path_not_allowed.

    Empty ``REA_INVESTIGATION_INPUT_ROOTS_JSON`` denies owner path utterances.
    RFC-0200 §3.3: an already-opened LTA extract (job id or explicit path under
    ``data_dir()/lta-extract/{job-id}/``) remains allowed even when roots are empty.
    """
    job_id = (lta_job_id or "").strip()
    raw = (path or "").strip()
    allowed = jarvis_allowed_roots()

    if job_id:
        try:
            job_root = succeeded_lta_extract_root(job_id)
        except KeyError as exc:
            raise PathNotAllowed("unknown LTA job", detail="unknown_lta_job") from exc
        except PathDenied as exc:
            raise PathNotAllowed(str(exc), detail=exc.detail or "lta_not_extracted") from exc
        target = job_root
        if raw:
            if not is_absolute_owner_path(raw):
                raise PathNotAllowed("REA targets must be absolute paths", detail="relative_path")
            try:
                reject_unsafe_path_text(raw)
                inner = resolve_allowed_path(raw, allowed + [str(job_root)])
            except PermissionError as exc:
                raise PathNotAllowed(str(exc), detail="path_not_allowed") from exc
            try:
                inner.relative_to(job_root)
            except ValueError as exc:
                raise PathNotAllowed(
                    "path is not under the LTA extract for this job",
                    detail="lta_extract_mismatch",
                ) from exc
            target = inner
        return target

    if not raw:
        raise PathNotAllowed("path or lta_job_id is required", detail="missing_target")
    if not is_absolute_owner_path(raw):
        raise PathNotAllowed("REA targets must be absolute paths", detail="relative_path")
    try:
        reject_unsafe_path_text(raw)
        resolved = resolve_allowed_path(raw, allowed)
    except PermissionError as exc:
        raise PathNotAllowed(str(exc), detail="path_not_allowed") from exc

    lta_root = _under_succeeded_lta_extract(resolved)
    if lta_root is not None:
        return resolved

    roots = configured_investigation_roots()
    if not roots:
        raise PathNotAllowed(
            "REA investigation roots are unset or empty; owner paths are denied",
            detail="roots_empty",
        )
    intersecting = intersect_roots(roots, allowed)
    if not intersecting:
        raise PathNotAllowed(
            "REA investigation roots do not intersect allowed_directories",
            detail="roots_not_intersecting",
        )
    if not any(path_is_under_root(str(resolved), root) for root in intersecting):
        raise PathNotAllowed(
            f"Path {resolved} is outside REA investigation roots",
            detail="outside_investigation_roots",
        )
    return resolved


_PATHISH_KEYS = frozenset(
    {
        "path",
        "target",
        "file",
        "filename",
        "directory",
        "dir",
        "folder",
        "binary",
        "binary_path",
        "app",
        "app_path",
        "input",
        "input_path",
        "snapshot_path",
        "artifact",
        "artifact_path",
        "source",
        "source_path",
    }
)


def sanitize_rea_mcp_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Validate absolute filesystem arguments before they reach REA MCP tools."""
    payload = dict(arguments or {})
    job_id = str(payload.get("lta_job_id") or payload.get("job_id") or "").strip() or None

    def _maybe_path(key: str, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return value
        key_l = key.lower()
        looks_path = key_l in _PATHISH_KEYS or is_absolute_owner_path(text)
        if not looks_path:
            return value
        resolved = resolve_rea_investigation_path(text, lta_job_id=job_id if job_id else None)
        return str(resolved)

    def _walk(obj: Any, key: str = "") -> Any:
        if isinstance(obj, dict):
            return {str(k): _walk(v, str(k)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(item, key) for item in obj]
        return _maybe_path(key, obj)

    if job_id and not any(isinstance(v, str) and is_absolute_owner_path(v) for v in payload.values()):
        # Job-id-only analyze: resolve extract root so REA receives an allowed path.
        payload.setdefault("path", str(resolve_rea_investigation_path(lta_job_id=job_id)))
    return _walk(payload)


def is_rea_mcp_server(server: dict[str, Any] | None) -> bool:
    if not isinstance(server, dict):
        return False
    name = str(server.get("name") or "").strip().lower()
    preset = str(server.get("preset") or "").strip().lower()
    catalog = str(server.get("catalog_key") or server.get("id") or "").strip().lower()
    args = " ".join(str(item) for item in (server.get("args") or []))
    if name == "rea" or preset == "rea":
        return True
    if catalog.startswith("io.github.morluto/rea"):
        return True
    return "rea-agents@" in args or args.endswith("rea-agents mcp") or " rea-agents " in f" {args} "
