# RFC-0216: Android settings — secure screen, off-grid downloads, STT fix, TTS language, content manager

**Status:** accepted  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-13

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §4 (voice is a primary interface), §9 (local-first / privacy), §13 (phone companion and grid-down), §20 (quality test: no stubs, honest failure, works when optional pieces disappear), §21 (finished product remains useful when the desktop or network is gone).  
**Extends (do not rewrite):** [RFC-0204](0204-android-anzu-standalone-upgrade.md) (Android ANZU standalone / Black Grid mode), [RFC-0140](0140-companion-on-device-voice-models.md) (on-device STT/TTS packs), [RFC-0108](0108-phone-companion-offline-ai-model.md) (on-device LLM packs), [RFC-0159](0159-offline-resilience-grid-down-degraded-mode.md) (offline packs with provenance), [RFC-0213](0213-android-pairing-and-app-access.md) (pairing / app access).  
**Astra boundary:** Do not edit persona roster, WebGL, `PresenceParticles`, or presence art. Presence *state wiring* already owned by existing companion code may reflect mic/TTS activity; do not redesign the orb.

This PR is **specs-only**. No application code. Weights, ZIMs, and map tiles stay out of git.

---

## Problem

Five owner-facing gaps on the ANZU Android app block a finished phone surface:

1. **Screenshots are blocked** by `FLAG_SECURE` with no owner control, so legitimate capture (bug reports, sharing a non-sensitive screen) is impossible, while the secure default for a personal assistant is still correct.
2. **Off-grid content is not choosable.** RFC-0204 / RFC-0140 / RFC-0108 cover Leader-unreachable operation and voice/LLM packs, but there is no Settings-driven Off-grid content mode with a power-pylon picker for offline maps and Prepper-Pi-style Kiwix knowledge bases (Wikipedia, medical, survival) that shows sizes and downloads only what the owner picked.
3. **STT is broken on Taco's Samsung Galaxy S23.** Manifest already declares `RECORD_AUDIO` and queries `RecognitionService` / `TTS_SERVICE`; the failure is elsewhere (platform recognizer binding, runtime permission UX, Samsung package visibility, or the Whisper native path). Silent failure is a product fail.
4. **TTS follows the device default voice.** Phone locale Dutch + app English yields English spoken with a Dutch accent. There is no voice-language setting independent of system locale, and no clear high-quality offline English TTS ≤ 150 MB offer tied to that setting.
5. **Downloaded content has no single manager.** LLM packs, voice packs, maps, and ZIMs will sprawl across More panels unless one Settings page lists sizes and supports update/delete.

## Decision

Ship **one RFC with five implement slices**. Each slice is a single CoS-assignable ticket with one named model (**fast off**). Extend existing More settings, pack managers, and catalogs. No stubs, scaffolding, soft-fails, or fake transcripts/audio. Empty catalog `url` rows remain a **fail** (RFC-0108 / RFC-0140 rule).

**Naming note — two different “Black Grid” ideas stay distinct:**

| Name | Meaning in this RFC |
| --- | --- |
| **Black Grid mode** (RFC-0204) | Phone operates as standalone ANZU when the Leader desktop is unreachable. |
| **Off-grid content** (this RFC, S2) | Optional offline maps + Kiwix ZIMs the owner downloads while online. |
| **Black Grid Publishing** | Sponsor mark / power-pylon icon reused as the Off-grid picker entry. |

**Secure default for screenshots:** **blocked** (`FLAG_SECURE` on). A personal assistant shows chats, notes, and pairing material; privacy-first matches §9 / §20. The owner may allow screenshots in Settings.

---

## Slices (one ticket each)

### S1 — Screenshot / screen-capture toggle (`FLAG_SECURE`)

**Goal.** Settings toggle **Allow screenshots**. Off (default) keeps `FLAG_SECURE` set on private ANZU windows. On clears the flag so the system screenshot / screen-record / recent-apps thumbnail path works.

**Model:** Composer 2.5 · **fast off**

**Owns (exclusive):**

