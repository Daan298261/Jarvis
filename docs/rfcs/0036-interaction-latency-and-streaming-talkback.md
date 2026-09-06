# RFC-0036: Interaction latency budgets and streaming talk-back

**Status:** accepted  
**Queue item:** P1 — responsiveness / user-perceived latency  
**Author:** ChatGPT runtime/voice synthesis  
**Date:** 2026-09-06

## Problem

Jarvis can be technically capable yet feel slow if it waits for full transcription, full reasoning, complete tool execution or an entire generated answer before giving the user feedback. Spoken interaction makes this especially noticeable. The user should quickly know that Jarvis heard the command, what it understood at a high level, whether work has begun, and when it is waiting or verifying. Long model/tool work must not block timely status feedback.

## Decision

Define explicit **interaction latency budgets** and make speech/status output stream independently from long-running reasoning and execution.

Jarvis shall measure the end-to-end interaction as separate stages rather than one opaque duration:

`speech endpoint -> ASR finalization -> command normalization -> task accepted -> first acknowledgement -> first useful result/status -> final verified result`

Initial engineering targets on the primary desktop, subject to benchmark adjustment:

- endpoint detection after the user stops speaking: target p50 <= 250 ms, p95 <= 500 ms;
- final tiny-ASR transcript after endpoint: target p50 <= 350 ms, p95 <= 700 ms for short commands;
- tiny command envelope after transcript: target p50 <= 100 ms and p95 <= 250 ms when the model is warm;
- safe fast-path command dispatch after envelope: target p50 <= 100 ms excluding the external action itself;
- acknowledgement audio should begin as soon as practical after task acceptance, target <= 700 ms from speech endpoint for ordinary short commands on the reference desktop;
- long tasks must surface a meaningful phase/status event within 1 s after acceptance and thereafter on state changes, not by noisy fixed-interval chatter.

These are product targets, not correctness shortcuts. If confidence is low, Jarvis should take longer rather than issue a wrong command.

### Acknowledgement path

Acknowledgement must not require the large reasoning model. Once the command front-end has produced a sufficiently confident envelope and the task has been accepted by policy, Jarvis may immediately speak a short local acknowledgement derived from deterministic templates or the tiny command model, for example a localized equivalent of "I'm checking that" or "Opening it now." It must not claim success before verification.

### Streaming talk-back

For substantive answers, TTS should begin on completed stable text chunks/sentences while the remainder of the answer is still being generated when doing so is semantically safe. Do not wait for the entire final answer to exist before starting speech.

Task execution and speech are separate asynchronous channels. Jarvis may say that it is working while tools/models continue in parallel. Tool execution must never wait for TTS playback to finish unless the user explicitly requested a spoken confirmation before acting.

### Local TTS candidates

Keep TTS provider-neutral and benchmark locally:

- **Piper/ONNX voices** are the baseline for Dutch because mature `nl_NL`/`nl_BE` voices exist and Piper supports local streaming output on low-power hardware.
- **Kokoro 82M** is a candidate for high-quality low-latency English and other supported languages; it is Apache-2.0 and small enough for local use. It is not the Dutch default unless a tested Dutch voice/model becomes available.
- OS-native TTS may remain an emergency/degraded fallback when no Jarvis voice runtime is available.

Prefer CPU/NPU residency for acknowledgement/TTS where possible so speaking does not evict or stall the primary GPU reasoning model.

### Barge-in and interruption

Microphone/VAD remains active enough to recognize deliberate user interruption while Jarvis is speaking. Commands such as "stop", "cancel", "wait", "no", or their Dutch equivalents receive a priority path: duck/stop TTS immediately, preserve the interruption transcript, and route it through the tiny command fast path before resuming any response.

### UI synchronization

The HUD must reflect the same real runtime events used by speech: `LISTENING`, `TRANSCRIBING`, `UNDERSTOOD`, `RUNNING`, `USING_TOOL`, `VERIFYING`, `WAITING_FOR_USER`, `SPEAKING`, `DONE`, `DEGRADED`. Do not animate fake progress unrelated to actual runtime state.

## Acceptance criteria

- [ ] Instrument per-stage latency from speech endpoint through acknowledgement and final result.
- [ ] Dashboard/HUD exposes aggregate p50/p95 latency diagnostics without requiring debug logs.
- [ ] First acknowledgement does not require the 9B/27B model when a command is already accepted with sufficient confidence.
- [ ] Acknowledgement never states that an action succeeded before execution/verifier evidence exists.
- [ ] TTS can consume stable generated chunks incrementally and begin playback before full-answer completion.
- [ ] Tool/model execution continues independently of TTS playback.
- [ ] Dutch local TTS has a tested offline baseline; Piper is the initial candidate.
- [ ] At least one higher-quality compact local TTS candidate is benchmarked for supported languages; Kokoro 82M is an initial candidate.
- [ ] TTS/ASR/tiny-command components are scheduled so they do not unnecessarily evict the primary 9B GPU model.
- [ ] Barge-in immediately stops/ducks playback and priority-routes cancel/stop/wait intents.
- [ ] HUD states are driven by real backend events and correspond to spoken status.
- [ ] Long tasks emit status on meaningful phase transitions without repetitive synthetic chatter.
- [ ] Degraded paths are explicit when ASR/TTS/tiny model is unavailable rather than silently hanging.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] `npm --prefix frontend run build` passes when HUD changes land.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | voice event pipeline, latency telemetry, TTS streaming adapter, interruption coordinator |
| Inference | resource placement for ASR/tiny/TTS and primary model |
| Frontend | HUD runtime-state/event display and latency diagnostics |
| Tests | timing harness, streaming TTS, barge-in, false-success acknowledgement tests |

## Out of scope

Forcing the system to meet a latency target by skipping policy or verification; provider-specific voice branding; full audio-device probing already covered by RFC-0033; choosing one permanent ASR/TTS vendor before benchmark data exists.

## Notes

Reference patterns include FatihMakes/Mark-LII's non-blocking realtime voice/HUD behavior, but Jarvis implements them through its own event and inference architecture. Piper is a fast local streaming TTS option with Dutch voices; Kokoro 82M is an Apache-2.0 compact TTS candidate for supported languages.

Recommendation: **ADAPT STRONGLY. Responsiveness is a first-class product requirement, not a cosmetic optimization.**
