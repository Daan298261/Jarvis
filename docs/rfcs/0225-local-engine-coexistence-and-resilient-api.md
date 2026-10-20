# RFC-0225: Local engine coexistence + resilient local-API connection

**Status:** accepted  
**Priority:** P0 (Taco bug batch 2026-10-17, bug 2 — highest impact)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20 (re-sliced 2026-10-20: lands on current `development` without drafts #648/#649; D2 review items 1–9 folded in; D2 re-review items 1–4 second re-review items 1–3 and third re-review items 1–3 of 2026-10-20 folded in)

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
3. **Several model servers compete for the same GPU.** ANZU spawns its own `llama-server` (`backends.py`, worker 8088, front 8089), can auto-start LM Studio on 1234 (`lmstudio_server.ensure_local_lmstudio` via `hotswap.py`), and talks to Ollama on 11434 through `ollama_runtime.ensure_local_ollama` (via `hotswap.py` and the Umi persona brain in `api/named_personas.py::_maybe_activate_persona_brain`). **`ensure_local_ollama` never starts Ollama:** when nothing listens it only polls `_wait_until_up` for `SERVER_WAIT_SECONDS` (45 s) and returns `server-down`; nothing in `ollama_runtime.py` / `gpu_prefer.py` runs `ollama serve`, `ollama_cli()` only searches `PATH`, and the persona-brain caller only logs the failure (`persona_brain_ollama_prepare_failed`). Taco runs LM Studio (9B on `:1234`) and Ollama (`anzu-coder-27b`, ~12 GB, `:11434`; `docs/audits/2026-10-09-model-reuse-scheduler-manager.md`). RFC-0210 offers use/leave/stop/replace per row but nothing asks at startup, nothing remembers what was stopped, nothing respawns it, and **engines ANZU itself is configured to use (Ollama runtime profiles, the Umi brain) are treated like strangers**.
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
4. **Model loaded?** Uses native inventory (`_loaded_model_ids`, ported from #648). If the model was idle-unloaded by RFC-0228 S2 (state `unloaded_idle_at` recorded by 0228-S2 through `engine_coexistence.note_idle_unload()`), this is a **reload**, delegated to the 0228-S2 reload routine once it exists; before 0228-S2 lands, the existing `ensure_local_lmstudio(model=…)` load path is the reload. A server left running with no model after an idle unload is never "dead", never "foreign", never offered.
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
   - **The owner is never left on silence.** This gate runs on the **worker** lane only. The turn's front lane (`agent/front_responder.py::run_two_lane_chat` yields front deltas first, `front_responder.py:1009–1022`; the 2B front model on ANZU's llama-server :8089 is resident by default, `config.py:114` `front_responder.resident = True`) answers immediately. The worker part follows once the 9B is loaded, or the failure line replaces it. If the front lane is disabled or not loaded, `owner_line("Bringing the 9B back, one moment.", task_id=…)` is spoken before the unload starts.
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

**What the portal actually consumes on `development` @ `11b264a7` (traced):**

- Spoken lines: the only path that reaches the speaker is the **task event stream**. `frontend/src/tts/useTaskSpeech.ts:64` opens `EventSource(getAuthUrl("/api/tasks/<id>/events"))`, and `:43` speaks only events with `kind == "chat_tts"` via `chatTtsPlayer.queueChatSpeech` (`tts/chatTtsPlayer.ts:134`). It is mounted only for the task open in the chat (`hud/HudChat.tsx:97`, `pages/Chat.tsx:50`). Backend producers publish `BUS.publish(task_id, "chat_tts", …)` (`agent/loop.py:1063`, `:1083`).
- Visible task lines: `chat/ownerChatView.ts:365` opens the same task stream. `filterWorkEvents` (`ownerChatView.ts:76–79`) shows every kind except `assistant_delta` / `chat_tts` / `replace_previous_text` (`:40`).
- **Not consumed:** `persona/chat_delivery.py::publish_owner_text` publishes on `OWNER_CHAT_CHANNEL` (`chat_delivery.py:71`, `:100`). That channel is served at `GET /api/owner/chat/events` (`api/owner_chat.py:65–78`), and the TTS queue `enqueue_chat_tts` is drained only by `GET /api/owner/chat/tts/pending` (`:83`). No file in `frontend/src`, `android/`, `extensions/` or the Manager subscribes to or polls either one. `running_models.py:338`'s "I found another local model server…" and RFC-0218's switch line (`tts/persona_speech.py::announce_persona_switch` → `publish_owner_text`) are orphaned the same way. **Architect decision (2026-10-20 15:15): the `running_models.py:338` notice is a live bug and is fixed in S3** (see "RFC-0210 offer notice" below). The RFC-0218 switch line is handled separately and is not touched here. `publish_owner_text` itself (`chat_delivery.py`) stays as it is; only this one caller moves off it.

Most of this RFC's lines are not bound to an open task (startup check, persona brain, timers, profile activation), so the task stream alone cannot carry them. **S3 therefore ships the consumer, wired end to end:**

1. **One backend entry.** `engine_coexistence.owner_line(text, *, level="info"|"error", engine_id=None, task_id=None)` is the only way this RFC (and RFC-0228 S2) emits an owner line. It:
   - (a) **always** publishes `BUS.publish_ephemeral(OWNER_CHAT_CHANNEL, "engine_notice", "Local engines", json.dumps({"text", "level", "engine_id", "task_id", "id"}), stage="engine_coexistence")`. `id` is a uuid4, used for dedupe;
   - (b) when `task_id` is given (the request is a chat or task turn), **also** publishes on that task: `BUS.publish(task_id, "engine_notice", "Local engines", text, stage="engine")` (persisted and visible in the work panel through the existing `filterWorkEvents`) and `BUS.publish(task_id, "chat_tts", "Local engines", text, stage="engine")` (spoken by the existing `useTaskSpeech`; the title is not "Speak reply", so it never joins the reply prefix at `useTaskSpeech.ts:47`);
   - it does **not** call `publish_owner_text` (no orphaned `enqueue_chat_tts` entry).
   - `task_id` reaches `prepare_engine_for` as a keyword argument: `persona/inference_context.py::ensure_context_for_messages` already receives `task_id` (it forwards it to `maybe_autoselect_runtime_for_budget`) and now also passes it to `MANAGER.load(…, task_id=…)` / `MANAGER.ensure_runtime(…, task_id=…)` (`inference_context.py:79`, `:87`), which forward it to `prepare_engine_for`. `activate_runtime_profile`, the persona brain and timers pass none.
2. **The consumer (new, S3): `frontend/src/hud/EngineNotices.tsx` is a new HUD file. It adds one mount in `HudShell.tsx` next to the existing children and doesn't change how any existing live component behaves or renders** (add-alongside rule; see the live-UI table). It is mounted once in `frontend/src/hud/HudShell.tsx` next to `<HudLocalStatus …/>` (`HudShell.tsx:111`). It opens `EventSource(getAuthUrl("/api/owner/chat/events"))` and listens **only** for the SSE event name `engine_notice` (the server names SSE events by `kind`, `owner_chat.py:76`), so the reply / `chat_tts` traffic on that channel is ignored and nothing is spoken twice. For each notice (deduped by `id`):
   - it shows a non-blocking, dismissible HUD chip with the text (error level styled as a warning, auto-hidden after 12 s for info);
   - it speaks the text through `queueChatSpeech` when `useSpeakChatReplies()` is on (same setting `HudChat.tsx:47` uses), **unless** `task_id` equals the task currently open in `HudChat`, because that line is already spoken by `useTaskSpeech` from the task stream;
   - on socket error it reconnects with 2 → 4 → 8 → 15 s backoff. Notices missed while disconnected are not replayed, but every failure also stays on the health rail (item 3).
3. **Persistent HUD health-rail item (failures).** Every failed revive, respawn, unload or reload also records `engine_coexistence.record_engine_failure(engine_id, text)`. `systems/self_check.py::run_self_check` appends **one item per engine** with a unique id, `_item(f"engines:{engine_id}", "Local engines", "degraded", <text>)`. `engine_id` is `<kind>@<host>:<port>` (e.g. `ollama@127.0.0.1:11434`, `lmstudio@127.0.0.1:1234`, `llama-server@127.0.0.1:8088`), and a second failure on the same engine replaces its text. `frontend/src/hud/systemHealth.ts::collectHealthIssues` turns each into `check-engines:<engine_id>` (`systemHealth.ts:49–58`), so the `<li key={issue.id}>` in `HudLocalStatus.tsx:46` gets distinct keys. **Add-alongside:** `systemHealth.ts` and `HudLocalStatus.tsx` are **not edited**; every existing item keeps its id, title, detail, link and rendering, and only new ids are added. The next successful prepare for that engine clears its item (`clear_engine_failure`).
4. **Request error (request paths only).** Chat / task / profile-activation requests fail with the same text and keep their existing error rendering.

**RFC-0210 offer notice (S3, Architect decision 2026-10-20).** On `development` @ `11b264a7`, `RunningModels._poll` (`inference/running_models.py:334–343`, from RFC-0210 #584 / `64db8b8`; not modified since) calls `await publish_owner_text("I found another local model server. Would you like to use it, leave it alone, stop it, or replace it with ANZU's model? The choices are on screen.", title="Available local models", source="running_models", lane="front")`. The owner never sees or hears it, because the channel it publishes on has no client. S3 replaces that one call with `engine_coexistence.owner_line(<the same text, byte-identical>, level="info", engine_id=<first pending row's engine_id>)`. Everything else stays: same once-per-row `_notified` bookkeeping, same 20 s poll, same `except` / `self.error` handling, and the HUD `RunningModels.tsx` card is untouched. The notice is then shown as an `EngineNotices` chip and spoken when speak-replies is on. The import of `publish_owner_text` leaves `running_models.py`. The next owner of `running_models.py`, RFC-0227 S1 (aggregated, rate-limited notice), builds on this call, so its notice also goes through `owner_line()`. Open PRs #648 / #649 (drafts, heads `b942bcd` / `edb4685`) touch `running_models.py` only in `scan`, `decide` and the `_poll` `auto_load` guard (`:335`), not the notice lines. Those pieces are already ported into S3 (see the #648 port table), so they never land `running_models.py` on their own.

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
| RFC-0210 "I found another local model server…" notice (`running_models.py:338`; today published on a channel with no client, so never heard or seen) | **Yes**: byte-identical text, once per new row, same poll; frequency stays RFC-0227's | It now actually reaches the owner: published through `owner_line()` and shown + spoken by `EngineNotices` (S3) |
| Every existing HUD component in `HudShell.tsx` (`PortalNav`, `HudLocalStatus`, `HelpTrigger`, `HudModelSelector`, `RunningModels`, `HudStarfield`, `HudTopChrome`, `HelpPanel`, `HudOpsRail`, `HudHealthRail`, `HudBottomChrome`) and their order, props and rendering | **Yes**: none edited; `HudShell.tsx` gets exactly one added line | `frontend/src/hud/EngineNotices.tsx` is a new HUD file. It adds one mount in `HudShell` next to the existing children and doesn't change how any existing live component behaves or renders |
| Health rail items from `systemHealth.ts` / `HudLocalStatus.tsx` | **Yes**: files not edited | Per-engine `engines:<engine_id>` items (S3 backend, S4 rendering test) |
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
| `tests/test_rfc0225_gguf_path_cache.py` (new), `tests/test_rfc0225_startup_optional_steps.py` (new) | Acceptance tests for the two S1 ports (below) |
| `tests/test_rfc0225_flicker_repro.py` (new) | Repro of the confirmed engine-side mode, marked `@pytest.mark.xfail(strict=True, reason="fixed by RFC-0225 S2")`; S2 removes the marker |

- [ ] Audit names the confirmed root cause(s) with evidence; rejected hypotheses listed with the evidence that rejected them; before/after loop-lag numbers recorded.
- [ ] LAN beacon never replies to announcements; probe replies ≤8 concurrent; payload/route work runs off the event loop (ported tests pass).
- [ ] `/api/model` returns ≤300 ms while `available_profiles`, outcomes and benchmarks are artificially slowed (5 s fakes); status cache miss returns `status_refresh_pending: true` immediately.
- [ ] `/api/system`, `/api/diagnostics`, swarm node/capability endpoints keep the event loop free under slowed `hardware_dict` / catalog fakes.
- [ ] Repro test (foreign responder on the managed llama-server port accepted as healthy) is `xfail(strict=True)` naming S2; CI stays green.
- [ ] **(D2 re-review #4) 30 s GGUF path cache** (ported #648 `qwen38_local._owner_gguf_paths` / `_scan_owner_gguf_paths` / `_PATH_CACHE` / `_PATH_LOCK`), in `tests/test_rfc0225_gguf_path_cache.py` (new; each test clears `PYTEST_CURRENT_TEST` and resets `_PATH_CACHE`, `time.monotonic` faked): `test_gguf_path_cache_hit_within_30s` (two calls 29 s apart → one scan, equal results); `test_gguf_path_cache_expires_after_30s` (second call at 30.01 s → second scan, new file visible); `test_gguf_path_cache_invalidated_when_roots_change` (`models_dir()` or the LM Studio root changes → cache key differs → rescan inside 30 s); `test_gguf_path_cache_bypassed_for_extra_roots` (`extra_roots` given → always scans, cache untouched); `test_gguf_path_cache_concurrent_callers_scan_once` (two threads, one scan).
- [ ] **(D2 re-review #4) `_start_optional_step`** (ported #648 `main.py::_start_optional_step` / `_startup_tasks`, shutdown cancel), in `tests/test_rfc0225_startup_optional_steps.py` (new): `test_optional_step_success_recorded` (step completes → name in `startup_health.report()["completed_steps"]`, task removed from `_startup_tasks`); `test_optional_step_failure_surfaces_in_health` (step raises → `GET /api/health` returns `startup.degraded == true` and `startup.failed_steps` contains the step name and the exception text; the failure is recorded, not swallowed, and other steps still run); `test_startup_completes_while_optional_steps_slowed` (localhost node, hardware snapshot, MCP refresh and presence restore each faked to sleep 5 s → `startup()` returns in < 1 s and `/api/health` answers meanwhile); `test_optional_steps_cancelled_on_shutdown` (steps still pending at `shutdown()` → cancelled and awaited, `_startup_tasks` empty, no "Task was destroyed but it is pending" warning).

### S2 — ANZU process registry + identity-checked managed server

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S1

| Path | Why |
| --- | --- |
| `backend/app/runtime/process_registry.py` (new) | `register(kind, pid, create_time, argv, port, owner_module, lifetime)` (`lifetime` ∈ `short` (registered_subprocess), `child` (terminated on shutdown), `detached` (left running on shutdown; used by S3's Ollama start)), `unregister`, `snapshot()`, `is_anzu_owned(pid, create_time)`, `registered_subprocess(...)` async context manager for short-lived children; argv stored **redacted** (secret flags `--api-key`, `--token`, `--password`, `--hf-token`, `--key`, `--secret` and any `KEY=VALUE` env-style arg with a secret-like key are replaced by `***`); atomic persist to `data_dir()/runtime/process-registry.json` |
| `backend/app/inference/backends.py` | Register/unregister managed llama-server (worker + front); pre-spawn port check → `port_conflict`; health accepts only listener pid == registered pid; `probe_remote_server` rejects non-2xx (ported from #648) |
| `backend/app/modules/supervisor.py` | Register module workers — covers `modules/crucix_runtime.py` (Crucix `node server.mjs`) and `studio/blackgrid_runtime.py` (BlackGrid), which spawn through `get_supervisor(...).start` (D2 #4) |
| `backend/app/modules/supermemory_runtime.py` | Register the Supermemory sidecar |
| `backend/app/workers/voice.py` | Register voice/STT subprocesses: ffmpeg conversion, whisper.cpp CLI, SAPI STT PowerShell (short-lived, via `registered_subprocess`); first owner in the chain S2 → RFC-0226 S2 |
| `backend/app/tts/system_sapi.py` | Register SAPI PowerShell synthesis subprocesses (short-lived) |
| `backend/app/tts/synthesize.py` | Register the Piper CLI subprocess (short-lived); first owner in the chain S2 → RFC-0226 S2 |
| `backend/app/api/processes.py` (new) | `GET /api/system/processes` → registry snapshot + live status (running/exited/orphaned, CPU %, RSS), argv never returned raw (redacted form only) |
| `backend/app/main.py` | Include the processes router; terminate/unregister registered `child` processes on shutdown (existing order kept; `detached` entries are left running); second owner in the chain S1 → S2 → S3 |
| `tests/test_rfc0225_process_registry.py` (new); `tests/test_rfc0225_flicker_repro.py` | Below; remove the xfail marker |

- [ ] Every spawn site above registers on start and unregisters on exit (incl. Crucix and BlackGrid via the supervisor, voice/STT/TTS short-lived children); a crashed child reports `exited` with exit code.
- [ ] Registry survives a core restart; stale entries (pid reused / create-time mismatch) are pruned, never killed.
- [ ] Foreign listener on 8088 before spawn → `port_conflict` with process name/pid; no spawn.
- [ ] Managed health rejects a responder on 8088 whose pid is not the registered child; `tests/test_rfc0225_flicker_repro.py` passes with the xfail marker removed.
- [ ] Registry file and API never contain a secret argv value (test with `--api-key sk-…`, `HF_TOKEN=…`).
- [ ] `GET /api/system/processes` ≤300 ms with 20 entries (psutil off the event loop).

### S3 — Engine classification, owner-consented stop, ledger, respawn/revive, VRAM gate, managed mode

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S2, RFC-0226 S2 (sequential owner of `systems/self_check.py`)

| Path | Why |
| --- | --- |
| `backend/app/inference/running_models.py` | `_poll` offer notice: the one `publish_owner_text(...)` call → `engine_coexistence.owner_line(<same text>)` (Architect decision 2026-10-20; nothing else in `_poll` changes). Classify rows `anzu_owned` / `selected` / `anzu_configured` / `foreign` (S2 registry, `settings.inference`, enabled runtime profiles, persona brain runtimes); engine kind + exe on rows; ported #648 `scan`/`decide`/`_poll` pieces; reuse `stop_listener` / `verify_unloaded`; first owner in the chain S3 → RFC-0227 S1 |
| `backend/app/inference/engine_coexistence.py` (new) | Startup check (non-blocking), prompt payload, `engine-choices.json` (incl. `manage`, `is_managed(engine)`), stop per the rule, ledger (`stopped` + `anzu_loads`, `record_anzu_load()` / `forget_anzu_load()` / `anzu_loaded_instances()`), `respawn()`, `revive()`, `prepare_engine_for()` (single-flight, identity, VRAM gate), `note_idle_unload()` (records `unloaded_idle_at`) / `idle_unloaded()` and `note_gate_unload()` / `gate_unloaded()` / `clear_gate_unload()` hooks for RFC-0228 S2, `owner_line()`, `record_engine_failure()` / `clear_engine_failure()` / `engine_failure_items()`, on-exit respawn |
| `backend/app/inference/endpoint.py` (new) | `inference_base_url(settings)` |
| `backend/app/inference/lmstudio_server.py` | Ported #648 pieces; `record_anzu_load()` after every verified `lms load` / REST load ANZU issues; `started_by: anzu` + registry entry when ANZU launches LM Studio; `stop_lmstudio_server()`; listener identity for :1234; first owner in the chain S3 → RFC-0228 S2 |
| `backend/app/inference/ollama_runtime.py` | Real start per "Ollama start": `ollama_cli()` Windows default paths, `start_local_ollama()` (detached `ollama serve`, `OLLAMA_HOST`, log file), registry entry `lifetime="detached"` + `started_by: anzu`, readiness poll, timeout/early-exit kill of the spawned pid only, `start-timeout` / `start-exited` results; listener identity for :11434 |
| `backend/app/api/named_personas.py` | Only `_maybe_activate_persona_brain`: replace the direct `ensure_local_ollama` call with `prepare_engine_for(profile)` (failure → owner line per "Owner-line surfaces" 1 + 2, not just a log). Disjoint from RFC-0218 S3b's hunks (`NamedPersonaPut`, `put_named_personas`); chain RFC-0218 S3b → 0225-S3 |
| `backend/app/systems/self_check.py` | Only: append the per-engine `engines:<engine_id>` items from `engine_coexistence.engine_failure_items()` to `checks` (second owner after RFC-0226 S2, whose `household_voice` hunk is untouched) |
| `backend/app/persona/inference_context.py` | Only: forward the existing `task_id` to `MANAGER.load` / `MANAGER.ensure_runtime` (only owner in the batch) |
| `backend/app/inference/vram.py` (new) | Free-VRAM measurement (NVML or `nvidia-smi`), "no NVIDIA GPU" result |
| `frontend/src/hud/EngineNotices.tsx` (new) | The `engine_notice` consumer (Owner-line surfaces 2): SSE on `/api/owner/chat/events`, chip, speech via `queueChatSpeech` gated by `useSpeakChatReplies()`, dedupe by `id`, skip speech for the open task's own lines, reconnect backoff |
| `frontend/src/hud/HudShell.tsx` | One mount line `<EngineNotices />` next to `<HudLocalStatus …/>`; no other hunk (first owner in the chain 0225-S3 → 0225-S4 → RFC-0226 S3) |
| `frontend/engine-notices.test.mjs` (new); `frontend/package.json` (`test:engine-notices`, one line); `.github/workflows/pr-tests.yml` (one append-only `frontend-build` step `- name: Engine notices tests (RFC-0225 S3)` / `run: npm run test:engine-notices`) | Below |
| `backend/app/inference/hotswap.py` | Call `prepare_engine_for` in `activate_runtime_profile` before the probe; first owner in the chain S3 → RFC-0228 S2 |
| `backend/app/inference/manager.py` | Call `prepare_engine_for` in `ensure_runtime` / `_load_locked` for non-managed endpoints; first owner in the chain S3 → RFC-0228 S2 |
| `backend/app/main.py` | `_autoload_model` ported from #648; shutdown → on-exit respawn; third owner in the chain S1 → S2 → S3 |
| `backend/app/api/model.py` | `GET /api/model/engines` (rows with class, kind, port, pid/exe, model ids, busy, `unloaded_idle_at` from the hook — the field name landed RFC-0229 S2 reads), `POST /api/model/engines/decision` (`keep` / `stop` / `stop_always`, `remember`, `respawn_on_exit`, `manage`), `GET /api/model/engines/ledger`, `POST /api/model/engines/{id}/respawn` |
| `tests/test_rfc0210_running_models.py` | **Exactly** the #648 fixture changes, every other assertion kept: (a) `test_valid_server_uses_metadata_only` parametrized over ports 1235 and 11434; (b) `test_background_reconnect_requires_existing_owner_choice` sets `settings.inference.auto_load = True`; (c) `test_startup_waits_for_owner_choice_before_loading_worker` renamed `test_startup_loads_saved_model_without_waiting_for_discovery` with assertion `load.assert_awaited_once_with(settings, context_size=settings.inference.context_size)` (behaviour change required by the non-blocking startup prompt); (d) **(Architect decision 2026-10-20)** `test_new_offer_is_announced_once_on_front_voice_lane` renamed `test_new_offer_is_announced_once_on_owner_channel`: it now patches `engine_coexistence.owner_line` instead of `chat_delivery.publish_owner_text` and asserts one call with the RFC-0210 text. The `lane == "front"` assertion goes, because it pinned the dead channel; it is replaced by an assertion that a patched `publish_owner_text` is never called. This is the only RFC-0210 assertion that changes, and it changes because the behaviour was the bug |
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
- [ ] **(D2 third re-review #1)** Owner lines reach the owner, in `tests/test_rfc0225_owner_lines.py` (new): `test_owner_line_publishes_engine_notice_on_owner_channel` (exact dict on a `BUS.subscribe(OWNER_CHAT_CHANNEL)` queue: `kind == "engine_notice"`, `title == "Local engines"`, `stage == "engine_coexistence"`, `json.loads(detail)` has `text`/`level`/`engine_id`/`task_id`/`id`); `test_owner_line_with_task_also_on_task_stream` (task queue receives one `engine_notice` and one `chat_tts` titled "Local engines", and a `TaskEvent` row exists for the `engine_notice`); `test_owner_line_never_uses_publish_owner_text` (patched `publish_owner_text` never called); `test_every_rfc0225_owner_line_goes_through_owner_line` (static: no other module calls `publish_owner_text` for the strings in this RFC, and `inference/running_models.py` contains no `publish_owner_text`); **(Architect decision 2026-10-20)** `test_running_models_offer_notice_reaches_owner_channel` (real `RunningModels` with one pending foreign row, `scan` and `sleep` faked as in `test_rfc0210_running_models.py`, and a real `BUS.subscribe(OWNER_CHAT_CHANNEL)` queue: after two poll iterations the queue holds **exactly one** `engine_notice` whose `json.loads(detail)["text"]` is the byte-identical RFC-0210 text, with `stage == "engine_coexistence"` and the row's `engine_id`; a patched `publish_owner_text` is never called; a second new row gives a second frame). Frontend `frontend/engine-notices.test.mjs` (fake `EventSource` and fake `queueChatSpeech`, fed the exact backend frame): `engine notice shows a chip and is spoken when speak-replies is on`; `engine notice is not spoken when speak-replies is off`; `assistant and chat_tts frames on the owner channel are ignored`; `a notice for the open task is shown but not spoken twice`; `duplicate id is shown once`; `reconnects with backoff after an error`; `running-models offer notice frame is shown and spoken once` (fed the frame shape that `test_running_models_offer_notice_reaches_owner_channel` asserts, built inline in the test with the byte-identical RFC-0210 text; the chip text equals that text and fake `queueChatSpeech` gets it once; no new fixture file).
- [ ] **(D2 third re-review #2)** `tests/test_rfc0225_owner_lines.py::test_two_failing_engines_give_two_self_check_items` (an Ollama start failure and an LM Studio reload failure → `run_self_check()` contains `engines:ollama@127.0.0.1:11434` and `engines:lmstudio@127.0.0.1:1234`, ids unique; a second failure on the same engine replaces its text rather than adding a third item).
- [ ] **(D2 #3)** 9B holding a request lease → no unload until the lease ends.
- [ ] `anzu_loads` is written after every ANZU load and pruned when native inventory no longer lists the instance; an instance the owner loaded with the same model key is never added (instance id compared).
- [ ] **(D2 re-review #2)** Ollama start, in `tests/test_rfc0225_ollama_start.py` (new; `Popen`, probe and registry faked): `test_dead_ollama_is_started_when_binary_exists` (nothing on :11434, `ollama_cli()` → fake path → `Popen` invoked exactly once with `[cli, "serve"]`, `OLLAMA_HOST=127.0.0.1:11434`, detached flags; registry entry `kind="ollama"`, `lifetime="detached"`, `started_by="anzu"`; probe flips ok → `ensure_local_ollama` returns ok and the pull/warm step runs); `test_ollama_binary_resolved_from_localappdata` (not on `PATH`, file at `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` → that path used); `test_missing_ollama_binary_never_spawns` (no binary anywhere → `Popen` never called, `method == "missing-cli"`, owner line "Couldn't start Ollama: Ollama is not installed…" via `prepare_engine_for`); `test_ollama_start_timeout_kills_only_spawned_pid` (never ready → after 45 s (fake clock) the spawned pid is terminated and unregistered, `method == "start-timeout"`, owner line shown, request fails); `test_ollama_early_exit_reported` (spawned process exits code 1 → `start-exited` with the exit code, no further polling); `test_listening_ollama_is_not_spawned_again` (probe ok → no `Popen`); `test_umi_brain_revives_dead_ollama` (`_maybe_activate_persona_brain` for Umi with Ollama dead → `prepare_engine_for` → started → brain activated); `test_umi_brain_start_failure_reaches_owner_surfaces` (start fails inside the background task → exactly one `engine_notice` frame with `level: "error"` and "Couldn't start Ollama for Umi's brain: …" on a `BUS.subscribe(OWNER_CHAT_CHANNEL)` queue (the frame `EngineNotices` renders and speaks, see `frontend/engine-notices.test.mjs`), `publish_owner_text` not called, **and** `GET /api/system/self-check` returns an `engines:ollama@127.0.0.1:11434` item with status `degraded` and that text; a later successful start clears the item). The health-rail rendering is asserted in S4.
- [ ] **(D2 #4)** Non-LM-Studio process listening on 1234 (or non-Ollama on 11434) → `port_conflict` with process name/pid; nothing loaded.
- [ ] `manage: true` persisted, survives restart, returned by `is_managed()`; `manage: false` reverts immediately; `manage` rejected for non-selected or non-LM-Studio engines; managed mode never stops the LM Studio server/app.
- [ ] `respawn_on_exit` honoured on shutdown; remembered `stop_always` applies on next start and the startup line names what was stopped.
- [ ] Startup autoload does not wait for discovery choices (ported #648 behaviour) and a failed LM Studio boot does not overwrite the saved selection.

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
| 0225-S1 | Root-cause evidence + ported event-loop stall fixes | Grok 4.5 | D1 | — |
| 0225-S2 | Process registry + identity-checked managed server | Grok 4.6 | D1 | S1 |
| 0225-S3 | Engine classification, consented stop, ledger, respawn/revive, VRAM gate, managed mode | Grok 4.6 | D1 | S2, 0226-S2 |
| 0225-S4 | Startup engine prompt + managed-mode question | Composer 2.5 | UX | S3 |
| 0225-S5 | Debounced identity-checked reachability | Grok 4.5 | UX | S1 |

## Likely files

See per-slice tables. Sequential ownership chains across the batch (never concurrent): `main.py` 0225-S1 → S2 → S3; `api/model.py` 0225-S1 → 0225-S3 → 0227-S1 → 0228-S2; `running_models.py` 0225-S3 → 0227-S1 (S3 moves the offer notice onto `owner_line()`, and 0227-S1 keeps it there); `lmstudio_server.py` 0225-S3 → 0228-S2; `hotswap.py` 0225-S3 → 0228-S2; `manager.py` 0225-S3 → 0228-S2; `config.py` 0228-S1 → 0228-S2 (not edited here); `workers/voice.py` 0225-S2 → 0226-S2; `tts/synthesize.py` 0225-S2 → 0226-S2; `HudShell.tsx` 0225-S3 → 0225-S4 → 0226-S3; `api/named_personas.py` RFC-0218 S3b → 0225-S3 (disjoint functions); `systems/self_check.py` 0226-S2 → 0225-S3 (disjoint hunks).

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
