# RFC-0042: FreeToken edge-native MoE runtime and bandwidth-aware scheduling

**Status:** accepted  
**Queue item:** P2/P4 — local inference backends / heterogeneous resource routing  
**Author:** ChatGPT paper and implementation review  
**Date:** 2026-09-07

## Problem

Jarvis currently treats local model feasibility primarily through GPU VRAM, model footprint, quantization, context and broad host resources. That is insufficient for modern sparse Mixture-of-Experts models. FreeToken demonstrates that when the active expert path is small, models far larger than VRAM can still run at interactive speeds if the complete expert pool resides in host RAM and the runtime dynamically coordinates GPU cache residency, CPU execution, PCIe transfers, prefix/state reuse and changing VRAM pressure.

This changes the practical hardware model for Jarvis. For MoE workloads, host-memory capacity and **measured bandwidth**, PCIe host-to-device bandwidth, expert locality, context-state reuse, and runtime elasticity can matter as much as nominal VRAM. A static `model_size <= VRAM` fit check would incorrectly reject useful configurations, while a static CPU/GPU split can perform badly across heterogeneous nodes.

FreeToken is also directly relevant to Jarvis's long-running agents: its semantic state caching is designed around tool calls, thinking blocks, conversation turns and edited histories, and its evaluation includes coding/tool agents rather than only single-turn token benchmarks.

## Decision

Add FreeToken as an optional local `InferenceBackend`/runtime adapter and extend Jarvis node/runtime scheduling with bandwidth-aware MoE capability metadata. Jarvis should integrate the maintained FreeToken server through its OpenAI-compatible and/or Anthropic-compatible API instead of reimplementing FreeToken kernels or expert scheduling.

FreeToken remains an inference engine. Jarvis retains planning, agent identity, tools, memory, permissions, task lifecycle, swarm scheduling, verification, privacy and audit authority.

### 1. Introduce a three-tier local inference hierarchy

Normalize local runtime placement into at least three residency classes:

```text
GPU_RESIDENT
    weights/model working set substantially resident in VRAM
    lowest latency; preferred for ordinary interactive Jarvis work

RAM_RESIDENT_MOE
    full expert pool in host RAM; active/cache working set in VRAM
    FreeToken-class runtime; potentially frontier-scale interactive inference

STORAGE_STREAMED_MOE
    model/expert pool exceeds practical host RAM and streams from NVMe/storage
    Colibri-class deep-local runtime; much higher latency
```

These are runtime capabilities, not hard-coded brands. FreeToken is the initial `RAM_RESIDENT_MOE` candidate and Colibri RFC-0040 remains the initial `STORAGE_STREAMED_MOE` candidate.

Prefer FreeToken over a storage-streamed deep tier when the desired model/quantization is supported, the complete expert pool fits the effective host-RAM budget, and measured service performance satisfies the task latency objective. Preserve Colibri for models/configurations that exceed RAM or are unsupported by FreeToken.

### 2. Add FreeToken as a selectable backend

Extend RFC-0030's backend abstraction with a `FREETOKEN` option, initially as a local endpoint adapter.

Required adapter behavior:

- health and version discovery;
- model discovery where exposed;
- OpenAI-compatible chat/completions support;
- Anthropic-compatible endpoint support only where useful to a harness;
- streaming and cancellation where supported;
- runtime/model/quantization metadata;
- current VRAM/cache allocation where exposed;
- startup/model-load state;
- normalized errors;
- performance telemetry.

Do not fork or embed FreeToken in phase 1. Apache-2.0 licensing permits deeper integration later, but maintained upstream should remain the default dependency boundary unless measurements justify a fork.

### 3. Extend node capability probes with measured bandwidth

MoE scheduling must use measured values from the actual node rather than specification-sheet assumptions. Extend node/runtime capability telemetry with, where measurable:

```text
host_ram_total
host_ram_available_for_inference
host_memory_effective_bandwidth
pinned_h2d_bandwidth
pcie_generation
pcie_link_width
numa_topology
physical_cpu_cores_available
simd_capabilities
vram_total
vram_currently_available
storage_read_bandwidth
runtime_supported_quantizations
runtime_supported_moe_families
```

The critical FreeToken-style signals are normalized as:

```text
B_H = effective host-side expert-processing bandwidth
B_P = effective pinned host-to-GPU transfer bandwidth
```

These must be benchmarked on deployed tensor/runtime paths where practical. `AUTO` routing should not infer them solely from DDR/PCIe generation.

### 4. Model the full MoE residency footprint

Extend `RuntimeManifest` and preflight admission with MoE-specific fields such as:

```text
architecture: moe
parameter_count_total
parameter_count_active
non_expert_vram_bytes
expert_pool_host_bytes
expert_cache_vram_min
expert_cache_vram_recommended
kv_cache_bytes_per_context_unit
host_ram_headroom
supported_weight_layouts
supported_quantizations
```

A FreeToken candidate is eligible only if the complete host-resident source-of-truth expert pool plus required runtime/context headroom fits the configured inference RAM budget. Do not consume all system RAM simply because the model can technically map it.

