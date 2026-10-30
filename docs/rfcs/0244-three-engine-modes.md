# RFC-0244: Three-position engine mode

**Status:** accepted
**Author:** Codex, requested by Daan
**Date:** 2026-10-30

## Problem

The owner wants one explicit choice between Model + JEV/Laya, Model only, and JEV/Laya only. Existing model selection and decision tier settings cannot express these choices together.

## Decision

Add a persisted engine mode with a three-position radio control in the model menu and classic settings. Hybrid preserves configured model/decision providers. Model only excludes JEV and Laya from decisions and warming. Reflex only excludes generative providers, front/worker model calls and model autoload; use structured decisions and bounded local replies, with a clear model-required response for unsupported free-form requests. Preserve provider credentials, privacy choices, saved model selection and all hard policy/approval checks. Switching mode does not download models, silently enable cloud access or claim VRAM was released. Mode applies at request entry; changing it does not forcibly unload resident weights.

## Acceptance criteria

- [ ] Three clearly named positions persist through settings reload and show save errors.
- [ ] Model only cannot call JEV/Laya; hybrid keeps current routing and provider availability checks.
- [ ] Reflex only cannot start/call front or worker generation, including startup and fallback paths.
- [ ] Reflex-only chat/task requests provide a bounded response and explain when a generative model is required, without claiming work happened.
- [ ] Mode changes do not remove credentials, promote another model or weaken hard permission checks.
- [ ] Backend regressions, frontend build/lint and browser interaction checks pass; installed behavior is reported separately.

## Scope

Engine-mode configuration/helper and settings API, Reflex provider selection/cache, Laya configuration, model/front runtime entrypoints, owner chat/agent ingress, startup warming, shared UI control, classic settings, focused tests. No architect-owned specifications, installer changes, model downloads or release promotion.
