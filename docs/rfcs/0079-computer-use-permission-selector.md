# RFC-0079: Computer-use permission selector

**Status:** implemented  
**Queue item:** ChatGPT-style computer-use permissions + node/RDP targeting  
**Author:** Taco request via Cursor  
**Date:** 2026-09-12  
**Owner for implement:** this PR

**Related (do not rewrite):** RFC-0002 reversibility; RFC-0031 approval provenance; RFC-0048/0078 HexStrike gateway; `SECURITY_AGENTS.md` §3.4.

## Problem

Computer use currently either runs or parks a generic “Approve delete” bar. There is no ChatGPT-style Allow once / Always / Don’t allow prompt, no fine-grained internet vs local-network vs cyber controls, and no explicit path for a phone request to land on this PC or a worker node (including RDP from the leader).

## Decision

1. **ChatGPT-style prompt** when a gated tool would run: Allow once, Allow this session, Always allow, Don’t allow. A **More** control expands the full catalog.
2. **Catalog** (persisted in `data/computer-permissions.json`):
   - `computer.this_device`, `computer.worker_nodes`, `computer.rdp`
   - `network.internet`, `network.local`
   - `cyber.hexstrike`
   - Blue: `blue.static_rules`, `blue.active_response`, `blue.isolate_device` (owned-LAN containment **plan/audit only**)
   - Red: `red.entry`, `red.exploration` — **permission flags only**. Default deny. Still require the Red Team password gate. No payloads, exploits, or hack-back.
3. **Targeting:** phone/companion work is planned against this device or a swarm node with `desktop_control`. If RDP is granted, the leader may launch the local RDP client (`mstsc /v:host`) to that node. Remote desktop **tools** still run on the node that owns the session; this RFC does not add a new remote-control protocol.
4. **Operator UI actions** (ModelSelector HexStrike start, Settings toggles) count as session grants when the mode is `ask`.

**Will not:** implement Red entry/exploration; proxy HexStrike command/payload APIs; deauth/kick arbitrary devices; edit Architect spec docs; build a full RDP stack.

## Acceptance criteria

- [x] Waiting tasks can present Allow once / Always / Don’t allow plus a More panel
- [x] Internet, local network, HexStrike, Blue, and Red flags are in the catalog
- [x] Red stays default-deny and gated; Blue isolate returns a containment playbook without executing kicks
- [x] Computer-use plan picks this device vs worker node and can sketch/launch RDP when permitted
- [x] Unit tests pass (`python3 -m pytest` for new coverage)
- [x] `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/policy/computer_permissions.py`, `backend/app/api/permissions.py`, `backend/app/api/computer_use.py`, `backend/app/workers/remote_desktop.py`, agent loop / authorize / tasks |
| Frontend | `frontend/src/chat/PermissionPrompt.tsx`, HUD/classic chat, Settings, Phone |
| Tests | `tests/test_computer_permissions.py` |
| Docs | this RFC |

## Out of scope

Worker-to-worker remote UI Automation RPC; LE Red tooling; HexStrike MCP for ordinary agents; Architect spec edits.
