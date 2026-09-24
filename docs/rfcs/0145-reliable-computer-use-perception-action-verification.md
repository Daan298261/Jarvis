# RFC-0145: Reliable computer use — perceive, act, verify, recover

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Desktop control parity requires more than click/type tools. Anzu must survive changed layouts, stale screenshots, focus errors and partial actions without blindly continuing.

## Decision
Create a Computer Use runtime with a closed loop: perceive → ground → propose action → policy/approval → execute → verify expected postcondition → recover/replan. Prefer semantic/native accessibility and application APIs; vision coordinates are fallback. Every action carries target app/window, expected state, timeout, reversibility and risk. Destructive/external actions retain existing approval gates. Add focus ownership, stale-frame detection, DPI/multi-monitor normalization, clipboard isolation and bounded retries.

## Acceptance criteria
- [ ] Native/accessibility/API targeting precedes coordinate clicks where available.
- [ ] Every mutating action has a postcondition check.
- [ ] Focus/window/frame identity is verified before input.
- [ ] Recovery handles moved controls, dialogs and stale frames without infinite loops.
- [ ] Multi-monitor/DPI tests and deterministic fake-desktop tests exist.
- [ ] UI shows current perception, proposed action, approval and verification result.

## Likely files
Computer-use tools, policy/approval layer, vision adapters, Control Room, tests.
