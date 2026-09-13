# RFC-0083: Conversation follow-ups stay conversational; hide model reasoning

**Status:** implemented  
**Queue item:** Owner chat must not dump thinking or hit the step limit  
**Author:** Taco report via Cursor  
**Date:** 2026-09-13

## Problem

A follow-up on an owner chat thread (HUD “Follow up…”, including a simple question) skips `_run_conversation` and enters the 28-step tool loop. The model then:

1. Publishes hidden chain-of-thought as **Reasoning complete** events
2. Gets forced to “execute the plan with tools”
3. Loops until **Step limit reached before verification**
4. Never speaks a normal reply

PR #130 (installer connections) does not address this.

## Decision

1. Conversation-class tasks stay on the no-tools chat path for follow-ups, unless the new message clearly asks for a tool task (install, files, pytest, …).
2. Do not publish `result.reasoning` onto the owner event bus.
3. Owner “Show work” still hides thinking-heartbeat titles.

**Will not:** add red-team / evasion help; change HexStrike; rewrite classify_task for first turns.

## Acceptance criteria

- [x] Follow-up on a conversation task completes via `_run_conversation` (no step-limit failure)
- [x] Agent loop does not bus-publish hidden reasoning text
- [x] Unit tests; frontend build if TS changed

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/agent/loop.py`, `backend/app/agent/planning.py` |
| Frontend | `frontend/src/chat/ownerChatView.ts` |
| Tests | `tests/test_owner_chat_greeting.py`, `tests/test_planning.py` |

## Out of scope

Marvel voice; installer; offensive / LE-evasion tooling.
