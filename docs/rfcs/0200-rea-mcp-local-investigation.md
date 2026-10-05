# RFC-0200: REA MCP local investigation (owner paths)

**Status:** accepted  
**Queue item:** (none — no §58 checkbox; implement for #542 cut stream)  
**Author:** Jarvis Architect  
**Date:** 2026-10-05

**Related:** [RFC-0198](0198-blue-re-lta-protected-folder.md) LTA extract dirs. [RFC-0197](0197-blue-red-purple-security-agents.md) license/target policy (no bypass). [RFC-0134](0134-mcp-usability-native-prefer.md) MCP session reuse, Connections, pin+adapter. [RFC-0086 Daybreak](0086-daybreak-blue-defensive-hexstrike.md) / [RFC-0196](0196-hexstrike-operator-chain-anzu-1.md) job status patterns (Connections/Modules only).

**Upstream (pin facts; do not invent APIs):** [morluto/rea](https://github.com/morluto/rea) · npm [`rea-agents`](https://www.npmjs.com/package/rea-agents) · MCP catalog identity `io.github.morluto/rea` (stdio launch remains `npx … mcp`).

Specs-only. **No ledger ticks.** **No** persona/WebGL/presence/morph/voice changes.

## Problem

Owners need Jarvis agents to **reverse-engineer local artifacts** (apps, binaries, ASAR, archives) on paths they control — without cloud upload, without bypassing Jarvis path grants, and without a second LTA unlock path. [Reverse Engineer Anything (REA)](https://github.com/morluto/rea) ships as a **local** Node MCP (`rea-agents`); Jarvis has MCP plumbing ([RFC-0134](0134-mcp-usability-native-prefer.md)) but no product contract for REA path policy, investigation allowlists, or coherence with LTA post-extract dirs ([RFC-0198](0198-blue-re-lta-protected-folder.md)).

## Decision

### 1. Product intent

Jarvis agents may call **REA MCP tools** to investigate **owner-named absolute local paths** under policy. Examples:

- “RE this binary at `D:\Samples\app.exe`”
- “Investigate the extract from LTA job `{id}`” (resolve to `data_dir()/lta-extract/{job-id}/` after RFC-0198 open succeeded)

REA is **tooling under owner policy** ([RFC-0197](0197-blue-red-purple-security-agents.md)); it does not bypass license modules or target registry. **Local-by-design:** REA does not host analysis upload; Jarvis must not proxy artifacts off-box for REA.

### 2. Integration shape

| Item | Rule |
| --- | --- |
| Package | Pin **`rea-agents`** in installer `mcp/package.json` (or equivalent preset) — **exact version at implement time** (upstream README example: `rea-agents@3.2.1`; re-check npm before land). |
| Launch | Stdio MCP registration in **Connections**, same preset pattern as email/WhatsApp ([RFC-0134](0134-mcp-usability-native-prefer.md)): |
| | `{"mcpServers":{"rea":{"command":"npx","args":["-y","rea-agents@PIN","mcp"]}}}` |
| Catalog key | Document MCP identity **`io.github.morluto/rea`** for Module Catalog / Connections labeling; runtime command stays `npx`. |
| Vendoring | **Do not** git-vendor `morluto/rea`. Prefer native MCP exposure + session reuse per RFC-0134. |
| Prerequisites | Node.js **22.19+** or **24.11+** per upstream. Deep native analysis may require **Hopper** and/or bring-your-own **Ghidra**; Windows Ghidra support is limited/unavailable upstream — document honestly; `rea doctor` is the provider truth source. |

### 3. Path policy (hard, fail-closed)

1. **Absolute paths only** from owner utterance, or resolved from an **already-approved** LTA job id → extract root under `data_dir()/lta-extract/{job-id}/` ([RFC-0198](0198-blue-re-lta-protected-folder.md)). LTA **must** open via RFC-0198 first; REA analyzes post-extract files without re-asking for keys/certs. **No** second unlock path.
2. **Jarvis-owned investigation roots:** set env **`REA_INVESTIGATION_INPUT_ROOTS_JSON`** — JSON array of absolute directory roots. Every owner-provided RE target path must resolve (after normalization) **under** one of these roots **and** under Jarvis `allowed_directories` / RFC-0079 owner grants (intersection, not union escape).
3. **LTA extract dirs** that already passed RFC-0198 path checks are eligible REA inputs even if not listed in `REA_INVESTIGATION_INPUT_ROOTS_JSON`, when referenced by job id or explicit path under that job dir.
4. If REA MCP is **enabled** for agent tools and `REA_INVESTIGATION_INPUT_ROOTS_JSON` is **unset or empty**, **deny** investigation calls (fail closed). Return honest error code **`path_not_allowed`** (and human-readable reason) for paths outside policy.
5. **Secrets:** never paste private keys, certs, or PKCS#7 blobs into chat/room; LTA key material stays on RFC-0198 vault/cert-store path only.

### 4. Approval gates

| Gate | Behavior |
| --- | --- |
| Enable REA MCP | Owner approval (existing Connections / tool-enable patterns; RFC-0110-style popup where applicable). |
| First investigation on a **new** root | Separate owner confirmation before adding root to `REA_INVESTIGATION_INPUT_ROOTS_JSON` or granting path. |
| Dynamic REA capabilities | Upstream envs such as `REA_PROCESS_EXECUTABLE_ROOTS_JSON`, `REA_PROCESS_WORKING_ROOTS_JSON`, `REA_BROWSER_SCENARIO_EXECUTABLE_ROOTS_JSON` — **off by default** in Jarvis. If exposed later, require **explicit** owner grants; Jarvis must **not** silently set upstream process/browser scenario envs when enabling base REA MCP. |

### 5. UI and honesty

- **No Astra surface:** no persona/WebGL/presence/morph/voice changes.
- Optional v1 UI: **Connections** status + **Module Catalog** / **Daybreak** job panel text **only** if matching existing RFC-0196/0086 patterns; otherwise backend + MCP-only is sufficient.
- Connections must **not** show “connected” when MCP `tools/list` fails (RFC-0134 honesty).

### 6. Implement anti-patterns

- Git-vendoring `morluto/rea` or claiming Windows Hopper/Ghidra parity beyond upstream
- Accepting relative paths or `..` escapes outside approved roots
- Enabling `REA_PROCESS_*` / browser scenario envs without explicit owner grant
- Using REA to bypass LTA workflow or license/target checks

## Acceptance criteria

Specs-only:

- [x] RFC-0200 accepted; upstream repo/npm/MCP launch cited without invented APIs
- [x] `REA_INVESTIGATION_INPUT_ROOTS_JSON` + fail-closed + `path_not_allowed` documented
- [x] LTA post-extract coherence with RFC-0198; no second unlock path
- [x] Approval gates + dynamic REA envs off-by-default documented
- [x] No Astra/persona/WebGL scope; REA not a license bypass (RFC-0197)

Implement follow-up:

- [ ] Pin `rea-agents@…` in `mcp/package.json` (or preset) + stdio MCP in Connections ([RFC-0134](0134-mcp-usability-native-prefer.md))
- [ ] Jarvis injects/validates `REA_INVESTIGATION_INPUT_ROOTS_JSON`; intersect with `allowed_directories` / grants
- [ ] LTA job id → extract path resolution for REA targets (RFC-0198 dirs only)
- [ ] Owner approval for enable REA MCP + first use per new root
- [ ] Unit tests for path allowlist / `path_not_allowed` / LTA extract resolution (`tests/test_rfc0200_*.py`)
- [ ] `python3 -m pytest`; if Connections/Modules UI touched, `npm --prefix frontend run build`
- [ ] **Desktop soak**: Node 22.19+; `rea doctor`; owner path under roots → MCP tool call succeeds; path outside roots fails closed

## Likely files

| Area | Paths |
| --- | --- |
| MCP / installer | `mcp/package.json`, preset JSON under `mcp/` or integrations setup |
| Backend | `backend/app/tools/mcp_runtime.py`, path policy helper (new), LTA job path resolver touch `backend/app/api/lta.py` |
| Frontend | `frontend/src/pages/Mcp.tsx`, Module Catalog / Connections only if status copy needed |
| Tests | `tests/test_rfc0200_*.py` |
| Docs | this RFC; optional `INTEGRATION_SPECS.md` row (Architect queue) |

## Out of scope

- blue.re partner spike ([RFC-0198](0198-blue-re-lta-protected-folder.md) §1) — separate from morluto REA
- Hosting REA analysis in cloud or Jarvis-side artifact upload
- Default-enabling process capture / browser scenario REA tools
- Persona morph, WebGL, voice, or Astra-owned surfaces
- Rewriting RFC-0198 LTA crypto workflow

## Notes

- Example npm pin in upstream README: `rea-agents@3.2.1` — implementers must verify latest compatible version on npm at land time.
- Cloud Linux agents can unit-test path policy; live REA MCP + Hopper/Ghidra is **desktop sign-off**.
- Queue hint for Architect: wire §58 / `#542` cut stream when implement merges.
