"""Real reverse executors + prior-state capture for RFC-0031 undo.

Journal rows store restore *references* (snapshot paths / small settings values),
never unbounded secret blobs. apply_undo must call these executors — status
``undone`` is only valid after a successful reverse op.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from ..config import data_dir

log = logging.getLogger("jarvis.policy.undo_restore")

_SNAPSHOT_DIR = "undo_snapshots"
_MAX_INLINE_SETTINGS_CHARS = 4000
_MAX_CAPTURE_BYTES = 8 * 1024 * 1024  # 8 MiB — larger files use on-disk snapshot only


class UndoNotImplementedError(RuntimeError):
    """Reverse op cannot run with the recorded prior_state."""


class UndoConflictError(RuntimeError):
    """World changed; reverse is unsafe."""


def undo_snapshot_root() -> Path:
    path = data_dir() / "policy" / _SNAPSHOT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def reset_undo_snapshots() -> None:
    root = undo_snapshot_root()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture_filesystem_prior(target: str) -> dict[str, Any]:
    """Capture restore payload for a filesystem path before mutation.

    Returns a prior_state dict. On failure raises OSError / ValueError so callers
    can fail closed when ``snapshot_required``.
    """
    raw = (target or "").strip()
    if not raw:
        raise ValueError("filesystem snapshot requires a non-empty target path")
    path = Path(raw).expanduser()
    # Prefer resolve when path exists; for new files keep the intended path.
    try:
        resolved = path.resolve() if path.exists() else path.expanduser().absolute()
    except OSError as exc:
        raise OSError(f"cannot resolve path for undo snapshot: {exc}") from exc

    if not resolved.exists():
        return {
            "kind": "filesystem_bytes",
            "path": str(resolved),
            "existed": False,
            "was_directory": False,
            "snapshot_path": None,
            "sha256": None,
            "encoding": None,
        }

    was_dir = resolved.is_dir()
    snap_id = uuid.uuid4().hex
    snap_dir = undo_snapshot_root() / snap_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    if was_dir:
        dest = snap_dir / "tree"
        shutil.copytree(resolved, dest, dirs_exist_ok=True)
        # Digest of sorted relative paths + sizes (not full blob in journal).
        hasher = hashlib.sha256()
        for item in sorted(dest.rglob("*")):
            if item.is_file():
                rel = item.relative_to(dest).as_posix()
                hasher.update(f"{rel}:{item.stat().st_size}".encode())
        digest = hasher.hexdigest()
        return {
            "kind": "filesystem_bytes",
            "path": str(resolved),
            "existed": True,
            "was_directory": True,
            "snapshot_path": str(dest),
            "sha256": digest,
            "encoding": "directory",
        }

    data = resolved.read_bytes()
    if len(data) > _MAX_CAPTURE_BYTES:
        raise OSError(
            f"file too large for undo snapshot ({len(data)} bytes > {_MAX_CAPTURE_BYTES})"
        )
    snap_file = snap_dir / "blob"
    snap_file.write_bytes(data)
    encoding = "binary"
    try:
        data.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        pass
    return {
        "kind": "filesystem_bytes",
        "path": str(resolved),
        "existed": True,
        "was_directory": False,
        "snapshot_path": str(snap_file),
        "sha256": _sha256_bytes(data),
        "encoding": encoding,
        "size": len(data),
    }


def capture_settings_prior(key: str) -> dict[str, Any]:
    """Capture previous settings value for a dotted/simple key."""
    from ..config import load_settings

    field = (key or "").strip()
    if not field:
        raise ValueError("settings snapshot requires a key")
    settings = load_settings()
    if not hasattr(settings, field):
        # Allow nested dump lookup
        dumped = settings.model_dump()
        if field not in dumped:
            raise ValueError(f"unknown settings key for undo capture: {field}")
        previous = dumped[field]
    else:
        previous = getattr(settings, field)
    payload = json.dumps(previous, default=str)
    if len(payload) > _MAX_INLINE_SETTINGS_CHARS:
        raise ValueError("settings value too large to journal for undo")
    return {
        "kind": "settings_value",
        "key": field,
        "previous_value": previous,
        "existed": True,
    }


def capture_prior_for_effect(
    tool_name: str,
    *,
    action: str,
    arguments: dict[str, Any] | None,
    snapshot_required: bool,
) -> dict[str, Any]:
    """Capture prior_state for a proposed side effect. Raises on required failure."""
    args = arguments if isinstance(arguments, dict) else {}
    name = (tool_name or "").strip().lower()
    act = (action or str(args.get("action") or "")).strip().lower()
    target = str(args.get("path") or args.get("destination") or args.get("target") or "").strip()

    if name == "filesystem" and act in {"copy", "move", "rename"}:
        source = str(args.get("path") or args.get("source") or target or "").strip()
        destination = str(args.get("destination") or args.get("to") or "").strip()
        if not source or not destination:
            raise ValueError(f"filesystem.{act} undo capture requires path and destination")
        source_prior = capture_filesystem_prior(source)
        dest_prior = capture_filesystem_prior(destination)
        return {
            "kind": "filesystem_copy_move",
            "action": act,
            "path": source_prior.get("path"),
            "source_path": source_prior.get("path"),
            "destination_path": dest_prior.get("path"),
            "source": source_prior,
            "destination": dest_prior,
            "existed": source_prior.get("existed"),
            "restorable": True,
        }

    if name == "filesystem" and act in {"write", "edit", "mkdir", "delete"}:
        path = target or str(args.get("path") or "")
        return capture_filesystem_prior(path)

    if name in {"settings", "config"}:
        key = str(args.get("path") or args.get("key") or target or "").strip()
        return capture_settings_prior(key)

    if snapshot_required:
        raise ValueError(
            f"snapshot_required but no capture handler for {name}.{act or 'invoke'}"
        )
    # Non-required: metadata-only prior is insufficient for apply; apply will refuse.
    return {
        "kind": "metadata_only",
        "tool_name": name,
        "action": act,
        "target": target,
        "restorable": False,
    }


def _restore_filesystem(prior: dict[str, Any], *, target_hint: str = "") -> dict[str, Any]:
    path_str = str(prior.get("path") or target_hint or "").strip()
    if not path_str:
        raise UndoNotImplementedError("filesystem undo missing path in prior_state")
    path = Path(path_str)
    existed = bool(prior.get("existed"))
    snap = prior.get("snapshot_path")

    if not existed:
        # Action created the path — reverse by removing it.
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        return {"restored": "deleted_created_path", "path": str(path)}

    if not snap:
        raise UndoNotImplementedError(
            "filesystem undo has no snapshot_path; refuse rather than fake success"
        )
    snap_path = Path(str(snap))
    if not snap_path.exists():
        raise UndoConflictError(f"undo snapshot missing or unreadable: {snap_path}")

    if prior.get("was_directory"):
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(snap_path, path, dirs_exist_ok=True)
        return {"restored": "directory", "path": str(path), "from": str(snap_path)}

    path.parent.mkdir(parents=True, exist_ok=True)
    data = snap_path.read_bytes()
    expected = prior.get("sha256")
    if expected and _sha256_bytes(data) != expected:
        raise UndoConflictError("undo snapshot digest mismatch")
    path.write_bytes(data)
    return {"restored": "file", "path": str(path), "bytes": len(data), "from": str(snap_path)}


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _restore_copy_move(prior: dict[str, Any]) -> dict[str, Any]:
    """Operation-specific inverses for copy / move / rename.

    - copy: restore destination prior (delete if it did not exist); leave source alone
    - move/rename: restore source from snapshot; restore destination prior (delete if new)
    """
    action = str(prior.get("action") or "").strip().lower()
    source = dict(prior.get("source") or {})
    destination = dict(prior.get("destination") or {})
    source_path = Path(str(prior.get("source_path") or source.get("path") or ""))
    dest_path = Path(str(prior.get("destination_path") or destination.get("path") or ""))
    if not source_path or not dest_path:
        raise UndoNotImplementedError("copy/move undo requires source and destination paths")

    details: dict[str, Any] = {"action": action, "source": str(source_path), "destination": str(dest_path)}

    if action == "copy":
        # Inverse of copy is removing/restoring only the destination.
        if destination.get("existed"):
            details["destination_restore"] = _restore_filesystem(destination)
        else:
            _remove_path(dest_path)
            details["destination_restore"] = {"restored": "deleted_created_path", "path": str(dest_path)}
        details["source_untouched"] = True
        return details

    if action in {"move", "rename"}:
        # Put source back from its pre-move snapshot, then restore destination prior.
        if source.get("existed"):
            details["source_restore"] = _restore_filesystem(source)
        else:
            raise UndoNotImplementedError("move/rename undo missing source snapshot")
        if destination.get("existed"):
            details["destination_restore"] = _restore_filesystem(destination)
        else:
            _remove_path(dest_path)
            details["destination_restore"] = {"restored": "deleted_created_path", "path": str(dest_path)}
        return details

    raise UndoNotImplementedError(f"unsupported copy/move action for undo: {action!r}")


def _restore_settings(prior: dict[str, Any]) -> dict[str, Any]:
    from ..config import load_settings, save_settings

    key = str(prior.get("key") or "").strip()
    if not key:
        raise UndoNotImplementedError("settings undo missing key")
    if "previous_value" not in prior:
        raise UndoNotImplementedError("settings undo missing previous_value")
    settings = load_settings()
    if not hasattr(settings, key):
        raise UndoNotImplementedError(f"settings key not restorable: {key}")
    setattr(settings, key, prior["previous_value"])
    save_settings(settings)
    return {"restored": "settings", "key": key}


def execute_reverse(record: dict[str, Any]) -> dict[str, Any]:
    """Run the reverse op for one undo journal row.

    Returns ``{status: undone|not_implemented|conflict, ...}``.
    Never reports undone without performing a reverse.
    """
    prior = dict(record.get("prior_state") or {})
    kind = str(prior.get("kind") or "")
    op = str(record.get("undo_operation") or "")
    tool = str(record.get("tool_name") or "").lower()

    try:
        # Non-restorable / metadata-only first — never fake success via op-name heuristics.
        if kind == "metadata_only" or prior.get("restorable") is False:
            raise UndoNotImplementedError(
                "no restorable prior_state captured; refuse rather than mark undone"
            )

        if kind == "filesystem_bytes":
            detail = _restore_filesystem(prior, target_hint=str(record.get("target") or ""))
            return {"status": "undone", "detail": detail, "undo_operation": op}

        if kind == "filesystem_copy_move":
            detail = _restore_copy_move(prior)
            return {"status": "undone", "detail": detail, "undo_operation": op}

        if kind == "settings_value":
            detail = _restore_settings(prior)
            return {"status": "undone", "detail": detail, "undo_operation": op}

        if op.startswith("filesystem.undo_") or tool == "filesystem":
            raise UndoNotImplementedError(
                "filesystem undo requires prior_state.kind=filesystem_bytes with snapshot"
            )

        if op.startswith("settings.") or tool in {"settings", "config"}:
            raise UndoNotImplementedError(
                "settings undo requires prior_state.kind=settings_value"
            )

        # Compensatable ops without a concrete restore payload (e.g. terminal.stop_if_running)
        # must refuse honestly until a real reverse is wired.
        raise UndoNotImplementedError(
            f"no reverse executor for undo_operation={op!r} kind={kind!r}"
        )
    except UndoNotImplementedError as exc:
        log.info("undo not_implemented record=%s: %s", record.get("id"), exc)
        return {"status": "not_implemented", "reason": str(exc), "record_id": record.get("id")}
    except UndoConflictError as exc:
        log.info("undo conflict record=%s: %s", record.get("id"), exc)
        return {"status": "conflict", "reason": str(exc), "record_id": record.get("id")}
    except Exception as exc:  # noqa: BLE001 — surface as conflict, never fake undone
        log.exception("undo reverse failed record=%s", record.get("id"))
        return {
            "status": "conflict",
            "reason": f"reverse op failed: {exc}",
            "record_id": record.get("id"),
        }


def default_undo_executor(record: dict[str, Any]) -> dict[str, Any]:
    """Executor for apply_undo — raises on non-success so journal is not marked undone."""
    result = execute_reverse(record)
    status = result.get("status")
    if status == "undone":
        return result
    if status == "not_implemented":
        raise UndoNotImplementedError(str(result.get("reason") or "not_implemented"))
    raise UndoConflictError(str(result.get("reason") or "conflict"))
