# RFC-0226: Reliable Kokoro load + automatic, visible voice fallback

**Status:** accepted  
**Priority:** P0 (Taco bug batch 2026-10-17, bug 1)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20

**Owner ask (verbatim intent, 2026-10-17):** "Kokoro shows 'FAILED TO LOAD' and only falls back to SAPI as an explicit system voice. Make voice load reliably, with a clean automatic fallback."  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §4 (voice is a primary interface — "It should not sound like a generic operating-system accessibility voice pretending to be an AI."; "The voice should belong to the selected ANZU personality and visual presence."; cites RFC-0092 and RFC-0111), §8 (verify — no fake "loaded"), §19 ("Do expose state when the user needs confidence in what ANZU is doing."; "Do not preserve an inferior implementation solely because an older specification happened to describe it." / "Do preserve the behavioural requirement…"), §20 Q6 ("Can ANZU recover intelligently when the happy path fails?") and Q8.  
**Extends (do not rewrite):** [RFC-0111 Kokoro real runtime](0111-kokoro-real-runtime.md) (five-fact runtime truth, `TtsRuntimeState`), [RFC-0092 no silent SAPI](0092-neural-tts-default-no-silent-sapi.md), [RFC-0070](0070-higher-quality-local-tts-engines.md), [RFC-0112 exact-profile preview](0112-voice-preview-exact-profile.md), [RFC-0193 voice alternatives](0193-voice-alternatives-and-installer-choices.md) (Pocket TTS / VoiceStudio engines).  
**Amends RFC-0092 (intent preserved):** RFC-0092 forbids *silent* SAPI presented as the natural voice. Taco now asks for an automatic fallback. This RFC keeps the RFC-0092 safety property — **SAPI is never silent and never presented as the persona's voice** — and replaces "stay mute" with "speak through the next working engine and say so visibly". RFC-0092's default speaker (`butler_original_v1`, Kokoro `bm_daniel`) is unchanged.  
**Open implementation PR that overlaps (rebase gate):** #648 (RFC-0223) touches `backend/app/tts/kokoro_adapter.py`, `backend/app/tts/warm_start.py` and `scripts/build-backend-sidecar.ps1` (bundles the frozen backend's English speech model and Pocket TTS resources). S1 starts after #648 is merged or closed and records whether #648 already fixed Taco's failure.  
**Astra boundary:** Persona, presence, WebGL, appearance and voice-to-persona binding art are **out of scope** (Astra). Persona voice *selection* (`resolve_speaking_voice`) is reused, not changed.

This PR is **specs-only**. No application code.

---

## Problem

Verified in `development` @ `3f17c3d8`:

