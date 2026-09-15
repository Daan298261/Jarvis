# RFC-0092: Neural TTS default, no silent SAPI

**Status:** accepted
**Queue item:** P0 — Default neural TTS (Taco pet peeve through 1.3.9)
**Author:** Jarvis Architect
**Date:** 2026-09-15

**Related (do not rewrite):** RFC-0070 higher-quality local TTS; RFC-0081 better default TTS (**implemented**, catalog/default **regressing**); RFC-0089 GPU-first + natural TTS / no silent SAPI (**accepted**, TTS acceptance **unchecked**); RFC-0062 voice profile catalog; RFC-0056 butler voice.

This PR is **specs-only**. Product code is a follow-up implement ticket.

## Problem

Through Jarvis **1.3.9** every spoken voice still sounds robotic. CoS verification (2026-09-15) found:

- Active / preferred default is `windows_natural_en_v1` = **Windows SAPI** (`engine_id: "system"`, `model_id: "windows-sapi"`) with `quality_tier: "natural"` — a mislabel. Settings copy even pushes “Windows natural” as the SAPI pick.
- Kokoro butler (`butler_original_v1` / `bm_daniel`) exists; weights and pack are on disk. It is **not** the default. `DEFAULT_VOICE_PROFILE_ID` and `VoiceSettings.active_profile_id` seed Windows-natural. `preferred_default_voice_profile_id()` prefers Windows-natural when that pack is available, and `get_active_voice_profile_id()` can **migrate owners off Kokoro** onto Windows-natural (`.migrated_voice_windows_natural_v1`).
- `synthesize.py` **silently falls through** Kokoro exceptions to SAPI (`legacy_system_tts_available()` → `_synthesize_system`). Neural profile `engine_chain_for_profile` also ends in `"system"`. Returning SAPI audio while the active profile is still Kokoro/Chatterbox/Orpheus is a fail. RFC-0089 accepted that this must stop; its TTS criteria remain unchecked.
- Chatterbox remains gated behind `JARVIS_TTS_CHATTERBOX` (engine availability, pack install hint, Settings copy). That env gate is not a one-click Desktop Setup quality path for the shipping Windows build.
- OpenViking is **agent memory**, not TTS. Do not propose it for voice.

RFC-0081 marked default Kokoro butler implemented; 1.3.9 (`Windows TTS default`) reintroduced the robotic SAPI default under a “natural” label.

## Decision

1. **Default voice profile** = `butler_original_v1` (Kokoro `bm_daniel`, speaking rate `0.96`). A better **already in-tree**, MIT/Apache-licensed local neural speaker may replace `bm_daniel` only if documented in the implement PR. **Never** set Windows SAPI / `windows_natural_en_v1` (or any SAPI adapter) as the default. **Never** label a SAPI profile `quality_tier: "natural"` — SAPI is `baseline` / `system` only. Display name must not say “natural” (e.g. “Windows system (SAPI)”).
2. **No silent SAPI when neural was requested.** If the active (or requested) profile’s `engine_id` is Kokoro, Chatterbox, or Orpheus, synthesis must **not** return SAPI/espeak/pyttsx3 audio on failure. Failure **surfaces** (HTTP/error to Settings/preview and speak path) and **retries the neural engine** (and/or another neural in the same class, e.g. Chatterbox → Kokoro). An **optional explicit user-visible degrade** to SAPI is allowed only after the neural path failed and the UI/API records that the owner accepted degrade — never while pretending the neural profile succeeded. This closes RFC-0089’s unchecked “Kokoro/Chatterbox failure does not return SAPI audio” criterion. GPU LM Studio load (RFC-0089 GPU half) may land separately.
3. **Chatterbox (or better MIT/Apache local already in-tree) one-click quality path** on Desktop Setup **without** requiring `JARVIS_TTS_CHATTERBOX` for the shipping Windows build. The env gate may remain for unsupported platforms and CI only, and must be documented. Default first speech stays Kokoro (RFC-0070); Chatterbox stays opt-in quality, not the silent default.
4. **Desktop A/B proof.** Spoken result metadata and/or sample WAV sidecars **must include `engine_id` and `profile_id`** so the owner can hear/verify which engine actually spoke. Settings preview plus optional debug sample files under a known Desktop path (e.g. `Desktop/Jarvis/tts-samples/`). Preview that returns only unlabeled WAV bytes is a fail.

