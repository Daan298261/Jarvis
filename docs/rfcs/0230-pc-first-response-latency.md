# RFC-0230: PC first response under 1.5 s

**Status:** accepted
**Priority:** P0 (Taco ask, 2026-10-20: "on the PC the first response takes about 21 s")
**Author:** Jarvis Architect
**Date:** 2026-10-20
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §4 ("The end goal is conversational latency. ANZU should acknowledge simple requests almost immediately"), §6 ("Simple operations should feel like conventional software"), §19 ("Do not optimize benchmarks while damaging perceived responsiveness"), §20 Q11.
**Builds on (port, do not rewrite):** [RFC-0117](0117-tiny-front-chat-responder.md) (warm front responder + 2026-10-08 ack-only-when-late), [RFC-0127](0127-swift-initial-reply-and-progress.md), [RFC-0171](0171-system-one-reflex-lane-jev-laya-priority.md) / [RFC-0206](0206-jev-laya-every-turn-arbitration.md) (50 ms reflex), [RFC-0203](0203-fast-path-lane-consolidation.md), [RFC-0214](0214-performance-compass.md), #550 (resident CPU Qwen3.5-2B front, 4B option, remote node with local fallback; Taco's 2026-10-08 decision).
**Landed (reused, never re-ported):** #648 RFC-0223 (`d214b6d`), #649 RFC-0224 (merge `ee786dc`; the single-system envelope is `bd873c6`).
**Reconciles with (open):** #652 RFC-0225 @ `aac2f5c`, #655 RFC-0228 @ `971ca15`, #664 RFC-0232 @ `df37b22`, #665 RFC-0231 @ `8b1ae68` (pre-push head of this joint push).
**Re-traced on:** `development` @ `bd2558b` (`3007696` plus #661, which touches only `reverse_engineering/store.py`, `apk_sidecar.py` and three RE tests). Every line reference below holds on that head (D1 re-checked them at `ae93c28`).
**Amended 2026-10-20 (joint push with #664/#665; CoS):** 0230-S3's per-turn prewarm skips while an RFC-0231 lease holds a target (`register_lease_probe` + 0231-S4's `large_prompt.active_target()`) and never touches the 27B; the busy-path RE cases are the same four as #664 (explicit, weak+probe confirms, weak+probe denies, plain negative); explicit wording skips only the dump-marker requirement; #652 @ current head, #664/#665 re-cited.
**Amended 2026-10-20 (D1 re-peer at `ae93c28`; CoS rulings):** slice rows match §9 on `synthesize.py`, `kokoro_adapter.py`, `api/voice.py`; `workers/voice.py` is 0230-S1 → 0225-S2 → 0226-S2 (S1 first; only S4 waits on the #652 chain); the S5 busy path still submits its single `decide()` and discards a late result; `inference/backends.py:379` per-launch `threads` (0230-S2 → 0225-S2); `test_inline_verify_kept_until_0226` dropped (S4 hard-depends on 0226-S2); re-traced on `bd2558b`.
**Amended 2026-10-20 (cross-citation pass 2):** #664 re-cited at `df37b22` (final helper `planning.re_intent_match`, probe `planning.probe_dump_target`); 0218-S3b (not landed) added to the `owner_turn.py` chain; the busy-path RE cases are explicit-wording or probe-confirmed and owned by 0232-S2.
**Amended 2026-10-20 (cross-citation pass):** `workers/voice.py` and `synthesize.py` list RFC-0225 S2 first, then RFC-0226 S2, then 0230 (matching #652); `kokoro_adapter.py` and `api/voice.py` put 0226-S1 before the later 0230 slice; RFC-0226 S1/S2 are cited by their real titles and pieces on development (`docs/rfcs/0226-reliable-kokoro-and-voice-fallback.md`: background re-verify with backoff in `kokoro_adapter.py`, `verify_kokoro_runtime_async()`, `fallback_chain_for_profile()`, `probe_fallback_engine()`, `voice_fallback`).
**Amended 2026-10-20 (D1 peer, 22 items at `99aef63`; CoS rulings 1-10):** #649 landed, row 6 fixed and pinned; line refs re-traced; order 0230 → 0232 → 0231 on shared files with 0218-S3b and 0232-S5 named; 0225 first on `main.py`; S5 reuses `_start_optional_step`; shared-file rows for `kokoro_adapter.py`, `api/voice.py`, `api.ts`, `answer_routing.py`, `useTaskSpeech.ts`; S4 split moved to `chatTtsPlayer.ts`; S4 inline-verify removal hard-depends on 0226-S1/S2; S0 repro drives the real HUD and closes on browser playback start; trace finish defined; `turnId` in `SpeakOpts`; `owner_chat.py` dropped (no live client); S2 early sentence rule; keep-warm pings only a resident front; S3 prewarm loads only the saved selection, covers `answer_routing.py:206`, exposes `cancel_prewarm`, and needs 0228-S2 for the idle-unload row; target start point and budget defined; S5 busy path reuses the timeout tail.
**Astra boundary:** persona, WebGL and presence internals are out of scope. Live UI is touched only add-alongside, with the reasoning pass below.

This PR is **specs-only** (plus evidence assets). No application code.

---

## 1. Measured breakdown (read this first)

Nobody can run Taco's PC from here. Every number below names its source. **VRPC** is Taco's PC (RFC-0215: "the owner usually works over RDP on VRPC"); VRPC numbers come from the #648/#649 PR bodies. **Box** numbers were measured on 2026-10-20 on the shared agent VM (8 vCPU Xeon, no GPU, other agents running, loadavg 3–37), with the backend at `development` `11b264a` (before #648/#649) and engines stubbed where stated. Code citations in §1.1 and the "After #648/#649" column are re-traced on `3007696`. Raw data and scripts: [`assets/0230-box-timings.json`](assets/0230-box-timings.json), [`assets/0230-turn-overhead-harness.py`](assets/0230-turn-overhead-harness.py), [`assets/0230-voice-bench.py`](assets/0230-voice-bench.py). Box numbers show code-path cost and orders of magnitude only. They are never the PC figure.

### 1.1 The desktop path today

HUD typed turn: `HudChat.tsx` `POST /api/tasks` → `AgentRuntime.create_task` (`agent/loop.py:479-559`, awaits `evaluate_request_route` at `:505`, two SQLite commits) → `_run` → `_run_conversation` (`:1243`) → `generate_front_reply` (`:1434`) → `_speak_front_reply` publishes `chat_tts` → the browser (`tts/useTaskSpeech.ts`) `POST /api/voice/speak` → full WAV → play.
HUD voice turn: `useLocalVoiceListen.ts` records the whole clip, uploads it to `POST /api/voice/listen` (`api/voice.py:82-102`) → `transcribe_audio` → `create_task` → same as typed.

### 1.2 Stage table

| # | Stage | development `11b264a` | After #648/#649 | Source | PC figure |
|---|---|---|---|---|---|
| 1 | STT model load | `WhisperModel(...)` is constructed on **every** utterance (`workers/voice.py:402`). Box: **0.29–0.37 s** per call (faster-whisper base, the bootstrap default, `installer/windows/bootstrap.ps1:630-634`) | unchanged | box | **not measured** → S0 |
| 2 | STT transcribe | runs **synchronously on the event loop** (`workers/voice.py:372-373`, plus the synchronous `voice_status()` call at `:355`), so every API call, the HUD health probe and other turns stall meanwhile. Box: **0.95–1.13 s** for a 3.8 s clip | unchanged | box | **not measured** → S0 |
| 3 | Intake (`POST /api/tasks` returns) | box: **6–22 ms** warm, **48–56 ms** first turn in a process | unchanged | box (stub engines) | S0 |
| 4 | Reflex lane (Jev/Laya, `decide_owner_turn`) | box, rules tier, Laya off: p50 **3.5 ms**, p95 **4.1–5.6 ms**, max **5.7–34 ms**, first call **7–9 ms** (n=300). Laya on VRPC: first probe **~1.3 s** (cold), which the 50 ms `wait_for` (`decision/owner_turn.py:568-595`, `wait_for` at `:580`) turns into a deadline fallback while the thread keeps running | `basic_qa` shape added (#649) | box; VRPC (#649 body) | S0 |
| 5 | Front model ready | front llama-server starts at boot (`main.py:368-374`), warmup on `11b264a` sent one user-only `"Hi"`, which did **not** warm the real prefix | fixed by #649: `_warmup` now sends the real `small_context_envelope("Hi", action_hint="final_basic")` prefix (`inference/front_runtime.py:585-602`) | code; #649 | S0 (cold-start mark) |
| 6 | Front request | before #649 (`11b264a`) every front request returned **HTTP 500**: `small_context_envelope` sent two system messages and the shipped Qwen template rejects a second one | **fixed on development by #649 (`ee786dc`, commit `bd873c6`)**: one leading system block (`agent/front_responder.py:701-708`, comment at `:701-702`), history filtered to user/assistant (`:712-714`); existing assertion `tests/test_rfc0224_task_workflow.py:151`; S2 adds `test_front_envelope_has_single_leading_system_message` over every front action. Not re-measured live on VRPC since; the figures that follow are #649's. VRPC 2B CPU: **0.935 s** cold prompt (prompt eval 600 ms for 329 tokens) / **0.263 s** cached prefix; 0.8B **0.555 / 0.356 s**; `generate_front_reply` against the resident 2B: **1.078 s**, first text **750 ms** | #649 body (VRPC benchmark) | VRPC numbers exist; end-to-end not measured |
| 7 | Front output → speech | the whole front reply is buffered (JSON payload, `front_responder.py:856-878`) before TTS is enqueued | unchanged | code | S0 |
| 8 | Ack hold | `ack_continue`/`handoff_notice` held **1.2 s** (`ACK_HOLD_SECONDS`, `front_responder.py:37`) by design. Box, task prompt: first `chat_tts` at **1217–1229 ms** | "What is RAM?" becomes `basic_qa` → `final_basic`, no hold | box; code | S0 |
| 9 | Worker cold load in the turn | the turn awaits `MANAGER.load` when nothing is loaded (`loop.py:2494-2498`, `:1369-1370`; also `persona/owner_chat.py:703-712`, a path with no live client, see S0). VRPC: selected model restored in **4.888 s** (frozen backend healthy at 4.356 s) | #648 restores the saved model at startup without waiting for discovery | #648 body (VRPC) | per-turn **not measured** → S0 |
| 10 | Router escalation | `prepare_answer_route` can hot-swap mid-turn with `MANAGER.load(..., force=True)` (`inference/model_escalation.py:165`); the 120 s restore reloads the 9B later (`:80-87`) | RFC-0228 S2 replaces the restore with `NINE_B_REWARM` | code | **not measured** → S0 |
| 11 | Worker first token | unknown: LM Studio 9B on `127.0.0.1:1234` (Taco) or ANZU llama-server | — | — | **not measured** → S0 |
| 12 | TTS synthesis | Kokoro runs on **CPU** (`tts/kokoro_adapter.py:137`). `/api/voice/speak` returns a full WAV per chunk (`api/voice.py:122-146`, `tts/chatTtsPlayer.ts:58-67`). If Kokoro is not verified yet, the first speak runs a full verify synthesis inline (`tts/synthesize.py:253-257`). Box: import **3.9–4.0 s** + model/pipeline **1.7 s** (covered by warm start); "Right away." **0.28–0.85 s**; a 57-char sentence **0.52–2.97 s** | unchanged | box | **not measured** → S0 |
| 13 | "First audio" metric | `front_first_audio_ms` is stamped at TTS **enqueue** (`agent/loop.py:1083`, `:1099`; `persona/owner_chat.py:603` on the clientless path), not at playback, so today's diagnostics cannot show the audible time | — | code | S0 fixes |
| 14 | Code path to first `chat_tts` (instant fake engines) | box: **23–33 ms** warm, **121–136 ms** first turn | — | box | — |
| 15 | Backend startup | box: `import app.main` **1.8–3.7 s**; spawn → `/api/health` 200 **2.4 s**; Laya `restore_on_startup()` runs synchronously on the startup path (`main.py:228-230`) | #648 moves several startup steps off the loop | box; code | not on the turn path |

Other VRPC figures on record: installed chat with the front lane on **3.927 s**, later **1.661 s** (#648 body; the PR does not say which stage that timer covers). Status reads after #648: health median 24.66 ms / P95 305 ms, model median 61 ms / P95 675 ms.

**RFC-0224's attribution** ("the owner observed a 21-second model-status read") is recorded here as an **unmeasured hypothesis**. #649's non-waiting status read removes that stall class, but nobody has shown that the status read is what Taco hears as a 21 s first response.

**What the evidence says.** The ANZU code path costs tens of milliseconds, and the reflex lane stays far inside 50 ms with rules. The known multi-second terms are: the dead front before #649 (#6, now fixed in code), a cold or escalated worker load inside the turn (#9, #10), CPU STT on the event loop with a per-call model load (#1, #2), CPU Kokoro synthesizing a whole chunk before playback (#12), and the 1.2 s hold whenever the front only acks (#8). The sum of the measured terms does not reach 21 s on its own, so the PC split is unknown until S0 lands. **S0 is first and measures before and after.**

## 2. Target

**Hard target (owner-visible, measured by S0 on VRPC):** from end of owner input (Enter, or mic release) to **first audible word ≤ 1.5 s at p50 and ≤ 2.0 s at p95** for a typed turn with the warm 2B front, over 20 turns of `scripts/anzu-latency-repro.ps1`. Voice turns add STT: **≤ 2.5 s p50** from mic release for clips ≤ 5 s. The reflex lane stays **≤ 50 ms on every turn** (Taco's mandate), and S0 records `decide_ms` on every turn.

**Start points (normative):**
- **First turn after boot** counts from the moment `/api/health` answers 200 **and** the front reports `decision.mode == "resident"` (`front_runtime.py`). The 2B CPU load itself is boot time, not turn time, and S0 reports it separately (`front_ready` mark, `front_cold`). A turn sent before that moment is reported as `front_cold = true` and is excluded from the p50/p95, with its count shown.
- **First turn after a worker idle unload** is measured once RFC-0228 S2 (which creates the idle unload) has landed; until then that row reads "measured after 0228-S2" (S3).
- The worker (LM Studio 9B on `127.0.0.1:1234`, or the 27B at ~12 GB) is off the first-word path under Decision 1, so its load time never counts against the target.

**Budget for the 1.5 s:** reflex ≤ 50 ms + front first sentence ≤ 800 ms + Kokoro first sentence ≤ 450 ms + transport and playback start ≤ 150 ms + slack 50 ms.
- **Front first sentence ≤ 800 ms** is anchored on #649's VRPC figure ("first text **750 ms**" against the resident 2B, row 6). The model emits the JSON prefix `{"action":"…","text":"` (≈ 10 tokens) before any speakable text, so the budget is **≤ 10 prefix tokens + ≤ 16 tokens of first sentence**; S2 caps the first streamed sentence at 16 tokens (longer sentences are split at the first comma or clause boundary). S0 records `front_first_token` and `front_first_sentence`, so the VRPC repro shows whether the 800 ms holds. No new number is assumed here.
- **CPU contention:** while the first sentence streams, Kokoro synthesizes it and the 2B front keeps generating on the same CPU. S4 caps Kokoro (`torch.set_num_threads`) at half the physical cores, and S2 caps the front server's `--threads` (S2 adds a per-launch `threads` keyword to `build_args`, `inference/backends.py:361`, `:379-408`) at the other half, so the two never oversubscribe. Whisper runs between turns, not during this window.

**Why this number (north star §4, §6):** a person hears a pause of more than about a second as a stall. 1.5 s is the longest gap that still reads as "ANZU heard me". It is reachable with the shipped 2B on CPU (#649's VRPC 263 ms cached-prefix front), and it does not ask for a bigger GPU or a cloud call.

## 3. Decisions

1. **The first audible word always comes from the resident front lane, never from a worker load.** The worker answers after; RFC-0117's merge rules are unchanged.
2. **When the turn knows the worker must load** (not loaded, idle-unloaded by RFC-0228, or an escalation is decided), the ack hold is skipped. ANZU speaks the front ack at once, because an answer cannot beat 1.2 s. The hold stays for every other case (RFC-0117/0127 2026-10-08 amendments).
3. **2B CPU stays the default** (Taco 2026-10-08, #550). The 4B (GPU-fit gated) and the #649 0.8B stay options. The remote front node keeps its local fallback. The front lane is never idle-unloaded: RFC-0228 already exempts `front_responder.resident`.
4. **The worker is reloaded on owner activity, not on a timer, and only to the saved selection.** Mic press and the first keystroke in the composer send a prewarm; it goes through RFC-0225 `prepare_engine_for` (single-flight). It loads only `load_settings().inference` (the owner's saved selection), never an escalation target or a tier-3+ profile such as `anzu-coder-27b`, and never persists anything (RFC-0228: "Update never auto-switches the model"). It respects RFC-0228's idle unload, its `NINE_B_REWARM` coordinator (never a second timer) and LM Studio on `127.0.0.1:1234`. No keep-alive ping for the worker.
5. **The front lane is kept warm, and only the front.** One cached-prefix ping after 10 min of front idleness, sent **only** to `FRONT_RUNTIME.provider(app)` when `decision.mode == "resident"` and the placement is local. It never uses `front_provider()`'s `MANAGER.provider` fallback (`front_responder.py:721-733`), so it never touches the 9B and never resets the LM Studio TTL or RFC-0228 S2's idle timer. A remote front is skipped. The ping uses only the front's own process: CPU for the 2B default, the GPU only when the owner selected the GPU 4B option.
6. **STT is resident and off the loop.** One Whisper model is loaded at startup and reused. Transcription runs in a worker thread.
7. **TTS speaks the first sentence first.** The front's first sentence is enqueued as soon as it is complete in the stream, and the browser player synthesizes the first sentence of any chunk as its own request. Kokoro is verified inline until RFC-0226 S1 (background re-verify) and S2 (visible fallback) land; after that it is never verified inside an owner turn, and there is never a silent fallback.
8. **Reflex lane:** a dedicated single-thread executor for `decide()`, so a slow Laya call or a busy default pool cannot delay the next turn. A busy executor reuses the existing timeout tail. Laya warms off the loop through #648's `_start_optional_step`.
9. **#648/#649 are reused, never re-ported.** Both have landed; S2 and S5 build on the landed hunks.

## 4. Relationship to #648 / #649 (both landed)

| Piece | Where on `bd2558b` | This RFC |
|---|---|---|
| Single leading system envelope (the HTTP 500 fix), history filter | #649 `bd873c6`: `front_responder.py:691-718` (one system message at `:708`), test `tests/test_rfc0224_task_workflow.py:151` | S2 builds on it and adds `test_front_envelope_has_single_leading_system_message` (every front action, with and without `self_status`) so the 500 cannot return |
| Real-prefix front warmup | #649: `front_runtime.py:585-602` | S2 keep-warm reuses `_warmup`'s envelope; no duplicate |
| `basic_qa` reply shape | #649: `decision/owner_turn.py:43` | S5 keeps it unchanged |
| 0.8B front option | #649: `inference/profiles.py` | stays an option (Decision 3) |
| Non-waiting status read, `model_details_cache`, diagnostics off the request thread | #649 (RFC-0225 S1 reuses) | not touched; S0 stays out of `api/diagnostics.py` |
| Startup restore of the saved model, `_start_optional_step`, `front_runtime` decide in a thread, Kokoro `_warmup_guarded` | #648: `main.py:140` (`_start_optional_step`, used at `:226`, `:286`, `:299`, `:392`) | S5 moves the Laya restore (`main.py:228-230`) onto `_start_optional_step`; nothing else in startup |
| `task_workflow` large-task stages | #649 | out of scope (RFC-0231 builds on it) |

S2 and S5's "Depends #649" is satisfied.

## 5. Live-UI add-alongside reasoning pass (2026-10-14 standing order)

| Live behaviour | Preserved? | Added alongside |
|---|---|---|
| HUD composer, mic button, transcript bubbles (`HudChat.tsx`, `OwnerChatTranscript.tsx`) | **Yes**, no visual change in the bubbles | S0: one `turn_latency` task event. It is an ordinary work event, so it shows only in the collapsed Show work list (`filterWorkEvents`, `chat/ownerChatView.ts:76`), as a plain line ("Heard you 0.4 s · first word 1.2 s · …"), never raw JSON and never as a bubble. S3: a prewarm call on mic press / first keystroke, with no visible element |
| Chat speech playback order, barge-in (`stopChatTts`), prefetch (`chatTtsPlayer.ts:69-88`) | **Yes** | S0: one playback-started mark per turn. S4: a multi-sentence item is queued as first sentence + remainder; `prefetchNext` fetches the remainder while the first plays; `stopChatTts` clears both |
| `useTaskSpeech` prefix handling ("Speak reply", `useTaskSpeech.ts:48-50`) | **Yes** | S0: passes `turnId` (the task id) in `SpeakOpts` |
| Ack-only-when-late, no double ack | **Yes** | S3: the hold is skipped only when a load is known to be needed; still at most one ack |
| Persona, presence, WebGL | untouched (Astra) | — |

Each implement PR carries a "Preserved live behaviour" section with a test or screenshot per row.

## 6. Stub rule

No stubs, soft-fails or orphans. A span that nothing records, a mark endpoint no client calls, a prewarm nobody triggers, an edit on a path no client calls, or a timing field that measures enqueue but is labelled "audio" fails review.

---

## 7. Slices (one developer each, fast off)

Order: **S0 first.** Then S1 ∥ S5, S2, then S3 (after S0, RFC-0225 S3; its idle-unload row after RFC-0228 S2), then S4 (after RFC-0226 S1 and S2; the only slice that waits on the #652 chain). On `main.py`, RFC-0225's slices go first (CoS): 0225-S1 → S2 → S3 → 0230-S0 → 0230-S5; S0 and S5 are developed in parallel and merge their one-line hunks after 0225-S3 with a merge commit.

### S0 — Per-turn latency trace, owner-visible, with a one-command PC repro

**Model:** Grok 4.6 · **Lane:** D1 · **Depends:** none in code (`main.py` merge order after 0225-S3, one `include_router` line)

A permanent product feature, not debug scaffolding. One `TurnTrace` per owner turn, keyed by task id, records marks:
`input_end` (client stamp, sent as `X-ANZU-Input-End` with the request), `request_received`, `stt_model_ready`, `stt_done`, `decide_done` (+ `decide_ms`, `decide_source`: rules / jev / laya / deadline_fallback), `front_ready` (+ `front_cold: bool`, true when the front server was started or reloaded for this turn), `front_first_token`, `front_first_sentence`, `ack_hold_end` (when held), `worker_load_start` / `worker_load_done` (+ `reason`: cold / idle_reload / escalation), `worker_first_token`, `tts_enqueued`, `tts_synth_done` (from `/api/voice/speak`, correlated by `X-ANZU-Turn`), `first_audio` (client playback start).

**Clock domains (normative).** `input_end` and `first_audio` are both **client** marks from the same page clock (`performance.timeOrigin + performance.now()` in the HUD tab), so the headline is `first_audio − input_end`, computed on client values only. Every server mark is `time.monotonic()` relative to the turn's `request_received`. The two domains are never subtracted from each other; the report shows the headline (client) and the per-stage breakdown (server) side by side.

**`first_audio` is playback start.** `chatTtsPlayer.ts` posts it once per turn from the `HTMLAudioElement` `playing` event of the turn's first item (not when the item is queued, fetched or `play()` is called).

**Trace finish (normative).** A trace finishes when `first_audio` is received for its turn, or 10 s after `tts_enqueued` without it. On finish, one persisted task event `turn_latency` (title "Response timing", detail = `summary_line`) is published. When the timeout fired, the line says "first word not reported" instead of a first-word time. `first_audio` arriving after the timeout is recorded in the JSONL but does not rewrite the event.

| Path | Why |
|---|---|
| `backend/app/observability/turn_trace.py` (new) | `TurnTrace`, `mark(turn_id, name, **meta)`, finish rule above, ring buffer of the last 50 turns persisted to `data_dir()/logs/turn-latency.jsonl`; `summary_line(trace)` for the owner-facing line |
| `backend/app/agent/loop.py` | marks in `create_task` (`request_received`, `decide_done`), `_run_conversation`, `_run_managed_front_lane`, `_speak_front_reply`, both `MANAGER.load` sites (`:1369-1370`, `:2494-2498`); `turn_latency` event on finish. First 0230 owner in the chain (after #649 and 0218-S3b) |
| `backend/app/api/voice.py` | `listen` (`:82-102`): `request_received`, `stt_model_ready`, `stt_done`; `speak` (`:122-146`): `tts_synth_done` when `X-ANZU-Turn` is present (existing `Server-Timing` kept). Chain: 0230-S0 → 0226-S1 → 0230-S1 (§9) |
| `backend/app/api/turn_latency.py` (new) | `GET /api/turn-latency?limit=20` (traces + p50/p95 per stage), `POST /api/turn-latency/{turn_id}/marks` (client marks `input_end`, `first_audio`; only these two names accepted) |
| `backend/app/main.py` | one `include_router` line (after 0225-S3, per CoS) |
| `frontend/src/tts/chatTtsPlayer.ts` | `SpeakOpts.turnId?: string`; `X-ANZU-Turn` header on `/api/voice/speak`; `first_audio` POST once per turn on the first item's `playing` event. First owner: 0230-S0 → S4 |
| `frontend/src/tts/useTaskSpeech.ts` | passes `turnId: taskId` into the `queueChatSpeech` calls at `:51` and `:93`; nothing else changes |
| `frontend/src/api.ts` | stamp `X-ANZU-Input-End` on `POST /api/tasks`, `/continue` and `/api/voice/listen`. First owner: 0230-S0 → 0218-S3 → 0227 selection helpers → 0231-S6 |
| `scripts/latency_repro.py` (new), `scripts/anzu-latency-repro.ps1` (new) | see *Repro* below |
| `tests/fixtures/voice/rfc0230_hello.wav`, `tests/fixtures/voice/rfc0230_question.wav` (new) + `tests/fixtures/voice/README.md` | see *Repro* below |
| `tests/test_rfc0230_turn_trace.py` (new); `frontend/turn-latency-marks.test.mjs` (new); `frontend/package.json` (`test:turn-latency-marks`, one line); `.github/workflows/pr-tests.yml` | see below |

`persona/owner_chat.py` is **not** edited: `/api/owner/chat/messages` and `/messages/stream` have no caller in `frontend/src`, `android/` or `extensions/` (only the conversation reads are used, `App.tsx:256`, `OwnerChat.tsx:28`), so marks there would be orphaned under §6.

**Repro (normative).** `powershell -File scripts\anzu-latency-repro.ps1` on VRPC runs `python scripts\latency_repro.py`, which:
- **drives the real HUD** in Chromium through Playwright (the same pattern as `scripts/verify-reverse-engineering.py:158-177`) against `http://127.0.0.1:<port>/`, so speech goes through `useTaskSpeech` → `queueChatSpeech` → real playback, and `first_audio` is the browser's own `playing` mark;
- **authenticates as the HUD does:** reads the owner key locally from `data_dir()/private_key.sec` (`auth.py:16-27`), sets it as `localStorage["jarvis_private_key"]` in the Playwright page before load (the key `api.ts:10` reads), and sends it as `X-Jarvis-Key` (`auth.py:69-71`) for its own `GET /api/turn-latency` calls. The key is never printed or written to the report;
- runs 20 typed turns (5 social, 10 `basic_qa`, 5 task-shaped) typed into the composer, and 5 voice turns by launching Chromium with `--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<wav>` and pressing the mic button, once cold (after `stop-jarvis.ps1` / start, waiting for the §2 boot start point) and once warm;
- prints the §1.2 table as Markdown from `GET /api/turn-latency` and writes `data/logs/turn-latency-report.md`;
- accepts extra case files (`--cases <file.json>`); RFC-0231-S4 appends three large-turn cases that way.

**Test WAVs:** `tests/fixtures/voice/rfc0230_hello.wav` ("Hello ANZU, are you there?") and `tests/fixtures/voice/rfc0230_question.wav` ("What is RAM and how much do I have?"), 16 kHz mono, 2-4 s. They are synthesized once with ANZU's own Kokoro (Apache-2.0 weights, voice `af_heart`) by the committed `scripts/make_rfc0230_wavs.py`, so source and licence are recorded in `tests/fixtures/voice/README.md` and no third-party recording is used.

Acceptance (CI: `pytest` job, step "RFC-0230 latency contract tests", then "Run full backend suite" at `pr-tests.yml:94`):
- [ ] `test_turn_trace_marks_typed_turn_in_order`: stub front + worker; `POST /api/tasks` → marks `request_received < decide_done < front_first_token < tts_enqueued`; after a posted `first_audio` one persisted `turn_latency` event whose detail is the plain summary line (asserted to contain no `{`).
- [ ] `test_turn_trace_finishes_on_first_audio_or_10s_timeout`: fake clock; no `first_audio` → event after 10 s with "first word not reported"; a late `first_audio` does not rewrite it.
- [ ] `test_turn_trace_records_worker_cold_load`: worker not loaded → `worker_load_start/done` with `reason="cold"`.
- [ ] `test_turn_trace_records_front_cold_flag`: front server started inside the turn → `front_cold == True`, excluded from p50/p95 and counted.
- [ ] `test_turn_trace_decide_source_and_ms`: deadline fallback → `decide_source == "deadline_fallback"`, `decide_ms` present.
- [ ] `test_voice_listen_records_stt_marks`: fake STT backend → `stt_model_ready`, `stt_done`.
- [ ] `test_client_marks_accept_only_known_names`: `first_audio` accepted; any other name → 422.
- [ ] `test_turn_latency_endpoint_percentiles`: 20 seeded traces → p50/p95 per stage match a hand computation; client and server domains never mixed.
- [ ] `test_first_audio_field_is_client_mark_only`: no server code writes `first_audio`.
- [ ] `test_repro_reads_key_locally_and_never_logs_it`: `latency_repro.py` with a temp `private_key.sec` → the key is in the page's localStorage and request headers, and absent from stdout and the report.
- [ ] `frontend/turn-latency-marks.test.mjs`: `queueChatSpeech` with `turnId` sends `X-ANZU-Turn` and posts `first_audio` exactly once per turn, on the fake audio element's `playing` event (not on queue or `play()`), even with two queued chunks; and `filterWorkEvents` (`ownerChatView.ts:76`) keeps a `turn_latency` event in the work list while the transcript bubble list does not contain it.
- [ ] CI: `pr-tests.yml` `pytest` job gains `- name: RFC-0230 latency contract tests` / `run: python -m pytest -q tests/test_rfc0230_*.py` (before "Run full backend suite"); `frontend-build` gains `- name: Turn latency mark tests (RFC-0230 S0)` / `run: npm run test:turn-latency-marks`. Append-only; S1-S5 add their backend test files to the same glob.
- [ ] **PC acceptance:** Taco runs the repro on VRPC before S1–S5 land; the report is attached to the S0 PR, and its numbers replace "not measured" in §1.2 by an amendment to this RFC.

### S1 — STT resident and off the event loop

**Model:** Grok 4.5 · **Lane:** D2 · **Depends:** S0. On `workers/voice.py` S1 goes **first** (CoS ruling 2026-10-20, accepting D1: STT resident and off the loop is not held behind the #652 chain); its hunks (model cache, `to_thread`) do not overlap 0225-S2's registry wrappers or 0226-S2's `voice_status()` fields

| Path | Why |
|---|---|
| `backend/app/workers/voice.py` | `_whisper_model()` cache: one `WhisperModel` per (path, device, compute type) behind a lock (today constructed per call, `:402`); `transcribe_audio` runs the faster-whisper / openai-whisper calls (`:372-373`) and `voice_status()` (`:355`) via `asyncio.to_thread`; `warm_stt()` loads the model and transcribes 0.5 s of silence. First owner in the chain 0230-S1 → 0225-S2 → 0226-S2 (CoS ruling; #652 is being updated to match) |
| `backend/app/voice_warm.py` (new) | `schedule_stt_warm_start()` fire-and-forget at startup, result in `last_stt_warm_report()` and in S0's `stt_model_ready` |
| `backend/app/api/voice.py` | `GET /api/voice/status` adds `stt_warm` (after 0230-S0 and 0226-S1) |
| `tests/test_rfc0230_stt_resident.py` (new) | below |

- [ ] `test_whisper_model_loaded_once_across_utterances`: three transcriptions → one model construction.
- [ ] `test_transcribe_does_not_block_event_loop`: fake transcribe sleeps 1 s → a concurrent `/api/health` answers in < 100 ms.
- [ ] `test_stt_warm_start_reports_ready_and_failure`: warm failure is recorded and shown in `/api/voice/status`, never swallowed.
- [ ] VRPC (S0 repro): `stt_model_ready` ≈ 0 ms on warm turns; voice p50 from mic release to first audio ≤ 2.5 s.

### S2 — Front lane: streamed first sentence, kept warm, cold-start visible

**Model:** Grok 4.6 · **Lane:** D1 · **Depends:** S0 (#649 has landed; its envelope, prefix warmup, `basic_qa` and 0.8B are on development)

| Path | Why |
|---|---|
| `backend/app/agent/front_responder.py` | Incremental parse of the front payload's `text` field while streaming (`:856-878` buffers it today). **Early-stream rule (normative):** the first complete sentence (≤ 16 tokens, §2) is streamed only when the already-parsed `action` is speakable and the sentence passes `enforce_front_safety` and `is_safe_front_speech` (`:355`) **on its own**. Once streamed it stands: it is never cancelled, because the browser may already be playing it. The full-reply check still runs at the end and governs only the remainder; a rejected remainder is not spoken. First owner after #649 |
| `backend/app/inference/backends.py` | `build_args` (`:361`) gains a keyword `threads: int | None = None` (per launch), used instead of `inference.threads or hardware.cpu_cores` (`:379`) when given; the worker launch passes nothing, so its behaviour is unchanged. First owner: 0230-S2 → 0225-S2 (registry) |
| `backend/app/inference/front_runtime.py` | Keep-warm per Decision 5: one cached-prefix request (the `_warmup` envelope, `:585-602`) after 10 min of front idleness, only to `FRONT_RUNTIME.provider(app)` with `decision.mode == "resident"` and local placement, skipped while a turn runs and for a remote front; never `front_provider()`'s `MANAGER.provider` fallback. Front `--threads` capped at half the physical cores (§2), passed as `build_args(..., threads=…)` from the front launch. Health watchdog: a dead front server is restarted off the turn path and the next turn's S0 trace has `front_cold = true`; remote placement fallback to local unchanged (#550) |
| `backend/app/agent/loop.py` | wire `on_first_sentence` to `_speak_front_reply` (`:1045`) (second 0230 owner after S0) |
| `tests/test_rfc0230_front_stream.py` (new) | below |

- [ ] `test_front_envelope_has_single_leading_system_message` (extends the landed `test_front_envelope_has_one_leading_system_message`, `tests/test_rfc0224_task_workflow.py:151`, which stays unchanged, from `final_basic` only to every action): `small_context_envelope` for `final_basic`, `ack_continue` and `handoff_notice`, each with and without `self_status` and with mixed-role history → exactly one `system` message, at index 0 (pins the HTTP 500 fix from #649).
- [ ] `test_front_first_sentence_enqueued_before_reply_completes`: stub streams 40 tokens at 20 ms → `tts_enqueued` before the stream ends.
- [ ] `test_unsafe_first_sentence_never_streamed`: a first sentence that fails the safety checks on its own is not enqueued early.
- [ ] `test_unsafe_remainder_not_spoken_first_sentence_stands`: safe first sentence, unsafe full reply → exactly the first sentence is spoken, no remainder, no cancel event.
- [ ] `test_front_keep_warm_ping_after_idle`: fake clock 10 min idle → exactly one cached-prefix request to the resident front; none during an active turn; none for a remote front.
- [ ] `test_keep_warm_never_pings_worker_provider`: no resident front (`FRONT_RUNTIME.provider()` is `None`) and `MANAGER.provider` is the LM Studio 9B → zero requests to the worker after any idle time; RFC-0228 S2's idle timer and the LM Studio TTL are not reset.
- [ ] `test_front_threads_capped_half_physical`: 16 physical cores → front `--threads 8`; the worker's `build_args` without `threads` still uses `inference.threads or hardware.cpu_cores`.
- [ ] `test_dead_front_restarted_off_turn_path`: health fails → restart scheduled; the turn falls back exactly as today.
- [ ] `test_front_default_stays_2b_cpu`: `config/default.json` profile `front_2b`, device `auto` → CPU, `-ngl 0`; 4B and 0.8B still selectable.

### S3 — Worker load never sits between input and first word

**Model:** Grok 4.6 · **Lane:** D1 · **Depends:** S0, RFC-0225 S3 (`engine_coexistence.prepare_engine_for`; read-only import, that file is not edited here). The lease skip uses a registration hook so 0230 never imports 0231: 0230-S3 ships `turn_prewarm.register_lease_probe(fn: Callable[[], object | None])` (nothing registered means no lease), and 0231-S4 registers `large_prompt.active_target` when its module is imported at startup. The VRPC "first turn after an idle unload" row also depends on RFC-0228 S2 (which creates the idle unload) and is measured once it lands.

| Path | Why |
|---|---|
| `backend/app/inference/turn_prewarm.py` (new) | `prewarm_worker(reason, *, turn_id=None) -> PrewarmHandle`: when the **saved** selection (`load_settings().inference`) is not loaded or is idle-unloaded, calls `prepare_engine_for(<saved selection>)` (single-flight; LM Studio `127.0.0.1:1234` reload/revive, ANZU llama-server load). It never loads an escalation target or a tier-3+ profile (e.g. `anzu-coder-27b`), never calls `activate_runtime_profile` or `save_settings` (both persist, `hotswap.py:192`, `:232`), never schedules a timer and never re-warms a 9B the VRAM gate unloaded (RFC-0228 `NINE_B_REWARM` keeps that). `cancel_prewarm(turn_id)` cancels a handle that has not yet entered `prepare_engine_for`; one already inside it finishes under the single-flight. `load_needed(turn)` (not loaded, idle-unloaded, or an escalation is decided) lives here. **While an RFC-0231 large-prompt lease holds a target** (the registered lease probe, i.e. 0231-S4's `large_prompt.active_target()`, returns a target), the saved selection being unloaded is by design: `prewarm_worker` and `load_needed` treat the worker as loaded and skip, so a concurrent chat turn never issues a 9B `prepare_engine_for` against the held lease, and the prewarm never touches the 27B |
| `backend/app/api/turn_latency.py` | `POST /api/turn-latency/prewarm` (second owner after S0) |
| `backend/app/agent/loop.py` | in `create_task` (`:479-559`), start `prewarm_worker("turn", turn_id=task_id)` **before** the reflex decision (`:505`); in `_run_conversation` / `_run` skip the ack hold when `load_needed(turn)` so the front ack is spoken at once (third 0230 owner after S0, S2). The prewarm never loads for a turn that RFC-0232 S3/S5 dispatch to RE before the model: their dispatch calls `cancel_prewarm(turn_id)`, so an FFS/APK ingest never triggers a worker load. RFC-0231-S4 calls it on a large verdict the same way |
| `backend/app/inference/answer_routing.py` | `prepare_answer_route` awaits `execute_visible_model_switch` (`:206`) only after the turn's front line is enqueued (S0 `tts_enqueued` mark present) or immediately when the front lane is off. Only owner (no other open RFC edits it) |
| `frontend/src/chat/useLocalVoiceListen.ts` | on mic press, fire-and-forget `POST /api/turn-latency/prewarm` |
| `frontend/src/hud/HudChat.tsx` | on the first keystroke of an empty composer (once per 30 s), the same prewarm call; no visible change |
| `tests/test_rfc0230_worker_prewarm.py` (new); `frontend/turn-prewarm.test.mjs` (new); `frontend/package.json` (`test:turn-prewarm`); `.github/workflows/pr-tests.yml` (`- name: Turn prewarm tests (RFC-0230 S3)` / `run: npm run test:turn-prewarm`) | below |

`persona/owner_chat.py` is not edited (no live client, S0).

- [ ] `test_cold_worker_turn_speaks_front_before_load_completes`: worker load faked at 5 s → `tts_enqueued` < 300 ms (stub front), `worker_load_done` ≈ 5 s.
- [ ] `test_prewarm_loads_saved_selection_only_and_never_persists`: saved LM Studio 9B; an escalation decided to `expert` and an enabled `anzu-coder-27b` → the prewarm targets only the 9B; `activate_runtime_profile` and `save_settings` are never called; `settings.json` is byte-identical.
- [ ] `test_idle_unloaded_worker_reloads_via_prepare_engine_for`: `idle_unloaded()` true → exactly one `prepare_engine_for` call across prewarm + turn.
- [ ] `test_prewarm_never_touches_gate_unloaded_9b`: `gate_unloaded()` set → no load call.
- [ ] `test_prewarm_skips_while_large_prompt_lease_held`: `large_prompt.active_target()` returns `anzu-coder-27b` and the saved 9B is not loaded → `prewarm_worker("turn")` makes zero `prepare_engine_for` calls, `load_needed` is false, and nothing loads or unloads the 27B; with the probe returning `None`, or none registered, the prewarm runs as before.
- [ ] `test_cancel_prewarm_before_prepare`: `cancel_prewarm` before the handle enters `prepare_engine_for` → no load call; after → the single-flight call completes once.
- [ ] `test_re_dispatched_turn_never_prewarms`: an RE pre-model dispatch cancels the prewarm → no worker load for that turn.
- [ ] `test_ack_hold_kept_when_worker_warm`: worker loaded → hold unchanged (RFC-0127 tests stay green).
- [ ] `test_escalation_switch_after_front_line`: escalation decided → `tts_enqueued` precedes `execute_visible_model_switch` (`answer_routing.py:206`) and its `MANAGER.load(force=True)`.
- [ ] `frontend/turn-prewarm.test.mjs`: mic press and first keystroke each send one prewarm; typing more within 30 s sends none.
- [ ] VRPC (S0 repro, after RFC-0228 S2): first turn after a 15-min idle unload → first audio ≤ 1.5 s, worker answer follows.

### S4 — TTS: first sentence first; inline verify removed after RFC-0226 S1/S2

**Model:** Grok 4.5 · **Lane:** D2 · **Depends:** S0, **RFC-0226 S1** ("Kokoro load root cause + reliable load, verify, retry": the `verifying` state and the background re-verify with backoff in `tts/kokoro_adapter.py`, plus warm start's `verify_kokoro_runtime_async()`) and **RFC-0226 S2** ("Fallback chain, real probes, `/api/voice/status` truth, `voice_fallback` signal, persona switch": `engines.fallback_chain_for_profile()` over `probe_fallback_engine()`, and the `voice_fallback` BUS event from `tts/persona_speech.py`). Hard dependency for the `synthesize.py` change, which does not merge before both. RFC-0226 names no function for the re-verify scheduler; S4 calls it through the adapter's re-verify entry that 0226-S1 ships

| Path | Why |
|---|---|
| `frontend/src/tts/chatTtsPlayer.ts` | `queueChatSpeech` (`:134`) splits a multi-sentence text into first sentence + remainder as **two queue items** (same `turnId`, same `onStart`/`onEnd` semantics across both); the existing `prefetchNext` (`:69-88`) fetches the remainder's audio while the first plays; `stopChatTts` clears both. This is where the desktop speaks from (`useTaskSpeech.ts:41-55` → `queueChatSpeech`). Second owner after S0 |
| `backend/app/tts/synthesize.py` | After 0226-S1/S2 land: `_synthesize_kokoro` no longer runs `verify_kokoro_runtime` inline (`:253-257`); not ready → `RuntimeError` at once, 0226-S2's `fallback_chain_for_profile()` moves to the next probed engine and publishes `voice_fallback` (visible), and 0226-S1's background re-verify with backoff (the one scheduler of verifies) runs. Until S4 merges, the inline verify is simply unchanged (no runtime branch on whether 0226 is present). Third owner in the chain 0225-S2 → 0226-S2 → 0230-S4 (§9) |
| `backend/app/tts/kokoro_adapter.py` | `torch.set_num_threads` capped at half the physical cores (`:137` area) so Kokoro, the 2B front and Whisper do not oversubscribe one CPU; the cap is recorded in `/api/voice/status`. Chain: 0226-S1 → 0230-S4 (§9) |
| `backend/app/persona/chat_delivery.py` | **not edited** (its queue is drained only by `GET /api/owner/chat/tts/pending`, which has no client) |
| `tests/test_rfc0230_tts_first_sentence.py` (new); `frontend/tts-first-sentence.test.mjs` (new); `frontend/package.json` (`test:tts-first-sentence`); `.github/workflows/pr-tests.yml` (`- name: TTS first sentence tests (RFC-0230 S4)` / `run: npm run test:tts-first-sentence`) | below |

- [ ] `frontend/tts-first-sentence.test.mjs`: `queueChatSpeech("One. Two. Three.")` → two `/api/voice/speak` requests, first "One.", then "Two. Three."; the second is fetched by `prefetchNext` while the first plays; no text lost or repeated; `stopChatTts` drops both; a one-sentence text stays one item.
- [ ] `test_kokoro_not_verified_never_blocks_turn` (after 0226-S1/S2): unverified Kokoro → speak falls through in < 50 ms (fake engines) to the next engine of 0226-S2's `fallback_chain_for_profile()` with one `voice_fallback` event, and exactly one background verify is scheduled, by 0226-S1's background re-verify in `kokoro_adapter.py`.
- [ ] `test_kokoro_thread_cap`: 16-core fake → 8 threads.
- [ ] VRPC (S0 repro): `tts_synth_done − tts_enqueued` p50 ≤ 450 ms for the first sentence.

### S5 — Reflex lane ≤ 50 ms on every turn

**Model:** Grok 4.5 · **Lane:** D2 · **Depends:** S0 (#649's `basic_qa` hunks have landed)

| Path | Why |
|---|---|
| `backend/app/decision/owner_turn.py` | `decide_owner_turn` runs `_decide_sync` on a dedicated `ThreadPoolExecutor(max_workers=1, thread_name_prefix="reflex")`. **Busy path (normative):** if the previous call still holds the executor (an abandoned Laya call after a timeout), the turn takes the **existing `TimeoutError` tail**: `_deadline_rules_result(reason="reflex executor busy")` → `_apply_floors` (`:296`) → `_with_deadline_persona`, audited as `deadline_fallback`. The turn **still submits its single `decide()`** to the executor (queued behind the abandoned call), so every turn has exactly one `decide()` (RFC-0206, and `decide_owner_turn`'s "never a skipped call"); the turn does not wait for it, and a result that arrives after the deadline is discarded and audited as late. It never starts a second `decide()`, and `resolve_persona_context` stays outside the window (`:563`). Floors that apply on the normal path (`:461`) and the deadline paths (`:600`, `:623`) — including RFC-0232 S2's RE floor and RFC-0231 S1's large-prompt floor — therefore apply on the busy path too. The 50 ms budget, audit and `persona_intent` behaviour are unchanged. Chain: #649 → 0218-S3b → 0230-S5 → 0232-S2 → 0231-S1 |
| `backend/app/main.py` | the synchronous Laya restore at `:228-230` becomes `_start_optional_step("laya_restore", lambda: asyncio.to_thread(laya_runtime.restore_on_startup))`, reusing #648's `_start_optional_step` (`:140`), as `presence` does at `:392`. `decision/laya/runtime.py` is not edited. Merges after 0225-S3 and 0230-S0 |
| `tests/test_rfc0230_reflex_budget.py` (new) | below |

- [ ] `test_decide_within_50ms_while_default_executor_saturated`: default pool filled with blocked jobs → `decide_owner_turn` returns in ≤ 50 ms (event-blocked stubs, no wall-clock sleeps).
- [ ] `test_abandoned_laya_call_does_not_delay_next_turn`: Laya stub blocked → turn 1 deadline fallback; turn 2 immediate rules fallback, not queued.
- [ ] `test_executor_busy_fallback_applies_floors_and_persona`: Laya blocked so turn 2 takes the busy path → `_apply_floors` ran (an explicit-action floor fixture gives `managed_task`), `persona_intent` comes from `_with_deadline_persona`, `decide_source == "deadline_fallback"`, and `decide()` was submitted exactly once per turn (turn 1: one call; turn 2: one call, queued, its late result discarded and not used for routing). **RFC-0232 S2 owns** adding the RE cases to `tests/test_rfc0230_reflex_budget.py` after 0230-S5 has landed (helper `planning.re_intent_match(prompt, *, allowed=None) -> ReIntent | None` and probe `planning.probe_dump_target`, #664; the probe reads the owner's allow-list from settings, never passes `None` to `store.admit_allowed_target`, and explicit wording skips only the dump-marker requirement, never the allow-list or the source veto). The case set is identical in #664 and here: (1) explicit `D:\cases\x\p1 is a full FFS of my Pixel, which accounts are on it?` with the probe faked as `plain` (admitted, exists, not source) → RE; (2) weak `D:\cases\x\ffs.zip what accounts are on it?` with the probe faked as `dump` → RE; (3) the same weak prompt with the probe faked as `absent` → not RE; (4) `C:\code\etl what does the extraction step do?` → not RE.
- [ ] `test_laya_restore_off_startup_path`: Laya warm faked at 3 s → `startup()` returns in < 1 s; the step name `laya_restore` is in `startup_health.report()`.
- [ ] VRPC (S0 repro): `decide_ms` ≤ 50 on 100 % of the 25 repro turns, with Laya enabled.

## 8. Ticket cards

| ID | Title | Model | Lane | Depends |
|---|---|---|---|---|
| 0230-S0 | Per-turn latency trace + PC repro | Grok 4.6 | D1 | — (`main.py` after 0225-S3) |
| 0230-S1 | STT resident, off the loop | Grok 4.5 | D2 | S0 (first on `workers/voice.py`) |
| 0230-S2 | Front streamed first sentence + keep-warm | Grok 4.6 | D1 | S0 |
| 0230-S3 | Worker load off the first-word path | Grok 4.6 | D1 | S0, 0225-S3 (idle row: 0228-S2) |
| 0230-S4 | TTS first sentence, inline verify after 0226 | Grok 4.5 | D2 | S0, **0226-S1**, **0226-S2** (hard; the only 0230 slice that waits on the #652 chain) |
| 0230-S5 | Reflex ≤ 50 ms every turn | Grok 4.5 | D2 | S0 |

All run with fast mode off.

## 9. Shared files and handoff order (CoS: 0230 → 0232 → 0231 on the turn files; RFC-0225 first on `main.py` and `synthesize.py`; 0230-S1 first on `workers/voice.py` and 0230-S2 first on `backends.py` (CoS); RFC-0226 before 0230-S4 on the voice files S4 shares)

| File | Order |
|---|---|
| `backend/app/agent/loop.py` | #649 (landed `ee786dc`) → 0218-S3b → 0230-S0 → 0230-S2 → 0230-S3 → 0232-S3 → 0232-S4 → 0232-S5 → 0231-S4 → 0231-S5. In `create_task`: 0230-S3's `prewarm_worker` and the route decision, then 0232's RE dispatch (S3 FFS, S5 APK; cancels the prewarm), then 0231's large branch |
| `backend/app/decision/owner_turn.py` | #649 (landed) → 0218-S3b (not landed) → 0230-S5 → 0232-S2 (RE floor in `_apply_floors`) → 0231-S1 |
| `backend/app/agent/front_responder.py`, `inference/front_runtime.py` | #648/#649 (landed) → 0230-S2 |
| `backend/app/inference/answer_routing.py` | 0230-S3 only |
| `backend/app/main.py` | 0225-S1 → 0225-S2 → 0225-S3 → 0230-S0 → 0230-S5 → 0231-S0 → 0231-S5 → #585 (draft; merges onto whatever has landed) |
| `backend/app/workers/voice.py` | 0230-S1 → 0225-S2 → 0226-S2 (CoS ruling 2026-10-20 accepting D1; #652 is being updated to match) |
| `backend/app/inference/backends.py` | 0230-S2 (per-launch `threads` on `build_args`, `:379`) → 0225-S2 (registry) |
| `backend/app/tts/synthesize.py` | 0225-S2 → 0226-S2 → 0230-S4 (RFC-0225 first, matching #652's RFC-0225 S2 table; S4 hard-depends on 0226-S2 and is the only 0230 slice that waits on the #652 chain) |
| `backend/app/tts/kokoro_adapter.py` | 0226-S1 (verifying state, background re-verify) → 0230-S4 (thread cap) |
| `backend/app/api/voice.py` | 0230-S0 → 0226-S1 (`POST /api/voice/kokoro/reload`) → 0230-S1 (`stt_warm`) |
| `backend/app/api/turn_latency.py` (new) | 0230-S0 → S3 |
| `frontend/src/api.ts` | 0230-S0 → 0218-S3 → 0227 (selection helpers) → 0231-S6 |
| `frontend/src/tts/chatTtsPlayer.ts` | 0230-S0 → 0230-S4 |
| `frontend/src/tts/useTaskSpeech.ts` | 0230-S0 only |
| `frontend/src/hud/HudChat.tsx` | 0230-S3 only (one effect; no JSX change) |
| `scripts/anzu-latency-repro.ps1`, `scripts/latency_repro.py` | 0230-S0 (creates) → 0231-S4 (append-only large cases) |
| `frontend/package.json`, `.github/workflows/pr-tests.yml` | **Append-only.** The Architect owns the workflow file. Each ticket appends its own `test:*` line and step and never edits another's; on a conflict it merges `development` with a merge commit and keeps both |

Not edited here: `persona/owner_chat.py`, `persona/chat_delivery.py`, `inference/manager.py`, `hotswap.py`, `lmstudio_server.py`, `engine_coexistence.py`, `rewarm.py`, `api/model.py`, `api/diagnostics.py`, `tts/warm_start.py`, `systems/self_check.py`, `decision/laya/runtime.py`, `config.py` (owned by 0225/0226/0228/#648/#649).

## 10. Files likely to overlap Astra's and Taco's unpushed PC speed fixes

Ask Taco to push these first. **No ticket waits on it**; whoever lands second merges by merge commit.

- `backend/app/agent/front_responder.py`, `backend/app/inference/front_runtime.py`, `backend/app/inference/profiles.py`, `config/default.json` (front envelope, warmup, front profile)
- `backend/app/agent/loop.py`, `backend/app/inference/answer_routing.py` (turn path, hold, escalation)
- `backend/app/decision/owner_turn.py`, `backend/app/decision/laya/runtime.py` (reflex, Laya warm)
- `backend/app/inference/manager.py`, `backend/app/inference/status_monitor.py`, `backend/app/api/model.py`, `backend/app/main.py` (status reads, startup, autoload)
- `backend/app/workers/voice.py`, `backend/app/tts/kokoro_adapter.py`, `backend/app/tts/synthesize.py`, `backend/app/tts/warm_start.py` (STT/TTS)
- `frontend/src/tts/chatTtsPlayer.ts`, `frontend/src/tts/useTaskSpeech.ts`, `frontend/src/hud/HudChat.tsx`, `frontend/src/chat/useLocalVoiceListen.ts` (playback, polling, mic)

## 11. Out of scope

- Persona, presence, WebGL (Astra).
- Streaming STT / voice activity detection (a later RFC once S0 shows the STT share on VRPC).
- Large-prompt pipeline (RFC-0231), FFS routing (RFC-0232), engine coexistence (RFC-0225), idle unload and re-warm (RFC-0228).
- Phone path (RFC-0222/0223-Android).
- The clientless owner-chat message path (`persona/owner_chat.py` `/messages`, `/messages/stream`).

## 12. Overall acceptance

- [ ] S0 lands first; VRPC "before" report attached.
- [ ] After S1–S5: VRPC repro p50 first audio ≤ 1.5 s typed, ≤ 2.5 s voice; p95 ≤ 2.0 s typed; `decide_ms` ≤ 50 on every turn; the first turn after boot (from the §2 start point) meets the same target, and the first turn after an idle unload does once RFC-0228 S2 has landed.
- [ ] Live-UI rows preserved; full backend suite, `RFC-0230 latency contract tests` step and the JS steps green in CI.
