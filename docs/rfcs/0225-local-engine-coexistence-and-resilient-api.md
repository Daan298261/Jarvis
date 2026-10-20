# RFC-0225: Local engine coexistence + resilient local-API connection

**Status:** accepted  
**Priority:** P0 (Taco bug batch 2026-10-17, bug 2 — highest impact)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20 (re-sliced 2026-10-20; **#648 and #649 have landed** on `development` (`d214b6d`, `ee786dc`), so every port step is removed and line numbers are re-checked against `a44da353`; D2 review items 1–9 folded in; D2 re-review items 1–4 second re-review items 1–3 and third re-review items 1–3 of 2026-10-20 folded in)

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
2. **Status reads can stall the API event loop.** `/api/model` awaits `MANAGER.snapshot` plus `available_profiles()`, task outcome stats and benchmarks inline; `status_monitor.get_snapshot` awaits a full refresh on a cache miss; the LAN beacon (`backend/app/mobile/lan_beacon.py`) replies to *announcements* (including its own broadcasts) and runs Windows route/NIC probes on the API thread. Draft #648 measured exactly this class of stall; #648/#649 fixed these on `development` (see "Relationship to #648/#649").
3. **Several model servers compete for the same GPU.** ANZU spawns its own `llama-server` (`backends.py`, worker 8088, front 8089), can auto-start LM Studio on 1234 (`lmstudio_server.ensure_local_lmstudio` via `hotswap.py`), and talks to Ollama on 11434 through `ollama_runtime.ensure_local_ollama` (via `hotswap.py` and the Umi persona brain in `api/named_personas.py::_maybe_activate_persona_brain`). **`ensure_local_ollama` never starts Ollama:** when nothing listens it only polls `_wait_until_up` for `SERVER_WAIT_SECONDS` (45 s) and returns `server-down`; nothing in `ollama_runtime.py` / `gpu_prefer.py` runs `ollama serve`, `ollama_cli()` only searches `PATH`, and the persona-brain caller only logs the failure (`persona_brain_ollama_prepare_failed`). Taco runs LM Studio (9B on `:1234`) and Ollama (`anzu-coder-27b`, ~12 GB, `:11434`; `docs/audits/2026-10-09-model-reuse-scheduler-manager.md`). RFC-0210 offers use/leave/stop/replace per row but nothing asks at startup, nothing remembers what was stopped, nothing respawns it, and **engines ANZU itself is configured to use (Ollama runtime profiles, the Umi brain) are treated like strangers**.
4. **No identity checks on ports.** `probe_remote_server` / `running_models.probe` accept any OpenAI-compatible responder on 8088 or 1234.
5. **No registry of ANZU-spawned processes** (llama-server, module workers incl. Crucix and BlackGrid, Supermemory, voice/STT/TTS subprocesses, LM Studio/Ollama started by ANZU).
6. **Root cause is asserted, not proven.**

## Decision

Ship **one RFC with five implement slices**, each one CoS-assignable ticket with one named model (**fast off**). Every slice lands on current `development`, which already contains #648 and #649 (see "Relationship to #648/#649").

### Terms

| Name | Meaning |
| --- | --- |
| **ANZU-owned process** | A process in the S2 registry (spawned by ANZU; pid + create-time verified), or LM Studio / Ollama that ANZU itself started (`started_by: anzu`). |
| **Selected engine** | The endpoint in `settings.inference`. Taco's LM Studio :1234 serving `qwen3.5-9b-defiant-fable-uncensored` is **selected**, never foreign, never a stop candidate. |
| **ANZU-configured engine** (D2 #1) | Any engine whose endpoint (host:port, provider) is referenced by an **enabled** runtime profile (`backend/app/inference/runtime_profiles.py::list_runtime_profiles`, `enabled == True`) or by a persona brain runtime (`persona/persona_brain.py::brain_runtime_name_for_persona` → runtime profile; e.g. Umi on Ollama). Never a stop candidate; it may be *respawned* or *revived* by ANZU like the selected engine. |
| **Foreign engine** | A detected local inference server that is none of the above. Only foreign engines appear in the stop prompt. |
| **Managed engine mode** | Owner-consented, remembered, revocable per-engine flag (`manage: true` in `engine-choices.json`) for the **selected** LM Studio engine. On: ANZU may load / unload / reload **any** instance of the selected model(s) there, including owner-loaded ones (RFC-0228 S2 applies idle unload and re-warm; S3 here applies the VRAM gate). Off (default): ANZU only touches instances it loaded. Never stops the LM Studio server/app. |
| **Engine ledger** | `data_dir()/runtime/engine-ledger.json`, two sections. `stopped`: every foreign engine ANZU stopped with owner consent — kind, port, exe, argv (redacted), served model ids, stop method, `stopped_at`, respawn method, `respawn_on_exit`. `anzu_loads`: every model instance **ANZU itself loaded** into an engine it does not own as a process (LM Studio, Ollama) — engine id, model key, native instance id, context size, `loaded_at`, `loaded_by: "anzu"`; written by `engine_coexistence.record_anzu_load()` from every ANZU load path (`lmstudio_server.ensure_local_lmstudio` load in 0225-S3; the RFC-0228 S2 reload routine and its `gpu_prefer.ensure_ollama_gpu` warm), removed by `forget_anzu_load()` after a verified unload, and pruned when native inventory (`_loaded_model_ids`) no longer lists the instance. |
| **ANZU-loaded instance** | A model instance in the ledger's `anzu_loads`, or the worker model of ANZU's managed llama-server (an ANZU-owned process, `MANAGER`). ANZU may always unload it, managed mode on or off. Anything else loaded in LM Studio / Ollama is **owner-loaded**. |
| **Respawn** | Restarting an engine **process** that is in the ledger's `stopped` section (owner-stopped via ANZU). |
| **Revive** | Starting the **selected or ANZU-configured** engine's server when it is not listening (e.g. LM Studio :1234 dead) via `ensure_local_lmstudio` / `ensure_local_ollama` (the latter really starts `ollama serve`, see "Ollama start" below). Not a respawn; never touches the ledger's `stopped` section. |
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
4. **Model loaded?** Uses native inventory (`lmstudio_server._loaded_model_ids`, on `development` since #648). If the model was idle-unloaded by RFC-0228 S2 (state `unloaded_idle_at` recorded by 0228-S2 through `engine_coexistence.note_idle_unload()`), this is a **reload**, delegated to the 0228-S2 reload routine once it exists; before 0228-S2 lands, the existing `ensure_local_lmstudio(model=…)` load path is the reload. A server left running with no model after an idle unload is never "dead", never "foreign", never offered.
5. **VRAM gate for large models.** Before loading a model whose requirement is known (catalog / graded profile `weight_gb` + context estimate; `anzu-coder-27b` ≈ 12 GB), free VRAM is measured (NVML via `pynvml` if importable, else `nvidia-smi --query-gpu=memory.free`; no NVIDIA GPU → gate skipped and logged). If free < requirement + 1 GB:
   - **ANZU-loaded 9B (managed mode on or off; D2 re-review #1)** → unload it: the managed llama-server worker via `MANAGER.unload()`, an LM Studio instance in `anzu_loads` via native unload (`/api/v1/models/unload` with its instance id) verified by `_loaded_model_ids`, then `forget_anzu_load()`. One owner line "Unloaded the 9B ANZU loaded to make room for anzu-coder-27b.", then free VRAM is re-measured and the 27B is loaded. This is the default-install case (RFC-0228 makes the ANZU-loaded Fable 9B the default), so the coder loads without managed mode.
   - **owner-loaded 9B, managed mode on** → unload the selected LM Studio 9B instance(s) (native unload, verified), owner line "Unloaded the 9B in LM Studio to make room for anzu-coder-27b.", then load the 27B.
   - **owner-loaded 9B, managed mode off** → no unload call is issued for it; the request fails visibly with the owner-visible reason "anzu-coder-27b needs about 12 GB of GPU memory; 7.8 GB is free. The 9B in LM Studio was loaded by you, so ANZU left it alone. Unload it in LM Studio or turn on 'ANZU manages LM Studio models'." (the same text names Ollama when the owner-loaded model is in Ollama). No blind load attempt.
   - ANZU-loaded instances are unloaded first; if free VRAM is still short and only owner-loaded instances remain, the rule for owner-loaded instances applies.
   - Every unload here records `engine_coexistence.note_gate_unload(nine_b, heavy)` (read via `gate_unloaded()`, cleared via `clear_gate_unload()`). Re-warming that 9B is RFC-0228 S2's `NINE_B_REWARM`, only after the heavy model has left VRAM, never on the 120 s orchestrator restore (ANZU-loaded: always; owner-loaded: managed mode on only).
6. **Reverse direction: the 9B is needed while a heavy model is resident (D2 third re-review #3; Architect decision).** This is typically the first chat turn after a coding burst: `prepare_engine_for` gets the 9B worker target while `gate_unloaded()` is set or a heavy model sits in VRAM. Free VRAM is **measured** (same `vram.py`):
   - **free ≥ 9B requirement + 1 GB** → nothing is unloaded; the 9B loads through the normal reload path (single-flight), the gate-unload marker is cleared, and the heavy model stays resident.
   - **free short and the resident heavy model is ANZU-loaded** (in `anzu_loads`, e.g. `anzu-coder-27b` loaded by ANZU's coding request) and holds no request lease → unload it: Ollama `POST /api/generate {"model": <key>, "keep_alive": 0}`, verified by `/api/ps` no longer listing it (LM Studio: native unload verified by `_loaded_model_ids`). Then `forget_anzu_load()`, `clear_gate_unload()`, re-measure, and load the 9B through the **same** single prepare/reload path (the one RFC-0228 S2's `NINE_B_REWARM` uses, so a concurrent timer reload joins the same future). One owner line: `owner_line("Unloaded anzu-coder-27b to bring the 9B back for chat.", task_id=…)`.
   - **free short and the resident heavy model is owner-loaded** (not in `anzu_loads`, e.g. Taco started `anzu-coder-27b` from his shell) → never unloaded; the turn gets `owner_line("The 9B needs about 7 GB of GPU memory; 3.1 GB is free because anzu-coder-27b, which you loaded, is using it. Unload it in Ollama to bring the 9B back.", level="error", task_id=…)`. No blind load.
   - **The unload fails, or VRAM is still short afterwards** → no 9B load is attempted, and the turn gets `owner_line("Couldn't bring the 9B back: <engine error / 'only 3.1 GB free after unloading anzu-coder-27b'>.", level="error", task_id=…)` plus the health-rail item. It never fails silently.
   - **The owner is never left on silence.** This gate runs on the **worker** lane only. The turn's front lane (`agent/front_responder.py::run_two_lane_chat` yields front deltas first, `front_responder.py:1009–1022`; the 2B front model on ANZU's llama-server :8089 is resident by default, `config.py:120` `front_responder.resident = True`) answers immediately. The worker part follows once the 9B is loaded, or the failure line replaces it. If the front lane is disabled or not loaded, `owner_line("Bringing the 9B back, one moment.", task_id=…)` is spoken before the unload starts.
   - A **coding request** targets the heavy model, not the 9B, so it never triggers this rule and the 27B stays (RFC-0228 `test_coding_request_while_waiting_keeps_27b`). A heavy model holding a request lease is never unloaded; the 9B preparation waits for the lease (bounded by the request deadline), then re-checks.
7. Never unload while the 9B holds a request lease (stream, tool loop, task stage); the 27B preparation waits for the lease (bounded by the existing request deadline) and then proceeds.

### Ollama start (normative; D2 re-review #2)

`ollama_runtime.ensure_local_ollama` gains a real start, owned by S3; `revive()` reaches it through `prepare_engine_for` step 2.

1. **Binary resolution.** `ollama_cli()` keeps `shutil.which("ollama")` / `"ollama.exe"`, then (Windows) `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` (the Ollama installer's per-user default) and `%PROGRAMFILES%\Ollama\ollama.exe`; the first existing file wins. None found → `{"ok": False, "method": "missing-cli"}` with the existing text "Ollama is not installed. Re-run the Jarvis installer Umi brain option."; nothing is spawned.
2. **Only when nothing listens.** Loopback host only (remote → existing `skipped`). If the port has a listener that fails the probe, the S3 identity step decides (`port_conflict` for a non-Ollama process); ANZU never spawns a second server onto an occupied port.
3. **Detached spawn.** `start_local_ollama(host, port)` runs `[cli, "serve"]` via `subprocess.Popen` inside `asyncio.to_thread`, env = current env + `OLLAMA_HOST=<host>:<port>`, stdin `DEVNULL`, stdout/stderr appended to `data_dir()/logs/ollama-serve.log`; Windows `creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`, POSIX `start_new_session=True`. The server outlives the request that started it.
4. **Registry.** Immediately after spawn: `process_registry.register(kind="ollama", pid, create_time, argv=[cli, "serve"], port, owner_module="inference.ollama_runtime", lifetime="detached")` with `started_by: "anzu"`. `detached` entries are not terminated on ANZU shutdown (Ollama also serves the owner's own shell/tools); they stay in the registry so the next start classifies the server as ANZU-owned, and are pruned by S2's stale-entry rule once the pid is gone.
5. **Readiness poll.** `probe_remote_server(host, port, timeout=2.0, retry=False)` every `POLL_SECONDS` (1 s) until ok; if the spawned process exits first, stop polling at once.
6. **Timeout.** `SERVER_WAIT_SECONDS` (45 s, unchanged). On timeout ANZU terminates **only the pid it spawned** (registry pid + create-time verified), unregisters it and returns `{"ok": False, "method": "start-timeout", "detail": "Ollama did not answer on 127.0.0.1:11434 within 45 s. Last log line: …"}`. Early exit → `{"ok": False, "method": "start-exited", "detail": "Ollama exited with code N: <last log line>"}`.
7. **Owner-visible failure.** `prepare_engine_for` turns any non-ok revive into the owner line "Couldn't start Ollama: <detail>" (delivered through `owner_line(level="error")` per "Owner-line surfaces" below; never only a log line). In a request path the request also fails with that text. The persona-brain path (`api/named_personas.py::_maybe_activate_persona_brain`) stops calling `ensure_local_ollama` directly and calls `prepare_engine_for(profile)` instead, so a dead Umi brain is revived. That path runs as a FastAPI background task after `PUT /api/named-personas` has already returned (`background_tasks.add_task(...)`), so there is no request to fail: its failure reaches the owner only through the HUD chip + speech (surface 2) and the health-rail item (surface 3) below, and the line names the persona ("Couldn't start Ollama for Umi's brain: <detail>"). After a successful start the existing pull / warm steps run unchanged.

### Owner-line surfaces (normative; D2 second re-review #1, third re-review #1, #2)

**What the portal actually consumes on `development` @ `a44da353` (traced):**

- Spoken lines: the only path that reaches the speaker is the **task event stream**. `frontend/src/tts/useTaskSpeech.ts:64` opens `EventSource(getAuthUrl("/api/tasks/<id>/events"))`, and `:43` speaks only events with `kind == "chat_tts"` via `chatTtsPlayer.queueChatSpeech` (`tts/chatTtsPlayer.ts:134`). It is mounted only for the task open in the chat (`hud/HudChat.tsx:97`, `pages/Chat.tsx:50`). Backend producers publish `BUS.publish(task_id, "chat_tts", …)` (`agent/loop.py:1077`, `:1097`).
- Visible task lines: `chat/ownerChatView.ts:365` opens the same task stream. `filterWorkEvents` (`ownerChatView.ts:76–79`) shows every kind except `assistant_delta` / `chat_tts` / `replace_previous_text` (`:40`).
- **Not consumed:** `persona/chat_delivery.py::publish_owner_text` publishes on `OWNER_CHAT_CHANNEL` (`chat_delivery.py:71`, `:100`). That channel is served at `GET /api/owner/chat/events` (`api/owner_chat.py:65–78`), and the TTS queue `enqueue_chat_tts` is drained only by `GET /api/owner/chat/tts/pending` (`:83`). No file in `frontend/src`, `android/`, `extensions/` or the Manager subscribes to or polls either one. `running_models.py:341–347`'s "I found another local model server…" and RFC-0218's switch line (`tts/persona_speech.py::announce_persona_switch` → `publish_owner_text`) are orphaned the same way. **Architect decision (2026-10-20 15:15): the `running_models.py:341–347` notice is a live bug and is fixed in S3** (see "RFC-0210 offer notice" below). RFC-0218's switch line is handled by RFC-0218's handoff (PR #663). This RFC fixes only its title (`"Persona switch"`, see item 1). `publish_owner_text` itself (`chat_delivery.py`) stays as it is; only this one caller moves off it.

Most of this RFC's lines are not bound to an open task (startup check, persona brain, timers, profile activation), so the task stream alone cannot carry them. **S3 therefore ships the consumer, wired end to end:**

1. **One backend entry.** `engine_coexistence.owner_line(text, *, level="info"|"error", engine_id=None, task_id=None, title: str = "Local engines")` is the only way this RFC (and RFC-0228 S2) emits an owner line. **`title` (Architect decision 2026-10-20 15:19)** is optional. Every RFC-0225 and RFC-0228 line passes no title, so it keeps the default "Local engines" and nothing about those lines changes. **There are exactly two named exceptions:**
   - the moved RFC-0210 offer notice below passes `title="Available local models"`, its original title (Architect decision 2026-10-20 15:20), so the move preserves both title and text;
   - RFC-0218's no-task persona-switch line (`tts/persona_speech.py::announce_persona_switch`, from the `stream_owner_chat` path) is `engine_coexistence.owner_line(persona_switch_line(to), level="info", title="Persona switch")`, with no `task_id` (Architect decision 2026-10-20 15:22). The move off `publish_owner_text` follows RFC-0218's switch-line handoff (PR #663): whichever of RFC-0218 S3b and RFC-0225 S3 lands **second** makes that call, so this RFC fixes the `title` either way. When 0225-S3 is second it edits only that one call in `persona_speech.py` and adds `test_announce_persona_switch_uses_persona_switch_title`, listed below, to `tests/test_rfc0225_owner_lines.py`. When RFC-0218 S3b is second, it writes the call with this title and adds the same named test to its own `tests/test_persona_intent_switch_turn.py`. The parameter exists so another caller can name its own notice; RFC-0218's no-task persona-switch line (PR #663) passes `title="Persona switch"`. An empty title, or `"Speak reply"` (which would join the reply prefix at `useTaskSpeech.ts:48–50`), raises `ValueError`. It:
   - (a) **always** publishes `BUS.publish_ephemeral(OWNER_CHAT_CHANNEL, "engine_notice", title, json.dumps({"text", "level", "engine_id", "task_id", "id"}), stage="engine_coexistence")`. `id` is a uuid4, used for dedupe;
   - (b) when `task_id` is given (the request is a chat or task turn), **also** publishes on that task: `BUS.publish(task_id, "engine_notice", title, text, stage="engine")` (persisted and visible in the work panel through the existing `filterWorkEvents`) and `BUS.publish(task_id, "chat_tts", title, text, stage="engine")` (spoken by the existing `useTaskSpeech`; the title is not "Speak reply", so it never joins the reply prefix at `useTaskSpeech.ts:48–50`);
   - it does **not** call `publish_owner_text` (no orphaned `enqueue_chat_tts` entry).
   - `task_id` reaches `prepare_engine_for` as a keyword argument: `persona/inference_context.py::ensure_context_for_messages` already receives `task_id` (it forwards it to `maybe_autoselect_runtime_for_budget`) and now also passes it to `MANAGER.load(…, task_id=…)` / `MANAGER.ensure_runtime(…, task_id=…)` (`inference_context.py:79`, `:87`), which forward it to `prepare_engine_for`. `activate_runtime_profile`, the persona brain and timers pass none.
2. **The consumer (new, S3): `frontend/src/hud/EngineNotices.tsx` is a new HUD file. It adds one mount in `HudShell.tsx` next to the existing children and doesn't change how any existing live component behaves or renders** (add-alongside rule; see the live-UI table). The behaviour lives in a plain-TS controller, `frontend/src/hud/engineNotices.ts` (new): connect, `engine_notice` filter, dedupe, speak decision, backoff, and the classic failure poll. `EngineNotices.tsx` is a thin render of that controller, so the node tests import it the same way `owner-chat-turns.test.mjs` imports `ownerChatView.ts`. The controller takes its `EventSource` factory, `fetch`, clock and `speak` function as arguments; `EngineNotices.tsx` passes the real `getAuthUrl` stream, `api()`, timers and `queueChatSpeech`. Props: `variant: "hud" | "classic"` (position and styling only) and `openTaskId?: string`.
   - **Both UI modes (D2 fourth re-review #1).** `App.tsx:528–575` renders `HudShell` only when `uiMode === "hud"`. Classic is a supported, persisted mode (`hud/uiMode.ts:9–17`), and its branch (`App.tsx:577–686`) renders neither `HudShell` nor the health rail. Its self-check poll is HUD-only too (`App.tsx:289`, `if (uiMode !== "hud") return`). So the component has exactly two mounts, one per mode:
     - **HUD:** `<EngineNotices variant="hud" openTaskId={activeTaskId} />` in `HudShellInner` (`HudShell.tsx:276`), one added line directly after `<HelpPanel … variant="hud" />` (`HudShell.tsx:435`). It is **not** in `HudTopChrome` (`HudShell.tsx:73`, where `<HudLocalStatus …/>` sits at `:111`), because `HudTopChrome`'s props have no `activeTaskId` (it is destructured only in `HudShellInner`, `:288`), so a mount there would not compile.
     - **Classic:** `<EngineNotices variant="classic" openTaskId={currentTaskId} />` in `App.tsx`'s classic branch, one added line as the **last** child of `div.app`, directly after `</main>` (`App.tsx:683`). `div.app` is the live two-column grid (`index.css:29–33`: `display: grid; grid-template-columns: 260px 1fr`) with the children `header.mobile-bar`, `HelpPanel`, the conditional `nav-backdrop`, `aside.sidebar` and `main` (`App.tsx:579–683`). So the mount must never take a grid cell:
       - with no notice to show, `EngineNotices` **renders nothing (returns `null`)**, in both variants, so the grid's children are exactly today's;
       - when it shows notices, its only root element is `div.engine-notices.engine-notices--classic` (or `--hud`), styled `position: fixed` (classic: `right: 16px; bottom: 16px`; `z-index` above `main`, below `HelpPanel`; `pointer-events: none` on the container, `auto` on chips). A fixed-position child is out of flow and takes no grid cell, so the columns, rows and placement of every existing child are unchanged;
       - the styles live in a declared new file, `frontend/src/hud/engineNotices.css`, imported only by `EngineNotices.tsx`. No existing CSS file is edited;
       - being last, it shifts no existing child's sibling index.
       No existing classic child, prop or class changes, and `BootNova`, persona, WebGL and presence code is not touched.
       **`variant="classic"` also starts the self-check poll** described in "Classic failures stay visible" below; `variant="hud"` never does.
     The two branches are mutually exclusive `return`s, so exactly one instance is mounted in either mode and nothing is shown or spoken twice. There is one component, one controller and one speech path (`queueChatSpeech` + `useSpeakChatReplies`), with no classic copy.
   - **Classic failures stay visible.** Classic has no health rail, so the classic variant alone also polls the existing `GET /api/system/self-check` every 30 s while the tab is visible (the same endpoint and payload as `App.tsx:308`), and shows each `degraded` item whose id starts with `engines:` as a persistent error chip until that item clears. That covers failures whose live notice was missed while disconnected. The HUD variant doesn't poll, because the HUD rail already shows those items (item 3). It opens `EventSource(getAuthUrl("/api/owner/chat/events"))` and listens **only** for the SSE event name `engine_notice` (the server names SSE events by `kind`, `owner_chat.py:76`), so the reply / `chat_tts` traffic on that channel is ignored and nothing is spoken twice. For each notice (deduped by `id`):
   - it shows a non-blocking, dismissible HUD chip with the **title it receives** (the frame's `title`, which `owner_chat.py:76` forwards inside the SSE `data`; never hard-coded in the component, and "Local engines" only when the frame carries no title) above the text (error level styled as a warning, auto-hidden after 12 s for info);
   - it speaks the text through `queueChatSpeech` when `useSpeakChatReplies()` is on (same setting `HudChat.tsx:47` uses), **unless** `task_id` equals `openTaskId` (the task open in `HudChat` in HUD mode, or in `ChatPage`, which mounts `useTaskSpeech` at `pages/Chat.tsx:50`, in classic mode), because that line is already spoken by `useTaskSpeech` from the task stream;
   - on socket error it reconnects with 2 → 4 → 8 → 15 s backoff. Notices missed while disconnected are not replayed, but every failure also stays on the health rail (item 3).
3. **Persistent HUD health-rail item (failures).** Every failed revive, respawn, unload or reload also records `engine_coexistence.record_engine_failure(engine_id, text)`. `systems/self_check.py::run_self_check` appends **one item per engine** with a unique id, `_item(f"engines:{engine_id}", "Local engines", "degraded", <text>)`. `engine_id` is `<kind>@<host>:<port>` (e.g. `ollama@127.0.0.1:11434`, `lmstudio@127.0.0.1:1234`, `llama-server@127.0.0.1:8088`), and a second failure on the same engine replaces its text. `frontend/src/hud/systemHealth.ts::collectHealthIssues` turns each into `check-engines:<engine_id>` (`systemHealth.ts:49–58`), so the `<li key={issue.id}>` in `HudLocalStatus.tsx:46` gets distinct keys. **Add-alongside:** `systemHealth.ts` and `HudLocalStatus.tsx` are **not edited**; every existing item keeps its id, title, detail, link and rendering, and only new ids are added. The next successful prepare for that engine clears its item (`clear_engine_failure`).
4. **Request error (request paths only).** Chat / task / profile-activation requests fail with the same text and keep their existing error rendering.

**RFC-0210 offer notice (S3, Architect decision 2026-10-20).** On `development` @ `a44da353`, `RunningModels._poll` (`inference/running_models.py:339–348`, notice call `:341–347`, from RFC-0210 #584 / `64db8b8`; #648 changed only the `auto_load` guard at `:335`) calls `await publish_owner_text("I found another local model server. Would you like to use it, leave it alone, stop it, or replace it with ANZU's model? The choices are on screen.", title="Available local models", source="running_models", lane="front")`. The owner never sees or hears it, because the channel it publishes on has no client. S3 replaces that one call with `engine_coexistence.owner_line(<the same text, byte-identical>, level="info", engine_id=<first pending row's engine_id>, title="Available local models")`. The title is the original one, so both title and text are preserved. Everything else stays: same once-per-row `_notified` bookkeeping, same 20 s poll, same `except` / `self.error` handling, and the HUD `RunningModels.tsx` card is untouched. The notice is then shown as an `EngineNotices` chip and spoken when speak-replies is on. The import of `publish_owner_text` leaves `running_models.py`. The next owner of `running_models.py`, RFC-0227 S1 (aggregated, rate-limited notice), builds on this call, so its notice also goes through `owner_line()`. #648's `running_models.py` changes (`scan`, `decide`, the `_poll` `auto_load` guard) are already on `development`; S3 changes only the notice call.

Every owner line uses 1 (+ the task copy when a task is known) and the chip; failures also use 3 and, in a request path, 4. "One owner line" in every acceptance test below means: **exactly one `engine_notice` frame received by a `BUS.subscribe(OWNER_CHAT_CHANNEL)` queue and rendered by `EngineNotices`** (the JS test drives that frame); a `publish_owner_text` call never satisfies it.

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
| RFC-0210 "I found another local model server…" notice (`running_models.py:341–347`; today published on a channel with no client, so never heard or seen) | **Yes**: byte-identical text and the original title "Available local models", once per new row, same poll; frequency stays RFC-0227's | It now actually reaches the owner: published through `owner_line()` and shown + spoken by `EngineNotices` (S3) |
| Every existing HUD component in `HudShell.tsx` (`PortalNav`, `HudLocalStatus`, `HelpTrigger`, `HudModelSelector`, `RunningModels`, `HudStarfield`, `HudTopChrome`, `HelpPanel`, `HudOpsRail`, `HudHealthRail`, `HudBottomChrome`) and their order, props and rendering | **Yes**: none edited; `HudShell.tsx` gets exactly one added line | `frontend/src/hud/EngineNotices.tsx` is a new HUD file. It adds one mount in `HudShell` next to the existing children and doesn't change how any existing live component behaves or renders |
| Classic portal layout: the `div.app` two-column grid (`index.css:29–33`) and its children in `App.tsx:577–686` (mobile bar, `HelpPanel`, `nav-backdrop`, sidebar with `ProjectsRail` / nav / `side-status` / "Switch to HUD UI", `main` with routes) and every classic component | **Yes**. No current classic behaviour changes: no existing classic component, prop, class or order is edited, and the classic branch gets exactly one added line, last in `div.app`. With no notice it renders `null`, so the grid's children are unchanged; with notices its single root is `position: fixed` (`engineNotices.css`), out of grid flow, so no column or row moves | `<EngineNotices variant="classic" …/>`: the same `EngineNotices` component and controller as the HUD mount and the same speech path. It shows and speaks owner lines (including the RFC-0210 offer notice and failures) in classic mode, which today receives none of them |
| RFC-0218 no-task persona-switch line (`announce_persona_switch`, today `publish_owner_text`, never heard or seen) | **Yes**: same `persona_switch_line(to)` text | Delivered through `owner_line(…, title="Persona switch")`; the chip shows "Persona switch" (handoff per RFC-0218 PR #663) |
| Health rail items from `systemHealth.ts` / `HudLocalStatus.tsx` | **Yes**: files not edited | Per-engine `engines:<engine_id>` items (S3 backend, S4 rendering test) |
| Identity-verified llama-server stop; editors never stopped | **Yes** | Ledger, respawn, revive |

Nothing is deleted. Each implement PR includes a "Preserved live behaviour" section with the test or screenshot per row.

### Stub rule

No stubs, scaffolding, TODO bodies, placeholder endpoints or soft-fails. A ledger that cannot respawn, a `prepare_engine_for` with no caller, or a health identity field nobody checks, is a fail.

---

## Relationship to #648/#649 (landed)

#648 (RFC-0223, merged as `d214b6d`) and #649 (RFC-0224, `ee786dc`) are on `development`. This RFC builds on their code and tests as they are and ports nothing. Pieces it relies on:
- `mobile/lan_beacon.py` (probe-only replies, bounded tasks), `status_monitor.get_snapshot` (`status_refresh_pending`), `model_details_cache.py`, `api/system.py` / `api/diagnostics.py` / swarm thread offload, the 30 s GGUF path cache (`qwen38_local._PATH_CACHE`), `main._start_optional_step`. Their tests are `tests/test_beacon_responsiveness.py`, `tests/test_status_read_responsiveness.py` and `tests/test_rfc0223_startup_model_stability.py` (e.g. `test_optional_startup_step_does_not_delay_event_loop`, `test_repeated_discovery_uses_bounded_cache`, `test_probe_rejects_error_and_redirect_responses`). S1 measures against them; no slice re-implements or duplicates them.
- `backends.probe_remote_server` rejects non-2xx; `lmstudio_server._loaded_model_ids` and the start-only-when-not-serving check; `running_models.scan` / `decide` / the `_poll` `auto_load` guard; `main._autoload_model` (no waiting for discovery choices, saved selection kept on a failed LM Studio boot). S2 and S3 call these and only add this RFC's behaviour.
- `tests/test_rfc0210_running_models.py` already carries #648's three fixture changes on `development`. The only change this batch makes to that file is RFC-0225 S3's change (d) (S3 table).


---

## Slices (one ticket each)

Assign order: **S1 → S2 → S3 → S4**; **S5** starts after S1 and lands before S3 (sequential owner of `App.tsx`).

### S1 — Root-cause evidence + engine-side repro

**Model:** Grok 4.5 (fast off) · **Lane:** D1 · **Depends:** none

Reproduce on Taco's Windows profile (LM Studio :1234 with the 9B, Ollama `anzu-coder-27b`, ANZU installed) and a clean profile. Capture: portal network log of failed `/api/model`, backend event-loop lag samples, `netstat -ano` for 1234/8088/8089/11434/4780, `nvidia-smi` VRAM per process, backend logs. Decide which hypothesis holds (concurrent servers/VRAM pressure, event-loop blocking, port collision, backend restart) and record loop-lag and `/api/model` failure numbers before #648/#649 (`11b264a7`) and on current `development` (`a44da353`), so the remaining engine-side cause (the S2 fix) is isolated from what #648/#649 already fixed.

| Path | Why |
| --- | --- |
| `docs/audits/2026-10-20-local-api-flicker-root-cause.md` (new) | Evidence, conclusion, before/after |
| `tests/test_rfc0225_flicker_repro.py` (new) | Repro of the confirmed engine-side mode, marked `@pytest.mark.xfail(strict=True, reason="fixed by RFC-0225 S2")`; S2 removes the marker |

- [ ] Audit names the confirmed root cause(s) with evidence, separating what #648/#649 already fixed from what remains; rejected hypotheses listed with the evidence that rejected them; before/after loop-lag numbers recorded.
- [ ] Repro test (foreign responder on the managed llama-server port accepted as healthy) is `xfail(strict=True)` naming S2; CI stays green.

### S2 — ANZU process registry + identity-checked managed server

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S1

| Path | Why |
| --- | --- |
| `backend/app/runtime/process_registry.py` (new) | `register(kind, pid, create_time, argv, port, owner_module, lifetime, role=None)` (`kind` ∈ the `ProcessKind` enum and the file layout in "Process registry file + processes API" below; `lifetime` ∈ `short` (registered_subprocess), `child` (terminated on shutdown), `detached` (left running on shutdown; used by S3's Ollama start)), `unregister`, `snapshot()`, `is_anzu_owned(pid, create_time)`, `registered_subprocess(...)` async context manager for short-lived children; argv stored **redacted** (secret flags `--api-key`, `--token`, `--password`, `--hf-token`, `--key`, `--secret` and any `KEY=VALUE` env-style arg with a secret-like key are replaced by `***`); atomic persist to `data_dir()/runtime/process-registry.json` |
| `backend/app/inference/backends.py` | Register/unregister managed llama-server (worker + front); pre-spawn port check → `port_conflict`; health accepts only listener pid == registered pid (`probe_remote_server`'s non-2xx rejection is already on `development` from #648 and is not touched) |
| `backend/app/modules/supervisor.py` | Register module workers — covers `modules/crucix_runtime.py` (Crucix `node server.mjs`) and `studio/blackgrid_runtime.py` (BlackGrid), which spawn through `get_supervisor(...).start` (D2 #4) |
| `backend/app/modules/supermemory_runtime.py` | Register the Supermemory sidecar |
| `backend/app/workers/voice.py` | Register voice/STT subprocesses: ffmpeg conversion, whisper.cpp CLI, SAPI STT PowerShell (short-lived, via `registered_subprocess`); first owner in the chain S2 → RFC-0226 S2 |
| `backend/app/tts/system_sapi.py` | Register SAPI PowerShell synthesis subprocesses (short-lived) |
| `backend/app/tts/synthesize.py` | Register the Piper CLI subprocess (short-lived); first owner in the chain S2 → RFC-0226 S2 |
| `backend/app/api/processes.py` (new) | `GET /api/system/processes` → registry snapshot + live status (running/exited/orphaned, CPU %, RSS), argv never returned raw (redacted form only); exact response shape below |
| `backend/app/main.py` | Include the processes router; terminate/unregister registered `child` processes on shutdown (existing order kept; `detached` entries are left running); first owner in the chain S2 → S3 (S1 no longer edits `main.py`) |
| `tests/test_rfc0225_process_registry.py` (new); `tests/test_rfc0225_flicker_repro.py` | Below; remove the xfail marker |

#### Process registry file + processes API (normative, S2; consumed by RFC-0229 S2)

**`ProcessKind` (string enum, `process_registry.ProcessKind`).** These are the only values of `kind`, both in the file and in the API. The engine kinds are the same strings RFC-0225 S3 uses in `engine_id` (`<kind>@<host>:<port>`) and RFC-0229 shows (`lmstudio`).

| `kind` | Spawned by (owner_module) | `role` |
| --- | --- | --- |
| `llama-server` | `inference.backends` | `"worker"` or `"front"` |
| `ollama` | `inference.ollama_runtime` (S3 start) | `null` |
| `lmstudio` | `inference.lmstudio_server` (when ANZU launches LM Studio) | `null` |
| `module-worker` | `modules.supervisor` | the module id, e.g. `"crucix"`, `"blackgrid"` |
| `supermemory` | `modules.supermemory_runtime` | `null` |
| `ffmpeg` | `workers.voice` | `null` |
| `whisper-cpp` | `workers.voice` | `null` |
| `sapi-stt` | `workers.voice` | `null` |
| `sapi-tts` | `tts.system_sapi` | `null` |
| `piper` | `tts.synthesize` | `null` |

`register()` raises `ValueError` for any other kind, so a new spawn site has to extend the enum, and its test, explicitly.

**File.** `data_dir()/runtime/process-registry.json`, UTF-8 JSON, written atomically (`<name>.tmp` + `os.replace`) on every register / unregister / exit. It is read by the core on start and by the RFC-0229 Manager when the core is down.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int, `1` | Readers reject any other value (the Manager shows "registry format not supported"; the core starts a fresh file and logs it) |
| `updated_at` | string, ISO-8601 UTC | Last write |
| `core` | object `{pid: int, create_time: float, started_at: string}` | The core process that wrote the file (`create_time` = `psutil.Process().create_time()`, epoch seconds) |
| `entries[]` | array of objects | One per registered process: |
| `entries[].id` | string, uuid4 hex | Stable row id |
| `entries[].kind` | `ProcessKind` | See table |
| `entries[].role` | string or null | See table |
| `entries[].pid` | int | OS pid |
| `entries[].create_time` | float | `psutil` create time of that pid at registration (identity with `pid`) |
| `entries[].exe_name` | string | Executable basename only (`llama-server.exe`), never a full path containing the user name |
| `entries[].argv_redacted` | array of strings | Redacted argv (secret flags / `KEY=VALUE` → `***`); raw argv is never written |
| `entries[].port` | int or null | Listening port when known |
| `entries[].owner_module` | string | Dotted module that spawned it |
| `entries[].lifetime` | `"short"` / `"child"` / `"detached"` | As above |
| `entries[].started_by` | `"anzu"` | Always `"anzu"` (only ANZU-spawned processes are registered) |
| `entries[].spawned_by_core` | object `{pid: int, create_time: float}` | The core instance that spawned it |
| `entries[].registered_at` | string, ISO-8601 UTC | |
| `entries[].exited_at` | string or null | Set when ANZU observed the exit |
| `entries[].exit_code` | int or null | Exit code when observed |

Exited entries are kept for 10 min (or the last 50, whichever is smaller), then dropped on the next write.

```json
{
  "schema_version": 1,
  "updated_at": "2026-10-20T13:30:02Z",
  "core": {"pid": 15220, "create_time": 1792502101.42, "started_at": "2026-10-20T13:15:01Z"},
  "entries": [
    {"id": "9f1c2a7e4b0d4f0c8a3e5d6b7c8d9e0f", "kind": "llama-server", "role": "front",
     "pid": 18840, "create_time": 1792502110.07, "exe_name": "llama-server.exe",
     "argv_redacted": ["llama-server.exe", "--port", "8089", "--api-key", "***"],
     "port": 8089, "owner_module": "inference.backends", "lifetime": "child", "started_by": "anzu",
     "spawned_by_core": {"pid": 15220, "create_time": 1792502101.42},
     "registered_at": "2026-10-20T13:15:10Z", "exited_at": null, "exit_code": null},
    {"id": "0a7d3c1b2e4f45a6b7c8d9e0f1a2b3c4", "kind": "ollama", "role": null,
     "pid": 20112, "create_time": 1792502190.88, "exe_name": "ollama.exe",
     "argv_redacted": ["ollama.exe", "serve"], "port": 11434, "owner_module": "inference.ollama_runtime",
     "lifetime": "detached", "started_by": "anzu", "spawned_by_core": {"pid": 15220, "create_time": 1792502101.42},
     "registered_at": "2026-10-20T13:16:30Z", "exited_at": null, "exit_code": null}
  ]
}
```

**How an entry is classified (one pure, read-only function, `process_registry.classify(entry, live_core) -> "running" | "exited" | "orphaned" | "reused"`, used by the API and imported by RFC-0229's `process_view.py` when the core is down; it never writes):**
- pid not alive → `exited` (`exit_code` from the entry, or `null` = "exited (unknown)");
- pid alive but `psutil` create time ≠ `entry.create_time` (compared rounded to 0.01 s) → **`reused`** (the pid now belongs to another process). The entry is never killed and never listed as ANZU's. **Only the core prunes it from the registry** (on its next write). The RFC-0229 Manager, which reads the file only when the core is down, hides `reused` rows and **never writes the core's file**;
- pid alive, create time matches, and `spawned_by_core` equals the live core (`pid` + `create_time`) → `running`;
- pid alive, create time matches, but `spawned_by_core` is a core that is no longer running (crashed or stopped core; with the core down, every such entry) → **`orphaned`**. A `detached` entry from an earlier core (e.g. ANZU-started Ollama) is re-adopted on core start: `spawned_by_core` is rewritten to the new core and it is `running`, because detached processes are meant to outlive the core.

**`GET /api/system/processes`** (existing core auth for `/api/system/*`; psutil work in `asyncio.to_thread`). **200**:

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-20T13:30:04Z",
  "core": {"pid": 15220, "create_time": 1792502101.42},
  "sample_interval_s": 2.0,
  "processes": [
    {"id": "9f1c2a7e4b0d4f0c8a3e5d6b7c8d9e0f", "kind": "llama-server", "role": "front",
     "pid": 18840, "exe_name": "llama-server.exe",
     "argv_redacted": ["llama-server.exe", "--port", "8089", "--api-key", "***"],
     "port": 8089, "owner_module": "inference.backends", "lifetime": "child", "started_by": "anzu",
     "status": "running", "exit_code": null, "exited_at": null,
     "cpu_percent": 3.5, "rss_bytes": 1311244288, "uptime_s": 894.0,
     "registered_at": "2026-10-20T13:15:10Z", "sample_error": null}
  ],
  "warnings": []
}
```

Field types: `schema_version` int; `generated_at` ISO string; `core` `{pid: int, create_time: float}`; `sample_interval_s` float (the interval CPU is measured over, see below); each process: `id` string, `kind` `ProcessKind`, `role` string|null, `pid` int, `exe_name` string, `argv_redacted` string[], `port` int|null, `owner_module` string, `lifetime` enum, `started_by` `"anzu"`, `status` `"running"|"exited"|"orphaned"`, `exit_code` int|null, `exited_at` string|null, `cpu_percent` float|null, `rss_bytes` int|null, `uptime_s` float|null, `registered_at` string, `sample_error` string|null. There is **no** `argv` key and no `create_time` per row (identity stays server-side). Rows are sorted by `kind`, then `registered_at`.
- **CPU %** is measured over the interval since the previous request (`psutil.Process.cpu_percent(interval=None)` on a per-pid `Process` object cached in the API). The **first** sample for a pid is `null` (the UI shows "measuring…"). `sample_interval_s` reports the real interval, so the RFC-0229 2 s refresh gives a 2 s average, and the endpoint never sleeps.
- **Empty case:** no registered processes → `200` with `"processes": []` and `"warnings": []`.
- **Per-row failure:** `psutil.AccessDenied` / `NoSuchProcess` mid-sample → the row stays, with `cpu_percent` / `rss_bytes` / `uptime_s` = `null` and `sample_error` = `"access denied"` / `"exited during sample"`; the response is still `200`.
- **Registry file unreadable at core start** (corrupt JSON, wrong `schema_version`): the core starts an empty registry, renames the bad file to `process-registry.json.bad-<ts>`, and the endpoint returns `200` with `"warnings": ["registry_file_reset: <reason>"]` until the next core start.
- **Endpoint failure** (unexpected exception): `500` with `{"error": "processes_unavailable", "detail": "<text>"}`; never a partial list without saying so.

- [ ] Every spawn site above registers on start and unregisters on exit (incl. Crucix and BlackGrid via the supervisor, voice/STT/TTS short-lived children); a crashed child reports `exited` with exit code.
- [ ] Registry survives a core restart; `reused` entries (create-time mismatch) are pruned by the core only, never killed.
- [ ] Foreign listener on 8088 before spawn → `port_conflict` with process name/pid; no spawn.
- [ ] Managed health rejects a responder on 8088 whose pid is not the registered child; `tests/test_rfc0225_flicker_repro.py` passes with the xfail marker removed.
- [ ] Registry file and API never contain a secret argv value (test with `--api-key sk-…`, `HF_TOKEN=…`).
- [ ] `GET /api/system/processes` ≤300 ms with 20 entries (psutil off the event loop).
- [ ] **Registry layout + API shape (for RFC-0229 S2)**, in `tests/test_rfc0225_process_registry.py`: `test_registry_file_layout_schema_v1` (after two registrations the file parses to exactly the documented top-level keys and per-entry keys and types, `schema_version == 1`, and no `argv` key); `test_registry_write_is_atomic` (a crash injected between the tmp write and `os.replace` leaves the previous file intact); `test_register_rejects_unknown_kind` (`ValueError` for `kind="llama"`; every `ProcessKind` value accepted; the enum equals the documented list); `test_engine_kinds_match_engine_id_kinds` (`ollama`, `lmstudio`, `llama-server` are both `ProcessKind` values and the `engine_id` prefixes S3 builds); `test_classify_running_exited_orphaned_reused` (fake psutil: live core match → `running`; dead pid → `exited`; alive pid from a dead core → `orphaned`; create-time mismatch → `classify` returns `"reused"`, nothing is killed, and the row is absent from the API); `test_classify_is_read_only` (`classify` on a `reused` entry leaves the file byte-identical; only `process_registry`'s core-side write drops it); `test_core_prunes_reused_on_next_write`; `test_detached_entry_readopted_on_core_start`; `test_exited_entries_retained_10_min_or_50`; `test_bad_registry_file_reset_with_warning` (corrupt file → renamed `.bad-<ts>`, empty registry, the API warning present); `test_processes_api_shape` (exact keys and types per the example, rows sorted, no `argv` / `create_time` per row); `test_processes_api_empty` (`200`, `processes == []`); `test_processes_api_cpu_first_sample_null` (first call `cpu_percent is None`, second call a float, `sample_interval_s` ≈ the faked interval, and the handler never sleeps); `test_processes_api_access_denied_row` (`sample_error == "access denied"`, status still reported); `test_processes_api_failure_500` (patched snapshot raising → `500` `{"error": "processes_unavailable", …}`).

### S3 — Engine classification, owner-consented stop, ledger, respawn/revive, VRAM gate, managed mode

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S2, S5 (sequential owner of `frontend/src/App.tsx`), RFC-0226 S2 (sequential owner of `systems/self_check.py`)

| Path | Why |
| --- | --- |
| `backend/app/inference/running_models.py` | `_poll` offer notice: the one `publish_owner_text(...)` call → `engine_coexistence.owner_line(<same text>)` (Architect decision 2026-10-20; nothing else in `_poll` changes). Classify rows `anzu_owned` / `selected` / `anzu_configured` / `foreign` (S2 registry, `settings.inference`, enabled runtime profiles, persona brain runtimes); engine kind + exe on rows; reuse `stop_listener` / `verify_unloaded`; first owner in the chain S3 → RFC-0227 S1 |
| `backend/app/inference/engine_coexistence.py` (new) | Startup check (non-blocking), prompt payload, `engine-choices.json` (incl. `manage`, `is_managed(engine)`), stop per the rule, ledger (`stopped` + `anzu_loads`, `record_anzu_load()` / `forget_anzu_load()` / `anzu_loaded_instances()`), `respawn()`, `revive()`, `prepare_engine_for()` (single-flight, identity, VRAM gate), `note_idle_unload()` (records `unloaded_idle_at`) / `idle_unloaded()` and `note_gate_unload()` / `gate_unloaded()` / `clear_gate_unload()` hooks for RFC-0228 S2, `owner_line()`, `record_engine_failure()` / `clear_engine_failure()` / `engine_failure_items()`, on-exit respawn |
| `backend/app/inference/endpoint.py` (new) | `inference_base_url(settings)` |
| `backend/app/inference/lmstudio_server.py` | Builds on the landed #648 inventory (`_loaded_model_ids`); `record_anzu_load()` after every verified `lms load` / REST load ANZU issues; `started_by: anzu` + registry entry when ANZU launches LM Studio; `stop_lmstudio_server()`; listener identity for :1234; first owner in the chain S3 → RFC-0228 S2 |
| `backend/app/inference/ollama_runtime.py` | Real start per "Ollama start": `ollama_cli()` Windows default paths, `start_local_ollama()` (detached `ollama serve`, `OLLAMA_HOST`, log file), registry entry `lifetime="detached"` + `started_by: anzu`, readiness poll, timeout/early-exit kill of the spawned pid only, `start-timeout` / `start-exited` results; listener identity for :11434 |
| `backend/app/api/named_personas.py` | Only `_maybe_activate_persona_brain`: replace the direct `ensure_local_ollama` call with `prepare_engine_for(profile)` (failure → owner line per "Owner-line surfaces" 1 + 2, not just a log). Disjoint from RFC-0218 S3b's hunks (`NamedPersonaPut`, `put_named_personas`); chain RFC-0218 S3b → 0225-S3 |
| `backend/app/systems/self_check.py` | Only: append the per-engine `engines:<engine_id>` items from `engine_coexistence.engine_failure_items()` to `checks` (second owner after RFC-0226 S2, whose `household_voice` hunk is untouched) |
| `backend/app/persona/inference_context.py` | Only: forward the existing `task_id` to `MANAGER.load` / `MANAGER.ensure_runtime` (only owner in the batch) |
| `backend/app/inference/vram.py` (new) | Free-VRAM measurement (NVML or `nvidia-smi`), "no NVIDIA GPU" result |
| `frontend/src/hud/EngineNotices.tsx` (new) | The `engine_notice` consumer (Owner-line surfaces 2): SSE on `/api/owner/chat/events`, chip showing the received `title` + text, speech via `queueChatSpeech` gated by `useSpeakChatReplies()`, dedupe by `id`, skip speech for the open task's own lines, reconnect backoff |
| `frontend/src/hud/engineNotices.css` (new) | `.engine-notices` fixed-position container + chip styles for both variants; imported only by `EngineNotices.tsx` |
| `frontend/src/hud/engineNotices.ts` (new) | The controller behind `EngineNotices.tsx` (filter, dedupe, speak decision, backoff, classic self-check poll); imported by the node tests |
| `frontend/src/hud/HudShell.tsx` | One mount line `<EngineNotices variant="hud" openTaskId={activeTaskId} />` in `HudShellInner` directly after `<HelpPanel … variant="hud" />` (`:435`), not in `HudTopChrome`; no other hunk (first owner in the chain 0225-S3 → 0225-S4 → RFC-0226 S3) |
| `frontend/src/App.tsx` | Only one added line in the classic branch: `<EngineNotices variant="classic" openTaskId={currentTaskId} />` as the last child of `div.app`, after `</main>` (`App.tsx:683`), plus its import; no other hunk (second owner after 0225-S5, whose hunk is only the `/api/model` poll effect) |
| `tts/persona_speech.py` (conditional) | Only when 0225-S3 lands after RFC-0218 S3b: `announce_persona_switch`'s one `publish_owner_text` call → `owner_line(persona_switch_line(to), level="info", title="Persona switch")` (RFC-0218 #663 handoff); otherwise not edited |
| `frontend/engine-notices.test.mjs` (new), `frontend/engine-notices-modes.test.mjs` (new); `frontend/package.json` (`test:engine-notices`, one line: `node --experimental-strip-types --test engine-notices.test.mjs engine-notices-modes.test.mjs`; both files register the existing `./presence-lifecycle-loader.mjs` the way `owner-chat-turns.test.mjs` does); `.github/workflows/pr-tests.yml` (one append-only `frontend-build` step `- name: Engine notices tests (RFC-0225 S3)` / `run: npm run test:engine-notices`) | Below |
| `backend/app/inference/hotswap.py` | Call `prepare_engine_for` in `activate_runtime_profile` before the probe; only owner in this batch (RFC-0228 S2 no longer edits it: #648's `persist=False` change has landed) |
| `backend/app/inference/manager.py` | Call `prepare_engine_for` in `ensure_runtime` / `_load_locked` for non-managed endpoints; first owner in the chain S3 → RFC-0228 S2 |
| `backend/app/main.py` | Shutdown → on-exit respawn (the landed `_autoload_model` is called as is); second owner in the chain S2 → S3 |
| `backend/app/api/model.py` | `GET /api/model/engines` (rows with class, kind, port, pid/exe, model ids, busy, `unloaded_idle_at` from the hook — the field name landed RFC-0229 S2 reads), `POST /api/model/engines/decision` (`keep` / `stop` / `stop_always`, `remember`, `respawn_on_exit`, `manage`), `GET /api/model/engines/ledger`, `POST /api/model/engines/{id}/respawn` |
| `tests/test_rfc0210_running_models.py` | #648's three fixture changes ((a) port parametrization, (b) `auto_load = True`, (c) the `test_startup_loads_saved_model_without_waiting_for_discovery` rename and assertion) are **already on `development`** (`tests/test_rfc0210_running_models.py:27`, `:271`, `:308`) and are not repeated. S3 makes only change (d) **(Architect decision 2026-10-20)** `test_new_offer_is_announced_once_on_front_voice_lane` renamed `test_new_offer_is_announced_once_on_owner_channel`: it now patches `engine_coexistence.owner_line` instead of `chat_delivery.publish_owner_text` and asserts one call with the RFC-0210 text and `title="Available local models"`. The `lane == "front"` assertion goes, because it pinned the dead channel; it is replaced by an assertion that a patched `publish_owner_text` is never called. This is the only RFC-0210 assertion that changes, and it changes because the behaviour was the bug |
| `tests/test_rfc0225_engine_coexistence.py` (new), `tests/test_rfc0225_ollama_start.py` (new), `tests/test_rfc0225_owner_lines.py` (new) | Below |

- [ ] Taco's selected LM Studio :1234 (`qwen3.5-9b-defiant-fable-uncensored`) → `selected`, never a stop candidate.
- [ ] **(D2 #1)** Ollama referenced by an enabled runtime profile, and Ollama used by the Umi persona brain runtime, → `anzu_configured`, never listed for stopping; the same Ollama with the profile disabled and no persona reference → `foreign`.
- [ ] No code path stops an engine without a recorded owner decision (stop functions reachable only from the decision endpoint and the RFC-0210 choice endpoint).
- [ ] Busy engine → decision rejected "in use"; nothing stopped. Successful stop writes a ledger entry; failed verification writes nothing.
- [ ] **(D2 #2)** `activate_runtime_profile` for a profile whose engine is ledgered → respawned, healthy, attached, one owner line; chat request routed via `MANAGER.ensure_runtime` to a ledgered engine → same. Respawn failure → visible error, request fails.
- [ ] **(D2 #3)** LM Studio :1234 selected and not listening → revived via `ensure_local_lmstudio`, ledger `stopped` section untouched; LM Studio listening with the 9B idle-unloaded (`idle_unloaded()` true) → reload path, no revive, no respawn, no prompt.
- [ ] **(D2 #3)** Two concurrent requests needing the same reload/revive/respawn → exactly one start/load call (single-flight).
- [ ] **(D2 #3, re-review #1)** 27B request, free VRAM < 13 GB, in `tests/test_rfc0225_engine_coexistence.py::test_vram_gate_*`:
  - `test_vram_gate_managed_on_unloads_owner_loaded_9b`: managed mode on, owner-loaded 9B → 9B unloaded (verified), one owner line, 27B loaded.
  - `test_vram_gate_managed_off_unloads_anzu_loaded_lmstudio_9b`: managed mode off, the 9B is in `anzu_loads` (LM Studio) → exactly that instance unloaded (verified by `_loaded_model_ids`), `forget_anzu_load()` called, one owner line "Unloaded the 9B ANZU loaded…", 27B loaded.
  - `test_vram_gate_managed_off_unloads_managed_llama_server_9b`: default install, Fable 9B in ANZU's llama-server → `MANAGER.unload()`, one owner line, 27B loaded.
  - `test_vram_gate_managed_off_refuses_owner_loaded_9b`: managed mode off, owner-loaded 9B (not in `anzu_loads`) → **no** unload call issued, request fails with the owner-visible reason naming the owner-loaded 9B and the managed-mode toggle; no 27B load attempted.
  - `test_vram_gate_mixed_unloads_anzu_loaded_first`: one ANZU-loaded and one owner-loaded instance, managed off → only the ANZU-loaded one unloaded; still short → owner-loaded refusal.
  - `test_vram_gate_skipped_without_nvidia_gpu`: no NVIDIA GPU → gate skipped and logged.
  - `test_vram_gate_records_gate_unload_marker`: every gate unload sets `gate_unloaded()` with the 9B and the heavy model; nothing in this RFC reloads that 9B on a timer.
- [ ] **(D2 third re-review #3)** Reverse direction (9B needed, heavy model resident), in `tests/test_rfc0225_engine_coexistence.py`:
  - `test_reverse_gate_unloads_anzu_loaded_27b_then_loads_9b_when_short`: ANZU-loaded `anzu-coder-27b` resident, measured free VRAM < 9B + 1 GB → `keep_alive: 0` sent and verified by `/api/ps`, `forget_anzu_load()` and `clear_gate_unload()` called, exactly one 9B load through the prepare path, exactly one `engine_notice` "Unloaded anzu-coder-27b to bring the 9B back for chat." on the owner channel and on the turn's task.
  - `test_reverse_gate_no_unload_when_both_fit`: free VRAM ≥ 9B + 1 GB → no unload call, 9B loaded, marker cleared, 27B still listed by `/api/ps`.
  - `test_reverse_gate_unload_failure_surfaces`: `keep_alive: 0` fails (and, as a second case, `/api/ps` still lists the 27B, or free VRAM is still short after a verified unload) → no 9B load attempted, one `engine_notice` with `level: "error"` and "Couldn't bring the 9B back: …", an `engines:ollama@127.0.0.1:11434` self-check item, and the worker part of the turn fails with that text.
  - `test_reverse_gate_owner_loaded_27b_refused`: an owner-loaded 27B (not in `anzu_loads`) → no unload call, error line naming it.
  - `test_reverse_gate_front_lane_answers_during_swap`: `run_two_lane_chat` with the 9B swap faked to take 20 s → the front (2B) deltas are yielded before the swap completes and the worker deltas after it; with the front lane disabled, "Bringing the 9B back, one moment." is published before the unload call.
  - `test_reverse_gate_waits_for_heavy_model_lease`: 27B holding a request lease → no unload until the lease ends.
- [ ] **(D2 third re-review #1)** Owner lines reach the owner, in `tests/test_rfc0225_owner_lines.py` (new): `test_owner_line_publishes_engine_notice_on_owner_channel` (exact dict on a `BUS.subscribe(OWNER_CHAT_CHANNEL)` queue: `kind == "engine_notice"`, `title == "Local engines"`, `stage == "engine_coexistence"`, `json.loads(detail)` has `text`/`level`/`engine_id`/`task_id`/`id`); `test_owner_line_with_task_also_on_task_stream` (task queue receives one `engine_notice` and one `chat_tts` titled "Local engines", and a `TaskEvent` row exists for the `engine_notice`); `test_owner_line_never_uses_publish_owner_text` (patched `publish_owner_text` never called); **(Architect decision 2026-10-20 15:19)** `test_owner_line_custom_title` (`owner_line("Switched to Umi.", title="Persona switch", task_id=t)` → owner-channel frame `title == "Persona switch"`, and both task frames carry `"Persona switch"`; the same call without `title` → `"Local engines"`; `title=""` and `title="Speak reply"` raise `ValueError`), plus `test_rfc0225_and_rfc0228_lines_use_default_title` (static: no `owner_line(` call in the RFC-0225 / RFC-0228 owned modules passes `title=`, with exactly two named exceptions: the `inference/running_models.py` offer notice with `title="Available local models"`, asserted to exist exactly once with that literal, and the `tts/persona_speech.py::announce_persona_switch` call with `title="Persona switch"`, which must be the only `owner_line(` call in that file and must carry that literal; any other `title=` fails); `test_persona_switch_title_reaches_owner_channel` (`owner_line(persona_switch_line("enki"), level="info", title="Persona switch")` → one owner-channel `engine_notice` with `title == "Persona switch"`, `json.loads(detail)["text"] == persona_switch_line("enki")`, `task_id is None`); `test_announce_persona_switch_uses_persona_switch_title` (with the RFC-0218 #663 handoff: whichever slice lands second adds it; `announce_persona_switch("enki")` → exactly one `engine_notice` titled "Persona switch" and a patched `publish_owner_text` never called); `test_every_rfc0225_owner_line_goes_through_owner_line` (static: no other module calls `publish_owner_text` for the strings in this RFC, and `inference/running_models.py` contains no `publish_owner_text`); **(Architect decision 2026-10-20)** `test_running_models_offer_notice_reaches_owner_channel` (real `RunningModels` with one pending foreign row, `scan` and `sleep` faked as in `test_rfc0210_running_models.py`, and a real `BUS.subscribe(OWNER_CHAT_CHANNEL)` queue: after two poll iterations the queue holds **exactly one** `engine_notice` whose `json.loads(detail)["text"]` is the byte-identical RFC-0210 text, with `title == "Available local models"` and `stage == "engine_coexistence"` and the row's `engine_id`; a patched `publish_owner_text` is never called; a second new row gives a second frame). Frontend `frontend/engine-notices.test.mjs` (fake `EventSource` and fake `queueChatSpeech`, fed the exact backend frame): `engine notice shows a chip and is spoken when speak-replies is on`; `engine notice is not spoken when speak-replies is off`; `assistant and chat_tts frames on the owner channel are ignored`; `a notice for the open task is shown but not spoken twice`; `duplicate id is shown once`; `persona switch notice shows the Persona switch title` (frame with `title: "Persona switch"` and `persona_switch_line("enki")` text → chip title "Persona switch", spoken once); `engine notice renders the title it receives` (a frame with `title: "Persona switch"` shows "Persona switch" on the chip; a frame with `title: "Local engines"` shows "Local engines"; the component source contains no hard-coded "Persona switch"); `reconnects with backoff after an error`. **Both modes (D2 fourth re-review #1)**, `frontend/engine-notices-modes.test.mjs` (new; node `--test`, like every frontend test here; `frontend/package.json` has no vitest or jsdom, and adding a DOM test framework is out of scope): `notice is shown and spoken in HUD mode` and `notice is shown and spoken in classic mode` (the controller from `engineNotices.ts`, run with `variant` `"hud"` / `"classic"` and fed the exact RFC-0210 offer frame and a `level: "error"` failure frame: chip model holds both, fake `queueChatSpeech` called once per frame, both through the same exported `speakNotice`); `classic variant shows engines self-check failures` (fake `/api/system/self-check` with `engines:ollama@127.0.0.1:11434` degraded → persistent error chip; cleared item → chip removed; HUD variant makes no self-check request); `renders nothing without a notice` (the controller's `view()` is `null` with no notices, for both variants, and `EngineNotices.tsx` returns `null` when `view()` is `null`, static); `classic layout is unchanged: grid children and structure` (static on `App.tsx`: the direct children of the classic `div.app` are, in order, `header.mobile-bar`, `HelpPanel`, the `navOpen && nav-backdrop`, `aside.sidebar`, `main`, then `EngineNotices`, so the five existing ones are unchanged in order, element and `className`; and `engineNotices.css` gives `.engine-notices` `position: fixed`, while no existing CSS file has an `engine-notices` rule); `classic variant starts the self-check poll and hud does not`; `exactly one EngineNotices mount per mode` (static on `App.tsx` and `HudShell.tsx`: `HudShell.tsx` has one `<EngineNotices variant="hud"`, inside `HudShellInner` after `<HelpPanel` and not inside `HudTopChrome`; `App.tsx` has one `<EngineNotices variant="classic"`, inside the classic branch after the `if (uiMode === "hud")` return and none inside that HUD branch; no other `src/` file mounts it); `no second speech path` (static: `EngineNotices.tsx` and `engineNotices.ts` call only `queueChatSpeech` for audio). These run in the S3 CI step "Engine notices tests (RFC-0225 S3)" through the one `test:engine-notices` script; `running-models offer notice frame is shown and spoken once` (fed the frame shape that `test_running_models_offer_notice_reaches_owner_channel` asserts, built inline in the test with the byte-identical RFC-0210 text and `title: "Available local models"`; the chip shows that title and that text and fake `queueChatSpeech` gets it once; no new fixture file).
- [ ] **(D2 third re-review #2)** `tests/test_rfc0225_owner_lines.py::test_two_failing_engines_give_two_self_check_items` (an Ollama start failure and an LM Studio reload failure → `run_self_check()` contains `engines:ollama@127.0.0.1:11434` and `engines:lmstudio@127.0.0.1:1234`, ids unique; a second failure on the same engine replaces its text rather than adding a third item).
- [ ] **(D2 #3)** 9B holding a request lease → no unload until the lease ends.
- [ ] `anzu_loads` is written after every ANZU load and pruned when native inventory no longer lists the instance; an instance the owner loaded with the same model key is never added (instance id compared).
- [ ] **(D2 re-review #2)** Ollama start, in `tests/test_rfc0225_ollama_start.py` (new; `Popen`, probe and registry faked): `test_dead_ollama_is_started_when_binary_exists` (nothing on :11434, `ollama_cli()` → fake path → `Popen` invoked exactly once with `[cli, "serve"]`, `OLLAMA_HOST=127.0.0.1:11434`, detached flags; registry entry `kind="ollama"`, `lifetime="detached"`, `started_by="anzu"`; probe flips ok → `ensure_local_ollama` returns ok and the pull/warm step runs); `test_ollama_binary_resolved_from_localappdata` (not on `PATH`, file at `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` → that path used); `test_missing_ollama_binary_never_spawns` (no binary anywhere → `Popen` never called, `method == "missing-cli"`, owner line "Couldn't start Ollama: Ollama is not installed…" via `prepare_engine_for`); `test_ollama_start_timeout_kills_only_spawned_pid` (never ready → after 45 s (fake clock) the spawned pid is terminated and unregistered, `method == "start-timeout"`, owner line shown, request fails); `test_ollama_early_exit_reported` (spawned process exits code 1 → `start-exited` with the exit code, no further polling); `test_listening_ollama_is_not_spawned_again` (probe ok → no `Popen`); `test_umi_brain_revives_dead_ollama` (`_maybe_activate_persona_brain` for Umi with Ollama dead → `prepare_engine_for` → started → brain activated); `test_umi_brain_start_failure_reaches_owner_surfaces` (start fails inside the background task → exactly one `engine_notice` frame with `level: "error"` and "Couldn't start Ollama for Umi's brain: …" on a `BUS.subscribe(OWNER_CHAT_CHANNEL)` queue (the frame `EngineNotices` renders and speaks, see `frontend/engine-notices.test.mjs`), `publish_owner_text` not called, **and** `GET /api/system/self-check` returns an `engines:ollama@127.0.0.1:11434` item with status `degraded` and that text; a later successful start clears the item). The health-rail rendering is asserted in S4.
- [ ] **(D2 #4)** Non-LM-Studio process listening on 1234 (or non-Ollama on 11434) → `port_conflict` with process name/pid; nothing loaded.
- [ ] `manage: true` persisted, survives restart, returned by `is_managed()`; `manage: false` reverts immediately; `manage` rejected for non-selected or non-LM-Studio engines; managed mode never stops the LM Studio server/app.
- [ ] `respawn_on_exit` honoured on shutdown; remembered `stop_always` applies on next start and the startup line names what was stopped.

### S4 — Startup engine prompt + managed-mode question (UI)

**Model:** Composer 2.5 (fast off) · **Lane:** UX · **Depends:** S3

| Path | Why |
| --- | --- |
| `frontend/src/hud/EngineCoexistencePrompt.tsx` (new) | Non-modal card: foreign engines (port, process, model ids, busy); Keep / Stop now / Stop whenever ANZU starts; "Remember my choice" (off); "Restart it when ANZU closes"; per-row pending + result; one-time "Let ANZU manage LM Studio models" question when LM Studio is selected |
| `frontend/src/hud/HudShell.tsx` | Mount next to the existing `<RunningModels />` mount (unchanged); second owner in the chain 0225-S3 → 0225-S4 → RFC-0226 S3 |
| `frontend/src/pages/Model.tsx` | "Other engines": remembered choices (revocable), ledger with "Restart now", "ANZU manages LM Studio models" toggle |
| `frontend/engine-coexistence.test.mjs` (new); `frontend/package.json` (`test:engine-coexistence`, one line); `.github/workflows/pr-tests.yml` (one append-only `frontend-build` step `- name: Engine coexistence prompt tests (RFC-0225 S4)` / `run: npm run test:engine-coexistence`) | Below |

- [ ] Prompt shows only when S3 reports ≥1 foreign engine without a remembered choice, or LM Studio is selected and `manage` is unanswered; never blocks chat or the HUD.
- [ ] Rows show port, process/executable, model ids, busy state; Stop disabled for busy rows with the reason.
- [ ] Selected and ANZU-configured engines never appear as stop rows (fixture with Taco's LM Studio + Umi Ollama).
- [ ] Answers go through `POST /api/model/engines/decision`; answered rows disappear from the RFC-0210 offer.
- [ ] Managed-mode question asked once (default off), remembered, shown as a toggle on the Model page that writes `manage`.
- [ ] **(D2 second re-review #1, third re-review #2)** `frontend/engine-coexistence.test.mjs::engine failure self-check items reach the health rail with distinct keys`: a self-check snapshot fixture with two items `{id: "engines:ollama@127.0.0.1:11434", label: "Local engines", status: "degraded", detail: "Couldn't start Ollama for Umi's brain: …"}` and `{id: "engines:lmstudio@127.0.0.1:1234", …, detail: "Couldn't bring the 9B back: …"}` → `collectHealthIssues` returns two issues with ids `check-engines:ollama@127.0.0.1:11434` and `check-engines:lmstudio@127.0.0.1:1234`; rendering `HudLocalStatus` with them produces two `<li>` with distinct keys and no React duplicate-key warning; a fixture with only the existing items renders exactly as before (snapshot of the existing list). No change to `systemHealth.ts` or `HudLocalStatus.tsx`.
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
- [ ] Default install (managed mode off, ANZU-loaded Fable 9B) on a 16 GB GPU → coding request unloads the ANZU-loaded 9B with one line and the 27B answers; Ollama stopped beforehand → ANZU starts it and the request still answers.
- [ ] No engine stopped without an owner decision over the soak (log audit).
- [ ] Live-UI rows preserved; frontend build + lint; full backend suite and JS tests green in CI.

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0225-S1 | Root-cause evidence + engine-side repro | Grok 4.5 | D1 | — |
| 0225-S2 | Process registry + identity-checked managed server | Grok 4.6 | D1 | S1 |
| 0225-S3 | Engine classification, consented stop, ledger, respawn/revive, VRAM gate, managed mode, owner-line consumer (HUD + classic) | Grok 4.6 | D1 | S2, S5, 0226-S2 |
| 0225-S4 | Startup engine prompt + managed-mode question | Composer 2.5 | UX | S3 |
| 0225-S5 | Debounced identity-checked reachability | Grok 4.5 | UX | S1 |

## Likely files

See per-slice tables. Sequential ownership chains across the batch (never concurrent): `main.py` 0225-S2 → S3; `api/model.py` 0225-S3 → 0227-S1 (S1 no longer edits it; RFC-0228 S2 no longer edits it, #648's `gguf_path` reset has landed); `running_models.py` 0225-S3 → 0227-S1 (S3 moves the offer notice onto `owner_line()`, and 0227-S1 keeps it there); `lmstudio_server.py` 0225-S3 → 0228-S2; `hotswap.py` 0225-S3 only; `manager.py` 0225-S3 → 0228-S2; `config.py` 0228-S1 → 0228-S2 (not edited here); `workers/voice.py` 0225-S2 → 0226-S2; `tts/synthesize.py` 0225-S2 → 0226-S2; `HudShell.tsx` 0225-S3 → 0225-S4 → 0226-S3; `frontend/src/App.tsx` 0225-S5 → 0225-S3 (disjoint hunks: the `/api/model` poll effect, then the one classic mount line); `tts/persona_speech.py` RFC-0218 S3b ↔ 0225-S3, whichever lands second makes the `owner_line(…, title="Persona switch")` call (RFC-0218 #663 handoff); `api/named_personas.py` RFC-0218 S3b → 0225-S3 (disjoint functions); `systems/self_check.py` 0226-S2 → 0225-S3 (disjoint hunks).

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
- **#648/#649 behaviour regressing** → S1's audit records their numbers; this RFC relies on their landed tests (see "Relationship to #648/#649").
