# RFC-0065: Companion PC endpoint bring-up (cloud/dev)

**Status:** implemented  
**Queue item:** P1 — Android companion / RFC-0064 verification prerequisite  
**Author:** Cursor cloud (continuation of Astra Android companion run)  
**Date:** 2026-09-10

## Problem

RFC-0064 realtime voice and the Android companion talk to the Windows/PC Jarvis
Leader over the local HTTP API (`:4780`) and the restricted mobile TLS gateway
(`:4781`). In cloud/dev VMs the PC endpoint is often down, so companion and
realtime-voice checks fail for infrastructure reasons rather than product bugs.

## Decision

Before companion/realtime verification:

1. Probe `http://127.0.0.1:4780/api/system` (and companion routes when auth allows).
2. If down, start the backend with `JARVIS_SKIP_MODEL=1` (no GPU model load on cloud).
3. If the portal SPA is missing, run `npm --prefix frontend run build` so `:4780`
   serves the built UI.
4. Optionally start `python -m app.mobile.gateway` on `:4781` when TLS ingress is
   needed for mobile-path checks.

Do **not** require a live 27B GGUF, Windows desktop tools, or public relay deploy
in this ticket.

## Acceptance criteria

- [x] `GET /api/system` returns HTTP 200 on `127.0.0.1:4780`.
- [x] Backend process stays up for the verification window.
- [x] If SPA assets were missing, frontend production build completes successfully.
- [x] Internal reference note documents the bring-up commands for docs-first grounding.
- [x] Unit/focused companion tests still pass with the endpoint available.

## Likely files

| Area | Paths |
| --- | --- |
| Docs (RFC) | `docs/rfcs/0065-companion-pc-endpoint-bringup.md` |
| Internal refs | `project/jarvis/jarvis/internal/references/companion-pc-endpoint.md` |
| Ops | uvicorn / `frontend` build only — no product code required unless start fails |

## Out of scope

Physical-phone pairing, FCM/TURN public infra, editing architect specs, merging #132/#146.

## Notes

Cloud VMs cannot sign off live model load. `JARVIS_SKIP_MODEL=1` is required here.
