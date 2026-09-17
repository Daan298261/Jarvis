# RFC-0101: Pipecat realtime voice pipeline

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md) ([PR #270](https://github.com/Daan298261/Jarvis/pull/270)).  
**Related (do not rewrite):** **RFC-0092 neural TTS default / no silent SAPI** (Sol-priority — this RFC must **not** fold it). RFC-0075 speak path + first-chunk TTS. RFC-0033 provider-neutral realtime voice I/O. RFC-0036 streaming talk-back. RFC-0064 Android realtime voice. RFC-0066 companion verification. RFC-0070 engines.

This PR is **specs-only**. Do not commit local clones. **Do not rewrite RFC-0092.**

## Instagram source

Taco Instagram `@tacotcr` Saved → **jarvis**. Architect box clone (already downloaded; **do not commit**):

| Repo | Canonical | Local path |
| --- | --- | --- |
| Pipecat | [pipecat-ai/pipecat](https://github.com/pipecat-ai/pipecat) | `/workspace/projects/rfc/pipecat` |

## Pipeline (RFC-0095 four-step)

| Step | Result (this RFC) |
| --- | --- |
| 1. Download | **Done locally** at `/workspace/projects/rfc/pipecat`. Not vendored. |
| 2. Usefulness review | **Score 3/5.** Primary bucket: `mas_integration` (realtime voice transport). Not a TTS engine. |
| 3. Integrate decision | **`partial`** — optional Pipecat pipeline **behind** existing Jarvis STT/TTS/persona. Align with voice RFCs; do not replace Kokoro default or reopen SAPI. Taco can override. |
| 4. Implement | Later named ticket. Must not land as a 0092 rewrite. |

## Problem

Jarvis already has host TTS (`backend/app/tts/`, `backend/app/workers/voice.py`), speak filter (RFC-0075), and companion duplex (RFC-0064). RFC-0033 still wants a provider-neutral realtime I/O layer (barge-in, device identity, reconnect) without binding to Gemini Live. Instagram-jarvis saves Pipecat (open realtime voice-agent frames: transport, VAD, turn-taking, frame pipeline). Risk: an implementer uses Pipecat to swap TTS engines or reintroduce SAPI, fighting RFC-0092.

## Decision

Add an **optional Pipecat realtime pipeline adapter** (`partial`) that **aligns with** RFC-0033 / 0064 / 0075 and **does not rewrite RFC-0092**.

1. Pipecat may own **transport + turn-taking + VAD + frame routing** (mic → STT frames → Jarvis orchestrator → filtered TTS frames → speaker). Conversation state stays Jarvis-owned.
2. **TTS/STT engines stay Jarvis:** Kokoro default butler (`butler_original_v1`), no silent SAPI, Chatterbox opt-in quality — RFC-0092 / 0070. Pipecat frames call existing `synthesize_with_engine` / STT helpers; they do not pick Windows SAPI as default or swallow neural failure.
3. Speak filter and reply-class (RFC-0075) still run before any audio frame is sent. Thought/plan chrome is never spoken.
4. Android / companion: reuse RFC-0064 WSS/WebRTC identity; Pipecat is an on-host pipeline option, not a second phone protocol.
5. Optional worker: missing Pipecat ⇒ existing clip STT/TTS and 0064 path remain. Jarvis stays orchestrator.

**Architect’s initial recommendation:** `partial`. Taco can override to `archive_only` if 0092/0075 must finish first with zero pipeline churn.

**Will not:** rewrite RFC-0092; change default voice profile; use OpenViking for voice; Gemini Live as required provider; Codsworth/actor clones; HexStrike.

## Acceptance criteria

Pipeline steps below are **spec’d**, not implemented.

- [x] Download — spec’d (`/workspace/projects/rfc/pipecat`; clones not committed)
- [x] Usefulness review — spec’d (3/5, `mas_integration`)
- [x] Integrate decision — spec’d (`partial`; Taco may override)
- [ ] Implement — later named ticket (not this PR)
- [ ] Optional Pipecat transport/VAD/turn-taking; Jarvis owns conversation + TTS/STT engines
- [ ] RFC-0092 **not** implemented or rewritten here (no SAPI default, no silent SAPI, no engine-catalog edits unless 0092 already landed separately)
- [ ] RFC-0075 speak filter still applies to spoken frames
- [ ] Specs-only in this PR
- [ ] Implement follow-up: `python3 -m pytest` (`tests/test_rfc0101_*.py`; do not weaken `tests/test_rfc0092_*.py` / 0075 tests)

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | new `backend/app/voice/pipecat_pipeline.py` (or similar); `backend/app/workers/voice.py` **hooks only**; `backend/app/api/voice.py`; companion realtime gateway — **no** `tts/synthesize.py` default/SAPI edits in this ticket |
| Frontend (implement PR only) | HUD listen/speak state only if RFC-0033 telemetry is wired; Settings Voice hosts toggle, not engine ranking |
| Tests | `tests/test_rfc0101_*.py` |
| Docs | this RFC; §59 batch line only |

## Out of scope

Product implementation in this PR. **RFC-0092** (do not rewrite). RFC-0075 engine/speak-filter redesign. OpenViking-as-TTS. Cloud TTS default. Persona merge. Offensive tools (LE-gated under RFC-0095).

## Notes

- Parent RFC-0095 reserved this number. Linux cloud cannot sign off live barge-in; unit-test frame routing + “0092 untouched” contracts; desktop listen is sign-off.
- Implement launch: this RFC only; branch from `development`; pytest; **do not edit RFC-0092 or TTS default/SAPI files unless that is a separately named 0092 ticket**; PR against `development`.