| Path | Why |
| --- | --- |
| New prefs helper (e.g. `SecureScreenPrefs.kt`) | Persist `allow_screenshots` (default `false`). Use the same prefs/DataStore pattern the app already uses for companion settings — do not invent a second store. |
| `MainActivity.kt` (window-flag application only) | Apply / clear `WindowManager.LayoutParams.FLAG_SECURE` in `onCreate` / `onResume` when preference changes. If another activity shows private UI, list it here in the implement PR; S1 owns those call sites. |
| More / Settings UI row in the existing settings surface | Toggle labeled **Allow screenshots** with short subtitle: default blocks capture to protect chats and pairing. |
| Unit / instrumented test | Preference false → flag present; preference true → flag absent (Robolectric or existing activity test style). |

**Acceptance.**

- [ ] Fresh install: screenshots blocked (`FLAG_SECURE` set). Device check on a physical phone.
- [ ] Toggling **Allow screenshots** on clears the flag without restart; toggling off restores it.
- [ ] Preference survives process death.
- [ ] No persona / WebGL / presence particle edits.
- [ ] Android unit tests for the preference ↔ flag mapping pass.

**Depends on.** Nothing.

---

### S2 — Off-grid content mode + power-pylon download picker

**Goal.** Settings **Off-grid content** section. Tapping the **power-pylon** mark (from the Black Grid Publishing logo already used for sponsor credit) opens a multi-select picker of allowlisted offline packs with **sizes shown before download**. Download **only** what was picked. After install, owner can open offline maps and search ZIM knowledge without Leader or network.

**Model:** Grok 4.6 · **fast off**

**Owns (exclusive):**

| Path | Why |
| --- | --- |
| `OffGridContentCatalog.kt` (+ test) | Pinned allowlist: id, title, category (`maps` \| `zim`), `size_bytes`, SHA-256, HTTPS URL, optional version. Empty URL = fail. |
| `OffGridContentManager.kt` (+ test) | Download (resumable), verify hash, cancel, delete, status (`missing` / `downloading` / `ready` / `error`), storage-space preflight. |
| Picker UI (Composable) + power-pylon entry on More | Multi-select, sizes in MB/GB, confirm before large downloads, progress. Reuse `bgp_logo` / pylon crop — do not redraw a substitute mark; do not add the 1.1 MB original. |
| Offline maps integration module | **Decision for implementer (pick one, document in PR):** (A) Organic Maps–compatible map files opened via explicit intent to Organic Maps if installed, else in-app MapLibre offline region; or (B) pure MapLibre offline pack stored under app-private storage. Must open a downloaded region offline. Pin at least one starter pack **or** a region-download flow that estimates size before commit. |
| Kiwix ZIM reader path | Embed libkiwix / kiwix-lib JNI **or** a maintained Android Kiwix reader dependency. Categories v1: Wikipedia (English compact class), medical, survival. Pin concrete ZIM URLs/hashes/sizes from the official Kiwix library / mirror allowlist. Open/search fail closed if file missing or hash bad. |
| Backend optional cache (only if LAN serve needed) | Mirror RFC-0108 pattern under gitignored `data/companion-offgrid/` + optional `GET` catalog — only if phone downloads from Leader. Otherwise phone downloads straight from pinned HTTPS. |

**Catalog rules (v1).**

- Combined auto-offer must not exceed **500 MB** without an explicit multi-select confirm that lists each size.
- Individual ZIM/map packs may be larger; the picker must show size and free-space check before start.
- No weights/ZIMs/maps in git.

**Acceptance.**

- [ ] Power-pylon entry opens picker; nothing downloads until the owner confirms a non-empty selection.
- [ ] Each catalog row has non-empty HTTPS URL, SHA-256, and `size_bytes`; unit test fails on empty URL.
- [ ] Corrupt hash → `error` + retry; never `ready`.
- [ ] Cancel mid-download leaves no `ready` partial presented as complete.
- [ ] Offline: opening a ready map pack and a ready ZIM works with network disabled (device sign-off).
- [ ] Missing reader/native lib → actionable error, not a blank WebView success.
- [ ] No persona / WebGL edits.

**Depends on.** Nothing hard. S5 will list these items once this lands.

---

### S3 — Fix STT on Samsung Galaxy S23

**Goal.** Diagnose the real root cause on S23, then fix it. Mic → transcript works for a spoken English sentence. No fake transcripts.

