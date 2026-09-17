# RFC-0097: OpenCut / OpenMontage / Hyperframes BlackGrid video stitch

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md) ([PR #270](https://github.com/Daan298261/Jarvis/pull/270)).  
**Related (do not rewrite):** RFC-0096 ComfyUI/SANA gen. RFC-0058 / RFC-0059 BlackGrid. RFC-0021 artifacts. `JARVIS_2.0.md` §76 (Editing / Export).

This PR is **specs-only**. Do not commit local clones.

## Instagram source

Taco Instagram `@tacotcr` Saved → **jarvis**. Architect box clones (already downloaded; **do not commit**):

| Repo | Canonical | Local path |
| --- | --- | --- |
| OpenCut | [OpenCut-app/OpenCut](https://github.com/OpenCut-app/OpenCut) | `/workspace/projects/rfc/opencut` |
| OpenMontage | [calesthio/OpenMontage](https://github.com/calesthio/OpenMontage) | `/workspace/projects/rfc/openmontage` |
| Hyperframes | [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) | `/workspace/projects/rfc/hyperframes` |
| Real-ESRGAN (optional preprocess) | [xinntao/Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) | `/workspace/projects/rfc/real-esrgan` |

## Pipeline (RFC-0095 four-step)

| Step | Result (this RFC) |
| --- | --- |
| 1. Download | **Done locally** under `/workspace/projects/rfc/{opencut,openmontage,hyperframes,real-esrgan}`. Not vendored. |
| 2. Usefulness review | **Score 4/5.** Primary bucket: `black_grid_media`. Secondary: `module`. |
| 3. Integrate decision | **`partial`** — BlackGrid `timeline` / `stitch` connectors + optional Real-ESRGAN restore **preprocess**. Not a second NLE app inside Jarvis. Taco can override. |
| 4. Implement | Later named ticket. |

## Problem

BlackGrid `studio_capabilities()` lists `timeline` / `stitch` / `takes` / `artifacts` but nothing is connected. RFC-0096 (if implemented) can generate clips; Jarvis still cannot assemble a timeline, stitch takes, or restore/upscale before export. Instagram-jarvis saves name OpenCut (open CapCut-class editor), OpenMontage (agentic production pipelines), and Hyperframes (HTML→video for agents) as the stitch set. Real-ESRGAN is the restore/upscale pass (called out in RFC-0095/0096; owned here as optional preprocess, not as a generator).

## Decision

Add a **`black_grid_media` stitch connector** (`partial`) for BlackGrid `timeline` / `stitch`.

1. **OpenCut** — preferred interactive/timeline metaphor (cut, arrange takes, export). Jarvis drives it as a worker/API or headless export path, not by embedding the full OpenCut SPA as the Jarvis portal.
2. **OpenMontage** — optional agentic production-knowledge / pipeline skills for scripted stitch jobs (concat, captions, music bed) **behind** Jarvis policy. Do not replace the orchestrator with OpenMontage’s agent.
3. **Hyperframes** — optional HTML/template→video renderer for motion-graphic / agent-written frames. Use when the job is template render, not NLE editing.
4. **Real-ESRGAN** — **optional preprocess** on stills or frames before stitch/export (upscale/restore). Off by default; owner toggle. Not a gen backend (RFC-0096). Failure degrades to passthrough, not a fake “restored” artifact.
5. **Contract:** `studio_capabilities()` reports `timeline` / `stitch` available only when at least one stitch backend is reachable. Outputs are RFC-0021 artifacts. GPU-heavy restore follows §76 unload/reload.

**Architect’s initial recommendation:** `partial`. Taco can override.

**Will not:** vendor the three editors; ship OpenCut as the Jarvis UI; use Real-ESRGAN as image gen; rewrite RFC-0096; HexStrike; persona merge.

## Acceptance criteria

Pipeline steps below are **spec’d**, not implemented.

- [x] Download — spec’d (paths above; clones not committed)
- [x] Usefulness review — spec’d (4/5, `black_grid_media`)
- [x] Integrate decision — spec’d (`partial`; Taco may override)
- [ ] Implement — later named ticket (not this PR)
- [ ] BlackGrid `timeline` / `stitch` connector; OpenCut primary, OpenMontage/Hyperframes optional
- [ ] Real-ESRGAN optional preprocess; passthrough on failure; not a generator
- [ ] `studio_capabilities()` truthful for stitch operations
- [ ] Specs-only in this PR
- [ ] Implement follow-up: `python3 -m pytest`; if portal touched, `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | `backend/app/mobile/service.py`; `backend/app/api/companion.py`; `backend/app/studio/` stitch adapter(s); optional Real-ESRGAN preprocess worker |
| Frontend (implement PR only) | studio stitch/export status; not a full NLE chrome |
| Tests | `tests/test_rfc0097_*.py` — capabilities, preprocess passthrough, dest sandbox |
| Docs | this RFC; §59 batch line only |

## Out of scope

Product implementation in this PR. RFC-0096 gen. Vendoring upstream. Instagram scraper. HexStrike. Voice. Persona merge. Offensive tools (LE-gated under RFC-0095).

## Notes

- Parent RFC-0095 reserved this number. Linux cloud cannot sign off live FFmpeg/GPU stitch; unit-test the contract; desktop is sign-off.
- Implement launch: this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`.
