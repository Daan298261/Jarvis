# RFC-0225: Local engine coexistence + resilient local-API connection

**Status:** accepted  
**Priority:** P0 (Taco bug batch 2026-10-17, bug 2 — highest impact)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20

**Owner ask (verbatim intent, 2026-10-17):** "Portal shows 'CANNOT REACH THE LOCAL API / Failed to fetch' even with a model loaded (GPU ~15%), status flickers between error and online. Root cause: concurrent model servers, LM Studio on :1234 vs ANZU's own. When ANZU starts, ask which other engines to kill, and respawn them later if needed. Also make the local-API connection resilient to this."  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §7 (autonomous, not reckless — "ANZU should eliminate unnecessary approvals without eliminating meaningful control."), §8 (verify — "Confidence should come from evidence rather than cheerful completion messages."), §9 (local-first — "The user chooses intent and policy. **ANZU chooses infrastructure.**"), §10 (swarm invisible unless inspected), §19 ("Do expose state when the user needs confidence in what ANZU is doing." / "Do not remove useful capability merely to simplify the codebase."), §20 Q6 ("Can ANZU recover intelligently when the happy path fails?") and Q8.  
**Extends (do not rewrite):** [RFC-0210 running-model discovery](0210-running-model-discovery-and-owner-choice.md) (use / leave / stop / replace, identity-verified stop), [RFC-0091 LM Studio autostart](0091-lmstudio-autostart-and-chat-bubbles.md), [RFC-0093](0093-installer-force-stop-and-prepare-unstick.md) / [RFC-0136 zombie-kill](0136-zombie-kill-setup-next-and-start.md) (ANZU-owned process stop), [RFC-0105](0105-cybersecurity-module.md) (`modules/supervisor.py` pid-tracking pattern), [RFC-0196 ANZU Manager](0196-native-anzu-manager.md).  
**Open implementation PRs that overlap (rebase gate):** #648 (RFC-0223 startup/model stability — moves status/LAN/catalog work off the event loop and touches `running_models.py`, `lmstudio_server.py`, `backends.py`, `main.py`, `App.tsx`) and #649 (RFC-0224). Every slice below that owns one of those files starts only after #648 is merged or closed, and rebases on the result. If #648 already removes the flicker cause, S1 records that as the root cause evidence and the remaining slices still ship the coexistence + resilience contract.  
**Astra boundary:** Persona, presence, WebGL and appearance are **out of scope** and stay Astra's. Nothing here edits `frontend/src/presence/**`, persona renderers or appearance settings.

This PR is **specs-only**. No application code.

---

## Problem

Verified in `development` @ `3f17c3d8`:

1. **The red banner fires on a single failed poll.** `frontend/src/App.tsx` polls `/api/model` every 8 s; any rejected fetch immediately calls `setPortalApiError(err.message)` and the next success clears it. `frontend/src/hud/systemHealth.ts` turns that string into the "Portal cannot reach the local API" issue. There is no debounce, no consecutive-failure threshold, no backoff and no distinction between timeout, refused connection and HTTP error. One slow `/api/model` answer = one red flash = the reported flicker.
2. **Several model servers compete for the same GPU.** ANZU spawns its own `llama-server` (`backend/app/inference/backends.py`, worker port 8088, front lane 8089), can auto-start LM Studio on 1234 (`backend/app/inference/lmstudio_server.py::ensure_local_lmstudio`, reached from `hotswap.py`), and Taco also runs LM Studio (9B on `http://127.0.0.1:1234/v1`) and Ollama (`anzu-coder-27b` on 11434, ~12 GB GPU; see `docs/audits/2026-10-09-model-reuse-scheduler-manager.md`). RFC-0210 discovers foreign servers every 20 s and offers use/leave/stop/replace per row, but **nothing at startup** asks the owner which engines should yield, nothing remembers what was stopped, and nothing can bring a stopped engine back.
3. **ANZU cannot tell its own server from a foreign one on the same port.** `probe_remote_server` / `running_models.probe` accept any OpenAI-compatible responder. If LM Studio or a stale llama-server holds 8088, ANZU's managed worker health check can pass against the wrong process.
4. **No registry of ANZU-spawned processes.** Spawn sites (`backends.py` llama-server, `modules/supervisor.py`, `modules/supermemory_runtime.py`, LM Studio autostart) each track their own handle. There is no single list to show the owner, to exclude from "foreign" detection, or to clean up on exit. (RFC-0229 needs this list for the Manager process screen.)
5. **The root cause is asserted, not proven.** Taco's diagnosis (concurrent servers) is plausible, but #648 found event-loop stalls (LAN beacon echo, blocking status reads) that produce the same symptom. The fix must be grounded in captured evidence.