**Model:** Grok 4.6 · **fast off**

**Owns (exclusive):**

| Path | Why |
| --- | --- |
| Platform STT path (`PlatformVoice.kt` and/or whatever wraps `SpeechRecognizer`) | Binding, error callbacks, retry. **Language:** until S4 lands, use the product-English default recognizer tag `en-US` (a single named constant). Do **not** invent a second STT-language preference. S4 owns the shared voice-language setting and removes this constant when it lands. |
| Runtime mic permission UX in the listen path | `RECORD_AUDIO` is in the manifest; ensure request/rationale/denied paths are honest. |
| `AndroidManifest.xml` `<queries>` only if diagnosis requires extra packages | Manifest already queries `RecognitionService` and `TTS_SERVICE`. Add Samsung/Google package queries **only** if confirmed necessary (e.g. `com.google.android.googlequicksearchbox`, Samsung speech package). Do not shotgun-query the world. |
| On-device Whisper path touch-ups if that is the working S23 path | `OnDeviceVoiceEngines.kt` / `CompanionVoicePackManager` / native bridge error surfacing — fail closed, install affordance when pack/`.so` missing. |
| Tests | Unit tests for permission-denied and recognizer-unavailable → visible error; no success on empty transcript. |
| Device sign-off note in implement PR | Cloud cannot pass S23. |

**Diagnosis order (implementer confirms on device; do not guess a root cause into production):**

1. **Runtime `RECORD_AUDIO`:** denied / “ask every time” / Samsung privacy dashboard silencing the mic.
2. **`SpeechRecognizer` availability:** `isRecognitionAvailable` false; no `RecognitionService` resolved despite `<queries>` — check whether Samsung needs an explicit `<package>` query for the active recognizer.
3. **Recognizer errors:** `ERROR_INSUFFICIENT_PERMISSIONS`, `ERROR_CLIENT`, `ERROR_NETWORK` on “offline” device speech, `ERROR_NO_MATCH` loops.
4. **Audio focus / call FGS conflict:** `CallService` or another FGS holding the mic.
5. **Wrong path selected:** UI claims listening while Whisper pack/native is missing and platform STT failed — soft-fail.
6. **Whisper native path:** if product intent on S23 grid-down is Whisper tiny.en, verify `JARVIS_BUILD_VOICE_NATIVE`, pack ready, and PCM → transcript; fix that path instead of papering over platform STT.

**Fix bar.**

- One spoken sentence produces a non-empty transcript the chat uses.
- Failure shows an actionable message (permission, install voice pack, enable Google/Samsung speech, etc.).
- Never return a canned or previous transcript as success.

**Acceptance.**

- [ ] Root cause written in the implement PR (which hypothesis, how confirmed).
- [ ] S23 device sign-off: listen → correct-ish transcript for a short English phrase.
- [ ] Permission denied and recognizer unavailable are explicit errors in tests or reproducible checklist.
- [ ] No silent soft-fail; no persona/WebGL edits.

**Depends on.** Nothing. Highest user-blocking slice — assign first.

**Language handoff to S4.** S3 may hardcode product-English `en-US` for `RecognizerIntent.EXTRA_LANGUAGE` / equivalent. When S4 lands, that constant is deleted; the recognizer reads the S4 voice-language preference (see S4).

---

### S4 — Voice language (TTS + STT) + high-quality offline TTS ≤ 150 MB

**Goal.** Settings **Voice language** (and optional voice) independent of system locale — the **single source** for both TTS language and the STT recognizer language (`RecognizerIntent.EXTRA_LANGUAGE` / equivalent). English ANZU UI defaults to an **English** neural/offline voice so a Dutch system locale cannot force a Dutch-accented English system voice or a Dutch STT recognizer. Offer / ensure a high-quality offline TTS pack **≤ 150 MB** (Pocket TTS class already in RFC-0140, or Piper/Kokoro-ONNX class pin).

**Model:** Grok 4.5 · **fast off**

**Owns (exclusive):**

