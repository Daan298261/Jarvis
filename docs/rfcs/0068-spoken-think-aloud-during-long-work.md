# RFC-0068: Spoken think-aloud during long work

**Status:** accepted  
**Author:** Jarvis Architect  
**Date:** 2026-09-10

**Related:** RFC-0067 (owner chat chrome/greeting), RFC-0036 (streaming talk-back), RFC-0061 (TTS / `speak_chat_replies`)

## Problem

When Jarvis takes a while to think or run tools, the owner hears silence (or only sees plan chrome). Taco wants brief spoken commentary during long work — persona and humor — not PLAN dumps or status boards.

## Decision

When a turn or tool run exceeds a short threshold (~2–3s before first useful output, or during a sustained long job), Jarvis **may** speak **one** brief persona-flavored status line (e.g. “this one’s a bit involved”, dry “on a Monday morning, come on now”). Tone follows the original butler pack (RFC-0061); lines are generated in character, not fixed scripts. Do **not** read END STATE, ACCEPTANCE, PLAN, or step traces aloud.

**Rules**

- Only when `tts.speak_chat_replies` is on and the owner is not muted / DND.
- Optional matching short chat text (same line); no plan chrome.
- Rate-limit: at most **one** think-aloud per long job, plus a cooldown before the next.
- No approval required for these lines.
- Complements RFC-0036 streaming talk-back; does **not** change latency budgets or replace first-reply TTS.

**Will not:** rewrite RFC-0067 chrome behavior; add new approval types; build companion-specific voice.

## Acceptance criteria

- [ ] Long jobs can emit one rate-limited spoken think-aloud without plan chrome
- [ ] Suppressed when TTS muted/DND or `speak_chat_replies` off
- [ ] Unit/smoke for threshold + rate-limit
- [ ] `python3 -m pytest`

## Likely files

| Area | Paths |
| --- | --- |
| Backend | Turn/tool timing hook, think-aloud trigger + rate limit |
| Persona/TTS | RFC-0061 pack, chat→TTS path (RFC-0036 timing) |
| Tests | `tests/test_....py` (threshold, cooldown, mute gates) |

## Out of scope

Rewriting RFC-0067; approval engine changes; companion/Android realtime voice.

## Notes

Taco 2026-09-10; pairs with #154 / RFC-0067. Implementation ticket follows accepted RFC.
