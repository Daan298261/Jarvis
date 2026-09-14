# RFC-0090: Optional worker Install now

**Status:** accepted  
**Queue item:** Tools page optional workers stay `missing` with no install action  
**Author:** Taco via Cursor  
**Date:** 2026-09-14

## Problem

The Tools page lists Browser Use, Microsoft UFO, Cua, Open Interpreter, and OpenHands as `missing`. Adapters are integrated, but the owner has to leave the portal and run undocumented pip/git commands. Native fallbacks keep Jarvis running; they do not install the optional worker.

## Decision

1. Each missing optional worker shows an **Install now** button on Tools (and System backends).
2. Clicking it installs that worker into the **same Python** Jarvis is running, using a hardcoded allowlist (no owner-supplied package names or shell).
3. Install runs in the background. The catalog polls until `ready` or `error`. Jarvis stays the orchestrator; Playwright / native desktop / filesystem remain defaults.
4. Package sources:
   - Browser Use: `browser-use[core]`, fallback `browser-use`
   - Open Interpreter: `open-interpreter`
   - OpenHands: `openhands`, fallback `openhands-ai`
   - Cua: `cua`, fallbacks `cua-computer`+`cua-agent`, then `cua-cli`
   - Microsoft UFO: shallow clone of `https://github.com/microsoft/UFO.git` plus `requirements.txt` (not a PyPI package)

**Will not:** make these workers the primary app; accept arbitrary pip specs; run `curl | sh`; install Cursor paid coding workers (those stay not-configured).

## Acceptance criteria

- [ ] Missing optional workers show **Install now**; ready workers do not
- [ ] POST `/api/tools/optional-workers/{id}/install` only accepts the five allowlisted ids
- [ ] Catalog overlay reports `installable` / `installing` / `install_error`
- [ ] Unit tests pass (`python -m pytest`)
- [ ] `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/workers/install.py`, `backend/app/tools/capabilities.py`, `backend/app/api/tools.py` |
| Frontend | `frontend/src/components/OptionalWorkerRow.tsx`, `frontend/src/pages/Tools.tsx`, `frontend/src/pages/System.tsx` |
| Tests | `tests/test_optional_worker_install.py` |
| Docs | this RFC |

## Out of scope

Cursor Composer/Grok paid workers; first-run setup components; Architect spec edits.

## Notes

Pip/git installs need the desktop network. Cloud VMs can unit-test the allowlist and UI wiring; live package install is Windows sign-off.
