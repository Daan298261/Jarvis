# RFC-0063 — Local Inference, Voice, Translation & Personality Stack

Status: **APPROVED FOR IMPLEMENTATION SCAFFOLDING**
Priority: **P1/P2**
Owner: Jarvis Architect
Requested by: Taco
Date: 2026-09-12

## 1. Goal

Jarvis should use the best practical local intelligence stack for the owner's RTX 5070 Ti 16 GB rather than assuming that one LLM must perform every function.

The target is a small set of cooperating local services:

```text
User input
   │
   ├─> language / intent / verbosity detection
   │
   ▼
PRIMARY BRAIN
   │
   ├─> tools / workers / workflows
   │
   ▼
PRESENTATION WORKER
   ├─ language normalization / translation when needed
   ├─ concise-vs-detailed control
   ├─ configurable personality
   └─ occasional context-appropriate humor
   │
   ▼
Text response
   │
   └─ optional TTS
        ├─ natural configurable quality voice
        └─ tiny low-latency fallback
```

The primary brain remains responsible for factual reasoning and tool decisions. Presentation must not mutate code, JSON, commands, paths, quotes, tool calls, or structured outputs.

The system must remain model-provider-neutral and expose OpenAI-compatible endpoints internally where practical.

## 2. Current hardware target

Baseline host:

- RTX 5070 Ti — 16 GB VRAM
- Intel i7-14700KF
- 64 GB RAM today; architecture must benefit automatically if upgraded to 128 GB
- fast NVMe storage

The stack must leave real VRAM headroom for KV cache, CUDA workspace, Windows, lazy vision, and short bursts of concurrent work. A model merely fitting as weights is not sufficient.

## 3. Default-brain candidates

No model becomes permanent default from reputation alone. Jarvis must benchmark candidates on the actual machine and select on verified autonomous-task performance.

### 3.1 Preferred first candidate — Qwen3.8 9B Distill Uncensored

Candidate family:

- `petruhonk/Qwen3.8-9B-Distill-uncensored-heretic`
- GGUFs: `petruhonk/...-GGUF` or reputable imatrix/static quants derived from that checkpoint

Recommended trials:

- Q6_K: ~7.6–7.7 GB
- Q8_0: ~9.8 GB

Why it leads the first benchmark:

- 9B dense model sized well for 16 GB VRAM;
- distilled from a much larger Qwen3.8 teacher into Qwen3.5 architecture;
- native Qwen function calling;
- preserved MTP head in the published uncensored GGUF;
- published source-model evaluation shows a large MMLU CoT gain over the Qwen3.5-9B base while GSM8K is roughly flat/slightly lower;
- the Heretic build reports low refusal behavior with relatively small KL deviation.

Use Q6 as the likely **resident balanced default** if quality is sufficiently close to Q8, because the saved ~2.2 GB is valuable for KV cache and auxiliary services. Use Q8 as the quality reference.

References:
- https://huggingface.co/petruhonk/Qwen3.8-9B-Distill-uncensored-heretic
- https://huggingface.co/petruhonk/Qwen3.8-9B-Distill-uncensored-heretic-GGUF
- https://huggingface.co/empero-ai/Qwen3.8-9B-Distill-GGUF

### 3.2 Fast-primary candidate — LFM2.5-8B-A1B Uncensored

Candidate:

- `zaakirio/LFM2.5-8B-A1B-Uncensored-GGUF`

Trials:

- Q6_K ~6.96 GB
- Q8_0 ~9.01 GB

Reasons to test:

- ~8.3B total but only ~1.5B active parameters/token;
- edge-oriented MoE;
- 128K context;
- base model explicitly trained for reliable tool calling;
- should offer unusually high throughput per GB if current llama.cpp support is stable.

Caveat: Liquid's LFM license is not Apache/MIT. Licensing must be reviewed before this becomes a redistributable bundled default.

References:
- https://www.liquid.ai/blog/lfm2-5-8b-a1b
- https://huggingface.co/zaakirio/LFM2.5-8B-A1B-Uncensored-GGUF

### 3.3 Small-agent candidate — MiniCPM5-2B Abliterated

Preferred small worker candidate:

- official base: `openbmb/MiniCPM5-2B`
- abliterated GGUF derivative: benchmark a reputable current MiniCPM5-2B abliterated/uncensored quant

Reasons:

- 2.5B-class footprint;
- 128K context;
- Apache-2.0 base;
- unusually strong published agent/tool/coding results for its size, including BFCL v4 and SWE-bench Verified;
- ideal candidate for routing, lightweight tool loops, translation/presentation, and Junior Nodes.

