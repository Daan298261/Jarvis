# RFC-0244: Engine modes and current-node model dropdown

**Status:** accepted
**Author:** Codex, requested by Daan
**Date:** 2026-10-30

## Problem

The owner wants one explicit choice between Model + JEV/Laya, Model only, and JEV/Laya only. Existing model selection and decision tier settings cannot express these choices together.

## Decision

Add a persisted engine mode with a three-position radio control in the model menu and classic settings. Hybrid preserves configured model/decision providers. Model only excludes JEV and Laya from decisions and warming. Reflex only excludes generative providers, front/worker model calls and model autoload; use structured decisions and bounded local replies, with a clear model-required response for unsupported free-form requests. Preserve provider credentials, privacy choices, saved model selection and all hard policy/approval checks. Switching mode does not download models, silently enable cloud access or claim VRAM was released. Mode applies at request entry; changing it does not forcibly unload resident weights.

Owner follow-up: remove all six pinnable slots and their assignment/reordering UI. Replace them with one model dropdown for the node serving this portal and explicit loading/status. Keep the engine-mode control. A More view lists verified resident models (including ANZU front/worker seats), exposed model servers and recognized AI applications/process groups on this node. Installed/advertised weights and AI client processes are never labelled as resident models. Inventory is read-only, bounded and off the event loop; it never reads command lines, credentials or browser tabs, starts models or stops other programs. Unsupported or inaccessible instances are reported as incomplete detection rather than claimed absent.

## Acceptance criteria

Owner-turn decisions use the caller's settings snapshot inside the 50 ms window, without reloading configuration. Legacy settings-less decisions retain deterministic rules only because no engine selection can be established; typed-provider fixtures must supply their enabled settings snapshot.

- [ ] Three clearly named positions persist through settings reload and show save errors.
- [ ] Six-slot/pin/reorder controls and shortcuts are gone; a current-node dropdown replaces them without silently activating models on selection.
- [ ] More shows this node's running models, model servers and recognized AI app instances, with provenance/verification and useful PID/port/status information.
- [ ] Inventory includes ANZU-owned front/worker seats, preserves multiple resident instances and distinguishes downloaded/advertised models from loaded ones.
- [ ] Refresh/read errors and partial process visibility are explicit; no discovered app is stopped or taken over by viewing inventory.
- [ ] Model only cannot call JEV/Laya; hybrid keeps current routing and provider availability checks.
- [ ] Reflex only cannot start/call front or worker generation, including startup and fallback paths.
- [ ] Reflex-only chat/task requests provide a bounded response and explain when a generative model is required, without claiming work happened.
- [ ] Mode changes do not remove credentials, promote another model or weaken hard permission checks.
- [ ] Backend regressions, frontend build/lint and browser interaction checks pass; installed behavior is reported separately.

## Scope

Engine-mode configuration/helper and settings API, Reflex provider selection/cache and owner-turn settings snapshot, Laya configuration, model/front runtime entrypoints, owner chat/agent ingress, startup warming, shared UI control, classic settings, node AI inventory/API, model dropdown and focused tests. No architect-owned specifications, installer changes, model downloads or release promotion.
