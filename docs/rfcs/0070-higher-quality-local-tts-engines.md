# RFC-0070: Higher-quality local TTS engines

**Status:** accepted
**Queue item:** P0 / P1 — Voice quality (owner: less robotic TTS)
**Author:** Jarvis Architect
**Date:** 2026-09-10

**Related (do not rewrite):** RFC-0061 chat→TTS + persona pack (`tts.voice_profile_id`, `speak_chat_replies`) — **implemented**; RFC-0062 selectable voice profile catalog — **implemented**; RFC-0064 Android realtime voice (host-side TTS must match desktop profile routing) — **implemented**; RFC-0067 owner chat chrome / greeting — **implemented**; RFC-0068 spoken think-aloud — **implemented**; RFC-0056 expressive butler voice runtime / engine selection; RFC-0036 latency budgets + local TTS candidates (Piper baseline; Kokoro 82M candidate).

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
| `engine_id` | Adapter key (`kokoro`, `chatterbox`, `orpheus`, `piper`, future entries) |
| `model_id` / `speaker_ref` / `pack_path` | Weights and speaker the adapter loads |
| `vram_class` / `latency_class` / `license` / `offline` | Hardware, timing, and legal metadata; `offline` must be `true` for default-path engines |
| `quality_tier` | Picker label: `baseline` \| `natural` \| `expressive` |

This RFC does not rewrite the RFC-0061 persona pack.

### 2. Ranking (canonical desktop: RTX 5070 Ti)

CoS candidate fold-in (2026-09-10). Open local engines only; original butler packs (RFC-0056 / 0062). Additional catalog entries may still land later when CoS/Architect accept license + quality.

| Rank | Engine | License | Role on Taco’s desktop |
| --- | --- | --- | --- |
| 1 | **Kokoro-82M** (`hexgrad/Kokoro-82M`) | Apache-2.0 | **Default low-latency English** path. CPU-friendly; preset voices; big step up from classic robotic TTS. |
| 2 | **Chatterbox / Chatterbox-Turbo** (Resemble) | MIT | Optional **quality** path when GPU VRAM is free (~4–6 GB). Best quality + cloning capability; commercial-safe. Use for “massive” quality when the owner selects it or an **expressive** profile. Cloning may only produce **original butler** packs — no actor/character clones. |
| 3 | **Orpheus 3B** | Apache-2.0 | Expressive / emotion tags; heavier. **Catalog entry, not default.** |
| Fallback | **Piper/ONNX** | Piper voice licenses | **Edge / Dutch / baseline** fallback (RFC-0036). Default ship path stays usable offline without a large download. Dutch remains viable (`nl_NL` / `nl_BE` or a tested equivalent). |

**Do not ship as product defaults:**

- **XTTS v2** — non-commercial license; not a product default.
- **F5-TTS** weights — CC-BY-NC; not a product default.

Criteria for accepting a further catalog engine (beyond the table):

- Permissive or properly licensed weights (Apache-2.0 / MIT / documented commercial-ok); provenance recorded. Non-commercial / CC-BY-NC engines stay out of the default ship path.
- Offline-capable; no cloud default.
- Beats the current robotic path on English butler lines (see §3).
- Meets RFC-0036 first-chunk / ack budgets on the canonical desktop, or documents graceful degrade to Kokoro or Piper for acknowledgements.
- No copyrighted-character clone packs.

### 3. Quality bar (must beat current)

Before flipping the **default** profile off the current robotic path, A/B on short butler lines vs today's default:

- naturalness; less metallic / robotic prosody; intelligibility;
- first-chunk speech respects RFC-0036 ack/streaming budgets on the canonical desktop, **or** documented ack-path fallback to Kokoro (or Piper).

Cloud VMs cannot sign off live quality; desktop owner listen is required.

### 4. Routing

RFC-0062 active `voice_profile_id` selects engine + speaker. Chat→TTS (0061), think-aloud (0068), and Android companion host TTS (0064) all use the **same host TTS path**. No per-model prompt hacks. No Android transport redesign.

Purpose / latency-class sketch (aligns RFC-0056 `voice.fast` / `balanced` / `expressive` with this ranking):

| Purpose | Engine |
| --- | --- |
| `voice.fast` / ack | Kokoro (or Piper if Kokoro unavailable / Dutch) |
| `voice.balanced` | Kokoro |
| `voice.expressive` | Chatterbox when VRAM allows (~4–6 GB free); else Kokoro |
| Orpheus | Opt-in catalog profile only; never the silent default |

Primary 9B/27B inference must not be evicted merely to speak a non-urgent line (RFC-0056). If Chatterbox cannot get VRAM, fall back to Kokoro rather than blocking speech.

### 5. Speakable content filter

The host TTS pipeline (RFC-0061 chat→TTS) speaks **final conversational text** and allowed persona lines only. When the owner opens “thought process” / Show work / plan chrome (RFC-0067 power-user disclosure), **TTS must not narrate** that content.

**Do not speak:** URLs, code, stack traces, PLAN / END STATE / ACCEPTANCE boards, tool dumps, or raw thought-process text.

**Speak only:**

- the final assistant reply / conversational output;
- short humoristic / persona think-aloud lines (RFC-0068) and greetings (RFC-0067);
- dry original British-butler register commentary.

