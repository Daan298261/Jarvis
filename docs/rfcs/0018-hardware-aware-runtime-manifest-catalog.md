# RFC-0018: Hardware-aware runtime manifest catalog

**Status:** accepted  
**Queue item:** Swarm/runtime installation and compatibility  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-30

## Problem

Jarvis already models node capabilities and runtime/model profiles, but installation and runtime selection still depend too heavily on manual knowledge about which model, quantization, accelerator backend, driver/runtime, memory topology and host configuration are appropriate for a given machine. As Jarvis expands to heterogeneous nodes such as Windows PCs, Linux servers, Raspberry Pis, mini-PCs, ARM systems, discrete-GPU workstations, unified-memory AI PCs and mixed GPU/NPU hardware, this becomes a reliability and onboarding bottleneck.

A competitor pattern worth adapting is a curated model/runtime manifest catalog combined with hardware-aware installation: detect the host, select compatible accelerator/runtime paths, and expose only configurations known to work on that class of device. NVIDIA's 2026 local-AI rollout strengthens this requirement: vendor-maintained optimized llama.cpp/vLLM paths can materially improve local inference and new systems such as RTX Spark expose up to 128 GB of unified CPU/GPU memory, which cannot be modeled correctly as ordinary discrete VRAM. Jarvis therefore needs to treat runtime implementation/build choice and memory topology as versioned, benchmarkable compatibility data rather than hard-coded assumptions.

## Decision

Introduce a versioned `RuntimeManifest` catalog that describes installable and runnable model/runtime combinations independently from user Agent Profiles.

Each manifest MUST be able to declare:

- manifest ID and schema version;
- model/artifact identifiers, hashes, quantization and license metadata;
- supported OS/architecture combinations;
- supported runtime backends such as llama.cpp, Ollama, LM Studio, vLLM or future NPU runtimes;
- runtime distribution/build identity, version, source/provenance, optimization channel, and accelerator target where applicable;
- minimum and recommended RAM/VRAM/**usable unified accelerator memory**/storage;
- accelerator requirements and optional CPU fallback;
- memory-topology requirements/assumptions: `DISCRETE`, `UNIFIED`, `SHARED_SYSTEM`, or provider-specific/unknown;
- expected context limits and approximate resource footprint;
- install/download steps or installer adapter;
- health-check and capability-probe requirements;
- known incompatibilities and warnings;
- trust/provenance/signature metadata.

On node enrollment or runtime setup, Jarvis SHALL probe host hardware/software and calculate manifest compatibility. Capability probing must distinguish physical memory from memory safely allocatable to AI after OS, applications and user-defined host reserve/caps. The UI should present `recommended`, `compatible`, `degraded`, or `unsupported` rather than exposing every possible model/runtime combination equally.

A manifest may reference a vendor- or project-maintained optimized build/channel, but optimization claims are not trusted blindly. Jarvis must distinguish compatibility from measured suitability. Before an optimized runtime/build becomes `recommended` for a hardware class, it should pass a representative local benchmark/health profile against the currently recommended path. Promotion must consider autonomous task success and stability first, then wall-clock latency/throughput, startup/model-load time, effective memory use, and crash/error rate. A faster build that regresses correctness or stability remains `compatible` or `degraded` rather than automatically becoming `recommended`.

Runtime updates must be reversible. Jarvis should retain the prior known-good runtime until the candidate passes install, health and smoke/benchmark checks. Vendor channels may update asynchronously, so manifests must pin the exact tested runtime/build version or artifact digest rather than resolving an unbounded `latest` at execution time.

This catalog feeds RFC-0003 runtime/model routing but does not replace Runtime Profiles. A Runtime Profile expresses how Jarvis wants to use a model; a Runtime Manifest expresses whether and how that model/runtime can safely run on a specific node.

## Acceptance criteria