## Decision

Ship **one RFC with five implement slices**, each one CoS-assignable ticket with one named model (**fast off**).

### Terms

| Name | Meaning |
| --- | --- |
| **ANZU-owned engine** | A process in the S2 process registry (spawned by ANZU, pid + create-time verified), or LM Studio that ANZU itself started via `ensure_local_lmstudio` (recorded as `started_by: anzu`). |
| **Selected engine** | The endpoint in `settings.inference` (host/port/remote_model). When Taco selects LM Studio :1234 as ANZU's engine, LM Studio is **selected, not foreign**, and is never offered for stopping. |
| **Foreign engine** | A detected local inference server (RFC-0210 `listener_inventory` + `probe`) that is neither ANZU-owned nor selected. |
| **Engine ledger** | Durable record (`data_dir()/runtime/engine-ledger.json`) of every foreign engine ANZU stopped with owner consent: kind, port, executable path, command line, served model ids, stop method, `stopped_at`, respawn method, `respawn_on_exit` flag. |

### Owner-consequential rule (normative)

Stopping another application's engine is owner-consequential (§7). Therefore:

1. **Never stop silently.** Every stop follows an explicit owner choice in the S4 prompt (or the existing RFC-0210 row buttons). No background timer, decision class, or model may stop a foreign engine on its own.
2. The prompt lists **every** detected foreign engine with **port, process name + executable, served/loaded model ids, busy state** (RFC-0210 `/slots` / native inventory).
3. Per engine the owner chooses **Keep running** / **Stop now** / **Stop now and whenever ANZU starts**. "Remember my choice" is optional and off by default; remembered choices are visible and revocable in Model settings.
4. Stop uses only the safest verified mechanism per kind, reusing RFC-0210 code: LM Studio → native unload (`/api/v1/models/unload`) then `lms server stop` when the owner chose to stop the server; Ollama → `keep_alive: 0` unload (server left up unless chosen); llama-server → `stop_listener` (pid + create-time + listener re-verification). Editors/agents (Cursor, Aider, Antigravity) are never stop targets (RFC-0210 rule kept).
5. Every successful stop writes an engine-ledger entry **before** returning success; a failed verification never writes "stopped".
6. **Respawn on demand:** when the owner or the router requests a model that only a ledgered engine serves (e.g. `anzu-coder-27b` on Ollama), ANZU restarts that engine with the recorded method, waits for health, attaches through the existing provider, and tells the owner in one line ("Restarted Ollama for anzu-coder-27b."). Failure is surfaced, never swallowed.
7. **Respawn on exit:** if the owner ticked "restart it when ANZU closes", ANZU's shutdown path restarts ledgered engines after its own servers are down. Default off.
8. Busy engines (another client mid-request) are never stopped; the prompt says so and offers "Ask me again when it is idle".

### Resilience contract (normative)

1. **Single source of truth for base URLs.** Frontend: every request already flows through `frontend/src/apiOrigin.ts::jarvisApiUrl` (verified: zero raw `fetch("/api…")` in `frontend/src`); S5 adds a guard test so it stays that way. Backend: a new `backend/app/inference/endpoint.py::inference_base_url(settings)` is the only place that builds the selected engine's `http://host:port/v1`; callers in `running_models.py` and `lmstudio_server.py` move to it (S3).
2. **Identity-checked health.** `/api/health` (via `backend/app/startup_health.py::report`) adds `service: "anzu-core"`, `instance_id` (random per process start) and `started_at`. The portal treats a 4780 responder without `service == "anzu-core"` as **port conflict**, not "cannot reach". ANZU's managed llama-server health passes only when the listener pid on its port equals the registered child pid (S2).
3. **Port-conflict detection.** Before spawning a managed llama-server, ANZU checks the port; a foreign listener → typed `port_conflict` state with the owning process, surfaced in Model page and S4 prompt, never a blind spawn into `EADDRINUSE`.
4. **Debounced reachability.** Portal state machine `online → suspect → offline → recovering → online`: `offline` (red banner) only after ≥3 consecutive failures spanning ≥10 s; probes back off 2 → 4 → 8 → 15 s (cap) while not online; `recovering → online` after 2 consecutive successes. Timeout, network refusal and HTTP 5xx are distinct reasons in the detail text. 401 keeps its existing immediate message.
5. A degraded model server (busy, loading, foreign on port) is a **model** issue, never rendered as "cannot reach the local API".

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

