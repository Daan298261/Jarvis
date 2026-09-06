# RFC-0037: Micro-model admission and routing benchmark

**Status:** accepted  
**Queue item:** P1/P4 — runtime benchmarking / tiny-model selection  
**Author:** ChatGPT runtime research  
**Date:** 2026-09-06

## Problem

Tiny models are attractive because they can remain resident, respond quickly and avoid waking a much larger model, but choosing one from vendor benchmarks would be unsafe. A 230M or 270M model may be excellent at function calling yet lose negations, mishandle Dutch, corrupt filenames, or overconfidently route ambiguous commands. Jarvis needs a repeatable local benchmark that decides whether a micro-model is actually good enough for a specific bounded role before it is allowed onto a fast path.

## Decision

Add a **MicroModelAdmission** benchmark and promotion process for models under roughly 1B parameters used for command normalization, intent classification, routing, extraction, lightweight tool selection, verification triage or other latency-sensitive helper roles.

Models are admitted per role, not globally. A model can be approved for `VOICE_NORMALIZER` but rejected for `DIRECT_TOOL_SELECTOR`, or approved for English while requiring fallback for Dutch.

Initial candidate set for the voice-command role:

- LFM2.5-230M;
- FunctionGemma 270M;
- LFM2.5-350M;
- Qwen3-0.6B;
- later equivalents discovered by RFC-0032 RuntimeManifest catalog.

The benchmark runs on the actual target node/runtime/quantization and records both quality and systems performance. Do not extrapolate desktop CUDA results to CPU, NPU, phone or Pi nodes.

### Command corpus

Maintain a versioned Jarvis command corpus with synthetic and user-approved anonymized examples covering:

- Dutch;
- English;
- Dutch/English code switching;
- short direct commands;
- conversational/filler-heavy commands;
- negations and corrections (`do not delete`, `no, open the other one`);
- numbers, dates, percentages and units;
- file paths, application names, URLs and project names;
- homophones/likely ASR errors;
- interrupt/cancel commands;
- ambiguous requests that must escalate;
- destructive/financial/credential/external-message examples that must never be put on an unsafe direct path;
- multi-step requests that must retain every constraint.

Each case contains expected structured fields and whether direct execution is forbidden, optional or required.

### Metrics

At minimum record:

- exact/semantic intent accuracy;
- entity/constraint retention;
- negation retention;
- structured-output parse success;
- forbidden-fast-path false-positive rate;
- escalation recall for ambiguous/high-risk requests;
- language accuracy;
- p50/p95 time-to-first-token and full-envelope latency;
- warm and cold startup latency;
- CPU utilization;
- RAM/VRAM footprint;
- sustained throughput under concurrent ASR/TTS/main-model activity;
- runtime stability over repeated commands.

Safety-critical admission is asymmetric: a false fast-path decision is worse than an unnecessary escalation. Thresholds should therefore prioritize near-zero unsafe-direct false positives even if more commands fall back to the 9B model.

### Promotion

A model/runtime pair progresses through:

`CANDIDATE -> BENCHMARKED -> SHADOW -> ADMITTED -> ACTIVE`

with `REJECTED`, `DEGRADED`, and `ROLLED_BACK` states.

`SHADOW` runs the candidate in parallel with the current path without allowing it to execute direct effects. Compare outputs and latency before activation. After activation, continue sampled auditing and automatically degrade/rollback when quality or latency materially regresses after a model/runtime update.

## Acceptance criteria

- [ ] Add a versioned command benchmark format with expected intent/entities/constraints/escalation policy.
- [ ] Corpus covers Dutch, English and code-switched commands.
- [ ] Negation/constraint fidelity is measured independently from generic intent accuracy.
- [ ] Benchmark records unsafe-fast-path false positives and treats them as a primary admission metric.
- [ ] Models are admitted per role/language/runtime/node rather than by a single global quality flag.
- [ ] Initial benchmark includes LFM2.5-230M, FunctionGemma 270M, LFM2.5-350M and Qwen3-0.6B when compatible artifacts are available.
- [ ] Benchmarks run using the exact quantization/runtime intended for production.
- [ ] Performance measurement occurs while representative ASR/TTS/main-model load is present, not only in isolation.
- [ ] Shadow mode can compare a candidate without granting it direct execution authority.
- [ ] Promotion and rollback decisions store benchmark revision, model artifact hash, runtime version and hardware identity.
- [ ] RuntimeManifest/RuntimeProfile can reference admission evidence for a helper role.
- [ ] A model update or quantization change invalidates/requires revalidation of relevant admission evidence.
- [ ] Regression monitoring can automatically disable the micro-model fast path and fall back to the primary model.
- [ ] Unit tests pass (`python3 -m pytest`).

## Likely files

| Area | Paths |
| --- | --- |
| Benchmark | `benchmarks/` or `tests/fixtures/voice_commands/`, runner/report generator |
| Backend | micro-model admission registry and fast-path eligibility checks |
| Inference | RuntimeManifest/Profile benchmark evidence linkage |
| Tests | corpus parser, metric calculation, promotion/rollback state tests |
| Docs | benchmark authoring and model-admission guide |

## Out of scope

Training a custom tiny model in v1; allowing generic benchmark leadership to override Jarvis-specific failures; storing private raw voice recordings without explicit user choice; replacing full verifier testing for the main agent.

## Notes

Current research makes sub-1B helpers credible: Liquid AI released LFM2.5-230M specifically for fast edge agentic/tool/extraction workflows; Google FunctionGemma specializes a 270M model for function calling; LFM2.5-350M adds stronger small-model tool use; Qwen3-0.6B offers a somewhat larger multilingual fallback. The benchmark, not parameter count or marketing claims, decides which earns a Jarvis fast-path role.

Recommendation: **ADAPT STRONGLY. Benchmark before trust.**
