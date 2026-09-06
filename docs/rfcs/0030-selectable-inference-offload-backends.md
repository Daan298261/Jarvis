# RFC-0030: Selectable inference offload backends

**Status:** accepted  
**Queue item:** P2/P3 — swarm execution / inference routing  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-09-04

## Problem

Jarvis has its own swarm placement and runtime-routing architecture, but users may also have access to maintained external local-inference routers such as NVIDIA Personal AI Router (PAIR). PAIR exposes Ollama-compatible and OpenAI-compatible local proxy endpoints, discovers paired nodes, tracks engine/model availability and workload, and routes each independent inference request to one eligible machine. Jarvis should not force one offload mechanism or duplicate vendor-maintained routing where an external backend is useful. It also must not confuse request routing with VRAM pooling: PAIR does not combine GPUs or shard one request across machines.

PAIR's current scheduler also has materially different placement intelligence from Jarvis. NVIDIA documents the present policy as primarily queue/workload based with coarse smoothed GPU-utilization input; it does not currently account for GPU class, available VRAM, model warmness, measured latency, or estimated request cost. That makes PAIR valuable for concurrent local inference, especially on similar machines, but unsafe to treat as automatically equivalent to Jarvis-native placement on a highly heterogeneous swarm.

## Decision

Introduce an `InferenceOffloadBackend` abstraction and user-selectable policy so Jarvis can choose among native Jarvis placement, NVIDIA PAIR, direct single-node execution, and future compatible routers without changing Agent Profiles or task logic.

Initial backend modes:

- `DIRECT` — execute on the selected local runtime/node only.
- `JARVIS_NATIVE` — use Jarvis node discovery, placement, resource policy, role constraints, warm-model/data-locality scoring, and audit telemetry.
- `NVIDIA_PAIR` — route inference through a configured PAIR local endpoint while Jarvis retains task orchestration, capability policy, model intent, verification, cost/resource accounting, and audit authority.
- `AUTO` — choose the best allowed backend from measured availability and policy; never silently cross a privacy or capability boundary.

PAIR integration is a provider adapter, not a replacement for Jarvis swarm architecture. Jarvis may delegate *inference request placement* to PAIR, but worker assignment, tools, filesystem access, task state, policy, approvals, verification, durable execution, and non-inference workloads remain Jarvis-owned.

Backend selection is configurable globally, per Agent Profile, per workspace/domain, and per task. Hard user choices (`FORCED`) override learned routing. `AUTO` may learn from observed completion latency, queue delay, model load time, failure rate, node availability, and user activity, but must remain reversible and explainable.

Jarvis must evaluate the *backend's routing capability*, not merely endpoint health. For PAIR, the adapter should surface the scheduler signals/version it can actually observe and classify the cluster as `SUITABLE`, `DEGRADED`, or `UNKNOWN` for automatic use. On materially heterogeneous clusters, `AUTO` should prefer Jarvis-native placement unless benchmark evidence shows PAIR meets the configured service objective or the user explicitly prefers/forces PAIR. A vendor upgrade that adds stronger scheduling signals may improve that classification without changing the Jarvis abstraction.

PAIR capabilities must be discovered rather than assumed. The adapter should detect endpoint health, supported API surface, available models where exposed, whether the backend is local, and enough cluster/runtime metadata to explain backend suitability. If PAIR is unavailable or unsupported for the requested model, Jarvis may fall back only according to configured fallback policy and must record the reason.

Do not represent PAIR as distributed VRAM. Each request is served by one eligible node. Large-model sharding or tensor/model parallelism belongs to separate runtime backends if added later.

## Acceptance criteria

