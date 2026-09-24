# RFC-0172: P0 Reflex-first browser/computer-use fast loop

**Status:** accepted — P0  
**Date:** 2026-09-24  
**Depends on:** RFC-0171 (hard). RFC-0145 and RFC-0151 exist on main @ `ac18fb32` but are **not yet ported** to development — soft until a later parity port. Implement may ship a minimal in-ticket `ActionFrame` / sandbox posture if those RFCs are absent; do not block on a full 0145/0151 land.

## Problem

General computer-use agents are slow when every click requires screenshot → large multimodal model → prose/reasoning → parse → click. Current Jev projects demonstrate a faster architecture by exposing a bounded action space and reserving generation for the minority of steps that require text.

## Decision

Implement a fast semantic action loop shared by browser and desktop accessibility control. Observation adapters produce an atomic `ActionFrame` with frame ID, app/page identity, timestamp, actionable nodes, role/name/value/state, geometry/visibility and supported operations. The Reflex Lane chooses `operation + target_id + done/block state` in one typed decision. Executor accepts only target IDs from the current frame, resolves to the original node, verifies frame freshness/focus/occlusion, performs the action and verifies a postcondition.

For browser tasks prefer DOM/accessibility/CDP identity; desktop prefers native accessibility/UI Automation. Vision/OCR augments missing semantics rather than replacing them by default. TYPE_TEXT invokes the smallest qualified text generator and validates the returned bounded string before typing. Repeated macros may be replayed only when frame predicates match and are verified after each mutating step.

## Acceptance criteria

- [ ] Atomic `ActionFrame` schema for browser and desktop.
- [ ] One typed decision chooses operation + target when possible.
- [ ] No model-generated selector/coordinate/JS/shell execution in fast path.
- [ ] Stale frames and changed targets are rejected before execution.
- [ ] TYPE_TEXT is the only default path that invokes text generation for ordinary form navigation.
- [ ] Postcondition verification after mutating actions.
- [ ] Deterministic benchmark compares Reflex loop to current Anzu computer/browser loop on identical tasks.
- [ ] Metrics include model calls, protocol/native calls, wall time, success and recovery count.
- [ ] Safety/approval rules remain outside the decision model.

## Likely files

Browser runtime, computer-use runtime, accessibility/DOM snapshot adapters, Reflex Lane, benchmark fixtures, Control Room.