Touched live UI: portal health rail / HUD banner (`App.tsx`, `systemHealth.ts` consumers), Model page, the RFC-0210 "Available local models" offer, `HudShell.tsx` mount point.

| Current live behaviour | Preserved? | What this RFC adds alongside |
| --- | --- | --- |
| Health rail shows "Portal cannot reach the local API" with owner-facing detail and `/system` link | **Yes** — same title, same link, same `ownerFacingApiMessage` text path | Debounce + reason; new distinct "Port 4780 is used by another program" issue |
| 401 shows the auth guidance message immediately | **Yes**, unchanged | — |
| `/api/model` 8 s poll feeding HUD model state | **Yes** (cadence unchanged while online) | Backoff only while not online |
| RFC-0210 offer: use / leave / stop / replace per discovered row; Model page "Scan running servers" | **Yes**, all four buttons and the scan button stay | Startup engine prompt (S4) writes the same choices store, so answered rows disappear from the offer exactly as today |
| RFC-0210 spoken "I found another local model server…" notice | **Yes** (frequency is RFC-0227's scope) | — |
| Identity-verified llama-server stop; never stopping editors | **Yes** | Ledger + respawn |

Nothing is deleted. Each implement PR includes a short "Preserved live behaviour" section listing the rows above with the test or screenshot that verified each.

### Stub rule

No stubs, scaffolding, TODO bodies, placeholder endpoints or soft-fails. A ledger that records but cannot respawn, a prompt that lists engines but cannot stop them, or a health identity field nobody checks, is a fail.

---

## Slices (one ticket each)

Assign order: **S1 → S2 → S3 → S4 ∥ S5** (S5 may start after S1).

### S1 — Root-cause evidence for the API flicker

**Model:** Grok 4.5 (fast off) · **Lane:** D1 · **Depends:** #648 merged or closed

Reproduce on Taco's Windows profile (LM Studio :1234 with the 9B loaded, Ollama `anzu-coder-27b`, ANZU installed) and on a clean profile. Capture: portal network log of every failed `/api/model`, backend event-loop lag samples, `netstat -ano` listeners for 1234/8088/8089/11434/4780, `nvidia-smi` VRAM per process, backend logs around each failure. Decide which hypothesis holds (concurrent servers → VRAM pressure/stall, event-loop blocking, port collision, backend restart, or a combination) and record the numbers.

| Path | Why |
| --- | --- |
| `docs/audits/2026-10-20-local-api-flicker-root-cause.md` (new) | Evidence + conclusion + which S2–S5 acceptance lines it drives |
| `tests/test_rfc0225_flicker_repro.py` (new) | Deterministic repro of the confirmed failure mode against a fake slow/foreign server; passes once S3/S5 land (marked with the slice that turns it green, not skipped) |

- [ ] Audit names the confirmed root cause(s) with captured evidence (timestamps, listener table, VRAM, loop lag); unconfirmed hypotheses are listed as rejected with the evidence that rejected them.
- [ ] States whether #648 already removed any contributing cause.
- [ ] Repro test fails on `development` before the fix for the confirmed mode and documents the slice that makes it pass.

### S2 — ANZU process registry + identity-checked managed server

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S1

| Path | Why |
| --- | --- |
| `backend/app/runtime/process_registry.py` (new) | `register(kind, pid, create_time, argv, port, owner_module)`, `unregister`, `snapshot()`, `is_anzu_owned(pid, create_time)`; persisted atomically to `data_dir()/runtime/process-registry.json` so the Manager can read it with the core down |
| `backend/app/inference/backends.py` | Register/unregister the managed llama-server (worker + front); pre-spawn port check → `port_conflict`; health accepts only when listener pid == registered pid |
| `backend/app/modules/supervisor.py` | Register module workers (reuses existing pid tracking) |
| `backend/app/modules/supermemory_runtime.py` | Register the Supermemory sidecar |
| `backend/app/api/processes.py` (new) | `GET /api/system/processes` → registry snapshot + live psutil status (running/exited, CPU %, RSS) |
| `backend/app/main.py` | Include the processes router; unregister/terminate registered children on shutdown (existing shutdown order kept) |
| `tests/test_rfc0225_process_registry.py` (new) | Below |

- [ ] Every spawn site above registers on start and unregisters on exit; a crashed child is reported `exited` with exit code, not silently dropped.
- [ ] Registry survives a core restart; stale entries (pid reused / create-time mismatch) are pruned, never killed.
- [ ] Foreign listener on 8088 before spawn → `port_conflict` with owning process name/pid; no spawn attempted.
- [ ] Managed health check rejects a responder on 8088 whose pid is not the registered child.
- [ ] `GET /api/system/processes` returns within 300 ms with 20 registered entries (psutil reads off the event loop).

### S3 — Foreign-engine detection, owner-consented stop, engine ledger, respawn

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S2

| Path | Why |
| --- | --- |
| `backend/app/inference/running_models.py` | Classify each RFC-0210 row as `anzu_owned` / `selected` / `foreign` using the S2 registry and `settings.inference`; add engine kind (`lmstudio`, `ollama`, `llama-server`, `remote`) and executable path to rows; reuse `stop_listener` / `verify_unloaded` |
| `backend/app/inference/engine_coexistence.py` (new) | Startup check (after model autoload decision, off the event loop), prompt payload, remembered choices (`data_dir()/runtime/engine-choices.json`), stop per the owner-consequential rule, engine ledger write, `respawn(entry)`, on-demand respawn hook, on-exit respawn |
| `backend/app/inference/endpoint.py` (new) | `inference_base_url(settings)`; single builder for the selected engine URL |
| `backend/app/inference/lmstudio_server.py` | Record `started_by: anzu` when ANZU starts LM Studio; expose `stop_lmstudio_server()` (`lms server stop`) and reuse `ensure_local_lmstudio` as the LM Studio respawn method; use `endpoint.py` |
| `backend/app/api/model.py` | `GET /api/model/engines` (prompt payload), `POST /api/model/engines/decision` (`keep` / `stop` / `stop_always`, `remember`, `respawn_on_exit`), `GET /api/model/engines/ledger`, `POST /api/model/engines/{id}/respawn` |
| `tests/test_rfc0225_engine_coexistence.py` (new) | Below |

- [ ] With Taco's selected engine = LM Studio :1234, LM Studio is classified `selected` and never appears as a stop candidate.
- [ ] No code path stops a foreign engine without a recorded owner decision (test asserts stop functions are only reachable from the decision endpoint and the existing RFC-0210 choice endpoint).
- [ ] Busy engine → decision rejected with "in use" reason; nothing stopped.
- [ ] Successful stop writes a ledger entry with kind, port, exe, argv, models, method, timestamp; failed verification writes nothing and returns the error.
- [ ] Requesting a model served only by a ledgered engine respawns it, waits for health, attaches, and publishes one owner line; respawn failure is surfaced to the owner and the request fails visibly.
- [ ] `respawn_on_exit` true → shutdown restarts the engine after ANZU's servers are down; false → nothing restarted.
- [ ] Remembered `stop_always` applies on next start **and** the startup announcement still names what was stopped (never silent).
- [ ] Editors/agents (Cursor, Aider, Antigravity) are never classified as engines.

### S4 — Startup engine prompt (UI)

**Model:** Composer 2.5 (fast off) · **Lane:** UX · **Depends:** S3

| Path | Why |
| --- | --- |
| `frontend/src/hud/EngineCoexistencePrompt.tsx` (new) | One non-modal card listing detected foreign engines (port, process, model ids, busy); per-engine Keep / Stop now / Stop whenever ANZU starts; "Remember my choice" (off by default); "Restart it when ANZU closes"; per-row pending + result state |
| `frontend/src/hud/HudShell.tsx` | Mount the prompt next to the existing `<RunningModels />` mount (existing mount unchanged) |
| `frontend/src/pages/Model.tsx` | "Other engines" section: remembered choices (revocable), ledger with "Restart now" |
| `frontend/engine-coexistence.test.mjs` (new) + `package.json` script | Below |

- [ ] Prompt shows only when S3 reports ≥1 foreign engine without a remembered choice; it never blocks chat or the HUD.
- [ ] Each row displays port, process/executable, model ids and busy state; Stop is disabled for busy rows with the reason shown.
- [ ] Answering writes through `POST /api/model/engines/decision`; answered rows also disappear from the RFC-0210 offer (shared choices store).
- [ ] Model page lists remembered choices (revoke works) and ledger entries ("Restart now" calls respawn and shows the result).
- [ ] Preserved-live-behaviour section in the PR covers every row of the table above; `npm --prefix frontend run build` + lint pass.

### S5 — Debounced, identity-checked local-API reachability

**Model:** Grok 4.5 (fast off) · **Lane:** UX · **Depends:** S1 (and #648 for `App.tsx`)

| Path | Why |
| --- | --- |
| `frontend/src/hud/apiReachability.ts` (new) | Pure state machine per the resilience contract (thresholds, backoff, reasons, identity check) |
| `frontend/src/App.tsx` | Replace the raw `setPortalApiError` calls in the `/api/model` poll with the state machine output; same `collectHealthIssues` call |
| `frontend/src/apiOrigin.ts` | Export the health-identity check helper (base URL logic unchanged) |
| `backend/app/startup_health.py` | `report()` adds `service`, `instance_id`, `started_at` |
| `frontend/api-reachability.test.mjs` (new) + `package.json` script; `tests/test_rfc0225_health_identity.py` (new) | Below |

- [ ] One failed poll between successes never shows the red banner (fixture: fail/ok/fail/ok over 30 s → zero `api` issues).
- [ ] 3 consecutive failures over ≥10 s → banner with the reason (timeout / refused / HTTP n); 2 successes → cleared.
- [ ] Backoff 2/4/8/15 s while not online; 8 s cadence restored when online.
- [ ] A 4780 responder without `service: "anzu-core"` → "Port 4780 is used by another program" issue, not "cannot reach".
- [ ] Guard test fails if any `frontend/src` file calls `fetch` with a raw `/api` path instead of `jarvisApiUrl`.
- [ ] 401 message unchanged; S1 repro test passes for the flicker mode.

---

## Overall acceptance

- [ ] S1 audit merged with confirmed root cause; S1 repro green after S3/S5.
- [ ] On Taco's PC: LM Studio 9B selected + Ollama 27B running + ANZU start → no red flicker over a 30-minute idle + chat soak; prompt lists Ollama with port/process/model; "Keep" leaves it untouched.
- [ ] "Stop now" on Ollama → VRAM freed (nvidia-smi), ledger entry written; asking for `anzu-coder-27b` respawns it and answers.
- [ ] No foreign engine is ever stopped without an owner decision (log audit over the soak).
- [ ] All Live-UI rows preserved; frontend build + lint; full backend suite green in CI.

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0225-S1 | Root-cause evidence for API flicker | Grok 4.5 | D1 | #648 resolved |
| 0225-S2 | ANZU process registry + identity-checked managed server | Grok 4.6 | D1 | S1 |
| 0225-S3 | Foreign-engine stop with consent, ledger, respawn | Grok 4.6 | D1 | S2 |
| 0225-S4 | Startup engine prompt UI | Composer 2.5 | UX | S3 |
| 0225-S5 | Debounced identity-checked reachability | Grok 4.5 | UX | S1, #648 |

## Likely files

See per-slice ownership tables. Cross-RFC sequencing: `running_models.py` and `api/model.py` pass to RFC-0227 S1 after 0225-S3 merges; `lmstudio_server.py` passes to RFC-0228 S2 after 0225-S3 merges. `main.py` and `HudShell.tsx` are owned only by this RFC in the 2026-10-17 batch.

`frontend/package.json` is shared by every frontend ticket in the 2026-10-17 batch: each ticket adds exactly one `test:*` script line (append-only hunk, trivial rebase) and touches nothing else in that file.

## Out of scope

- Persona, presence, WebGL, appearance (Astra).
- Remote (non-loopback) engines: never stopped or respawned by ANZU.
- Chooser popup frequency/responsiveness and dropdown persistence (RFC-0227).
- Idle unload of the 9B (RFC-0228 S2) — this RFC only respawns foreign engines it stopped.
- Manager process screen UI (RFC-0229 S2 consumes the S2 registry).

## Risks

- **LM Studio CLI differences** (`lms server stop`, unload API) across versions → S3 detects capability and falls back to "stop it in LM Studio" guidance with the row left running; never a forced kill of `LM Studio.exe`.
- **Respawn of an engine started by the owner with custom flags** → ledger records argv/exe; when argv is unavailable the respawn method is the engine's standard start and the owner is told.
- **#648 overlap** → hard rebase gate above.
- **False "foreign" on ANZU's own LM Studio** → `started_by: anzu` + selected-engine rule; tests cover both.
