# RFC-0043: LM Studio graded model profiles

**Status:** accepted  
**Queue item:** P1 — LM Studio graded model profiles  
**Author:** Jarvis Architect (Taco ask via CoS)  
**Date:** 2026-09-08

## Problem

Jarvis already supports LM Studio as an inference backend and named `RuntimeProfile` objects (RFC-0003), but the portal model picker does not help users choose among the GGUFs they have downloaded in LM Studio. Taco's desktop inventory contains many similarly sized Qwen-family models with overlapping names and quantizations; picking the right one for coding, writing, agents, or tight VRAM is guesswork.

Users need a **curated, graded catalog** of named profiles bound to on-disk LM Studio GGUFs — sorted by overall quality, with videogame-style hover stats, VRAM fit warnings (RFC-0018), and pin/favorite support — without rewriting RFC-0003 `AUTO` routing.

## Decision

Extend the user-facing model catalog and picker (RFC-0003) with **LM Studio graded model profiles**:

1. **Discover** GGUF artifacts under the host LM Studio models directory (default `C:\Users\daanv\.lmstudio\models`), skipping `mmproj` sidecars and non-GGUF files.
2. **Match** discovered files to a versioned **graded profile catalog** (provisional axes and overall rank; see Notes).
3. **Expose** a catalog API that merges discovered on-disk models with graded metadata, compatibility hints from RFC-0018 node probes, and user overrides (pin/favorite, manual grade override).
4. **Render** in both **HUD** and **Classic** portal pickers: list sorted by overall grade (best first); hover card shows per-axis bars, strength/weakness blurbs, size/quant, and resolved path/id.
5. **Bind** each selectable row to an RFC-0003 `RuntimeProfile` (or create/update one on selection) so routing, pinning, and `AUTO` continue to work unchanged.

Grades are **provisional** — derived from public benchmark families and maintainer notes, not live Jarvis harness measurements. The UI must label them as estimates and allow manual override.

VRAM policy (RFC-0018): profiles whose declared weight footprint exceeds ~16 GB effective VRAM on the active node are **hidden by default** with an explicit "show anyway" toggle and a warning badge; profiles between ~12–16 GB show a caution state.

Do **not** change `AUTO` routing scoring, download models, or claim absolute benchmark truth.

## Acceptance criteria

