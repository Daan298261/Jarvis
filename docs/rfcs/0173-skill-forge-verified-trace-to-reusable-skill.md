# RFC-0173: Skill Forge — verified trace to reusable skill

**Status:** implemented
**Implemented:** #414 @ `e442b3314c9b9d03e6eff9bdc020f8e8db111a01` (`backend/app/skills/`, `/api/skill-forge/*`).
**Residuals:** Modules/Skills portal UI (UX); Desktop live soak N/A-unit-covered.
**Renumbered on development:** was incorrectly `RFC-0139` on main @ `ac18fb32` (collided with Android companion orb RFC-0139). Canonical on development is **RFC-0173**.  
**Date:** 2026-09-24

## Problem

Repeated successful work should become reusable capability, but autonomous self-modification from raw traces is unsafe and tends to preserve accidental behavior.

## Decision

Add a Skill Forge pipeline: observe eligible execution traces → extract a candidate procedure → generalize inputs/outputs → generate manifest/tests → replay in an isolated evaluation workspace → security/provenance review → owner/admin approval → publish versioned skill. Failed skills can generate repair candidates but cannot silently overwrite the active version.

A skill manifest declares purpose, input/output schema, tools, permissions, secrets, network/filesystem scope, compatible personas/models, examples, provenance, tests, version and rollback target. Promotion requires repeated success or an explicit owner request plus passing tests. Skills are signed/hashed and can be disabled/rolled back. Marketplace/imported skills enter quarantine and use the same evaluation pipeline.

## Acceptance criteria

- [x] Trace eligibility excludes secrets, hidden reasoning and unapproved consequential actions.
- [x] Candidate extraction produces typed manifests and deterministic tests.
- [x] Replay/evaluation is isolated and compares against golden criteria.
- [x] No automatic publication or privilege expansion.
- [x] Versioning, provenance, signatures/hashes, disable and rollback work.
- [x] Repair creates a new candidate version; active skill remains intact until approval.
- [x] Skill search/routing integrates with personas and Goal Runtime.

## Likely files

`backend/app/skills/`, policy/audit integration, evaluation harness, Modules/Skills UI, `tests/test_skill_forge_*.py`.
