# CoS review notes — integration / Jarvis 1.4 completed work

**Reviewer:** Cursor cloud (code review only; no product-code changes)  
**Base:** `development` tip `a8cacae` (2026-09-17)  
**Compared to:** `main` `25825e5` (1.3.13 via #268)  
**Open PRs at review time:** none (this notes PR excepted)

**Taco mid-review clarify (2026-09-17):** bulk Instagram/catalog integration was **not** supposed to be in Jarvis 1.4 except the most interesting ones. The first pass of this review over-counted 0095–0104 as “1.4 incomplete.” That framing is **wrong**. Recut below.

No one-line safety fix was applied. Operator-path issues are worse than one line; they are reported rather than drive-by patched.

---

## 0. 1.4 scope (authoritative for this review)

### In 1.4.0 cut

| Item | On this tip |
| --- | --- |
| **RFC-0107 Obsidian brain** | Specs-only (#280) |
| **RFC-0108 phone offline AI** | Specs-only (#280) |
| **RFC-0109 media upload** | Specs-only (#280) |
| **RFC-0110 approval modal** | Not in tree (in flight / unnamed). Existing `PermissionPrompt` is not this ticket |
| **HexStrike / Daybreak / cyber already in flight** (RFC-0105, RFC-0106, Daybreak HexStrike UX) | 0105 product code; 0106 **backend only**; Daybreak operator HUD **not started** |
| **`JARVIS_1.4_SPECS` core** | **File missing on `development` and `main`** (GitHub code search empty). 1.4 core has no canonical spec file in-repo |
| **Runtime already in flight for the cut** (`n_keep`, empty-chat/`reasoning_content`, no silent SAPI) | Empty-chat + SAPI on `development` *and* `main` (#266/#259). `n_keep` **not** in llama-server argv |

### Out of 1.4 — later INTEGRATION queue (not “1.4 incomplete”)

Park these. Do not block a 1.4 cut on them. Do not describe them as missing 1.4 work.

- RFC-0095 Module Catalog / Instagram ingest umbrella
- RFC-0096–0104 reel children (ComfyUI, stitch, Browser-Use, OpenViking, Firecrawl, Pipecat, LocalSend, RuView, persona pack)
- RFC-0098 Browser-Use deepen **including** backend #273 (interesting, but not a 1.4 gate)
- `INTEGRATION_SPECS.md` as a living later-queue index (it also lists 0107–0109, which *are* 1.4)

0105 reused RFC-0095 download plumbing. That reuse is in-flight cyber, not a reason to pull the whole catalog program into 1.4.

---

## 1. What is actually done — 1.4 slice only

**Precision:** “completed” = product code + tests on `development`. Specs and HUD shells that fake rows are not completed.

### COMPLETED IMPLEMENTATION (1.4-relevant product code)

| Ticket | PRs | Landed | Gap vs 1.4 bar |
| --- | --- | --- | --- |
| **RFC-0105 cybersecurity** | #272 spec, #274 HUD, #277 backend, #278 tick | Module `cybersecurity` (6 members), Daybreak left-bar, `/api/modules/catalog/cybersecurity/*`, discovery, skill-pack names, generic supervisor | Soft-fail static shell leftover; start often needs `jarvis-module.json` clones don’t have; no loopback-bind guarantee; live Windows open-folder/subprocess unsigned |
| **RFC-0106 HexStrike operator — backend** | #276 spec, #279 backend | `/api/hexstrike/tools`, `/operate`, `/jobs`, MCP register hook, `hexstrike_operator` chat tool, catalog beyond six Blue enums, install jobs, job/artifact store | **Daybreak operator HUD not landed** (still 0086 five-action shell). RFC still `accepted`. Help still “MCP always rejected” |
| **1.3.13 owner-chat / SAPI** | #266 (and #259 on `main`) | `reasoning_content` when `content` empty; Kokoro refuses silent SAPI | Not a 0105/0106 regression. `n_keep` still absent |

Settings IA (#267) is already on `main` (1.3.13). Treat as prior, not a 1.4 deliverable.

### 1.4 SPECS-ONLY / NOT STARTED (these *are* 1.4 incomplete)

| Item | Status on tip |
| --- | --- |
| **RFC-0107 Obsidian brain** | Accepted spec (#280). No vault bind, watch, graph retrieve/act, or picker |
| **RFC-0108 phone offline AI** | Accepted spec. No on-device runtime / sync |
| **RFC-0109 media upload** | Accepted spec. Daybreak composer still text+Speak; companion attach is the old 64 MiB blob |
| **RFC-0110 approval modal** | **No RFC file, no PR.** HexStrike path auto-grants and skips the existing Always-allow buttons |
| **Daybreak HexStrike operator UX** | Explicitly not in #279. HUD subtitle still “defensive gateway · local and owner-attested only” |
| **`JARVIS_1.4_SPECS` core** | File does not exist on either branch. Cannot audit 1.4 core vs code until Architect lands it |
| **`n_keep < n_ctx`** | llama-server `build_args` has `--ctx-size` only |

### Later INTEGRATION queue (landed or spec’d; not a 1.4 scorecard)

| Item | Note |
| --- | --- |
| RFC-0098 Browser-Use deepen | Backend #273 is real; RFC file still says unimplemented. **Later queue**, not 1.4 incomplete |
| RFC-0095–0104 except 0105 | Specs on `development` via #270/#271. Later queue |
| `INTEGRATION_SPECS.md` | Useful index; stale on 0106 (“specs-only”) and 0098. Architect hygiene, not a 1.4 gate |

### Branch drift

`main` = 1.3.13. 0105/0106/0107–0109 live only on `development`. Promoting today would ship HexStrike operator HTTP/MCP **without** operator HUD and **without** Obsidian/phone/media/0110. Still do not cut 1.4.0 from this tip — because **in-scope 1.4 work is unfinished**, not because Instagram RFCs are unfinished.

---

## 2. Specs quality (1.4 items)

### Contradictions

1. **RFC-0106 vs RFC-0086 vs help vs HUD.** 0106 wins over Blue-only / no-MCP. Help `hexstrike-blue` still says MCP is always rejected and only typed defensive actions exist. HUD matches 0086. Three product stories. **1.4 blocker.**
2. **RFC-0106 status vs code.** Honest: **backend CODE PRESENT / HUD not started.** INTEGRATION_SPECS calling 0106 specs-only is stale (hygiene; the HUD gap is the real 1.4 issue).
3. **RFC-0105 ticked implemented** vs HUD “until D1 lands” static six-row shell (`staticCybersecurityModule()`). D1 (#277) already landed. **1.4 should-fix / residual stub.**
4. **RFC-0105 allowed “stub catalog for UX”** vs Taco no-stubs bar. That RFC sentence is the defect; the shell survived D1.
5. **No invented gating** vs Daybreak still requiring attested Blue scopes for click-run, while `operate()` HTTP/MCP does not require a scope.
6. **`JARVIS_1.4_SPECS` missing** while 0107–0109 exist as RFCs. 1.4 core (whatever is *not* those RFCs) has no in-repo contract. Review cannot confirm voice/`n_keep`/approval as specified vs accidental.

RFC-0098 unchecked boxes after #273 belong on the **later INTEGRATION queue**, not this contradiction list as a 1.4 fail.

### Stubs / soft-fail (1.4 surfaces)

- Cyber HUD: “Module catalog API is not available yet… until D1 lands.”
- Cyber start: “Add jarvis-module.json…” when clones have no start metadata — hole, not a harness.
- HexStrike HUD: health + five Blue actions; discovered catalog fetched then **ignored**. RFC-0106: health-only UI is a **fail**.
- `operator_ready` = MCP ok AND catalog longer than Blue enums. MCP down blocks non-`defensive:` operate even if HTTP tools exist.
- `hexstrike_compat.py` mitmproxy stubs: host-boot, not 1.4 product UX, still a stub on the operator path.

Voice-catalog “system TTS until backend lands” is leftover **prior** UX, not 1.4 integration. Keep off the 1.4 must-fix list unless `JARVIS_1.4_SPECS` (when filed) says otherwise.

### Missing Always-allow popup (RFC-0110 — in 1.4)

`PermissionPrompt.tsx` already has **Allow once / Always allow / Don’t allow**. HexStrike **bypasses** it:

- `cyber.hexstrike` default `ask`
- `/api/hexstrike/operate` and `HexStrikeOperatorTool` call `operator_intent_grant(..., "allow_session")` on `ask`
- Daybreak click or chat tool = silent session grant

RFC-0110 is not in the repo. Shipping HexStrike operator without it means 1.4 would ship **always-on grant**, not an on-demand modal.

### Obsidian-brain / on-demand tool-search (RFC-0107 — in 1.4)

0107 is a solid vault/graph/sync spec (canonical Markdown, hop-capped retrieve, no full-vault inject). Gaps vs Taco’s bar, to lock in the implement ticket:

- Spec does not say **on-demand tool-search** (search/select tools at need; do not stuff schemas).
- Implementers could “complete” 0107 as vault-path-saved / retrieval-always-empty — RFC already forbids that; keep it loud.
- **Related 1.4 bleed (cyber/HexStrike already on the tip):** `load_skill_blocks()` injects every `module:cybersecurity:*` hint into the harness prompt; HexStrike `MCP.refresh()` can dump wholesale tools into mixed/long-horizon tasks (`hexstrike_operator` enabled by default). That is prompt bloat **now**, not a later Instagram problem.

---

## 3. Unintended results (1.4 in-flight code)

### A. Prompt bloat / `n_keep` (1.4 runtime)

- llama-server argv: `--ctx-size`, **no `--n-keep`**. In-flight fix still required; HexStrike MCP + cyber skill hints make it worse.
- `GET /api/hexstrike` (HUD poll **every 2.5s**) → `sync_operator_surface(register_mcp=True)` while running. MCP churn + schema instability.
- `hexstrike_operator` `status` dumps catalog into the tool result (12k truncate).
- Cyber catalog GET re-walks clones every 5s HUD poll.

### B. Silent SAPI / empty `content`

- #266/#259 hold. Kokoro does not fall through to SAPI; `reasoning_content` fills empty chat.
- Not regressed by 0105/0106. Do not claim 1.4 “fixed voice.” Residual: voice-catalog soft shell (prior; not 1.4 gate).

### C. Always-on grant vs on-demand popup

- HexStrike HTTP + chat tool auto `allow_session`.
- Mixed/long-horizon tasks get `hexstrike_operator` without `request_tools`.
- This is exactly why **0110 is in 1.4** and must land (or HexStrike operate stays dark).

### D. HexStrike operate / install security

Loopback pin/audit remain (good). New surface:

1. `operator_post_allowed`: any `api/tools/<name>` except substring denylist; HTTP rows `additionalProperties: True`.
2. `pip:` install of any `[a-z0-9._-]+` package. Missing HexStrike home → **`sys.executable`** (Jarvis’s interpreter).
3. Chat tool `install_dependency` / `operate` after silent grant.
4. MCP wholesale register on start **and** on status poll.
5. `/stop` does not call `_operator_permission`.
6. Test `test_mcp_registration_refuses_non_loopback_host` is vacuous (no `hexstrike_mcp.py` in tmp → `[]`, not a loopback check).

### E. RFC-0105 supervisor

- Executes checkout `jarvis-module.json` argv or `start.sh`/`main.py` **without forcing loopback bind**.
- Manifest health URL need not be `127.0.0.1`; HTTP `<500` = healthy.
- 1.4 cut risk if those clones are on the owner PC (they are, per RFC). Not an Instagram-queue deferral — this code is already on `development`.

### F. Frontend shells / dual APIs (cyber vs HexStrike)

- Cyber static catalog on **any** catalog GET failure.
- HexStrike HUD caps tools at 48; TS types omit `catalog` / `operator` / `operator_jobs`; no operate client helper.
- Dual job lists; HUD only shows six Blue `managed_jobs`.
- `hexstrike_defensive` is Blue-role-gated; `hexstrike_operator` is general and stronger.
- Gateway `/upstream/{path}` POST now uses widened operator rules.

### G. Product lie

HUD + help tell the owner the suite is defensive-only while `/operate` and MCP are live.

---

## 4. Punch list (recut)

### Must-fix before a 1.4.0 cut

1. **Do not promote this tip as 1.4.0.** In-scope gaps: Daybreak HexStrike UX, 0107–0109 product code, RFC-0110, `JARVIS_1.4_SPECS` file, `n_keep`. Instagram 0095–0104 are **not** the reason.
2. **Stop MCP register on status poll.** `GET /api/hexstrike` must not `register_mcp=True` every 2.5s.
3. **Land RFC-0110 (or equivalent) and remove silent `operator_intent_grant` on operate/install.** `ask` must ask (Always-allow / once / deny).
4. **Bind `pip:` / winget to the discovered catalog**; never fall back to `sys.executable`.
5. **Daybreak HexStrike UX must match the backend** (full catalog, operate, jobs/logs, no 48-cap, kill defensive-only copy) **or** keep `/operate` + MCP dark. Health-only HUD + live operate is the RFC-0106 fail.
6. **Strip cyber HUD “until D1 lands” static shell.**
7. **`n_keep < n_ctx`** before 27B with MCP/skill/catalog bloat.
8. **Implement 0107 / 0108 / 0109** as named tickets (full intent, no stub vault / canned offline / attach-chip-that-never-ingests).
9. **Architect: land `JARVIS_1.4_SPECS` on `development`** (or point at the real file). Until then 1.4 “core” is unauditable. Also mark RFC-0106 backend-implemented / HUD-open; rewrite help `hexstrike-blue`.

### Should-fix (1.4 in-flight cyber/HexStrike)

- Do not inject all `module:cybersecurity:*` names into every harness prompt; on-demand `SKILL.md` only.
- Keep `hexstrike_operator` off mixed-task default exposure; require HexStrike-suite context / `request_tools`.
- Loopback-enforce module-worker health/bind.
- Fix vacuous MCP loopback test.
- Validate `operate()` args against discovered schema.
- Hard miss when `jarvis-module.json` is absent.
- Fire-and-forget `create_task(supervisor.stop())` from the sync enable handler.
- RFC-0107 implement spec addendum: on-demand retrieve **and** on-demand tool-search; never dump vault or HexStrike MCP list into the system prompt.

### Later INTEGRATION queue (not 1.4)

- Tick RFC-0098 implemented (backend #273 already landed).
- Browser-Use frontend status copy.
- RFC-0095–0104 product tickets (Comfy, stitch, Pipecat, OpenViking, Firecrawl, LocalSend, RuView, persona hold).
- `INTEGRATION_SPECS.md` stale 0098/0106 status lines.
- Flowsint graph embed (0105 nice-to-have vs open-folder).
- Collapse `managed_jobs` / `operator_jobs` into one timeline (HexStrike HUD ticket can take this).

---

## 5. Verdict (1.4-scoped)

**0105 (in 1.4):** partial connectors + Daybreak panel are real; leftover soft-fail shell and checkout spawn remain. Desktop sign-off still required.

**0106 + Daybreak UX (in 1.4):** backend is a real operator surface; **owner-visible HUD is still 0086**; new surface auto-grants + pip-installs + polls MCP. Highest-risk unintended result on this tip.

**0107–0109 (in 1.4):** specs-only. Required for the cut; not started in product code.

**0110 (in 1.4):** missing. Current HexStrike path is the anti-pattern the modal is supposed to replace.

**`JARVIS_1.4_SPECS` (in 1.4):** missing from both branches. Architect gap, not an implementer miss.

**0095–0104 / 0098 (out of 1.4):** later INTEGRATION queue. #273 Browser-Use deepen is extra credit on `development`, not a 1.4 hole.

**1.3.13 empty-chat + SAPI:** already on `main`; not regressed.

Do not merge this review PR. Do not merge `development` → `main` as 1.4 until the **in-scope** must-fix list is owned. Do not wait on Instagram catalog RFCs for that cut.
