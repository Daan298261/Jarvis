# RFC-0075: Natural speak path + latency + thought-process chevron

**Status:** accepted
**Author:** Jarvis Architect
**Date:** 2026-09-11
**Owner for implement:** D1 (speak filter / TTS enqueue) + UX (chevron) after this specs-only land

**Related (do not rewrite):** RFC-0070 TTS engines + speak filter; RFC-0036 streaming talk-back / latency budgets; RFC-0049 conversational onboarding; RFC-0061 always-on chat→TTS; RFC-0068 spoken think-aloud / speak filter; RFC-0067 hide plan chrome / greeting.

## Problem

Default voice still feels robotic to the owner on 1.2.5. Simple social queries (weather) wait ~10s for the full tool+model turn before any speech. TTS reads markdown and dev/tool errors aloud (`**18**`, fences, stack traces). Thought / plan / process is still visible or not chevron-collapsed by default, despite RFC-0067 hide-chrome intent and the existing “Show work” control on `OwnerChatTranscript`.

RFC-0070 owns **which engine** speaks (Kokoro default). This RFC owns **what** is spoken and **when**, plus default-collapsed thought chrome.

## Decision

Classify the assistant turn before enqueueing TTS. Social replies become natural prose and start as soon as a stable sentence is ready. Technical replies stay denser but still pass the speak filter. Owner chat shows the final reply only; thought/process sits behind a collapsed chevron.

### 1. Reply class before speak

Before the host TTS path (`backend/app/persona/chat_delivery.py` → `filter_text_for_speech`) speaks a chat reply, classify the assistant output as **social / conversational** vs **technical**.

| Class | Heuristics (first cut; optional tiny classifier later) | Speak behavior |
| --- | --- | --- |
| **Social** | Short weather / time / chit-chat / greeting; no code fences; no stack traces; little or no tool-dump structure | Strip markdown, code fences, URLs, stack traces, “Final reply:”, PLAN dumps; rewrite numbers/units for speech (“eighteen degrees”, “three o’clock” / “fifteen hundred hours”); never speak asterisks or raw markup |
| **Technical** | Code, diffs, traces, API errors, long tool output, PLAN-shaped boards | May keep denser wording; still apply RFC-0070 speak-filter — no thought-process, no raw fences, no URLs, no stack traces aloud |

Heuristics must be unit-testable (keyword / shape / length / fence / traceback). A tiny on-device classifier is optional and must not block the speak path if absent.

**Social weather example (must not be read as markup):**

- Bad (spoken): “asterisk asterisk 18 asterisk asterisk to 11 degrees”
- Good (spoken): “eighteen to eleven degrees…”

### 2. Technical path still filtered

Technical replies may keep denser wording (file names, short identifiers) but **must** still run `filter_text_for_speech` (RFC-0070 / RFC-0061 / RFC-0068): no thought-process, no raw fences, no URLs, no tool/dev error dumps aloud. Extend the filter so leftover `**`, `#` headings, and list markers are not vocalized on either path.

### 3. Latency — start speech before full completion

For short **social** answers, start TTS on the first stable sentence / chunk (RFC-0036 streaming talk-back). Do **not** wait for full tool+model completion when a speakable social sentence is already ready.

- First-chunk / ack budgets remain RFC-0036 (ack ≲ 700 ms on the reference desktop for ordinary short commands).
- Long jobs: one brief persona ack / think-aloud (RFC-0068), then speak the social sentence when it lands — not after the entire turn.
- Never claim success before verification (RFC-0036). If the first sentence would be false or incomplete (“it’s 18 degrees” before the tool returns), wait or speak a non-committal ack instead.
- This RFC does not change AUTO model routing or swap TTS engines.

### 4. Default voice quality (not this RFC’s engine work)

Keep Kokoro (or the better active RFC-0070 profile) as the everyday default. This RFC does not add engines, retrain voices, or change `voice_profile_id` ranking.

### 5. Thought-process chrome — collapsed chevron

Owner chat default = **final reply only**. Thought / plan / process / tool steps live behind a **collapsed chevron** (“Show work” / equivalent). Expanding reveals details; collapsing is the default and the default preference (`jarvis.chat.showWork` already defaults off — reinforce if any surface still opens work or renders thought inline).

- Applies to Classic chat, Neural HUD (`HudChat` / `OwnerChatTranscript`), and any owner transcript that still inlines process.
- Chevron, not a persistent PLAN/ACCEPTANCE board (RFC-0067).
- TTS never narrates the expanded work panel (RFC-0070 speak filter).

### Will not

- Retrain TTS models or add engines (RFC-0070)
- Change AUTO model routing (RFC-0003)
- Show thought process by default
- Rewrite RFC-0067 / 0068 contracts except to reinforce collapsed chrome and the speak filter

## Acceptance criteria

- [ ] Social vs technical speak path documented and testable (heuristics and/or classifier hook)
- [ ] Social TTS never speaks `**`, fences, URLs, or raw tool/dev errors
- [ ] Weather-like example speaks natural prose (“eighteen to eleven degrees”), not markup
- [ ] Short social replies begin speech before full turn completion when semantically safe (RFC-0036 budgets)
- [ ] Thought / process UI default collapsed behind a chevron on owner chat (Classic + HUD)
- [ ] Specs-only in this PR (no product code)
- [ ] Implement follow-up: `python3 -m pytest` (speak-filter + class + latency hooks); `npm --prefix frontend run build` if transcript UI changes

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/tts/speak_filter.py`, `backend/app/persona/chat_delivery.py`, TTS enqueue / chunking (RFC-0036), optional class helper next to speak-filter |
| Frontend | `frontend/src/chat/OwnerChatTranscript.tsx`, `frontend/src/chat/ownerChatView.ts`, `frontend/src/hud/HudChat.tsx` / `HudChatHome.tsx` |
| Persona | RFC-0061 pack hooks only — no pack rewrite |
| Tests | `tests/test_rfc0070_tts.py`, new speak-class / social-rewrite tests, owner-chat chevron default |
| Docs | this RFC; optional Architect §59 line |

## Out of scope

Product implementation in this PR. New TTS engines (RFC-0070). AUTO routing. Companion/Android transport. Showing work by default. Retraining voices.

## Notes

Taco 1.2.5 desktop test via CoS → Jarvis Architect (specs-only). Robotic default, ~10s wait on simple weather, markdown/dev errors spoken, thought process still visible.

RFC-0070 remains the engine/ranking/speak-filter contract; this RFC tightens **what** and **when**. RFC-0067 chrome stays hide-by-default; the chevron is the owner disclosure control.

Linux cloud VMs cannot sign off live Kokoro quality or first-chunk latency; desktop listen remains owner sign-off.
