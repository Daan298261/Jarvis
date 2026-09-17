# RFC-0106: HexStrike Jarvis full operator control

**Status:** implemented
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Owner intent (Taco, north star):** Jarvis needs **complete control** over HexStrike and its toolchain options. Jarvis is the **human** using HexStrike. Do **not** invent gating (owner will handle later). Do **not** build stubs — build the real thing.

**Related (read; do not rewrite those files except a successor pointer on RFC-0086):** RFC-0078 HexStrike suite shell (implemented: ModelSelector row, loopback supervisor, Daybreak HUD chrome, `hex_aegis`). RFC-0086 Daybreak Blue defensive release (pinned install/repair, loopback, five/six typed actions — **operator limits superseded here**). RFC-0048 HexStrike gateway (loopback, audit, process supervisor **remain**; “no MCP / no command proxy” is **not** the HexStrike end-state). RFC-0079 computer-use session grants (HUD click / owner chat may still count as operator intent; no new LE/ATO invented here). RFC-0090 optional-worker install overlay. RFC-0105 cybersecurity module (sibling pack — **do not collapse** into HexStrike).

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not edit `frontend/src/` or backend in this PR.

**Intent precedence:** For HexStrike **operation**, **RFC-0106 wins** over thinner “Blue-only enum / no MCP / no command proxy / ordinary Jarvis cannot operate HexStrike” wording in RFC-0086 (and the matching RFC-0078 decision §4 / RFC-0048 gateway bullets). Keep loopback bind and install pinning where they protect the host. Remove the product stance that Jarvis cannot drive HexStrike’s real operator surface.

**Hard constraint for this spec and for implement PRs:** do **not** include exploit recipes, PoCs, payload samples, or step-by-step attack procedures — not in this RFC, not in help text, not in tests as copy-pastable tradecraft.

## Problem

RFC-0078 / RFC-0086 shipped a **managed defensive shell** on `development` (~`f109347`): pinned `0x4m4/hexstrike-ai` clone, loopback `hexstrike_server.py`, Daybreak HUD health/telemetry, and `/api/hexstrike` install/start/stop. That is not “Jarvis uses HexStrike like a human operator.”

On the current tip:

- Gateway allowlists only a **narrow Blue defensive enum** (`lan_inventory`, `container_scan`, `iac_scan`, `host_baseline`, `forensic_inspection`, `threat_intel_lookup`) mapped to five host binaries (nmap / trivy / checkov / docker / exiftool).
- Upstream **MCP is not registered** into Jarvis’s owner-operator / HexStrike-suite tool context.
- Raw operator HTTP that a human would use against the HexStrike server (including non-enum tool routes) is **denied** by `gateway_allows` / `_BLOCKED_TOKENS` / `hexstrike_defensive`.
- Host toolchain install is a **fixed five-package winget list**; HexStrike’s real dependency set is discovered only as “missing nmap” style rows, not as the upstream catalog.
- Chat exposes `hexstrike_defensive` only to `blue-team` tasks. Daybreak is largely a **health + five-action** panel.

Owner (Taco) directed the end-state: Jarvis **is** the operator. A decorative health panel is a fail.

## Decision

Treat HexStrike as an **embedded operator suite** that Jarvis drives end-to-end. When the HexStrike / Daybreak suite is active, **or** the owner asks in chat (“Jarvis, run HexStrike …”), Jarvis may use the **full HexStrike toolchain** the upstream server exposes for an interactive human operator: install path, process lifecycle, tool availability, jobs, and operational calls.

### 1. Jarvis = HexStrike operator

Jarvis is not a spectator of a third-party dashboard. The owner talks to Jarvis; Jarvis talks to HexStrike (MCP and/or first-class operator HTTP) the way a human at a keyboard would: start the suite, see which tools are live, install what is missing, invoke capabilities, watch jobs, read logs, collect artifacts.

Selecting `hexstrike-suite` in ModelSelector still starts the managed loopback process and opens Daybreak (RFC-0078). Owner chat must be able to drive the same suite **without** forcing a GGUF unload: HexStrike runs as a **sidecar** when the owner asks, even if another inference profile is loaded.

### 2. What this RFC supersedes vs keeps

