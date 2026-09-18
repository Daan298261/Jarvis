# RFC-0112: Voice preview uses the exact selected profile

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a named follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent / living spec:** [`JARVIS_1.4_SPECS.md`](../../JARVIS_1.4_SPECS.md) work package **B** (§4) + preview slices of §10–12 / DoD §14.  
**Related (do not rewrite):** [RFC-0111](0111-kokoro-real-runtime.md) runtime truth / requested-vs-actual engine (this RFC **consumes** that status; it does not re-specify the adapter). [RFC-0092](0092-neural-tts-default-no-silent-sapi.md) preview/sample metadata (`engine_id` + `profile_id`). [RFC-0062](0062-selectable-voice-profile-catalog.md) catalog. [RFC-0070](0070-higher-quality-local-tts-engines.md) engines.

This PR is **specs-only**. Product code is a follow-up implement ticket. Full intent; **no stubs / soft-fail** (collapsing every failure into `Preview is not available for this voice yet.`, treating `audio.onerror` as success, or previewing a different engine/profile than the one selected, is a fail).

**Recommended implement model:** Composer 2.5 (1.4 §2 — narrow full-stack change). Depends on RFC-0111 status/synth contracts when Kokoro is the selected engine.

## Problem

The backend already has a useful profile-specific preview endpoint, but the frontend **collapses nearly every failure** into:

```text
Preview is not available for this voice yet.
```

That hides the real problem (missing assets, pipeline init, 503, empty WAV, browser decode).

Tip evidence (`frontend/src/tts/voiceProfiles.ts`):

- `requestPreviewAudio` tries `/api/voice-profiles/{id}/preview` then `POST /api/voice-profiles/preview` and **swallows every catch**, including 503 Kokoro init.
- `previewVoiceProfile` treats `audio.onerror` and `audio.play().catch` as **successful completion** (`finish` → `ok: true`).
- `VoicePreviewResult` only has `ok`, optional `engineId` / `profileId` — no model, speaker, status, or error string.

Owners cannot A/B-listen the selected Kokoro profile or see why preview failed. RFC-0092 already required engine/profile on preview; 1.4 makes the **exact selected profile** and **actionable errors** the product bar.

## Decision

One canonical preview route synthesizes the **exact requested profile’s sample utterance**, returns WAV plus engine/profile/model/voice identity, and propagates backend errors. The frontend preserves those errors. Browser playback failure is a failure. Never replace a known concrete error with the generic “not available yet” copy.

### 1. Canonical preview route

```text
POST /api/voice-profiles/{profile_id}/preview
```

The preview must:

1. load the **exact** requested voice profile (not a default butler stand-in, not a different speaker);
2. synthesize that profile’s **sample utterance**;
3. return WAV audio;
4. identify **actual** engine and profile in headers or metadata;
5. return a meaningful backend error when synthesis fails (RFC-0111 `TtsSynthesisError` / `last_error`, not a generic 500).

Suggested response headers:

```text
X-Jarvis-TTS-Engine: kokoro
X-Jarvis-Voice-Profile: butler_original_v1
X-Jarvis-TTS-Model: kokoro-82m
X-Jarvis-TTS-Voice: bm_daniel
```

(`bm_daniel` when that is the selected profile; do not preview `bm_george` unless that profile was selected. RFC-0111’s health probe speaker is not the preview speaker.)

A compatibility `POST /api/voice-profiles/preview` body `{ voice_profile_id }` may remain, but the **canonical** path is the `{profile_id}` route. Fallback to the other shape is allowed **only** for route-not-found (404/405), not for synthesis errors.

### 2. Frontend must preserve backend errors

Do **not** broadly swallow every fetch error.

Compatibility fallback may only occur for route-not-found style failures:

```typescript
catch (err) {
  if (isHttpStatus(err, 404) || isHttpStatus(err, 405)) {
    continue
  }
  throw err
}
```

A **503** from Kokoro initialization must remain a 503 Kokoro error. Same for 4xx/5xx that carry `last_error`.

