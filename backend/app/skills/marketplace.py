"""Marketplace / imported skills — always quarantine, then same evaluation pipeline."""

from __future__ import annotations

import json
import uuid
from typing import Any

from .extract import sign_manifest
from .schema import (
    LifecycleStatus,
    Provenance,
    SkillCandidate,
    SkillManifest,
    SkillVersion,
)
from .store import quarantine_path, save_candidate, utc_now


class MarketplaceError(ValueError):
    pass


def import_skill_manifest(
    payload: dict[str, Any] | SkillManifest,
    *,
    source: str = "marketplace",
    imported_from: str | None = None,
    created_by: str = "marketplace_import",
) -> SkillCandidate:
    """Import an external skill into quarantine. Never activates. Must pass eval + approval."""
    if isinstance(payload, SkillManifest):
        manifest = payload.model_copy(deep=True)
    else:
        if not isinstance(payload, dict):
            raise MarketplaceError("import payload must be a skill manifest object")
        manifest = SkillManifest.model_validate(payload)

    manifest.provenance = Provenance(
        source="marketplace" if source == "marketplace" else "import",
        trajectory_ids=list(manifest.provenance.trajectory_ids or []),
        parent_version_id=manifest.provenance.parent_version_id,
        created_by=created_by,
        imported_from=imported_from or source,
        notes="Imported skill entered quarantine; evaluation and owner approval required",
    )
    manifest = sign_manifest(manifest)

    import_id = str(uuid.uuid4())
    qpath = quarantine_path(import_id)
    (qpath / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (qpath / "QUARANTINED.txt").write_text(
        "This skill is quarantined until Skill Forge evaluation and owner approval succeed.\n",
        encoding="utf-8",
    )

    skill_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    candidate_id = str(uuid.uuid4())
    now = utc_now()
    version = SkillVersion(
        version_id=version_id,
        skill_id=skill_id,
        status=LifecycleStatus.QUARANTINED,
        manifest=manifest,
        created_at=now,
        quarantine_reason="marketplace_or_import",
        immutable=False,
    )
    candidate = SkillCandidate(
        candidate_id=candidate_id,
        skill_id=skill_id,
        status=LifecycleStatus.QUARANTINED,
        version=version,
        created_at=now,
        updated_at=now,
    )
    return save_candidate(candidate)
