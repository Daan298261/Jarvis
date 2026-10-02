"""RFC-0199: detect customer *.jarvis-license beside Setup and apply on first backend start."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir, repo_root
from ..policy.cyber_ato import (
    AtoError,
    audit_ato_event,
    effective_expires_at,
    install_license,
    load_installed,
    verify_license,
)

log = logging.getLogger(__name__)

PREFERRED_SIDECAR_NAME = "Jarvis.jarvis-license"
IGNORE_SIDECAR_NAMES = frozenset({"Jarvis-unrestricted.jarvis-license"})

PENDING_FLAG_NAME = "license-pending-apply.json"
FAILURE_FLAG_NAME = "license-sidecar-apply-failure.json"
SIDECAR_DIR_NAME = "license-sidecar"


def pending_apply_path() -> Path:
    return data_dir() / PENDING_FLAG_NAME


def sidecar_failure_path() -> Path:
    return data_dir() / FAILURE_FLAG_NAME


def sidecar_residence_dir(app_root: Path | None = None) -> Path:
    root = (app_root or repo_root()).resolve()
    path = root / SIDECAR_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_installer_sidecars(installer_dir: Path) -> list[Path]:
    directory = installer_dir.resolve()
    if not directory.is_dir():
        return []
    found: list[Path] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        if not path.name.lower().endswith(".jarvis-license"):
            continue
        if path.name in IGNORE_SIDECAR_NAMES:
            continue
        found.append(path)
    return sorted(found, key=lambda item: item.name.lower())


def select_installer_sidecar(candidates: list[Path]) -> Path | None:
    if not candidates:
        return None
    for path in candidates:
        if path.name.lower() == PREFERRED_SIDECAR_NAME.lower():
            return path
    if len(candidates) == 1:
        return candidates[0]
    return sorted(candidates, key=lambda item: item.name.lower())[0]


def _iso_now() -> str:
    value = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return value.replace("+00:00", "Z")


def _read_json_object(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AtoError("License file must be a JSON object")
    return raw


def _installed_payload_if_valid() -> dict[str, Any] | None:
    document = load_installed()
    if not document:
        return None
    try:
        return verify_license(document)
    except AtoError:
        return None


def _sidecar_payload_if_valid(path: Path) -> dict[str, Any] | None:
    try:
        document = _read_json_object(path)
        return verify_license(document)
    except (AtoError, OSError, json.JSONDecodeError):
        return None


def should_apply_sidecar_over_existing(
    existing_payload: dict[str, Any],
    sidecar_payload: dict[str, Any],
) -> bool:
    new_expires = effective_expires_at(sidecar_payload)
    current_expires = effective_expires_at(existing_payload)
    return new_expires > current_expires


def clear_sidecar_failure() -> None:
    path = sidecar_failure_path()
    if path.is_file():
        path.unlink()


def record_sidecar_failure(message: str, *, source: str = "") -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "message": message.strip(),
        "source": source,
        "at": _iso_now(),
    }
    temp = sidecar_failure_path().with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, sidecar_failure_path())


def write_pending_apply(*, residence_copy: Path, sidecar_source: Path) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "source": str(residence_copy.resolve()),
        "installer_source": str(sidecar_source.resolve()),
        "sidecar_filename": residence_copy.name,
        "staged_at": _iso_now(),
    }
    temp = pending_apply_path().with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, pending_apply_path())
    clear_sidecar_failure()


def clear_pending_apply() -> None:
    path = pending_apply_path()
    if path.is_file():
        path.unlink()


def read_pending_apply() -> dict[str, Any] | None:
    path = pending_apply_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def public_sidecar_status() -> dict[str, Any]:
    failure: dict[str, Any] | None = None
    path = sidecar_failure_path()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("message"):
                failure = {
                    "message": str(raw["message"]),
                    "source": str(raw.get("source") or ""),
                    "at": str(raw.get("at") or ""),
                }
        except (OSError, json.JSONDecodeError):
            failure = {"message": "Sidecar license invalid.", "source": "", "at": ""}
    pending = read_pending_apply()
    return {
        "pending_apply": pending is not None,
        "failure": failure,
    }


def stage_installer_sidecar(*, installer_dir: Path, app_root: Path) -> dict[str, Any]:
    """Copy sidecar beside Setup into residence and queue pending apply when appropriate."""
    candidates = list_installer_sidecars(installer_dir)
    selected = select_installer_sidecar(candidates)
    if selected is None:
        return {"status": "none", "message": "No customer license sidecar beside installer."}

    sidecar_payload = _sidecar_payload_if_valid(selected)
    if sidecar_payload is None:
        message = f"Sidecar license invalid: could not verify signature ({selected.name})."
        record_sidecar_failure(message, source=str(selected))
        clear_pending_apply()
        return {"status": "invalid", "message": message, "sidecar": selected.name}

    existing = _installed_payload_if_valid()
    if existing is not None and not should_apply_sidecar_over_existing(existing, sidecar_payload):
        message = (
            "Skipping installer license sidecar: a valid license is already installed "
            "with same or later expiry."
        )
        log.info(message)
        return {
            "status": "skipped_upgrade",
            "message": message,
            "sidecar": selected.name,
            "installed_expires_at": existing.get("expires_at"),
            "sidecar_expires_at": sidecar_payload.get("expires_at"),
        }

    residence = sidecar_residence_dir(app_root)
    destination = residence / selected.name
    shutil.copy2(selected, destination)
    write_pending_apply(residence_copy=destination, sidecar_source=selected)
    return {
        "status": "staged",
        "message": f"License sidecar staged for apply on first start ({selected.name}).",
        "sidecar": selected.name,
        "residence_copy": str(destination),
    }


def apply_pending_sidecar_license() -> dict[str, Any] | None:
    """Apply pending sidecar license during backend startup (idempotent when no flag)."""
    pending = read_pending_apply()
    if not pending:
        return None

    source_text = str(pending.get("source") or "").strip()
    if not source_text:
        message = "Sidecar license invalid: pending apply flag missing source path."
        record_sidecar_failure(message)
        clear_pending_apply()
        log.error(message)
        return {"status": "failed", "message": message}

    source = Path(source_text)
    if not source.is_file():
        message = f"Sidecar license invalid: staged copy missing ({source})."
        record_sidecar_failure(message, source=source_text)
        clear_pending_apply()
        log.error(message)
        return {"status": "failed", "message": message}

    try:
        document = _read_json_object(source)
        install_license(document)
    except AtoError as exc:
        message = f"Sidecar license invalid: {exc}"
        record_sidecar_failure(message, source=source_text)
        clear_pending_apply()
        log.error(message)
        return {"status": "failed", "message": message}
    except (OSError, json.JSONDecodeError) as exc:
        message = f"Sidecar license invalid: {exc}"
        record_sidecar_failure(message, source=source_text)
        clear_pending_apply()
        log.error(message)
        return {"status": "failed", "message": message}

    clear_pending_apply()
    clear_sidecar_failure()
    audit_ato_event("license_auto_applied", source=source_text, sidecar=pending.get("sidecar_filename"))
    log.info("Installer license sidecar applied from %s", source_text)
    return {"status": "applied", "source": source_text}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RFC-0199 installer license sidecar helper")
    sub = parser.add_subparsers(dest="command", required=True)

    stage = sub.add_parser("stage", help="Detect sidecar beside Setup and stage pending apply")
    stage.add_argument("--installer-dir", required=True)
    stage.add_argument("--app-root", required=True)

    sub.add_parser("apply-pending", help="Apply pending sidecar license (backend startup)")

    args = parser.parse_args(argv)
    if args.command == "stage":
        result = stage_installer_sidecar(
            installer_dir=Path(args.installer_dir),
            app_root=Path(args.app_root),
        )
        print(json.dumps(result, indent=2))
        if result.get("status") == "invalid":
            return 2
        return 0
    if args.command == "apply-pending":
        result = apply_pending_sidecar_license()
        print(json.dumps(result or {"status": "idle"}, indent=2))
        return 0 if result is None or result.get("status") != "failed" else 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