| Path | Why |
| --- | --- |
| Voice language preference + Settings UI | **Single source** for spoken language across TTS and STT. Default product English stored as BCP-47 (prefer `en` in UI; see resolution below) + optional engine voice name. Optional separate STT override may exist later; if blank/absent, STT uses this spoken language. Do not add a second independent “STT language” default that diverges from Voice language. |
| Shared language resolver helper (new small helper; S4 owns) | Resolve the preference to tags engines need: TTS may accept `en`; Android `SpeechRecognizer` / `EXTRA_LANGUAGE` needs a **regioned** tag. Rule: bare language subtag such as `en` → canonical regioned default `en-US` (document the map; same for other bare tags the UI offers). Prefer-region tags like `en-GB` pass through. |
| `PlatformVoice.kt` (locale/voice selection for TTS **and** recognizer language wiring) | Apply setting to `TextToSpeech` language / voice; do not use raw `Locale.getDefault()` when an explicit ANZU voice language is set. Apply the **same** resolved tag to recognizer intents (`EXTRA_LANGUAGE`). **Remove S3’s temporary `en-US` constant** once this preference exists. File-lock with S3: if S3 still open, land resolver + preference first and leave a one-line call site S3 can already use; do not leave two sources. |
| `CompanionVoicePackCatalog` / manager updates if a new ≤150 MB pack is required | Prefer existing `pocket-tts-en` if it meets quality and size. If Pocket cannot honor language cleanly, pin one additional English pack ≤ 150 MB with URL/hash/size (Piper medium or Kokoro-ONNX phone build). Empty URL = fail. |
| Routing | When on-device TTS is selected (RFC-0140 Mode A/B), speak with the pack matching the voice-language setting. When platform TTS is used, same language setting applies. Platform and on-device STT both read the same resolved language unless an optional STT override is set. |
| Tests | Preference applied to TTS **and** recognizer extra; bare `en` → `en-US` for recognizer; missing pack → download affordance; success path does not claim ready on silence (keep `isNearSilentPcmWav` reject). |

**Acceptance.**

- [ ] Device locale `nl-NL` + Voice language `English` → spoken English uses English voice/pack, not Dutch system voice.
- [ ] **nl-NL device, Voice language English → recognizer intent `EXTRA_LANGUAGE` is English, from the setting** (not the Dutch system locale). Same Voice language preference as TTS.
- [ ] Bare preference `en` resolves to a regioned recognizer tag such as `en-US` (unit-tested).
- [ ] S3’s temporary product-English `en-US` constant is removed; only the Voice language preference (plus optional blank STT override) remains.
- [ ] Offline TTS option ≤ 150 MB is installable from allowlist with hash verification.
- [ ] Missing pack: visible Download, not a “success” Dutch accent fallback.
- [ ] RFC-0092 PC path untouched.
- [ ] Unit tests for preference routing (TTS + STT) pass; audible quality is device sign-off.

**Depends on.** Soft-depends on S3 only for shared listen/speak UX polish — file lock: S3 owns recognizer binding/mic/error paths; S4 owns the voice-language preference, resolver (including bare→regioned), TTS packs, and recognizer **language** wiring. Do not both edit the same method bodies; split helpers if needed.

---

### S5 — Downloaded content manager

**Goal.** One Settings page listing **all** downloaded offline content with on-disk sizes: LLM packs, voice packs (STT/TTS), off-grid maps, Kiwix ZIMs. Per row: **Update** (re-fetch if pin/version/hash newer) and **Delete** (owner-confirmed).

**Model:** Composer 2.5 · **fast off**

**Owns (exclusive):**

| Path | Why |
| --- | --- |
| `DownloadedContentManager.kt` (aggregator) + test | Read-only inventory over `CompanionPackManager`, `CompanionVoicePackManager`, `OffGridContentManager`. Single list model; no duplicate download implementation. |
| Settings **Storage** / **Downloaded content** screen | List, sizes, status, Update, Delete (confirm for large items). |
| Wiring from More | One entry point. |

**Acceptance.**

- [ ] Every ready pack type appears with a correct size (± small FS accounting skew documented).
- [ ] Delete removes files and returns status to `missing`; chat/voice/off-grid paths fail closed afterward.
- [ ] Update re-verifies hash; failed update does not delete the last good pack unless the owner confirms replace.
- [ ] Page usable when S2 has not landed yet: shows LLM + voice packs; maps/ZIM sections appear when those managers exist (feature-detect, no crash).
- [ ] No persona/WebGL edits.

