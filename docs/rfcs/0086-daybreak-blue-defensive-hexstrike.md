# RFC-0086: Daybreak Blue defensive HexStrike release

**Status:** accepted
**Queue item:** Stream H — Daybreak Blue defensive HexStrike follow-up
**Author:** Taco request via Codex
**Date:** 2026-09-14

**Related:** RFC-0078 suite shell; RFC-0079 computer-use permissions; `docs/spec.md` Stream H; `SECURITY_AGENTS.md` §3.4.

## Problem

The HexStrike suite shell can supervise a configured loopback process and show read-only health, telemetry, and process data, but it cannot install or repair the upstream runtime. It also lacks owner-attested target scopes and a role-bound defensive action surface. Registering upstream HexStrike MCP wholesale would expose arbitrary command, payload, exploit, credential-attack, and file-mutation functions to ordinary agents.

## Decision

1. Add an idempotent Windows bootstrapper pinned to reviewed upstream commit `d689933ff579d839c676c82b231f8e98326c5f04`. It clones only `https://github.com/0x4m4/hexstrike-ai.git`, creates `hexstrike-env`, installs the server dependencies, verifies `/health`, and always binds to loopback.
2. Add asynchronous install/repair state to `/api/hexstrike` and the HUD. The installer refuses unknown remotes, dirty managed clones, commit mismatches, and non-loopback configuration. It does not install the upstream catalog of external security tools.
3. Persist explicit owner-attested scopes for private LAN hosts/CIDRs, local evidence paths, container images, and the local host. Public Internet targets are refused in this release.
4. Expose schema-bound defensive operations only: LAN inventory, container/IaC scanning, local host benchmarks, forensic inspection, and CVE/threat-intelligence lookup. Arguments are normalized by Jarvis; raw commands, arbitrary flags, upstream paths, payloads, exploit generation, credential attacks, and hack-back remain unavailable.
5. Defensive actions require `cyber.hexstrike`, the relevant Blue permission, an unlocked Blue security gate, and a persisted `blue-team` task role. Only Blue tasks receive the filtered `hexstrike_defensive` tool schema. Every install, scope change, execution, stop, and denial is audit-logged.
6. Process controls may stop only jobs launched and tracked by Jarvis. Upstream MCP is never registered wholesale.
7. Add operator help and perform Windows desktop sign-off against the live loopback runtime and HUD.

## Acceptance criteria

- [ ] Install/repair is idempotent, pinned, loopback-only, observable, and recoverable after failure.
- [ ] HUD shows install progress, actionable errors, capabilities, missing dependencies, and managed jobs.
- [ ] Owner-attested scopes reject public targets, traversal, symlink escapes, and invalid container references.
- [ ] Only the documented defensive action enum reaches upstream; arbitrary command/payload/exploit/credential routes remain denied and audited.
- [ ] Blue role, gate, and computer-use permissions are enforced at schema exposure and execution time.
- [ ] Managed process controls cannot terminate untracked processes.
- [ ] Focused tests, full pytest, frontend lint/build, `git diff --check`, `pip check`, and dependency audit are run.
- [ ] Windows sign-off verifies install, `/health`, HUD telemetry/process views, a harmless local defensive action, and blocked offensive requests.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/security/hexstrike.py`, `backend/app/api/hexstrike.py`, `backend/app/policy/computer_permissions.py`, task/tool exposure and a filtered defensive tool |
| Frontend | `frontend/src/hud/HudHexStrikeSuite.tsx`, `frontend/src/hud/hexstrike.css`, `frontend/src/api.ts` |
| Bootstrap/help | `scripts/bootstrap-hexstrike.ps1`, `.gitignore`, `backend/app/help/topics.py` |
| Tests | `tests/test_hexstrike_suite.py`, `tests/test_computer_permissions.py`, task/tool exposure coverage |

## Out of scope

Red/counter-response enablement; PolitieGPT internals; LE artifact validation; public-target scanning; upstream MCP registration; arbitrary commands; payload or exploit generation; credential attacks; automatic installation of 150+ external security tools; version bump, installer release, or promotion to `main`.