1. **The exact owner-visible string comes from self-check.** `backend/app/systems/self_check.py` emits `"Kokoro · FAILED TO LOAD. Windows SAPI is available only as an explicit system voice."` when Kokoro is not ready **and** Kokoro assets are not found; `frontend/src/tts/VoiceProfilePicker.tsx` shows `Kokoro · FAILED TO LOAD · <last_error>`.
2. **"Not yet verified" is rendered as "FAILED".** `engine_availability()["kokoro"]` is `TtsRuntimeState.ready`, which needs `synthesis_verified`. `KokoroAdapter.runtime_state()` starts from `_base_state()` (verified = false) until `verify()` runs; `warm_start._warm_kokoro_langs` only builds pipelines. A healthy-but-unverified Kokoro therefore reads "FAILED TO LOAD · Health verification pending".
3. **Real load failure candidates (unconfirmed):** (a) `resolved_kokoro_model_dir()` falls back to `preferred_gguf_install_dir(...)` on another volume where no `config.json` / `*.pth` / `voices/bm_daniel.pt` exist; (b) `kokoro_package_ready()` requires *exact* pinned versions of `kokoro` and `soundfile`, which a frozen/updated backend may not match; (c) frozen backend missing English G2P/speech data (#648 claims to bundle it); (d) pipeline init exception on CPU/torch. Which one hits Taco is **not proven**.
4. **No automatic fallback.** `workers/voice.py::synthesize_speech_result` filters system engines out unless the profile is explicitly SAPI; `engines.engine_chain_for_profile` returns `["kokoro"]` for Kokoro profiles; `persona_speech.speak_text` raises `SpeechRefused` for SAPI. Result: Kokoro down = ANZU mute, or SAPI only when the owner manually picks "Windows natural".
5. **No retry/reload.** Once Kokoro fails, nothing retries; the owner must restart ANZU.

## Decision

Ship **one RFC with three implement slices** (one ticket each, one named model, **fast off**).

### Fallback chain (normative)

For a persona whose primary engine is Kokoro:

`kokoro → next available local neural engine (pocket_tts, then piper, then voicestudio — first that is runtime-verified) → system (SAPI / espeak)`

For other primaries the existing chain is kept and extended with the same tail: e.g. `chatterbox → kokoro → [neural tail] → system`.

Rules:

1. **Runtime truth only.** An engine joins the chain only when its runtime state is verified (RFC-0111 five facts for Kokoro; equivalent `*_runtime_state().ready` for Pocket TTS / VoiceStudio; Piper voice file present + probe). No engine is reported "loaded" without a successful synthesis probe.
2. **Automatic, never silent.** When a non-primary engine speaks, ANZU (a) logs `tts_synthesis` with `requested_engine`, `actual_engine`, `fallback_reason` (existing log, extended); (b) publishes one `voice_fallback` event per state change (not per utterance) with `{requested, actual, reason}`; (c) self-check `household_voice` becomes `degraded` with "Speaking with <Engine> while Kokoro recovers — <reason>"; (d) the voice settings card shows the same line. The notice is **non-blocking**: no modal, no confirmation, speech continues.
3. **SAPI is last and labelled.** SAPI audio is never tagged with the persona's neural `model_id`; `SynthesizedSpeech.engine_id`/`model_id` report `system` / `windows-sapi`. The persona's stored `voice_profile_id` is never rewritten to `windows_natural_en_v1`. Explicitly choosing "Windows natural" as a persona voice stays refused (existing rule).
4. **Retry / reload.** On Kokoro failure a background re-verify runs with backoff 30 s → 2 min → 10 min (cap), off the event loop and never during an utterance. On success the chain returns to Kokoro and a `voice_fallback` event `{actual: "kokoro", reason: "recovered"}` clears the notice. Owner "Retry Kokoro" forces `reset()` + `verify(force=True)` immediately.
5. **Pending ≠ failed.** Self-check and the picker distinguish `verifying` ("Kokoro · checking voice…", status `starting`) from `failed` (real `last_error`). Warm start runs `verify_kokoro_runtime_async()` once after pipelines warm.
6. **Root cause recorded.** S1 writes the confirmed cause and evidence; the fix targets that cause, and `last_error` shown to the owner names it in plain words.

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

Touched live UI: Settings → Voice (`VoiceProfilePicker.tsx`), health rail entry fed by self-check.

| Current live behaviour | Preserved? | Added alongside |
| --- | --- | --- |
| Profile list with select / preview / install buttons, "Install household voice" | **Yes**, unchanged | "Retry Kokoro" button in the status line |
| READY line `Kokoro 82M · <voice> · READY` | **Yes**, same text | — |
| Failure line shows `last_error` | **Yes** (text still carries the real error) | "Speaking with <Engine> meanwhile" suffix; `verifying` state |
| Selecting "Windows natural" for a named persona is refused with the existing message | **Yes** | — |
| Preview uses the exact profile (RFC-0112) and reports the actual engine | **Yes** — preview does **not** fall back (exact profile), it reports the failure as today | — |
| Health rail `household_voice` item and link | **Yes**, same id/label | Degraded-with-fallback detail |

The sentence "Speech stays silent if the neural voice fails; it will not pretend that SAPI is Kokoro." becomes "If Kokoro fails, ANZU keeps talking with the next local voice and tells you which one; it never presents SAPI as Kokoro." — same honesty guarantee, new behaviour; the copy change is required because the old text would now be false (§19). Nothing else is removed.

### Stub rule

No stubs, soft-fails or fake states. A `voice_fallback` event nobody renders, a retry button that only resets UI state, or a chain that lists an engine that cannot synthesize, is a fail.

---

## Slices (one ticket each)

Assign order: **S1 → S2 → S3.**

### S1 — Kokoro load root cause + reliable load, verify, retry

**Model:** Grok 4.6 (fast off) · **Lane:** D2 · **Depends:** #648 merged or closed

| Path | Why |
| --- | --- |
| `docs/audits/2026-10-20-kokoro-load-root-cause.md` (new) | Evidence on Taco's installed build + clean install: resolved model dir, asset listing, package versions in the frozen backend, verify exception trace, timing |
| `backend/app/tts/kokoro_adapter.py` | Fix the confirmed cause; `verifying` vs `failed` state; background re-verify with backoff; `reload()` = `reset()` + `verify(force=True)`; plain-language `last_error` |
| `backend/app/tts/warm_start.py` | After pipeline warm, run one `verify_kokoro_runtime_async()`; record result in `last_warm_report` |
| `backend/app/tts/runtime_state.py` | Add `verifying: bool` to `TtsRuntimeState` (serialized; `ready` semantics unchanged) |
| `backend/app/api/voice.py` | `POST /api/voice/kokoro/reload` → returns fresh runtime state |
| `scripts/build-backend-sidecar.ps1` | Only if the audit shows a bundling cause (e.g. missing data/assets in the frozen backend) |
| `tests/test_rfc0226_kokoro_load.py` (new) | Below |

- [ ] Audit names the confirmed root cause on Taco's machine with evidence; the fix addresses it and a regression test reproduces it.
- [ ] Fresh start with valid assets → state goes `verifying` → `ready` without owner action; never shows "FAILED" while verifying.
- [ ] Missing assets / wrong version / pipeline exception → `ready == false`, `last_error` names the specific cause; no code path sets `synthesis_verified` without a produced WAV.
- [ ] Background re-verify runs on backoff and recovers when the cause is removed (test swaps assets in); it never runs during an active synthesis.
- [ ] `POST /api/voice/kokoro/reload` returns the new state and is serialized with synthesis (adapter lock).
- [ ] `tests/test_rfc0111_kokoro_runtime.py` and `tests/test_rfc0092_neural_tts.py` still pass (amended only where they assert "mute on failure").

### S2 — Automatic fallback chain + `voice_fallback` signal

**Model:** Grok 4.6 (fast off) · **Lane:** D2 · **Depends:** S1

| Path | Why |
| --- | --- |
| `backend/app/tts/engines.py` | `engine_chain_for_profile`: neural tail + `system` last per the normative chain; `fallback_chain_for_profile()` filters to verified engines |
| `backend/app/workers/voice.py` | `synthesize_speech_result`: allow the system tail when the chain reached it; `SynthesizedSpeech` gains `fallback_reason`; extend `tts_synthesis` log |
| `backend/app/tts/persona_speech.py` | Persona speech uses the chain (persona primary first); `SpeechRefused` only for an explicitly SAPI persona voice, not for fallback; publish `voice_fallback` on state change via existing owner event bus |
| `backend/app/systems/self_check.py` | `household_voice`: `ready` / `starting` (verifying) / `degraded` with "Speaking with <Engine> while Kokoro recovers — <reason>" / `missing` |
| `tests/test_rfc0226_voice_fallback.py` (new) | Below |

- [ ] Kokoro failing + Pocket TTS verified → audio from Pocket TTS; `actual_engine == "pocket_tts"`, `fallback_reason` set.
- [ ] Kokoro + all neural engines failing → SAPI audio; `engine_id == "system"`, `model_id == "windows-sapi"`; persona `voice_profile_id` unchanged.
- [ ] `voice_fallback` emitted once per state change (Kokoro→Pocket, Pocket→Kokoro recovered), not per utterance.
- [ ] Self-check never reports `ready` while a fallback engine is speaking; detail names the engine and reason.
- [ ] Explicit persona voice = `windows_natural_en_v1` still refused; exact-profile preview (RFC-0112) does not fall back.
- [ ] No synthesis path blocks the owner turn longer than today on failure (fallback attempt is bounded; test with failing fakes).

### S3 — Visible non-blocking notice + Retry Kokoro (UI)

**Model:** Composer 2.5 (fast off) · **Lane:** UX · **Depends:** S2

| Path | Why |
| --- | --- |
| `frontend/src/tts/VoiceProfilePicker.tsx` | `verifying` line; fallback suffix; "Retry Kokoro" button → `POST /api/voice/kokoro/reload` with pending/result state; updated honesty sentence |
| `frontend/src/settings/VoiceSettingsPane.tsx` | Surface the same status line where the pane already shows voice status (no layout removal) |
| `frontend/voice-fallback-notice.test.mjs` (new) + `package.json` script | Below |

- [ ] Kokoro failing + fallback speaking → picker shows the real error **and** "Speaking with <Engine> meanwhile"; no modal, chat unaffected.
- [ ] "Retry Kokoro" shows working state, then READY or the new error; double-click does not queue two reloads.
- [ ] Verifying state shows "checking voice…", never "FAILED TO LOAD".
- [ ] Every existing control (select, preview, install, Install household voice) still present and working — PR includes the preserved-behaviour section.
- [ ] `npm --prefix frontend run build` + lint pass.

---

## Overall acceptance

- [ ] On Taco's PC after update: Settings → Voice shows Kokoro READY within the warm-start window, or a named real cause plus the fallback engine speaking.
- [ ] Forced Kokoro failure (rename weights) → ANZU keeps speaking via the next neural engine, the notice is visible, renaming back recovers automatically within the backoff window without restart.
- [ ] SAPI is reached only when no neural engine is verified, and is labelled as SAPI everywhere.
- [ ] RFC-0111 / RFC-0092 / RFC-0112 suites green (with documented amendments); full backend suite + frontend build in CI.

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0226-S1 | Kokoro root cause + reliable load/verify/retry | Grok 4.6 | D2 | #648 resolved |
| 0226-S2 | Automatic fallback chain + voice_fallback signal | Grok 4.6 | D2 | S1 |
| 0226-S3 | Visible fallback notice + Retry Kokoro UI | Composer 2.5 | UX | S2 |

## Likely files

See ownership tables. No file here is owned by another RFC of the 2026-10-17 batch.

`frontend/package.json` is shared by every frontend ticket in the 2026-10-17 batch: each ticket adds exactly one `test:*` script line (append-only hunk, trivial rebase) and touches nothing else in that file.

## Out of scope

- Persona/presence/WebGL/appearance (Astra); persona→voice mapping.
- New TTS engines or new voice packs (RFC-0193).
- STT / recognizer changes.
- Installer voice task UI (RFC-0228 handles installed/greyed state generically).

## Risks

- **Fallback voice mismatch with persona** — mitigated by the visible notice and fast recovery; persona binding is never rewritten.
- **Retry loop CPU cost** — capped backoff (10 min), skipped while a synthesis is running.
- **#648 overlap** — rebase gate; S1 audit states what #648 already fixed.
