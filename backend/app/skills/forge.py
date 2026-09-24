"""Skill Forge orchestrator — observe → extract → sandbox → verify → approve → publish."""

from __future__ import annotations

import uuid
from typing import Any

from ..policy.audit import record_policy_change
from ..trajectories.schema import JarvisTrajectoryV1
from .approval import ApprovalError, approve_candidate, reject_candidate, request_approval
from .eligibility import EligibilityResult, evaluate_trajectory_eligibility
from .evaluate import evaluate_manifest
from .extract import ExtractionError, extract_candidate_manifest, new_ids, sign_manifest
from .marketplace import import_skill_manifest
from .permissions import PrivilegeExpansionError, compute_effective_capabilities, enforce_no_privilege_expansion
from .schema import (
    LifecycleStatus,
    Provenance,
    SkillCandidate,
    SkillManifest,
    SkillScope,
    SkillVersion,
)
from .store import (
    clear_active_version,
    get_active_version_id,
    get_candidate,
    get_version,
    list_candidates,
    list_skills,
    save_candidate,
    save_version,
    set_active_version,
    utc_now,
)


class ForgeError(ValueError):
    pass


class SkillForge:
    """Governed pipeline. Never auto-publishes or silently overwrites active versions."""

    def observe_trajectory(
        self,
        trajectory: JarvisTrajectoryV1 | dict[str, Any],
        *,
        auto_extract: bool = False,
    ) -> dict[str, Any]:
        if isinstance(trajectory, dict):
            trajectory = JarvisTrajectoryV1.model_validate(trajectory)
        eligibility = evaluate_trajectory_eligibility(trajectory)
        payload: dict[str, Any] = {
            "trajectory_id": trajectory.trajectory_id,
            "eligibility": eligibility.as_dict(),
            "candidate": None,
        }
        if auto_extract and eligibility.eligible:
            candidate = self.propose_from_trajectory(trajectory)
            payload["candidate"] = candidate.model_dump(mode="json")
        return payload

    def propose_from_trajectory(
        self,
        trajectory: JarvisTrajectoryV1 | dict[str, Any],
        *,
        scope: SkillScope = SkillScope.WORKFLOW,
        created_by: str = "skill_forge",
    ) -> SkillCandidate:
        if isinstance(trajectory, dict):
            trajectory = JarvisTrajectoryV1.model_validate(trajectory)
        eligibility = evaluate_trajectory_eligibility(trajectory)
        if not eligibility.eligible:
            raise ForgeError("ineligible trajectory: " + "; ".join(eligibility.reasons))
        try:
            manifest = extract_candidate_manifest(
                trajectory,
                require_eligible=True,
                scope=scope,
                created_by=created_by,
            )
        except ExtractionError as exc:
            raise ForgeError(str(exc)) from exc
        return self._create_candidate(manifest, status=LifecycleStatus.PROPOSED)

    def propose_from_manifest(
        self,
        manifest: SkillManifest | dict[str, Any],
        *,
        status: LifecycleStatus = LifecycleStatus.PROPOSED,
    ) -> SkillCandidate:
        if isinstance(manifest, dict):
            manifest = SkillManifest.model_validate(manifest)
        manifest = sign_manifest(manifest)
        return self._create_candidate(manifest, status=status)

    def _create_candidate(self, manifest: SkillManifest, *, status: LifecycleStatus) -> SkillCandidate:
        skill_id, candidate_id, version_id = new_ids()
        now = utc_now()
        version = SkillVersion(
            version_id=version_id,
            skill_id=skill_id,
            status=status,
            manifest=manifest,
            created_at=now,
            immutable=False,
        )
        candidate = SkillCandidate(
            candidate_id=candidate_id,
            skill_id=skill_id,
            status=status,
            version=version,
            created_at=now,
            updated_at=now,
        )
        return save_candidate(candidate)

    def sandbox(
        self,
        candidate_id: str,
        *,
        profile_id: str | None = None,
        task_capabilities: list[str] | None = None,
        node_capabilities: list[str] | None = None,
        parent_capabilities: list[str] | None = None,
    ) -> SkillCandidate:
        candidate = self._require(candidate_id)
        if candidate.status not in {
            LifecycleStatus.PROPOSED,
            LifecycleStatus.QUARANTINED,
            LifecycleStatus.SANDBOXED,
        }:
            raise ForgeError(f"cannot sandbox candidate in status {candidate.status.value}")

        try:
            effective = enforce_no_privilege_expansion(
                candidate.version.manifest,
                profile_id=profile_id,
                task_capabilities=task_capabilities,
                node_capabilities=node_capabilities,
                parent_capabilities=parent_capabilities,
            )
        except PrivilegeExpansionError as exc:
            updated = candidate.model_copy(deep=True)
            updated.status = LifecycleStatus.REJECTED
            updated.version.status = LifecycleStatus.REJECTED
            updated.rejection_reason = str(exc)
            updated.updated_at = utc_now()
            return save_candidate(updated)

        updated = candidate.model_copy(deep=True)
        updated.status = LifecycleStatus.SANDBOXED
        updated.version.status = LifecycleStatus.SANDBOXED
        updated.version.effective_capabilities = effective
        updated.updated_at = utc_now()
        return save_candidate(updated)

    def verify(self, candidate_id: str) -> SkillCandidate:
        candidate = self._require(candidate_id)
        if candidate.status not in {
            LifecycleStatus.SANDBOXED,
            LifecycleStatus.QUARANTINED,
            LifecycleStatus.VERIFIED,
        }:
            raise ForgeError(f"candidate must be sandboxed before verify (status={candidate.status.value})")

        # Quarantined imports: move through sandbox semantics first if needed.
        if candidate.status == LifecycleStatus.QUARANTINED:
            candidate = self.sandbox(candidate_id)

        verifier = evaluate_manifest(candidate.version.manifest, candidate_id=candidate_id)
        updated = candidate.model_copy(deep=True)
        updated.version.verifier = verifier
        updated.updated_at = utc_now()
        if verifier.passed:
            updated.status = LifecycleStatus.VERIFIED
            updated.version.status = LifecycleStatus.VERIFIED
        else:
            # Stay sandboxed (or quarantined path already sandboxed) — not verified.
            updated.status = LifecycleStatus.SANDBOXED
            updated.version.status = LifecycleStatus.SANDBOXED
        return save_candidate(updated)

    def request_owner_approval(self, candidate_id: str, *, actor: str = "skill_forge") -> SkillCandidate:
        candidate = self._require(candidate_id)
        if candidate.status != LifecycleStatus.VERIFIED:
            raise ForgeError("only verified candidates may request approval")
        return request_approval(candidate, actor=actor)

    def approve(self, candidate_id: str, *, actor: str, admin: bool = True) -> SkillCandidate:
        return approve_candidate(candidate_id, actor=actor, admin=admin)

    def reject(self, candidate_id: str, *, actor: str, reason: str) -> SkillCandidate:
        return reject_candidate(candidate_id, actor=actor, reason=reason)

    def activate(
        self,
        candidate_id: str,
        *,
        actor: str,
        profile_id: str | None = None,
        task_capabilities: list[str] | None = None,
        node_capabilities: list[str] | None = None,
        parent_capabilities: list[str] | None = None,
    ) -> SkillCandidate:
        """Publish an approved candidate as the active version. Never auto-called."""
        if not actor or not str(actor).strip():
            raise ForgeError("activation requires an owner/admin actor")
        candidate = self._require(candidate_id)
        approval = candidate.version.approval or {}
        if candidate.status != LifecycleStatus.APPROVED or not approval.get("approved"):
            raise ForgeError("activation requires explicit owner/admin approval")

        try:
            effective = enforce_no_privilege_expansion(
                candidate.version.manifest,
                profile_id=profile_id,
                task_capabilities=task_capabilities,
                node_capabilities=node_capabilities,
                parent_capabilities=parent_capabilities,
            )
        except PrivilegeExpansionError as exc:
            raise ForgeError(str(exc)) from exc

        # Supersede previous active version without mutating it.
        previous_id = get_active_version_id(candidate.skill_id)
        if previous_id and previous_id != candidate.version.version_id:
            previous = get_version(previous_id)
            if previous is not None:
                superseded = previous.model_copy(deep=True)
                # Active versions are immutable — we only flip status via replacing record once.
                # If already immutable, write a status companion by cloning is forbidden;
                # mark via index only and keep prior bytes. We allow a one-time status stamp
                # before immutability lock below.
                if not superseded.immutable:
                    superseded.status = LifecycleStatus.SUPERSEDED
                    save_version(superseded)

        updated = candidate.model_copy(deep=True)
        updated.status = LifecycleStatus.ACTIVE
        updated.version.status = LifecycleStatus.ACTIVE
        updated.version.effective_capabilities = effective
        updated.version.activated_at = utc_now()
        updated.version.immutable = True
        updated.updated_at = utc_now()
        if previous_id and previous_id != updated.version.version_id:
            updated.version.manifest.rollback_target_version_id = previous_id
            updated.version.manifest = sign_manifest(updated.version.manifest)
        saved = save_candidate(updated)
        set_active_version(saved.skill_id, saved.version.version_id)
        record_policy_change(
            actor=actor,
            profile_id=profile_id,
            field="skill_forge.activate",
            old_value=previous_id,
            new_value=saved.version.version_id,
        )
        return saved

    def disable(self, skill_id: str, *, actor: str) -> SkillVersion | None:
        if not actor:
            raise ForgeError("disable requires an actor")
        version_id = get_active_version_id(skill_id)
        if not version_id:
            return None
        version = get_version(version_id)
        if version is None:
            return None
        # Immutability of content: disable flag is metadata — store a disabled overlay on candidate index.
        # We allow toggling disabled on the version record only if we clone status fields carefully.
        # Active content (manifest) stays intact; we clear active pointer and mark rolled metadata.
        clear_active_version(skill_id)
        record_policy_change(
            actor=actor,
            profile_id=None,
            field="skill_forge.disable",
            old_value=version_id,
            new_value=None,
        )
        return version

    def rollback(self, skill_id: str, *, actor: str, to_version_id: str | None = None) -> SkillVersion:
        if not actor:
            raise ForgeError("rollback requires an actor")
        current_id = get_active_version_id(skill_id)
        current = get_version(current_id) if current_id else None
        target_id = to_version_id
        if not target_id and current is not None:
            target_id = current.manifest.rollback_target_version_id
        if not target_id:
            raise ForgeError("no rollback target available")
        target = get_version(target_id)
        if target is None:
            raise ForgeError(f"rollback target not found: {target_id}")
        if target.skill_id != skill_id:
            raise ForgeError("rollback target belongs to a different skill")

        if current is not None and not current.immutable:
            rolled = current.model_copy(deep=True)
            rolled.status = LifecycleStatus.ROLLED_BACK
            save_version(rolled)
        elif current is not None:
            # Content stays; active pointer moves. Audit records the rollback.
            pass

        set_active_version(skill_id, target.version_id)
        # Ensure target is marked active in its record when mutable; immutable targets keep bytes.
        if not target.immutable and target.status != LifecycleStatus.ACTIVE:
            restored = target.model_copy(deep=True)
            restored.status = LifecycleStatus.ACTIVE
            restored.disabled = False
            save_version(restored)
            target = restored
        record_policy_change(
            actor=actor,
            profile_id=None,
            field="skill_forge.rollback",
            old_value=current_id,
            new_value=target.version_id,
        )
        return get_version(target.version_id) or target

    def repair(
        self,
        skill_id: str,
        *,
        trajectory: JarvisTrajectoryV1 | dict[str, Any] | None = None,
        manifest_patch: dict[str, Any] | None = None,
        created_by: str = "skill_forge_repair",
    ) -> SkillCandidate:
        """Create a new candidate version from a failed/repair path. Active skill stays intact."""
        active_id = get_active_version_id(skill_id)
        active = get_version(active_id) if active_id else None
        if active is None:
            # Fall back to latest candidate for this skill.
            for candidate in list_candidates(limit=200):
                if candidate.skill_id == skill_id:
                    active = candidate.version
                    break
        if active is None:
            raise ForgeError(f"no existing skill version to repair for {skill_id}")

        if trajectory is not None:
            if isinstance(trajectory, dict):
                trajectory = JarvisTrajectoryV1.model_validate(trajectory)
            # Repair may use failed traces; skip full eligibility success requirement but still
            # block secrets / hidden reasoning / unapproved consequential actions.
            eligibility = evaluate_trajectory_eligibility(trajectory)
            blocked = [
                reason
                for reason in eligibility.reasons
                if "secret" in reason or "hidden reasoning" in reason or "consequential" in reason
            ]
            if blocked:
                raise ForgeError("repair trajectory blocked: " + "; ".join(blocked))
            # Force verified flags for extraction by copying with verified outcome when extracting steps.
            try:
                manifest = extract_candidate_manifest(
                    trajectory,
                    require_eligible=False,
                    scope=active.manifest.scope,
                    created_by=created_by,
                )
            except ExtractionError as exc:
                raise ForgeError(str(exc)) from exc
        else:
            manifest = active.manifest.model_copy(deep=True)
            if manifest_patch:
                data = manifest.model_dump(mode="json")
                data.update(manifest_patch)
                manifest = SkillManifest.model_validate(data)
            manifest = sign_manifest(manifest)

        manifest.provenance = Provenance(
            source="repair",
            trajectory_ids=list(manifest.provenance.trajectory_ids),
            parent_version_id=active.version_id,
            created_by=created_by,
            notes=f"Repair candidate; active version {active.version_id} left intact",
        )
        manifest.rollback_target_version_id = active.version_id
        # Bump version string lightly
        manifest.version = _bump_patch(manifest.version)
        manifest = sign_manifest(manifest)

        candidate_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        now = utc_now()
        version = SkillVersion(
            version_id=version_id,
            skill_id=skill_id,
            status=LifecycleStatus.PROPOSED,
            manifest=manifest,
            created_at=now,
            immutable=False,
        )
        candidate = SkillCandidate(
            candidate_id=candidate_id,
            skill_id=skill_id,
            status=LifecycleStatus.PROPOSED,
            version=version,
            created_at=now,
            updated_at=now,
        )
        return save_candidate(candidate)

    def import_marketplace(
        self,
        payload: dict[str, Any] | SkillManifest,
        *,
        imported_from: str | None = None,
    ) -> SkillCandidate:
        return import_skill_manifest(payload, imported_from=imported_from)

    def run_pipeline(
        self,
        trajectory: JarvisTrajectoryV1 | dict[str, Any],
        *,
        actor: str | None = None,
        auto_activate: bool = False,
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        """Full observe→extract→sandbox→verify→(optional approve request). Never auto-activates."""
        if auto_activate:
            raise ForgeError("automatic publication is forbidden")
        observation = self.observe_trajectory(trajectory, auto_extract=False)
        if not observation["eligibility"]["eligible"]:
            return {**observation, "pipeline": "stopped_ineligible"}
        candidate = self.propose_from_trajectory(trajectory)
        candidate = self.sandbox(candidate.candidate_id, profile_id=profile_id)
        if candidate.status == LifecycleStatus.REJECTED:
            return {
                "eligibility": observation["eligibility"],
                "candidate": candidate.model_dump(mode="json"),
                "pipeline": "rejected_privilege",
            }
        candidate = self.verify(candidate.candidate_id)
        if candidate.status == LifecycleStatus.VERIFIED:
            candidate = self.request_owner_approval(candidate.candidate_id, actor=actor or "skill_forge")
        return {
            "eligibility": observation["eligibility"],
            "candidate": candidate.model_dump(mode="json"),
            "pipeline": "awaiting_approval" if candidate.status == LifecycleStatus.VERIFIED else "verification_failed",
            "activation_requires": "explicit owner/admin approve + activate",
        }

    def permission_preview(
        self,
        candidate_id: str,
        *,
        profile_id: str | None = None,
        task_capabilities: list[str] | None = None,
        node_capabilities: list[str] | None = None,
        parent_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        candidate = self._require(candidate_id)
        return compute_effective_capabilities(
            candidate.version.manifest,
            profile_id=profile_id,
            task_capabilities=task_capabilities,
            node_capabilities=node_capabilities,
            parent_capabilities=parent_capabilities,
        )

    def _require(self, candidate_id: str) -> SkillCandidate:
        candidate = get_candidate(candidate_id)
        if candidate is None:
            raise ForgeError(f"candidate not found: {candidate_id}")
        return candidate


def _bump_patch(version: str) -> str:
    parts = (version or "0.1.0").split(".")
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2].split("-")[0])
        return f"{major}.{minor}.{patch + 1}"
    except Exception:
        return f"{version}.repair"


forge = SkillForge()