MiniCPM5-1B remains a micro/router candidate, but 2B should be tested first when a few extra GB are available because its capability jump may outweigh its small residency cost.

Reference:
- https://huggingface.co/openbmb/MiniCPM5-2B

### 3.4 Small fallback candidate — Nemotron3 Nano 4B Uncensored

Candidate:

- `Unrestricted/Nemotron3-Nano-4B-Uncensored-HauhauCS-Aggressive`

Useful trial:

- Q8_K_P ~4.4 GB

Role:

- compact general worker;
- possible presentation/translation worker if it materially beats 1–2B candidates;
- possible low-end primary on smaller swarm nodes.

Reference:
- https://huggingface.co/Unrestricted/Nemotron3-Nano-4B-Uncensored-HauhauCS-Aggressive

## 4. Kimi assessment

Kimi must be evaluated honestly rather than selected because of frontier reputation.

### Kimi K3

Current Colibri support can run Kimi K3, but K3 is roughly 2.8T total / 104B active parameters. It is a frontier-scale streamed MoE, not a sensible interactive default for this machine.

Use case:

- optional laboratory / deep-expert endpoint;
- long-running analysis where latency is acceptable;
- future multi-node/high-RAM experimentation.

Do **not** make Kimi K3 the default Jarvis brain on the 5070 Ti.

### Kimi K2.5

Kimi K2.5 is a strong multimodal/agentic model, but current Colibri model-family support does not make it a practical small local default. Keep it as an API/remote or future runtime candidate rather than designing Jarvis around it.

References:
- https://github.com/MoonshotAI/Kimi-K2.5
- https://github.com/JustVugg/colibri/blob/main/docs/kimi_k3.md

## 5. Colibri integration

Colibri is strategically interesting because it treats VRAM, RAM and NVMe as an inference hierarchy for MoE models and exposes an OpenAI-compatible server.

Jarvis should integrate Colibri as **another InferenceBackend / OpenAI-compatible local endpoint**, never as a hard dependency.

### 5.1 First Colibri candidate — Qwen3.6-35B-A3B Abliterated

This is the most interesting Colibri candidate for the current host:

- ~35B total / ~3B active per token;
- Colibri recommended int4 container around 20 GB;
- roughly 24 GB RAM residency requirement for the standard container;
- CUDA hot-expert tier supported;
- Colibri reports 1.44 → 10.05 tok/s on 2×8 GB GPUs for its Qwen3.6 engine; single-5070-Ti performance must be measured locally rather than inferred.

Uncensored/abliterated Qwen3.6-35B-A3B checkpoints exist, including `wangzhang/Qwen3.6-35B-A3B-abliterated-v2`. The Jarvis experiment must only claim compatibility after conversion/runtime validation.

This model is a **candidate heavy local brain / expert**, not automatically the default.

References:
- https://github.com/JustVugg/colibri
- https://huggingface.co/wangzhang/Qwen3.6-35B-A3B-abliterated-v2

### 5.2 Colibri models not suitable as default today

- Kimi K3 — too large/slow for everyday interactivity on current hardware.
- GLM-5.2 744B — useful proof that Colibri works, but published single-5070-Ti decode is around ~1 tok/s on representative setups; expert-only.
- Qwen3.8-Flash-Next — current Colibri path is CPU-only and ~185 GB FP8, so not an everyday default.

### 5.3 Required Colibri adapter behavior

Jarvis must support:

- executable/path discovery;
- `coli doctor --json` readiness checks;
- `coli plan --json` resource plan ingestion;
- `coli tune` as an explicit benchmark/tuning action;
- `coli serve` OpenAI-compatible endpoint;
- configurable RAM/VRAM budgets;
- quality/balanced policy;
- model health and current bottleneck telemetry;
- graceful fallback to llama.cpp/LM Studio if Colibri is unavailable.

Jarvis must never silently use lossy Colibri routing flags such as top-p expert pruning unless the user/profile explicitly allows a quality trade-off.

## 6. Target model roles

Jarvis should expose logical roles, not hard-code one model everywhere:

```text
MICRO
  MiniCPM5-1B or equivalent
  always-on classification, routing, event triage

SMALL
  MiniCPM5-2B / Nemotron Nano 4B
  lightweight agents and background jobs

PRIMARY
  Qwen3.8-9B Distill Uncensored (first candidate)
  or LFM2.5-8B-A1B Uncensored if benchmarks win

PRESENTATION
  0.8–2B worker
  language, verbosity and personality layer

EXPERT
  larger 27B or Qwen3.6-35B-A3B via Colibri
  difficult escalation

LAB / FRONTIER-LOCAL
  Kimi K3 / GLM-class Colibri endpoint
  explicit slow tasks only
```