| Keep (host protection) | Supersede (product end-state for this module) |
| --- | --- |
| Loopback bind only (`127.0.0.1` / `::1`). No WAN listener. | “Only the six Blue enums may reach upstream.” |
| Managed install/repair pinned to reviewed remote `https://github.com/0x4m4/hexstrike-ai.git` and commit (today `d689933ff579d839c676c82b231f8e98326c5f04`) **or** an **owner-approved** newer commit on that same remote. Unknown remotes, dirty managed clones, and non-loopback binds stay refused. | “Upstream MCP is never registered.” |
| Jarvis-owned subprocess: start/stop/pid; stop only jobs/pids Jarvis started. | “Raw operator routes always 403.” |
| Audit log every install, start/stop, catalog refresh, invoke, deny (host/network), artifact write. | “Ordinary Jarvis cannot operate HexStrike’s real surface.” |
| Daybreak HUD chrome (`.hex-suite`, `hex_aegis`). Do not delete the panel. | Host tools frozen at the five winget ids. |
| HexStrike **not vendored** into git. | `hexstrike_defensive` as the only chat tool, Blue-role gated as the product bar. |

RFC-0086 remains the install/repair/loopback/HUD **shell** ticket. This RFC is the **operator** ticket. Do not re-litigate pinning vs loopback.

### 3. No invented authorization gates

This RFC does **not** add LE / Red / Purple / ATO / officer-procedure gates. Existing HUD/chat session intent (`cyber.hexstrike` from RFC-0079) may be reused so a Daybreak click or owner chat turn can actually run. Do **not** invent new checklists, case-file workflows, or role matrices here. Authorization policy is **out of scope** (owner later). Implementers must not block the operator surface on “Blue-only enum” leftovers from RFC-0086.

Product surface (not a new ATO): HexStrike operator MCP/routes belong to **Daybreak + owner chat**. Do not attach them to guest portals as a default.

### 4. Real, not stubs

Half-shell health-only UI, mock MCP tools that never call the managed server, hardcoded five-enum-only invoke, or “TODO install later” for tools the pinned clone actually needs are **fails**. Taco’s bar is full implementation.

#### 4a. Managed HexStrike install / repair

Keep `scripts/bootstrap-hexstrike.ps1` + `backend/app/security/hexstrike_install.py` idempotent install/repair into `runtime/hexstrike-ai` or `JARVIS_HEXSTRIKE_HOME`. Observable progress in Daybreak. Recoverable after failure. Owner-approved pin bump: Daybreak/settings records a new commit SHA on the same allowlisted remote; next repair checks it out. Still no arbitrary GitHub URL.

#### 4b. Host toolchain — discover, surface, install

HexStrike needs host binaries and Python deps beyond the five RFC-0086 winget packages. Implementers **discover** that set from the **managed install**, not from a Jarvis-invented pentest shopping list:

1. Running suite health / tools payload (already partially mirrored on `GET /api/hexstrike`).
2. Upstream MCP `list_tools` once the server is up.
3. Inventory / requirements files **inside the pinned clone** (names and package managers only — do not copy tradecraft into Jarvis docs or tests).

Daybreak shows **all** discovered tools with live available/missing status (paginate; do not silently cap the operator out of the catalog). Missing deps get one-click / repair install where Windows allows:

- **winget** when a stable package id is known (extend `hexstrike_tools.py` past the five).
- **hexstrike-env pip** for Python packages the pin’s own installer expects.
- RFC-0090 **job overlay** for long installs (progress / error).
- If Windows cannot auto-install an item, show an actionable owner path (what is missing, why, where to put it on `PATH`). Silent skip of a discovered required tool is a stub.

Jarvis orchestrates this. The owner should not have to leave Jarvis to stand up HexStrike’s toolchain.

#### 4c. Invoke — MCP and/or first-class operator API

Implement **both** of the following so Daybreak (HTTP) and chat (tools) can drive the suite. One may wrap the other; neither may be a decorative stub.

1. **MCP.** When the suite starts, and when owner chat engages HexStrike, register the upstream HexStrike MCP into the **HexStrike-suite / owner-operator** context via `backend/app/tools/mcp_runtime.py` (stdio or loopback HTTP/SSE — whichever the pin actually ships). Refresh `list_tools` after start and after host-tool installs. Jarvis calls those tools; results return through the normal tool/job path.
2. **First-class `/api/hexstrike` operator routes** that are **not** limited to the RFC-0086 six-action `Literal`. Discover the catalog; invoke by capability id + JSON arguments validated against the discovered schema; return a job. Expand or replace `hexstrike_defensive` so owner chat is not stuck on five enums / Blue-task-only exposure.

Suggested contract (implement may rename, not invent a second suite):

