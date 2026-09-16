# RFC-0096: ComfyUI + SANA BlackGrid media gen module

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md) Instagram jarvis collection module catalog + Download ([PR #270](https://github.com/Daan298261/Jarvis/pull/270)).  
**Related (do not rewrite):** RFC-0058 Apex media parity. RFC-0059 BlackGrid capability contract (`studio_capabilities()`). RFC-0021 artifact crafts. RFC-0090 optional-worker Install now. RFC-0097 video stitch / Real-ESRGAN restore. `JARVIS_2.0.md` §76 multimedia.

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not commit local clones.

## Instagram source

Taco Instagram `@tacotcr` Saved → **jarvis**. Architect box clones (already downloaded; **do not commit**):

| Repo | Canonical | Local path |
| --- | --- | --- |
| ComfyUI | [comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI) | `/workspace/projects/rfc/comfyui` |
| SANA | [NVlabs/Sana](https://github.com/NVlabs/Sana) | `/workspace/projects/rfc/sana` |
| comfyui-ref2va-vsa (optional) | [Kablex/ComfyUI-Ref2VA-VSA](https://github.com/Kablex/ComfyUI-Ref2VA-VSA) | `/workspace/projects/rfc/comfyui-ref2va-vsa` |

Owner Download destination (RFC-0095): Desktop/`projects/<slug>` or library `projects/<slug>`.

## Pipeline (RFC-0095 four-step)

| Step | Result (this RFC) |
| --- | --- |
| 1. Download | **Done locally** under `/workspace/projects/rfc/{comfyui,sana,comfyui-ref2va-vsa}`. Not vendored into Jarvis git. |
| 2. Usefulness review | **Score 4/5.** Primary bucket: `black_grid_media`. Secondary: `module`. |
| 3. Integrate decision | **`partial`** — BlackGrid studio **connector** only (HTTP/API to a separately installed ComfyUI/SANA runtime). Not a whole-tree merge. Taco can override. |
| 4. Implement | Later named ticket after CoS names it. This RFC is the acceptance contract, not the code. |

## Problem

`JARVIS_2.0.md` §76 and RFC-0059 require BlackGrid Multimedia Studio (or equivalent) as a Jarvis worker. Companion `studio_capabilities()` still advertises `image` / `video` with `available: False` and must not look like a live generator. There is no local gen backend for BlackGrid `image` / `video`. Instagram-jarvis saves name ComfyUI (node graph, local GPU) and SANA (efficient diffusion) as the gen pair; Ref2VA-VSA is an optional Comfy custom-node path for reference-to-video, not a second studio.

## Decision

Add a **`black_grid_media` gen connector** (`partial`) that talks to an owner-installed ComfyUI (and optionally SANA) as the BlackGrid `image` / `video` backend.

1. **Jarvis stays orchestrator.** ComfyUI/SANA run as optional sidecars (local HTTP / workflow API). Do not vendor their trees. Do not make ComfyUI the portal or the primary app.
2. **Contract:** when the sidecar is reachable, `studio_capabilities()` may report `image` (and `video` if a video workflow is registered) as available; otherwise keep `available: False` with a truthful detail. Never advertise a placeholder as operational (RFC-0059).
3. **Jobs:** submit a bounded gen job (prompt, size, seed, workflow id, output dest under a Jarvis-managed artifacts dir). GPU-heavy steps follow §76: checkpoint agent state, load gen, run, validate, unload, restore the main model. Outputs become RFC-0021 artifacts (`image` / `video` file bundle), not chat blobs.
4. **SANA** is an optional high-efficiency diffusion backend reachable via Comfy custom nodes **or** a thin SANA HTTP adapter — same BlackGrid operations, not a second UI.
5. **comfyui-ref2va-vsa** is optional: enable only if the owner has that custom node installed; skip silently when absent.
6. **Real-ESRGAN** is **not** the gen backend. Mentioned here as a later restore/upscale pass on export; RFC-0097 owns stitch + optional Real-ESRGAN preprocess. Do not implement restore in this ticket.

**Architect’s initial recommendation:** `partial` connector into BlackGrid studio. Taco can override to `whole` / `archive_only`.

**Will not:** vendor ComfyUI/SANA; replace the 9B/27B chat model with a diffusion model as default; rewrite RFC-0097 stitch; fold Real-ESRGAN here; HexStrike; persona merge; offensive tools.

## Acceptance criteria

Pipeline steps below are **spec’d**, not implemented.

- [x] Download — spec’d (local paths above; clones not committed)
- [x] Usefulness review — spec’d (4/5, `black_grid_media`)
- [x] Integrate decision — spec’d (`partial`; Taco may override)
- [ ] Implement — later named ticket (not this PR)
- [ ] BlackGrid `image` (and optional `video`) connector to ComfyUI; SANA optional; Ref2VA-VSA optional
- [ ] `studio_capabilities()` truthful: available only when sidecar reachable; placeholder never looks live
- [ ] Gen outputs are artifacts under a Jarvis-managed dir; GPU load/unload per §76
- [ ] Specs-only in this PR
- [ ] Implement follow-up: `python3 -m pytest`; if portal touched, `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | `backend/app/mobile/service.py` (`studio_capabilities`); `backend/app/api/companion.py` (`/studio`); new `backend/app/studio/` or `backend/app/workers/blackgrid.py` Comfy/SANA adapter; artifact handoff |
| Frontend (implement PR only) | companion studio status; optional Tools/System worker row (RFC-0090 pattern) — not a ComfyUI clone UI |
| Tests | `tests/test_rfc0096_*.py` — capabilities false when sidecar down; job contract; no tree vendoring |
| Docs | this RFC; `JARVIS_MASTER_PLAN.md` §59 batch line only |

## Out of scope

Product implementation in this PR. RFC-0097 timeline/stitch. Real-ESRGAN restore (0097). Vendoring upstream. Instagram scraper. HexStrike. RFC-0092 voice. Persona merge. Offensive tools (Strix / Pentagi / Claude-Red stay LE-gated under RFC-0095).

## Notes

- Parent RFC-0095 reserved this number; Architect scored 2026-09-17. Linux cloud VMs cannot sign off live Comfy GPU gen — unit-test the connector contract; desktop GPU is sign-off.
- Implement launch: implement this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`; do not merge other PRs.
