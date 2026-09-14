# RFC-0091: Auto-start local LM Studio + chat-bubble follow-ups

**Status:** accepted  
**Queue item:** Runtime Play fails if LM Studio is closed; HUD follow-ups rewrite the original prompt  
**Author:** Taco via Cursor  
**Date:** 2026-09-14

## Problem

1. Choosing an LM Studio runtime while the app/server is closed shows *Could not reach lmstudio at 127.0.0.1:1234. Start the server and load a model…*. The owner should not have to do that by hand on this PC.
2. A typed follow-up is appended onto `task.prompt` as `Follow-up: …` and the transcript shows that whole blob as the first “You” bubble. Later messages should appear at the bottom, like a normal chat.

## Decision

1. When a **loopback** LM Studio probe fails, Jarvis starts LM Studio (app + `lms server start`) and loads the requested model, then re-probes. Remote/LAN endpoints are not auto-started. If start still fails, keep the existing error.
2. Keep concatenating `Follow-up:` onto `task.prompt` for the agent if needed. Expose clean user/assistant **turns** from `conversation_json`. The HUD/classic transcript renders those as bubbles; the composer placeholder is a normal message field.

## Acceptance criteria

- [ ] Unreachable local LM Studio triggers auto-start before the Play/runtime error
- [ ] Auto-start is not attempted for non-loopback hosts
- [ ] Follow-up text is a new user bubble, not mixed into the original prompt on screen
- [ ] Unit tests; `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/lmstudio_server.py`, `backend/app/inference/hotswap.py`, `backend/app/agent/loop.py`, `backend/app/api/tasks.py` |
| Frontend | `frontend/src/chat/ownerChatView.ts`, `OwnerChatTranscript.tsx`, `HudChat.tsx`, `Chat.tsx` |
| Tests | `tests/test_runtime_activate.py`, `tests/test_owner_chat_greeting.py`, `tests/test_chat_turns.py` |

## Out of scope

Remote LM Studio; Architect spec edits; paid Cursor workers.