| Method | Path | Intent |
| --- | --- | --- |
| `GET` | `/api/hexstrike` | Runtime + install + **full** discovered tool catalog + missing deps + jobs |
| `POST` | `/api/hexstrike/start` · `/stop` | Process lifecycle (existing) |
| `POST` | `/api/hexstrike/install` | Pinned clone/repair (existing) |
| `GET` | `/api/hexstrike/tools` | Discovered operator catalog (MCP + HTTP + host-tool rows) |
| `POST` | `/api/hexstrike/tools/{id}/install` | Orchestrate one missing host/Python dep |
| `POST` | `/api/hexstrike/operate` | Invoke one discovered capability; start a job |
| `GET` | `/api/hexstrike/jobs` | Managed jobs |
| `GET` | `/api/hexstrike/jobs/{id}` | Status + log tail |
| `GET` | `/api/hexstrike/jobs/{id}/artifacts` | Artifact list under owned paths |
| `POST` | `/api/hexstrike/jobs/{id}/stop` | Stop Jarvis-tracked job only |

Do not freeze the catalog as six string enums in FastAPI `Literal`s. Schema comes from discovery. This RFC does **not** document upstream argument examples.

#### 4d. Results stream back into Jarvis

Every operate call is a **job**: id, capability, start/end, status, log tail, artifact paths. Persist under Jarvis-owned storage (e.g. `data_dir()/hexstrike/jobs/{id}/` and artifacts only under `allowed_directories` / that jobs root). Daybreak polls/streams the same store owner chat uses. Logs and summaries appear in the HUD and as chat tool results. Do not leave output only inside the HexStrike process.

### 5. Daybreak is the primary HUD; chat is a first-class operator

- **Daybreak** (`HudHexStrikeSuite`): start/stop, install/repair, live tool status, missing-dep install, operate, jobs/logs/artifacts. Copy must stop saying “defensive gateway · local and owner-attested only” as if that were the capability ceiling. Health-only without operator drive is a **fail**.
- **Owner chat:** first-class. Natural language that means “use HexStrike” starts/repairs the sidecar if needed, then invokes. Do not require the owner to open the HUD to do real work.

### 6. RFC-0105 sibling — do not collapse

RFC-0105 (`cybersecurity` module: Strix, Anthropic Cybersecurity Skills, Exploitarium, Pentagi, Claude-Red, Flowsint) is a **sibling** surface. HexStrike is the **embedded HexStrike suite**. Jarvis may orchestrate both. Do not fold 0105 members into HexStrike MCP, and do not replace HexStrike with those six clones. Do not rewrite `HudCybersecurityModule` in the HexStrike implement ticket (and vice versa).

### 7. Architect ledger

Light `JARVIS_MASTER_PLAN.md` §59 Decision Log line only. No §57 rewrite. No new §58 checkbox. No edits to `SECURITY_AGENTS.md` / `BLUE_TEAM.md` / `PORTAL_UX.md` in this PR.

**Will not:** invent LE/Red/Purple/ATO gates or officer checklists. Collapse RFC-0105. Vendor `hexstrike-ai` into git. Bind HexStrike on a WAN interface. Put exploit recipes, PoCs, payloads, or attack steps in this RFC, help topics, or tests. Ship product code in this PR.

## Acceptance criteria

Specs-only in **this** PR:

- [x] RFC-0106 filed as `docs/rfcs/0106-hexstrike-jarvis-full-operator-control.md`, status **accepted**, Author Jarvis Architect, Date 2026-09-17 — specs PR #276
- [x] North star recorded: Jarvis = HexStrike operator; full upstream operator toolchain; no invented gating; real, not stubs
- [x] RFC-0106 **intent wins** over RFC-0086 “Blue-only enum / no MCP / no command proxy” for HexStrike operation; loopback + install pin kept
- [x] RFC-0105 called out as sibling (do not collapse)
- [x] No exploit recipes, PoCs, payload samples, or attack procedures in this RFC
- [x] Light §59 Decision Log line only
- [x] No `frontend/src/` or backend product edits in this PR

Implement follow-up (landed — **Taco’s full-implementation bar**):

