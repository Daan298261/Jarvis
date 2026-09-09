# RFC-0061: Always-on chat→TTS and universal personality

**Status:** accepted  
**Queue item:** P1 — Always-on TTS and portable personality  
**Author:** Jarvis Architect  
**Date:** 2026-09-09

## Problem

TTS today is effectively mic/voice-session oriented; typed chat replies are silent. Personality is inconsistent across models (per-model prompt hacks). Users want Jarvis to **speak every reply** (including typed chat) and keep one portable persona across backends.

## Decision

### 1. Always-on chat→TTS

After (or while streaming) an assistant reply in the main chat UI, synthesize speech via the existing/local TTS path and play it, even when the user typed (no mic required).

- User setting: `tts.speak_chat_replies` default **on** (with mute / push-to-mute and per-session quiet).
- Respect focus/DND/quiet hours from related persona policy where present.
- Typed send and voice send both enqueue TTS for assistant output.
- Streaming: prefer first-sentence / chunk TTS per RFC-0036 when available; else speak full reply on completion.
- Overlap: barge-in / stop-speaking on new user send.
- Failures: TTS error must not block showing text reply.

### 2. Universal personality pack

A portable **system/instructions layer** (persona pack) applied uniformly before model-specific formatting — not per-model ad-hoc strings. Pack includes: voice of character (register, humour, address style), hard behavioral constraints, and optional short few-shot tone examples. Loaded from a versioned local pack file / settings blob; same pack feeds chat, voice, and future butler commentary.

Applied as the first system/instructions segment for all chat models (local and remote). Model adapters may wrap but must not replace the pack.

#### Personality pack contract (sketch)

```json
{
  "id": "jarvis-default-v1",
  "locale": "en-GB",
  "system_prefix": "...",
  "traits": {"register": "british_understated", "humour": "dry", "address": "neutral"},
  "must": ["..."],
  "must_not": ["claim to be a copyrighted character", "..."],
  "tts": {"voice_profile_id": "...", "speak_chat_replies": true}
}
```

### Relation to other RFCs (do not re-implement)

| RFC | Ownership |
| --- | --- |
| RFC-0036 | Latency budgets / streaming talk-back timing — this RFC **consumes** those budgets for when TTS may start |
| RFC-0056 | Expressive butler voice runtime / voice identity — this RFC **uses** whatever TTS backend RFC-0056 selects |
| RFC-0055 | Social commentary interruption policy — chat→TTS for normal replies is separate; commentary still goes through 0055 gates |

This ticket = **chat→TTS path + persona pack portability** only.

## Acceptance criteria

- [ ] Setting `speak_chat_replies`; default on; mute works
- [ ] Typed chat replies produce audible TTS without enabling mic mode
- [ ] Persona pack loaded once and injected for ≥2 different model backends the same way
- [ ] Pack changes apply without per-model code edits
- [ ] Does not require RFC-0056 full engine; works with current TTS stub/backend
- [ ] Respects quiet/DND if already present; otherwise document hook
- [ ] Unit/integration tests for pack injection + TTS enqueue on chat completion
- [ ] Unit tests pass (`python3 -m pytest`); if portal touched, `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend | system-prompt / persona module, chat completion → TTS enqueue |
| Frontend | chat send path + mute control for `speak_chat_replies` |
| Tests | pack injection, TTS enqueue on chat completion |
| Config | versioned persona pack file / settings blob |

## Out of scope

Full RFC-0056 expressive butler; RFC-0033 device reliability rewrite; Astra Command Deck UI redesign; installer; social ambient commentary (RFC-0053–0055).

## Notes

RFC-0036 defines when streaming TTS may begin; RFC-0056 selects the voice runtime. This RFC wires typed chat through that stack and unifies persona injection across backends.
