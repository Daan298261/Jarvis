# RFC-0128: Progressive answers with background verification

**Status:** implemented  
**Queue item:** (optional) progressive owner answers  
**Author:** Cursor cloud worker  
**Date:** 2026-03-19

## Problem

Double-checking assistant answers improves accuracy but blocks the owner on a second model pass. Owners should see the initial answer immediately while a lightweight verification runs asynchronously; they are notified only when verification finds a meaningful correction.

## Decision

1. After an initial owner-facing answer is produced on conversation paths (`owner_chat` API and agent `CONVERSATION_CLASS`), publish that answer immediately (no wait for verification).
2. Schedule a background verification task (`asyncio.create_task`) that performs a second, non-blocking model call with a dedicated verify prompt: if the answer stands, reply exactly `VERIFIED_OK`; otherwise reply with the corrected answer only.
3. When verification returns `VERIFIED_OK` (or an equivalent normalized match), remain silent (optional debug bus event).
4. When verification differs materially, publish a follow-up owner message / `chat_tts` prefixed with “I double-checked and have an update: …” and append the correction to the conversation transcript.
5. Implement logic in `backend/app/agent/background_verify.py`, hooked from `owner_chat.py` and the conversation branch in `loop.py`.

We will **not** rework the full managed-task verification loop or block worker execution on this pass in this RFC.

## Acceptance criteria

- [ ] Initial owner/chat answers are published before background verification completes
- [ ] Background pass uses the verify prompt contract and treats `VERIFIED_OK` as silent success
- [ ] Material corrections emit follow-up TTS/chat and append to conversation history
- [ ] Unit tests in `tests/test_rfc0128_background_verify.py`
- [ ] Unit tests pass (`python3 -m pytest`)

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/agent/background_verify.py`, `backend/app/persona/owner_chat.py`, `backend/app/agent/loop.py`, `backend/app/config.py` |
| Tests | `tests/test_rfc0128_background_verify.py` |
| Docs | `docs/rfcs/0128-progressive-answer-background-verify.md` |

## Out of scope

- Replacing in-loop `verify_code` / critic passes for long-running managed tasks
- Portal UI for verification status
- Swarm / multi-agent verification

## Notes

- Controlled by `dialogue.background_verify` in settings (default on) and `JARVIS_BACKGROUND_VERIFY=0` to disable at runtime.
- Desktop live-model sign-off remains optional; unit tests use mocked inference.

## Implementation note

Landed on `development` via #339 @ `b85d1b14` (publish the owner answer, then verify in the background; silent on `VERIFIED_OK`) and #375 @ `06cbf5b7` (async verify contract tests). Live model verification remains desktop sign-off. Acceptance checkboxes left open for that sign-off.