- [x] Half-shell **health-only** Daybreak UI without operator drive is a **fail** — Daybreak operator console #283
- [x] Stubs, mock MCP, five-enum-only invoke, or skipped discovered host-tool install (when Windows can install it) are a **fail** — backend #279
- [x] Managed pin/repair + loopback start/stop still work; unknown remotes / non-loopback still refused
- [x] Host toolchain discovered from the managed install; Daybreak shows missing deps; Jarvis can orchestrate install beyond the original five winget tools
- [x] Upstream HexStrike MCP is registered to the HexStrike-suite / owner-operator context when the suite is active or owner chat engages it
- [x] `/api/hexstrike` operator routes (or equivalent) invoke discovered capabilities, **not** only the RFC-0086 six enums
- [x] Owner chat can start/stop and operate HexStrike without requiring a GGUF swap; Daybreak remains the HUD console
- [x] Jobs, logs, and artifacts stream into Jarvis under owned paths; HUD and chat share the job store
- [x] RFC-0105 module remains a sibling (no collapse)
- [x] No new LE/Red/Purple/ATO gates added by this implement
- [x] Unit tests: `python3 -m pytest` (catalog not limited to six enums; MCP registration hook; loopback/pin still enforced; jobs only stop Jarvis pids; artifacts path-bound). Do **not** encode attack procedures in tests
- [x] `npm --prefix frontend run build` (and lint if TS changed)
- [ ] Windows desktop sign-off: live pinned install, start/stop, discovered tool status, one real operator invoke through HUD **and** chat, job/log/artifact visible in Jarvis. Cloud VMs cannot sign this off

## Likely files

| Area | Paths |
| --- | --- |
| Backend — runtime / gateway | `backend/app/security/hexstrike.py` (drop operator-surface denials that 0086 used as the product bar; keep loopback + audit); `backend/app/security/hexstrike_install.py`; `backend/app/security/hexstrike_tools.py` (discover + extend installers); `backend/app/security/hexstrike_defensive.py` (enum ceases to be the ceiling — evolve or replace) |
| Backend — API / tools / MCP | `backend/app/api/hexstrike.py`; `backend/app/tools/hexstrike_defensive.py` (expand/replace with owner-operator tool); `backend/app/tools/mcp_runtime.py`; `backend/app/agent/tool_exposure.py` (HexStrike-suite / owner chat context); `backend/app/help/topics.py` |
| Frontend — Daybreak | `frontend/src/hud/HudHexStrikeSuite.tsx`; `frontend/src/hud/hexstrike.css`; `frontend/src/hud/hexstrikeSuite.ts`; `frontend/src/api.ts`; ModelSelector start path only if sidecar-from-chat needs it |
| Bootstrap | `scripts/bootstrap-hexstrike.ps1` |
| Tests | `tests/test_hexstrike_suite.py`; `tests/test_daybreak_blue.py` (update expectations that 403 all non-enum routes); new `tests/test_rfc0106_*.py` |
| Docs | this RFC; `JARVIS_MASTER_PLAN.md` §59 Decision Log line only; successor pointer on RFC-0086 |

## Out of scope

- Authorization policy (LE, Red, Purple, ATO, officer procedures) — **deferred to owner**; not specified here. Do not invent checklists.
- Product implementation in this PR.
- RFC-0105 six-member module wiring / Daybreak panel work (sibling; separate tickets).
- `whole` embed of the upstream HexStrike web UI as a WAN app.
- Vendoring `hexstrike-ai` into this git repo.
- Binding HexStrike on a non-loopback / WAN interface.
- Architect rewrites of `SECURITY_AGENTS.md` / `BLUE_TEAM.md` / `JARVIS_2.0.md` / `PORTAL_UX.md` beyond the §59 ledger tick.
- Swarm / P4–P5 / model-stack.
- Exploit, PoC, payload, or attack-step documentation.

## Notes

- Source: Taco owner directive 2026-09-17. HexStrike is the embedded suite; Jarvis is the operator. RFC-0105 tools are siblings.
- Upstream project (pin, do not vendor): https://github.com/0x4m4/hexstrike-ai
- Linux cloud VMs: unit-test discovery, catalog-not-five-enums, MCP registration hooks, loopback/pin guards, job path bounds. Live HexStrike + host-tool winget + HUD/chat invoke is **Windows desktop sign-off**.
- Implement launch: this RFC only; branch from `development`; pytest + frontend build; do not edit Architect spec docs beyond what Architect already landed; PR against `development`; do not merge other PRs.

## Implementation note

Landed on `development` via specs **#276** @ `7c1be3f` + backend **#279** @ `175b2dc` + Daybreak UX **#283** @ `69eebd7` (operator catalog / MCP / `/api/hexstrike` operate→jobs; Daybreak tabbed console — Runtime / Catalog / Operate / Jobs; `hexstrike_operator` chat tool). RFC-0105 cybersecurity module stays a sibling (no collapse). Loopback bind + install pin kept. Gating/authorization not invented. Live pinned install / HUD+chat invoke / job-log-artifact remains Windows desktop sign-off. No new §58 checkbox.
