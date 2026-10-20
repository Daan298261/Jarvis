# RFC-0229: ANZU Manager — debug logger, button-press feedback, spawned-process monitor

**Status:** accepted  
**Priority:** P2 (Taco batch 2026-10-17, items 8 and 9)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20 (re-sliced 2026-10-20: UX review items 1–4 folded in; UX re-review 2026-10-20: `.js` MIME type pinned for the module script, script-tag row corrected)

**Owner ask (verbatim intent, 2026-10-17):** "8. Add a debug logger and visual feedback on button presses. 9. Add a small screen listing every process ANZU spawned, showing its status, resource usage, and whether it is idle or working, with a timer for how long."  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §2 (one design language; "Finished is the target."), §10 ("Swarm computing should be invisible unless inspected" — this is the *inspect* surface), §15 ("ANZU should know whether its own systems are healthy… explain what happened"), §19 ("Do expose state when the user needs confidence in what ANZU is doing."; "Do not expose architecture simply because the architecture exists." — the screen lives in the Manager, not the main HUD), §20 Q6, Q11.  
**Extends (do not rewrite):** [RFC-0196 native ANZU Manager](0196-native-anzu-manager.md) (loopback :4782, start/stop/restart with session token + confirm, supervisor), [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) **S2 process registry** (the single source of "processes ANZU spawned") and S3 engine ledger.  
**Depends on:** RFC-0225 S2 (process registry) and RFC-0225 S3 (engine classification, selected engine, idle-unload hook) for S2 of this RFC. No gate on #648/#649 (see "Relationship to drafts #648/#649").  
**Astra boundary:** Persona/presence/WebGL/appearance out of scope (Astra). The Manager's existing background canvas animation (`#field`) is kept as is.

This PR is **specs-only**. No application code.

---

## Problem

Verified in `development` @ `3f17c3d8`:

1. **Button presses give almost no feedback.** `backend/app/manager/static/app.js`: Start/Restart/Stop → `confirm()` → `b.disabled = true` → `fetch` → `alert(e.message)` on error. A restart can take up to 250 s (`frontend/src-tauri/src/lib.rs` comment: 150 + 10 + 90) with only a disabled button; success is indistinguishable from "nothing happened" until the 5 s status refresh.
2. **No debug log of Manager actions.** `backend/app/manager/main.py` writes launcher stdout to `logs/anzu-launch.log` (rotated) and Tauri logs failed controls, but there is no structured, viewable record of presses, request ids, durations, results or supervisor decisions.
3. **No process visibility.** The Manager shows core state, task counts, GPU name, disk, RAM. It cannot show ANZU's llama-server(s), front lane, module workers, Supermemory sidecar, LM Studio started by ANZU, or the **selected** engine ANZU talks to (Taco's LM Studio :1234, which ANZU did not spawn). Spawn sites track their own handles; RFC-0225 S2 introduces the registry this screen needs.
4. **Manager UI is untested.** `backend/app/manager/static/app.js` is one minified classic script (`<script src="/assets/app.js">`); no JS test covers it and `pr-tests.yml` runs none.

## Decision

Ship **one RFC with two implement slices** (one named model each, **fast off**).

### Debug logger (normative)

