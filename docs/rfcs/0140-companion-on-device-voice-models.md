# RFC-0140: Companion on-device small voice models (fallback + grid-down)

**Status:** accepted  
**Queue item:** §58 RFC backlog — RFC-0140  
**Author:** Jarvis Architect  
**Date:** 2026-09-23  

**Related (do not rewrite):** [RFC-0108](0108-phone-companion-offline-ai-model.md) (on-device **LLM** pack — sibling; this RFC is **STT/TTS voice**). [RFC-0064](0064-realtime-voice.md) / companion WSS voice when online. [RFC-0092](0092-neural-tts-default-no-silent-sapi.md) (PC neural TTS; **do not** reintroduce silent SAPI on the PC). [RFC-0062](0062-selectable-voice-profile-catalog.md) Desktop voice profiles / Kokoro-on-PC. [RFC-0075](0075-social-vs-technical-speak-path.md) speak path. [RFC-0123](0123-companion-reachability-and-anti-impersonation.md). [RFC-0125](0125-companion-hud-lan-pair.md). [RFC-0139](0139-android-companion-fancy-orb-humanoid-ui.md) presence chrome while speaking/listening offline.

This PR is **specs-only**. Product code is a **named follow-up**. Full intent; **no stubs / soft-fail**. Quality bar: multibillion-company / **Anzu 1.0**. Subpar implement → **CoS → Taco** in review.

## Problem

When the PC / gateway / LAN is down, the companion still needs **usable speech in and speech out**. RFC-0108 covers the offline **LLM**. Phone OS speech APIs alone are uneven, often cloud-backed, and are not a durable private fallback. Online, the product correctly prefers Leader / Kokoro-on-PC paths (RFC-0062 / RFC-0092 / RFC-0064). Offline and grid-down need an explicit **on-device** STT and TTS pack with size, battery, and failure rules — not a silent soft-fail into “voice unavailable” with no install path.

## Decision

Ship **allowlisted, owner-downloadable on-device voice packs** inside the existing companion (same privacy posture as RFC-0108: app-private storage, no weights in git).

### 1. Two operating modes

| Mode | When | Voice behaviour |
| --- | --- | --- |
| **A — Fallback** | Leader / TLS gateway / LAN session unavailable, but the owner still uses the companion | On-device **STT and/or TTS** so the owner can dictate and hear replies. Pair with RFC-0108 local LLM when the pack is ready; if the LLM pack is missing, still allow capture → text draft / Outbox and playback of any local reply the device can produce. |
| **B — Grid-down / local AI** | Intentional offline companion path (no grid / no PC), local LLM running per RFC-0108 | On-device STT feeds the local model; on-device TTS speaks local model tokens. End-to-end private loop on the phone. |

**Online preference (unchanged product rule):** when the Leader session is live, prefer gateway / PC Kokoro (or the active Desktop `voice_profile_id`) for TTS and the existing companion realtime / host STT path. On-device packs may optionally run as a **low-latency front-end** only if they hand off to the Leader for authoritative speech and memory — they must not silently replace host neural voice while online.

### 2. Architect-recommended packs (v1 allowlist)

Pin concrete catalogs the way RFC-0108 pins GGUF URLs. Empty `url` rows are a **fail**.

| Role | Recommended id | Class | Why | Size budget (order) |
| --- | --- | --- | --- | --- |
| **STT (default)** | `whisper-tiny-en-cpp` | Whisper.cpp / sherpa-onnx **tiny.en** (Whisper-nano class) | English-first, real-time enough on mid-range phones, small download, on-device privacy | **≤ ~80 MB** install |
| **STT (optional)** | `whisper-base-en-cpp` | Whisper **base.en** | Better accuracy when storage/RAM allow | **≤ ~150 MB** |
| **TTS (default)** | `pocket-tts-en` | **Pocket TTS** class (Kyutai Pocket TTS or documented successor ONNX pack) | Taco-named quality/latency class; neural, local | **≤ ~150 MB** |
| **TTS (small fallback)** | `piper-en-lessac-medium` | Piper ONNX medium English | Tiny footprint if Pocket TTS exceeds device storage or fails NPU/CPU budget | **≤ ~60 MB** |

Exact filenames, HTTPS allowlisted URLs, and SHA-256 are filled in the implement catalog (same pattern as RFC-0108 §2.1). Do not commit weight binaries. Leader may cache packs under `data/companion-voice-packs/` (gitignored) for LAN serve after pair.

**Not v1 defaults:** full Desktop Kokoro-82M on phone (too heavy as required), cloud STT/TTS as the only offline path, XTTS/F5-TTS NC licenses as product defaults, IP-clone voices (Codsworth / Cortana / Ultron — `ip_guard` still applies to any display names).

