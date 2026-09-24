# RFC-0173: Skill Forge — verified trace to reusable skill

**Status:** accepted
**Renumbered on development:** was incorrectly `RFC-0139` on main @ `ac18fb32` (collided with Android companion orb RFC-0139). Canonical on development is **RFC-0173**.  
**Date:** 2026-09-24

## Problem

Repeated successful work should become reusable capability, but autonomous self-modification from raw traces is unsafe and tends to preserve accidental behavior.

## Decision

Add a Skill Forge pipeline: observe eligible execution traces → extract a candidate procedure → generalize inputs/outputs → generate manifest/tests → replay in an isolated evaluation workspace → security/provenance review → owner/admin approval → publish versioned skill. Failed skills can generate repair candidates but cannot silently overwrite the active version.

A skill manifest declares purpose, input/output schema, tools, permissions, secrets, network/filesystem scope, compatible personas/models, examples, provenance, tests, version and rollback target. Promotion requires repeated success or an explicit owner request plus passing tests. Skills are signed/hashed and can be disabled/rolled back. Marketplace/imported skills enter quarantine and use the same evaluation pipeline.

## Acceptance criteria

- [ ] Trace eligibility excludes secrets, hidden reasoning and unapproved consequential actions.
- [ ] Candidate extraction produces typed manifests and deterministic tests.
- [ ] Replay/evaluation is isolated and compares against golden criteria.
- [ ] No automatic publication or privilege expansion.
- [ ] Versioning, provenance, signatures/hashes, disable and rollback work.
- [ ] Repair creates a new candidate version; active skill remains intact until approval.
- [ ] Skill search/routing integrates with personas and Goal Runtime.

## Likely files

`backend/app/skills/`, policy/audit integration, evaluation harness, Modules/Skills UI, `tests/test_skill_forge_*.py`.