The user's host resource cap remains authoritative. If the host is configured for, for example, 50% resource use, FreeToken admission and cache sizing must respect that policy.

### 5. Session affinity becomes a routing signal

FreeToken exploits temporal expert locality plus semantic-aware prefix/state reuse across agent turns. Moving a long-running agent session to another runtime/node can destroy warm expert cache and reusable prefix/recurrent state.

Add normalized routing signals:

```text
session_affinity_score
prefix_cache_reuse_bytes_or_tokens
semantic_state_anchor_depth
expert_cache_warmness
estimated_migration_penalty
```

For long tool-using sessions, Jarvis should prefer keeping consecutive model calls on the same healthy runtime when the expected cache/state reuse benefit exceeds load-balancing gains. This is a preference, not a hard pin: failures, resource pressure, explicit node pins or stronger policy may still migrate the task.

### 6. Preserve semantic boundaries in agent context management

Jarvis's context compaction/history editing should preserve stable semantic boundaries around:

- conversation turns;
- tool calls;
- tool outputs;
- planner/executor phase boundaries;
- removable thinking/reasoning segments where the model/runtime protocol exposes them.

The goal is not to copy FreeToken internals. The goal is to make Jarvis context editing predictable for prefix/state caches: remove or replace complete semantic blocks where possible rather than making arbitrary edits deep inside otherwise reusable prefixes.

Expose optional runtime hints/telemetry for semantic cache anchors when the backend supports them.

### 7. Elastic VRAM must cooperate with host resource policy

FreeToken can resize the expert cache at scheduler safe points as VRAM availability changes, allowing correctness to remain host-backed while GPU residency changes performance.

Jarvis should expose a generic runtime capability:

```text
supports_elastic_vram: true/false
min_vram_budget
preferred_vram_budget
current_vram_budget
safe_reconfigure: true/false
```

When the user changes Jarvis's host resource slider, launches a game/application, or another Jarvis workload needs GPU memory, the node scheduler may request a smaller FreeToken cache instead of terminating the entire runtime when supported. When VRAM becomes available again, the cache may grow at a safe point.

This capability must be backend-driven; Jarvis must not assume arbitrary runtimes can resize live.

### 8. Benchmark agent workloads, not only tokens/sec

FreeToken's paper shows that agentic workloads can expose severe TTFT and context-reprefill behavior that single-turn benchmarks miss. Extend Jarvis runtime admission benchmarks with multi-turn traces representing actual Jarvis operation.

Measure at least:

- mean decode tokens/sec;
- p95/p99 or worst-turn TTFT;
- cold-start/model-load time;
- warm-turn TTFT;
- long-context re-prefill cost;
- tool-call turn latency;
- expert-cache hit/miss telemetry where exposed;
- semantic/prefix cache reuse where exposed;
- memory footprint over context growth;
- throughput under concurrent agents;
- user-activity/resource-pressure degradation;
- end-to-end task success.

Tail TTFT must be treated as a service-availability constraint. A runtime that has high average TPS but repeatedly stalls long enough to trigger task/harness timeouts should be downgraded for interactive agent use.

### 9. Current Jarvis hardware implication

The current Leader specification uses a 16 GB RTX 5070 Ti. FreeToken's published results include a 35B MoE model on an 8 GB RTX 4060 laptop and a 284B MoE model on a 32 GB RTX 5090 desktop with much larger host memory. These results **do not prove** that the current Leader can run a particular 284B/753B model: the complete quantized expert pool, host-RAM capacity, model support, CPU bandwidth and PCIe path remain binding constraints.

However, they justify changing Jarvis hardware planning from "buy VRAM only" to a measured multi-resource model. Future Senior Worker purchases/upgrades should score:

```text
GPU VRAM and bandwidth
+ host RAM capacity
+ host memory bandwidth
+ PCIe bandwidth/link width
+ CPU SIMD/memory path
+ NVMe capacity/bandwidth
+ watts / purchase price
```

For MoE-oriented senior workers, inexpensive high-capacity system RAM and a full-bandwidth PCIe GPU link may produce substantially more useful model capability than the same budget spent only chasing a larger GPU.

Jarvis should benchmark the current Leader before making any automatic FreeToken recommendation in the installer/UI.

## Acceptance criteria

