# RFC-0105: Cybersecurity module (six Instagram clones)

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent:** RFC-0095 Instagram collection ingest + Module Catalog Download.  
**Related (read only; do not rewrite):** RFC-0006 hierarchical workers. RFC-0007 domain/workspace packs. RFC-0009 runtime portability. RFC-0024 skill lifecycle. RFC-0078 / RFC-0086 HexStrike (existing defensive suite — **not** “HexStrike forever” as the only cyber surface). RFC-0090 optional-worker Install now. RFC-0094 Settings Advanced. `SECURITY_AGENTS.md` (related reading only).

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not edit `frontend/src/` or backend in this PR. Local clones belong under Architect’s `projects/` library — **not** committed here.

RFC numbers **0096–0104** are reserved by open [PR #271](https://github.com/Daan298261/Jarvis/pull/271) (Instagram child integrations). This RFC is **0105**. Do not reuse 0096–0104.

## Problem

RFC-0095 downloaded Taco’s Instagram-jarvis saves and defaulted six of them (Strix, Anthropic Cybersecurity Skills, Exploitarium, Pentagi, Claude-Red, Flowsint) to archive-only pending a named product RFC. The clones already exist on the Architect box and the Windows PC. There is no Module Catalog grouping, no per-tool enable/status UX, and no architecture for discovering those checkouts or attaching them as optional backends / skill packs / workers.

RFC-0095 did not specify how these six become a **module**. HexStrike (RFC-0078 / 0086) is the existing defensive suite; it is not the only cybersecurity surface Jarvis will ever have. Owner (Taco) directed these six into one cybersecurity module. This RFC covers **module surface + integration wiring**, not security-politics.

## Decision

Treat the six local clones as **one** Jarvis module in the Module Catalog / Packs (RFC-0095 Download + enable pattern). Module id: `cybersecurity`. They are optional backends, skill packs, and workers **inside that module** — not six unrelated orphan tools.

RFC-0095’s archive-only default is **superseded for these six named tools only**. Other unnamed Instagram pentest saves stay under RFC-0095 until a later named RFC. HexStrike stays the existing defensive suite **beside** this module; this RFC does not rewrite HexStrike, fold the six into HexStrike MCP, or declare HexStrike the permanent sole cyber UI.

### 1. Four-step pipeline (RFC-0095)

Skipping a step is a fail. For this module:

| Step | This RFC |
| --- | --- |
| **Download** | **Done.** Clones already on disk (table below). Re-fetch uses RFC-0095 `POST /api/modules/catalog/{id}/download` (allowlisted `source_url` only). |
| **Usefulness** | Primary bucket **`module`**; tag **`cybersecurity`**. Secondary tags per member (harness / skill_pack / library_backend / graph_ui) are allowed. |
| **Integrate** | **`partial`** — connectors into the `cybersecurity` module first (discover, enable, launch hook, skill-pack register, graph/UI entry). **`whole`** embed of any upstream app is optional later (separate RFC). |
| **Implement** | Named follow-up ticket after this spec lands. Ordinary workers do not start product wiring from a save alone. |

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

### 4. Module UX

Daybreak / Settings **Advanced** (RFC-0094 `advanced`) **or** Module Catalog / Packs (prefer extending the RFC-0095 catalog if the list stays small) shows **one Cybersecurity module** card, not six top-level Packs rows.

Per member, the card shows:

- Enable / disable (module master enable plus per-tool enable; disabled members are not launched or registered).
- Status (`missing` / `found` / `running` / …).
- Path to the local clone.
- **Open folder** when `local_path` exists.
- **Download** (RFC-0095) when the path is missing or the owner re-fetches.

Do not add a second HexStrike HUD. Flowsint gets its own graph/UI entry under this module (below). Deep-link `/packs` or `/settings/advanced` is enough; do not invent a seventh Settings group.

### 5. Architecture wiring (`partial` connectors)

This section is **wiring only**. It does **not** document exploits, PoCs, attack steps, payloads, recipes, or operator tradecraft. Implement tickets name start commands from each clone’s own README; this RFC does not copy them.

**Shared launch hook.** Reuse RFC-0090 job overlay (progress / error) and the HexStrike **process-supervisor shape** (Jarvis-owned subprocess, loopback bind, pid, start/stop, health) as a **generic module-worker supervisor** — not a HexStrike fork. Jarvis may stop only pids it started. Do not register any upstream MCP catalog wholesale. Do not pip-install owner-typed specs; clones are already on disk.

| Member | Role | Connector (v1 `partial`) |
| --- | --- | --- |
| `strix` | Agent harness + optional worker | Discover checkout; optional-worker / subprocess launch hook; **agent harness entry** so Jarvis can dispatch a bounded child worker (RFC-0006 / RFC-0009) whose cwd is the clone. |
| `anthropic-cybersecurity-skills` | Skill pack | Scan the clone for skill manifests (`SKILL.md` or equivalent). **Register as a skill pack** (RFC-0024 + existing `backend/app/agent/skills.py` / harness skill hints). Attach when the member is enabled. List pack **names** only in Jarvis UI. |
| `exploitarium` | Optional library backend | Discover checkout; optional filename/title index for retrieval. No copy of library bodies into Jarvis `docs/` or this RFC. |
| `pentagi` | Agent harness + optional worker | Same shape as Strix: subprocess launch hook + **agent harness entry** (bounded child worker, clone cwd). Optional local UI is open-folder / loopback embed later (`whole` is out of this RFC). |
| `claude-red` | Skill pack | Same as Anthropic Cybersecurity Skills: register the clone **as a skill pack**; attach when enabled. |
| `flowsint` | Graph / UI | **Graph/UI entry** on the module card (portal or Daybreak panel). Discover a local UI if the clone exposes one on loopback; otherwise Open folder. Not HexStrike HUD; not a PresenceHost / RFC-0069 rewrite. |

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

**Will not:** invent authorization / LE / Red / Purple / ATO gating rules or officer procedures. Rewrite HexStrike. Vendor upstream trees. Put exploit recipes, PoCs, attack steps, or payloads in this RFC or in Jarvis spec docs. Start product implementation in this PR. Reuse RFC numbers 0096–0104.

## Acceptance criteria

- [ ] Specs-only in this PR (no `frontend/src` / backend product edits; no `projects/` clones committed)
- [ ] Six tools named and grouped under module id `cybersecurity` (not six orphan catalog rows)
- [ ] Four-step pipeline specified: Download (done) → usefulness `module` / cybersecurity → integrate **`partial`** → implement (follow-up)
- [ ] Module UX specified: Settings Advanced or Module Catalog; per-tool enable, status, local path, open-folder; RFC-0095 Download for re-fetch
- [ ] Architecture wiring specified only: discovery, optional-worker / subprocess hooks, skill-pack register (Anthropic Cybersecurity Skills + Claude-Red), graph/UI entry (Flowsint), harness entry (Strix + Pentagi)
- [ ] HexStrike remains the existing defensive suite beside this module (RFC-0078 / 0086 not rewritten)
- [ ] No exploit recipes, PoCs, attack steps, or payload docs in this RFC
- [ ] Gating / authorization not invented here (see Out of scope)
- [ ] Light §59 Decision Log line only (no §57 rewrite, no new §58 checkbox)
- [ ] Implement follow-up (separate ticket): `python3 -m pytest`; if portal touched, `npm --prefix frontend run build` (and lint if TS changed)

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | `backend/app/api/modules.py` (RFC-0095 catalog) + `backend/app/modules/cybersecurity.py` (discover, enable, supervisor); reuse `backend/app/workers/install.py` job overlay and HexStrike supervisor **shape** from `backend/app/security/hexstrike.py` without folding into `/api/hexstrike`; skill-pack register via `backend/app/agent/skills.py` / `local_harness.py` |
| Frontend (implement PR only) | `frontend/src/pages/Packs.tsx` and/or Module Catalog; `frontend/src/settings/AdvancedSettingsPane.tsx`; `frontend/src/api.ts`; optional small `CybersecurityModuleCard` |
| Tests | `tests/test_rfc0105_*.py` — discovery roots, module grouping, enable flags, start/stop only Jarvis pids, download allowlist reuse |
| Docs | this RFC; `JARVIS_MASTER_PLAN.md` §59 Decision Log line only |

## Out of scope

- Gating / authorization (LE, Red, Purple, ATO, officer procedures) — **deferred to owner**; not specified here.
- Product implementation in this PR.
- `whole` embed of any upstream app (later RFC).
- HexStrike redesign or “HexStrike is the only cyber module.”
- RFC-0096–0104 Instagram children (open PR #271).
- Other Instagram pentest saves not in the six.
- Persona merge, voice/TTS, swarm / P4–P5 / model-stack.
- Architect rewrites of `SECURITY_AGENTS.md` / `BLUE_TEAM.md` / `JARVIS_2.0.md` / `PORTAL_UX.md` beyond the §59 ledger tick.
- Committing `/workspace/projects` or Windows `le-gated` clones.
- Exploit, PoC, payload, or attack-step documentation.

## Notes

- Source: Taco owner directive 2026-09-17 after RFC-0095. These six were LE-gated archive clones; this RFC is the named product path for **module grouping + partial connectors**.
- Linux cloud VMs can unit-test discovery + enable flags. Live subprocess / Open folder / Desktop path is Windows desktop sign-off.
- Implement launch: implement this RFC only (module catalog grouping + connectors); branch from `development`; pytest + frontend build if UI; do not edit Architect spec docs except the §59 tick already in the specs PR; PR against `development`; do not merge other PRs (including #271).
