# RFC-0040: Colibri Deep Inference Tier

**Status:** draft  
**Queue item:** P1 — high-capability local inference / slow-lane reasoning  
**Author:** ChatGPT  
**Date:** 2026-09-07

## Problem

Jarvis currently optimizes inference primarily around conventional local models that fit substantially within VRAM/RAM or are exposed through local/remote inference servers. That limits the maximum local model capability available when the user is willing to trade latency for reasoning quality.

Colibri makes substantially larger sparse Mixture-of-Experts models practical on consumer hardware by treating VRAM, system RAM, and NVMe storage as an inference hierarchy and streaming routed experts from storage as required. It exposes an OpenAI-compatible API and can run as a persistent model service. The trade-off is potentially extreme latency: a large Colibri model can be useful for difficult reasoning tasks while being inappropriate for ordinary conversation, voice control, UI interactions, short tool loops, or other latency-sensitive workloads.

Jarvis therefore needs a first-class **deep inference tier**: a very capable but potentially slow local model runtime that the scheduler invokes selectively when expected quality gains justify the latency.

## Decision

Integrate Colibri as an optional Jarvis inference backend and introduce a `DEEP_LOCAL` / slow-lane execution class for complex, latency-tolerant work.

The first implementation will run Colibri as a separate managed or externally managed process and communicate through its OpenAI-compatible API rather than embedding or forking the Colibri C engine.

Conceptually:

```text
                         JARVIS
                            │
                    Runtime Router
                            │
             ┌──────────────┼──────────────┐
             │              │              │
         FAST LOCAL     DEEP LOCAL       CLOUD
         llama.cpp       COLIBRI          APIs
         Qwen 9/27B     GLM/Kimi/etc
             │              │
          seconds        seconds/minutes+
```

Colibri must not become the normal conversational model. It should instead be selectable when task complexity is high, latency sensitivity is low, interaction requirements are low, privacy preference favors local inference, and the expected quality gain is significant.

Typical Colibri-eligible tasks include:

- architecture analysis;
- large codebase review;
- difficult debugging;
- long-form research synthesis;
- manuscript consistency/review passes;
- complex planning;
- security analysis requiring deeper reasoning;
- verification of outputs from smaller agents;
- difficult problems where Jarvis would otherwise escalate to a premium cloud model.

Typical non-eligible tasks include:

- normal chat;
- voice interactions;
- UI navigation;
- simple tool selection;
- short summarization;
- routine scheduling;
- status queries;
- lightweight agent loops.

### 1. New runtime capability class

Extend runtime profiles with execution and latency classes:

```yaml
execution_class: deep_local
latency_class: very_slow
interaction_modes:
  - batch
  - asynchronous
capabilities:
  - reasoning
  - high_quality
  - large_model
  - local
  - moe_streaming
runtime:
  backend: colibri
```

Recommended normalized latency classes:

```text
REALTIME
INTERACTIVE
NORMAL
SLOW
VERY_SLOW
BATCH
```

Colibri will normally advertise `VERY_SLOW` or `BATCH`, based on measured performance for the active model/hardware combination.

### 2. Explicit task latency tolerance

Add routing metadata to tasks:

```python
TaskInferenceRequirements(
    quality_requirement="high",
    latency_tolerance="batch",
    interaction_required=False,
    allow_deep_local=True,
)
```

Jarvis must never assume a task can wait indefinitely merely because it is complex. Task metadata, Agent Profile, workspace policy, or explicit user preference may override deep-inference eligibility.

### 3. Colibri backend adapter

Add a dedicated backend adapter, likely:

```text
backend/app/inference/colibri.py
```

with a `ColibriBackend(InferenceBackend)` implementation.

The adapter should support:

- health discovery;
- model discovery;
- startup and shutdown;
- OpenAI-compatible chat completions;
- streaming;
- cancellation where supported;
- context/model metadata;
- performance telemetry;
- storage-tier telemetry where exposed;
- cluster state where exposed;
- normalized errors and retry behavior.

Because Colibri exposes `/v1/chat/completions`, Jarvis should reuse its existing OpenAI-compatible provider path wherever possible.

Initial server flow:

```text
coli serve
    ↓
127.0.0.1:8000/v1
    ↓
Jarvis ModelProvider
```

Colibri is an inference runtime, not an agent framework. Jarvis retains ownership of planning, agents, memory, tools, permissions, verification, scheduler, swarm placement, task state, and audit.

### 4. Deep inference escalation

Extend the existing runtime router with an explicit quality/latency trade-off.

Jarvis already scores runtime candidates on quality, latency, cost, privacy, load, warmness, and specialization. Add:

```text
complexity_score
latency_tolerance
expected_quality_gain
deep_inference_bonus
estimated_completion_time
```

Example scoring intent:

```text
Qwen 9B
quality       55
latency       98
ETA           4 sec

Qwen 27B
quality       75
latency       90
ETA           18 sec

Colibri GLM
quality       94
latency       15
ETA           8 min
```

For an interactive request, Qwen 27B should win. For a difficult unattended analysis, Colibri may win.

Raw model capability must never dominate routing without accounting for latency tolerance.

### 5. Two-stage inference

The preferred use of Colibri should often be escalation rather than immediate execution:

```text
Task
 │
 ▼
small/normal model
 │
 ├── confident → finish
 │
 └── uncertain / difficult
             │
             ▼
         Colibri
             │
             ▼
         verifier
```

Jarvis may therefore route a single task through multiple model tiers, for example:

```text
Qwen 9B → classify
Qwen 27B → attempt
Colibri → solve difficult component
Qwen 9B → summarize/result formatting
```

This avoids wasting slow deep-inference calls on simple portions of a task.

### 6. Colibri as Senior/Leader intelligence

Colibri should be eligible as a **model capability assigned to Leader or Senior Worker roles**, but the model runtime must not itself imply either hardware role.

Example:

```text
Leader
RTX 5070 Ti / main node

fast brain:
Qwen 27B

deep brain:
Colibri large MoE

junior agents:
small always-on models
```

Jarvis must distinguish:

```text
model intelligence
≠
node compute speed
≠
worker hierarchy
```

A very slow but highly capable Colibri model can therefore act as a senior/deep reasoning resource without changing the node's assigned swarm role.

### 7. Storage-aware admission

Before making a Colibri model available, Jarvis should inspect:

- free disk capacity;
- model size;
- system RAM;
- available VRAM;
- NVMe capabilities where measurable;
- optional secondary SSD availability.

The UI should expose estimated placement, for example:

```text
Model storage      371 GB
Resident RAM       9.9 GB
VRAM cache         12 GB
NVMe tier          351 GB

Estimated:
Cold              VERY SLOW
Warm              SLOW
```

Installation must require explicit confirmation before downloading very large model assets. Jarvis must refuse installation when free storage is insufficient.

### 8. Benchmark-driven routing

Jarvis must not assume a fixed Colibri throughput. On initial setup and when model/hardware placement materially changes, run a benchmark suite covering where available:

- time to first token;
- tokens/sec;
- cold-cache generation;
- warm-cache generation;
- expert cache hit ratio;
- disk throughput;
- RAM residency;
- VRAM residency;
- power draw where available.

Store results in a normalized profile, for example:

```python
ColibriPerformanceProfile(
    model="glm-5.x",
    node_id="leader",
    cold_tps=...,
    warm_tps=...,
    ttft_seconds=...,
    estimated_task_time=...,
)
```

Routing should use measured performance rather than static marketing expectations.

### 9. Background-task UX

When Colibri is selected, Jarvis must clearly explain why the task is taking longer.

Example:

```text
DEEP INFERENCE

Model
GLM-5.x via Colibri

Reason
High-complexity architecture analysis

Estimated completion
~6–12 minutes

Execution
NVMe-streamed MoE

Status
Loading experts...
```

Execution observability should expose at least:

```text
QUEUED
MODEL_STARTING
LOADING
INFERENCE
VERIFYING
DONE
```

A long Colibri request must not look like Jarvis has frozen.

### 10. Cancellation and fallback

A Colibri request must remain cancellable from Jarvis.

Fallback policy should follow the existing routing/privacy model, conceptually:

```text
COLIBRI
   │ failure / ETA violation
   ▼
NORMAL LOCAL
   │
   ▼
TRUSTED CLOUD
```

Fallback to cloud is allowed only when the configured policy permits it. `LOCAL ONLY` must never escape to cloud automatically.

### 11. Colibri cluster integration

Phase 1 supports a single Colibri host.

Phase 2 may support Colibri's own coordinator/worker execution model as one logical inference backend.

Jarvis should treat a Colibri cluster as one inference runtime rather than exposing every Colibri worker as an independent Jarvis agent worker. This prevents overlapping schedulers and keeps responsibilities clear:

```text
Jarvis swarm
│
├── node A
├── node B
├── node C
│
└── Colibri runtime
      ├── coordinator
      ├── expert worker A
      └── expert worker B
```

Jarvis schedules the task. Colibri schedules model internals.

### 12. Routing policy

Add deep-inference admission logic along these lines:

