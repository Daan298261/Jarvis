# RFC-0154: Artifact Workspace — files, previews, lineage and handoff

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Agents produce code, documents, images, datasets and reports. Treating these as chat attachments loses provenance and makes multi-agent work difficult.

## Decision
Create first-class Artifact records with immutable versions, MIME/type, creator persona/agent/task, source inputs, checksums, project, permissions and lineage. Provide preview/edit/open/export operations appropriate to type. Agents pass artifact references rather than copying large payloads through prompts. Integrate Git/worktrees for code artifacts and project folders for user files. Generated artifacts remain distinguishable from source evidence.

## Acceptance criteria
- [ ] Versioned artifact registry with lineage/checksums.
- [ ] Large artifacts are referenced/retrieved, not injected wholesale into prompts.
- [ ] Agent/Goal/Workflow handoffs use artifact IDs.
- [ ] Preview/download/export respect permissions and source ownership.
- [ ] Code artifacts can map to isolated worktrees/commits.
- [ ] UI exposes provenance and version history.

## Likely files
`backend/app/artifacts/`, projects/files, coding runtime, frontend workspace, tests.
