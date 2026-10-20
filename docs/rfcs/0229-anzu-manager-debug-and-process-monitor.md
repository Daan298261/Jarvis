# RFC-0229: ANZU Manager — debug logger, button-press feedback, spawned-process monitor

**Status:** accepted  
**Priority:** P2 (Taco batch 2026-10-17, items 8 and 9)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20

**Owner ask (verbatim intent, 2026-10-17):** "8. Add a debug logger and visual feedback on button presses. 9. Add a small screen listing every process ANZU spawned, showing its status, resource usage, and whether it is idle or working, with a timer for how long."  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §2 (one design language; "Finished is the target."), §10 ("Swarm computing should be invisible unless inspected" — this is the *inspect* surface), §15 ("ANZU should know whether its own systems are healthy… explain what happened"), §19 ("Do expose state when the user needs confidence in what ANZU is doing."; "Do not expose architecture simply because the architecture exists." — the screen lives in the Manager, not the main HUD), §20 Q6, Q11.  
**Extends (do not rewrite):** [RFC-0196 native ANZU Manager](0196-native-anzu-manager.md) (loopback :4782, start/stop/restart with session token + confirm, supervisor), [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) **S2 process registry** (the single source of "processes ANZU spawned") and S3 engine ledger.  
**Depends on:** RFC-0225 S2 for S2 of this RFC. No dependency on #648/#649 (they do not touch `backend/app/manager/**`).  
**Astra boundary:** Persona/presence/WebGL/appearance out of scope (Astra). The Manager's existing background canvas animation (`#field`) is kept as is.

This PR is **specs-only**. No application code.

---

## Problem

Verified in `development` @ `3f17c3d8`:

1. **Button presses give almost no feedback.** `backend/app/manager/static/app.js`: Start/Restart/Stop → `confirm()` → `b.disabled = true` → `fetch` → `alert(e.message)` on error. A restart can take up to 250 s (`frontend/src-tauri/src/lib.rs` comment: 150 + 10 + 90) with only a disabled button; success is indistinguishable from "nothing happened" until the 5 s status refresh.
2. **No debug log of Manager actions.** `backend/app/manager/main.py` writes launcher stdout to `logs/anzu-launch.log` (rotated) and Tauri logs failed controls, but there is no structured, viewable record of presses, request ids, durations, results or supervisor decisions.
3. **No process visibility.** The Manager shows core state, task counts, GPU name, disk, RAM. It cannot show ANZU's llama-server(s), front lane, module workers, Supermemory sidecar, LM Studio started by ANZU, etc. Spawn sites track their own handles; RFC-0225 S2 introduces the registry this screen needs.

## Decision

Ship **one RFC with two implement slices** (one named model each, **fast off**).

### Debug logger (normative)

- `logs/manager-debug.log`, JSON lines, size-rotated with the existing `rotate_file` (reuse `LAUNCH_LOG_MAX_BYTES` / `LAUNCH_LOGS_KEPT` policy). Fields: `ts`, `level`, `event` (`press`, `control_start`, `control_end`, `supervisor`, `status_error`, `process_view`), `action`, `request_id`, `duration_ms`, `ok`, `detail`.
- Every control press carries a client `request_id` (header) logged at receipt and completion; supervisor restarts/backoffs are logged.
- `GET /api/manager/v1/debug-log?tail=200` (loopback-only, existing middleware) returns parsed lines; secrets/tokens never logged (session token redacted).
- "Debug" drawer in the Manager page shows the tail with level filter and auto-refresh while open; a "Verbose" toggle raises level to DEBUG for the current Manager session.

### Button feedback (normative)

States per control button: `idle → pressed (≤100 ms) → working (spinner + elapsed seconds + phase text from the control endpoint: "Stopping…", "Waiting for health…") → success (green tick, 3 s) | failed (red, inline message, stays until dismissed)`. Other control buttons are disabled while one runs, with a tooltip saying why. Existing `confirm()` prompts are kept.

### Process monitor (normative)

