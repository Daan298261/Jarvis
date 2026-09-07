# RFC-0018: Hardware-aware runtime manifest catalog

**Status:** accepted  
**Queue item:** Swarm/runtime installation and compatibility  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-30

## Problem

Jarvis already models node capabilities and runtime/model profiles, but installation and runtime selection still depend too heavily on manual knowledge about which model, quantization, accelerator backend, driver/runtime, and host configuration are appropriate for a given machine. As Jarvis expands to heterogeneous nodes such as Windows PCs, Linux servers, Raspberry Pis, mini-PCs, ARM systems, and mixed GPU/NPU hardware, this becomes a reliability and onboarding bottleneck.

A competitor pattern worth adapting is a curated model/runtime manifest catalog combined with hardware-aware installation: detect the host, select compatible accelerator/runtime paths, and expose only configurations known to work on that class of device. NVIDIA's September 2026 local-AI rollout strengthens this requirement: vendor-maintained optimized llama.cpp/vLLM paths can materially improve local inference and may arrive independently of Jarvis releases. Jarvis therefore needs to treat runtime implementation/build choice as versioned, benchmarkable compatibility data rather than a hard-coded binary preference.

## Decision

Introduce a versioned `RuntimeManifest` catalog that describes installable and runnable model/runtime combinations independently from user Agent Profiles.

Each manifest MUST be able to declare:

- manifest ID and schema version;
- model/artifact identifiers, hashes, quantization and license metadata;
- supported OS/architecture combinations;
- supported runtime backends such as llama.cpp, Ollama, LM Studio, vLLM or future NPU runtimes;
- runtime distribution/build identity, version, source/provenance, optimization channel, and accelerator target where applicable;
- minimum and recommended RAM/VRAM/storage;
- accelerator requirements and optional CPU fallback;
- expected context limits and approximate resource footprint;
- install/download steps or installer adapter;
- health-check and capability-probe requirements;
- known incompatibilities and warnings;
- trust/provenance/signature metadata.

On node enrollment or runtime setup, Jarvis SHALL probe host hardware/software and calculate manifest compatibility. The UI should present `recommended`, `compatible`, `degraded`, or `unsupported` rather than exposing every possible model/runtime combination equally.

A manifest may reference a vendor- or project-maintained optimized build/channel, but optimization claims are not trusted blindly. Jarvis must distinguish compatibility from measured suitability. Before an optimized runtime/build becomes `recommended` for a hardware class, it should pass a representative local benchmark/health profile against the currently recommended path. Promotion must consider autonomous task success and stability first, then wall-clock latency/throughput, startup/model-load time, VRAM/RAM use, and crash/error rate. A faster build that regresses correctness or stability remains `compatible` or `degraded` rather than automatically becoming `recommended`.

Runtime updates must be reversible. Jarvis should retain the prior known-good runtime until the candidate passes install, health and smoke/benchmark checks. Vendor channels may update asynchronously, so manifests must pin the exact tested runtime/build version or artifact digest rather than resolving an unbounded `latest` at execution time.

This catalog feeds RFC-0003 runtime/model routing but does not replace Runtime Profiles. A Runtime Profile expresses how Jarvis wants to use a model; a Runtime Manifest expresses whether and how that model/runtime can safely run on a specific node.

## Acceptance criteria

- [ ] Define a versioned `RuntimeManifest` schema with validation.
- [ ] Node capability probing records OS, architecture, CPU/RAM, GPU/NPU type, available VRAM, storage, and installed accelerator/runtime versions where detectable.
- [ ] Jarvis evaluates each manifest against a node and returns `recommended`, `compatible`, `degraded`, or `unsupported` with machine-readable reasons.
- [ ] Runtime manifests can identify the exact runtime implementation/distribution/build, version or digest, source/provenance, optimization channel, and intended hardware/accelerator target.
- [ ] Vendor/project optimized channels can be represented without making Jarvis depend on a specific vendor runtime.
- [ ] Unsupported configurations cannot be auto-installed without an explicit user override.
- [ ] Recommended manifests can drive a zero/low-configuration install path for a newly enrolled node.
- [ ] Artifact checksums and source/provenance are verified before activation.
- [ ] A candidate runtime/build is not promoted to `recommended` solely from vendor performance claims; promotion requires a Jarvis-controlled health/smoke benchmark on a representative hardware fixture or the target node.
- [ ] Runtime evaluation prioritizes task success/stability and records wall-clock latency/throughput, model-load/startup time, memory use, and error/crash rate where measurable.
- [ ] A failed install, health check, or promotion benchmark leaves the prior working runtime untouched and records a recoverable failure.
- [ ] Runtime updates retain a known-good rollback target and never resolve an untested floating `latest` build at task execution time.
- [ ] Runtime Profiles in RFC-0003 can reference a manifest ID while retaining routing/policy settings separately.
- [ ] The Nodes/Models UI shows why a runtime is or is not suitable for a particular node and whether it is native/upstream/vendor-optimized.
- [ ] Tests cover at least x86_64 CPU-only, NVIDIA GPU, and ARM low-power node fixtures plus incompatible-manifest rejection.
- [ ] Tests cover an optimized candidate that benchmarks faster but fails stability/correctness gates and therefore is not promoted to `recommended`.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | node capability registry/probes, model/runtime registry, installer service, runtime benchmark/promotion service |
| Schemas | RuntimeManifest and compatibility result models |
| Frontend | Nodes / Models compatibility, optimization-channel and install UI |
| Tests | manifest validation, hardware matching, install rollback, promotion/benchmark fixtures |
| Docs | runtime manifest authoring, trust model, optimized-runtime lifecycle |

## Out of scope

Remote node pairing/transport itself, general app/plugin marketplace behavior, model-selection routing policy, and making NVIDIA software a mandatory Jarvis dependency.

## Notes

Initial source: https://www.taos.my/  
Initial discovery date: 2026-08-30  
Initial recommendation: ADAPT.  

Additional source: https://blogs.nvidia.com/blog/local-ai-ifa-next-gen-agents-nv-pair-rtx-spark/  
Additional source: https://developer.nvidia.com/blog/nvidia-pair-virtual-inference-router-expands-available-compute-on-your-local-network/  
Discovery date: 2026-09-07  
Recommendation: ADAPT STRONGLY for versioned vendor-optimized runtime channels with Jarvis-controlled promotion/rollback.  

The useful taOS pattern remains the hardware-detecting installer and curated model-manifest catalog across heterogeneous local hardware. NVIDIA's September 3, 2026 local-AI rollout adds a second concrete pattern: optimized llama.cpp/vLLM builds and simplified local-agent setup may be maintained and improved by the hardware/runtime vendor. Jarvis should consume such maintained optimizations behind its own manifest/provider abstraction when they prove beneficial, while retaining runtime portability, exact-version provenance, benchmark-based promotion and rollback. NVIDIA reports up to 1.9x faster local inference for its current optimization work; Jarvis should treat that as a candidate-performance claim to validate, not a permanent architectural assumption.