A model can fill more than one role if benchmarks show that keeping one small resident service is better than loading two nearly identical models.

## 7. Presentation / translator / personality worker

This service should be small and cheap enough to stay resident or CPU-capable.

First candidates:

1. Qwen3.5-0.8B abliterated/uncensored
2. MiniCPM5-1B abliterated/uncensored
3. MiniCPM5-2B abliterated if the capability gain justifies residency

Responsibilities:

- detect language;
- preserve the original language when the primary handles it well;
- translate only when needed;
- default output to concise;
- infer when the user explicitly wants detail;
- apply a configurable personality preset;
- occasionally add context-appropriate dry humor/comments;
- normalize text for speech.

### 7.1 Default answer-length policy

Default: **AUTO, biased toward concise**.

Available modes:

- very-short
- concise
- balanced
- detailed
- exhaustive
- auto

### 7.2 Personality presets

Minimum presets:

- Minimal — terse, no jokes
- Professional — concise, neutral
- Jarvis Dry — concise, understated, occasional dry comment
- Friendly — warmer, light humor
- Custom

Custom controls:

- verbosity;
- formality;
- warmth;
- humor frequency;
- dryness/sarcasm;
- proactivity;
- directness.

Humor must be context-aware and suppressible. Never inject jokes into serious or high-risk interactions merely to satisfy a frequency target.

### 7.3 Integrity boundary

Presentation processing must not rewrite:

- tool calls;
- JSON/schema output;
- commands;
- source code;
- file paths;
- quoted evidence;
- hashes/identifiers;
- structured data requiring byte/exact preservation.

## 8. TTS / voice stack

Existing RFC-0056 / issue #121 remains authoritative for the complete voice runtime. This RFC defines the inference-resource relationship.

Primary quality candidate:

- **Chatterbox Multilingual V3** — natural multilingual voice, configurable/zero-shot speaker identity, lazy quality engine.

Fast fallback:

- **Kokoro-82M** — tiny, fast, suitable for CPU/low-VRAM fallback.

Optional low-latency English candidate:

- Chatterbox Turbo.

Required properties:

- backend-neutral voice profiles;
- multiple configurable voices;
- speed and expressiveness controls when supported;
- lazy quality-engine loading;
- TTS unavailable => text continues normally;
- quality TTS must not evict the primary model for text-only sessions;
- swarm scheduler can later place TTS on a secondary GPU/node.

## 9. VRAM profiles for 16 GB

### 9.1 Balanced / recommended target

```text
Primary Qwen3.8 9B Q6       ~7.6 GB
Micro/presentation          ~1–2.7 GB
Q8 KV + runtime/workspace   remaining budget
Quality TTS                 lazy or CPU fallback
Vision projector            lazy
```

This is the preferred architecture if Q6 passes quality gates.

### 9.2 Quality profile

```text
Primary Qwen3.8 9B Q8       ~9.8 GB
Presentation ~0.8–1B        ~0.5–1.5 GB
KV cache / runtime          remaining budget
Quality TTS                 lazy
Vision                      lazy
```

Use dynamic context and cache quantization to prevent spill.

### 9.3 Fast parallel profile

```text
LFM2.5 8B-A1B Q6            ~7.0 GB
MiniCPM5 1–2B               ~1–3 GB
Kokoro                      CPU/tiny
```

Benchmark for high parallel throughput and always-on operation.

## 10. Benchmark and promotion gate

The default model must be chosen by **verified useful autonomous work**, not a single academic score.

Jarvis benchmark suite should include at minimum:

- instruction adherence;
- correct native tool calling;
- JSON/schema adherence;
- simple and multi-step filesystem work;
- shell execution planning;
- recovery after failed tool call;
- browser workflow planning;
- code-edit tasks;
- debugging;
- task decomposition;
- long-running loop stability;
- Dutch ↔ English and additional multilingual prompts;
- concise-answer compliance;
- refusal/over-refusal tests for legitimate owner tasks;
- TTFT;
- prompt processing speed;
- decode tok/s;
- peak VRAM;
- peak RAM;
- context scaling;
- load/unload time;
- successful tasks per wall-clock minute;
- human intervention rate.

### 10.1 Weighted decision rule

The benchmark should publish component scores rather than hiding the decision in an opaque AI judgment.

Recommended default weighting:

- autonomous task completion / verification: 30%
- tool calling + structured output: 20%
- recovery / loop stability: 10%
- reasoning + coding: 15%
- multilingual quality: 5%
- refusal/over-refusal suitability: 5%
- latency / throughput: 10%
- VRAM/RAM efficiency: 5%