- [ ] LM Studio GGUF discovery scans the configured models root, indexes `.gguf` files, extracts size/quantization hints from filenames, and skips `mmproj` artifacts.
- [ ] Catalog API returns graded profiles merged with discovery results: overall rank, per-axis scores (1–10), strength, weakness, weight GB, quantization, filesystem path, stable profile id, pin/favorite state, and RFC-0003 `RuntimeProfile` binding id when set.
- [ ] List sort order is **overall grade descending**; pinned/favorited profiles sort above unpinned within the same band.
- [ ] HUD and Classic portal model pickers consume the catalog API and show the videogame hover card (overall label, seven axis bars, strength, weakness, size/quant, path/id).
- [ ] Selecting a catalog row creates or updates the bound `RuntimeProfile` (provider `lmstudio`, correct model id/path, quantization, local-only privacy) without altering `AUTO` router logic.
- [ ] Node VRAM probe (RFC-0018) drives hide/warn: `>16 GB` footprint → hidden unless user opts in; `12–16 GB` → visible with warning.
- [ ] Provisional grades, source citations, and per-profile notes are stored in versioned catalog data; user manual grade override persists locally.
- [ ] Pin/favorite persists per profile id and is reflected in API and UI.
- [ ] Unit tests cover discovery (including mmproj skip), catalog merge, sort order, VRAM hide/warn thresholds, profile binding, and override persistence.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal code changes, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/backends.py` (LM Studio paths), new `lmstudio_catalog.py` or equivalent, `backend/app/inference/runtime_profiles.py`, `backend/app/api/` catalog endpoint |
| Schemas | graded profile catalog schema, discovery result models |
| Frontend | HUD model picker, `frontend/src/pages/Model.tsx`, `frontend/src/pages/RuntimeProfiles.tsx`, shared hover card component |
| Tests | `tests/test_lmstudio_catalog.py`, discovery/VRAM fixture tests |
| Data | `backend/app/data/lmstudio_graded_profiles.json` (or `data/` runtime seed) |

## Out of scope

- Rewriting RFC-0003 `AUTO` routing policy or router scoring.
- Model downloads, LM Studio install, or new inference engines.
- Claiming absolute or Jarvis-measured benchmark rankings (live harness admission is RFC-0037).
- Replacing RFC-0018 `RuntimeManifest` install flows; this RFC only consumes VRAM compatibility signals.
- Qwen3.8-9B profiles (not present on disk; see Notes).

## Notes

### Related RFCs

- **RFC-0003** — `RuntimeProfile` binding and picker integration; `AUTO` routing untouched.
- **RFC-0018** — VRAM / hardware-aware hide and warn thresholds.
- **RFC-0037** — future path to replace provisional grades with admission evidence.

### LM Studio inventory (Taco desktop, 2026-09-08)

Root: `C:\Users\daanv\.lmstudio\models` (exclude `mmproj`).

| Weight (GB) | Artifact (short) |
| ---: | --- |
| 21.2 | Qwen3.6-40B Deck-Opus NEO-CODE Q4_K_S |
| 16.5 | Ortenzya Gemma4-31B Q4 |
| 15.9 | Qwen3.8-27B TurboFCFusion Q4 |
| 15.4 | Qwen3.6-27B stock Q4 |
| 15.1 | Qwen3.6-27B heretic Q4 |
| 14.0 | Qwen3.6-35B-A3B Q2 |
| 11.3 | Qwen3.8-27B MTP IQ2 |
| 10.0 | Qwen3.5-9B Defiant Q8 |
| 6.9 | Ornith-1.0-9B Q6 |
| 6.1 | Qwen3.5-9B Defiant Q4 |
| 4.4 | Llama-3.1-8B Q4 |

**Gap:** No Qwen3.8-9B on disk. Closest small Qwen is Qwen3.5-9B Defiant; Qwen3.8 family entries are 27B-class only.

### Provisional graded profiles (overall desc)

Axes are scored **1–10** (higher is better). Overall rank sorts the default picker. Grades cite public benchmark families (e.g. MMLU-style reasoning, HumanEval/SWE-bench coding proxies, MT-Bench writing, LMSYS arena trends) — **not** absolute truth.

| Rank | Profile id | Display name | Matched GGUF | Overall | Coding | Writing | Reasoning | Speed/Cost | VRAM fit | Instruction | Uncensored |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `lm-best-overall` | Best overall | Qwen3.8-27B TurboFCFusion Q4 | 9.2 | 9 | 8 | 9 | 6 | 5 | 9 | 7 |
| 2 | `lm-coding-heavy` | Coding heavy | Qwen3.6-40B Deck-Opus NEO-CODE Q4_K_S | 8.9 | 10 | 7 | 8 | 4 | 3 | 8 | 8 |
| 3 | `lm-coding-moe` | Coding MoE | Qwen3.6-35B-A3B Q2 | 8.4 | 9 | 7 | 8 | 7 | 6 | 8 | 7 |
| 4 | `lm-balanced-27b` | Balanced 27B | Qwen3.6-27B stock Q4 | 8.1 | 8 | 8 | 8 | 6 | 5 | 8 | 6 |
| 5 | `lm-creative` | Creative / marketing | Ortenzya Gemma4-31B Q4 | 7.8 | 6 | 9 | 7 | 5 | 4 | 8 | 8 |
| 6 | `lm-cheap-coding-9b` | Cheap coding 9B | Qwen3.5-9B Defiant Q4 | 7.2 | 8 | 6 | 7 | 9 | 9 | 7 | 7 |
| 7 | `lm-agent-9b` | Agent 9B | Ornith-1.0-9B Q6 | 7.0 | 7 | 6 | 7 | 8 | 9 | 8 | 6 |
| 8 | `lm-legacy-cheap` | Legacy cheap | Llama-3.1-8B Q4 | 5.5 | 5 | 6 | 5 | 10 | 10 | 6 | 5 |

**Strength / weakness blurbs (hover copy):**

| Profile | Strength | Weakness |
| --- | --- | --- |
| Best overall | Strong all-rounder; best default for mixed Jarvis tasks | ~16 GB VRAM; slower than 9B |
| Coding heavy | Top-tier code generation and refactors | 21 GB footprint; slow on 16 GB cards |
| Coding MoE | MoE efficiency; good code/reasoning per GB | Q2 quality loss; MoE runtime quirks |
| Balanced 27B | Stable Qwen3.6 generalist | Superseded by 3.8 Turbo on same VRAM |
| Creative / marketing | Voice, ads, long-form prose | Weaker coding vs Qwen 27B/40B |
| Cheap coding 9B | Fast, low VRAM, solid tool loops | Not for hardest reasoning |
| Agent 9B | Tuned for agentic tool use | Smaller context/world knowledge |
| Legacy cheap | Tiny footprint, always fits | Clearly below modern Qwen tiers |

### Hover card (videogame stats)

On pointer hover (desktop) or long-press (touch), show a compact card:

```text
┌─────────────────────────────────────┐
│ ★ Best overall          Overall 9.2 │
├─────────────────────────────────────┤
│ Coding      ████████░░ 9            │
│ Writing     ████████░░ 8            │
│ Reasoning   █████████░ 9            │
│ Speed/Cost  ██████░░░░ 6            │
│ VRAM fit    █████░░░░░ 5  ⚠ ~16 GB  │
│ Instruction █████████░ 9            │
│ Uncensored  ███████░░░ 7            │
├─────────────────────────────────────┤
│ + Strong all-rounder; mixed tasks   │
│ − Heavy VRAM; slower than 9B        │
├─────────────────────────────────────┤
│ 15.9 GB · Q4 · lm-best-overall      │
│ …/Qwen3.8-27B-TurboFCFusion-Q4.gguf │
└─────────────────────────────────────┘
```

Bars map linearly from axis score (1–10). VRAM row uses RFC-0018 compatibility tint (green / amber / red). Footer shows weight, quantization, profile id, and truncated path.

### Catalog configuration

- Default models root: `%USERPROFILE%\.lmstudio\models` on Windows; override via settings/env.
- Catalog version field increments when grades or profile rows change.
- `source_notes` per profile: short citation string (e.g. "SWE-bench proxy; LMSYS Qwen3.8 trend — provisional").
- Unmatched discovered GGUFs appear in an **Ungraded** section (filename + size only) without overall rank.

### RFC-0003 binding

Each graded profile maps to:

```yaml
provider: lmstudio
privacy_class: local-only
is_local: true
model: <lmstudio model id or gguf stem>
quantization: <parsed quant>
capability_tags: [llm_inference, text, graded-catalog]
specialization_tags: [<profile-specific>]
```

Selecting a profile in the picker sets the active `RuntimeProfile` id; `AUTO` may still override per RFC-0003 unless the user pins.