- [ ] Define an `InferenceOffloadBackend` interface with backend ID, health/capability discovery, model availability, request execution, cancellation where supported, telemetry, and normalized errors.
- [ ] Implement backend modes `DIRECT`, `JARVIS_NATIVE`, `NVIDIA_PAIR`, and `AUTO` in configuration/schema even if PAIR ships behind a feature flag initially.
- [ ] Add a PAIR adapter using its local OpenAI-compatible and/or Ollama-compatible endpoint; do not require changes to agent prompts/harness logic.
- [ ] Backend choice can be set globally and overridden per Agent Profile, workspace/domain, and individual task.
- [ ] Support selection policy values such as `FORCED`, `PREFERRED`, `AUTO`, and `DISABLED`; `FORCED` never silently changes backend.
- [ ] `AUTO` scoring may use measured latency, queue delay, model presence, model load/startup time, backend/node utilization, historical success rate, and user-activity/resource constraints.
- [ ] Add a normalized backend-suitability result (`SUITABLE`, `DEGRADED`, `UNKNOWN`) with machine-readable reasons such as heterogeneous hardware, missing placement signals, stale telemetry, unsupported model, or insufficient benchmark evidence.
- [ ] The PAIR adapter must not claim PAIR considers GPU class, free VRAM, model warmness, latency, or request cost unless the detected PAIR version/API actually exposes and uses those signals.
- [ ] For a heterogeneous cluster, `AUTO` does not prefer PAIR over Jarvis-native placement solely because the PAIR endpoint is healthy; PAIR must satisfy configured benchmark/service-objective evidence or be explicitly preferred/forced.
- [ ] For similar-node clusters, PAIR may be considered `SUITABLE` when endpoint/model health is good and representative concurrency benchmarks meet the configured service objective.
- [ ] Jarvis records selected backend, endpoint/cluster identity, requested model, actual model/runtime where observable, backend suitability, selection reason, fallback reason, latency, success/failure, and verification result.
- [ ] PAIR unavailability degrades only the PAIR path; configured fallback may use Jarvis-native or direct execution without losing task state.
- [ ] If privacy mode is `LOCAL ONLY`, only endpoints positively classified as local/trusted may be used; `AUTO` cannot escalate to cloud solely because PAIR/native routing failed.
- [ ] Backend policy cannot bypass node/resource limits, protected-device rules, gaming/interactive-use exclusions, or Agent Profile authority.
- [ ] UI exposes an "Inference offload" selector with concise options: Automatic, Jarvis swarm, NVIDIA PAIR, This device; advanced settings show fallback order, current health, and a concise suitability warning when an external router has weaker placement signals than Jarvis-native routing.
- [ ] Task detail shows which offload backend actually served each model call when non-direct routing is used.
- [ ] Benchmark harness can compare `DIRECT`, `JARVIS_NATIVE`, and `NVIDIA_PAIR` on representative concurrent-agent workloads using success rate and wall-clock completion, not tokens/sec alone; include at least one homogeneous-node and one heterogeneous-node scenario when such hardware is available.
- [ ] Tests prove that PAIR routing is treated as one-request-to-one-node and is never presented as pooled VRAM/model sharding.
- [ ] Tests prove `AUTO` can downgrade or avoid an externally healthy backend whose routing capability is insufficient for the current cluster/policy.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | inference provider/router abstraction, model runtime service, placement/router policy, PAIR adapter |
| Config | Agent Profile/workspace/task inference-offload policy schemas |
| Frontend | Model/System settings, Agent Profile overrides, task execution detail |
| Tests | backend selection, fallback, privacy policy, PAIR adapter, suitability gating, telemetry, benchmark integration |
| Docs | inference routing/offload architecture and PAIR setup notes |

## Out of scope

Replacing Jarvis native swarm scheduling; using PAIR for filesystem/tool/worker placement; GPU-memory pooling; tensor/model parallel sharding across nodes; cloud inference providers; automatic installation of PAIR in the first implementation; depending on undocumented NVIDIA APIs; reimplementing PAIR's internal scheduler.

## Notes

Source: https://developer.nvidia.com/blog/nvidia-pair-virtual-inference-router-expands-available-compute-on-your-local-network/  
Source: https://github.com/NVIDIA/Personal-AI-Router  
Source: https://github.com/NVIDIA/Personal-AI-Router/blob/main/docs/known-issues.mdx  
Source: https://github.com/NVIDIA/Personal-AI-Router/blob/main/docs/architecture.mdx  
Source: https://www.nvidia.com/en-eu/ai-on-rtx/personal-ai-router/  
Discovery date: 2026-09-04; scheduler-capability refinement discovered 2026-09-06  
Recommendation: ADAPT STRONGLY.  

Jarvis is adapting PAIR as an optional maintained inference-routing backend behind a provider-neutral abstraction. Jarvis keeps orchestration and policy authority and retains its native swarm for broader heterogeneous execution. NVIDIA PAIR currently supports compatible RTX, DGX Spark/Grace-Blackwell, and Apple-silicon systems through local OpenAI/Ollama-compatible proxy endpoints; exact vendor capabilities must be discovered at runtime rather than hard-coded as permanent assumptions.

The integration intentionally treats external-backend health and external-backend placement quality as separate questions. PAIR's current scheduler limitations are not a reason to reject the integration: they are a reason for Jarvis `AUTO` to benchmark and gate delegation intelligently while still allowing an explicit user choice.
