# RFC-0067: Owner chat hides plan/approval chrome; conversational launch greeting

**Status:** accepted  
**Queue item:** P0 — Owner HUD usable for talk  
**Author:** Jarvis Architect  
**Date:** 2026-09-10

## Problem

On the current HUD, owner chat surfaces agent internals — END STATE / ACCEPTANCE / PLAN panels and “Approval required” gates — so Jarvis feels like a ticket runner, not a conversational assistant. Taco reports it won’t talk and isn’t usable. Separately, launch should feel alive: a short conversational greeting (and spoken when TTS is on), not a blank plan chrome.

## Decision

Amend presence/chat UX (relates to RFC-0050 shell/presence; does not redesign Humanoid RFC-0051).

### 1. Hide agent reasoning / plan / approval chrome by default (owner chat)

For the **owner** main chat surface (Classic and Neural HUD; Humanoid if active):

- Do **not** show END STATE, ACCEPTANCE, PLAN, step traces, or “Approval required” chrome in the default conversation view.
- Default mode is **conversational**: user message → assistant reply (streaming text; TTS per RFC-0061 `tts.speak_chat_replies`).
- Irreversible / gated actions still use existing policy gates, but prompts appear as normal chat/confirm dialogs — not a persistent PLAN/ACCEPTANCE board blocking talk.
- Optional advanced/debug toggle (settings, default **off**): “Show agent plan & approvals” restores the chrome for power users.
- Guest portals / worker UIs may keep richer chrome if already specified; this RFC is **owner home chat** first.

### 2. Launch greeting

On app/session start for the owner (cold start or new local session):

- Jarvis sends a brief conversational greeting (e.g. hello / light “how was your day” — persona from RFC-0061 pack; keep short, not a status dump).
- If `tts.speak_chat_replies` is on (and not muted/DND), **speak** the greeting via the chat→TTS path.
- Do not open with PLAN/END STATE chrome. Do not require approval to greet.
- One greeting per session start; don’t re-greet on every HUD mode toggle.

## Acceptance criteria

- [ ] Owner chat default view has no END STATE / ACCEPTANCE / PLAN / persistent Approval-required board
- [ ] Owner can send a normal chat turn and get a spoken/text reply without clearing plan chrome first
- [ ] Settings toggle restores plan/approval chrome (default off)
- [ ] On launch, owner gets one short conversational greeting; TTS speaks it when `speak_chat_replies` is on and not muted
- [ ] Greet does not fire on mere Classic↔HUD toggle within the same session
- [ ] Unit/UI tests or smoke for default-hidden chrome + greeting once
- [ ] `python3 -m pytest`; `npm --prefix frontend run build` if portal touched

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | HUD/chat layout, message list, settings |
| Backend | Optional session-start greeting hook / system event |
| Persona/TTS | RFC-0061 pack + `speak_chat_replies` |

## Out of scope

New agent capabilities, new approval policy engine, Humanoid mesh redesign, installer, companion/Android, relay/Firebase.

## Notes

Taco 2026-09-10 via CoS: HUD unusable with plan/approval chrome; want hide-by-default + conversational launch greeting with TTS. Retroactive acceptance documents intent already agreed for implementation.