The winner becomes default only if it also passes hard gates:

- fully local by default;
- no routine CPU layer spill for the normal primary profile;
- reliable tool calls;
- no major regression in task success versus incumbent;
- leaves enough memory for normal Jarvis operation;
- acceptable license for intended distribution.

## 11. Download and runtime UX

Jarvis should support LM Studio/Hugging Face discovery without forcing the user to know repository names.

Model UI should show:

- role;
- recommended candidate;
- quant;
- expected weight size;
- estimated VRAM headroom;
- installed/not installed;
- runtime compatibility;
- license warning where relevant;
- benchmark status;
- `Download`, `Test`, `Promote`, `Rollback` actions.

If LM Studio already has a compatible model, prefer importing/reusing it rather than redownloading.

## 12. Routing behavior

Default routing after this RFC is implemented:

```text
simple deterministic task
→ native tool / deterministic code first

very small classification/presentation task
→ micro/small model

normal autonomous task
→ primary model

primary fails / complexity threshold exceeded
→ expert model

explicit deep local task where latency is acceptable
→ Colibri expert/lab endpoint

speech requested
→ TTS after final natural-language presentation
```

The routing layer must account for model warm state and load cost.

## 13. Implementation phases

### Phase A — registry and configuration (implement now)

- Add candidate models to the advisory model catalog.
- Add logical `primary`, `micro`, `presentation`, and `colibri-expert` routing roles.
- Add presentation/personality settings.
- Expand TTS settings with backend/loading preferences.
- Add current candidate metadata to LM Studio grading catalog.
- Add tests for role normalization/catalog/config defaults.

### Phase B — benchmark harness

- Extend agent benchmark to accept model candidates and role labels.
- Add multilingual/verbosity/tool-loop tasks.
- Record VRAM/RAM/load time and verified task completion.
- Produce promotion report.

### Phase C — local download/runtime support

- Add one-click Hugging Face/LM Studio candidate discovery/download.
- Add model compatibility preflight.
- Implement primary promotion/rollback.

### Phase D — presentation worker

- Run language/style model as separate local endpoint or lightweight service.
- Protect structured spans from rewriting.
- Implement presets and concise-default logic.

### Phase E — TTS

- Implement RFC-0056 using Chatterbox/Kokoro benchmark results.
- Stream/cancel speech; expose selectable voices.

### Phase F — Colibri

- Implement Colibri backend adapter around `doctor`, `plan`, `tune`, `serve`.
- First experiment: Qwen3.6-35B-A3B compatible uncensored checkpoint.
- Keep Kimi K3/GLM-class engines lab-only until latency makes them practical.

## 14. Acceptance criteria

Phase A is complete when:

- candidate catalog is represented in code;
- Qwen3.8 9B, LFM2.5 8B-A1B, MiniCPM5 2B, Nemotron Nano 4B, Qwen3.6/Colibri and Kimi/Colibri are distinguishable candidates;
- routing understands primary/micro/presentation/Colibri expert roles;
- concise/personality settings persist;
- TTS engine/loading preferences persist;
- current default behavior is not silently replaced before local benchmark sign-off.

Full RFC is complete when:

- actual 5070 Ti benchmark selects the default primary;
- user can download/reuse the selected model with minimal configuration;
- small presentation worker handles language/length/personality without corrupting structured content;
- natural configurable TTS works with graceful fallback;
- Colibri can be enabled as an optional local expert backend;
- Jarvis can expose the benchmark evidence that caused a model to be promoted.

## 15. Current provisional recommendation

Until the benchmark is run on the real host:

1. **Primary first benchmark:** Qwen3.8-9B-Distill Uncensored Heretic Q6_K, with Q8_0 as quality reference.
2. **Fast-primary challenger:** LFM2.5-8B-A1B Uncensored Q6/Q8.
3. **Small worker:** MiniCPM5-2B Abliterated; compare MiniCPM5-1B for micro role.
4. **Alternative small worker:** Nemotron3 Nano 4B Uncensored.
5. **Heavy local/Colibri challenger:** Qwen3.6-35B-A3B Abliterated.
6. **Kimi K3:** lab/expert only, not default.
7. **TTS:** Chatterbox Multilingual V3 quality + Kokoro fallback.
8. **Presentation:** Qwen3.5-0.8B abliterated or MiniCPM5-1B/2B, selected by translation/style benchmark.

This recommendation is deliberately provisional. Jarvis promotes the model that completes the most real work correctly on the owner's actual machine.