**Catalog / first-run rules**

- Stop auto-migrating the active selection to Windows-natural when Kokoro is available. Remove (or invert) the Kokoro → Windows-natural migration marker behavior.
- First-run / Desktop Setup seeds `butler_original_v1` as active (`config` default, persona pack, installer seed).
- Curated picker may still list SAPI as an explicit **system** choice; it must not rank above the default butler or be the empty-settings fallback.

**Will not:** use OpenViking for TTS; cloud TTS as default; Codsworth / Fallout / actor / Marvel clones; leave SAPI as default under a “natural” label; rewrite RFC-0070/0081/0089/0062/0056.

## Acceptance criteria

- [ ] Fresh Setup / default settings: active profile is `butler_original_v1` (Kokoro `bm_daniel` or documented better in-tree neural), not `windows_natural_en_v1`
- [ ] No SAPI / `engine_id: "system"` profile may use `quality_tier: "natural"`
- [ ] Neural engine request never silently returns SAPI audio; error/retry path documented and testable (closes RFC-0089 unchecked TTS criterion)
- [ ] Chatterbox (or successor MIT/Apache already in-tree) available as one-click quality path on Desktop Setup without `JARVIS_TTS_CHATTERBOX` on the shipping Windows build
- [ ] Preview/sample path records `engine_id` (+ `profile_id`) in metadata or sidecar for A/B listening
- [ ] Specs-only in this PR
- [ ] Implement follow-up: `python3 -m pytest` TTS routing/fallback tests (`tests/test_rfc0070_tts.py` updates + new `tests/test_rfc0092_*.py`)

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/tts/synthesize.py`, `engines.py`, `system_sapi.py`, `pack_install.py`; `backend/app/voice_profiles/catalog.py`; `backend/app/config.py`; `backend/app/api/voice_profiles.py`; `backend/app/workers/voice.py`; persona pack / `persona_pack.json` |
| Frontend | `frontend/src/tts/VoiceProfilePicker.tsx`, `voiceProfiles.ts`, Settings voice preview |
| Packs | `voice_packs/butler_original_v1/`, `voice_packs/windows_natural_en_v1/profile.json` |
| Tests | `tests/test_rfc0070_tts.py`, `tests/test_voice_profiles.py`, new `tests/test_rfc0092_*.py` |
| Installer | Desktop Setup seed of default profile / Chatterbox optional one-click (do not overwrite `installer/windows/` from a specs PR) |
| Docs | this RFC; optional `JARVIS_MASTER_PLAN.md` §59 Decision Log line only |

## Out of scope

Product implementation in this PR. OpenViking (memory, not TTS). Cloud TTS default. GPU LM Studio / Ollama `num_gpu` load (RFC-0089 GPU half — may land separately). Marvel / Iron Man / Codsworth / Fallout / actor clones. Trajectory-prompt collapse (RFC-0089 remainder). Chatterbox as the silent first-run default.

## Notes

- Taco pet peeve, urgent 2026-09-15 via CoS. Complements RFC-0089 (make no-silent-SAPI landable) and corrects the RFC-0081 catalog/default regression that 1.3.9 reintroduced.
- Evidence in tree (do not treat as already fixed): `windows_natural_en_v1` `quality_tier: "natural"`; `catalog.py` `DEFAULT_VOICE_PROFILE_ID = WINDOWS_NATURAL_VOICE_PROFILE_ID` plus Kokoro→Windows migration; `synthesize.py` Kokoro `except Exception` → SAPI; `JARVIS_TTS_CHATTERBOX` in `engines.py` / pack install / picker copy; tests assert Windows-natural default (`test_default_voice_profile_is_windows_natural`).
- Linux cloud VMs cannot sign off live listen quality; implement unit-tests the routing/fallback/metadata contracts. Desktop owner A/B listen remains operational verification after Setup rebuild.
- Implement launch: implement this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`; do not merge other PRs.
