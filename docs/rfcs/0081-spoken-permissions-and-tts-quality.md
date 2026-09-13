# RFC-0081: Better default TTS, spoken permission asks, original butler (not a movie clone)

**Status:** implemented  
**Queue item:** Default voice quality + spoken permission grant  
**Author:** Taco request via Cursor  
**Date:** 2026-09-12

**Related:** RFC-0061/0062/0070 voice catalog; RFC-0079 computer-use permissions. IP rules unchanged.

## Problem

The Settings picker shows `install_required` stubs with no Install button (RFC-0070 fail). The default “household butler” often falls through to robotic SAPI because Kokoro weights are not staged. Taco wants a calmer household-AI delivery and spoken permission turns (“I need your permission to search the internet, sir — do you grant it?”) that can be answered by voice. Copyrighted Iron Man / Marvel JARVIS clones are not allowed.

## Decision

1. **Original butler only.** Do not ship, download, or label a Marvel/Iron Man JARVIS clone. Keep IP guards. Delivery is an original British household aide (`sir` in spoken confirms).
2. **Quality:** Prefer Kokoro when the Python package is installed; silently install the engine into the Jarvis interpreter and stage Kokoro-82M weights (Setup + first speak). Default speaker `bm_daniel`, speaking rate `0.96`. End users never run pip.
3. **Install:** Settings shows **Get this voice** for `install_required` packs (existing `POST /api/voice-profiles/{id}/install`).
4. **Spoken permission:** confirmation payload includes `spoken_prompt`. The permission UI speaks it, then records a short yes/no/always answer via `/api/voice/transcribe`.

**Will not:** clone copyrighted character voices; cloud TTS as default; auto-listen without a visible Listening state.

## Acceptance criteria

- [x] Default butler profile uses Kokoro `bm_daniel` at 0.96
- [x] Kokoro is preferred over SAPI when the package is present; weights download on first speak
- [x] Settings can one-click install optional packs
- [x] Permission prompt includes a spoken ask and voice reply mapping
- [x] Household voice is prepared by Setup / Jarvis itself (no end-user pip)
## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/tts/engines.py`, `backend/app/tts/synthesize.py`, `backend/app/tts/system_sapi.py`, `backend/app/tts/pack_install.py`, `backend/app/policy/computer_permissions.py`, `backend/app/persona/persona_pack.json` |
| Frontend | `frontend/src/tts/VoiceProfilePicker.tsx`, `frontend/src/chat/PermissionPrompt.tsx`, `frontend/src/chat/spokenGrant.ts` |
| Packs | `voice_packs/butler_original_v1/` |
| Tests | `tests/test_rfc0070_tts.py`, `tests/test_computer_permissions.py` |

## Out of scope

Marvel / Iron Man JARVIS clones, cloud TTS, HexStrike, APK JDK (RFC-0080).

## Notes

Videos using a movie JARVIS clone are copyrighted character voices. Jarvis ships an original British household aide (`sir`, Kokoro `bm_daniel`) with the same register, not a clone.
