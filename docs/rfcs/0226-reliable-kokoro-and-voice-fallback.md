# RFC-0226: Reliable Kokoro load + automatic, visible voice fallback

**Status:** accepted  
**Priority:** P0 (Taco bug batch 2026-10-17, bug 1)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20 (re-sliced 2026-10-20: lands on current `development` without drafts #648/#649; D2 re-review items 1–3 of 2026-10-20 folded in)

**Owner ask (verbatim intent, 2026-10-17):** "Kokoro shows 'FAILED TO LOAD' and only falls back to SAPI as an explicit system voice. Make voice load reliably, with a clean automatic fallback."  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §4 (voice is a primary interface — "It should not sound like a generic operating-system accessibility voice pretending to be an AI."; "The voice should belong to the selected ANZU personality and visual presence."; cites RFC-0092 and RFC-0111), §8 (verify — no fake "loaded"), §19 ("Do expose state when the user needs confidence in what ANZU is doing."; "Do not preserve an inferior implementation solely because an older specification happened to describe it." / "Do preserve the behavioural requirement…"), §20 Q6 ("Can ANZU recover intelligently when the happy path fails?") and Q8.  
**Extends (do not rewrite):** [RFC-0111 Kokoro real runtime](0111-kokoro-real-runtime.md) (five-fact runtime truth, `TtsRuntimeState`), [RFC-0092 no silent SAPI](0092-neural-tts-default-no-silent-sapi.md), [RFC-0070](0070-higher-quality-local-tts-engines.md), [RFC-0112 exact-profile preview](0112-voice-preview-exact-profile.md), [RFC-0193 voice alternatives](0193-voice-alternatives-and-installer-choices.md) (Pocket TTS / VoiceStudio engines).  
**Amends RFC-0092 (intent preserved):** RFC-0092 forbids *silent* SAPI presented as the natural voice. Taco now asks for an automatic fallback. This RFC keeps the RFC-0092 safety property — **SAPI is never silent and never presented as the persona's voice** — and replaces "stay mute" with "speak through the next working engine and say so visibly". RFC-0092's default speaker (`butler_original_v1`, Kokoro `bm_daniel`) is unchanged.  
**Drafts #648/#649:** no gate. The Kokoro/spaCy pieces of #648 are ported into S1 (see "Relationship to drafts #648/#649").  
**Astra boundary:** Persona, presence, WebGL, appearance and voice-to-persona binding art are **out of scope** (Astra). Persona voice *selection* (`resolve_speaking_voice`) is reused, not changed.

This PR is **specs-only**. No application code.

---

## Problem

Verified in `development` @ `3f17c3d8`:

1. **The exact owner-visible string comes from self-check.** `backend/app/systems/self_check.py` emits `"Kokoro · FAILED TO LOAD. Windows SAPI is available only as an explicit system voice."` when Kokoro is not ready **and** Kokoro assets are not found; `frontend/src/tts/VoiceProfilePicker.tsx` shows `Kokoro · FAILED TO LOAD · <last_error>`.
2. **"Not yet verified" is rendered as "FAILED".** `engine_availability()["kokoro"]` is `TtsRuntimeState.ready`, which needs `synthesis_verified`. `KokoroAdapter.runtime_state()` starts from `_base_state()` (verified = false) until `verify()` runs; `warm_start._warm_kokoro_langs` only builds pipelines. A healthy-but-unverified Kokoro therefore reads "FAILED TO LOAD · Health verification pending".
3. **Real load failure candidates (unconfirmed):** (a) `resolved_kokoro_model_dir()` falls back to `preferred_gguf_install_dir(...)` on another volume where no `config.json` / `*.pth` / `voices/bm_daniel.pt` exist; (b) `kokoro_package_ready()` requires *exact* pinned versions of `kokoro` and `soundfile`, which a frozen/updated backend may not match; (c) **spaCy `en_core_web_sm` missing in the frozen backend**: Kokoro's English G2P (misaki) loads it dynamically; when absent spaCy tries its CLI downloader and raises `SystemExit`; `KokoroAdapter.get_pipeline` lets it propagate and `SystemExit` is not an `Exception`, so warm start dies and the adapter never verifies — `scripts/build-backend-sidecar.ps1` bundles neither `en_core_web_sm` nor `pocket_tts`, and `backend/jarvis_sidecar.py::_verify_frozen_imports` only imports `kokoro`/`soundfile` (draft #648 diagnosed this and is the strongest candidate); (d) pipeline init exception on CPU/torch. Which one hits Taco is **not proven**.
4. **Status lies by omission.** `workers/voice.py::voice_status()` (served by `GET /api/voice/status`) hard-codes `"fallback_active": False` and reports `actual_engine: None` whenever Kokoro is not ready; no frontend code subscribes to `/api/ws`, so a published event would be orphaned; `engines.is_piper_available()` only checks that a binary/module exists; `named_persona.pack_status` returns `tts_unavailable` for a Kokoro persona while Kokoro is merely verifying.
5. **No automatic fallback.** `workers/voice.py::synthesize_speech_result` filters system engines out unless the profile is explicitly SAPI; `engines.engine_chain_for_profile` returns `["kokoro"]` for Kokoro profiles; `persona_speech.speak_text` raises `SpeechRefused` for SAPI. Result: Kokoro down = ANZU mute, or SAPI only when the owner manually picks "Windows natural".
6. **No retry/reload.** Once Kokoro fails, nothing retries; the owner must restart ANZU.

## Decision

Ship **one RFC with three implement slices** (one ticket each, one named model, **fast off**). None waits for #648/#649.

### Fallback chain (normative)

For a persona whose primary engine is Kokoro:

`kokoro → pocket_tts → piper → voicestudio → system (SAPI / espeak)`, skipping every engine whose probe (rule 1) has not passed.

For other primaries the existing chain is kept and extended with the same tail: e.g. `chatterbox → kokoro → pocket_tts → piper → voicestudio → system`.

### Fallback voices (normative, D2 #4)

Each fallback engine speaks with exactly one voice; nothing else is ever chosen implicitly.

| Engine | Voice | Source in repo | Credit shown in the notice (`fallback_engine_credit`) |
| --- | --- | --- | --- |
| `pocket_tts` | `alba` (profile `pocket_tts_alba_en_v1`, `tts.speaker_ref = "alba"`, `POCKET_TTS_DEFAULT_VOICE`) | `voice_packs/pocket_tts_alba_en_v1/profile.json` (`tts.license = "CC-BY-4.0"`) | "Voice: Alba (Kyutai Pocket TTS), CC BY 4.0" |
| `piper` | `en_US-lessac-medium` (`rhasspy/piper-voices` v1.0.0, the file already pinned in `backend/app/mobile/companion_voice_pack_catalog.json`), resolved from `resolved_piper_voices_dir()`; no other `.onnx` is used for fallback | `tts/synthesize.py::_resolve_piper_onnx` called with `voice="en_US-lessac-medium"` | "Voice: Piper en_US-lessac-medium" plus the license string read from the voice's `.onnx.json` / model card at install time; if none is recorded, no license claim is shown |
| `voicestudio` | `default` (`VOICESTUDIO_PROBE_VOICE`, profile `voicestudio_clone_en_v1`) | `tts/voicestudio_adapter.py` | "Voice: VoiceStudio local (default voice)" |
| `system` | Windows SAPI default voice (`windows_natural_en_v1` engine path) | `tts/system_sapi.py` | "Voice: Windows SAPI (system voice)" |

Rules:

1. **Runtime truth only (probe owned by S2).** An engine joins the chain only after `tts/engines.py::probe_fallback_engine(engine_id)` passes: it synthesizes the phrase "Voice check." with the voice from the table, through the same synthesis function the chain uses, and requires a valid WAV header, duration ≥ 0.3 s and RMS above −50 dBFS (non-silent). Results are cached with a timestamp, re-run on the S1 backoff after a failure, and never run during an utterance. Kokoro keeps its RFC-0111 five-fact verification. `is_piper_available()` (binary/module present) stays as a precondition only; it is no longer sufficient.
2. **Automatic, never silent.** When a non-primary engine speaks, ANZU (a) logs `tts_synthesis` with `requested_engine`, `actual_engine`, `fallback_reason` (existing log, extended); (b) publishes one `voice_fallback` event on `backend/app/events.py::BUS` per state change (not per utterance), in the bus's own shape (see "`voice_fallback` wire contract" below); (c) updates the fallback state served by `GET /api/voice/status` (below); (d) self-check `household_voice` becomes `degraded` with "Speaking with <Engine> while Kokoro recovers — <reason>"; (e) the frontend consumer (S3) shows the notice with the credit. The notice is **non-blocking**: no modal, no confirmation, speech continues.
3. **`/api/voice/status` truth (D2 #1, owned by S2).** `workers/voice.py::voice_status()` today hard-codes `fallback_active: False` and reports `actual_engine: None` whenever Kokoro is not ready. It returns instead, from the S2 fallback state: `actual_engine` (engine of the last successful persona synthesis, or the first probed-ready engine of the active chain before any synthesis), `fallback_active` (`actual_engine` ≠ requested primary), `fallback_reason` (plain words, e.g. "Kokoro is still checking its voice", "Kokoro failed: English language model missing"), `fallback_engine_credit` (table above; `null` when not falling back). `tts_ready` is true when any chain engine is ready. The fields live in `tts_runtime` and reach clients as `GET /api/voice/status` → `tts.{actual_engine, fallback_active, fallback_reason, fallback_engine_credit}` through the existing merge in `api/voice.py::get_voice_status` (that file only gains the S1 reload route).
4. **SAPI is last and labelled (RFC-0092 guarantee kept).** SAPI is reached only when no neural engine passed its probe; SAPI audio is never tagged with the persona's neural `model_id`; `SynthesizedSpeech.engine_id`/`model_id` report `system` / `windows-sapi`; the notice names "Windows SAPI (system voice)". The persona's stored `voice_profile_id` is never rewritten to `windows_natural_en_v1`. Explicitly choosing "Windows natural" as a persona voice stays refused. Unsigned speech (no active profile) and single-engine calls (`synthesize_with_engine(engine_id=...)`) still never fall back.
5. **Persona switch while Kokoro is verifying or falling back (D2 #5, owned by S2).** `voice_profiles/catalog.py::_profile_is_available` and `persona/named_persona.py::pack_status` treat a Kokoro profile whose assets and package are installed as available while Kokoro is `verifying` or failed-with-a-ready-fallback (status `ok`, availability reason `degraded`). Switching to such a persona succeeds, binds the Kokoro profile unchanged, speaks through the fallback voice, and shows the notice. `tts_unavailable` is returned only when Kokoro assets/package are missing **and** no fallback engine passed its probe.
6. **Retry / reload.** On Kokoro failure a background re-verify runs with backoff 30 s → 2 min → 10 min (cap), off the event loop and never during an utterance. On success the chain returns to Kokoro and a `voice_fallback` event `{actual: "kokoro", reason: "recovered"}` clears the notice. Owner "Retry Kokoro" forces `reset()` + `verify(force=True)` immediately.
7. **Pending ≠ failed.** Self-check and the picker distinguish `verifying` ("Kokoro · checking voice…", status `starting`) from `failed` (real `last_error`). Warm start runs `verify_kokoro_runtime_async()` once after pipelines warm.
8. **Root cause recorded.** S1 writes the confirmed cause and evidence; the fix targets that cause, and `last_error` shown to the owner names it in plain words.

### `voice_fallback` wire contract (normative; D2 re-review #1)

`EventBus.publish` (`backend/app/events.py`) emits exactly `{task_id, kind, title, detail, stage, source, created_at}`. There is no `type` key and no free-form field, and `/api/ws` (`main.py::websocket_endpoint`) forwards that dict unchanged. The signal therefore uses the bus shape, published by S2 as:

```python
await BUS.publish_ephemeral(
    "voice",                       # task_id / channel (no TaskEvent row, no task FK)
    "voice_fallback",              # kind
    actual_engine,                 # title, e.g. "pocket_tts" or "kokoro"
    json.dumps({"requested": requested_engine, "actual": actual_engine,
                "reason": reason, "credit": credit}, ensure_ascii=False),  # detail
    "voice",                       # stage
)
```

so the frame on the socket is `{"task_id": "voice", "kind": "voice_fallback", "title": "<actual>", "detail": "<JSON string {requested, actual, reason, credit}>", "stage": "voice", "source": "jarvis-agent", "created_at": "<ISO>"}` (`source` is `publish_ephemeral`'s default). `publish_ephemeral` (persist=False) is used because the event belongs to no task. Consumers match on **`kind == "voice_fallback"`** only, and parse `detail` with `JSON.parse` inside a try (a malformed `detail` still triggers the status re-read; `GET /api/voice/status` stays the source of truth for what is rendered).

### Tests retired or inverted by S2 (D2 #6)

The new behaviour lives in **new** files (`tests/test_rfc0226_voice_fallback.py`, `tests/test_rfc0226_persona_switch.py`); existing RFC-0092 / persona tests that assert the old "mute on failure" behaviour are retired by S2 (each removal named in the S2 PR with its replacement):

| Test (file:line on `development` @ `3f17c3d8`) | Action in S2 | Replacement (new file) |
| --- | --- | --- |
| `tests/test_rfc0092_neural_tts.py:60` `test_neural_profile_chains_do_not_include_system_fallback` | Retired (behaviour inverted: chains now end with a labelled `system` tail) | `test_rfc0226_voice_fallback.py::test_neural_chain_ends_with_labelled_system_tail` and `::test_system_tail_only_after_every_neural_probe_fails` |
| `tests/test_uniform_persona_speech.py:180` `test_neural_request_never_yields_sapi` | Retired (inverted: neural all down → labelled SAPI audio + notice) | `test_rfc0226_voice_fallback.py::test_neural_all_down_yields_labelled_sapi_with_notice` and `::test_sapi_never_tagged_as_persona_model` |
| `tests/test_rfc0092_neural_tts.py:19` `test_kokoro_failure_never_silently_returns_system_audio` | **Kept unchanged** (single-engine `synthesize_with_engine` never falls back) | — |
| `tests/test_rfc0092_neural_tts.py:43` `test_unknown_engine_does_not_silently_return_system_audio` | Kept unchanged | — |
| `tests/test_rfc0092_neural_tts.py:108` `test_primary_tts_backend_never_falls_back_to_sapi` | Kept unchanged (primary backend selection unchanged) | — |
| `tests/test_rfc0092_neural_tts.py:121` `test_unsigned_speech_does_not_fall_back_to_sapi` | Kept unchanged (rule 4) | — |
| `tests/test_uniform_persona_speech.py:169` `test_windows_natural_is_never_the_persona_voice` | Kept unchanged | — |
| `tests/test_rfc0137_named_persona.py:120` `test_missing_non_anzu_pack_does_not_write_sapi`, `:189` `test_appearance_overrides_persist_and_reject_sapi` | Kept unchanged (missing non-Kokoro pack still refused; SAPI never written) | — |

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

Touched live UI: Settings → Voice. The voice status line renders **only** in `frontend/src/tts/VoiceProfilePicker.tsx` (embedded by `frontend/src/settings/VoiceSettingsPane.tsx`, which has no status line of its own), so the notice goes in the picker and `VoiceSettingsPane.tsx` is **not** touched (D2 #8). Added alongside: a small non-blocking HUD notice (`frontend/src/hud/VoiceFallbackNotice.tsx`) so the owner sees the fallback without opening Settings.

| Current live behaviour | Preserved? | Added alongside |
| --- | --- | --- |
| Profile list with select / preview / install buttons, "Install household voice" | **Yes**, unchanged | "Retry Kokoro" button in the status line |
| READY line `Kokoro 82M · <voice> · READY` | **Yes**, same text | — |
| Failure line shows `last_error` | **Yes** (text still carries the real error) | "Speaking with <Engine> meanwhile · <credit>" suffix; `verifying` state |
| Selecting "Windows natural" for a named persona is refused with the existing message | **Yes** | — |
| Preview uses the exact profile (RFC-0112) and reports the actual engine | **Yes** — preview does **not** fall back | — |
| Health rail `household_voice` item and link | **Yes**, same id/label | Degraded-with-fallback detail |
| Settings → Voice pane layout (STT/TTS selects, speak-replies toggle) | **Yes**, file untouched | — |
| HUD (no voice notice today) | n/a | Dismissible `VoiceFallbackNotice` chip while `fallback_active`; dismiss hides it until the next state change |

The sentence "Speech stays silent if the neural voice fails; it will not pretend that SAPI is Kokoro." becomes "If Kokoro fails, ANZU keeps talking with the next local voice and tells you which one; it never presents SAPI as Kokoro." — same honesty guarantee, new behaviour; the copy change is required because the old text would now be false (§19). Nothing else is removed.

### Stub rule

No stubs, soft-fails or fake states. A `voice_fallback` event nobody renders, a status field that is always `false`, a probe that only checks for a binary, a retry button that only resets UI state, or a chain that lists an engine that cannot synthesize, is a fail.

---

## Relationship to drafts #648/#649

PG ruling via CoS (2026-10-20): no gate on Taco's drafts. Ported pieces are cited in S1 as "Ported from #648 `<file>::<function>`".

| Draft piece | Decision | Slice |
| --- | --- | --- |
| #648 `tts/kokoro_adapter.py::get_pipeline` — wrap `KPipeline(...)` in `except SystemExit` → `RuntimeError("Kokoro English pipeline unavailable; install en_core_web_sm")` | Ported | S1 |
| #648 `tts/warm_start.py::_warmup_guarded` — catches `(Exception, SystemExit)`, stores `warmup_error` (≤240 chars) in `_last_report`, logs a warning; `schedule_tts_warm_start` schedules `_warmup_guarded` instead of `_warmup_sync` | Ported | S1 |
| #648 `scripts/build-backend-sidecar.ps1` — ensure `en_core_web_sm` (`python -m spacy download en_core_web_sm`, throw on failure) and `pocket-tts==3.3.0`; PyInstaller `--collect-all en_core_web_sm --collect-all pocket_tts`; failure text "Frozen default voice stack is incomplete (Kokoro, soundfile or the English model)." | Ported | S1 |
| #648 `backend/jarvis_sidecar.py::_verify_frozen_imports` — also import `pocket_tts`; `spacy.load("en_core_web_sm")` inside `try/except (Exception, SystemExit)` → `missing.append("spaCy English pipeline: …")`; success line names all four | Ported | S1 |
| #648 `tests/test_rfc0111_kokoro_runtime.py` new tests `test_voice_pipeline_system_exit_becomes_runtime_failure`, `test_optional_warmup_system_exit_does_not_stop_event_loop`, `test_frozen_voice_check_rejects_missing_language_resources` | Ported as equivalents in new `tests/test_rfc0226_kokoro_load.py` (existing RFC-0111 file not edited) | S1 |
| Everything else in #648/#649 | Not needed by this RFC | — |

**Reconciliation rule:** if #648 lands first, S1 reuses #648's `SystemExit` guard, `_warmup_guarded`, build-script steps and sidecar check as-is (no second guard) and the duplicate ported tests are dropped from `tests/test_rfc0226_kokoro_load.py`; S1 then only adds verifying/failed state, re-verify backoff, reload endpoint and the audit. If S1 lands first, #648 rebases onto it and drops its identical hunks.

---

## Slices (one ticket each)

Assign order: **S1 → S2 → S3.**

### S1 — Kokoro load root cause + reliable load, verify, retry

**Model:** Grok 4.6 (fast off) · **Lane:** D2 · **Depends:** none

| Path | Why |
| --- | --- |
| `docs/audits/2026-10-20-kokoro-load-root-cause.md` (new) | Evidence on Taco's installed build + clean install: resolved model dir, asset listing, package versions in the frozen backend, verify exception trace, timing |
| `backend/app/tts/kokoro_adapter.py` | Ported from #648 `kokoro_adapter.py::get_pipeline` (`SystemExit` → `RuntimeError` naming `en_core_web_sm`); fix any further confirmed cause; `verifying` vs `failed` state; background re-verify with backoff; `reload()` = `reset()` + `verify(force=True)`; plain-language `last_error` |
| `backend/app/tts/warm_start.py` | Ported from #648 `warm_start.py::_warmup_guarded`; after pipeline warm, run one `verify_kokoro_runtime_async()`; record result in `last_warm_report` |
| `backend/app/tts/runtime_state.py` | Add `verifying: bool` to `TtsRuntimeState` (serialized; `ready` semantics unchanged) |
| `backend/app/api/voice.py` | `POST /api/voice/kokoro/reload` → returns fresh runtime state |
| `scripts/build-backend-sidecar.ps1` | Ported from #648 (`en_core_web_sm` + `pocket-tts==3.3.0` ensure steps, `--collect-all en_core_web_sm --collect-all pocket_tts`, failure text) |
| `backend/jarvis_sidecar.py` | Ported from #648 `_verify_frozen_imports` (`pocket_tts` import + `spacy.load("en_core_web_sm")` check) |
| `tests/test_rfc0226_kokoro_load.py` (new) | Below |

- [ ] Audit names the confirmed root cause on Taco's machine with evidence (incl. whether `spacy.load("en_core_web_sm")` fails in the installed frozen backend); the fix addresses it and a regression test reproduces it.
- [ ] `KPipeline` raising `SystemExit` → `RuntimeError` mentioning `en_core_web_sm`; adapter `last_error` carries it; the API process keeps running.
- [ ] Warm start whose work raises `SystemExit` records `warmup_error` in `last_warm_report()` and the event loop keeps running.
- [ ] `_verify_frozen_imports` exits 1 with "spaCy English pipeline" on stderr when `spacy.load` fails; the sidecar build script fails the build in that case.
- [ ] Fresh start with valid assets → state goes `verifying` → `ready` without owner action; never shows "FAILED" while verifying.
- [ ] Missing assets / wrong version / pipeline exception → `ready == false`, `last_error` names the specific cause; no code path sets `synthesis_verified` without a produced WAV.
- [ ] Background re-verify runs on backoff and recovers when the cause is removed (test swaps assets in); it never runs during an active synthesis.
- [ ] `POST /api/voice/kokoro/reload` returns the new state and is serialized with synthesis (adapter lock).
- [ ] `tests/test_rfc0111_kokoro_runtime.py`, `tests/test_rfc0092_neural_tts.py` and `tests/test_uniform_persona_speech.py` pass **unchanged** after S1 (S1 edits none of them). The only later change to the existing RFC-0092 / uniform-persona tests is S2's removal of exactly `test_rfc0092_neural_tts.py:60` and `test_uniform_persona_speech.py:180` (table above); no assertion in any existing test is amended, and replacements live only in new `tests/test_rfc0226_*.py` files.

### S2 — Fallback chain, real probes, `/api/voice/status` truth, `voice_fallback` signal, persona switch

**Model:** Grok 4.6 (fast off) · **Lane:** D2 · **Depends:** S1, RFC-0225 S2 (sequential owner of `workers/voice.py`)

| Path | Why |
| --- | --- |
| `backend/app/tts/engines.py` | `engine_chain_for_profile`: tail per the normative chain; `probe_fallback_engine()` (rule 1, real synthesis smoke test, cached); `fallback_chain_for_profile()` filters to probed engines; `FALLBACK_VOICES` table (voice + credit per engine) |
| `backend/app/tts/synthesize.py` | Second owner after RFC-0225 S2 (its Piper `registered_subprocess` wrapper kept). Fallback synthesis uses the table's voice (`_resolve_piper_onnx(voice="en_US-lessac-medium")`, Pocket `alba`, VoiceStudio `default`); no other implicit voice |
| `backend/app/workers/voice.py` | Second owner after RFC-0225 S2 (registry wrappers kept). `synthesize_speech_result`: allow the system tail only when the chain reached it; `SynthesizedSpeech` gains `fallback_reason`; `voice_status()` returns real `actual_engine`, `fallback_active`, `fallback_reason`, `fallback_engine_credit` from the fallback state (rule 3); extend `tts_synthesis` log |
| `backend/app/tts/persona_speech.py` | Persona speech uses the chain (persona primary first); `SpeechRefused` only for an explicitly SAPI persona voice; holds the fallback state and publishes `voice_fallback` on `BUS` on state change, exactly per the wire contract (`BUS.publish_ephemeral("voice", "voice_fallback", …)`) |
| `backend/app/voice_profiles/catalog.py` | `_profile_is_available`: Kokoro profile with installed assets/package is available (`degraded`) while verifying or falling back (rule 5) |
| `backend/app/persona/named_persona.py` | `pack_status`: same rule; `tts_unavailable` only when Kokoro is missing **and** no fallback passed its probe |
| `backend/app/systems/self_check.py` | `household_voice`: `ready` / `starting` (verifying) / `degraded` with "Speaking with <Engine> while Kokoro recovers — <reason>" / `missing` |
| `tests/test_rfc0226_voice_fallback.py` (new), `tests/test_rfc0226_voice_status.py` (new), `tests/test_rfc0226_persona_switch.py` (new) | Below |
| `frontend/test-fixtures/voice_fallback_event.json` (new) | The exact bus frame of the wire contract (Kokoro → Pocket TTS), shared by the S2 backend test and the S3 JS test |
| `tests/test_rfc0092_neural_tts.py`, `tests/test_uniform_persona_speech.py` | **Only** the removal of the two retired tests listed in "Tests retired or inverted by S2" (`test_rfc0092_neural_tts.py:60`, `test_uniform_persona_speech.py:180`); no assertion in either file is amended and every other test is byte-identical; replacements live in the new files above |

- [ ] Kokoro failing + Pocket TTS probed → audio from Pocket TTS voice `alba`; `actual_engine == "pocket_tts"`, `fallback_reason` set.
- [ ] Kokoro + Pocket failing, Piper with `en_US-lessac-medium` present → Piper audio from that voice; Piper binary present but the voice missing or producing silence → probe fails, Piper skipped (fixtures: missing ONNX, all-zero WAV, sub-0.3 s WAV).
- [ ] Kokoro + all neural engines failing → SAPI audio; `engine_id == "system"`, `model_id == "windows-sapi"`; persona `voice_profile_id` unchanged; notice credit "Windows SAPI (system voice)".
- [ ] **(D2 #1)** `GET /api/voice/status` while Pocket speaks for a failed Kokoro → `actual_engine: "pocket_tts"`, `fallback_active: true`, `fallback_reason` names the Kokoro cause, `fallback_engine_credit: "Voice: Alba (Kyutai Pocket TTS), CC BY 4.0"`; Kokoro ready → `fallback_active: false`, credit `null`; nothing hard-coded (test flips states).
- [ ] `voice_fallback` published on `BUS` once per state change (Kokoro→Pocket, Pocket→Kokoro recovered) with `credit`, not per utterance. **(D2 re-review #1)** `tests/test_rfc0226_voice_fallback.py::test_voice_fallback_event_exact_bus_payload`: a `BUS.subscribe()` queue receives a dict whose keys are exactly `{task_id, kind, title, detail, stage, source, created_at}`, with `task_id == "voice"`, `kind == "voice_fallback"`, `title == "pocket_tts"`, `stage == "voice"`, `source == "jarvis-agent"`, `json.loads(detail) == {"requested": "kokoro", "actual": "pocket_tts", "reason": <reason>, "credit": "Voice: Alba (Kyutai Pocket TTS), CC BY 4.0"}`, no `type` key, and no `TaskEvent` row written. The test also asserts that this dict equals the committed fixture `frontend/test-fixtures/voice_fallback_event.json` (every key and value except `created_at`, which must parse as ISO 8601), so a bus-shape change fails both the backend and the JS test.
- [ ] **(D2 #5)** Switching to a Kokoro persona while Kokoro is `verifying` → switch succeeds (no `tts_unavailable`), next line speaks via the fallback, status shows the notice fields; same while Kokoro is failed with Pocket ready; Kokoro assets missing and no fallback probed → `tts_unavailable` as today.
- [ ] Self-check never reports `ready` while a fallback engine is speaking; detail names the engine and reason.
- [ ] Explicit persona voice = `windows_natural_en_v1` still refused; exact-profile preview (RFC-0112) does not fall back; unsigned speech still refused (kept tests green).
- [ ] No synthesis path blocks the owner turn longer than today on failure (fallback attempt bounded; probes cached and never inline in a turn).

### S3 — Fallback notice (picker + HUD), `voice_fallback` consumer, Retry Kokoro (UI)

**Model:** Composer 2.5 (fast off) · **Lane:** UX · **Depends:** S2, RFC-0225 S4 (sequential owner of `HudShell.tsx`)

| Path | Why |
| --- | --- |
| `frontend/src/tts/voiceFallback.ts` (new) | **The `voice_fallback` consumer (D2 #2):** opens `/api/ws` through `getAuthUrl("/api/ws")` (same auth helper the EventSource streams use), filters on **`kind == "voice_fallback"`** (the bus has no `type` key; wire contract above), and on each event re-reads `GET /api/voice/status`; if the socket closes it polls `/api/voice/status` every 15 s until it reconnects; exposes `useVoiceFallback()` → `{active, actualEngine, reason, credit}` |
| `frontend/src/tts/VoiceProfilePicker.tsx` | Status line: `verifying` text; "Speaking with <Engine> meanwhile · <credit>" suffix from `useVoiceFallback()`; "Retry Kokoro" button → `POST /api/voice/kokoro/reload` with pending/result state; updated honesty sentence |
| `frontend/src/hud/VoiceFallbackNotice.tsx` (new) | Non-blocking, dismissible HUD chip "Speaking with <Engine> while Kokoro recovers · <credit>" while `active`; dismiss hides it until the next state change |
| `frontend/src/hud/HudShell.tsx` | One mount line for `<VoiceFallbackNotice />` (second owner after RFC-0225 S4; existing mounts untouched) |
| `frontend/voice-fallback-notice.test.mjs` (new; reads S2's `frontend/test-fixtures/voice_fallback_event.json`, not edited here); `frontend/package.json` (`test:voice-fallback-notice`, one line); `.github/workflows/pr-tests.yml` (one append-only `frontend-build` step `- name: Voice fallback notice tests (RFC-0226 S3)` / `run: npm run test:voice-fallback-notice`) | Below |

`frontend/src/settings/VoiceSettingsPane.tsx` is **not** edited (it renders the picker, which carries the status line).

- [ ] Kokoro failing + fallback speaking → picker shows the real error **and** "Speaking with Pocket TTS meanwhile · Voice: Alba (Kyutai Pocket TTS), CC BY 4.0"; HUD chip shows the same; no modal, chat unaffected.
- [ ] **(D2 #3)** The CC BY 4.0 Alba credit text is rendered whenever Pocket TTS is the fallback (picker and HUD; JS test).
- [ ] **(D2 #2, re-review #1)** A `voice_fallback` message on the socket triggers a status re-read and updates picker + chip; socket closed → 15 s polling keeps them current (JS test with fake socket/timers); `Kokoro recovered` event clears both. The JS test feeds the exact bus dict from `frontend/test-fixtures/voice_fallback_event.json` (S2's golden file): that frame triggers the re-read; the same frame with `kind` changed (e.g. `model_switch`) does not; a frame carrying `type: "voice_fallback"` but another `kind` does not; a frame with malformed `detail` still triggers the re-read.
- [ ] "Retry Kokoro" shows working state, then READY or the new error; double-click does not queue two reloads.
- [ ] Verifying state shows "checking voice…", never "FAILED TO LOAD".
- [ ] Every existing control (select, preview, install, Install household voice) still present and working — PR includes the preserved-behaviour section.
- [ ] **(D2 #7)** `npm --prefix frontend run build` + lint pass; `npm --prefix frontend run test:voice-fallback-notice` runs in the `pr-tests.yml` step above.

---

## Overall acceptance

- [ ] On Taco's PC after update: Settings → Voice shows Kokoro READY within the warm-start window, or a named real cause plus the fallback engine speaking.
- [ ] Forced Kokoro failure (rename weights) → ANZU keeps speaking via the next neural engine, the notice is visible, renaming back recovers automatically within the backoff window without restart.
- [ ] SAPI is reached only when no neural engine is verified, and is labelled as SAPI everywhere.
- [ ] RFC-0111 / RFC-0112 suites green unchanged; RFC-0092 / uniform-persona suites green minus the two retired tests (replacements in new files); full backend suite, frontend build and the S3 JS test in CI.

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0226-S1 | Kokoro root cause + reliable load/verify/retry (ports #648 spaCy guard) | Grok 4.6 | D2 | — |
| 0226-S2 | Fallback chain, real probes, voice status truth, voice_fallback, persona switch | Grok 4.6 | D2 | S1, 0225-S2 |
| 0226-S3 | Fallback notice (picker + HUD) + voice_fallback consumer + Retry Kokoro | Composer 2.5 | UX | S2, 0225-S4 |

## Likely files

See ownership tables. Cross-RFC chains (sequential): `backend/app/workers/voice.py` RFC-0225 S2 → 0226-S2; `backend/app/tts/synthesize.py` RFC-0225 S2 → 0226-S2 (shared: 0225-S2 registers the Piper subprocess, 0226-S2 pins the fallback voices); `frontend/src/hud/HudShell.tsx` RFC-0225 S4 → 0226-S3. No other file here is owned by another RFC of the batch. Within this RFC: `frontend/test-fixtures/voice_fallback_event.json` 0226-S2 (creates) → 0226-S3 (reads only).

`frontend/package.json` and `.github/workflows/pr-tests.yml` are shared by every frontend ticket in the 2026-10-17 batch: each ticket adds exactly one `test:*` script line and one `frontend-build` step (append-only hunks, trivial rebase) and touches nothing else in those files.

## Out of scope

- Persona/presence/WebGL/appearance (Astra); persona→voice mapping.
- New TTS engines or new voice packs (RFC-0193).
- STT / recognizer changes.
- Installer voice task UI (RFC-0228 handles installed/greyed state generically).

## Risks

- **Fallback voice mismatch with persona** — mitigated by the visible notice and fast recovery; persona binding is never rewritten.
- **Retry loop CPU cost** — capped backoff (10 min), skipped while a synthesis is running.
- **#648 overlap** — handled by the reconciliation rule; ported hunks cited by file/function.
