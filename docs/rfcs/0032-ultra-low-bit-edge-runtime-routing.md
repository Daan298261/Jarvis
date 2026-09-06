# RFC-0032: Ultra-low-bit models and edge runtime routing

**Status:** accepted  
**Queue item:** P4 — model routing / heterogeneous edge compute  
**Author:** ChatGPT model-runtime review  
**Date:** 2026-09-06

## Problem

Very-low-bit model formats make parameter count and nominal model size poor proxies for whether a model fits a node or is suitable for a Jarvis task. A large aggressively quantized model may have a small weight file yet still require materially more runtime memory for KV cache, buffers, context and concurrency. Quantization may also preserve reasoning better than tool calling, vision or instruction following. Jarvis therefore needs runtime- and task-specific capability accounting rather than routing by parameter count/VRAM heuristics alone. The same change can make optional phones/tablets and other low-power devices useful as ephemeral workers when a supported runtime exists.

## Decision

Extend `RuntimeManifest`, `RuntimeProfile`, node capability discovery and the model router with low-bit/runtime-aware metadata. Treat ultra-low-bit formats as capabilities of runtime adapters, not as a special hard-coded model family.

Model/runtime records should distinguish weight footprint from estimated deployed memory and include effective bits/weight, KV-cache format/precision, required backend/runtime version and kernels/features, accelerator compatibility, speculative-decoding support, modality/tool support, task-class benchmark scores, quality-retention evidence, and license/redistribution status.

Router scoring should use measured task capability and deployed resource cost. Candidate fit includes weights + runtime overhead + KV cache + requested context + concurrency headroom, backend/kernel compatibility, warm-model state, sustained throughput, power/thermal constraints, and per-capability quality thresholds. A model can therefore be acceptable for ordinary chat/coding but ineligible for tool use or vision.

Node discovery should report OS/architecture, RAM/unified memory/VRAM, accelerator, supported runtime backends, supported quantization formats, relevant runtime/kernel versions, sustained inference benchmark, thermal/power policy, and battery state where applicable.

Phones/tablets may later register as optional ephemeral compute workers when they expose a compatible Jarvis runtime adapter. This is independent of the existing Android remote-control client: a phone may be only a control client, only an eligible edge worker, both, or neither. Do not create a mandatory permanent `PHONE` swarm role; schedule it through normal capability discovery and worker policy.

Initial runtime targets should include GGUF/llama.cpp plus MLX where available, with CUDA, Metal, Vulkan and CPU paths represented through adapter capability reporting. The scheduler must ask the runtime adapter whether the exact artifact can execute on the exact node before assignment.

## Acceptance criteria

- [ ] `RuntimeManifest`/model metadata can store `effective_bits_per_weight`, weight footprint, estimated runtime memory, KV-cache format/precision, backend/runtime requirements, required kernels/features and capability tags.
- [ ] Weight file size and estimated execution memory are distinct fields and are both visible to routing/compatibility logic.
- [ ] Runtime memory estimation accounts for model weights, runtime buffers, KV cache for requested context, and configured concurrency/headroom.
- [ ] Capability metadata can independently represent chat, reasoning, coding, instruction-following, tool use/function calling, vision/multimodal and other future task classes.
- [ ] Router policy can define minimum capability/benchmark thresholds per task class; one weak modality can disqualify a model without disqualifying it globally.
- [ ] Router can prefer a larger low-bit model over a smaller higher-bit model when measured quality/resource fit is better.
- [ ] Router records capability-per-GB/resource-efficiency factors without allowing them to override privacy, hard policy, task minimum quality or explicit pins.
- [ ] Backend/runtime/kernel incompatibility rejects a node before model load rather than failing after task assignment.
- [ ] Node probes report OS/architecture, RAM/unified memory/VRAM, accelerator, supported backends/formats, relevant versions, and sustained throughput where benchmarkable.
- [ ] Edge/mobile-capable nodes may additionally report battery and thermal/power constraints; scheduler can avoid or throttle them under user policy.
- [ ] Optional mobile/edge workers use normal Junior Worker/specialist capability scheduling and do not introduce a required phone-specific cluster role.
- [ ] The existing Android control-client contract remains independent from edge compute enrollment and authentication/policy can distinguish the two roles.
- [ ] Runtime adapters expose a preflight `can_run`/equivalent compatibility result for an artifact + node before scheduling.
- [ ] Fallback/escalation can move from an aggressive low-bit local model to a higher-quality local model and then to a permitted cloud profile where policy allows.
- [ ] Verifier policy may require a stronger/different model than the primary worker.
- [ ] Model licenses and redistribution rights remain first-class; low-bit artifacts are not redistributed merely because they are technically loadable.
- [ ] Tests cover low-bit fit, KV/context growth, incompatible runtime/kernel rejection, task-specific capability rejection, edge power policy and escalation.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal Nodes/Models UI is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/...`, router/scoring, runtime adapters, model/runtime manifest schemas |
| Swarm/nodes | capability probes, worker registration, scheduler compatibility/preflight |
| Frontend | Models/Nodes compatibility, measured memory/capability and routing explanation UI |
| Tests | runtime-memory estimation, quantization/capability routing, edge-node fixtures |
| Docs | runtime manifest and low-bit compatibility authoring guide |

## Out of scope

Making PrismML Bonsai or any one model/vendor a dependency; shipping a mobile model runtime in the Android control client; changing the basic Leader/Orchestrator/Senior/Junior role model; assuming a small model file guarantees equivalent quality or memory usage.

## Notes

Reference case: PrismML Bonsai 27B / ternary low-bit releases and their llama.cpp/MLX paths. This RFC captures the architecture lesson rather than binding Jarvis to that implementation. It extends the intent of RFC-0003 and RFC-0018 and is the RFC handoff for GitHub issue #93 (`P4: Ultra-low-bit model support and edge inference routing`).

Recommendation: **ADAPT STRONGLY**.
