# RFC-0163: Accessibility, localization and alternative input

**Status:** accepted  
**Date:** 2026-09-24

## Problem
A daily assistant should not require precise pointer use, English-only UI or visual interpretation of glowing HUD state.

## Decision
Make accessibility a release-gated product capability. All controls get keyboard navigation, semantic labels, focus states and screen-reader announcements. HUD/orbs have equivalent textual state. Support scalable text/reduced motion/high contrast and captions/transcripts. Externalize UI strings and locale formatting. Voice language and UI language are independent. Add push-to-talk and keyboard-only paths for every essential flow.

## Acceptance criteria
- [ ] Core setup/chat/approval/persona/modules/goals usable keyboard-only.
- [ ] Screen-reader semantic checks and automated accessibility tests.
- [ ] Reduced-motion mode disables nonessential particle animation.
- [ ] Captions available for voice output/input state.
- [ ] Locale framework supports translation without code changes.

## Likely files
Frontend design system/HUD, voice UI, setup, test automation.
