# RFC-0130: Session personality prompt addenda + extra modes

**Status:** implemented  
**Author:** Cursor cloud worker  
**Date:** 2026-09-19  
**Depends on:** PR #334 / [RFC-0126](0126-personality-session-modes.md)

## Problem

PR #334 shipped core/coding session modes with HUD accents, but did not inject a system-prompt addendum into the persona pack / front responder, and lacked research/concise modes plus a settings selector.

## Decision

Extend the existing `/api/session-personality` surface (do not replace it):

1. Add `system_prefix_addendum` on each `SessionMode`.
2. Add `research` and `concise` modes; accept `default` as an alias for `core`.
3. Inject addendum via `build_persona_instructions` and `front_system_prompt()`.
4. Appearance settings selector for explicit mode pick.
5. Light HUD accents for research/concise.

## Acceptance criteria

- [x] Prompt paths include session addendum
- [x] research/concise selectable + phrase detection
- [x] Settings selector wired to existing API
- [x] `python3 -m pytest tests/test_session_personality.py`
- [x] Frontend build when UI touched

## Notes

HUD theming remains partial (CSS accents + top-bar label). Full Daybreak/presence reskin and automatic TTS voice swap stay out of scope. Parallel branch `cursor/rfc0130-session-personalities-34ee` is superseded by this enhancement on top of #334. Presence shape and voice binding is [RFC-0137](0137-persona-presence-shape-and-voice-binding.md). This RFC's status is unchanged.
