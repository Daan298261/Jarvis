# RFC-0105: Cybersecurity module (six Instagram clones)

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent:** RFC-0095 Instagram collection ingest + Module Catalog Download.  
**Related (read only; do not rewrite):** RFC-0006 hierarchical workers. RFC-0007 domain/workspace packs. RFC-0009 runtime portability. RFC-0024 skill lifecycle. RFC-0050 HUD / presence. RFC-0078 / RFC-0086 HexStrike (existing defensive suite + HUD panel **pattern** — **not** “HexStrike forever” as the only cyber surface; do not rewrite `HudHexStrikeSuite`). RFC-0090 optional-worker Install now. RFC-0094 Settings IA (Voice/Appearance left-bar; Advanced is **not** this module’s home). `SECURITY_AGENTS.md` (related reading only).

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not edit `frontend/src/` or backend in this PR. Local clones belong under Architect’s `projects/` library — **not** committed here.

RFC numbers **0096–0104** are reserved by open [PR #271](https://github.com/Daan298261/Jarvis/pull/271) (Instagram child integrations). This RFC is **0105**. Do not reuse 0096–0104.

## Problem

RFC-0095 downloaded Taco’s Instagram-jarvis saves and defaulted six of them (Strix, Anthropic Cybersecurity Skills, Exploitarium, Pentagi, Claude-Red, Flowsint) to archive-only pending a named product RFC. The clones already exist on the Architect box and the Windows PC. There is no Module Catalog grouping, no per-tool enable/status UX, and no architecture for discovering those checkouts or attaching them as optional backends / skill packs / workers.

RFC-0095 did not specify how these six become a **module**. HexStrike (RFC-0078 / 0086) is the existing defensive suite; it is not the only cybersecurity surface Jarvis will ever have. Owner (Taco) directed these six into one cybersecurity module, **operable from Daybreak** (HUD), not buried in Settings Advanced. This RFC covers **module surface + integration wiring**, not security-politics.

## Decision

Treat the six local clones as **one** Jarvis module in the Module Catalog / Packs (RFC-0095 Download + enable pattern). Module id: `cybersecurity`. They are optional backends, skill packs, and workers **inside that module** — not six unrelated orphan tools.

**Implement surface = Daybreak** (HUD). The module must be reachable and operable from Daybreak: HexStrike-adjacent **left-bar** (next to `AppearancePresenceControls` Voice/Appearance groups) **or** a Daybreak **suite panel** patterned on `HudHexStrikeSuite` / `.hex-suite`. Settings Advanced / Packs may deep-link; they are **not** the home. A Settings-only or Advanced dump is a fail.

Jarvis UX owns `frontend/src` Daybreak UI (enable / status / open-folder / per-tool rows). Backend worker hooks (discover, subprocess supervisor, skill-pack register, harness spawn) are a **separate D1 slice** after CoS names that ticket. This RFC still records the wiring contract so D1 does not invent a second catalog.

RFC-0095’s archive-only default is **superseded for these six named tools only**. Other unnamed Instagram pentest saves stay under RFC-0095 until a later named RFC. HexStrike stays the existing defensive suite **beside** this module; this RFC does not rewrite HexStrike, fold the six into HexStrike MCP, or declare HexStrike the permanent sole cyber UI.

### 1. Four-step pipeline (RFC-0095)

Skipping a step is a fail. For this module:

| Step | This RFC |
| --- | --- |
| **Download** | **Done.** Clones already on disk (table below). Re-fetch uses RFC-0095 `POST /api/modules/catalog/{id}/download` (allowlisted `source_url` only). |
| **Usefulness** | Primary bucket **`module`**; tag **`cybersecurity`**. Secondary tags per member (harness / skill_pack / library_backend / graph_ui) are allowed. |
| **Integrate** | **`partial`** — connectors into the `cybersecurity` module first (discover, enable, launch hook, skill-pack register, graph/UI entry). **`whole`** embed of any upstream app is optional later (separate RFC). |
| **Implement** | Two named follow-ups after this spec: **Jarvis UX** Daybreak panel; **D1** worker hooks after CoS names that slice. Ordinary workers do not start product wiring from a save alone. |

Pipeline state is durable on the parent catalog entry `cybersecurity` and on each member. Re-saves of the same canonical repo dedupe (RFC-0095).

### 2. The six members

| Member id | Tool | Upstream | Architect box | Windows |
| --- | --- | --- | --- | --- |
| `strix` | Strix | https://github.com/usestrix/strix | `/workspace/projects/le-gated/strix` | `C:\Users\daanv\projects\jarvis-ig\le-gated\strix` |
| `anthropic-cybersecurity-skills` | Anthropic Cybersecurity Skills | https://github.com/mukul975/Anthropic-Cybersecurity-Skills | `.../Anthropic-Cybersecurity-Skills` | same under `le-gated` |
| `exploitarium` | Exploitarium | https://github.com/bikini/exploitarium | `.../exploitarium` | same |
| `pentagi` | Pentagi | https://github.com/vxcontrol/pentagi | `.../pentagi` | same |
| `claude-red` | Claude-Red | https://github.com/SnailSploit/Claude-Red | `.../Claude-Red` | same |
| `flowsint` | Flowsint | https://github.com/reconurge/flowsint | `.../flowsint` | same |

Do not vendor these trees into the Jarvis git repo. Directory name `le-gated` is historical path only; it is not a policy in this RFC.

### 3. Local discovery

Jarvis resolves each member’s `local_path` in order:

1. Catalog-recorded `local_path` if the directory still exists.
2. Known library roots, first match wins: Windows `C:\Users\daanv\projects\jarvis-ig\le-gated\<slug>`, Architect `/workspace/projects/le-gated/<slug>`, RFC-0095 library `projects/<slug>`, Desktop `%USERPROFILE%\Desktop\projects\<slug>`.
3. Match by member id / upstream repo slug / recorded `source_url`. Do not walk the whole disk.

Status values: `missing` | `found` | `starting` | `running` | `error` | `disabled`. Missing + downloadable → RFC-0095 Download. Success records `local_path`, source URL, resolved commit/tag, timestamp.

### 4. Module UX (Daybreak)

**Home:** Daybreak HUD (`HudChatHome`, `uiMode === "hud"`), not Settings.

Place **one Cybersecurity module** panel — not six orphan Packs rows — in either (implementer picks one; both are Daybreak):

1. **Left-bar toolkit group** adjacent to `AppearancePresenceControls` (Voice / Appearance `<details>` on `HudChatHome`). A third first-class left-bar group, e.g. summary **Cybersecurity**, with per-tool rows inside. Do not merge it into Voice or Appearance. Do not bury it under Settings Advanced.
2. **Daybreak suite panel** HexStrike-adjacent: same HUD chrome as `HudHexStrikeSuite` (`.hex-suite` / overlay expand). A sibling suite panel, not a rewrite of HexStrike and not a second Aegis HUD. Flowsint’s graph/UI entry lives here when the member is enabled.

Per member row (Jarvis UX, `frontend/src`):

- Enable / disable (module master enable plus per-tool enable; disabled members are not launched or registered).
- Status (`missing` / `found` / `running` / …).
- Path to the local clone.
- **Open folder** when `local_path` exists.
- **Download** (RFC-0095) when the path is missing or the owner re-fetches.

Optional deep-link from the panel to `/packs` or `/settings/advanced` is allowed **in addition**, never instead of Daybreak operability. Do not invent a seventh Settings group. Do not rewrite HexStrike left-bar / suite behavior (RFC-0094 / RFC-0078).

### 5. Architecture wiring (`partial` connectors)

This section is **wiring only**. It does **not** document exploits, PoCs, attack steps, payloads, recipes, or operator tradecraft. Implement tickets name start commands from each clone’s own README; this RFC does not copy them.

**Slice split:** Jarvis UX implements the Daybreak panel (read catalog, enable, open-folder, status rows) against the light API below — stub or read-only catalog is enough for the UX ticket if D1 has not landed. **D1** implements worker hooks (discovery scan, subprocess start/stop, skill-pack register, harness spawn) after CoS names that slice. UX must not wait on HexStrike internals.

**Shared launch hook (D1).** Reuse RFC-0090 job overlay (progress / error) and the HexStrike **process-supervisor shape** (Jarvis-owned subprocess, loopback bind, pid, start/stop, health) as a **generic module-worker supervisor** — not a HexStrike fork. Jarvis may stop only pids it started. Do not register any upstream MCP catalog wholesale. Do not pip-install owner-typed specs; clones are already on disk.

| Member | Role | Connector (v1 `partial`) |
| --- | --- | --- |
| `strix` | Agent harness + optional worker | Discover checkout; optional-worker / subprocess launch hook; **agent harness entry** so Jarvis can dispatch a bounded child worker (RFC-0006 / RFC-0009) whose cwd is the clone. |
| `anthropic-cybersecurity-skills` | Skill pack | Scan the clone for skill manifests (`SKILL.md` or equivalent). **Register as a skill pack** (RFC-0024 + existing `backend/app/agent/skills.py` / harness skill hints). Attach when the member is enabled. List pack **names** only in Jarvis UI. |
| `exploitarium` | Optional library backend | Discover checkout; optional filename/title index for retrieval. No copy of library bodies into Jarvis `docs/` or this RFC. |
| `pentagi` | Agent harness + optional worker | Same shape as Strix: subprocess launch hook + **agent harness entry** (bounded child worker, clone cwd). Optional local UI is open-folder / loopback embed later (`whole` is out of this RFC). |
| `claude-red` | Skill pack | Same as Anthropic Cybersecurity Skills: register the clone **as a skill pack**; attach when enabled. |
| `flowsint` | Graph / UI | **Graph/UI entry** on the Daybreak module panel. Discover a local UI if the clone exposes one on loopback; otherwise Open folder. Not HexStrike HUD; not a PresenceHost / RFC-0069 rewrite. |

Skill packs are resources of module `cybersecurity`, not butler persona (RFC-0095 `persona_candidate` track / RFC-0104). Do not fold them into RFC-0055 / voice defaults.

**API (light; implement may rename, not invent a second catalog):**

| Method | Path | Intent |
| --- | --- | --- |
| `GET` | `/api/modules/catalog` | Existing RFC-0095 list; `cybersecurity` is one row with `members[]` |
| `GET` | `/api/modules/catalog/cybersecurity` | Module + six members: id, source_url, local_path, enabled, status, role |
| `POST` | `/api/modules/catalog/cybersecurity/enable` | `{ "enabled": bool }` master switch |
| `POST` | `/api/modules/catalog/cybersecurity/tools/{id}/enable` | Per-tool enable |
| `POST` | `/api/modules/catalog/{id}/download` | Reuse RFC-0095 Download |
| `POST` | `/api/modules/catalog/cybersecurity/tools/{id}/start` | Subprocess / harness / UI hook when the role needs it |
| `POST` | `/api/modules/catalog/cybersecurity/tools/{id}/stop` | Stop Jarvis-managed pid only |
| `POST` | `/api/modules/catalog/cybersecurity/tools/{id}/open-folder` | Open `local_path` |

**Will not:** invent authorization / LE / Red / Purple / ATO gating rules or officer procedures. Rewrite HexStrike / `HudHexStrikeSuite`. Ship Settings-only or Advanced-dump UX. Vendor upstream trees. Put exploit recipes, PoCs, attack steps, or payloads in this RFC or in Jarvis spec docs. Start product implementation in this PR. Reuse RFC numbers 0096–0104.

## Acceptance criteria

- [ ] Specs-only in this PR (no `frontend/src` / backend product edits; no `projects/` clones committed)
- [ ] Six tools named and grouped under module id `cybersecurity` (not six orphan catalog rows)
- [ ] Four-step pipeline specified: Download (done) → usefulness `module` / cybersecurity → integrate **`partial`** → implement (follow-up)
- [ ] Module UX specified as **Daybreak** (HUD / HexStrike-adjacent left-bar or Daybreak suite panel): per-tool enable, status, local path, open-folder; RFC-0095 Download for re-fetch. Settings-only / Advanced dump is a fail
- [ ] Jarvis UX owns `frontend/src` Daybreak UI; backend worker hooks are a separate D1 slice after CoS names it
- [ ] Architecture wiring specified only: discovery, optional-worker / subprocess hooks, skill-pack register (Anthropic Cybersecurity Skills + Claude-Red), graph/UI entry (Flowsint), harness entry (Strix + Pentagi)
- [ ] HexStrike remains the existing defensive suite beside this module (RFC-0078 / 0086 not rewritten)
- [ ] No exploit recipes, PoCs, attack steps, or payload docs in this RFC
- [ ] Gating / authorization not invented here (see Out of scope)
- [ ] Light §59 Decision Log line only (no §57 rewrite, no new §58 checkbox)
- [ ] Implement follow-up (separate tickets): Jarvis UX Daybreak — `npm --prefix frontend run build` (and lint if TS changed). D1 worker hooks — `python3 -m pytest`

## Likely files

| Area | Paths |
| --- | --- |
| Frontend — Jarvis UX (Daybreak implement) | `frontend/src/hud/HudChatHome.tsx`; new `frontend/src/hud/HudCybersecurityModule.tsx` (name may vary); HexStrike-adjacent suite CSS **patterns** from `frontend/src/hud/hexstrike.css` without rewriting `HudHexStrikeSuite.tsx`; left-bar adjacent to `frontend/src/presence/AppearancePresenceControls.tsx`; `frontend/src/hud/HudShell.tsx` only if HUD chrome needs an entry; `frontend/src/api.ts` catalog types + enable / open-folder. Optional deep-link only: `Packs.tsx` / `AdvancedSettingsPane.tsx` |
| Backend — D1 slice (later, after CoS names) | `backend/app/api/modules.py` (RFC-0095 catalog) + `backend/app/modules/cybersecurity.py` (discover, enable, supervisor); reuse `backend/app/workers/install.py` job overlay and HexStrike supervisor **shape** from `backend/app/security/hexstrike.py` without folding into `/api/hexstrike`; skill-pack register via `backend/app/agent/skills.py` / `local_harness.py` |
| Tests | UX: Daybreak panel rows / enable / open-folder. D1: `tests/test_rfc0105_*.py` — discovery roots, module grouping, enable flags, start/stop only Jarvis pids, download allowlist reuse |
| Docs | this RFC; `JARVIS_MASTER_PLAN.md` §59 Decision Log line only |

## Out of scope

- Gating / authorization (LE, Red, Purple, ATO, officer procedures) — **deferred to owner**; not specified here.
- Product implementation in this PR.
- Settings Advanced / Packs as the **primary** UX (Daybreak is required).
- Backend worker-hook implementation in the Jarvis UX Daybreak ticket (that is D1, after CoS names it).
- `whole` embed of any upstream app (later RFC).
- HexStrike redesign or “HexStrike is the only cyber module.”
- RFC-0096–0104 Instagram children (open PR #271).
- Other Instagram pentest saves not in the six.
- Persona merge, voice/TTS, swarm / P4–P5 / model-stack.
- Architect rewrites of `SECURITY_AGENTS.md` / `BLUE_TEAM.md` / `JARVIS_2.0.md` / `PORTAL_UX.md` beyond the §59 ledger tick.
- Committing `/workspace/projects` or Windows `le-gated` clones.
- Exploit, PoC, payload, or attack-step documentation.

## Notes

- Source: Taco owner directive 2026-09-17 after RFC-0095. Addendum: **implement surface = Daybreak** (HUD / HexStrike-adjacent left-bar or suite panel); Jarvis UX owns `frontend/src`; D1 owns worker hooks later. These six were LE-gated archive clones; this RFC is the named product path for **module grouping + partial connectors**.
- Linux cloud VMs can unit-test discovery + enable flags and Daybreak panel wiring. Live subprocess / Open folder / Desktop HUD is Windows desktop sign-off.
- Implement launch (UX): Daybreak panel only; branch from `development`; `npm --prefix frontend run build` + lint; do not edit Architect spec docs; PR against `development`; do not merge other PRs (including #271). D1 worker hooks: separate named ticket.
