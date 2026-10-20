# RFC-0230: PC first response under 1.5 s

**Status:** accepted
**Priority:** P0 (Taco ask, 2026-10-20: "on the PC the first response takes about 21 s")
**Author:** Jarvis Architect
**Date:** 2026-10-20
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §4 ("The end goal is conversational latency. ANZU should acknowledge simple requests almost immediately"), §6 ("Simple operations should feel like conventional software"), §19 ("Do not optimize benchmarks while damaging perceived responsiveness"), §20 Q11.
**Builds on (port, do not rewrite):** [RFC-0117](0117-tiny-front-chat-responder.md) (warm front responder + 2026-10-08 ack-only-when-late), [RFC-0127](0127-swift-initial-reply-and-progress.md), [RFC-0171](0171-system-one-reflex-lane-jev-laya-priority.md) / [RFC-0206](0206-jev-laya-every-turn-arbitration.md) (50 ms reflex), [RFC-0203](0203-fast-path-lane-consolidation.md), [RFC-0214](0214-performance-compass.md), #550 (resident CPU Qwen3.5-2B front, 4B option, remote node with local fallback; Taco's 2026-10-08 decision).
**Reconciles with (open):** #648 RFC-0223 (head `b942bcde`), #649 RFC-0224 (head `edb46857`, content `b5c3640`), #652 RFC-0225, #655 RFC-0228, #665 RFC-0231, #664 RFC-0232.
**Astra boundary:** persona, WebGL and presence internals are out of scope. Live UI is touched only add-alongside, with the reasoning pass below.

This PR is **specs-only** (plus evidence assets). No application code.

---

## 1. Measured breakdown (read this first)

Nobody can run Taco's PC from here. Every number below names its source. **VRPC** is Taco's PC (RFC-0215: "the owner usually works over RDP on VRPC"); VRPC numbers come from the #648/#649 PR bodies. **Box** numbers were measured on 2026-10-20 on the shared agent VM (8 vCPU Xeon, no GPU, other agents running, loadavg 3–37), with the backend at `development` `11b264a` and engines stubbed where stated. Raw data and scripts: [`assets/0230-box-timings.json`](assets/0230-box-timings.json), [`assets/0230-turn-overhead-harness.py`](assets/0230-turn-overhead-harness.py), [`assets/0230-voice-bench.py`](assets/0230-voice-bench.py). Box numbers show code-path cost and orders of magnitude only. They are never the PC figure.

### 1.1 The desktop path today

HUD typed turn: `HudChat.tsx` `POST /api/tasks` → `AgentRuntime.create_task` (`agent/loop.py:478-558`, awaits `evaluate_request_route` at `:504`, two SQLite commits) → `_run` → `_run_conversation` (`:1229`) → `generate_front_reply` (`:1420`) → `_speak_front_reply` publishes `chat_tts` → the browser (`tts/useTaskSpeech.ts`) `POST /api/voice/speak` → full WAV → play.
HUD voice turn: `useLocalVoiceListen.ts` records the whole clip, uploads it to `POST /api/voice/listen` (`api/voice.py:82-102`) → `transcribe_audio` → `create_task` → same as typed.

### 1.2 Stage table

