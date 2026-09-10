# RFC-0070: Higher-quality local TTS engines

**Status:** accepted
**Queue item:** P0 / P1 — Voice quality (owner: less robotic TTS)
**Author:** Jarvis Architect
**Date:** 2026-09-10

**Related (do not rewrite):** RFC-0061 chat→TTS + persona pack (`tts.voice_profile_id`, `speak_chat_replies`) — **implemented**; RFC-0062 selectable voice profile catalog — **implemented**; RFC-0064 Android realtime voice (host-side TTS must match desktop profile routing) — **implemented**; RFC-0068 spoken think-aloud — **implemented**; RFC-0056 expressive butler voice runtime / engine selection; RFC-0036 latency budgets + local TTS candidates (Piper baseline; Kokoro 82M candidate).

## Problem

Current local TTS still sounds robotic / low-fidelity to Taco despite chat→TTS (RFC-0061) and the selectable voice-profile catalog (RFC-0062). Host synthesis often falls through to OS/SAPI/espeak-class backends. Taco (2026-09-10) wants a **massive quality jump** — less robotic voice — via better local-friendly engines and voices, without cloud lock-in or IP-clone packs.

## Decision

Extend the RFC-0062 catalog with an explicit **engine adapter** layer so the active `voice_profile_id` selects a real local engine + speaker, not only a hint that falls back to system TTS.

### 1. Engine/voice catalog (additive to RFC-0062)

Extend profile `tts` metadata. Existing RFC-0062 fields stay (`id`, `archetype`, `display_name`, pack-level `license` / `provenance`, `persona_hooks`, `engine_hint`). `engine_hint` remains a backward-compatible alias for `engine_id`.

```json
{
  "id": "butler_natural_en_v1",
  "archetype": "british_butler",
  "display_name": "Household butler (natural)",
  "license": "original",
  "provenance": "...",
  "tts": {
    "engine_id": "kokoro",
    "engine_hint": "kokoro",
    "model_id": "kokoro-82m",
    "speaker_ref": "bf_emma",
    "pack_path": "voice_packs/butler_natural_en_v1",
    "vram_class": "balanced",
    "latency_class": "interactive",
    "license": "Apache-2.0",
    "offline": true,
    "quality_tier": "natural"
  },
  "persona_hooks": { "register": "british_understated", "humour": "dry" },
  "sample_utterance": "At your service."
}
```

| Field | Role |
| --- | --- |
| `engine_id` | Adapter key (`piper`, `kokoro`, future entries) |
| `model_id` / `speaker_ref` / `pack_path` | Weights and speaker the adapter loads |
| `vram_class` / `latency_class` / `license` / `offline` | Hardware, timing, and legal metadata; `offline` must be `true` for default-path engines |
| `quality_tier` | Picker label: `baseline` \| `natural` \| `expressive` |

This RFC does not rewrite the RFC-0061 persona pack.

### 2. Ranking and candidates

- **Piper/ONNX** remains **baseline / Dutch / low-resource** (RFC-0036). The default ship path must stay usable offline without a large download.
- **Kokoro 82M** (`hexgrad/Kokoro-82M`, Apache-2.0) is the primary English naturalness candidate to evaluate and ship **when quality wins** on the owner desktop (RTX 5070 Ti / CPU-NPU friendly).
- Additional open engines (for example StyleTTS2-class or other permissive local engines) may be added as **catalog entries** after CoS/Architect accept license + quality. CoS is also searching candidate repos. This RFC does **not** hard-require a specific new vendor.

Criteria for accepting a new catalog engine:

- Permissive or properly licensed weights (Apache-2.0 / MIT / documented commercial-ok); provenance recorded.
- Offline-capable; no cloud default.
- Beats the current robotic path on English butler lines (see §3).
- Meets RFC-0036 first-chunk / ack budgets on the canonical desktop, or documents graceful degrade to Piper (or another fast engine) for acknowledgements.
- Dutch remains viable (Piper `nl_NL` / `nl_BE` or a tested equivalent).
- No copyrighted-character clone packs.

### 3. Quality bar (must beat current)

Before flipping the **default** profile off the current robotic path, A/B on short butler lines vs today's default:

- naturalness; less metallic / robotic prosody; intelligibility;
- first-chunk speech respects RFC-0036 ack/streaming budgets on the canonical desktop, **or** documented ack-path fallback to a fast engine (Piper).

Cloud VMs cannot sign off live quality; desktop owner listen is required.

### 4. Routing

RFC-0062 active `voice_profile_id` selects engine + speaker. Chat→TTS (0061), think-aloud (0068), and Android companion host TTS (0064) all use the **same host TTS path**. No per-model prompt hacks. No Android transport redesign.

### 5. IP rules (unchanged from RFC-0062)

Original or licensed packs only. No Codsworth / Cortana / Ultron clones or trademarked ids. Archetype presentation only (`Household butler (original)`, never a protected character name as the product voice).

### 6. Installer / download

Higher-quality models are **optional packs**. The default offline install remains usable (Piper / current baseline). Large models are opt-in downloads with a clear license shown before fetch.

### Will not

- Cloud-only TTS as the default
- Rewrite the persona pack
- Redesign Android transport
- Ship or recommend copyrighted voice assets / clone packs
- Require the 27B model for speaking

## Acceptance criteria

- [ ] Documented engine+voice catalog schema extending RFC-0062 profile `tts` block
- [ ] Ranking: open local engines preferred; Piper remains baseline; ≥1 higher-quality English candidate named (Kokoro 82M) with license
- [ ] Quality bar: must subjectively/objectively beat current robotic default on owner desktop before flipping default profile
- [ ] Same active profile drives desktop chat→TTS and Android host TTS (0064)
- [ ] Latency: first-chunk speech respects RFC-0036 budgets or documented ack-path fallback to fast engine
- [ ] IP guardrails restated (no clone packs)
- [ ] Specs-only PR (no product code in this PR)

Implementation follow-up (not this PR): unit tests (`python3 -m pytest`); portal picker build if TS changes (`npm --prefix frontend run build`).

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/workers/voice.py` (adapters), `backend/app/voice_profiles/` (catalog / schema), download / pack install |
| Frontend | `frontend/src/tts/VoiceProfilePicker.tsx`, quality-tier labels |
| Tests | engine routing, forbidden ids, offline fallback |
| Docs | this RFC; optional §59 Decision Log line |

## Out of scope

Product implementation in this PR. Persona-pack rewrite (RFC-0061). Android realtime transport redesign (RFC-0064). Full RFC-0056 expressive-runtime bake-off (this RFC names the quality/engine catalog and evaluation bar; 0056 still owns style / delivery planner). Cloud-only TTS default. Training or cloning a copyrighted character voice.

## Notes

- Taco 2026-09-10: less robotic Jarvis voice; wants a massive quality jump.
- CoS assign to Jarvis Architect (specs-only). Catalog is expandable when CoS/Architect accept a license+quality candidate.
- RFC-0061 / 0062 / 0064 / 0068 are implemented; this RFC does not reopen those contracts except to extend the `tts` block.
- Kokoro 82M: `hexgrad/Kokoro-82M`, Apache-2.0 (also named in RFC-0036 / RFC-0056).
- Linux cloud VMs cannot verify live TTS quality or GPU latency; desktop sign-off on the owner machine.
