# RFC-0127: Swift initial chat response and >60s progress feedback

**Status:** implemented  
**Queue item:** Owner silence on simple queries; immediate front ack + slow-worker progress  
**Author:** Cursor cloud worker  
**Date:** 2026-09-19

**Related:** [RFC-0117](0117-tiny-front-chat-responder.md), [RFC-0068](0068-think-aloud-status.md).

## Problem

Simple owner turns can sit silent for minutes while the worker model loads or tools run. The owner needs immediate confirmation and, after about a minute, an explanation that work is still underway.

## Decision

1. Swift `ack_continue` from `front_responder` before worker model load (conversation path) and template/model fallbacks when the front chat provider is unavailable.
2. Progress watchdog at 60s (repeat ~50s cooldown) using `front_responder` progress generation, think-aloud templates, and BUS stage context.
3. Wire through `loop.py`, `front_responder.py`, `worker_progress.py`, `think_aloud.py`.

## Acceptance criteria

- [ ] Swift ack before worker load on conversation turns
- [ ] Managed path front/template ack when model missing
- [ ] 60s progress with cooldown
- [ ] `tests/test_rfc0127_swift_reply_progress.py`
- [ ] `python3 -m pytest` passes

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/agent/front_responder.py`, `loop.py`, `worker_progress.py`, `backend/app/persona/think_aloud.py` |
| Tests | `tests/test_rfc0127_swift_reply_progress.py` |

## Out of scope

Spec doc edits, portal UI, live GPU sign-off.

## Implementation note

Landed on `development` via #338 @ `13d9aa0b` (swift front ack and 60s worker progress), #354 @ `19a2e4a7` (progress watchdog and duplicate front TTS), #355 @ `e87af8eb` (managed follow-up swift lane), and #375 @ `06cbf5b7` (swift-ack contract tests). Live GPU/TTS remains desktop sign-off. Acceptance checkboxes left open for that sign-off.