- [ ] Define a versioned `RuntimeManifest` schema with validation.
- [ ] Node capability probing records OS, architecture, CPU/RAM, accelerator type, discrete VRAM where applicable, unified/shared memory topology and capacity where applicable, storage, and installed accelerator/runtime versions where detectable.
- [ ] Capability probing records both physical memory and an `ai_allocatable_memory` estimate after OS reserve, active workload reserve and user-configured host resource caps.
- [ ] Runtime manifests can express memory requirements without assuming `RAM + VRAM` are independent pools; unified-memory nodes are evaluated from allocatable unified capacity.
- [ ] Jarvis evaluates each manifest against a node and returns `recommended`, `compatible`, `degraded`, or `unsupported` with machine-readable reasons.
- [ ] Runtime manifests can identify the exact runtime implementation/distribution/build, version or digest, source/provenance, optimization channel, and intended hardware/accelerator target.
- [ ] Vendor/project optimized channels can be represented without making Jarvis depend on a specific vendor runtime.
- [ ] Unsupported configurations cannot be auto-installed without an explicit user override.
- [ ] Recommended manifests can drive a zero/low-configuration install path for a newly enrolled node, including automatic model/quantization/runtime selection within user policy.
- [ ] Artifact checksums and source/provenance are verified before activation.
- [ ] A candidate runtime/build is not promoted to `recommended` solely from vendor performance claims; promotion requires a Jarvis-controlled health/smoke benchmark on a representative hardware fixture or the target node.
- [ ] Runtime evaluation prioritizes task success/stability and records wall-clock latency/throughput, model-load/startup time, effective memory use, and error/crash rate where measurable.
- [ ] A failed install, health check, or promotion benchmark leaves the prior working runtime untouched and records a recoverable failure.
- [ ] Runtime updates retain a known-good rollback target and never resolve an untested floating `latest` build at task execution time.
- [ ] Runtime Profiles in RFC-0003 can reference a manifest ID while retaining routing/policy settings separately.
- [ ] The Nodes/Models UI shows why a runtime is or is not suitable for a particular node, its memory topology/allocatable AI memory, and whether the runtime is native/upstream/vendor-optimized.
- [ ] Tests cover x86_64 CPU-only, NVIDIA discrete GPU, ARM low-power, and a 128-GB-class unified-memory AI-PC fixture plus incompatible-manifest rejection.
- [ ] Unified-memory tests prove Jarvis does not double-count the same physical memory as both RAM and VRAM and respects the user's host reserve/cap.
- [ ] Tests cover an optimized candidate that benchmarks faster but fails stability/correctness gates and therefore is not promoted to `recommended`.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | node capability registry/probes, model/runtime registry, installer service, runtime benchmark/promotion service |
| Schemas | RuntimeManifest, memory-topology/capability and compatibility result models |
| Frontend | Nodes / Models compatibility, memory topology, optimization-channel and install UI |
| Tests | manifest validation, hardware/memory matching, install rollback, promotion/benchmark fixtures |
| Docs | runtime manifest authoring, memory accounting, trust model, optimized-runtime lifecycle |

## Out of scope

Remote node pairing/transport itself, general app/plugin marketplace behavior, model-selection routing policy, and making NVIDIA software or RTX Spark a mandatory Jarvis dependency.

## Notes

Initial source: https://www.taos.my/  
Initial discovery date: 2026-08-30  
Initial recommendation: ADAPT.  

Additional sources: https://blogs.nvidia.com/blog/local-ai-ifa-next-gen-agents-nv-pair-rtx-spark/ and https://www.nvidia.com/en-us/products/rtx-spark/  
Update date: 2026-09-07  
Recommendation: **ADAPT STRONGLY** for versioned vendor-optimized runtime channels, zero/low-configuration hardware-aware setup, and topology-aware memory accounting.

Jarvis adapts NVIDIA's useful direction rather than targeting one product: detect hardware, select a validated local model/runtime automatically, consume vendor-optimized builds behind portable manifests, and model large unified-memory AI PCs correctly. RTX Spark is evidence that future Jarvis nodes may expose 64–128 GB unified CPU/GPU memory; Jarvis must reason about allocatable memory rather than assuming discrete VRAM. Vendor performance and capacity claims remain inputs to validate, not permanent routing assumptions.
