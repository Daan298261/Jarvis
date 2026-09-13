# RFC-0082: Launch self-check with initializing nova

**Status:** implemented  
**Queue item:** Launch systems check + initializing presence  
**Author:** Taco request via Cursor  
**Date:** 2026-09-13

**Related:** RFC-0081 household voice; RFC-0050 presence / Apex orb.

## Problem

Jarvis can come up with a missing household voice, a still-loading model, or silent SAPI fallback and the portal just appears. Taco wants a launch self-check (“all systems in working order”) with a visually stunning initializing nova in the glowing orb language.

## Decision

1. On portal load, run a cheap `GET /api/systems/self-check` (core API, local inference, household voice, speech recognition).
2. Show a full-screen initializing overlay: pulsing nova / orbiting spark, **INITIALIZING**, then **ALL SYSTEMS IN WORKING ORDER**.
3. Do not block forever. Household voice still installing is `degraded`/`starting`, not a hard fail. Setup and guest routes skip the overlay.
4. End users never see pip. The check reports readiness only.

**Will not:** replace HUD presence; clone copyrighted splash screens; block chat if the model is still loading past a short wait.

## Acceptance criteria

- [x] Self-check endpoint returns structured checks and overall status
- [x] Portal shows initializing nova once per tab session, then dismisses
- [x] Success copy: ALL SYSTEMS IN WORKING ORDER
- [x] Unit tests; `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/systems/self_check.py`, `backend/app/api/system.py`, `backend/app/auth.py` |
| Frontend | `frontend/src/boot/BootNova.tsx`, `frontend/src/boot/bootNova.css`, `frontend/src/App.tsx` |
| Tests | `tests/test_systems_self_check.py` |

## Out of scope

Marvel splash clones; first-run Setup wizard rewrite; installer/NSIS changes.
