# RFC-0196: HexStrike operator chain (Anzu 1.0 quality)

**Status:** accepted  
**Queue item:** (none — no §58 checkbox; CoS cuts implement waves after this package lands)  
**Author:** Jarvis Architect  
**Date:** 2026-10-02

**Parent stream:** Anzu 1.0 cyber product (siblings [RFC-0197](0197-blue-red-purple-security-agents.md), [RFC-0198](0198-blue-re-lta-protected-folder.md), [RFC-0199](0199-installer-license-auto-apply.md)).

**Related (read; surgical amends in this PR only):** [RFC-0078](0078-hexstrike-cyber-suite.md) suite profile + HUD shell. [RFC-0086 Daybreak](0086-daybreak-blue-defensive-hexstrike.md) pinned install / loopback / scopes (operator ceiling **superseded** by [RFC-0106](0106-hexstrike-jarvis-full-operator-control.md) and **tightened here**). [RFC-0106](0106-hexstrike-jarvis-full-operator-control.md) operator contract (baseline; this RFC adds Anzu 1.0 completion bar). [RFC-0105](0105-cybersecurity-module.md) sibling module (do not collapse). [RFC-0119](0119-license-package-entitlements-and-release-unrestricted.md) license package as capability gate (no invented LE/password gates). [RFC-0079](0079-computer-use-permissions.md) / [RFC-0110](0110-spoken-permissions-and-tts-quality.md) per-action grants after entitlement. [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) Daybreak `hex_aegis` override (unchanged).

This PR is **specs-only**. Product code is follow-up implement tickets. **Do not** tick §57/§58 ledger lines for this stream.

**Hard constraint:** no exploit recipes, PoCs, payload samples, or step-by-step attack procedures in this RFC, help text, or tests.

## Problem

HexStrike on `development` implements much of RFC-0106 (operator catalog, MCP hook, Daybreak tabs, jobs store), but Anzu 1.0 requires an **end-to-end operator chain** that is honest under failure, streams results into Daybreak, and forbids thin landings. Prior RFCs allowed or implied defensive-only enums, health-only HUD, mock MCP, and “implemented” status while **Windows desktop soak** and several operator-path edges remain unchecked. Implement tickets still need a single acceptance contract so workers cannot ship stubs, scaffolding, soft-fail placeholders, or silent caps on the discovered catalog.

## Decision

Specify the **full HexStrike operator chain** as Jarvis-as-operator control: discovery → gated invoke → job lifecycle → streamed results in Daybreak and owner chat → auditable errors. RFC-0106 remains the functional baseline; **this RFC is the Anzu 1.0 quality gate** for implement PRs.

### 1. Operator session lifecycle

| Phase | Owner-visible behavior | Backend contract |
| --- | --- | --- |
| **Entitlement** | If the installed license package lacks `hexstrike` (RFC-0119), suite select and operate paths **deny** with a license reason (not a password gate). | `licensed_module_allowed("hexstrike")` / entitlements wrapper; audit `deny` + reason. |
| **Activate** | ModelSelector `hexstrike-suite` **or** owner chat intent to use HexStrike starts/repairs the **sidecar** without forcing GGUF unload (RFC-0106). | Managed process on loopback only; pin + remote allowlist unchanged. |
| **Discover** | Daybreak **Catalog** lists **all** tools from managed server health, upstream MCP `list_tools`, and host-tool inventory (RFC-0106 §4b). Pagination required; no silent top-N truncation. | `GET /api/hexstrike/tools` (or equivalent) returns schema-bearing rows + `missing_deps[]`. |
| **Prepare** | Missing deps show **actionable** install/repair (winget / pip / job overlay). “Available” must not display if invoke would fail for a fixable dep. | `POST .../tools/{id}/install`; job progress via RFC-0090 overlay pattern. |
| **Invoke** | **Operate** tab + owner chat `hexstrike_operator` (or successor) call **discovered** capabilities by id + JSON args validated against discovered schema. | `POST /api/hexstrike/operate` → job id; no frozen six-enum `Literal` ceiling. |
| **Observe** | Daybreak **Jobs** streams status, log tail, artifacts; owner chat receives the same job summary. | Shared job store under Jarvis-owned paths only. |
| **Teardown** | Stop suite or switch inference profile stops managed server; stop job only for Jarvis-tracked pids. | Existing supervisor rules. |

### 2. Tool discovery and refresh

1. On suite **start** and after any **host-tool install** completes, refresh discovery (MCP + HTTP + host rows).
2. Discovery failure is **surfaced** (HTTP error, MCP handshake error, unhealthy `/health`) — not an empty catalog with `ok: true`.
3. Stale catalog after repair without refresh is a **fail**.

### 3. Gated invocation (honest gates only)

| Gate | Source | Must not |
| --- | --- | --- |
| License module `hexstrike` | RFC-0119 installed package | Invent LE/ATO/officer checklists in this chain |
| Loopback bind | RFC-0078 / 0086 / 0106 | WAN listener or proxy to raw upstream without audit |
| Per-action computer-use | RFC-0079 / 0110 when a call touches desktop/files/network | Password `security-model-gates.json` as capability unlock |
| Owner-attested scope (defensive targets) | RFC-0086 persisted scopes for **defensive** LAN/local paths where still enforced | Public-Internet scanning as default; scope bypass |