```python
if runtime.execution_class == "deep_local":
    if task.latency_tolerance in {"realtime", "interactive"}:
        reject()

    if not task.allow_deep_local:
        reject()

    score += complexity_score * DEEP_MODEL_WEIGHT
    score += expected_quality_gain
    score -= estimated_latency_penalty

    if task.background:
        score += BACKGROUND_DEEP_BONUS
```

Provide a configurable escalation threshold, for example:

```text
Deep inference:
Automatic

Escalate when:
complexity          ≥ 0.80
expected gain       ≥ 0.15
latency tolerance   ≥ SLOW

Maximum runtime:
30 min
```

Agent Profiles may override this behavior. Example defaults:

```text
Research Agent     Colibri: preferred
Voice Agent        Colibri: disabled
Developer Agent    Colibri: automatic
Verifier           Colibri: preferred for high-risk outputs
```

## Acceptance criteria

- [ ] Add `colibri` as a recognized inference backend.
- [ ] Implement `ColibriBackend` using Colibri's OpenAI-compatible API.
- [ ] Colibri can be enabled or disabled independently.
- [ ] Existing Jarvis operation does not require Colibri.
- [ ] Colibri installation/runtime is optional.
- [ ] Add normalized `execution_class` and `latency_class` to runtime profiles.
- [ ] Add per-task `latency_tolerance`.
- [ ] Add per-task `allow_deep_local`.
- [ ] Router cannot select Colibri for `REALTIME` or `INTERACTIVE` tasks unless explicitly forced by the user.
- [ ] Router cannot select Colibri when explicitly disabled.
- [ ] Colibri can be forced manually.
- [ ] Colibri may be preferred per Agent Profile.
- [ ] Router considers measured Colibri performance.
- [ ] Cold and warm performance are recorded separately.
- [ ] UI explains why Colibri was selected.
- [ ] UI displays inference progress rather than appearing stalled.
- [ ] Task detail records actual runtime/model/backend.
- [ ] Cancellation terminates or abandons the active Colibri request cleanly.
- [ ] Failure respects configured fallback policy.
- [ ] `LOCAL ONLY` never falls through to public cloud.
- [ ] Model download/storage requirements are shown before installation.
- [ ] Jarvis detects insufficient free disk before model installation.
- [ ] Colibri telemetry is normalized into Jarvis inference metrics.
- [ ] Colibri cluster operation can be represented as a single logical inference endpoint.
- [ ] Tests cover deep-tier admission, forced selection, disablement, cancellation, fallback, privacy boundaries, and ETA/benchmark-based routing.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/colibri.py`, `backend/app/inference/backends.py` |
| Routing | `backend/app/inference/runtime_router.py`, `backend/app/inference/manager.py` |
| Profiles | `backend/app/inference/runtime_profiles.py` |
| Config/API | `backend/app/config.py`, `backend/app/api/model.py`, runtime-profile API |
| Frontend | `frontend/src/pages/Model.tsx`, `frontend/src/pages/RuntimeProfiles.tsx`, task execution detail |
| Tests | `tests/test_colibri.py`, runtime profile/router tests |
| Docs | this RFC plus Colibri setup/runtime notes |

## Out of scope

The first RFC does not require:

- forking Colibri;
- modifying its inference engine;
- embedding Colibri C code into Jarvis;
- implementing new MoE kernels;
- changing model precision;
- building a Jarvis-specific model format;
- reimplementing Colibri expert routing;
- turning Colibri workers into Jarvis workers;
- making Colibri the default Jarvis model.

Those can be evaluated later if tighter integration provides measurable benefits.

## Relationship to RFC-0030

RFC-0030 defines **where an inference request is routed** through selectable inference offload backends.

RFC-0040 defines **when a very slow but unusually capable inference runtime should be used**.

They compose as separate layers:

```text
Task intelligence routing
        │
        ▼
FAST / NORMAL / DEEP
        │
        ▼
Inference backend selection
        │
        ▼
DIRECT / JARVIS_NATIVE / PAIR / COLIBRI
```

Colibri is therefore a model/runtime capability, not a replacement for the Jarvis swarm.

## Notes

Primary references:

- https://github.com/JustVugg/colibri
- https://github.com/JustVugg/colibri/blob/main/docs/api.md
- https://github.com/JustVugg/colibri/blob/main/docs/serve_protocol.md
- `docs/rfcs/0030-selectable-inference-offload-backends.md`

Recommendation: **ADAPT STRONGLY**.

The primary value is not merely that Jarvis can technically run a very large model. It is that Jarvis can keep small and medium models always-on for low-latency cognition while selectively invoking a much larger local model as a deep-thinking senior resource for complex, asynchronous work.