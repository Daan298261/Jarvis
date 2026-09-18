# RFC-0118: Taco goals — highest-leverage improvements (decision memo)

**Status:** accepted (decision memo — **not** an implement contract)  
**Queue item:** (none — no new §58 checkbox)  
**Author:** Jarvis Architect (Taco goals pass, 2026-09-18)  
**Date:** 2026-09-18

**Parent:** [`JARVIS_MASTER_PLAN.md`](../../JARVIS_MASTER_PLAN.md) §59. [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) Taco ladder.  
**Related (do not rewrite):** RFC-0108 (in-flight), RFC-0109 (amended this PR), RFC-0115, RFC-0117 tiny-front (implemented; colliding journal RFC-0117 stays accepted), RFC-0107 (accepted until desktop sign-off), RFC-0005 (implemented), RFC-0020 (accepted, thin), RFC-0110 (implemented), RFC-0114 (implemented). Thin new contracts: [RFC-0120](0120-coding-and-3d-real-tools.md), [RFC-0121](0121-projects-folder-chats-db-media-placement.md). **RFC-0119 is reserved** for a parallel license-package entitlements RFC — this memo does not take that number.

This file is a **light decision memo**. It ranks work. It does **not** replace the named implement RFCs. Full intent; **no stubs / soft-fail**. No invented LE / Red / Purple / ATO gates. Draft [#282](https://github.com/Daan298261/Jarvis/pull/282) stays unmerged / out of scope. Bulk IG **0095–0104** stay later. HOLD Sol TTS **0092 / 0112** unless already landed (0111 Kokoro runtime **is** implemented; 0112 remains HOLD).

## Problem

Taco’s near-term product goals are:

1. **Response speed**
2. **Tool calling for coding + 3D modelling** — real tools, not stubs
3. **OCR + media upload** on phone and desktop
4. **Projects folder structure** with chats in the internal DB; media on disk/path if the same PC as the DB-host node, else a storage node

The spec set already covers large parts of this (0108/0109/0115/0117/0107/0005/0020). Duplicate front-responder or third media RFCs would steal the 0108 lane. This memo picks **at most five** highest-leverage next steps and says reuse vs new.

## In-flight assumption

**RFC-0108** (phone companion offline AI) continues. D1+UX are implementing it now. CoS: **0109 after 0108**. This memo does not divert that lane.

## Ranked items (≤5)

### 1 — Finish **RFC-0109** media ingest, amended for explicit OCR

| | |
| --- | --- |
| **Maps to** | Goal 3 (OCR + media upload on phone and desktop) |
| **Reuse vs new** | **Reuse / amend RFC-0109** (`accepted`). This PR amends 0109 so analyze **requires OCR** for images and photos of text on **phone and desktop**, not only vision/describe, Whisper, and extract-text-from-documents. **No third media RFC.** |
| **Why it wins** | Desktop Chat is still text-only; companion attach is a thin blob POST. Without ingest, OCR has nothing to read. 0109 already specified one artifact store, both surfaces, and analyze — the gap is photos of whiteboards/receipts/pages, which vision/describe does not guarantee as text. |
| **Order vs 0108** | **After 0108.** Specs amend lands now; implement ticket is the CoS-named 0109 follow-up. |

### 2 — Implement **RFC-0115** Ornith complexity router + visible handoff

| | |
| --- | --- |
| **Maps to** | Goal 1 (response speed) and better model selection for tools (goal 2) |
| **Reuse vs new** | **Reuse RFC-0115** (`accepted`, not implemented). RFC-0117 tiny front responder is **implemented** (#305); RFC-0114 preflight is **implemented**. Do **not** invent a duplicate front-responder RFC. Remaining speed leverage is router/tier/handoff so Ornith does not attempt coding/architecture until it 400s. |
| **Why it wins** | First-token latency is already addressed in code by the warm `front_responder` lane; perceived slowness on real work is still “wrong model stays loaded.” 0115 gates capability **before** warm-score and hands off automatically — that is the next speed *and* tool-quality win. |
| **Order vs 0108** | **After 0108, then after or overlapping 0109 implement** if lanes differ (0109 is UX+ingest; 0115 is inference/router). Do not block 0108. 1.4 suggested split: PR 1 roles/tiers/gates, then PR 3 visible switch + handoff — both remain 0115. |

### 3 — **RFC-0120** coding + 3D modelling **real tools**

| | |
| --- | --- |
| **Maps to** | Goal 2 (tool calling for coding + 3D modelling) |
| **Reuse vs new** | **New thin RFC-0120.** RFC-0005 (`implemented`) is worktree isolation, not a coding/3D tool contract. Native `filesystem` / `terminal` / `python` / `git` / `verify_code` exist; `code_worker` is optional OpenHands. There is **no** Blender / OpenSCAD / local DCC tool. 0120 demands real edit/run/test calls and a real 3D CLI path, discovered via RFC-0107 tool search, gated by RFC-0110 approvals. **Do not use 0119** (reserved for license-package entitlements). |
| **Why it wins** | Isolation without mandatory tool execution still lets a model “complete” coding in chat. 3D is absent from the registry. One contract covering both keeps coding and modelling on the same no-stub bar. |
| **Order vs 0108** | **After 0115** (specialist/expert routing must exist so Ornith/front_responder are not the coding/3D worker). May start design/tests in parallel with 0109 implement; do not land a stub 3D tool while 0108 is the named product ticket. |

### 4 — **RFC-0121** projects folder + chats-in-DB + media placement

| | |
| --- | --- |
| **Maps to** | Goal 4 (projects folder structure; chats in internal DB; media on disk colocated with DB-host, else storage node) |
| **Reuse vs new** | **New thin RFC-0121** (extends, does not replace, RFC-0020). RFC-0020 (`accepted`) is knowledge retrieval/workspaces — too thin for folder layout, chat persistence, and blob topology. Portal Projects today are **browser `localStorage`** (`frontend/src/projects.ts`); `conversations` already live in SQLite but are not project-scoped. `PORTAL_UX.md` currently says portal-local grouping and no new REST resource — 0121 supersedes that for durable projects (Architect updates `PORTAL_UX.md` after accept; this PR does not edit that file). |
| **Why it wins** | Taco’s ask is storage topology, not another RAG adapter. Chats must survive browser wipes and follow the Leader DB; media bytes must not be stuffed into SQLite or left only on the phone. Colocate with the DB-host PC when that is the same machine; otherwise the swarm **Storage Node** (`SWARM_ARCHITECTURE.md` §2). |
| **Order vs 0108** | **After 0109 implement** for media placement (ingest contract must exist). Chats-in-DB + folder layout can start as soon as 0108 is no longer the sole named ticket, but blob paths should land with or immediately after 0109. |

### 5 — Residual speed: **RFC-0107** remaining hot-path use (reuse)

| | |
| --- | --- |
| **Maps to** | Goal 1 (speed via smaller prompts / right tools) and enables goal 2 (per-turn tool search) |
| **Reuse vs new** | **Reuse RFC-0107** (`accepted`). Vault bind / index / working-set / tool search and the Obsidian embed host **landed in code**; the ledger stays **accepted** until Taco **desktop sign-off**. Do **not** tick 0107 implemented. Do **not** open Pipecat RFC-0101 now (bulk **0095–0104** stay later; 0101 is TTS-adjacent while 0092/0112 remain HOLD). Do **not** deepen 0117 with a new RFC — remaining 0117 work is Windows first-visible / first-audible measurement. RFC-0085 fast-path is largely covered by 0117; leave it, do not duplicate. |
| **Why it wins** | Survey: further front-responder architecture is already shipped; Pipecat is a later voice transport. The remaining 0107 gap is proving the bound vault and per-turn tool search actually enter owner turns (not décor). That cuts prompt junk (speed) and is how 0120 tools get pulled without stuffing the catalog. |
| **Order vs 0108** | **Non-blocking residual.** Desktop sign-off / use-path proof can proceed whenever a Windows session is available. It must not steal the 0108 implement lane or jump ahead of 0109/0115 as a new cloud ticket. |

## Suggested implement order (relative to 0108)

```text
RFC-0108 continues          (in-flight; do not divert)
    → RFC-0109 implement    (amended OCR; CoS: after 0108)
    → RFC-0115 implement    (remaining 1.4 router/speed)
    → RFC-0120 implement    (coding + 3D real tools; needs 0115 + 0107 search + 0110)
    → RFC-0121 implement    (projects + chats-in-DB; media paths with/after 0109)
RFC-0107 remaining          (desktop sign-off / hot-path use; never falsely ticked implemented)
RFC-0117 remaining          (desktop first-visible/audible; no new RFC)
RFC-0095–0104, 0101         (later)
RFC-0092 / 0112             (HOLD unless already landed)
draft #282                  (out of scope)
```

## What this memo will not do

- Divert D1+UX off RFC-0108.
- Add a third media RFC or a second front-responder RFC.
- Take **RFC-0119** (reserved for license-package entitlements, parallel Architect ticket).
- Tick RFC-0107 implemented.
- Merge draft #282.
- Promote bulk Instagram / Pipecat / persona RFCs.
- Edit product code in this PR.
- Invent LE / Red / Purple / ATO gates or exploit recipes.

## Acceptance criteria

- [x] Light RFC-style memo at this path, status `accepted` as a decision memo
- [x] ≤5 ranked items with reuse-vs-new, Taco goal mapping, why, and order vs 0108
- [x] RFC-0109 amended for explicit OCR (phone + desktop)
- [x] At most two new implement RFCs: **0120** (coding+3D), **0121** (projects/chats/media placement). **0119 unused here.**
- [x] §59 Decision Log pointer only (no §57/§58 rewrite)
- [ ] Implementers take the **named** RFC (0109 / 0115 / 0120 / 0121 / 0107 remaining), not this memo, as the ticket

## Out of scope

Product implementation. Swarm P3 scheduling. BlackGrid gen engines (0096/0097). HexStrike. Persona merge. License issuer. Spec-doc rewrites other than §59 pointer + this RFC pack.

## Notes

- Number **0118** — the two existing 0117 files (tiny-front **implemented**; durable-state journal **accepted**) are left as-is. **0119 is reserved** (license-package entitlements, parallel ticket). Thin implement RFCs from this memo are **0120** and **0121** only.
- Linux cloud: specs-only. Live model load, OCR on camera photos, Blender/OpenSCAD, and Obsidian.exe remain desktop/device sign-off on the implement tickets.
