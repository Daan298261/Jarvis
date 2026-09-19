# CoS review notes — integration / Jarvis 1.4 completed work

**Reviewer:** Cursor cloud (code review only; no product-code changes)  
**Base:** `development` tip `69eebd7` (2026-09-17, includes Daybreak HexStrike UX **#283**)  
**Compared to:** `main` `25825e5` (1.3.13 via #268)  
**Prior notes revision:** scored HUD against `a8cacae` (pre-#283). This amend treats Daybreak operator console as **landed product code**, not “not started.”

**Taco mid-review clarify (2026-09-17):** bulk Instagram/catalog integration was **not** supposed to be in Jarvis 1.4 except the most interesting ones. RFC-0095–0104 are a later INTEGRATION queue, not “1.4 incomplete.”

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
| **HexStrike / Daybreak / cyber already in flight** (RFC-0105, RFC-0106, Daybreak HexStrike UX) | 0105 product code; 0106 **backend (#279) + Daybreak operator console (#283)**; RFC file still `accepted`; help topic still 0086; desktop sign-off open |
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
| **RFC-0106 HexStrike operator** | #276 spec, #279 backend, **#283 Daybreak HUD** | Backend operator routes + `hexstrike_operator` tool; Daybreak tabbed console (Runtime / Catalog / Operate / Jobs); catalog pagination (24/page, not a silent 48-cap); `operateHexStrike` JSON invoke; job log/artifacts/stop; copy is “operator console · loopback suite” | RFC file still `accepted` (not ticked implemented). Help `hexstrike-blue` still says MCP is always rejected. HUD still polls `GET /api/hexstrike` every 2.5s (backend still MCP-registers on status). No Always-allow modal (0110). Live Windows operate = desktop sign-off |
| **1.3.13 owner-chat / SAPI** | #266 (and #259 on `main`) | `reasoning_content` when `content` empty; Kokoro refuses silent SAPI | Not a 0105/0106 regression. `n_keep` still absent |

Settings IA (#267) is already on `main` (1.3.13). Treat as prior, not a 1.4 deliverable.

### 1.4 SPECS-ONLY / NOT STARTED (these *are* 1.4 incomplete)

| Item | Status on tip |
| --- | --- |
| **RFC-0107 Obsidian brain** | Accepted spec (#280). No vault bind, watch, graph retrieve/act, or picker |
| **RFC-0108 phone offline AI** | Accepted spec. No on-device runtime / sync |
| **RFC-0109 media upload** | Accepted spec. Daybreak composer still text+Speak; companion attach is the old 64 MiB blob |
| **RFC-0110 approval modal** | **No RFC file, no PR.** HexStrike operate (now including Daybreak “Run capability”) auto-grants and skips Always-allow |
| **`JARVIS_1.4_SPECS` core** | File does not exist on either branch. Cannot audit 1.4 core vs code until Architect lands it |
| **`n_keep < n_ctx`** | llama-server `build_args` has `--ctx-size` only |

### Later INTEGRATION queue (landed or spec’d; not a 1.4 scorecard)

| Item | Note |
| --- | --- |
| RFC-0098 Browser-Use deepen | Backend #273 is real; RFC file still says unimplemented. **Later queue**, not 1.4 incomplete |
| RFC-0095–0104 except 0105 | Specs on `development` via #270/#271. Later queue |
| `INTEGRATION_SPECS.md` | Useful index; stale on 0106 (“specs-only”) and 0098. Architect hygiene, not a 1.4 gate |

### Branch drift

`main` = 1.3.13. 0105/0106/0107–0109 + Daybreak operator console (#283) live only on `development`. Promoting today would ship a **full HexStrike operator HUD + HTTP/MCP** without Obsidian/phone/media/0110/`n_keep`. Still do not cut 1.4.0 from this tip — because **those in-scope 1.4 items are unfinished**, not because Instagram RFCs are unfinished, and not because Daybreak UX is missing.

---

## 2. Specs quality (1.4 items)

### Contradictions

1. **RFC-0106 vs RFC-0086 vs help.** 0106 wins over Blue-only / no-MCP. **HUD #283 now matches 0106** (operator console). Help `hexstrike-blue` still says MCP is always rejected and only typed defensive actions exist. Two remaining stories (HUD vs help), not three. Help rewrite is Architect/should-fix, not a missing console.
2. **RFC-0106 status vs code.** Honest as of `69eebd7`: **backend + Daybreak HUD CODE PRESENT**; RFC file still `accepted`; INTEGRATION_SPECS still “specs-only”; desktop sign-off open. Tick/help/index are stale.
3. **RFC-0105 ticked implemented** vs HUD “until D1 lands” static six-row shell (`staticCybersecurityModule()`). D1 (#277) already landed. **1.4 should-fix / residual stub.**
4. **RFC-0105 allowed “stub catalog for UX”** vs Taco no-stubs bar. That RFC sentence is the defect; the shell survived D1.
5. **No invented gating.** #283 dropped the always-visible attested-scope form; defensive operate still offers optional scope quick-fill. HTTP/MCP `operate()` still does not require a scope. Daybreak “Run capability” is a one-click path into the auto-grant backend.
6. **`JARVIS_1.4_SPECS` missing** while 0107–0109 exist as RFCs. 1.4 core (whatever is *not* those RFCs) has no in-repo contract. Review cannot confirm voice/`n_keep`/approval as specified vs accidental.

RFC-0098 unchecked boxes after #273 belong on the **later INTEGRATION queue**, not this contradiction list as a 1.4 fail.

### Stubs / soft-fail (1.4 surfaces)

- Cyber HUD: “Module catalog API is not available yet… until D1 lands.”
- Cyber start: “Add jarvis-module.json…” when clones have no start metadata — hole, not a harness.
- HexStrike HUD **was** health-only; **#283 replaced it** with catalog/operate/jobs. Residual stub-adjacent: help topic still 0086; `operator_ready` still MCP-gated so HTTP-only catalogs look “not ready.”
- `operator_ready` = MCP ok AND catalog longer than Blue enums. MCP down blocks non-`defensive:` operate even if HTTP tools exist.
- `hexstrike_compat.py` mitmproxy stubs: host-boot, not 1.4 product UX, still a stub on the operator path.

Voice-catalog “system TTS until backend lands” is leftover **prior** UX, not 1.4 integration. Keep off the 1.4 must-fix list unless `JARVIS_1.4_SPECS` (when filed) says otherwise.

### Missing Always-allow popup (RFC-0110 — in 1.4)

`PermissionPrompt.tsx` already has **Allow once / Always allow / Don’t allow**. HexStrike **bypasses** it:

- `cyber.hexstrike` default `ask`
- `/api/hexstrike/operate` and `HexStrikeOperatorTool` call `operator_intent_grant(..., "allow_session")` on `ask`
- Daybreak click (“Run capability”) or chat tool = silent session grant. **#283 makes this worse, not better:** the owner now has a first-class Operate tab that still never shows Always-allow.

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
- `GET /api/hexstrike` (HUD poll **every 2.5s**, unchanged in #283) → `sync_operator_surface(register_mcp=True)` while running. MCP churn + schema instability. #283 also polls operator jobs every 2s while a job is selected.
- `hexstrike_operator` `status` dumps catalog into the tool result (12k truncate).
- Cyber catalog GET re-walks clones every 5s HUD poll.

### B. Silent SAPI / empty `content`

- #266/#259 hold. Kokoro does not fall through to SAPI; `reasoning_content` fills empty chat.
- Not regressed by 0105/0106. Do not claim 1.4 “fixed voice.” Residual: voice-catalog soft shell (prior; not 1.4 gate).

### C. Always-on grant vs on-demand popup

- HexStrike HTTP + chat tool auto `allow_session`.
- Mixed/long-horizon tasks get `hexstrike_operator` without `request_tools`.
- This is exactly why **0110 is in 1.4** and must land. #283 did not darken operate; it added a first-class Run capability button on the same auto-grant path.

### D. HexStrike operate / install security

Loopback pin/audit remain (good). New surface:

1. `operator_post_allowed`: any `api/tools/<name>` except substring denylist; HTTP rows `additionalProperties: True`.
2. `pip:` install of any `[a-z0-9._-]+` package. Missing HexStrike home → **`sys.executable`** (Jarvis’s interpreter).
3. Chat tool **and Daybreak Operate tab** `install_dependency` / `operate` after silent grant.
4. MCP wholesale register on start **and** on status poll.
5. `/stop` does not call `_operator_permission`.
6. Test `test_mcp_registration_refuses_non_loopback_host` is vacuous (no `hexstrike_mcp.py` in tmp → `[]`, not a loopback check).

### E. RFC-0105 supervisor

- Executes checkout `jarvis-module.json` argv or `start.sh`/`main.py` **without forcing loopback bind**.
- Manifest health URL need not be `127.0.0.1`; HTTP `<500` = healthy.
- 1.4 cut risk if those clones are on the owner PC (they are, per RFC). Not an Instagram-queue deferral — this code is already on `development`.

### F. Frontend shells / dual APIs (cyber vs HexStrike)

- Cyber static catalog on **any** catalog GET failure. **Unchanged by #283.**
- HexStrike HUD **#283:** types include `catalog` / `operator` / `operator_jobs`; `operateHexStrike` client exists; catalog is paginated (24/page) rather than silently capped at 48. Dual job lists remain in the API; HUD Jobs tab shows **operator** jobs (legacy `managed_jobs` no longer the only visible list).
- `hexstrike_defensive` is Blue-role-gated; `hexstrike_operator` is general and stronger.
- Gateway `/upstream/{path}` POST still uses widened operator rules.

### G. Help still lies; HUD no longer does

#283 HUD copy is “HexStrike operator console · loopback suite.” Footer still links `/help?topic=hexstrike-blue`, whose body still says MCP is always rejected and only typed defensive actions exist. **Help is now the leftover product lie.**

---

## 4. Punch list (recut)

### Must-fix before a 1.4.0 cut

1. **Do not promote this tip as 1.4.0.** Daybreak HexStrike UX **is no longer the missing piece** (#283). In-scope gaps that remain: 0107–0109 product code, RFC-0110, `JARVIS_1.4_SPECS` file, `n_keep`, HexStrike operate safety (silent grant / pip / MCP-on-poll), desktop sign-off. Instagram 0095–0104 are **not** the reason.
2. **Stop MCP register on status poll.** `GET /api/hexstrike` must not `register_mcp=True` every 2.5s. #283 did not change this; the new console polls *more* (status + selected job).
3. **Land RFC-0110 (or equivalent) and remove silent `operator_intent_grant` on operate/install.** `ask` must ask (Always-allow / once / deny). The Operate tab now makes the skip obvious.
4. **Bind `pip:` / winget to the discovered catalog**; never fall back to `sys.executable`. Catalog “Install” in #283 calls the same backend.
5. **HexStrike help + RFC tick.** Rewrite `hexstrike-blue` (or add an operator topic). Architect: mark RFC-0106 implemented (backend+#283) pending desktop sign-off. **HUD itself is no longer a 1.4 “not started” item.**
6. **Strip cyber HUD “until D1 lands” static shell.**
7. **`n_keep < n_ctx`** before 27B with MCP/skill/catalog bloat.
8. **Implement 0107 / 0108 / 0109** as named tickets (full intent, no stub vault / canned offline / attach-chip-that-never-ingests).
9. **Architect: land `JARVIS_1.4_SPECS` on `development`** (or point at the real file). Until then 1.4 “core” is unauditable.

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
- Collapse leftover `managed_jobs` into the operator Jobs tab if Blue-enum actions still exist as a compatibility path.
- Desktop sign-off for #283 (live pin, catalog refresh, HUD operate, job/log/artifact). Cloud did not.

---

## 5. Verdict (1.4-scoped)

**0105 (in 1.4):** partial connectors + Daybreak panel are real; leftover soft-fail shell and checkout spawn remain. Desktop sign-off still required.

**0106 + Daybreak UX (in 1.4):** **backend #279 + HUD #283 are real operator surfaces**, not a health-only shell. Highest remaining risk is that this console is live **on top of** silent `allow_session`, unbounded `pip:`, and MCP-register-on-poll. Help topic still 0086. Desktop sign-off open. RFC file not ticked.

**0107–0109 (in 1.4):** specs-only. Required for the cut; not started in product code.

**0110 (in 1.4):** missing. #283 Operate tab is the anti-pattern the modal is supposed to wrap.

**`JARVIS_1.4_SPECS` (in 1.4):** missing from both branches. Architect gap, not an implementer miss.

**0095–0104 / 0098 (out of 1.4):** later INTEGRATION queue. #273 Browser-Use deepen is extra credit on `development`, not a 1.4 hole.

**1.3.13 empty-chat + SAPI:** already on `main`; not regressed.

Do not merge this review PR. Do not merge `development` → `main` as 1.4 until the **in-scope** must-fix list is owned. Do not wait on Instagram catalog RFCs for that cut.
