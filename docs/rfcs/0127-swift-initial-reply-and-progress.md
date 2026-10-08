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

## Amendment 2026-10-08

**Author:** Jarvis Architect

**Product alignment:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) — owners should get confirmation when work is slow, not redundant chatter when the assistant already has an answer (**responsiveness of conventional software**).

### Decision 1 (amended)

Replace “swift ack before worker load” with **ack-only-when-late**, aligned with [RFC-0117](0117-tiny-front-chat-responder.md) Amendment 2026-10-08:

- `ack_continue` and `handoff_notice` are **held ~1.2 s** after turn start (configurable inference/front setting; default **1200 ms**). They are emitted (shown/spoken) **only if** no final answer and no first answer token has arrived by then; otherwise the held ack is dropped.
- Template/model fallbacks when the front chat provider is unavailable follow the **same hold-and-drop** rule for ack-class actions; `final_basic` remains immediate.
- Progress watchdog (Decision 2) is unchanged; it must not emit a second ack when `ack_emitted` is already set for the turn.

### Acceptance criteria (Wave 2 implement)

- [ ] Timing test: fast answer → no ack; slow answer → one ack at ~default 1.2 s.
- [ ] `final_basic` / terminal front path: immediate; not subject to ack hold.
- [ ] Shared per-turn `ack_emitted` across front lane and loop progress (no double ack with `owner_chat` ~L219–223 and `loop` ~L1992).
- [ ] `python3 -m pytest` green.

**Note:** Call-site implementation belongs to senior 4.7 dev Wave 2; spec-only here.
