# RFC-0086: In-person cyber ATO license (LE + validity)

**Status:** implemented  
**Queue item:** LE authorization artifact for Blue/Red runtime  
**Author:** Taco (in-person verification) via Cursor  
**Date:** 2026-09-14

## Problem

`SECURITY_AGENTS.md` §3.2 requires an authorization artifact Taco provides before Red runtime is allowed. Today only a password gate exists. That is not in-person verification, has no law-enforcement flag, and has no ATO expiry/renewal. Blue/Red specialist routing can be unlocked with a password alone.

## Decision

1. Issue **Ed25519-signed** cyber ATO licenses on the Leader. Issuance records **in-person verification**. A **law-enforcement** checkbox is required for Red. Blue may be licensed without LE. Licenses carry `expires_at` and `renew_by` (ATO renewal).
2. Blue/Red **runtime** (`gate_is_enabled`, specialist routing, computer-use blue/red flags) requires the password gate **and** a valid ATO covering that role. Red also requires the LE flag. This still does **not** add exploits, payloads, or hack-back tools.
3. A small CLI (`python -m app.policy.cyber_ato`) and `/api/cyber-ato` mint, install, renew, and report status. Portal Model page shows LE, validity, and ATO renewal.
4. Update `AGENTS.md` / `docs/PROCESS.md` guardrail wording to match: runtime is allowed under a valid ATO; ordinary agents still must not add offensive capability. **Do not** edit Architect spec docs.

**Will not:** ship exploits/PoCs; invent PolitieGPT internals; edit `SECURITY_AGENTS.md` / `BLUE_TEAM.md`.

## Acceptance criteria

- [x] Red ATO without LE is rejected
- [x] Expired ATO does not unlock Blue/Red runtime even if the password gate is on
- [x] CLI and API can issue a license JSON with LE + validity + renew-by
- [x] Model page can issue/install/renew and shows LE + ATO dates
- [x] Unit tests; frontend build

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/policy/cyber_ato.py`, `backend/app/api/cyber_ato.py`, `backend/app/inference/security_gates.py`, `backend/app/main.py` |
| Frontend | `frontend/src/pages/SecurityModelGates.tsx`, `frontend/src/api.ts` |
| Docs | `AGENTS.md`, `docs/PROCESS.md`, this RFC |
| Tests | `tests/test_cyber_ato.py`, `tests/test_security_gates.py` |

## Out of scope

HexStrike payload proxy; offensive tool registry; Architect spec edits.
