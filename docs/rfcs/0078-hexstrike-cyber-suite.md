# RFC-0078: HexStrike AI cybersecurity suite

**Status:** implemented  
**Queue item:** HexStrike cybersecurity suite (HUD model selector)  
**Author:** Taco request via Cursor  
**Date:** 2026-09-12  
**Owner for implement:** this PR

**Related (do not rewrite):** RFC-0048 HexStrike gateway boundary; RFC-0069 presence shape catalog; RFC-0073 HUD model hotswap; `SECURITY_AGENTS.md` §3.4.

## Problem

Taco wants HexStrike AI as a first-class **cybersecurity suite** in Jarvis: pick it in the HUD ModelSelector like a model, start the HexStrike application in the background, and operate it through the Jarvis HUD. RFC-0048 specified a Jarvis-controlled gateway but did not ship a suite profile, process supervisor, or HUD surface. HexStrike’s upstream project is an MCP + loopback API (default `:8888`); it does not ship a first-class web UI on mainline.

## Decision

Treat HexStrike as a **suite runtime profile** (`hexstrike-suite`), not an LLM:

1. **ModelSelector** — a dedicated HexStrike AI row (also pinnable). Selecting it activates the suite without calling `MANAGER.load` / swapping GGUF.
2. **Background process** — Jarvis starts `hexstrike_server.py` on loopback (`127.0.0.1`, default port 8888) when the operator selects the suite, if an install is configured. Switching to an inference profile stops it. Missing install still opens the suite HUD (status + path setup).
3. **Jarvis HUD console** — HexStrike is shown **through Jarvis**, not as a raw WAN-exposed server. A hexagonal suite overlay presents live health, tool availability, telemetry, and process dashboard from the gateway. Presence morphs to a new shape, `hex_aegis`.
4. **Gateway (RFC-0048)** — same-origin `/api/hexstrike` only. Allowlisted read/monitor paths. **No** proxy of raw `/api/command`, Python exec, file-write, payload, or exploit endpoints. Ordinary agents do **not** receive HexStrike MCP tools.
5. **Routing** — suite profiles are ignored by inference `route_runtime` / `force_profile`.

**Will not:** vendor HexStrike source; auto-download tools; add payload generation, hack-back, or Red LE plumbing; edit Architect spec docs; expose HexStrike on a WAN listener.

## Acceptance criteria

- [x] Default runtime profile `hexstrike-suite` appears in HUD ModelSelector
- [x] Selecting it starts (or attempts) HexStrike on loopback and opens the suite HUD
- [x] Presence morphs to registered shape `hex_aegis`
- [x] Gateway allowlist refuses command/python/payload/exploit paths
- [x] Inference router never selects the suite as an LLM
- [x] Unit tests pass (`python3 -m pytest`) for HexStrike/runtime coverage
- [x] `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/security/hexstrike.py`, `backend/app/api/hexstrike.py`, `backend/app/config.py`, `backend/app/inference/{model_stack,hotswap,runtime_profiles,runtime_router}.py`, `backend/app/main.py` |
| Frontend | `frontend/src/hud/HudHexStrikeSuite.tsx`, `HudModelSelector.tsx`, `HudChatHome.tsx`, `hexstrike.css`, `frontend/src/presence/renderers/shapes/hexAegis.ts` |
| Tests | `tests/test_hexstrike_suite.py` |
| Docs | this RFC |

## Out of scope

HexStrike MCP registration for ordinary agents; Red/LE offensive modules; installer bundling of 150+ pentest binaries; cloning `0x4m4/hexstrike-ai` into this repo.

## Notes

Upstream: https://github.com/0x4m4/hexstrike-ai — start with `python hexstrike_server.py --port 8888`. Desktop sign-off: live HexStrike install + HUD embed on Windows.