| # | Stage | development `11b264a` | After #648/#649 | Source | PC figure |
|---|---|---|---|---|---|
| 1 | STT model load | `WhisperModel(...)` is constructed on **every** utterance (`workers/voice.py:402`). Box: **0.29–0.37 s** per call (faster-whisper base, the bootstrap default, `installer/windows/bootstrap.ps1:630-634`) | unchanged | box | **not measured** → S0 |
| 2 | STT transcribe | runs **synchronously on the event loop** (`workers/voice.py:372-373`, plus the synchronous `voice_status()` call at `:355`), so every API call, the HUD health probe and other turns stall meanwhile. Box: **0.95–1.13 s** for a 3.8 s clip | unchanged | box | **not measured** → S0 |
| 3 | Intake (`POST /api/tasks` returns) | box: **6–22 ms** warm, **48–56 ms** first turn in a process | unchanged | box (stub engines) | S0 |
| 4 | Reflex lane (Jev/Laya, `decide_owner_turn`) | box, rules tier, Laya off: p50 **3.5 ms**, p95 **4.1–5.6 ms**, max **5.7–34 ms**, first call **7–9 ms** (n=300). Laya on VRPC: first probe **~1.3 s** (cold), which the 50 ms `wait_for` (`decision/owner_turn.py:548-575`) turns into a deadline fallback while the thread keeps running | `basic_qa` shape added (#649) | box; VRPC (#649 body) | S0 |
| 5 | Front model ready | front llama-server starts at boot (`main.py:368-374`), warmup sends one user-only `"Hi"` (`inference/front_runtime.py:582`), which does **not** warm the real prefix | #649 warms the real `small_context_envelope` prefix | code; #649 | S0 (cold-start mark) |
| 6 | Front request | `small_context_envelope` sends **two** system messages (`agent/front_responder.py:701-704`). The shipped Qwen template rejects that with **HTTP 500**, so on development every front request fails and the turn waits for the worker | #649 sends one system block. VRPC 2B CPU: **0.935 s** cold prompt (prompt eval 600 ms for 329 tokens) / **0.263 s** cached prefix; 0.8B **0.555 / 0.356 s**; `generate_front_reply` against the resident 2B: **1.078 s**, first text **750 ms** | #649 body (VRPC benchmark) | VRPC numbers exist; end-to-end not measured |
| 7 | Front output → speech | the whole front reply is buffered (JSON payload, `front_responder.py:856-878`) before TTS is enqueued | unchanged | code | S0 |
| 8 | Ack hold | `ack_continue`/`handoff_notice` held **1.2 s** (`ACK_HOLD_SECONDS`, `front_responder.py:37`) by design. Box, task prompt: first `chat_tts` at **1217–1229 ms** | "What is RAM?" becomes `basic_qa` → `final_basic`, no hold | box; code | S0 |
| 9 | Worker cold load in the turn | the turn awaits `MANAGER.load` when nothing is loaded (`loop.py:2474-2478`, `:1355-1356`; `persona/owner_chat.py:710-719`). VRPC: selected model restored in **4.888 s** (frozen backend healthy at 4.356 s) | #648 restores the saved model at startup without waiting for discovery | #648 body (VRPC) | per-turn **not measured** → S0 |
| 10 | Router escalation | `prepare_answer_route` can hot-swap mid-turn with `MANAGER.load(..., force=True)` (`inference/model_escalation.py:165`); the 120 s restore reloads the 9B later (`:80-87`) | RFC-0228 S2 replaces the restore with `NINE_B_REWARM` | code | **not measured** → S0 |
| 11 | Worker first token | unknown: LM Studio 9B on `127.0.0.1:1234` (Taco) or ANZU llama-server | — | — | **not measured** → S0 |
| 12 | TTS synthesis | Kokoro runs on **CPU** (`tts/kokoro_adapter.py:137`). `/api/voice/speak` returns a full WAV per chunk (`api/voice.py:122-146`, `tts/chatTtsPlayer.ts:58-67`). If Kokoro is not verified yet, the first speak runs a full verify synthesis inline (`tts/synthesize.py:253-257`). Box: import **3.9–4.0 s** + model/pipeline **1.7 s** (covered by warm start); "Right away." **0.28–0.85 s**; a 57-char sentence **0.52–2.97 s** | unchanged | box | **not measured** → S0 |
| 13 | "First audio" metric | `front_first_audio_ms` is stamped at TTS **enqueue** (`persona/owner_chat.py:610`, `agent/loop.py:1069`, `:1085`), not at playback, so today's diagnostics cannot show the audible time | — | code | S0 fixes |
| 14 | Code path to first `chat_tts` (instant fake engines) | box: **23–33 ms** warm, **121–136 ms** first turn | — | box | — |
| 15 | Backend startup | box: `import app.main` **1.8–3.7 s**; spawn → `/api/health` 200 **2.4 s**; Laya `restore_on_startup()` runs synchronously on the startup path (`main.py:219-221`) | #648 moves several startup steps off the loop | box; code | not on the turn path |

Other VRPC figures on record: installed chat with the front lane on **3.927 s**, later **1.661 s** (#648 body; the PR does not say which stage that timer covers). Status reads after #648: health median 24.66 ms / P95 305 ms, model median 61 ms / P95 675 ms.

**RFC-0224's attribution** ("the owner observed a 21-second model-status read") is recorded here as an **unmeasured hypothesis**. #649's non-waiting status read removes that stall class, but nobody has shown that the status read is what Taco hears as a 21 s first response.

**What the evidence says.** The ANZU code path costs tens of milliseconds, and the reflex lane stays far inside 50 ms with rules. The known multi-second terms are: the dead front on development (#6), a cold or escalated worker load inside the turn (#9, #10), CPU STT on the event loop with a per-call model load (#1, #2), CPU Kokoro synthesizing a whole chunk before playback (#12), and the 1.2 s hold whenever the front only acks (#8). The sum of the measured terms does not reach 21 s on its own, so the PC split is unknown until S0 lands. **S0 is first and measures before and after.**

## 2. Target

**Hard target (owner-visible, measured by S0 on VRPC):** from end of owner input (Enter, or mic release) to **first audible word ≤ 1.5 s at p50 and ≤ 2.0 s at p95** for a typed turn with the warm 2B front, over 20 turns of `scripts/anzu-latency-repro.ps1`. That includes the first turn after boot and the first turn after a worker idle unload: the resident front speaks, and the worker answers after. Voice turns add STT: **≤ 2.5 s p50** from mic release for clips ≤ 5 s. The reflex lane stays **≤ 50 ms on every turn** (Taco's mandate), and S0 records `decide_ms` on every turn.

**Budget for the 1.5 s:** reflex ≤ 50 ms + front first sentence ≤ 700 ms on a cached prefix (VRPC 2B: 263 ms for 10 tokens) + Kokoro first sentence ≤ 500 ms + transport and playback start ≤ 150 ms + slack 100 ms.

**Why this number (north star §4, §6):** a person hears a pause of more than about a second as a stall. 1.5 s is the longest gap that still reads as "ANZU heard me". It is reachable with the shipped 2B on CPU, the VRPC numbers already show it (a 263 ms cached-prefix front), and it does not ask for a bigger GPU or a cloud call.

## 3. Decisions

1. **The first audible word always comes from the resident front lane, never from a worker load.** The worker answers after; RFC-0117's merge rules are unchanged.
2. **When the turn knows the worker must load** (not loaded, idle-unloaded by RFC-0228, or an escalation is decided), the ack hold is skipped. ANZU speaks the front ack at once, because an answer cannot beat 1.2 s. The hold stays for every other case (RFC-0117/0127 2026-10-08 amendments).
3. **2B CPU stays the default** (Taco 2026-10-08, #550). The 4B (GPU-fit gated) and the #649 0.8B stay options. The remote front node keeps its local fallback. The front lane is never idle-unloaded: RFC-0228 already exempts `front_responder.resident`.
4. **The worker is reloaded on owner activity, not on a timer.** Mic press and the first keystroke in the composer send a prewarm; it goes through RFC-0225 `prepare_engine_for` (single-flight). That respects RFC-0228's idle unload (15 min default), its `NINE_B_REWARM` coordinator (never a second timer) and LM Studio on `127.0.0.1:1234` (on-demand reload/revive). No keep-alive ping for the worker.
5. **The front lane is kept warm.** One cached-prefix ping after 10 min of front idleness keeps the prompt cache and page cache hot; it is CPU only, no VRAM.
6. **STT is resident and off the loop.** One Whisper model is loaded at startup and reused. Transcription runs in a worker thread.
7. **TTS speaks the first sentence first.** The front's first sentence is enqueued as soon as it is complete in the stream, and the first sentence of any chunk is synthesized as its own request. Kokoro is never verified inside an owner turn.
8. **Reflex lane:** a dedicated single-thread executor for `decide()`, so a slow Laya call or a busy default pool cannot delay the next turn. Laya warms off the loop.
9. **#648/#649 are reused, never re-ported.** A slice that needs a #649 piece depends on #649.

## 4. Relationship to #648 / #649 (CoS 2026-10-20: both may land first)

| Piece | Owner | This RFC |
|---|---|---|
| Single leading system envelope, real-prefix front warmup, `basic_qa` shortcut, 0.8B front option (`front_responder.py`, `front_runtime.py`, `decision/owner_turn.py`, `profiles.py`) | #649 | **S2 and S5 depend on #649** and build on these hunks; no duplicate |
| Non-waiting status read (`status_refresh_pending`), 30 s `model_details_cache`, system/diagnostics/swarm work off the request thread | #649 (RFC-0225 S1 reuses) | not touched; S0 stays out of `api/diagnostics.py` |
| Startup restore of the saved model, `_start_optional_step`, `front_runtime` decide in a thread, Kokoro `_warmup_guarded` | #648 (RFC-0225/0226 reuse) | S5 moves Laya restore off the loop only; nothing else in startup |
| `task_workflow` large-task stages, owner_chat split replaced by one task | #649 | out of scope (RFC-0231 builds on it) |

If #649 has not landed when S2 or S5 starts, the slice waits for it. Every other slice lands on current `development`.

## 5. Live-UI add-alongside reasoning pass (2026-10-14 standing order)

| Live behaviour | Preserved? | Added alongside |
|---|---|---|
| HUD composer, mic button, transcript and Show work (`HudChat.tsx`, `OwnerChatTranscript.tsx`) | **Yes**, no visual change | S0: one `turn_latency` task event, rendered by the existing event list as a plain line ("Heard you 0.4 s · first word 1.2 s · …"), never raw JSON. S3: a prewarm call on mic press / first keystroke, with no visible element |
| Chat speech playback order, barge-in (`stopChatTts`), prefetch (`chatTtsPlayer.ts`) | **Yes** | S0: one playback-started mark per turn. S4: the first sentence arrives as its own queue item |
| Ack-only-when-late, no double ack | **Yes** | S3: the hold is skipped only when a load is known to be needed; still at most one ack |
| Persona, presence, WebGL | untouched (Astra) | — |

Each implement PR carries a "Preserved live behaviour" section with a test or screenshot per row.

## 6. Stub rule

No stubs, soft-fails or orphans. A span that nothing records, a mark endpoint no client calls, a prewarm nobody triggers, or a timing field that measures enqueue but is labelled "audio" fails review.

---

## 7. Slices (one developer each, fast off)

Order: **S0 first.** Then S1 ∥ S4 ∥ S5, then S2 (after #649), then S3 (after S0 and RFC-0225 S3).

### S0 — Per-turn latency trace, owner-visible, with a one-command PC repro

**Model:** Grok 4.6 · **Lane:** D1 · **Depends:** none

A permanent product feature, not debug scaffolding. One `TurnTrace` per owner turn (keyed by task id, or `owner:<conversation_id>`) records monotonic marks:
`input_end` (client stamp, sent as `X-ANZU-Input-End` with the request), `request_received`, `stt_model_ready`, `stt_done`, `decide_done` (+ `decide_ms`, `decide_source`: rules / jev / laya / deadline_fallback), `front_ready` (+ `front_cold: bool`, true when the front server was started or reloaded for this turn), `front_first_token`, `front_first_sentence`, `ack_hold_end` (when held), `worker_load_start` / `worker_load_done` (+ `reason`: cold / idle_reload / escalation), `worker_first_token`, `tts_enqueued`, `tts_synth_done` (from `/api/voice/speak`, correlated by `X-ANZU-Turn`), `first_audio` (client playback start).

| Path | Why |
|---|---|
| `backend/app/observability/turn_trace.py` (new) | `TurnTrace`, `mark(turn_id, name, **meta)`, `finish(turn_id)`, ring buffer of the last 50 turns persisted to `data_dir()/logs/turn-latency.jsonl`; `summary_line(trace)` for the owner-facing line |
| `backend/app/agent/loop.py` | marks in `create_task` (`request_received`, `decide_done`), `_run_conversation`, `_run_managed_front_lane`, `_speak_front_reply`, both `MANAGER.load` sites; on finish one persisted task event `turn_latency` (title "Response timing", detail = `summary_line`). First owner in the chain |
| `backend/app/persona/owner_chat.py` | same marks on the owner-chat path (`OWNER_CHAT_CHANNEL`); replaces the enqueue-time `front_first_audio_ms` with `tts_enqueued_ms` and leaves `first_audio` to the client mark |
| `backend/app/api/voice.py` | `listen`: `request_received`, `stt_model_ready`, `stt_done`; `speak`: `tts_synth_done` when `X-ANZU-Turn` is present (existing `Server-Timing` kept) |
| `backend/app/api/turn_latency.py` (new) | `GET /api/turn-latency?limit=20` (traces + p50/p95 per stage), `POST /api/turn-latency/{turn_id}/marks` (client marks `input_end`, `first_audio`; only these two names accepted) |
| `backend/app/main.py` | one `include_router` line. First owner in the chain 0230-S0 → 0230-S5 → 0225-S1 → 0225-S2 → 0225-S3 |
| `frontend/src/tts/chatTtsPlayer.ts` | `X-ANZU-Turn` header on `/api/voice/speak`; on the first `audio.play()` of a turn, POST the `first_audio` mark once |
| `frontend/src/api.ts` | stamp `X-ANZU-Input-End` on `POST /api/tasks`, `/continue` and `/api/voice/listen` |
| `scripts/latency_repro.py` (new), `scripts/anzu-latency-repro.ps1` (new) | One command on the PC: `powershell -File scripts\anzu-latency-repro.ps1` runs 20 typed turns (5 social, 10 `basic_qa`, 5 task-shaped) and 5 voice turns from bundled WAVs against the running ANZU, once cold (after `stop-jarvis.ps1` / start) and once warm, then prints the §1.2 table as Markdown from `GET /api/turn-latency` and writes `data/logs/turn-latency-report.md` |
| `tests/fixtures/voice/rfc0230_hello.wav`, `rfc0230_question.wav` (new) | 2–4 s clips for the repro and tests |
| `tests/test_rfc0230_turn_trace.py` (new); `frontend/turn-latency-marks.test.mjs` (new); `frontend/package.json` (`test:turn-latency-marks`, one line); `.github/workflows/pr-tests.yml` | see below |

Acceptance:
- [ ] `test_turn_trace_marks_typed_turn_in_order`: stub front + worker; `POST /api/tasks` → marks `request_received < decide_done < front_first_token < tts_enqueued` and one persisted `turn_latency` event whose detail is the plain summary line (asserted to contain no `{`).
- [ ] `test_turn_trace_records_worker_cold_load`: worker not loaded → `worker_load_start/done` with `reason="cold"`.
- [ ] `test_turn_trace_records_front_cold_flag`: front server started inside the turn → `front_cold == True`.
- [ ] `test_turn_trace_decide_source_and_ms`: deadline fallback → `decide_source == "deadline_fallback"`, `decide_ms` present.
- [ ] `test_voice_listen_records_stt_marks`: fake STT backend → `stt_model_ready`, `stt_done`.
- [ ] `test_client_marks_accept_only_known_names`: `first_audio` accepted; any other name → 422.
- [ ] `test_turn_latency_endpoint_percentiles`: 20 seeded traces → p50/p95 per stage match a hand computation.
- [ ] `test_first_audio_field_is_client_mark_only`: no server code writes `first_audio`.
- [ ] `frontend/turn-latency-marks.test.mjs`: `queueChatSpeech` sends `X-ANZU-Turn` and posts `first_audio` exactly once per turn, even with two queued chunks.
- [ ] CI: `pr-tests.yml` `pytest` job gains `- name: RFC-0230 latency contract tests` / `run: python -m pytest -q tests/test_rfc0230_*.py` (before "Run full backend suite"); `frontend-build` gains `- name: Turn latency mark tests (RFC-0230 S0)` / `run: npm run test:turn-latency-marks`. S0 owns these two append-only steps; S1–S5 add their test files to the same glob.
- [ ] **PC acceptance:** Taco runs the repro on VRPC before S1–S5 land; the report is attached to the S0 PR, and its numbers replace "not measured" in §1.2 by an amendment to this RFC.

### S1 — STT resident and off the event loop

**Model:** Grok 4.5 · **Lane:** D2 · **Depends:** S0

| Path | Why |
|---|---|
| `backend/app/workers/voice.py` | `_whisper_model()` cache: one `WhisperModel` per (path, device, compute type) behind a lock; `transcribe_audio` runs the faster-whisper / openai-whisper calls and `voice_status()` via `asyncio.to_thread`; `warm_stt()` loads the model and transcribes 0.5 s of silence. First owner in the chain 0230-S1 → 0225-S2 → 0226-S2 (registry wrappers and fallback edits rebase onto it) |
| `backend/app/voice_warm.py` (new) | `schedule_stt_warm_start()` fire-and-forget at startup, result in `last_stt_warm_report()` and in S0's `stt_model_ready` |
| `backend/app/api/voice.py` | `GET /api/voice/status` adds `stt_warm` (second owner after S0) |
| `tests/test_rfc0230_stt_resident.py` (new) | below |

- [ ] `test_whisper_model_loaded_once_across_utterances`: three transcriptions → one model construction.
- [ ] `test_transcribe_does_not_block_event_loop`: fake transcribe sleeps 1 s → a concurrent `/api/health` answers in < 100 ms.
- [ ] `test_stt_warm_start_reports_ready_and_failure`: warm failure is recorded and shown in `/api/voice/status`, never swallowed.
- [ ] VRPC (S0 repro): `stt_model_ready` ≈ 0 ms on warm turns; voice p50 from mic release to first audio ≤ 2.5 s.

### S2 — Front lane: streamed first sentence, kept warm, cold-start visible

**Model:** Grok 4.6 · **Lane:** D1 · **Depends:** #649 (envelope, prefix warmup, `basic_qa`, 0.8B), S0

| Path | Why |
|---|---|
| `backend/app/agent/front_responder.py` | Incremental parse of the front payload's `text` field while streaming; the first complete safe sentence goes to `on_first_sentence` (same `enforce_front_safety` / `is_safe_front_speech` checks on that sentence; the full-reply check still runs at the end and a rejected reply cancels queued speech). First owner after #649 |
| `backend/app/inference/front_runtime.py` | Idle keep-warm (one cached-prefix request after 10 min of front idleness, CPU only, skipped while a turn runs); health watchdog: a dead front server is restarted off the turn path and the next turn's S0 trace has `front_cold = true`; remote placement fallback to local unchanged (#550) |
| `backend/app/agent/loop.py`, `backend/app/persona/owner_chat.py` | wire `on_first_sentence` to `_speak_front_reply` / `maybe_enqueue_streaming_social_tts` (second owner after S0) |
| `tests/test_rfc0230_front_stream.py` (new) | below |

- [ ] `test_front_first_sentence_enqueued_before_reply_completes`: stub streams 40 tokens at 20 ms → `tts_enqueued` before the stream ends.
- [ ] `test_unsafe_full_reply_cancels_streamed_sentence`: safety rejection at the end → queued item removed, no double speech.
- [ ] `test_front_keep_warm_ping_after_idle`: fake clock 10 min idle → exactly one cached-prefix request; none during an active turn.
- [ ] `test_dead_front_restarted_off_turn_path`: health fails → restart scheduled; the turn falls back exactly as today.
- [ ] `test_front_default_stays_2b_cpu`: `config/default.json` profile `front_2b`, device `auto` → CPU, `-ngl 0`; 4B and 0.8B still selectable.

### S3 — Worker load never sits between input and first word

**Model:** Grok 4.6 · **Lane:** D1 · **Depends:** S0, RFC-0225 S3 (`engine_coexistence.prepare_engine_for`; read-only import, that file is not edited here)

| Path | Why |
|---|---|
| `backend/app/inference/turn_prewarm.py` (new) | `prewarm_worker(reason)`: when the selected worker is not loaded or is idle-unloaded, calls `prepare_engine_for(target)` (single-flight; LM Studio `127.0.0.1:1234` reload/revive, ANZU llama-server load). Never schedules a timer and never re-warms a 9B the VRAM gate unloaded (RFC-0228 `NINE_B_REWARM` keeps that) |
| `backend/app/api/turn_latency.py` | `POST /api/turn-latency/prewarm` (second owner after S0) |
| `backend/app/agent/loop.py` | in `create_task`, start `prewarm_worker("turn")` before the reflex decision; in `_run_conversation` / `_run` skip the ack hold when `load_needed(turn)` (not loaded, idle-unloaded, or an escalation is decided) so the front ack is spoken at once; `execute_visible_model_switch` is awaited only after the front line is enqueued (third owner after S0, S2) |
| `backend/app/persona/owner_chat.py` | same prewarm + hold rule on the owner-chat path |
| `frontend/src/chat/useLocalVoiceListen.ts` | on mic press, fire-and-forget `POST /api/turn-latency/prewarm` |
| `frontend/src/hud/HudChat.tsx` | on the first keystroke of an empty composer (once per 30 s), the same prewarm call; no visible change |
| `tests/test_rfc0230_worker_prewarm.py` (new); `frontend/turn-prewarm.test.mjs` (new); `frontend/package.json` (`test:turn-prewarm`); `.github/workflows/pr-tests.yml` (`- name: Turn prewarm tests (RFC-0230 S3)` / `run: npm run test:turn-prewarm`) | below |

- [ ] `test_cold_worker_turn_speaks_front_before_load_completes`: worker load faked at 5 s → `tts_enqueued` < 300 ms (stub front), `worker_load_done` ≈ 5 s.
- [ ] `test_idle_unloaded_worker_reloads_via_prepare_engine_for`: `idle_unloaded()` true → exactly one `prepare_engine_for` call across prewarm + turn.
- [ ] `test_prewarm_never_touches_gate_unloaded_9b`: `gate_unloaded()` set → no load call.
- [ ] `test_ack_hold_kept_when_worker_warm`: worker loaded → hold unchanged (RFC-0127 tests stay green).
- [ ] `test_escalation_switch_after_front_line`: escalation decided → `tts_enqueued` precedes the `MANAGER.load(force=True)` call.
- [ ] `frontend/turn-prewarm.test.mjs`: mic press and first keystroke each send one prewarm; typing more within 30 s sends none.
- [ ] VRPC (S0 repro): first turn after a 15-min idle unload → first audio ≤ 1.5 s, worker answer follows.

### S4 — TTS: first sentence first, no inline verify

**Model:** Grok 4.5 · **Lane:** D2 · **Depends:** S0

| Path | Why |
|---|---|
| `backend/app/tts/synthesize.py` | `_synthesize_kokoro` no longer runs `verify_kokoro_runtime` inline (`:253-257`): not ready → `RuntimeError` at once, so the existing chain moves on, and the verify runs in the background (RFC-0226 S1's retry). First owner in the chain 0230-S4 → 0225-S2 → 0226-S2 |
| `backend/app/persona/chat_delivery.py` | a chunk longer than one sentence is enqueued as first sentence + remainder (two `chat_tts` items, same stream cursor) |
| `backend/app/tts/kokoro_adapter.py` | `torch.set_num_threads` capped at half the physical cores so Kokoro, the 2B front (`--threads`) and Whisper do not oversubscribe one CPU; the cap is recorded in `/api/voice/status` |
| `tests/test_rfc0230_tts_first_sentence.py` (new) | below |

- [ ] `test_long_chunk_split_into_first_sentence_and_remainder`: 3-sentence reply → two queue items, no text lost or repeated.
- [ ] `test_kokoro_not_verified_never_blocks_turn`: unverified Kokoro → speak returns or falls through in < 50 ms (fake engines), verify scheduled once.
- [ ] `test_kokoro_thread_cap`: 16-core fake → 8 threads.
- [ ] VRPC (S0 repro): `tts_synth_done − tts_enqueued` p50 ≤ 500 ms for the first sentence.

### S5 — Reflex lane ≤ 50 ms on every turn

**Model:** Grok 4.5 · **Lane:** D2 · **Depends:** #649 (owner_turn `basic_qa` hunks), S0

| Path | Why |
|---|---|
| `backend/app/decision/owner_turn.py` | `decide_owner_turn` runs `_decide_sync` on a dedicated `ThreadPoolExecutor(max_workers=1, thread_name_prefix="reflex")`; if the previous call still holds it (an abandoned Laya call after a timeout), the turn goes straight to the rules deadline fallback instead of queueing. The 50 ms budget, audit and `persona_intent` behaviour are unchanged. Chain: #649 → 0230-S5 → RFC-0231 → RFC-0232 S2 |
| `backend/app/decision/laya/runtime.py` | `restore_on_startup_async()` warms in a thread; `is_ready()` unchanged |
| `backend/app/main.py` | call the async restore instead of the synchronous one at `:219-221` (second owner after S0) |
| `tests/test_rfc0230_reflex_budget.py` (new) | below |

- [ ] `test_decide_within_50ms_while_default_executor_saturated`: default pool filled with blocked jobs → `decide_owner_turn` returns in ≤ 50 ms (event-blocked stubs, no wall-clock sleeps).
- [ ] `test_abandoned_laya_call_does_not_delay_next_turn`: Laya stub blocked → turn 1 deadline fallback; turn 2 immediate rules fallback, not queued.
- [ ] `test_laya_restore_off_startup_path`: Laya warm faked at 3 s → `startup()` returns in < 1 s.
- [ ] VRPC (S0 repro): `decide_ms` ≤ 50 on 100 % of the 25 repro turns, with Laya enabled.

## 8. Ticket cards

| ID | Title | Model | Lane | Depends |
|---|---|---|---|---|
| 0230-S0 | Per-turn latency trace + PC repro | Grok 4.6 | D1 | — |
| 0230-S1 | STT resident, off the loop | Grok 4.5 | D2 | S0 |
| 0230-S2 | Front streamed first sentence + keep-warm | Grok 4.6 | D1 | #649, S0 |
| 0230-S3 | Worker load off the first-word path | Grok 4.6 | D1 | S0, 0225-S3 |
| 0230-S4 | TTS first sentence, no inline verify | Grok 4.5 | D2 | S0 |
| 0230-S5 | Reflex ≤ 50 ms every turn | Grok 4.5 | D2 | #649, S0 |

## 9. Shared files and handoff order (0230 first, per CoS)

| File | Order |
|---|---|
| `backend/app/agent/loop.py` | #649 (if landed) → 0230-S0 → S2 → S3 → RFC-0231 → RFC-0232 S2 |
| `backend/app/persona/owner_chat.py` | #649 → 0230-S0 → S2 → S3 |
| `backend/app/decision/owner_turn.py` | #649 → 0230-S5 → RFC-0231 → RFC-0232 S2 |
| `backend/app/agent/front_responder.py`, `inference/front_runtime.py` | #648/#649 → 0230-S2 |
| `backend/app/main.py` | 0230-S0 → 0230-S5 → 0225-S1 → 0225-S2 → 0225-S3 |
| `backend/app/workers/voice.py` | 0230-S1 → 0225-S2 → 0226-S2 |
| `backend/app/tts/synthesize.py` | 0230-S4 → 0225-S2 → 0226-S2 |
| `backend/app/api/voice.py` | 0230-S0 → S1 |
| `backend/app/api/turn_latency.py` (new) | 0230-S0 → S3 |
| `frontend/src/hud/HudChat.tsx` | 0230-S3 only (one effect; no JSX change) |
| `frontend/package.json`, `.github/workflows/pr-tests.yml` | append-only: one `test:*` line and one step per frontend ticket, as in the 2026-10-17 batch |

Not edited here: `inference/manager.py`, `hotswap.py`, `lmstudio_server.py`, `engine_coexistence.py`, `rewarm.py`, `api/model.py`, `api/diagnostics.py`, `tts/warm_start.py`, `systems/self_check.py` (owned by 0225/0226/0228/#648/#649).

## 10. Files likely to overlap Astra's and Taco's unpushed PC speed fixes

Ask Taco to push these first. **No ticket waits on it**; whoever lands second rebases.

- `backend/app/agent/front_responder.py`, `backend/app/inference/front_runtime.py`, `backend/app/inference/profiles.py`, `config/default.json` (front envelope, warmup, front profile)
- `backend/app/agent/loop.py`, `backend/app/persona/owner_chat.py` (turn path, hold, overlap)
- `backend/app/decision/owner_turn.py`, `backend/app/decision/laya/runtime.py` (reflex, Laya warm)
- `backend/app/inference/manager.py`, `backend/app/inference/status_monitor.py`, `backend/app/api/model.py`, `backend/app/main.py` (status reads, startup, autoload)
- `backend/app/workers/voice.py`, `backend/app/tts/kokoro_adapter.py`, `backend/app/tts/synthesize.py`, `backend/app/tts/warm_start.py` (STT/TTS)
- `frontend/src/tts/chatTtsPlayer.ts`, `frontend/src/hud/HudChat.tsx`, `frontend/src/chat/useLocalVoiceListen.ts` (playback, polling, mic)

## 11. Out of scope

- Persona, presence, WebGL (Astra).
- Streaming STT / voice activity detection (a later RFC once S0 shows the STT share on VRPC).
- Large-prompt pipeline (RFC-0231), FFS routing (RFC-0232), engine coexistence (RFC-0225), idle unload and re-warm (RFC-0228).
- Phone path (RFC-0222/0223-Android).

## 12. Overall acceptance

- [ ] S0 lands first; VRPC "before" report attached.
- [ ] After S1–S5: VRPC repro p50 first audio ≤ 1.5 s typed, ≤ 2.5 s voice; p95 ≤ 2.0 s typed; `decide_ms` ≤ 50 on every turn; the first turn after boot and after an idle unload meets the same target.
- [ ] Live-UI rows preserved; full backend suite, `RFC-0230 latency contract tests` step and the JS steps green in CI.
