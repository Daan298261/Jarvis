# CoS review notes — integration / Jarvis 1.4 completed work

**Reviewer:** Cursor cloud (code review only; no product-code changes)  
**Base:** `development` tip `a8cacae` (2026-09-17)  
**Compared to:** `main` `25825e5` (1.3.13 via #268)  
**Open PRs at review time:** none  
**In-flight (not on this tip):** Daybreak HexStrike UX, RFC-0110 approval modal, `n_keep ≥ n_ctx` llama-server fix — none of these exist as files, RFC numbers, or open PRs on `development`/`main`.

**Precision rule used here:** “completed” means product code + tests on `development`. Specs, RFC ticks, and HUD shells that degrade to static rows are called out separately.

No one-line safety fix was applied. Several operator-path issues are worse than one line; they are reported below rather than drive-by patched.

---

## 1. What is actually done in code (vs specs-only)

### COMPLETED IMPLEMENTATION (product code on `development`)

| Ticket | PRs | What landed | What did *not* land |
| --- | --- | --- | --- |
| **RFC-0105 cybersecurity module** | #272 spec, #274 HUD, #277 backend, #278 RFC tick | Module id `cybersecurity` with six members; Daybreak left-bar panel; catalog API under `/api/modules/catalog/cybersecurity/*`; enable flags; discovery roots; skill-pack name register; generic subprocess supervisor; RFC-0095 download reuse | Live Windows open-folder / subprocess; `jarvis-module.json` start metadata in the clones (not in git); Flowsint graph embed; real harness dispatch beyond “start this argv” |
| **RFC-0106 HexStrike operator — backend only** | #276 spec, #279 backend | `/api/hexstrike/tools`, `/operate`, `/jobs`, MCP register hook, `hexstrike_operator` chat tool, catalog beyond six Blue enums, host-tool/pip install jobs, job/artifact store under `data_dir()/hexstrike/jobs` | **Daybreak operator HUD** (still RFC-0086 five-action shell); RFC not ticked `implemented`; help topic still “MCP always rejected” |
| **RFC-0098 Browser-Use deepen — backend** | #273 | Session reuse, structured results, `network.internet`/`network.local` gates, Playwright remains default | RFC file still says “spec’d, not implemented”; no frontend status-copy pass; live Browser Use = desktop sign-off |
| **RFC-0094 settings IA** | #265 spec, #267 UI, #269 tick | Settings submenu groups (voice / appearance / models / network / integrations / advanced) | Not 1.4-specific; already on `main` via #268 |
| **1.3.13 runtime** | #266 | Owner-chat `reasoning_content` when `content` empty; hotswap slot mismatch; Kokoro refuses silent SAPI fallback | `n_keep` still absent from llama-server argv; live GPU sign-off not done here |
| **RFC-0092 / #259** | already on `main` | Neural TTS default; Kokoro chain does not fall through to SAPI | Voice-catalog frontend still has “catalog not available yet → system TTS” soft shell |

### SPECS-ONLY (do not treat as shipped)

| Item | Where | Status on tip |
| --- | --- | --- |
| **INTEGRATION_SPECS.md** + **RFC-0107 Obsidian brain** | #280 | Accepted specs. No `obsidian_vault.py`, no vault picker, no graph retrieve/act |
| **RFC-0108 phone offline model** | #280 | Accepted specs. No on-device GGUF runtime |
| **RFC-0109 media/file/video upload** | #280 | Accepted specs. Daybreak composer still text+Speak; companion attach is the old 64 MiB blob |
| **RFC-0095–0104 reel children** except 0098 backend / 0105 | #270/#271 | Specs. 0096/0097/0099–0104 unimplemented |
| **JARVIS_1.4_SPECS** | — | **File does not exist on `development` or `main`.** 1.4 intent currently lives as `INTEGRATION_SPECS.md` + RFC-0105–0109 on `development` only |
| **RFC-0110 approval modal** | — | Not in tree. Existing `PermissionPrompt` already has Allow once / Always allow / Don’t allow |
| **Daybreak HexStrike operator UX** | — | Explicitly not in #279. HUD copy still “defensive gateway · local and owner-attested only” |
| **`n_keep ≥ n_ctx`** | — | llama-server `build_args` sets `--ctx-size` only; no `--n-keep` |

### Branch drift `development` vs `main`

`main` is a 1.3.13 cut (`#268`). All of 0105/0106/0098/0107–0109 and `INTEGRATION_SPECS.md` are **development-only**. Promoting `development` → `main` today would ship HexStrike operator HTTP/MCP **without** the Daybreak operator UI and without 1.4 Obsidian/phone/media. Do not cut 1.4.0 from this tip.

`INTEGRATION_SPECS.md` (#280, merged minutes after #279) still labels RFC-0106 “accepted (specs-only)” and RFC-0098 as RFC-only. That is already stale versus the tree.

---

## 2. Specs quality

### Contradictions

1. **RFC-0106 vs RFC-0086 vs help vs HUD.** RFC-0106 says it **wins** over Blue-only enum / no MCP / no command proxy. Help topic `hexstrike-blue` still says “upstream MCP registration are always rejected” and “only listed typed defensive actions.” HUD subtitle and “Run defensive action” enum match 0086, not 0106. Three product stories at once.
2. **RFC-0106 status vs code.** RFC remains `accepted` with implement checkboxes open; backend #279 is on the tip; INTEGRATION_SPECS still says specs-only. Honest status is **backend CODE PRESENT / HUD not started**.
3. **RFC-0105 vs its own UX copy.** RFC ticked implemented. HUD still tells the owner “actions stay disabled until D1 lands” when the catalog GET fails, and keeps a **static six-row shell** (`staticCybersecurityModule()` in `frontend/src/api.ts`).
4. **RFC-0105 “stub catalog is enough for UX”** vs Taco “no stubs / no soft-fail ever.” The RFC explicitly allowed a read-only/stub catalog for the UX ticket. That language shipped into the panel. D1 then landed, but the soft-fail shell was not removed.
5. **RFC-0098** implement boxes still unchecked after #273.
6. **No invented gating** (0105/0106) vs leftover Blue-scope attestation UI that is still the only way to click-run anything in Daybreak. Backend `operate()` does not require an attested scope for `http:`/`mcp:` capabilities.

### Stubs / soft-fail language that violate Taco’s bar

- Cyber HUD: “Module catalog API is not available yet… until D1 lands.”
- Cyber start: if checkout has no `jarvis-module.json` / heuristic entry, API returns *“No start metadata found. Add jarvis-module.json…”* — a documented hole, not a real harness.
- HexStrike HUD: health + five Blue actions; discovered catalog is fetched (status JSON) then **ignored**. RFC-0106: “Half-shell health-only UI … is a fail.”
- Voice picker: “Speech still uses your system TTS until the backend catalog lands.”
- `hexstrike_compat.py` still stubs mitmproxy so the reviewed server can bind. Different class of stub (host boot), but it is still a stub on the operator path.
- `operator_ready` is `mcp_ok AND catalog > len(CAPABILITIES)`. MCP failure blocks non-`defensive:` operate even when HTTP tools exist.

### Missing Always-allow popup

`frontend/src/chat/PermissionPrompt.tsx` already has **Allow once / Always allow / Don’t allow** (and voice “Always allow”). HexStrike **bypasses** that popup:

- `cyber.hexstrike` default is `ask`.
- `/api/hexstrike/operate` and `HexStrikeOperatorTool._ensure_permission` call `operator_intent_grant(..., "allow_session")` whenever status is `ask`.
- Any Daybreak click or chat tool call is treated as the grant. The owner never sees Always-allow vs once vs deny for operate/install.

That is the opposite of RFC-0110’s likely intent (on-demand modal, not a silent session grant). RFC-0110 is not in the repo.

### Missing Obsidian-brain / on-demand tool-search intent

RFC-0107 is a solid vault/graph/sync spec (canonical Markdown, hop-capped retrieve, no full-vault inject). Gaps vs Taco’s stated bar:

- No **on-demand tool-search** (search/select tools at need instead of stuffing schemas). `request_tools` exists for the agent loop, but INTEGRATION_SPECS / 0107 do not bind Obsidian (or HexStrike MCP) to that pattern.
- Cyber skill packs are **not** on-demand: `load_skill_blocks()` appends every `module:cybersecurity:*` hint to the harness system prompt whenever packs are registered.
- HexStrike MCP `MCP.refresh()` registers upstream tools into the Jarvis MCP runtime; mixed/long-horizon tasks can then receive **every enabled tool** including `hexstrike_operator` (`enabled: True` by default) plus MCP schemas.

---

## 3. Unintended results / regressions

### A. Prompt bloat / `n_keep` risk (must-fix before any 27B cut that uses this tip)

- llama-server argv (`backends.py` `build_args`) has `--ctx-size` and **no `--n-keep`**. The in-flight `n_keep ≥ n_ctx` fix is still required; this tip can only make it worse.
- `GET /api/hexstrike` (HUD poll **every 2.5s**) calls `sync_operator_surface(register_mcp=True)` while the suite is running. That re-registers HexStrike MCP and rewrites `catalog.json` on a health poll. Unintended: MCP process churn, tool-schema instability, extra tokens if those tools leak into the next chat turn.
- `hexstrike_operator` `status` dumps the full snapshot + catalog into the tool result (truncated at 12k, still large).
- Cyber `GET /api/modules/catalog/cybersecurity` re-walks clones (`rglob` SKILL.md up to 500; Exploitarium index 200 files) every 5s HUD poll.
- Owner-chat empty-content fix (#266) is on this branch and on `main`. New 1.4 surfaces were not wired through that path (HexStrike jobs do not speak). Residual risk is **context** (catalog/MCP/skills), not the 1.3.13 empty-reply bug itself.

### B. Silent SAPI / TTS fallthrough

- Kokoro/Chatterbox synthesis **does** refuse SAPI fallback (`synthesize.py`). Good; #266/#259 hold.
- Soft path remains: `primary_tts_backend()` still returns `sapi` if Kokoro is disabled; voice-catalog UI still advertises system TTS when the catalog GET fails; `engine_chain_for_profile` for unknown engines returns `["system"]`.
- Not a new 0105/0106 regression. Do not claim 1.4 “fixed voice.”

### C. Empty chat `content` vs `reasoning_content`

- Covered by `tests/test_reasoning_content_chat.py` and `completion_text.py`. Landed in #266. No evidence 0105/0106 rebroke it (those modules do not touch owner-chat).

### D. Always-on approval gate vs on-demand popup

- HexStrike HTTP + chat tool auto-grant `allow_session` (see above). Computer-use permissions page still has Always allow as a **settings** control, not a per-operate modal.
- Mixed/long-horizon tasks get `hexstrike_operator` without `request_tools` because it is in the default enabled registry and `_enabled_native()` returns every enabled tool.

### E. Security — HexStrike operate / install

Keep loopback pin/audit (good). New surface is the problem.

1. **`operator_post_allowed` allows any `api/tools/<name>`** except substring tokens (`command`, `payload`, `exploit`, `python`, `shell`, …). HTTP catalog rows use `additionalProperties: True`. `operate()` forwards arbitrary JSON to loopback. Token filter is a name denylist, not a capability allowlist. `api/tools/payload-builder` is blocked; `api/tools/custom_tool_beta` is allowed by tests.
2. **`pip:` install is not catalog-bound.** `install_dependency_by_id("pip:whatever")` installs any `[a-z0-9._-]+` package. If HexStrike home is missing, `_hexstrike_python()` uses **`sys.executable`** — Jarvis’s own interpreter.
3. **Chat tool can `install_dependency` / `operate` after silent session grant.** Combined with (1)(2).
4. **MCP wholesale register** into Jarvis MCP runtime when suite is up (and on every status poll).
5. **`_operator_permission` on GET-less mutate routes** auto-grants; `/stop` does not even call it.
6. Test `test_mcp_registration_refuses_non_loopback_host` is **vacuous**: `build_hexstrike_mcp_server(tmp)` returns `[]` because `hexstrike_mcp.py` is absent, not because `0.0.0.0` is rejected. If the script exists, non-loopback **raises** `ValueError` uncaught.

### F. Security — RFC-0105 supervisor

- `resolve_start_spec` executes `jarvis-module.json` `start`/`command` argv, or `start.sh` / `main.py`, **without forcing loopback bind**. Health URL from the manifest is not required to be `127.0.0.1`.
- `_wait_for_health` treats any HTTP status `< 500` as healthy, including 401/404 on a non-loopback URL if someone put one in the JSON.
- This is “partial connector” as spec’d, but it is a real process spawn of third-party checkouts (Strix, Pentagi, Flowsint) with no ATO/LE gate — which matches owner “don’t invent gating,” and is still a 1.4 cut risk if those clones are present.

### G. Frontend soft-fail shells

- Cyber static catalog on any catalog GET failure (not only 404).
- HexStrike HUD caps tool names at **48** (`toolEntries(...).slice(0, 48)`). RFC-0106: do not silently cap the operator out of the catalog.
- HexStrike TS types (`HexStrikeStatus`) have no `catalog` / `operator` / `operator_jobs`. Extra JSON is dropped. No `operateHexStrike` client helper exists.

### H. Catalog vs HexStrike API merge conflict

Two parallel cyber surfaces, as spec’d (siblings) — good. Accidental coupling:

- Status payload still mixes `capabilities` (six Blue enums) + `catalog` (discovered) + `managed_jobs` + `operator_jobs`. HUD only renders `capabilities` + `managed_jobs`.
- `hexstrike_defensive` remains Blue-role-gated; `hexstrike_operator` is general and more powerful. An owner on a conversation task can drive HexStrike without a Blue role.
- Gateway `/upstream/{path}` now uses the widened `operator_post_allowed` POST rules, so the old proxy is no longer six-enum-only.

### I. RFC-0106 Daybreak copy still the capability ceiling

HUD + help still tell the owner the suite is defensive-only while `/operate` and MCP are live. That is an **unintended product lie**, not just missing UX.

---

## 4. Punch list

### Must-fix before a 1.4.0 cut

1. **Do not promote this tip to `main` as 1.4.0.** Backend HexStrike operator is live; HUD/help still describe RFC-0086; Obsidian/phone/media are specs-only.
2. **Stop treating HTTP status polls as MCP register.** `GET /api/hexstrike` must not `register_mcp=True` every 2.5s. Register on start/sync only.
3. **Remove silent `operator_intent_grant` on operate/install.** Show the existing Always-allow / once / deny popup (or land RFC-0110). Default `ask` must actually ask.
4. **Bind `pip:` / winget install to the discovered catalog** and never fall back to `sys.executable`.
5. **Daybreak HexStrike UX must match the backend** (full catalog, operate, jobs/logs/artifacts, no 48-cap, kill “defensive-only” copy) **or** the operator routes must stay dark until that HUD exists. Shipping HTTP operate with a five-enum panel is the RFC-0106 fail condition.
6. **Strip cyber HUD “until D1 lands” static shell.** Catalog API is on the tip; failure should error, not fake six disabled rows.
7. **Land `n_keep` correctly (`n_keep < n_ctx`)** before loading 27B with MCP/skill/catalog bloat. Not on this tip.
8. **Reconcile specs:** tick RFC-0098 implement; mark RFC-0106 “backend implemented / HUD open”; fix INTEGRATION_SPECS stale 0106/0098 lines (Architect). Help topic `hexstrike-blue` is now wrong.

### Should-fix

- Do not inject all `module:cybersecurity:*` skill names into every harness prompt; honor on-demand load of the relevant `SKILL.md`.
- Keep `hexstrike_operator` off mixed-task default exposure; require `request_tools` / HexStrike-suite context (RFC-0106 §5).
- Enforce loopback on module-worker `health_url` and bind; refuse non-loopback manifests.
- Fix vacuous MCP loopback unit test; catch `ValueError` from `build_hexstrike_mcp_server`.
- `operate()` HTTP schema `additionalProperties: True` is not “validated against discovered schema.”
- RFC-0105 start without `jarvis-module.json` should be a hard, actionable miss (clone README), not a soft “add this file.”
- Voice catalog “system TTS until backend lands” leftover.
- `set_member_enabled` fire-and-forget `loop.create_task(supervisor.stop())` from a sync handler.

### Nice

- RFC-0107: add an explicit “on-demand retrieve + on-demand tool-search; never dump vault or HexStrike MCP list into the system prompt” paragraph so implementers cannot “complete” it as path-saved/empty-retrieve.
- Flowsint graph entry (0105) is open-folder only.
- Browser-Use frontend status copy (0098 likely files).
- Collapse dual job lists (`managed_jobs` vs `operator_jobs`) in one HUD timeline.
- `JARVIS_1.4_SPECS.md` does not exist; either create it on `development` (Architect) or stop referring to it — today the index is `INTEGRATION_SPECS.md`.

---

## 5. Verdict

**0105:** implemented at the “partial connector / Daybreak panel” bar, with leftover UX soft-fail and unsafe-ish subprocess heuristics. Desktop sign-off still required.

**0106:** backend is a real operator surface (not a mock), **but the product the owner sees is still the 0086 health shell**, and the new surface auto-grants + pip-installs + polls MCP. That is the highest-risk unintended result on this tip.

**0098:** backend deepen is real; RFC/index still pretend it is specs-only.

**0107–0109 / INTEGRATION_SPECS / 1.4 Obsidian-brain / phone offline / media upload:** specs-only. Not 1.4.0 completable from this code.

**1.3.13 empty-chat + SAPI:** already on `main`; not regressed by the cyber/HexStrike batch.

Do not merge this review PR. Do not merge `development` → `main` as a 1.4 cut until must-fix 1–8 are owned.
