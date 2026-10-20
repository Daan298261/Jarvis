# RFC-0225: Local engine coexistence + resilient local-API connection

**Status:** accepted  
**Priority:** P0 (Taco bug batch 2026-10-17, bug 2 — highest impact)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20 (re-sliced 2026-10-20: lands on current `development` without drafts #648/#649; D2 review items 1–9 folded in)

**Owner ask (verbatim intent, 2026-10-17):** "Portal shows 'CANNOT REACH THE LOCAL API / Failed to fetch' even with a model loaded (GPU ~15%), status flickers between error and online. Root cause: concurrent model servers, LM Studio on :1234 vs ANZU's own. When ANZU starts, ask which other engines to kill, and respawn them later if needed. Also make the local-API connection resilient to this."  
**CoS follow-up (2026-10-20):** LM Studio is an engine ANZU can **drive**, not only stop (managed engine mode below; consumed by RFC-0228 S2).  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §7 ("ANZU should eliminate unnecessary approvals without eliminating meaningful control."), §8 ("Confidence should come from evidence rather than cheerful completion messages."), §9 ("The user chooses intent and policy. **ANZU chooses infrastructure.**"), §10, §19 ("Do expose state when the user needs confidence in what ANZU is doing."; "Do not remove useful capability merely to simplify the codebase."), §20 Q6 ("Can ANZU recover intelligently when the happy path fails?") and Q8.  
**Extends (do not rewrite):** [RFC-0210 running-model discovery](0210-running-model-discovery-and-owner-choice.md), [RFC-0091 LM Studio autostart](0091-lmstudio-autostart-and-chat-bubbles.md), [RFC-0093](0093-installer-force-stop-and-prepare-unstick.md) / [RFC-0136 zombie-kill](0136-zombie-kill-setup-next-and-start.md), [RFC-0105](0105-cybersecurity-module.md) (`modules/supervisor.py` pid-tracking pattern), [RFC-0196 ANZU Manager](0196-native-anzu-manager.md).  
**Astra boundary:** Persona, presence, WebGL and appearance are **out of scope** and stay Astra's. Nothing here edits `frontend/src/presence/**`, persona renderers or appearance settings. (Persona *brain runtime profiles* are read only to classify engines as `anzu_configured`.)

This PR is **specs-only**. No application code.

---

## Problem

Verified in `development` @ `3f17c3d8`:

1. **The red banner fires on a single failed poll.** `frontend/src/App.tsx` polls `/api/model` every 8 s; any rejected fetch immediately calls `setPortalApiError(err.message)` and the next success clears it. `frontend/src/hud/systemHealth.ts` turns that into "Portal cannot reach the local API". No debounce, no backoff.
2. **Status reads can stall the API event loop.** `/api/model` awaits `MANAGER.snapshot` plus `available_profiles()`, task outcome stats and benchmarks inline; `status_monitor.get_snapshot` awaits a full refresh on a cache miss; the LAN beacon (`backend/app/mobile/lan_beacon.py`) replies to *announcements* (including its own broadcasts) and runs Windows route/NIC probes on the API thread. Draft #648 measured exactly this class of stall.
3. **Several model servers compete for the same GPU.** ANZU spawns its own `llama-server` (`backends.py`, worker 8088, front 8089), can auto-start LM Studio on 1234 (`lmstudio_server.ensure_local_lmstudio` via `hotswap.py`) and Ollama (`ollama_runtime.ensure_local_ollama` via `hotswap.py` and the Umi persona brain in `api/named_personas.py`). Taco runs LM Studio (9B on `:1234`) and Ollama (`anzu-coder-27b`, ~12 GB, `:11434`; `docs/audits/2026-10-09-model-reuse-scheduler-manager.md`). RFC-0210 offers use/leave/stop/replace per row but nothing asks at startup, nothing remembers what was stopped, nothing respawns it, and **engines ANZU itself is configured to use (Ollama runtime profiles, the Umi brain) are treated like strangers**.
4. **No identity checks on ports.** `probe_remote_server` / `running_models.probe` accept any OpenAI-compatible responder on 8088 or 1234.
5. **No registry of ANZU-spawned processes** (llama-server, module workers incl. Crucix and BlackGrid, Supermemory, voice/STT/TTS subprocesses, LM Studio/Ollama started by ANZU).
6. **Root cause is asserted, not proven.**

## Decision

Ship **one RFC with five implement slices**, each one CoS-assignable ticket with one named model (**fast off**). Every slice lands on current `development`; none waits for #648/#649 (see "Relationship to drafts").

### Terms

| Name | Meaning |
| --- | --- |
| **ANZU-owned process** | A process in the S2 registry (spawned by ANZU; pid + create-time verified), or LM Studio / Ollama that ANZU itself started (`started_by: anzu`). |
| **Selected engine** | The endpoint in `settings.inference`. Taco's LM Studio :1234 serving `qwen3.5-9b-defiant-fable-uncensored` is **selected**, never foreign, never a stop candidate. |
| **ANZU-configured engine** (D2 #1) | Any engine whose endpoint (host:port, provider) is referenced by an **enabled** runtime profile (`backend/app/inference/runtime_profiles.py::list_runtime_profiles`, `enabled == True`) or by a persona brain runtime (`persona/persona_brain.py::brain_runtime_name_for_persona` → runtime profile; e.g. Umi on Ollama). Never a stop candidate; it may be *respawned* or *revived* by ANZU like the selected engine. |
| **Foreign engine** | A detected local inference server that is none of the above. Only foreign engines appear in the stop prompt. |
| **Managed engine mode** | Owner-consented, remembered, revocable per-engine flag (`manage: true` in `engine-choices.json`) for the **selected** LM Studio engine. On: ANZU may load / unload / reload **any** instance of the selected model(s) there, including owner-loaded ones (RFC-0228 S2 applies idle unload and re-warm; S3 here applies the VRAM gate). Off (default): ANZU only touches instances it loaded. Never stops the LM Studio server/app. |
| **Engine ledger** | `data_dir()/runtime/engine-ledger.json`: every foreign engine ANZU stopped with owner consent — kind, port, exe, argv (redacted), served model ids, stop method, `stopped_at`, respawn method, `respawn_on_exit`. |
| **Respawn** | Restarting an engine **process** that is in the ledger (owner-stopped via ANZU). |
| **Revive** | Starting the **selected or ANZU-configured** engine's server when it is not listening (e.g. LM Studio :1234 dead) via `ensure_local_lmstudio` / `ensure_local_ollama`. Not a respawn; never touches the ledger. |
| **Reload** | Loading a model instance into an engine that is already listening (e.g. the 9B after an idle unload, RFC-0228 S2). Not a respawn, not a revive. |

### Owner-consequential rule (normative)

1. **Never stop silently.** Every stop follows an explicit owner choice in the S4 prompt or the existing RFC-0210 row buttons. No timer, decision class or model may stop an engine on its own.
2. Only **foreign** engines are listed (selected, ANZU-configured and ANZU-owned are excluded), each with port, process + executable, served/loaded model ids, busy state.
3. Per engine: **Keep running** / **Stop now** / **Stop now and whenever ANZU starts**; "Remember my choice" optional, off by default; remembered choices visible and revocable on the Model page.
4. Stop uses only verified mechanisms (RFC-0210 code reused): LM Studio → native unload then `lms server stop` if chosen; Ollama → `keep_alive: 0` unload (server left up unless chosen); llama-server → `stop_listener` (pid + create-time + listener re-verification). Editors/agents (Cursor, Aider, Antigravity) are never stop targets.
5. Every successful stop writes the ledger **before** returning success; failed verification writes nothing.
6. **Respawn on demand** and **respawn on exit** (owner-ticked, default off) as below; failures surfaced, never swallowed.
7. Busy engines are never stopped ("Ask me again when it is idle").
8. **Managed engine mode** is asked once (S4) when the selected engine is LM Studio: "Let ANZU manage LM Studio models (unload when idle, reload when needed, make room for the coding model)". Off by default; remembered; revocable on the Model page.

### Engine preparation path (normative; D2 #2, #3)

One function, `engine_coexistence.prepare_engine_for(target)` (`target` = runtime profile or inference settings + model id), is the **only** place that revives, respawns, reloads-on-demand-precheck or VRAM-gates before a model is used. Callers (wired by S3, with tests):

- `backend/app/inference/hotswap.py::activate_runtime_profile` (covers `api/runtime_profiles.py`, `api/lmstudio.py`, `api/named_personas.py` persona brain) — before the provider probe.
- `backend/app/inference/manager.py::ensure_runtime` and `_load_locked` (router / chat request path, e.g. `persona/inference_context.py`) — before the probe when the target endpoint is not ANZU's managed llama-server.

Order inside `prepare_engine_for`:

1. **Single-flight.** One in-flight preparation per `(engine, model)`; concurrent requests await the same future. Guarantees no double reload/revive/respawn.
2. **Engine listening?** If the target engine has no listener: ledgered → **respawn** (ledger method), owner line "Restarted Ollama for anzu-coder-27b."; selected / ANZU-configured → **revive** (`ensure_local_lmstudio` / `ensure_local_ollama`), owner line only on failure or if the revive took > 5 s; foreign and not ledgered → not started (the request fails visibly).
3. **Identity.** For LM Studio :1234 and Ollama :11434 the listener must belong to the expected process family (`lms`/LM Studio executable resolved by `lmstudio_server.lmstudio_cli()/lmstudio_app_path()`, `ollama`), pid + create-time recorded; otherwise `port_conflict` (D2 #4), surfaced, nothing loaded.
4. **Model loaded?** Uses native inventory (`_loaded_model_ids`, ported from #648). If the model was idle-unloaded by RFC-0228 S2 (state `unloaded_idle_at` recorded by 0228-S2 through `engine_coexistence.note_idle_unload()`), this is a **reload**, delegated to the 0228-S2 reload routine once it exists; before 0228-S2 lands, the existing `ensure_local_lmstudio(model=…)` load path is the reload. A server left running with no model after an idle unload is never "dead", never "foreign", never offered.
5. **VRAM gate for large models.** Before loading a model whose requirement is known (catalog / graded profile `weight_gb` + context estimate; `anzu-coder-27b` ≈ 12 GB), free VRAM is measured (NVML via `pynvml` if importable, else `nvidia-smi --query-gpu=memory.free`; no NVIDIA GPU → gate skipped and logged). If free < requirement + 1 GB:
   - managed mode **on** → unload the selected LM Studio 9B instance(s) (native unload, verified), owner line "Unloaded the 9B in LM Studio to make room for anzu-coder-27b.", then load the 27B. Re-warming the 9B after the 27B idles is RFC-0228 S2.
   - managed mode **off** → nothing is unloaded; the request fails visibly with "anzu-coder-27b needs about 12 GB of GPU memory; 7.8 GB is free. Free GPU memory or turn on 'ANZU manages LM Studio models'." No blind load attempt.
6. Never unload while the 9B holds a request lease (stream, tool loop, task stage); the 27B preparation waits for the lease (bounded by the existing request deadline) and then proceeds.

### Resilience contract (normative; D2 #6, #7)

1. **Single source of truth for base URLs.** Frontend: `frontend/src/apiOrigin.ts::jarvisApiUrl` (verified: zero raw `fetch("/api…")`); S5 adds a guard test. Backend: new `backend/app/inference/endpoint.py::inference_base_url(settings)` used by `running_models.py` and `lmstudio_server.py` (S3).
2. **Health identity.** `/api/health` already embeds `startup_health.report()` as `startup`; `report()` adds `identity: {service: "anzu-core", instance_id, started_at}` (`instance_id` random per process start), so the check reads `health.startup.identity` and `main.py` is not touched by S5. `/api/health` stays auth-exempt (unchanged).
3. **Browser-observable states only.** `fetch` cannot distinguish "connection refused" from other network errors, so the portal state machine uses exactly: **network failure** (fetch rejected / aborted by timeout), **HTTP status** (response with status ≥ 500, or 401 handled as today), **identity mismatch** (reachable `/api/health` without `startup.identity.service == "anzu-core"`), **ok**. States: `online → suspect → offline(reason) → recovering → online`; `offline` only after ≥3 consecutive failures spanning ≥10 s; backoff 2 → 4 → 8 → 15 s (cap) while not online; `recovering → online` after 2 consecutive successes.
4. **Per mode (D2 #7):**
   - **Vite dev** (`window.location.port == "5173"`, `/api` proxied to 4780): identity mismatch → "Port 4780 is used by another program".
   - **Tauri shell** (`tauri.localhost`, absolute `http://127.0.0.1:4780`): identity mismatch → "Port 4780 is used by another program".
   - **Same-origin production** (portal served by 4780 itself): no port-conflict message (the page itself came from that server); identity comes from the same origin's `/api/health`; an `instance_id` change means ANZU restarted → caches refresh silently, no banner.
5. **Port conflicts on engine ports** (8088, 8089, LM Studio 1234, Ollama 11434) are model/engine issues shown on the Model page and in S4, never as "cannot reach the local API".

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

| Current live behaviour | Preserved? | Added alongside |
| --- | --- | --- |
| Health rail "Portal cannot reach the local API" with `ownerFacingApiMessage` detail and `/system` link | **Yes** — same title, link, text path | Debounce + browser-observable reason; mode-specific "Port 4780 is used by another program" |
| 401 auth guidance shown immediately | **Yes** | — |
| `/api/model` 8 s poll | **Yes** while online | Backoff only while not online |
| RFC-0210 offer (use / leave / stop / replace, hints, `window.confirm` on stop/replace); Model page scan | **Yes**, all kept | S4 prompt writes the same choices store; answered rows disappear from the offer as today |
| RFC-0210 spoken "I found another local model server…" | **Yes** (frequency is RFC-0227) | — |
| Identity-verified llama-server stop; editors never stopped | **Yes** | Ledger, respawn, revive |

Nothing is deleted. Each implement PR includes a "Preserved live behaviour" section with the test or screenshot per row.

### Stub rule

No stubs, scaffolding, TODO bodies, placeholder endpoints or soft-fails. A ledger that cannot respawn, a `prepare_engine_for` with no caller, or a health identity field nobody checks, is a fail.

---

## Relationship to drafts #648/#649

PG ruling via CoS (2026-10-20): the batch does **not** wait for Taco's draft PRs #648 (RFC-0223) and #649 (RFC-0224, stacked on #648). The pieces this RFC needs are **ported** (same behaviour, cited per slice as "Ported from #648 `<file>::<function>`"); everything else stays with the drafts.

| Draft piece | Decision | Slice |
| --- | --- | --- |
| #648 `mobile/lan_beacon.py` — reply only to `probe: true`, ≤8 bounded reply tasks, `_prepare_reply` / `_prepare_broadcast` via `asyncio.to_thread`, `close()` + `connection_lost()` | Ported | S1 |
| #649 `inference/status_monitor.py::get_snapshot` (miss → schedule refresh, return `status_refresh_pending`, never await) and `_fail_closed_snapshot` (uses `live_state_overlay`) | Ported | S1 |
| #649 `inference/model_details_cache.py` (new) + `api/model.py::model_status` reading `MODEL_DETAILS.read()` | Ported | S1 |
| #648 `api/system.py::system_info` (`_system_details` in `asyncio.to_thread`), `api/diagnostics.py` (`build_diagnostics` in thread), `swarm/nodes.py` / `swarm/capabilities.py` / `swarm/workers.py` (`hardware_dict` / catalog in thread), `inference/qwen38_local.py` (30 s bounded GGUF path cache) | Ported (endpoints polled by `App.tsx` / HUD) | S1 |
| #648 `main.py::_start_optional_step` (localhost node, hardware snapshot, MCP refresh, presence restore off the startup path; cancelled on shutdown) | Ported | S1 |
| #648 `inference/backends.py::probe_remote_server` (`not response.is_success` rejects 3xx/4xx) | Ported | S2 |
| #648 `inference/lmstudio_server.py` (`_loaded_model_ids`, model-ready check, start app/CLI only when not already serving, `encoding="utf-8"` in `_run_cli`) | Ported | S3 |
| #648 `inference/running_models.py::scan` (selected endpoint/model → `choice: "use"`), `decide` (`not MANAGER.state.loading` on leave), `_poll` (`settings.inference.auto_load` guard) | Ported | S3 |
| #648 `main.py::_autoload_model` (no waiting for discovery choices; LM Studio boot via `ensure_local_lmstudio`; fallback does not overwrite the saved selection) | Ported | S3 |
| #648 `api/voice_profiles.py`, `api/named_personas.py`, `api/custom_presence.py` sync handlers; `front_runtime.py` decide in thread | Not needed (not polled by the reachability path); stays in #648 | — |
| #648 `App.tsx` lazy pages + `components/PageBoundary.tsx` | Not needed (bundle size, not reachability); S5 touches only the `/api/model` poll effect | — |
| #648 `config.py` settings merge/atomic write + `gguf_path`, `manager.py` `_same_endpoint` / cancelled-load cleanup, `hotswap.py` persist-after-success, `api/model.py::load_model` `gguf_path` reset | Ported in RFC-0228 S2 (after this RFC's S3 in the file chains), not here | — |
| #649 front/fast-chat, task workflow, `profiles.py` `front_08b`, `runtime_install.py` | Not needed by this RFC | — |

**Reconciliation rule:** if a draft lands first, the slice reuses the draft's code for the ported piece (no duplicate function, no second implementation) and only adds what the slice specifies beyond it. If a slice lands first, the draft rebases onto the slice and drops its now-identical hunk. Ported tests live in new `tests/test_rfc0225_*.py` files so they never collide with the drafts' `tests/test_rfc0223_*` / `test_status_read_responsiveness.py` / `test_beacon_responsiveness.py`; on reconciliation the duplicate test is deleted from whichever side lands second.

---

## Slices (one ticket each)

Assign order: **S1 → S2 → S3 → S4 ∥ S5** (S5 may start after S1).

### S1 — Root-cause evidence + ported event-loop stall fixes

**Model:** Grok 4.5 (fast off) · **Lane:** D1 · **Depends:** none

Reproduce on Taco's Windows profile (LM Studio :1234 with the 9B, Ollama `anzu-coder-27b`, ANZU installed) and a clean profile. Capture: portal network log of failed `/api/model`, backend event-loop lag samples, `netstat -ano` for 1234/8088/8089/11434/4780, `nvidia-smi` VRAM per process, backend logs. Decide which hypothesis holds (concurrent servers/VRAM pressure, event-loop blocking, port collision, backend restart) and record numbers before and after the ported fixes.

| Path | Why |
| --- | --- |
| `docs/audits/2026-10-20-local-api-flicker-root-cause.md` (new) | Evidence, conclusion, before/after |
| `backend/app/mobile/lan_beacon.py` | Ported from #648 (see table) |
| `backend/app/inference/status_monitor.py` | Ported from #649 `get_snapshot` / `_fail_closed_snapshot` |
| `backend/app/inference/model_details_cache.py` (new) | Ported from #649 |
| `backend/app/api/model.py` | `model_status` uses `MODEL_DETAILS.read()` (ported from #649); first owner in the chain S1 → S3 → RFC-0227 S1 → RFC-0228 S2 |
| `backend/app/api/system.py`, `backend/app/api/diagnostics.py`, `backend/app/swarm/nodes.py`, `backend/app/swarm/capabilities.py`, `backend/app/swarm/workers.py`, `backend/app/inference/qwen38_local.py` | Ported from #648 (thread offload / bounded cache) |
| `backend/app/main.py` | `_start_optional_step` ported from #648; first owner in the chain S1 → S2 → S3 |
| `tests/test_rfc0225_api_responsiveness.py` (new) | Ported equivalents of #648 `test_beacon_responsiveness.py` / `test_status_read_responsiveness.py` cases + #649 status-monitor cases |
| `tests/test_rfc0225_flicker_repro.py` (new) | Repro of the confirmed engine-side mode, marked `@pytest.mark.xfail(strict=True, reason="fixed by RFC-0225 S2")`; S2 removes the marker |

- [ ] Audit names the confirmed root cause(s) with evidence; rejected hypotheses listed with the evidence that rejected them; before/after loop-lag numbers recorded.
- [ ] LAN beacon never replies to announcements; probe replies ≤8 concurrent; payload/route work runs off the event loop (ported tests pass).
- [ ] `/api/model` returns ≤300 ms while `available_profiles`, outcomes and benchmarks are artificially slowed (5 s fakes); status cache miss returns `status_refresh_pending: true` immediately.
- [ ] `/api/system`, `/api/diagnostics`, swarm node/capability endpoints keep the event loop free under slowed `hardware_dict` / catalog fakes.
- [ ] Repro test (foreign responder on the managed llama-server port accepted as healthy) is `xfail(strict=True)` naming S2; CI stays green.

### S2 — ANZU process registry + identity-checked managed server

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S1

| Path | Why |
| --- | --- |
| `backend/app/runtime/process_registry.py` (new) | `register(kind, pid, create_time, argv, port, owner_module, lifetime)`, `unregister`, `snapshot()`, `is_anzu_owned(pid, create_time)`, `registered_subprocess(...)` async context manager for short-lived children; argv stored **redacted** (secret flags `--api-key`, `--token`, `--password`, `--hf-token`, `--key`, `--secret` and any `KEY=VALUE` env-style arg with a secret-like key are replaced by `***`); atomic persist to `data_dir()/runtime/process-registry.json` |
| `backend/app/inference/backends.py` | Register/unregister managed llama-server (worker + front); pre-spawn port check → `port_conflict`; health accepts only listener pid == registered pid; `probe_remote_server` rejects non-2xx (ported from #648) |
| `backend/app/modules/supervisor.py` | Register module workers — covers `modules/crucix_runtime.py` (Crucix `node server.mjs`) and `studio/blackgrid_runtime.py` (BlackGrid), which spawn through `get_supervisor(...).start` (D2 #4) |
| `backend/app/modules/supermemory_runtime.py` | Register the Supermemory sidecar |
| `backend/app/workers/voice.py` | Register voice/STT subprocesses: ffmpeg conversion, whisper.cpp CLI, SAPI STT PowerShell (short-lived, via `registered_subprocess`); first owner in the chain S2 → RFC-0226 S2 |
| `backend/app/tts/system_sapi.py` | Register SAPI PowerShell synthesis subprocesses (short-lived) |
| `backend/app/tts/synthesize.py` | Register the Piper CLI subprocess (short-lived) |
| `backend/app/api/processes.py` (new) | `GET /api/system/processes` → registry snapshot + live status (running/exited/orphaned, CPU %, RSS), argv never returned raw (redacted form only) |
| `backend/app/main.py` | Include the processes router; terminate/unregister registered long-lived children on shutdown (existing order kept); second owner in the chain S1 → S2 → S3 |
| `tests/test_rfc0225_process_registry.py` (new); `tests/test_rfc0225_flicker_repro.py` | Below; remove the xfail marker |

- [ ] Every spawn site above registers on start and unregisters on exit (incl. Crucix and BlackGrid via the supervisor, voice/STT/TTS short-lived children); a crashed child reports `exited` with exit code.
- [ ] Registry survives a core restart; stale entries (pid reused / create-time mismatch) are pruned, never killed.
- [ ] Foreign listener on 8088 before spawn → `port_conflict` with process name/pid; no spawn.
- [ ] Managed health rejects a responder on 8088 whose pid is not the registered child; `tests/test_rfc0225_flicker_repro.py` passes with the xfail marker removed.
- [ ] Registry file and API never contain a secret argv value (test with `--api-key sk-…`, `HF_TOKEN=…`).
- [ ] `GET /api/system/processes` ≤300 ms with 20 entries (psutil off the event loop).

### S3 — Engine classification, owner-consented stop, ledger, respawn/revive, VRAM gate, managed mode

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S2

| Path | Why |
| --- | --- |
| `backend/app/inference/running_models.py` | Classify rows `anzu_owned` / `selected` / `anzu_configured` / `foreign` (S2 registry, `settings.inference`, enabled runtime profiles, persona brain runtimes); engine kind + exe on rows; ported #648 `scan`/`decide`/`_poll` pieces; reuse `stop_listener` / `verify_unloaded`; first owner in the chain S3 → RFC-0227 S1 |
| `backend/app/inference/engine_coexistence.py` (new) | Startup check (non-blocking), prompt payload, `engine-choices.json` (incl. `manage`, `is_managed(engine)`), stop per the rule, ledger, `respawn()`, `revive()`, `prepare_engine_for()` (single-flight, identity, VRAM gate), `note_idle_unload()` / `idle_unloaded()` hooks for RFC-0228 S2, on-exit respawn |
| `backend/app/inference/endpoint.py` (new) | `inference_base_url(settings)` |
| `backend/app/inference/lmstudio_server.py` | Ported #648 pieces; `started_by: anzu` + registry entry when ANZU launches LM Studio; `stop_lmstudio_server()`; listener identity for :1234; first owner in the chain S3 → RFC-0228 S2 |
| `backend/app/inference/ollama_runtime.py` | `started_by: anzu` + registry entry when ANZU starts Ollama; listener identity for :11434 |
| `backend/app/inference/vram.py` (new) | Free-VRAM measurement (NVML or `nvidia-smi`), "no NVIDIA GPU" result |
| `backend/app/inference/hotswap.py` | Call `prepare_engine_for` in `activate_runtime_profile` before the probe; first owner in the chain S3 → RFC-0228 S2 |
| `backend/app/inference/manager.py` | Call `prepare_engine_for` in `ensure_runtime` / `_load_locked` for non-managed endpoints; first owner in the chain S3 → RFC-0228 S2 |
| `backend/app/main.py` | `_autoload_model` ported from #648; shutdown → on-exit respawn; third owner in the chain S1 → S2 → S3 |
| `backend/app/api/model.py` | `GET /api/model/engines` (rows with class, kind, port, pid/exe, model ids, busy, `idle_unloaded_at` from the hook — read by RFC-0229 S2), `POST /api/model/engines/decision` (`keep` / `stop` / `stop_always`, `remember`, `respawn_on_exit`, `manage`), `GET /api/model/engines/ledger`, `POST /api/model/engines/{id}/respawn` |
| `tests/test_rfc0210_running_models.py` | **Exactly** the #648 fixture changes, every other assertion kept: (a) `test_valid_server_uses_metadata_only` parametrized over ports 1235 and 11434; (b) `test_background_reconnect_requires_existing_owner_choice` sets `settings.inference.auto_load = True`; (c) `test_startup_waits_for_owner_choice_before_loading_worker` renamed `test_startup_loads_saved_model_without_waiting_for_discovery` with assertion `load.assert_awaited_once_with(settings, context_size=settings.inference.context_size)` (behaviour change required by the non-blocking startup prompt) |
| `tests/test_rfc0225_engine_coexistence.py` (new) | Below |

- [ ] Taco's selected LM Studio :1234 (`qwen3.5-9b-defiant-fable-uncensored`) → `selected`, never a stop candidate.
- [ ] **(D2 #1)** Ollama referenced by an enabled runtime profile, and Ollama used by the Umi persona brain runtime, → `anzu_configured`, never listed for stopping; the same Ollama with the profile disabled and no persona reference → `foreign`.
- [ ] No code path stops an engine without a recorded owner decision (stop functions reachable only from the decision endpoint and the RFC-0210 choice endpoint).
- [ ] Busy engine → decision rejected "in use"; nothing stopped. Successful stop writes a ledger entry; failed verification writes nothing.
- [ ] **(D2 #2)** `activate_runtime_profile` for a profile whose engine is ledgered → respawned, healthy, attached, one owner line; chat request routed via `MANAGER.ensure_runtime` to a ledgered engine → same. Respawn failure → visible error, request fails.
- [ ] **(D2 #3)** LM Studio :1234 selected and not listening → revived via `ensure_local_lmstudio`, ledger untouched; LM Studio listening with the 9B idle-unloaded (`idle_unloaded()` true) → reload path, no revive, no respawn, no prompt.
- [ ] **(D2 #3)** Two concurrent requests needing the same reload/revive/respawn → exactly one start/load call (single-flight).
- [ ] **(D2 #3)** 27B request, free VRAM < 13 GB, managed mode on → 9B instance unloaded (verified), one owner line, 27B loaded; managed mode off → no unload call, request fails with the "needs about 12 GB … free" message; no NVIDIA GPU → gate skipped and logged.
- [ ] **(D2 #3)** 9B holding a request lease → no unload until the lease ends.
- [ ] **(D2 #4)** Non-LM-Studio process listening on 1234 (or non-Ollama on 11434) → `port_conflict` with process name/pid; nothing loaded.
- [ ] `manage: true` persisted, survives restart, returned by `is_managed()`; `manage: false` reverts immediately; `manage` rejected for non-selected or non-LM-Studio engines; managed mode never stops the LM Studio server/app.
- [ ] `respawn_on_exit` honoured on shutdown; remembered `stop_always` applies on next start and the startup line names what was stopped.
- [ ] Startup autoload does not wait for discovery choices (ported #648 behaviour) and a failed LM Studio boot does not overwrite the saved selection.

### S4 — Startup engine prompt + managed-mode question (UI)

**Model:** Composer 2.5 (fast off) · **Lane:** UX · **Depends:** S3

| Path | Why |
| --- | --- |
| `frontend/src/hud/EngineCoexistencePrompt.tsx` (new) | Non-modal card: foreign engines (port, process, model ids, busy); Keep / Stop now / Stop whenever ANZU starts; "Remember my choice" (off); "Restart it when ANZU closes"; per-row pending + result; one-time "Let ANZU manage LM Studio models" question when LM Studio is selected |
| `frontend/src/hud/HudShell.tsx` | Mount next to the existing `<RunningModels />` mount (unchanged); first owner in the chain S4 → RFC-0226 S3 |
| `frontend/src/pages/Model.tsx` | "Other engines": remembered choices (revocable), ledger with "Restart now", "ANZU manages LM Studio models" toggle |
| `frontend/engine-coexistence.test.mjs` (new); `frontend/package.json` (`test:engine-coexistence`, one line); `.github/workflows/pr-tests.yml` (one append-only `frontend-build` step `- name: Engine coexistence prompt tests (RFC-0225 S4)` / `run: npm run test:engine-coexistence`) | Below |

- [ ] Prompt shows only when S3 reports ≥1 foreign engine without a remembered choice, or LM Studio is selected and `manage` is unanswered; never blocks chat or the HUD.
- [ ] Rows show port, process/executable, model ids, busy state; Stop disabled for busy rows with the reason.
- [ ] Selected and ANZU-configured engines never appear as stop rows (fixture with Taco's LM Studio + Umi Ollama).
- [ ] Answers go through `POST /api/model/engines/decision`; answered rows disappear from the RFC-0210 offer.
- [ ] Managed-mode question asked once (default off), remembered, shown as a toggle on the Model page that writes `manage`.
- [ ] Preserved-live-behaviour section; build + lint; the new JS test runs in `pr-tests.yml`.

### S5 — Debounced, identity-checked local-API reachability

**Model:** Grok 4.5 (fast off) · **Lane:** UX · **Depends:** S1

| Path | Why |
| --- | --- |
| `frontend/src/hud/apiReachability.ts` (new) | Pure state machine per the resilience contract (network failure / HTTP status / identity mismatch / ok; thresholds; backoff; per-mode messages) |
| `frontend/src/App.tsx` | Only the `/api/model` poll effect: feed results into the state machine; same `collectHealthIssues` call |
| `frontend/src/apiOrigin.ts` | Export `apiMode()` (`vite-dev` / `tauri` / `same-origin`) and the health-identity check (base URL logic unchanged) |
| `backend/app/startup_health.py` | `report()` adds `identity: {service, instance_id, started_at}` (surfaced in `/api/health` through the existing `startup` key) |
| `frontend/api-reachability.test.mjs` (new); `frontend/package.json` (`test:api-reachability`); `.github/workflows/pr-tests.yml` (one append-only step `- name: API reachability tests (RFC-0225 S5)` / `run: npm run test:api-reachability`); `tests/test_rfc0225_health_identity.py` (new) | Below |

- [ ] fail/ok/fail/ok over 30 s → zero `api` issues.
- [ ] 3 consecutive network failures over ≥10 s → banner "cannot reach" with reason "network"; 3× HTTP 503 → reason "HTTP 503"; 2 successes → cleared.
- [ ] Backoff 2/4/8/15 s while not online; 8 s cadence when online.
- [ ] Vite-dev and Tauri modes: reachable `/api/health` without `startup.identity.service == "anzu-core"` → "Port 4780 is used by another program". Same-origin mode: no such message; `instance_id` change → silent refresh, no banner.
- [ ] Guard test: no `frontend/src` file calls `fetch` with a raw `/api` path.
- [ ] 401 message unchanged; health identity fields present (pytest).

---

## Overall acceptance

- [ ] S1 audit merged; S1 repro passes after S2 removes its xfail.
- [ ] Taco's PC: LM Studio 9B selected + Ollama 27B + Umi brain → ANZU start: no red flicker over a 30-minute idle + chat soak; prompt lists no ANZU-configured engine; managed-mode question asked once.
- [ ] Managed mode on, coding request for `anzu-coder-27b` with the 9B resident on a 16 GB GPU → 9B unloaded with one line, 27B answers.
- [ ] No engine stopped without an owner decision over the soak (log audit).
- [ ] Live-UI rows preserved; frontend build + lint; full backend suite and JS tests green in CI.

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0225-S1 | Root-cause evidence + ported event-loop stall fixes | Grok 4.5 | D1 | — |
| 0225-S2 | Process registry + identity-checked managed server | Grok 4.6 | D1 | S1 |
| 0225-S3 | Engine classification, consented stop, ledger, respawn/revive, VRAM gate, managed mode | Grok 4.6 | D1 | S2 |
| 0225-S4 | Startup engine prompt + managed-mode question | Composer 2.5 | UX | S3 |
| 0225-S5 | Debounced identity-checked reachability | Grok 4.5 | UX | S1 |

## Likely files

See per-slice tables. Sequential ownership chains across the batch (never concurrent): `main.py` 0225-S1 → S2 → S3; `api/model.py` 0225-S1 → 0225-S3 → 0227-S1 → 0228-S2; `running_models.py` 0225-S3 → 0227-S1; `lmstudio_server.py` 0225-S3 → 0228-S2; `hotswap.py` 0225-S3 → 0228-S2; `manager.py` 0225-S3 → 0228-S2; `config.py` 0228-S1 → 0228-S2 (not edited here); `workers/voice.py` 0225-S2 → 0226-S2; `HudShell.tsx` 0225-S4 → 0226-S3.

`frontend/package.json` and `.github/workflows/pr-tests.yml` are shared by every frontend ticket in the 2026-10-17 batch: each ticket adds exactly one `test:*` script line and one `frontend-build` step (append-only hunks, trivial rebase) and touches nothing else in those files.

## Out of scope

- Persona, presence, WebGL, appearance (Astra).
- Remote (non-loopback) engines: never stopped, revived or respawned.
- Chooser popup frequency/responsiveness and dropdown persistence (RFC-0227).
- Idle unload and re-warm of the 9B (RFC-0228 S2; this RFC provides the VRAM gate and the hooks).
- Manager process screen UI (RFC-0229 S2).

## Risks

- **LM Studio CLI/API differences** → capability detection; when unload/stop is unsupported the owner gets "stop it in LM Studio" guidance and the row stays running; never a forced kill of `LM Studio.exe`.
- **VRAM estimate wrong** → gate uses catalog weight + context estimate + 1 GB headroom; a load that still fails surfaces the engine's error and the 9B is re-warmed by RFC-0228 S2.
- **Draft divergence** → reconciliation rule above; ported hunks cited by file/function.