- [ ] Add `FREETOKEN` as an optional `InferenceBackend`/offload backend using its supported local API rather than embedding its kernels in phase 1.
- [ ] Add normalized residency classes `GPU_RESIDENT`, `RAM_RESIDENT_MOE`, and `STORAGE_STREAMED_MOE` (names may vary if schema conventions require).
- [ ] FreeToken is optional and existing Jarvis operation does not depend on it.
- [ ] Runtime/node manifests can represent total vs active MoE parameters and separate host expert-pool memory from VRAM working-set/cache requirements.
- [ ] Preflight refuses a FreeToken configuration that exceeds the effective host-RAM budget after policy headroom.
- [ ] Node probes can measure/store effective host expert bandwidth and pinned H2D bandwidth where supported.
- [ ] Router uses measured bandwidth/runtime benchmarks rather than PCIe/DDR labels alone when comparing MoE backends.
- [ ] Session affinity, warm expert state and prefix/state reuse can influence routing without overriding explicit user pins or policy.
- [ ] Context compaction preserves semantic block boundaries where practical to maximize cache reuse and avoid unnecessary re-prefill.
- [ ] Runtime capability can declare live/elastic VRAM resizing and Jarvis may request a revised budget only when that capability is advertised.
- [ ] Host resource usage caps constrain FreeToken RAM/CPU/VRAM allocation.
- [ ] Benchmark harness includes multi-turn tool-agent workloads, tail TTFT, cold/warm behavior, context growth and concurrent-agent measurements.
- [ ] A runtime with unacceptable tail TTFT is downgraded for latency-sensitive task classes even if average TPS is high.
- [ ] Router prefers FreeToken/RAM-resident MoE over storage-streamed deep inference when both satisfy quality requirements and FreeToken meets the latency/resource objective.
- [ ] Colibri RFC-0040 remains eligible when model support/host-RAM limits make RAM-resident serving impossible or inferior.
- [ ] UI can explain why a large model is runnable despite exceeding VRAM, including host RAM, measured bandwidth and expected runtime class.
- [ ] Hardware recommendation logic does not rank LLM nodes by VRAM alone once MoE runtime support is enabled.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal code changes, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/...`, FreeToken adapter, runtime process/service integration |
| Runtime manifests | MoE residency/resource fields, runtime compatibility/preflight |
| Swarm/nodes | bandwidth probes, resource telemetry, session-affinity scheduling |
| Router | residency class, migration penalty, tail-latency and warm-state scoring |
| Context | compaction/history block semantics and cache-friendly edit policy |
| Frontend | node/model compatibility, measured bandwidth, residency class, runtime explanation |
| Tests | FreeToken adapter, MoE fit, bandwidth scoring, session affinity, elastic VRAM, agentic benchmark fixtures |
| Docs | FreeToken setup, MoE hardware guidance, benchmark methodology |

## Out of scope

Reimplementing FreeToken's `q*` policy, CUDA graph cache controller, SIMD kernels, FTW weight format or expert cache; modifying model weights; making FreeToken the default runtime for all models; promising a model will run solely from parameter count; replacing Jarvis's node scheduler with FreeToken's internal execution scheduler.

## Relationship to existing RFCs

- RFC-0018 provides the hardware-aware runtime manifest catalog. RFC-0042 adds MoE-specific capacity/bandwidth fields.
- RFC-0030 provides selectable inference backends. FreeToken becomes another backend under that abstraction.
- RFC-0032 makes runtime memory and quantization first-class. RFC-0042 extends that logic to sparse MoE residency and measured host/interconnect bandwidth.
- RFC-0040 defines a very-slow NVMe-streamed deep-local tier through Colibri. RFC-0042 adds the faster RAM-resident MoE tier between normal GPU-resident inference and storage-streamed inference.

Resulting local hierarchy:

```text
FAST / ordinary local
GPU-resident llama.cpp/Ollama/etc.
        ↓ escalation when useful
RAM-resident frontier MoE
FreeToken-class backend
        ↓ if model exceeds RAM or unsupported
NVMe-streamed deep local
Colibri-class backend
        ↓ if policy permits and preferable
Cloud provider
```

## Notes

Primary references:

- Shuo Yang et al., "FreeToken: Efficient Edge-Native MoE Serving with Bandwidth-Adaptive Execution", arXiv:2608.16157v1, 2026-08-17: https://arxiv.org/abs/2608.16157
- https://github.com/FlashML-org/FreeToken
- https://flashml.ai
- `docs/rfcs/0018-hardware-aware-runtime-manifest-catalog.md`
- `docs/rfcs/0030-selectable-inference-offload-backends.md`
- `docs/rfcs/0032-ultra-low-bit-edge-runtime-routing.md`
- `docs/rfcs/0040-colibri-deep-inference-tier.md`

The paper reports FreeToken serving more than 20 MoE models across hardware from an 8 GB RTX 4060 laptop through a 96 GB RTX PRO 6000. Representative results include Qwen3.6-35B-A3B at 39.3 tok/s on the 8 GB laptop, DeepSeek-V4-Flash (284B total / 13B active) interactively on a 32 GB gaming desktop, and GLM-5.2 (753B total / 40B active) at 14.9 tok/s on the 96 GB workstation. These are research measurements on specific model formats and hosts, not generic guarantees; Jarvis must benchmark each node/runtime/model combination.

FreeToken's repository is Apache-2.0 and currently advertises Windows/Linux desktop setup, OpenAI/Anthropic-compatible APIs, RTX 30/40/50 support, dynamic VRAM allocation, semantic-aware caching and its FTW runtime format.

Recommendation: **ADAPT VERY STRONGLY**. This is more than another inference backend: it changes the hardware signals and session-locality assumptions Jarvis should use when scheduling frontier sparse models on consumer machines.
