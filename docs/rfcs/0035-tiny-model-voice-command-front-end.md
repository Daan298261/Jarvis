# RFC-0035: Tiny-model voice command front-end

**Status:** accepted  
**Queue item:** P1 — low-latency interaction / voice command fast path  
**Author:** ChatGPT runtime/voice synthesis  
**Date:** 2026-09-06

## Problem

Jarvis should feel immediate when receiving spoken commands. Sending every utterance through the primary 9B/27B reasoning stack adds avoidable latency, consumes scarce GPU residency and makes trivial commands feel slow. Voice input also needs a normalization stage: speech recognition output can contain filler words, transcription errors, partial phrasing and conversational wording that a larger execution model should not have to disentangle from scratch.

A much smaller always-resident model can act as a command front-end: understand the transcript, preserve user intent, classify the request, extract entities, choose whether a deterministic fast path is sufficient, and construct a compact structured request for the larger Jarvis model when deeper reasoning is needed.

## Decision

Add a local **Voice Command Front-End** that is independent from the main reasoning model and small enough to remain resident on CPU/system RAM or another low-cost accelerator without evicting the primary GPU model.

Pipeline:

`microphone -> VAD/endpointing -> streaming ASR -> tiny command model -> fast-path tool OR structured prompt envelope -> 9B primary -> 27B escalation when needed`

The tiny command model does not replace the main agent. It performs bounded interpretation only and emits a structured envelope such as:

```json
{
  "raw_transcript": "...",
  "normalized_request": "...",
  "intent": "open_app | status | cancel | system_setting | task | question | unknown",
  "entities": {},
  "language": "nl | en | ...",
  "urgency": "normal | interrupt",
  "complexity": "instant | normal | expert",
  "direct_action_candidate": null,
  "confidence": 0.0
}
```

The original transcript is always preserved and forwarded alongside normalization when a larger model is invoked. The tiny model may clean filler and obvious ASR artifacts but may not silently discard material constraints, names, quantities, negations, destinations or safety-relevant wording.

### Fast path

High-confidence, narrowly scoped, low-risk commands may bypass the large model and invoke existing deterministic Jarvis capabilities after normal policy/firewall checks. Initial examples:

- cancel/stop the current task;
- report current task/system status;
- mute/unmute or adjust volume;
- open a known application;
- pause/resume listening;
- simple navigation to a known Jarvis UI view.

Unknown, destructive, credential, financial, external-message, ambiguous or multi-step commands always escalate. The tiny model can propose a direct action but never bypass RFC-0002 policy, RFC-0027 firewall or RFC-0031 human-gate semantics.

### Candidate tiny text models

Benchmark rather than hard-code one model. Initial candidates:

- **LFM2.5-230M** — 230M parameters; positioned for edge agentic workflows, tool use and extraction; official Liquid figures report very high decode speed even on phone/Pi-class hardware.
- **FunctionGemma 270M** — specialized Gemma 3 270M variant for natural-language-to-function-call translation; strong candidate for direct command/tool classification.
- **LFM2.5-350M** — slightly larger fallback with native tool calling and stronger instruction-following while remaining extremely small.
- **Qwen3-0.6B** — larger fallback with broad multilingual support and agent/tool capabilities; particularly relevant for mixed Dutch/English commands.

Do not select on generic benchmark score alone. Jarvis needs command-intent accuracy, negation retention, named-entity fidelity, Dutch/English robustness, structured-output validity, cold/warm latency and CPU memory footprint.

### Candidate ASR front-end

- **Whisper tiny (39M)** is the initial multilingual baseline because Jarvis must handle Dutch as well as English.
- **Moonshine Tiny (27M)** is worth benchmarking for English-only/edge scenarios because of its very small footprint, but it must not become the default if Dutch quality is inadequate.
- Runtime-optimized Whisper implementations (for example whisper.cpp/ONNX paths) may be preferred over the original Python stack when benchmarked latency is better.

VAD/endpointing should be deterministic and lightweight; do not use the large LLM to decide whether the user stopped speaking.

## Acceptance criteria

- [ ] Voice input has a distinct ASR + tiny-command stage before the main reasoning model.
- [ ] The tiny text model can remain resident without forcing the primary 9B model out of GPU memory.
- [ ] The normalization envelope always includes the raw transcript when escalating to a larger model.
- [ ] Tests prove negation, quantities, filenames/names, destinations and safety-sensitive constraints survive normalization.
- [ ] High-confidence low-risk instant commands can execute without a 9B/27B round trip after normal policy checks.
- [ ] Ambiguous, multi-step, destructive, credential, financial and consequential external commands always escalate/gate appropriately.
- [ ] The tiny model cannot grant itself capabilities or create human approvals.
- [ ] Candidate benchmark includes LFM2.5-230M, FunctionGemma 270M, LFM2.5-350M and Qwen3-0.6B or documented equivalents available at implementation time.
- [ ] ASR benchmark includes a multilingual tiny model suitable for Dutch and English; Whisper tiny is the baseline.
- [ ] Benchmark corpus contains natural spoken Dutch, English and code-switched Jarvis commands, including false starts and conversational filler.
- [ ] Runtime records p50/p95 endpoint-to-envelope latency, structured-output validity, intent accuracy, entity fidelity and memory/CPU/GPU usage.
- [ ] Low-confidence tiny-model output automatically falls through to the main model instead of guessing.
- [ ] User interruption/cancel commands receive elevated priority and can preempt a long-running response/task path.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If UI is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | voice ingress, ASR adapter, command-normalizer adapter, fast-path router |
| Inference | tiny runtime profile/manifest integration from RFC-0003/0018/0032 |
| Policy | direct-action checks through existing authorization/firewall/approval boundaries |
| Tests | voice-command corpus, normalization fidelity, latency and fast-path routing |
| Frontend | listening/transcribing/understood state only; no separate voice UI architecture |

## Out of scope

Using the tiny model as Jarvis's primary reasoning agent; allowing it to autonomously execute complex work; replacing the 9B/27B hierarchy; full duplex audio-device/session reliability already covered by RFC-0033; final TTS/talk-back latency policy, covered separately.

## Notes

Model references reviewed 2026-09-06: Liquid AI LFM2.5-230M/350M, Google FunctionGemma 270M, Qwen3-0.6B, OpenAI Whisper tiny and Useful Sensors Moonshine Tiny. The RFC intentionally defines a benchmarked role rather than locking Jarvis to one vendor/model.

Recommendation: **ADAPT STRONGLY / implement as a resident micro-model front-end.**
