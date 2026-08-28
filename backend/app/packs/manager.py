from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Literal

from .schema import (
    InstalledPack,
    PackManifest,
    PackPreview,
    PackResource,
    ResourceChange,
    ResourceRecord,
    parse_version,
    version_satisfies,
)
from .store import (
    append_history,
    create_snapshot,
    get_installation,
    get_resource_record,
    history_event,
    list_installations,
    list_resource_records,
    list_resources_for_pack,
    load_snapshot,
    remove_installation,
    remove_resource_record,
    set_installation,
    set_resource_record,
)
from .trust import (
    CapabilityPolicyError,
    TrustError,
    check_jarvis_version,
    enforce_capability_policy,
    enforce_trust_policy,
    evaluate_capabilities,
    verify_signature,
)

_SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|password|token|credential|private[_-]?key)", re.I)


class PackError(ValueError):
    pass


class PackConflictError(PackError):
    pass


def _hash_data(data: dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_manifest(manifest: PackManifest) -> str:
    return _hash_data(manifest.model_dump(mode="json"))


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _SECRET_KEY_RE.search(str(key)):
                continue
            cleaned[key] = _strip_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    return value


def _evaluate_dependencies(manifest: PackManifest) -> dict[str, Any]:
    installed = {item.id: item.version for item in list_installations()}
    missing: list[str] = []
    optional_missing: list[str] = []
    unsatisfied: list[str] = []
    for dependency in manifest.dependencies:
        current = installed.get(dependency.id)
        if current is None:
            if dependency.optional:
                optional_missing.append(dependency.id)
            else:
                missing.append(dependency.id)
            continue
        if not version_satisfies(current, dependency.version):
            unsatisfied.append(f"{dependency.id}@{dependency.version}")
    return {
        "satisfied": not missing and not unsatisfied,
        "missing": missing,
        "optional_missing": optional_missing,
        "unsatisfied": unsatisfied,
    }


def _resource_payload(resource: PackResource) -> dict[str, Any]:
    payload = copy.deepcopy(resource.data)
    payload.setdefault("id", resource.id)
    payload.setdefault("type", resource.type)
    return payload


def _compute_resource_change(
    manifest: PackManifest,
    resource: PackResource,
    *,
    action: Literal["install", "upgrade"],
    overrides: dict[str, str] | None = None,
) -> ResourceChange:
    overrides = overrides or {}
    existing = get_resource_record(resource.id)
    incoming = _resource_payload(resource)
    override = overrides.get(resource.id)

    if existing is None:
        return ResourceChange(
            resource_id=resource.id,
            resource_type=resource.type,
            action="create",
            before=None,
            after=incoming,
        )

    if existing.user_modified and resource.merge_strategy == "skip_if_user_modified":
        if override == "use_pack":
            return ResourceChange(
                resource_id=resource.id,
                resource_type=resource.type,
                action="update",
                before=existing.data,
                after=incoming,
                reason="override_use_pack",
            )
        return ResourceChange(
            resource_id=resource.id,
            resource_type=resource.type,
            action="skip",
            before=existing.data,
            after=incoming,
            reason="user_modified",
        )

    if existing.user_modified and override == "keep_user":
        return ResourceChange(
            resource_id=resource.id,
            resource_type=resource.type,
            action="skip",
            before=existing.data,
            after=incoming,
            reason="override_keep_user",
        )

    if existing.data_hash == _hash_data(incoming):
        return ResourceChange(
            resource_id=resource.id,
            resource_type=resource.type,
            action="skip",
            before=existing.data,
            after=incoming,
            reason="unchanged",
        )

    if existing.user_modified and override != "use_pack" and resource.merge_strategy != "merge":
        return ResourceChange(
            resource_id=resource.id,
            resource_type=resource.type,
            action="conflict",
            before=existing.data,
            after=incoming,
            reason="user_modified",
        )

    merged = incoming
    if resource.merge_strategy == "merge":
        merged = _deep_merge(existing.data, incoming)

    return ResourceChange(
        resource_id=resource.id,
        resource_type=resource.type,
        action="update",
        before=existing.data,
        after=merged,
        reason=action,
    )


def preview_pack(
    manifest: PackManifest,
    *,
    action: Literal["install", "upgrade", "uninstall"] = "install",
    overrides: dict[str, str] | None = None,
    require_signature: bool = False,
) -> PackPreview:
    errors: list[str] = []
    warnings: list[str] = []
    changes: list[ResourceChange] = []

    jarvis_check = check_jarvis_version(manifest)
    if not jarvis_check["satisfied"]:
        errors.append(
            f"Jarvis {jarvis_check['jarvis_version']} does not satisfy minimum "
            f"{jarvis_check['min_jarvis_version']}"
        )

    dependency_check = _evaluate_dependencies(manifest)
    if dependency_check["missing"]:
        errors.append("Missing required pack dependencies: " + ", ".join(dependency_check["missing"]))
    if dependency_check["unsatisfied"]:
        errors.append("Unsatisfied pack dependencies: " + ", ".join(dependency_check["unsatisfied"]))
    if dependency_check["optional_missing"]:
        warnings.append(
            "Optional dependencies not installed: " + ", ".join(dependency_check["optional_missing"])
        )

    trust_result = verify_signature(manifest)
    if require_signature and not trust_result["signature_valid"]:
        errors.append(trust_result["message"])
    elif not trust_result["signature_valid"] and manifest.trust.trust_level != "user":
        errors.append(trust_result["message"])

    capability_result = evaluate_capabilities(manifest)
    if not capability_result["allowed"]:
        if capability_result["missing"]:
            errors.append("Missing required tools: " + ", ".join(capability_result["missing"]))
        if capability_result["denied_present"]:
            errors.append(
                "Denied tools are currently enabled: " + ", ".join(capability_result["denied_present"])
            )

    installed = get_installation(manifest.id)
    if action == "install":
        if installed is not None:
            errors.append(f"Pack {manifest.id!r} is already installed")
        for resource in manifest.resources:
            changes.append(_compute_resource_change(manifest, resource, action="install", overrides=overrides))
    elif action == "upgrade":
        if installed is None:
            errors.append(f"Pack {manifest.id!r} is not installed")
        else:
            try:
                if parse_version(manifest.version) <= parse_version(installed.version):
                    warnings.append("Upgrade manifest version is not newer than the installed version")
            except ValueError as exc:
                errors.append(str(exc))
            for resource in manifest.resources:
                changes.append(_compute_resource_change(manifest, resource, action="upgrade", overrides=overrides))
    elif action == "uninstall":
        if installed is None:
            errors.append(f"Pack {manifest.id!r} is not installed")
        for record in list_resources_for_pack(manifest.id):
            changes.append(
                ResourceChange(
                    resource_id=record.resource_id,
                    resource_type=record.resource_type,
                    action="delete",
                    before=record.data,
                    after=None,
                    reason="uninstall",
                )
            )

    return PackPreview(
        pack_id=manifest.id,
        version=manifest.version,
        action=action,
        valid=not errors,
        errors=errors,
        warnings=warnings,
        changes=changes,
        trust=trust_result,
        capabilities=capability_result,
        dependencies=dependency_check,
    )


def _apply_changes(
    manifest: PackManifest,
    changes: list[ResourceChange],
    *,
    installed_version: str,
) -> list[str]:
    applied: list[str] = []
    for change in changes:
        if change.action in {"skip", "conflict"}:
            continue
        if change.action == "delete":
            remove_resource_record(change.resource_id)
            applied.append(change.resource_id)
            continue
        if change.after is None:
            continue
        existing = get_resource_record(change.resource_id)
        user_modified = False
        if existing is not None and existing.user_modified and change.action == "update":
            if change.reason not in {"override_use_pack"} and _hash_data(change.after) != existing.data_hash:
                user_modified = True
        record = ResourceRecord(
            resource_id=change.resource_id,
            pack_id=manifest.id,
            resource_type=change.resource_type,
            user_modified=user_modified,
            override=None,
            data_hash=_hash_data(change.after),
            installed_version=installed_version,
            data=change.after,
        )
        set_resource_record(record)
        applied.append(change.resource_id)
    return applied


def _snapshot_current_state(pack_id: str) -> str:
    installation = get_installation(pack_id)
    resources = [item.model_dump(mode="json") for item in list_resources_for_pack(pack_id)]
    payload = {
        "installation": installation.model_dump(mode="json") if installation else None,
        "resources": resources,
    }
    return create_snapshot(pack_id, payload)


def install_pack(
    manifest: PackManifest,
    *,
    overrides: dict[str, str] | None = None,
    require_signature: bool = False,
    enforce_policies: bool = True,
) -> dict[str, Any]:
    preview = preview_pack(manifest, action="install", overrides=overrides, require_signature=require_signature)
    if not preview.valid:
        raise PackError("; ".join(preview.errors))
    if any(change.action == "conflict" for change in preview.changes):
        raise PackConflictError("Install preview contains unresolved conflicts")

    if enforce_policies:
        enforce_trust_policy(manifest, require_signature=require_signature)
        enforce_capability_policy(manifest)

    applied = _apply_changes(manifest, preview.changes, installed_version=manifest.version)
    record = InstalledPack(
        id=manifest.id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        status="installed",
        installed_at=_utc_now(),
        manifest_hash=_hash_manifest(manifest),
        previous_version=None,
        snapshot_id=None,
        resource_ids=applied,
    )
    set_installation(record)
    append_history(
        history_event("pack.installed", manifest.id, version=manifest.version, details={"resources": applied})
    )
    return {"installation": record.model_dump(mode="json"), "preview": preview.model_dump(mode="json")}


def upgrade_pack(
    manifest: PackManifest,
    *,
    overrides: dict[str, str] | None = None,
    require_signature: bool = False,
    enforce_policies: bool = True,
) -> dict[str, Any]:
    installed = get_installation(manifest.id)
    if installed is None:
        raise PackError(f"Pack {manifest.id!r} is not installed")

    preview = preview_pack(manifest, action="upgrade", overrides=overrides, require_signature=require_signature)
    if not preview.valid:
        raise PackError("; ".join(preview.errors))
    if any(change.action == "conflict" for change in preview.changes):
        raise PackConflictError("Upgrade preview contains unresolved conflicts")

    if enforce_policies:
        enforce_trust_policy(manifest, require_signature=require_signature)
        enforce_capability_policy(manifest)

    snapshot_id = _snapshot_current_state(manifest.id)
    applied = _apply_changes(manifest, preview.changes, installed_version=manifest.version)
    resource_ids = sorted({*installed.resource_ids, *applied})
    record = InstalledPack(
        id=manifest.id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        status="installed",
        installed_at=installed.installed_at,
        manifest_hash=_hash_manifest(manifest),
        previous_version=installed.version,
        snapshot_id=snapshot_id,
        resource_ids=resource_ids,
    )
    set_installation(record)
    append_history(
        history_event(
            "pack.upgraded",
            manifest.id,
            version=manifest.version,
            snapshot_id=snapshot_id,
            details={"resources": applied, "previous_version": installed.version},
        )
    )
    return {
        "installation": record.model_dump(mode="json"),
        "preview": preview.model_dump(mode="json"),
        "snapshot_id": snapshot_id,
    }


def rollback_pack(pack_id: str) -> dict[str, Any]:
    installed = get_installation(pack_id)
    if installed is None:
        raise PackError(f"Pack {pack_id!r} is not installed")
    snapshot_id = installed.snapshot_id
    if not snapshot_id:
        raise PackError(f"Pack {pack_id!r} has no rollback snapshot")

    snapshot = load_snapshot(pack_id, snapshot_id)
    if snapshot is None:
        raise PackError(f"Rollback snapshot {snapshot_id!r} not found")

    for record in list_resources_for_pack(pack_id):
        remove_resource_record(record.resource_id)

    restored_resources: list[str] = []
    for raw in snapshot.get("resources") or []:
        if not isinstance(raw, dict):
            continue
        record = ResourceRecord.model_validate(raw)
        set_resource_record(record)
        restored_resources.append(record.resource_id)

    previous_installation = snapshot.get("installation")
    if isinstance(previous_installation, dict):
        restored = InstalledPack.model_validate(previous_installation)
        restored.status = "rolled_back"
        restored.snapshot_id = None
        set_installation(restored)
        installation = restored.model_dump(mode="json")
    else:
        installation = installed.model_dump(mode="json")

    append_history(
        history_event(
            "pack.rolled_back",
            pack_id,
            version=installation.get("version"),
            snapshot_id=snapshot_id,
            details={"resources": restored_resources},
        )
    )
    return {"installation": installation, "snapshot_id": snapshot_id, "resources": restored_resources}


def uninstall_pack(pack_id: str, *, keep_user_modified: bool = True) -> dict[str, Any]:
    preview = preview_pack(
        PackManifest(id=pack_id, name=pack_id, version="0.0.0"),
        action="uninstall",
    )
    if not preview.valid:
        raise PackError("; ".join(preview.errors))

    removed: list[str] = []
    kept: list[str] = []
    for record in list_resources_for_pack(pack_id):
        if keep_user_modified and record.user_modified:
            kept.append(record.resource_id)
            continue
        remove_resource_record(record.resource_id)
        removed.append(record.resource_id)

    removed_installation = remove_installation(pack_id)
    append_history(
        history_event(
            "pack.uninstalled",
            pack_id,
            version=removed_installation.version if removed_installation else None,
            details={"removed": removed, "kept": kept},
        )
    )
    return {
        "pack_id": pack_id,
        "removed_resources": removed,
        "kept_resources": kept,
        "preview": preview.model_dump(mode="json"),
    }


def export_pack(
    pack_id: str,
    *,
    include_user_modifications: bool = False,
    name: str | None = None,
    version: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    installation = get_installation(pack_id)
    if installation is None:
        raise PackError(f"Pack {pack_id!r} is not installed")

    resources: list[PackResource] = []
    for record in list_resources_for_pack(pack_id):
        if record.user_modified and not include_user_modifications:
            continue
        resources.append(
            PackResource(
                id=record.resource_id,
                type=record.resource_type,  # type: ignore[arg-type]
                data=_strip_secrets(record.data),
                merge_strategy="skip_if_user_modified",
            )
        )

    manifest = PackManifest(
        id=pack_id,
        name=name or installation.name,
        version=version or installation.version,
        description=description or installation.description,
        resources=resources,
        trust={"trust_level": "user"},
    )
    return manifest.model_dump(mode="json")


def list_installed_packs() -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in list_installations()]


def get_installed_pack(pack_id: str) -> dict[str, Any] | None:
    installation = get_installation(pack_id)
    if installation is None:
        return None
    resources = [item.model_dump(mode="json") for item in list_resources_for_pack(pack_id)]
    return {"installation": installation.model_dump(mode="json"), "resources": resources}


def mark_resource_user_modified(resource_id: str, data: dict[str, Any] | None = None) -> ResourceRecord:
    record = get_resource_record(resource_id)
    if record is None:
        raise PackError(f"Resource {resource_id!r} not found")
    if data is not None:
        record.data = data
        record.data_hash = _hash_data(data)
    record.user_modified = True
    set_resource_record(record)
    return record


def parse_manifest(raw: dict[str, Any]) -> PackManifest:
    return PackManifest.model_validate(raw)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