### 3. Size, compute, battery

- **Combined recommended download (STT tiny.en + Pocket TTS):** target **≤ ~250 MB**. Hard stop: do not auto-download more than **500 MB** without an explicit owner confirm that shows sizes.
- Prefer **NPU / NNAPI / GPU** delegates when the runtime supports them; otherwise quantized **CPU**. Document thermal throttle: pause or downshift rather than pegging a core until the phone cooks.
- Idle: packs **unloaded** or memory-mapped cold; do not keep TTS+STT+LLM all hot unless actively in a voice turn.
- Battery: voice session shows an honest “on-device voice” indicator; long dictation warns once when thermal/battery is elevated.

### 4. Privacy

Audio for Mode A/B stays on-device unless the owner is online and the product path intentionally streams to the Leader (existing companion voice). No third-party cloud STT/TTS as the offline success path. Pack downloads only from the pinned allowlist or Leader cache.

### 5. Prefer local vs gateway

| Condition | STT | TTS |
| --- | --- | --- |
| Leader reachable + realtime voice healthy | Gateway / host path | PC active neural profile (Kokoro etc.) |
| Leader reachable but voice WSS/host TTS failing | Offer on-device fallback with visible banner; do not silent-fail | Same |
| Leader unreachable | On-device STT required for voice input | On-device TTS required for spoken local replies |
| Packs missing | Install UI (Download) — never pretend listening/speaking works | Same |

### 6. Failure modes (no silent soft-fail)

- Missing pack → status `missing` + Download affordance (post-pair offer may bundle voice packs beside RFC-0108 LLM offer, or a sibling More → Voice on-device panel).
- Corrupt hash → `error` + retry; never `ready`.
- Runtime init fail → `error` with actionable text (ABI, storage, RAM); Compose / UI must not show a fake waveform.
- Online path fails and on-device pack missing → explicit error, not empty mic success.
- Do **not** route phone offline TTS through PC SAPI. Do **not** change RFC-0092 PC defaults in this RFC.

### 7. Surfaces

- More → on-device **Voice**: STT pack, TTS pack, sizes, statuses (`missing` / `downloading` / `ready` / `running` / `error`), Download / delete.
- Optional post-pair offer for the **recommended** STT+TTS pair with sizes in MB (can share chrome patterns with RFC-0108 §2.4 without blocking LLM pack).
- HUD listening/speaking states ([RFC-0139](0139-android-companion-fancy-orb-humanoid-ui.md)) must reflect real on-device mic/TTS activity offline.

## Acceptance criteria

- [ ] Specs-only in this PR (no product weights; no silent stub voice)
- [ ] Mode A (fallback) and Mode B (grid-down with RFC-0108 LLM) are specified and testable
- [ ] Allowlisted STT + TTS catalogs with pinned URLs/hashes/sizes; empty URL is a **fail**
- [ ] Recommended defaults: Whisper tiny.en class STT + Pocket TTS class TTS; Piper small TTS fallback documented
- [ ] Size / battery / NPU-or-CPU / privacy / local-vs-gateway rules as above
- [ ] Missing/corrupt/init failures are visible and recoverable; no fake listening/speaking
- [ ] Online still prefers Leader/Kokoro-on-PC; RFC-0092 not weakened; no IP-clone packs
- [ ] Unit tests for catalog non-empty URL, hash fail → not ready, routing preference table; device soak for latency/thermal is phone sign-off
- [ ] Anzu 1.0 quality bar; soft-fail voice is a **fail**; subpar → CoS → Taco in review

## Likely files

| Area | Paths |
| --- | --- |
| Android | New voice-pack manager beside `CompanionPackManager`; STT/TTS engines (whisper.cpp / sherpa-onnx + Pocket TTS or Piper ONNX); More Voice panel; mic/TTS wiring in offline chat |
| Backend | Optional `GET /api/companion/voice-packs` + Leader cache under `data/companion-voice-packs/`; catalog JSON in repo (URLs/hashes only) |
| Tests | Catalog + routing unit tests; Android instrumented smoke when packs present |
| Docs | this RFC; §58; §59; cross-link RFC-0108 |

## Out of scope

Replacing RFC-0108 LLM packs. Rewriting Desktop Kokoro / RFC-0092 defaults. Full multilingual pack matrix (English-first v1; more languages later). Realtime duplex WebRTC redesign. Persona-specific phone voice binds (Desktop RFC-0137 remains host-side until a later RFC). Product code in this PR.

## Notes

Taco via CoS 2026-09-23: Pocket TTS / Whisper nano class; Mode A fallback when PC/gateway down; Mode B with local phone AI. Architect recommendation locked above. Linux cloud cannot sign off on-device latency — phone soak required.