Red-team offensive use of HexStrike tools is **out of this RFC** — routed through [RFC-0197](0197-blue-red-purple-security-agents.md) authorization and target policy, not a second hidden gate.

### 4. Streaming results into Daybreak console

1. **Jobs** tab subscribes to job store updates (poll ≤2s or SSE/WebSocket if added — either is acceptable if UI stays live during long runs).
2. **Log tail** grows during `running`; terminal states `succeeded` | `failed` | `cancelled` with **honest** `error` text from upstream (redact secrets only).
3. **Artifacts** list is clickable/open-folder only under allowed paths; missing artifact file → `failed` state, not silent omit.
4. Owner chat tool results include job id + summary + link hint to open Daybreak Jobs (no duplicate job store).

Soft-fail patterns (**forbidden**): returning `{"ok": true}` with empty output; mock MCP tools; “coming soon” Operate panel; catalog capped to six enums; health-only HUD without Operate/Jobs.

### 5. Error honesty

- Install/repair errors: show stderr excerpt + recovery action (retry repair, check pin, check loopback port).
- Invoke errors: propagate upstream message; do not map all failures to generic “defensive action denied.”
- Entitlement errors: name missing **module** on the license package.
- Network to loopback failure: distinguish “server not running” vs “connection refused” vs “timeout.”

### 6. Implement-ticket anti-patterns (explicit ban)

Implement PRs for this chain **must not** land:

- Stub MCP registration that never calls the managed server
- Hardcoded defensive enum as the only invoke path
- Daybreak UI that lists tools but cannot invoke or install deps
- Jobs that never persist logs/artifacts
- Silent skip of discovered required host tools
- `TODO` operator paths behind feature flags default-on in production HUD
- Tests that only assert HTTP 200 on `/health` without catalog/operate/job coverage

### 7. Supersedes / amends prior HexStrike RFCs

| RFC | What changes |
| --- | --- |
| RFC-0078 | Suite shell + `hex_aegis` **unchanged**; operator depth is RFC-0106 + **this RFC** |
| RFC-0086 | Install pin, loopback, scopes, audit **remain**; “defensive-only enum / no MCP / Blue-task-only tools” is **not** the product bar |
| RFC-0106 | Still the operator feature list; **0196 adds** streaming, error honesty, anti-stub rules, and desktop soak matrix |
| RFC-0105 | Sibling; HexStrike chain does not absorb the six catalog members |

## Acceptance criteria

Specs-only in **this** PR:

- [x] RFC-0196 filed, status **accepted**, cross-links to 0078/0086/0105/0106/0119
- [x] End-to-end operator chain documented (lifecycle, discovery, gates, streaming, errors)
- [x] Explicit forbid list for stubs/scaffolding/soft-fail in implement tickets
- [x] No exploit recipes / PoCs / attack steps in this RFC
- [x] No `JARVIS_MASTER_PLAN.md` §58 ledger ticks

Implement follow-up (one or more CoS-named tickets; **Anzu 1.0 bar**):

- [x] Entitlement deny path is license-based (RFC-0119); no password gate required for entitled `hexstrike`
- [x] Discovery refresh on start and after dep install; failures visible in HUD
- [x] Full catalog paginated; Operate uses discovered schemas (not six-enum ceiling)
- [x] Jobs stream log tail + artifacts into Daybreak; chat shares job store
- [x] Error messages honest per §5; no mock/stub paths in production
- [x] Unit tests: discovery refresh, operate→job, entitlement deny, loopback/pin guards, artifact path bounds
- [x] `npm --prefix frontend run build` (and lint if TS changed)
- [ ] **Windows desktop soak** (unchecked in cloud): pinned install → start → catalog shows live tools → one real operate via HUD **and** chat → job log + artifact visible → stop/restart recovery → blocked invoke when unentitled

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/security/hexstrike*.py`, `backend/app/api/hexstrike.py`, `backend/app/tools/hexstrike_*.py`, `backend/app/tools/mcp_runtime.py`, `backend/app/agent/tool_exposure.py`, `backend/app/licensing/entitlements.py`, `backend/app/policy/cyber_ato.py` |
| Frontend | `frontend/src/hud/HudHexStrikeSuite.tsx`, `frontend/src/hud/hexstrikeSuite.ts`, `frontend/src/hud/hexstrike.css`, `frontend/src/api.ts` |
| Tests | `tests/test_hexstrike_suite.py`, `tests/test_rfc0106_*.py`, new `tests/test_rfc0196_*.py` |
| Bootstrap | `scripts/bootstrap-hexstrike.ps1` |
| Docs | this RFC; surgical amend notes on 0078/0086/0106 |

## Out of scope

- Blue/red/purple agent personas and target authorization ([RFC-0197](0197-blue-red-purple-security-agents.md))
- blue.re / LTA protected-folder UX ([RFC-0198](0198-blue-re-lta-protected-folder.md))
- Installer license sidecar ([RFC-0199](0199-installer-license-auto-apply.md))
- Collapsing RFC-0105 cybersecurity module into HexStrike
- Inventing LE/Red/Purple/ATO officer procedures or new license fields
- Architect edits to `SECURITY_AGENTS.md`, `BLUE_TEAM.md`, `PORTAL_UX.md`, or §57 Current State

## Notes

- Cloud agents: pytest + frontend build only; **desktop soak** is owner/Windows sign-off.
- Model for this Architect PR: **Composer 2.5 standard** (`fast=off`).
