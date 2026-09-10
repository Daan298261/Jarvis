# RFC-0066: Companion + realtime voice program verification

**Status:** implemented  
**Queue item:** P1 — Android companion / RFC-0064 acceptance  
**Author:** Cursor cloud (continuation of Astra Android companion run)  
**Date:** 2026-09-10

## Problem

Astra died after green GitHub Actions on the companion branch. RFC-0064 code is on
`cursor/android-realtime-voice-3291`, but the program still needs an explicit
verification pass against a live PC endpoint: focused pytest, companion/realtime
routes, and a recorded evidence artifact.

## Decision

After RFC-0065 bring-up:

1. Run focused automated tests: `tests/test_mobile_realtime_voice.py`,
   `tests/test_mobile_companion.py`, related mobile suites.
2. Hit live companion capabilities / system endpoints on the running PC API.
3. Exercise the realtime WebSocket hello path with a paired test device when the
   in-process ASGI path is insufficient to prove the live server.
4. Save evidence under `/opt/cursor/artifacts/` and note desktop/phone sign-off
   items that cloud cannot verify.

## Acceptance criteria

- [x] Focused mobile + realtime pytest suite passes.
- [x] Live `GET /api/system` and unauthenticated companion probe behave as expected.
- [x] Live authenticated realtime WS `hello` → `session` succeeds (or documented blocker).
- [x] Internal reference summarizes how to re-run verification.
- [x] Physical-device latency / live TTS quality remain explicit sign-off (not claimed here).

## Likely files

| Area | Paths |
| --- | --- |
| Tests | `tests/test_mobile_realtime_voice.py`, `tests/test_mobile_*.py` |
| Docs (RFC) | `docs/rfcs/0066-companion-realtime-voice-verification.md` |
| Internal refs | `project/jarvis/jarvis/internal/references/companion-realtime-voice.md` |
| Artifacts | `/opt/cursor/artifacts/*` |

## Out of scope

Public relay/Firebase deploy, editing `ANDROID_CLIENT.md` / master plan, APK sideload on a physical phone.

## Notes

Depends on RFC-0065 endpoint bring-up. Stacks with PR #146 / companion preview #132.