- Source: RFC-0225 S2 registry. With the core healthy, the Manager reads `GET /api/system/processes`; with the core down, it reads `data_dir()/runtime/process-registry.json` directly and verifies each pid/create-time with psutil (so orphans left by a crashed core are visible).
- Columns: name/kind, pid, status (`running` / `exited (code)` / `orphaned`), CPU % (1 s sample), RAM (RSS), GPU memory where the platform exposes per-process GPU usage (NVIDIA `nvidia-smi --query-compute-apps`; otherwise the cell reads "not reported by driver"), activity (`working` / `idle`), and **timer** "for 12m 03s" since the last activity change, plus uptime.
- Activity rules: llama-server → `/slots` `is_processing` (RFC-0210 probe); module workers / sidecars → CPU > 5 % averaged over 10 s = working; others → CPU rule. The rule used is shown in a tooltip.
- Read-only by default. A "Stop" action per row is **not** added in this RFC (stopping ANZU's own children stays with RFC-0093/0136 force-stop and Manager Stop).
- Refresh every 2 s while the screen is visible, 0 when hidden; psutil work off the event loop.

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

| Current live behaviour | Preserved? | Added alongside |
| --- | --- | --- |
| Header "LOCAL CONTROL PLANE / ANZU Manager / state line" | **Yes** | — |
| Start / Restart / Stop (danger) / Quit Manager buttons with their `confirm()` texts | **Yes**, same labels and confirms | Pressed/working/success/failed states, elapsed timer, phase text |
| Error surfaced via `alert(message)` | **Yes** (alert kept) | Inline failed state on the button with the same message |
| Status cards (Core, Tasks/agents, Model/GPU, Disk, Memory, Manager) refreshing every 5 s | **Yes** | "Processes" card link + Debug drawer |
| `#field` background canvas | **Yes**, untouched | — |
| Loopback-only middleware, session token, explicit confirm on control | **Yes** | Debug-log endpoint behind the same middleware |
| Tauri manager mode (`JARVIS_MANAGER=1`), tray Quit Manager | **Yes** | — |

Nothing is deleted. Each implement PR includes the preserved-behaviour section with screenshots.

### Stub rule

No stubs. A process screen fed by mock data, a GPU column that is always blank without saying why, or a log endpoint nothing writes to, is a fail.

---

## Slices (one ticket each)

Assign order: **S1 → S2** (S2 also needs RFC-0225 S2).

### S1 — Manager debug logger + button feedback

**Model:** Composer 2.5 (fast off) · **Lane:** UX · **Depends:** none

| Path | Why |
| --- | --- |
| `backend/app/manager/main.py` | JSON-lines debug logger; `request_id` on control; phase reporting for control (`GET /api/manager/v1/control/progress`); `GET /api/manager/v1/debug-log`; token redaction |
| `backend/app/manager/supervisor.py` | Emit supervisor events to the debug logger (restart, backoff, crash-log preserved) |
| `backend/app/manager/static/app.js` | Button state machine, elapsed timer, phase text, inline failure, Debug drawer |
| `backend/app/manager/static/index.html` | Debug drawer markup |
| `backend/app/manager/static/style.css` | Pressed/working/success/failed styles in the existing design language |
| `tests/test_rfc0229_manager_debug.py` (new) | Below (alongside `tests/test_rfc0196_anzu_manager.py`, `tests/test_manager_supervisor.py`) |

- [ ] Each press writes `press` + `control_start` + `control_end` lines with the same `request_id`, `duration_ms`, `ok`.
- [ ] Session token never appears in the log (test greps output).
- [ ] Debug-log endpoint returns the last N lines, rejects non-loopback (existing middleware test pattern).
- [ ] Button shows pressed within 100 ms, elapsed timer during a simulated 30 s restart, then success or the inline error; existing confirm texts unchanged.
- [ ] Log rotation honoured; RFC-0196 tests green.

### S2 — Spawned-process monitor screen

**Model:** Grok 4.5 (fast off) · **Lane:** UX · **Depends:** S1 (sequential owner of `main.py` / static files), RFC-0225 S2

| Path | Why |
| --- | --- |
| `backend/app/manager/process_view.py` (new) | Merge core `/api/system/processes` or the on-disk registry with psutil samples; activity rules; timers; NVIDIA per-process GPU when available |
| `backend/app/manager/main.py` | `GET /api/manager/v1/processes` |
| `backend/app/manager/static/processes.js` (new) | Processes screen rendering, 2 s refresh while visible |
| `backend/app/manager/static/index.html` / `style.css` | Processes card/link and table styles |
| `tests/test_rfc0229_process_view.py` (new) | Below |

- [ ] Core healthy → every RFC-0225 registry entry listed with status, CPU, RSS, activity and timer.
- [ ] Core stopped with a leftover llama-server → listed as `orphaned` from the on-disk registry; pid reuse (create-time mismatch) is not listed as ANZU's.
- [ ] llama-server busy fixture (`is_processing: true`) → `working`; timer resets on activity change.
- [ ] No NVIDIA driver → GPU cell reads "not reported by driver"; with fixture data → MiB value.
- [ ] Endpoint p95 < 300 ms for 20 processes; screen stops polling when hidden.

---

## Overall acceptance

- [ ] On Taco's PC: Manager Restart shows phases and elapsed time to completion; the debug drawer shows the press with request id and duration.
- [ ] Processes screen lists ANZU's worker llama-server, front lane, module workers and sidecars with live CPU/RAM, idle/working and timers; after killing the core, leftovers show as orphaned.
- [ ] All Live-UI rows preserved; RFC-0196 suite green.

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0229-S1 | Manager debug logger + button feedback | Composer 2.5 | UX | — |
| 0229-S2 | Spawned-process monitor screen | Grok 4.5 | UX | S1, 0225-S2 |

## Likely files

See ownership tables. No file here is owned by another RFC of the 2026-10-17 batch.

## Out of scope

- Persona/presence/WebGL/appearance (Astra).
- Stopping/restarting individual processes from the Manager.
- Foreign engines (RFC-0225 S4 prompt / Model page show those).
- Tauri tray menu changes.

## Risks

- **psutil cost on Windows** — sampling off the event loop, 2 s cadence only while visible.
- **Registry not yet landed** — S2 hard-depends on RFC-0225 S2; S1 ships independently.
