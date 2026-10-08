# RFC-0131: Context-size model autoselect

**Status:** implemented

Autoselect larger runtime profile when prompt exceeds cap; front-lane keep-busy during hotswap; runtime_role/source_model on model-lane events.

## Implementation note

Landed on `development` via #337 @ `d4eceef9` (context-size model autoselect).

## Amendment 2026-10-08

**Author:** Jarvis Architect

**Product alignment:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) — owners should not see mid-task stalls or silent failures from infrastructure; context changes must preserve **trustworthy, polished** behaviour during long turns.

### Turn-boundary context reload only

**Model context reload/resize** (unload + reload of the LM Studio / llama runtime with a new context length) may run **only at turn boundaries**: immediately before the turn’s first model call, or after the turn completes. It must **never** run inside the step loop, immediately before an individual chat completion mid-turn, or during overflow recovery mid-turn.

**Mid-turn**, fitting the prompt uses **compaction/trim only** (summarize, drop sections, trim) against the **currently loaded** context size.

### In-flight lease

No reload while **any** inference request for the active turn is in flight. A resize requested during a turn is **deferred** to the next turn boundary (queue + apply at boundary).

### Failed reload

A failed reload must **fail visibly** to the owner/operator and **restore the original load settings** (the profile/settings in effect before the resize attempt — not a hard-coded `--gpu max` or other implicit default). Never leave the app believing a model is loaded when it is not.

### Implementing work

Open PR **#549** ([RFC-0202](0202-context-scaling.md) context scaling) must conform to this amendment; do not edit RFC-0202 in this tick.

### Acceptance criteria (Wave 2 implement)

- [ ] Reload attempted mid-turn is deferred to next boundary (no unload during step loop).
- [ ] In-flight lease: resize blocked while a request is active; applied at boundary when safe.
- [ ] Failed reload surfaces error and restores pre-attempt load settings.
- [ ] `python3 -m pytest` green.
