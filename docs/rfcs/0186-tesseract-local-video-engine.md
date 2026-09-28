# RFC-0186: Mirage Tesseract local video engine

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-28

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md). Living index: [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) § 2026-09-28 reel batch (implement-first #4).  
**Extends:** [RFC-0097](0097-opencut-openmontage-hyperframes-blackgrid-stitch.md) BlackGrid `timeline` / `stitch`.  
**Related (do not rewrite):** RFC-0059 `studio_capabilities()`. RFC-0096 image/video gen. RFC-0109 media ingest. `JARVIS_2.0.md` §76 (read only). RFC-0187 image sidecar.

This file is **specs-only**. Do not vendor Mirage Tesseract or its CLI zip. No second NLE in the portal. Full intent. **No stubs / soft-fail.**

## Problem

BlackGrid can plan a stitch (RFC-0097) but has no local **agent video create/edit** engine for layered edits, motion graphics, and a keepable project file. Shipping a timeline UI inside Daybreak would duplicate the editor. Advertising `video` as available while no engine is installed is the RFC-0059 failure this ticket must not repeat.

## Goals

- Optional local Tesseract sidecar for BlackGrid video **create and edit**: cut, framing, dialogue/music, titles, diagrams, overlays, preview, render.
- Jarvis stays orchestrator. The owner (and the agent) work through CLI/skills against a `.tsrct` project. Outputs are Jarvis artifacts (RFC-0021) plus the project file.
- `studio_capabilities()` reports video create/edit available only when the pinned CLI runs and checksum-verifies. Otherwise `available: false` with a truthful detail.
- Upstream skills **Tesseract: Edit Video** and **Tesseract: Motion Graphics** are the procedure pack. Portal does not grow a second editor.

## Non-goals

- Replacing OpenCut / OpenMontage / Hyperframes (RFC-0097) or ComfyUI/SANA (RFC-0096). Tesseract is an additional engine the owner can enable.
- Embedding the Mirage UI, redistributing CLI binaries in Jarvis git, or skipping upstream product terms.
- A fake preview (still frame labeled as a render, or a success status with no output file).
- Invented LE / ATO gates. Exploit docs.

## Contract

| Rule | Requirement |
| --- | --- |
| Source | [mirage-hq/Tesseract](https://github.com/mirage-hq/Tesseract). Owner installs the CLI build that matches the skills’ required version (Windows x64, Linux x86_64, or the macOS build on a Mac). Verify the published `.sha256` before the first run. |
| Operations | BlackGrid asks: create or revise a `.tsrct`, render a preview, export a finished video. Inputs come from RFC-0109 artifacts or owner paths on the filesystem allowlist. |
| Skills | Load Edit Video and Motion Graphics from the local clone when the sidecar is enabled. Do not invent a parallel motion language in the portal. |
| Capabilities | `studio_capabilities()` gains a truthful video-edit/create fact for this engine, distinct from “Comfy video workflow registered” (RFC-0096) and from stitch connectors (RFC-0097). Absent CLI ⇒ that fact is false. |
| GPU / disk | Render stays on the owner machine. Failures return the CLI stderr summary and leave the project file in place. No silent passthrough that claims a finished video. |
| Terms | Install records that the owner is using upstream product terms. Jarvis does not relicense the CLI. |
| Fail | Portal timeline that is the deliverable. `available: true` without a live CLI. Export path outside the artifact store with no owner path. |

Preview-then-revise is in scope: a revision prompt re-opens the same `.tsrct` rather than starting from nothing unless the owner asked for a new project.

## Acceptance

- [x] Spec: local CLI sidecar, no second NLE, truthful capabilities, checksum
- [ ] Implement: enable → health check → create/edit/render writes artifacts and keeps `.tsrct`
- [ ] Implement: missing or checksum-mismatch CLI ⇒ `available: false` and a Download/repair CTA
- [ ] Implement: RFC-0097 stitch and RFC-0096 gen stay independently truthful
- [ ] Tests with a stub CLI (scripted success and failure), not a claim of a live GPU render (`tests/test_rfc0186_*.py`)
- [ ] Desktop sign-off later for a real Windows render; cloud VM cannot sign that off
- [ ] No CLI zip and no vendored tree in the specs PR

## Local clone

Not in git. The clone is the skills/docs tree; the CLI binary is an installed release, not a git submodule.

| Machine | Path |
| --- | --- |
| Architect box | `/workspace/projects/rfc/Tesseract` |
| Windows owner library | `C:\Users\daanv\projects\jarvis-ig\rfc\Tesseract` |

Upstream: https://github.com/mirage-hq/Tesseract

## Lane

**D1** (BlackGrid connector, capabilities, artifact handoff, tests). **UX** only if a studio status row must show this engine — not a new editor surface.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `studio_capabilities()` (today `backend/app/mobile/service.py`), BlackGrid worker / `backend/app/studio/` |
| Tests | `tests/test_rfc0186_*.py` |
| Docs | this RFC; [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md); §59 ledger only |

## Out of scope

Image gen (RFC-0187). Portal NLE. Rewriting `JARVIS_2.0.md`. Live GPU sign-off on a cloud VM.
