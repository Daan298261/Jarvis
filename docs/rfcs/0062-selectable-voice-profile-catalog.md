# RFC-0062: Selectable working TTS / voice profiles

**Status:** accepted  
**Queue item:** P1 — Selectable voice profile catalog  
**Author:** Jarvis Architect  
**Date:** 2026-09-09

## Problem

Taco wants Jarvis to offer multiple working TTS/voice options presented like familiar pop-culture archetypes (British butler, Cortana-like, Ultron-like, etc.). RFC-0056 defines an original butler voice runtime; RFC-0061 wires chat→TTS plus a single persona pack with `voice_profile_id`. There is not yet a **user-selectable catalog** of swappable voice profiles with clear legal/IP rules and a picker API. Users must not get copyrighted character clones.

## Decision

Extend RFC-0056/0061 with a **Voice Profile Catalog**:

1. **Catalog of voice profiles** — each entry is an original or properly licensed local (or explicitly licensed) voice pack, presented under an **archetype label** (marketing/UX name), never as a claim to be a copyrighted character.
2. **Picker API + settings** — list profiles, select active `voice_profile_id`, preview sample, persist selection. Default: butler-original (`jarvis_butler_v1` or successor from RFC-0056).
3. **Pack swap without per-model hacks** — changing voice profile updates TTS routing plus optional persona tone hooks via the portable layer (RFC-0061); LLM adapters must not need per-model voice strings.

### Hard IP / presentation rules (non-negotiable)

- MUST be **original local/licensed packs** plus **archetype presentation**.
- MUST NOT ship or recommend: Codsworth / Fallout / Stephen Russell samples or clones; Cortana / Microsoft Halo assets; Ultron / Disney Marvel assets; any “I am X” identity claims.
- UX copy uses archetype language only, e.g. `British butler (original)`, `Tactical soft-spoken aide (original)`, `Cold synthetic command (original)` — optional parenthetical “inspired by the *feel* of …” is allowed only if it does **not** name a protected character as the product voice and does not use trademarked names in the profile id or pack filename.
- Prefer: `id: butler_original_v1`, `archetype: british_butler`, `display_name: "Household butler (original)"`.
- Forbidden: `id: codsworth`, `display_name: "Codsworth"`, cloning from game/film audio.

### Profile contract (sketch)

```json
{
  "id": "butler_original_v1",
  "archetype": "british_butler",
  "display_name": "Household butler (original)",
  "license": "original|licensed|permissive_stock",
  "provenance": "...",
  "tts": { "engine_hint": "...", "speaker_ref": "...", "pack_path": "..." },
  "persona_hooks": { "register": "british_understated", "humour": "dry" },
  "sample_utterance": "At your service.",
  "vram_class": "edge|balanced|expressive"
}
```

Catalog ships with ≥1 working default (butler-original). Additional archetypes may ship as stubs that resolve only when a legal pack is installed; picker shows unavailable packs as install/unlock, not silent fake voices.

### API / hooks

- `GET /api/voice-profiles` (or equivalent settings API) → list with availability
- `PUT /api/voice-profiles/active` `{ "voice_profile_id": "..." }`
- `POST .../preview` optional short sample synthesis
- Chat→TTS (RFC-0061) and expressive runtime (RFC-0056) both read **active** profile
- Persona pack `tts.voice_profile_id` stays in sync with active selection

### Relation to other RFCs

| RFC | Ownership |
| --- | --- |
| RFC-0056 | Engines, expressive delivery, butler asset model — this RFC adds multi-profile catalog + picker; does not replace engine selection benchmarks |
| RFC-0061 | Chat→TTS + persona pack — this RFC supplies the selectable `voice_profile_id` catalog those packs point at |
| RFC-0055 | Commentary policy unchanged |

## Acceptance criteria

- [ ] Catalog schema + ≥1 default butler-original profile documented and loadable
- [ ] Picker/list + set-active API (or settings equivalent) works; selection persists
- [ ] Chat and voice paths use active profile without per-model prompt hacks
- [ ] IP guardrails enforced in docs and in validation (reject forbidden ids/names; no clone-from-copyrighted-sample path in product UI)
- [ ] Unavailable archetype packs fail clearly (install/license) rather than hallucinating a clone
- [ ] Preview or documented sample path for switching voices
- [ ] Unit tests for catalog load, active selection, forbidden-id rejection
- [ ] Unit tests pass (`python3 -m pytest`); if portal picker touched, `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend | voice profile registry, settings/API, TTS enqueue reads active id |
| Frontend | settings/voice picker (UX ticket later) |
| Packs | `voice_packs/` or install-relative packs with provenance |
| Tests | catalog + IP validation |

## Out of scope

Full RFC-0056 engine bake-off; training a new voice from scratch in this ticket; Astra UI / installer; shipping any copyrighted character assets; rewriting `JARVIS_MASTER_PLAN.md` in this PR.

## Notes

Taco’s Codsworth request is satisfied only via original butler-archetype feel (already RFC-0055/0056 policy), never a Fallout pack.
