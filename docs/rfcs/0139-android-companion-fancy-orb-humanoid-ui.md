# RFC-0139: Android companion fancy orb / humanoid presence UI

**Status:** accepted  
**Queue item:** §58 RFC backlog — RFC-0139  
**Author:** Jarvis Architect  
**Date:** 2026-09-23  

**Related (do not rewrite):** [RFC-0125](0125-companion-hud-lan-pair.md) (Compose HUD baseline — glowing orb + particle humanoid). [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) (13-persona roster + shared presence states on Desktop). [RFC-0138](0138-anzu-orb-custom-ui-generation.md) (custom orb compositions — Desktop; do not port custom-UI generation in this ticket). [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (`registerPresenceShape`, `uMorph`). [RFC-0051](0051-humanoid-presence-runtime.md) (reduced motion). [RFC-0039](0039-android-native-client.md) / [RFC-0059](0059-android-companion-delivery.md) (companion is a paired controller). [RFC-0108](0108-phone-companion-offline-ai-model.md) offline chat brain. [RFC-0123](0123-companion-reachability-and-anti-impersonation.md) reachability.

This PR is **specs-only**. Product code is a **named follow-up**. Full intent; **no stubs / soft-fail**. Quality bar: multibillion-company / **Anzu 1.0**. Subpar implement → **CoS → Taco** in review (not a code path).

## Problem

The Android companion Home HUD must feel like the Desktop presence: a rich, readable multi-orb / particle **humanoid** figure with clear state motion. Tip today ships Compose `PresenceHud` / `PresenceParticles` (RFC-0125). When the Leader is unreachable (`connected === false`), activity collapses to a very low factor (order **0.12**), so the offline orb looks **dead and barely visible in daylight**. Offline is a first-class product mode (RFC-0108); a dim ghost figure is a **fail**.

Desktop presence uses the Three.js / morphable orb stack (`three` in `frontend`, RFC-0069 / RFC-0137). The phone must reach a **comparable visual quality bar** for the **humanoid** default — either by sharing / embedding that TJS (or equivalent high-fidelity) orb chrome, or by upgrading the Compose particle path to the same readability and detail. This RFC does **not** require shipping the full 13-persona morph catalog on the phone yet.

## Decision

### 1. Surface

Upgrade the **Android companion** Home HUD presence only. Keep tabs / pairing / More chrome from RFC-0125. Do **not** invent a custom brain UI. Do **not** rewrite Desktop RFC-0137 / RFC-0138 product code in this ticket.

### 2. Default chrome: humanoid

- Default presence mode on the phone is **`humanoid`** (particle / multi-orb humanoid bust), matching Desktop’s humanoid-first product feel.
- Mode chip may still offer a simpler orb, but humanoid is the default after install and after a missing stored preference.
- **Do not** require the full 13-persona morph set (`stormbird` … `forge_core`) on Android in this RFC. A later companion-roster RFC may share Desktop shape samples when cheap. Until then, one high-quality humanoid figure + shared **states** is enough.
- Appearance overrides that already exist on Desktop (orb colour, accent, glow, animation intensity, scale) may be mirrored as a thin companion settings slice when the Leader session is live; offline uses last-synced Appearance or humanoid defaults. Missing sync must not blank the figure.

### 3. Shared visual states (align with RFC-0137)

Drive the phone HUD from one state machine that matches Desktop intent (phase ids may map 1:1 or via an explicit table in code comments):

| State | When (first match wins) | Visual requirement on phone |
| --- | --- | --- |
| Offline | Leader unreachable / no live session | **Bright, readable** idle-offline look — see §4. Broken-ring or equivalent offline cue **without** collapsing brightness to near-zero. |
| Error | Task failed / hard companion error | Irregular flicker + warning colour (not persona accent). |
| Waiting / approval | Pending owner confirmation | Locked ring + indicator. |
| Alert | System degraded | Red/orange pulse. |
| Speaking | Local or gateway TTS playing | Brightness / waveform follows audio level. |
| Listening | Mic open / recording | Ring / attention toward mic. |
| Working | Task running | Elevated particle motion (not a static dim). |
| Thinking | Non-terminal work / queued | Rotating / expanding rings. |
| Idle | Otherwise, connected | Breathing scale; clearly alive. |

Reduced motion: snap morphs / hold a static pose of the current state (RFC-0051 intent). No second canvas that fights the HUD.

### 4. Offline / idle brightness and detail (hard requirements)

Tip’s “almost off” offline dim is **rejected**.

- **Daylight readable:** In outdoor / bright indoor lighting, an owner must still see the humanoid silhouette and the offline cue without cupping the screen. Acceptance: minimum particle / glow **alpha and light** floors for Offline and Idle-offline that are **≥ ~0.45 effective activity** (or an equivalent documented brightness floor), never the current ~0.12 dead look.
- **More detail:** Offline and Idle must use a **richer** composition than a sparse stub — higher particle count and/or multi-orb layers (core + halo + secondary orbs / sparks) so the figure does not look like a single faint blob. Humanoid density must remain at least the RFC-0125 humanoid seed quality, and Offline must not drop density.
- Offline colour may shift (e.g. warm alert tint) **in addition to** brightness, not instead of it.
- Banner copy (“Leader unreachable — answering on-device” when RFC-0108 offline brain is active) stays honest; the orb must not contradict it by looking powered-down.

### 5. Fancy stack: share Desktop quality, do not soft-fail

**Preferred path:** embed or port the Desktop morphable-orb / TJS-quality presentation into the companion Home HUD (WebView asset bundle **only if it actually paints**, or a native GL / Filament / equivalent path that matches the particle-orb language). Compose upgrade of `PresenceHud` / `PresenceParticles` is an acceptable v1 if it hits the same brightness, detail, and state-motion bar.

**Fails:**

- Leaving Offline at tip’s near-zero activity.
- A flat circle / emoji / static bitmap as the shipped presence.
- A WebView / TJS init failure that silently falls back to a blank or dim stub without an actionable error and a readable Compose fallback that still meets §4.
- Remount pops, blank HUD, or incorrect clip (historical RFC-0125 bugs).
- Porting RFC-0138 custom-UI generation or the full 13-shape roster as a blocker for this ticket.
- Treating this as a second brain UI or Obsidian rewrite.

### 6. Online vs offline behaviour

- Online: states follow Leader task / mic / TTS signals (existing companion session).
- Offline: states follow on-device STT/TTS and local model activity ([RFC-0140](0140-companion-on-device-voice-models.md) + RFC-0108). Idle-offline stays bright and detailed per §4.

## Acceptance criteria

- [ ] Specs-only in this PR (no `android/` / `frontend/src` / backend product edits)
- [ ] Default companion presence mode is **humanoid**
- [ ] Shared states cover Idle, Listening, Thinking, Working, Speaking, Alert, Waiting/approval, Offline, Error with Desktop-aligned intent
- [ ] Offline (and idle-offline) is **daylight-readable**; brightness floor replaces tip’s ~0.12 dead dim; richer multi-orb / particle detail than a sparse stub
- [ ] State transitions are visible (not snap-only unless reduced motion); no blank HUD; WebView/TJS failure fails closed with a readable Compose fallback that still meets the offline bar
- [ ] No full 13-persona morph requirement in this RFC; no RFC-0138 custom-UI generation on phone; no custom brain UI
- [ ] Android unit tests cover Offline brightness floor + humanoid particle count / composition smoke; physical phone daylight soak is device sign-off
- [ ] Quality bar Anzu 1.0 / multibillion; soft-fail or stub presence is a **fail**; subpar → CoS → Taco in review

## Likely files

| Area | Paths |
| --- | --- |
| Android (implement PR) | `PresenceHud.kt`, `PresenceParticles.kt`, Home HUD hosting in `MainActivity.kt` / related Compose; optional shared orb asset / GL / WebView only if it paints |
| Frontend (reference only) | Desktop `morphableOrbCloud.ts`, `HumanoidPresence`, presence state machine — read for parity; do not rewrite Desktop in this ticket unless CoS names a shared-module extract |
| Tests | Android unit tests for Offline brightness + particle composition; optional screenshot golden on device |
| Docs | this RFC; §58 backlog row; §59 Decision Log |

## Out of scope

Full 13-persona companion morph catalog. RFC-0138 custom presence generation on phone. RFC-0107 Obsidian. Changing pairing / TLS (RFC-0123). On-device voice packs ([RFC-0140](0140-companion-on-device-voice-models.md)). Product code in this PR.

## Notes

Taco via CoS 2026-09-23: bring fancy orb UI to Android; humanoid first; Offline too dim on tip; more detail so offline does not look dead. Tip evidence: `PresenceHud` maps `!connected && phase == "idle"` to activity `0.12f`. Desktop `three` stack remains the quality reference. Device sign-off required for daylight readability.