**Depends on.** Soft: S2 for maps/ZIM rows. Can start immediately against LLM/voice managers.

---

## Recommended assign order (for CoS)

1. **S3** (S23 STT — user blocking) ∥ **S1** (FLAG_SECURE toggle)  
2. **S4** (Voice language for TTS+STT / offline voice)  
3. **S2** (off-grid picker + maps/ZIM)  
4. **S5** (content manager — after S2 for full inventory; partial OK earlier)

## Overall acceptance criteria

- [ ] Specs-only in this PR: `docs/rfcs/0216-…` (+ RFC index line). No `android/` product edits in the spec PR.
- [ ] Five slices each name exactly one model (Composer 2.5 / Grok 4.5 / Grok 4.6) with **fast off**.
- [ ] Screenshot default is blocked; owner can allow.
- [ ] Off-grid picker shows sizes and downloads only the selection; maps + Wikipedia/medical/survival ZIM classes are specified with allowlist rules.
- [ ] STT slice requires root-cause + S23 device sign-off; no fake transcripts.
- [ ] Voice language is independent of system locale and is the single source for TTS and STT recognizer language (bare `en` → regioned tag for recognizer); offline TTS ≤ 150 MB offered/pinned.
- [ ] Content manager lists sizes and supports update/delete without parallel inventories drifting.
- [ ] No stubs, soft-fails, empty catalog URLs, persona/WebGL edits, or weights in git.

## Likely files

| Slice | Paths |
| --- | --- |
| S1 | Secure screen prefs, MainActivity window flags, More toggle, tests |
| S2 | Off-grid catalog/manager, picker UI, maps + Kiwix integration, optional Leader cache |
| S3 | PlatformVoice / SpeechRecognizer path, permission UX, manifest queries (if proven), Whisper error surfacing, tests |
| S4 | Voice language prefs/UI, shared language resolver (bare→regioned), PlatformVoice TTS + recognizer language, remove S3 `en-US` constant, voice pack catalog pin if needed, tests |
| S5 | Aggregator manager, Downloaded content Settings screen, More entry |
| Docs | this RFC; `docs/rfcs/README.md` index line |

## Out of scope

- Persona roster, WebGL, presence particle redesign (Astra).
- Choosing the abliterated GGUF (still RFC-0204 §2.1 open question).
- Desktop Kokoro / RFC-0092 changes.
- iOS.
- Auto-downloading multi-GB ZIMs without explicit pick.
- Rewriting RFC-0204 Black Grid mode behavior (Leader-unreachable) — this RFC adds **content** packs only.

## Risks and notes

1. **S23 STT is device-bound.** Cloud CI cannot green-check it; implement PR must record the confirmed cause and the device pass.
2. **Kiwix / maps native size.** Reader and map engine ABIs grow the APK; prefer official libraries and document ABI filters. A WebView pretending to be Kiwix without a ZIM backend is a fail.
3. **Storage pressure.** Multi-GB ZIMs need free-space checks and S5 delete.
4. **File locks across S3/S4.** Mic/STT binding vs voice-language + TTS — split helpers; no drive-by edits on the other slice’s methods. S3’s temporary `en-US` constant must die in S4 so language never has two sources.
5. **README numbering.** As of 2026-10-13, `docs/rfcs/README.md` still says next free is 0215; **0215 already exists**. This RFC takes **0216**. Update the README “next free” note in this PR.

## Implement ticket cards (copy for CoS)

| ID | Title | Model |
| --- | --- | --- |
| S1 | Android: Allow-screenshots toggle (`FLAG_SECURE`, default blocked) | Composer 2.5 · fast off |
| S2 | Android: Off-grid content picker (maps + Kiwix ZIMs, sizes, selected-only download) | Grok 4.6 · fast off |
| S3 | Android: Fix STT on Samsung S23 (diagnose RecognitionService / permission / queries / Whisper path) | Grok 4.6 · fast off |
| S4 | Android: Voice language setting (TTS + STT single source) + offline TTS ≤ 150 MB | Grok 4.5 · fast off |
| S5 | Android: Downloaded content manager (list / size / update / delete) | Composer 2.5 · fast off |
