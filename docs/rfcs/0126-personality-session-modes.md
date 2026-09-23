# RFC-0126: Selectable personality session modes

**Status:** implemented  
**Author:** Cursor cloud agent (Taco goal follow-up)  
**Date:** 2026-09-19

## Problem

The owner wants Jarvis (Anzu core) to switch into focused personalities (for example a coding session) with matching HUD chrome, without merging third-party persona packs (RFC-0104).

## Decision

Introduce **session modes** — small, first-party profiles selected explicitly or by natural-language intent. Modes adjust dialogue preset hints and portal `data-session-mode` styling; they do not replace the Leader loop or load external persona trees.

| Mode | Trigger examples | HUD / UX |
| --- | --- | --- |
| `core` | default, "back to general" | standard orange/black HUD |
| `coding` | "start a coding session", "let's code" | cool accent, coding badge |

Modes are stored in process memory with optional persistence later; v1 exposes REST read/write and detection hook on owner chat ingress.

## Acceptance criteria

- [ ] Modes documented in this RFC
- [ ] API lists and sets active session mode
- [ ] Natural-language detection switches coding mode
- [ ] HUD applies theme class for coding mode
- [ ] `python3 -m pytest tests/test_session_personality.py`

## Out of scope

RFC-0104 persona_candidate merges; voice pack retraining; full module catalog entries.

## Implementation note

Landed on `development` via #334 @ `8344b806` (personality session modes v1). Prior status was `accepted (implement v1 in PR)`. Acceptance checkboxes left as written.

## Notes

[RFC-0137](0137-persona-presence-shape-and-voice-binding.md) is a separate named-persona catalog (13-persona ANZU roster, amended in place). It does not bind these session modes. This RFC's status is unchanged.