### 3. Preview result type

```typescript
export type VoicePreviewResult = {
  ok: boolean
  engineId?: string
  profileId?: string
  modelId?: string
  voiceId?: string
  error?: string
  status?: number
}
```

Populate from headers / JSON error body. `ok: true` only after WAV generated **and** the client actually played it (section 4).

### 4. Playback failure must be a failure

Do **not** treat `audio.onerror` as successful completion.

```typescript
await new Promise<void>((resolve, reject) => {
  audio.onended = () => resolve()
  audio.onerror = () => reject(new Error("Browser could not decode preview audio"))
  audio.play().catch(reject)
})
```

Always revoke the object URL in `finally`.

### 5. Preview UI copy

| Outcome | Copy |
| --- | --- |
| Success | `Preview: Kokoro 82M · bm_daniel` (actual engine · actual speaker from headers) |
| Backend failure | `Kokoro preview failed: model assets could not be loaded.` (or the real `last_error`) |
| Playback failure | `Preview audio was generated, but this client could not play the WAV.` |

**Never** replace a known concrete error with `Preview is not available for this voice yet.` That generic line is allowed only when the profile is truly not in the catalog / `available=false` **and** there is no backend error to show.

### 6. Observability

Events: `voice_preview_requested`, `voice_preview_succeeded`, `voice_preview_failed`. Include `profile_id`, `requested_engine`, `actual_engine`, `model_id`, `speaker_ref`, status/error. Never hide empty waveform or browser playback failure (1.4 §10 TTS).

**Will not:** change which engine is default (RFC-0092 / RFC-0111). Swallow 503 into the next URL. Mark preview OK on `onerror`. Preview a different profile than the one clicked.

## Acceptance criteria

- [ ] Specs-only in this PR (no product code)
- [ ] Canonical `POST /api/voice-profiles/{profile_id}/preview` loads that profile, synthesizes its sample utterance, returns WAV
- [ ] Response headers (or equivalent metadata) identify actual engine, profile, model, and voice
- [ ] Each enabled Kokoro profile can synthesize a valid WAV preview (1.4 §12 test 5)
- [ ] Backend preview error reaches the frontend unchanged enough to be actionable (test 7); 503 stays 503
- [ ] Compatibility fallback only on 404/405, never on synthesis/init errors
- [ ] `VoicePreviewResult` carries `engineId`, `profileId`, `modelId`, `voiceId`, `error`, `status`
- [ ] Browser playback failure is reported as failure (test 8); object URL always revoked
- [ ] Success/failure copy as specified; generic “not available yet” never replaces a known error
- [ ] Preview of `butler_original_v1` is Kokoro audio for that profile (1.4 §12 test 34 — desktop listen sign-off)
- [ ] Implement follow-up: `python3 -m pytest`; `npm --prefix frontend run build` (and lint if TS changed). Live audible play is Windows desktop sign-off.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/api/voice_profiles.py`; synth via RFC-0111 adapter (`backend/app/tts/synthesize.py`) |
| Frontend | `frontend/src/tts/voiceProfiles.ts`, `VoiceProfilePicker.tsx`; Settings Voice pane |
| Tests | `tests/test_rfc0112_*.py`; frontend preview error/playback tests as the implement PR prefers |
| Docs | this RFC; `JARVIS_1.4_SPECS.md`; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. RFC-0111 adapter/pin/health probe (cite; do not re-implement here if 0111 is a separate named ticket — if CoS combines them, both contracts still apply). RFC-0113 Settings IA. Changing TTS defaults. HexStrike. Invented LE/Red/Purple gates. Exploit recipes.

## Notes

- 1.4 suggested implement order: **PR 5** after Kokoro runtime (RFC-0111).
- Linux cloud can unit-test headers, error propagation, and `onerror` → `ok: false`. Audible WAV play remains desktop sign-off.
- Implement launch: this RFC only; branch from `development`; pytest + frontend build; do not edit Architect spec docs; PR against `development`; do not merge other PRs.
