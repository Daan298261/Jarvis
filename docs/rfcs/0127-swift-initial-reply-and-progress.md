# RFC-0127: Swift initial chat response and >60s progress feedback

**Status:** accepted  
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