- `logs/manager-debug.log`, JSON lines, size-rotated with the existing `supervisor.rotate_file`: **2 MiB per file** (`LAUNCH_LOG_MAX_BYTES = 2 * 1024 * 1024`) and **5 rotated files kept** (`LAUNCH_LOGS_KEPT = 5`), so the debug log never uses more than **12 MiB** on disk (current + 5). Fields: `ts`, `level`, `event` (`press`, `control_start`, `control_end`, `supervisor`, `status_error`, `process_view`), `action`, `request_id`, `duration_ms`, `ok`, `detail`.
- Every control press carries a client `request_id` (header) logged at receipt and completion; supervisor restarts/backoffs are logged.
- `GET /api/manager/v1/debug-log?tail=200` (loopback-only, existing middleware) returns parsed lines.
- **Redaction (UX #2), one module `backend/app/manager/redact.py` used by the logger and the process view, applied before anything is written or returned:**
  - Header values for `Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`, `Api-Key`, `X-Jarvis-Key`, `X-Anzu-Manager-Token` (`manager/main.py::TOKEN_HEADER`) and the Manager session token → `***`.
  - Argv: values of `--api-key`, `--token`, `--password`, `--secret`, `--key`, `--hf-token`, `--auth`, `--bearer` (both `--flag value` and `--flag=value`) → `***`; any `NAME=value` arg whose name matches `(KEY|TOKEN|SECRET|PASSWORD|PASS|AUTH|CREDENTIAL)` (case-insensitive) → `NAME=***`.
  - Environment: values are never logged or returned; only names, and only on DEBUG.
  - Owner chat text: fields `text`, `prompt`, `message`, `content`, `transcript` → `<n chars>`.
  - Case-file paths: any path under `data_dir()/investigations` (`reverse_engineering/store.py`) → `<case-file>`.
  - **Raw argv is never returned.** The process endpoint returns `argv_redacted` only (and the executable name); the raw list never leaves the process.
- "Debug" drawer in the Manager page shows the tail with level filter and auto-refresh while open.
- **Verbose toggle (UX #4):** raises the logger to DEBUG. State lives **only in Manager process memory** (`manager/debug_log.py::_verbose`), resets to off on every Manager start, and is never persisted. It is set only by `POST /api/manager/v1/debug-log/verbose` from the local Manager UI: the route requires the loopback middleware **and** the Manager session token (`X-Anzu-Manager-Token`), and rejects requests whose `Origin` is not the Manager page itself (`http://127.0.0.1:4782` / `http://localhost:4782`) — the portal on 4780 can read the session token via `/session` but still cannot enable verbose (no remote enable, no LAN, no core-side setter).

### Button feedback (normative)

States per control button: `idle → pressed (≤100 ms) → working (spinner + elapsed seconds + phase text from the control endpoint: "Stopping…", "Waiting for health…") → success (green tick, 3 s) | failed (red, inline message, stays until dismissed)`. Other control buttons are disabled while one runs, with a tooltip saying why. Existing `confirm()` prompts are kept.

### Module script MIME type (normative, UX re-review)

S1 turns `app.js` into an ES module (`<script type="module">` in `static/index.html`). Browsers and WebView2 enforce a strict MIME check on module scripts and refuse one served as non-JavaScript, while the current classic script is tolerated. Verified on `development` @ `3f17c3d8`: `backend/app/manager/main.py` line 300 serves `/assets` with `app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")`, and Starlette's `StaticFiles` / `FileResponse` take `Content-Type` from Python `mimetypes`, which on Windows reads the registry, where `.js` is often mapped to `text/plain`. Without a fix, an affected Taco PC would lose the whole Manager UI, live Start/Restart/Stop buttons included.

- `backend/app/manager/main.py` calls `mimetypes.add_type("text/javascript", ".js")` at module level (`import mimetypes` with the other stdlib imports), **before** the `app.mount("/assets", …)` line, so every `/assets/*.js` response carries `text/javascript; charset=utf-8` whatever the registry says. It is a plain call, not wrapped in a try/except or behind a flag.
- `index.html` itself is served by `FileResponse` at `/admin` as `text/html` and is unaffected.
- This line is part of S1 (the slice that introduces the module). S2's `processes.js` is served by the same mount and needs no further `main.py` change.

### Process monitor (normative)

- Source: RFC-0225 S2 registry for ANZU-spawned processes. With the core healthy, the Manager reads `GET /api/system/processes`; with the core down, it reads `data_dir()/runtime/process-registry.json` directly and verifies each pid/create-time with psutil (so orphans left by a crashed core are visible).
- Columns: name/kind, pid, status (`running` / `exited (code)` / `orphaned`), CPU % measured over the 2 s refresh interval (psutil `cpu_percent(interval=None)` delta between consecutive refreshes; the first sample of a process reads "measuring…") (erratum 2026-10-20: a blocking 1 s sample per refresh cannot meet the p95 < 300 ms endpoint target below; the core-side value comes from RFC-0225 S2's `cpu_percent` / `sample_interval_s`, and with the core down `process_view.py` keeps per-pid `psutil.Process` objects the same way), RAM (RSS), GPU memory where the platform exposes per-process GPU usage (NVIDIA `nvidia-smi --query-compute-apps`; otherwise the cell reads "not reported by driver"), activity (`working` / `idle`), and **timer** "for 12m 03s" since the last activity change, plus uptime.
- Activity rules: llama-server → `/slots` `is_processing` (RFC-0210 probe); module workers / sidecars → CPU > 5 % averaged over 10 s = working; others → CPU rule. The rule used is shown in a tooltip.
- **Selected engine row (UX #1).** The engine ANZU talks to is listed even though ANZU did not spawn it: from RFC-0225 S3 `GET /api/model/engines` (rows classified `selected`, e.g. Taco's LM Studio, kind `lmstudio`, port 1234, pid + exe from the RFC-0225 identity check). Activity: `lms ps --json` when the `lms` CLI is available (LM Studio ≥ 0.3.27 reports each loaded model's generation status and its queued prediction requests): generating or queued > 0 → `working`, loaded and quiet → `idle`, none loaded → `unloaded`. When `lms` is missing, or its JSON has no generation status (older LM Studio), the activity cell reads **"not reported"**. The loaded-instance list may still come from `GET http://127.0.0.1:1234/api/v1/models`, but activity is never inferred from it (erratum 2026-10-20: the LM Studio REST API exposes loaded instances but no in-flight request state, so it cannot tell `working` from `idle`). When RFC-0225's `idle_unloaded()` hook is set for that engine (written by RFC-0228 S2), the row reads **"unloaded (idle) for 12m 03s"** with the timer from `unloaded_idle_at`. Core down → the Manager probes `:1234` itself and shows "core down — idle state unknown" instead of guessing.
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
| Manager page loads and runs `app.js` (all controls work) on any Windows `.js` registry mapping | **Yes**: the module switch is safe only together with the pinned `text/javascript` type, so both ship in S1 | `mimetypes.add_type("text/javascript", ".js")` in `main.py` + MIME regression test |
| Loopback-only middleware, session token, explicit confirm on control | **Yes** | Debug-log endpoint behind the same middleware |
| Tauri manager mode (`JARVIS_MANAGER=1`), tray Quit Manager | **Yes** | — |

Nothing is deleted. Each implement PR includes the preserved-behaviour section with screenshots.

### Stub rule

No stubs. A process screen fed by mock data, a GPU column that is always blank without saying why, or a log endpoint nothing writes to, is a fail.

---

## Relationship to drafts #648/#649

PG ruling via CoS (2026-10-20): no gate. #648/#649 do not touch `backend/app/manager/**`, `frontend/manager-controls.test.mjs` / `frontend/manager-processes.test.mjs` or this RFC's endpoints; nothing is ported. The selected-engine and idle-unload data come from RFC-0225 S3 (which ports the #648 `lmstudio_server._loaded_model_ids` inventory this screen reads through `/api/model/engines`).

**Reconciliation rule:** if a draft lands first and touches a file owned here, the slice reuses the draft's code and adds only this RFC's behaviour; if a slice lands first, the draft rebases onto it.

---

## Slices (one ticket each)

Assign order: **S1 → S2** (S2 also needs RFC-0225 S2).

### S1 — Manager debug logger + button feedback

**Model:** Composer 2.5 (fast off) · **Lane:** UX · **Depends:** none

| Path | Why |
| --- | --- |
| `backend/app/manager/debug_log.py` (new) | JSON-lines logger, rotation (2 MiB × 5), in-memory `_verbose` |
| `backend/app/manager/redact.py` (new) | Redaction rules above |
| `backend/app/manager/main.py` | `request_id` on control; phase reporting (`GET /api/manager/v1/control/progress`); `GET /api/manager/v1/debug-log`; `POST /api/manager/v1/debug-log/verbose` (local-only). For the module switch it owns **only** `import mimetypes` + `mimetypes.add_type("text/javascript", ".js")` before `app.mount("/assets", …)`; the script tag is not in this file |
| `backend/app/manager/supervisor.py` | Emit supervisor events to the debug logger (restart, backoff, crash-log preserved) |
| `backend/app/manager/static/app.js` | Becomes an ES module entry (same behaviour, same `confirm()`/`alert()` calls); wires buttons and the Debug drawer |
| `backend/app/manager/static/controls.js` (new) | Pure, DOM-free button state machine (`idle → pressed → working → success/failed`), elapsed formatting, phase text — exported for tests |
| `backend/app/manager/static/index.html` | Debug drawer markup + Verbose toggle; the script tag change `<script src="/assets/app.js">` → `<script type="module" src="/assets/app.js">` lives here (page served by `FileResponse` at `/admin`) |
| `backend/app/manager/static/style.css` | Pressed/working/success/failed styles in the existing design language |
| `tests/test_rfc0229_manager_debug.py` (new) | Below (alongside `tests/test_rfc0196_anzu_manager.py`, `tests/test_manager_supervisor.py`) |
| `tests/test_rfc0229_manager_js_mime.py` (new); `.github/workflows/pr-tests.yml` (one append-only `pytest`-job step `- name: Manager JS MIME type tests (RFC-0229 S1)` / `run: python -m pytest -q -rs tests/test_rfc0229_manager_js_mime.py`) | Module MIME regression test (below); also collected by the existing "Run full backend suite" step |
| `frontend/manager-controls.test.mjs` (new); `frontend/package.json` (`test:manager-controls`: `node --test manager-controls.test.mjs`, importing `../backend/app/manager/static/controls.js`); `.github/workflows/pr-tests.yml` (one append-only `frontend-build` step `- name: Manager control feedback tests (RFC-0229 S1)` / `run: npm run test:manager-controls`) | UX #3 |

- [ ] Each press writes `press` + `control_start` + `control_end` lines with the same `request_id`, `duration_ms`, `ok`.
- [ ] **(UX #2)** Redaction: a control request with `Authorization: Bearer x`, a spawn argv with `--api-key sk-1`, `--token=t`, `HF_TOKEN=h`, an env dict, an owner message body and a path under `data_dir()/investigations` → log and endpoint contain none of the secret values, `<n chars>` for the message and `<case-file>` for the path (test greps output); session token never appears.
- [ ] **(UX #2)** Disk cap: writing 30 MiB of events leaves at most 6 files, each ≤ 2 MiB, total ≤ 12 MiB.
- [ ] **(UX #4)** Verbose: off at start; local UI POST with token + Manager origin → DEBUG lines appear; Manager restart → off again; POST without token, with a foreign `Origin`, or from a non-loopback client → 403 and level unchanged; no file contains the verbose state.
- [ ] **(UX #3)** `npm run test:manager-controls` covers pressed ≤100 ms transition, working with elapsed, success auto-clear after 3 s, failed stays until dismissed, other buttons disabled while one runs; runs in `pr-tests.yml`.
- [ ] Debug-log endpoint returns the last N lines, rejects non-loopback (existing middleware test pattern).
- [ ] Button shows pressed within 100 ms, elapsed timer during a simulated 30 s restart, then success or the inline error; existing confirm texts unchanged.
- [ ] Log rotation honoured; RFC-0196 tests green.
- [ ] **(UX re-review)** `tests/test_rfc0229_manager_js_mime.py::test_manager_js_served_as_javascript_when_registry_says_text_plain`: in a fresh interpreter (`subprocess.run([sys.executable, "-c", …])` with `PYTHONPATH` = `backend/`, so the preset happens before `app.manager.main` is imported, as the Windows registry does) it first runs `mimetypes.add_type("text/plain", ".js")` and asserts `mimetypes.guess_type("x.js")[0] == "text/plain"` (preset took effect), then imports `app.manager.main` and with `TestClient(main.app)` asserts `GET /assets/app.js` and `GET /assets/controls.js` return 200 with `content-type` starting `text/javascript`. Removing the `add_type` line from `main.py` makes it fail. Runs in the "Manager JS MIME type tests (RFC-0229 S1)" step.
- [ ] `GET /admin` still returns `index.html` as `text/html` and it contains `<script type="module" src="/assets/app.js">`.

### S2 — Spawned-process monitor screen

**Model:** Grok 4.5 (fast off) · **Lane:** UX · **Depends:** S1 (sequential owner of `main.py` / static files), RFC-0225 S2 (registry), RFC-0225 S3 (`/api/model/engines` selected row + `idle_unloaded()` hook), RFC-0227 S1 (creates the Taco fixture `tests/fixtures/rfc0227_taco/lmstudio_1234_selected.json` used below) (erratum 2026-10-20: RFC-0227 S1 added)

| Path | Why |
| --- | --- |
| `backend/app/manager/process_view.py` (new) | Merge core `/api/system/processes` or the on-disk registry with psutil samples; selected-engine row from `/api/model/engines` + LM Studio native API / `lms ps`; idle-unloaded state; activity rules; timers; NVIDIA per-process GPU when available; output through `redact.py` (`argv_redacted` only) |
| `backend/app/manager/main.py` | `GET /api/manager/v1/processes` |
| `backend/app/manager/static/processes.js` (new) | ES module: pure row formatting (`formatRow`, timer text, "unloaded (idle) for …", "measuring…", "not reported") exported for tests + screen rendering, 2 s refresh while visible; emits nothing to the debug log itself |
| `backend/app/manager/static/index.html` / `style.css` | Processes link and table styles. `processes.js` loads through a **second** module tag, `<script type="module" src="/assets/processes.js"></script>`, after S1's `app.js` tag. The "Processes" link sits **right after** `<section id="cards">`, as a sibling, not inside it, because `app.js` rewrites `#cards` with `cards.innerHTML=…` on every 5 s refresh (`app.js:3`, `setInterval(refresh,5000)` at `:6`), which would delete a link placed inside (erratum 2026-10-20: the card-link placement and the single-script assumption are corrected) |
| `backend/app/manager/process_view.py` → `debug_log.py` | S2 emits the `process_view` event, already in S1's event enum ("Debug logger", `event` field), through S1's `debug_log` API from `process_view.py`: one line per registry-file fallback (core down), per newly detected orphan, and per sampling error, with `detail` redacted. `debug_log.py` stays S1's file, and S2 doesn't edit it (erratum 2026-10-20: names the slice that emits `process_view`) |
| `tests/test_rfc0229_process_view.py` (new) | Below (erratum 2026-10-20: each acceptance item now names its test functions; the Python names live in this file and the JS names in `frontend/manager-processes.test.mjs`) |
| `tests/test_rfc0229_manager_js_mime.py` (S1 file, extended sequentially) | Adds `/assets/processes.js` to the asserted list; no CI change (S1's step already runs the file) |
| `frontend/manager-processes.test.mjs` (new); `frontend/package.json` (`test:manager-processes`, importing `../backend/app/manager/static/processes.js`); `.github/workflows/pr-tests.yml` (one append-only step `- name: Manager process screen tests (RFC-0229 S2)` / `run: npm run test:manager-processes`) | UX #3 |

- [ ] `test_core_healthy_lists_every_registry_entry`: Core healthy → every RFC-0225 registry entry listed with status, CPU, RSS, activity and timer.
- [ ] `test_core_down_leftover_llama_server_is_orphaned` / `test_core_down_pid_reuse_not_listed`: Core stopped with a leftover llama-server → listed as `orphaned` from the on-disk registry; pid reuse (create-time mismatch) is not listed as ANZU's.
- [ ] `test_llama_server_busy_is_working_and_timer_resets`: llama-server busy fixture (`is_processing: true`) → `working`; timer resets on activity change.
- [ ] `test_gpu_cell_not_reported_without_driver` / `test_gpu_cell_mib_from_fixture`: No NVIDIA driver → GPU cell reads "not reported by driver"; with fixture data → MiB value.
- [ ] `test_taco_lmstudio_selected_row_activity_from_lms_ps` / `test_lmstudio_activity_not_reported_without_lms`: **(UX #1)** Taco fixture (RFC-0227 `lmstudio_1234_selected.json`): LM Studio :1234 row listed as selected, kind `lmstudio`, with the 9B instance and `idle`/`working` from a fake `lms ps --json`; `lms` missing → "not reported" (erratum 2026-10-20).
- [ ] `test_idle_unloaded_row_text` (Python) + JS `idle-unloaded row text` / `test_core_down_idle_state_unknown`: **(UX #1)** `idle_unloaded()` set 12 min ago for that engine → row reads "unloaded (idle) for 12m …" (Python + JS tests); core down → "core down — idle state unknown".
- [ ] `test_endpoint_returns_argv_redacted_only`: **(UX #2)** Endpoint returns `argv_redacted` only; a registry entry with `--api-key` never shows the value; no `argv` key in the payload.
- [ ] JS `formatRow`, `timer text`, `idle-unloaded row text`, `measuring placeholder on first sample`: **(UX #3)** `npm run test:manager-processes` covers row formatting, timers and the idle-unloaded text; runs in `pr-tests.yml`.
- [ ] `test_endpoint_p95_under_300ms_for_20_processes` / `test_polling_stops_when_hidden` (JS): Endpoint p95 < 300 ms for 20 processes; screen stops polling when hidden.
- [ ] (erratum 2026-10-20) `test_cpu_measured_over_refresh_interval` (fake psutil: no blocking sample; the first row `cpu` is `null` → "measuring…", the second is the delta over the faked 2 s); `test_process_view_events_logged` (core-down fallback, a new orphan and a sampling error each write one `process_view` debug-log line, redacted); `test_index_html_loads_processes_module_after_cards` (static: `index.html` has a second `<script type="module" src="/assets/processes.js">` after the `app.js` tag, and the Processes link is a sibling right after `<section id="cards">`, not inside it).
- [ ] **(UX re-review)** `tests/test_rfc0229_manager_js_mime.py` asserts `app.js`, `controls.js` **and** `processes.js` are served with `content-type` starting `text/javascript` with `.js` preset to `text/plain`; green in the "Manager JS MIME type tests (RFC-0229 S1)" step.

---

## Overall acceptance

- [ ] On Taco's PC: Manager Restart shows phases and elapsed time to completion; the debug drawer shows the press with request id and duration.
- [ ] Processes screen lists ANZU's worker llama-server, front lane, module workers and sidecars with live CPU/RAM, idle/working and timers; after killing the core, leftovers show as orphaned.
- [ ] All Live-UI rows preserved; RFC-0196 suite green.

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0229-S1 | Manager debug logger + button feedback | Composer 2.5 | UX | — |
| 0229-S2 | Spawned-process monitor screen (+ selected engine row) | Grok 4.5 | UX | S1, 0225-S2, 0225-S3 |

## Likely files

See ownership tables. Manager files are owned sequentially 0229-S1 → 0229-S2. No file here is owned by another RFC of the batch. Manager static files are bundled by the existing `--collect-all app` step in `scripts/build-backend-sidecar.ps1` and served by the existing `/assets` mount in `backend/app/manager/main.py` with the S1 `text/javascript` pin (new modules need no build change).

`frontend/package.json` and `.github/workflows/pr-tests.yml` are shared by every frontend ticket in the 2026-10-17 batch: each ticket adds exactly one `test:*` script line and one `frontend-build` step (append-only hunks, trivial rebase) and touches nothing else in those files. 0229-S1 additionally appends one `pytest`-job step (the Manager JS MIME type test), also append-only.

## Out of scope

- Persona/presence/WebGL/appearance (Astra).
- Stopping/restarting individual processes from the Manager.
- Foreign engines (RFC-0225 S4 prompt / Model page show those).
- Tauri tray menu changes.

## Risks

- **psutil cost on Windows** — sampling off the event loop, 2 s cadence only while visible.
- **Registry not yet landed** — S2 hard-depends on RFC-0225 S2 and S3; S1 ships independently.
- **`.js` served as `text/plain` on Windows** — the registry-driven `mimetypes` map would make WebView2 refuse the module and break the whole Manager UI; closed by the S1 `mimetypes.add_type("text/javascript", ".js")` line and its regression test, both required in the same PR as the `type="module"` switch.
- **Module script on older WebView2** — ES modules are supported by every WebView2 runtime ANZU ships with; the Manager page is also opened in the default browser, where they are universal.