This aligns RFC-0067 hide-chrome-by-default with RFC-0061: the speak path filters to final conversational text + allowed persona lines, regardless of which engine adapter is selected.

### 6. IP rules (unchanged from RFC-0062 / 0056)

Taco’s “Codsworth-like voice” means **feel** (dry household butler), not a character clone. Original or licensed packs only. MUST NOT clone Codsworth / Fallout / Stephen Russell, Cortana, Ultron, or any trademarked id. UX uses archetype language only (`Household butler (original)`), never a protected character name as the product voice.

### 7. Installer / download / out-of-box butler

Taco hard rule: listing voices that show `install_required` without a trivial install path is a **fail**.

- The **default household butler pack** (original, RFC-0056 / 0062) must **work out of the box after Windows Setup** — no extra download, no Settings hunt, no silent `install_required`.
- Kokoro (and Piper) stay on the default ship path so first speech is usable offline. Prefer **bundling** the default English Kokoro butler pack (and Dutch Piper if shipped) in Windows Setup.
- Any catalog profile that is not bundled must be reachable via **one-click or an extremely short “Get more voices”** flow in Settings (bundle in Setup **or** that one-click path — not a listing-only stub).
- Chatterbox and Orpheus remain **optional packs** — opt-in downloads with a clear license shown before fetch. Large GPU models must not be required for first speech.

### Will not

- Cloud-only TTS as the default
- Rewrite the persona pack
- Redesign Android transport
- Ship or recommend copyrighted voice assets / actor or character clone packs
- Ship XTTS v2 or F5-TTS (CC-BY-NC) as product defaults
- Require the 27B model for speaking
- Narrate thought-process / Show work / plan chrome, URLs, or code
- Ship catalog voices as listing-only `install_required` stubs with no Setup bundle or one-click install

## Acceptance criteria

- [ ] Documented engine+voice catalog schema extending RFC-0062 profile `tts` block
- [ ] Ranking: Kokoro-82M (Apache-2.0) default low-latency English; Chatterbox/Turbo (MIT) optional quality; Orpheus 3B (Apache-2.0) catalog not default; Piper remains edge/Dutch/baseline; XTTS v2 and F5-TTS (CC-BY-NC) are not product defaults
- [ ] Quality bar: must subjectively/objectively beat current robotic SAPI/espeak/pyttsx3 stack on owner desktop before flipping default profile
- [ ] Default household butler pack works out of the box after Windows Setup (no extra download)
- [ ] Profiles that would show `install_required` are either bundled in Setup or installed via one-click / extremely short “Get more voices” in Settings — listing-only stubs fail
- [ ] Same active profile drives desktop chat→TTS and Android host TTS (0064)
- [ ] Latency: first-chunk speech respects RFC-0036 budgets or documented ack-path fallback to Kokoro/Piper
- [ ] IP guardrails restated (no clone packs; “Codsworth-like” is feel only)
- [ ] TTS never speaks thought-process / Show work / plan chrome, URLs, code, stack traces, or tool dumps
- [ ] Specs-only PR (no product code in this PR)

Implementation follow-up (not this PR): unit tests (`python3 -m pytest`); portal picker build if TS changes (`npm --prefix frontend run build`).

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/workers/voice.py` (adapters), `backend/app/voice_profiles/` (catalog / schema), download / pack install, speak filter |
| Frontend | `frontend/src/tts/VoiceProfilePicker.tsx`, quality-tier labels, “Get more voices” |
| Installer | Windows Setup bundle for default butler / Kokoro (see `INSTALLER.md` — Architect spec only; this RFC does not overwrite `installer/windows/`) |
| Tests | engine routing, forbidden ids, offline fallback, speak-filter (no thought-process / URL / code), OOB butler availability |
| Docs | this RFC; optional §59 Decision Log line |

## Out of scope

Product implementation in this PR. Persona-pack rewrite (RFC-0061). Android realtime transport redesign (RFC-0064). Full RFC-0056 delivery-planner bake-off (this RFC names engines, licenses, VRAM, routing, and the speak filter; 0056 still owns style / delivery planner). Cloud-only TTS default. Training or cloning a copyrighted / actor / character voice (including Codsworth / Fallout / Stephen Russell). Shipping XTTS v2 or F5-TTS as product defaults.

Informational only — **not** acceptance criteria and not this ticket: MediaPipe face look-at, Morphix, and privacypuppet-style mouse+webcam head follow are UX tracking refs for a **later presence ticket**.

## Notes

- Taco 2026-09-10: less robotic Jarvis voice; wants a massive quality jump.
- CoS assign to Jarvis Architect (specs-only). CoS candidate fold-in names Kokoro / Chatterbox / Orpheus / Piper with licenses and VRAM notes.
- RFC-0061 / 0062 / 0064 / 0067 / 0068 are implemented; this RFC does not reopen those contracts except to extend the `tts` block and to state the speak filter. Host TTS path stays shared.
- RFC-0056 butler voice remains original; Chatterbox cloning is pack-creation capability, not a product clone of named actors/characters.
- Linux cloud VMs cannot verify live TTS quality or GPU latency; desktop sign-off on the owner machine.
