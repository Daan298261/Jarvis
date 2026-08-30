# RFC-0018: Hardware-aware runtime manifest catalog

**Status:** accepted  
**Queue item:** Swarm/runtime installation and compatibility  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-30

## Problem

Jarvis already models node capabilities and runtime/model profiles, but installation and runtime selection still depend too heavily on manual knowledge about which model, quantization, accelerator backend, driver/runtime, and host configuration are appropriate for a given machine. As Jarvis expands to heterogeneous nodes such as Windows PCs, Linux servers, Raspberry Pis, mini-PCs, ARM systems, and mixed GPU/NPU hardware, this becomes a reliability and onboarding bottleneck.

A competitor pattern worth adapting is a curated model/runtime manifest catalog combined with hardware-aware installation: detect the host, select compatible accelerator/runtime paths, and expose only configurations known to work on that class of device.

## Decision

Introduce a versioned `RuntimeManifest` catalog that describes installable and runnable model/runtime combinations independently from user Agent Profiles.

Each manifest MUST be able to declare:

- manifest ID and schema version;
- model/artifact identifiers, hashes, quantization and license metadata;
- supported OS/architecture combinations;
- supported runtime backends such as llama.cpp, Ollama, LM Studio, vLLM or future NPU runtimes;
- minimum and recommended RAM/VRAM/storage;
- accelerator requirements and optional CPU fallback;
- expected context limits and approximate resource footprint;
- install/download steps or installer adapter;
- health-check and capability-probe requirements;
- known incompatibilities and warnings;
- trust/provenance/signature metadata.

On node enrollment or runtime setup, Jarvis SHALL probe host hardware/software and calculate manifest compatibility. The UI should present `recommended`, `compatible`, `degraded`, or `unsupported` rather than exposing every possible model/runtime combination equally.

This catalog feeds RFC-0003 runtime/model routing but does not replace Runtime Profiles. A Runtime Profile expresses how Jarvis wants to use a model; a Runtime Manifest expresses whether and how that model/runtime can safely run on a specific node.

## Acceptance criteria

- [ ] Define a versioned `RuntimeManifest` schema with validation.
- [ ] Node capability probing records OS, architecture, CPU/RAM, GPU/NPU type, available VRAM, storage, and installed accelerator/runtime versions where detectable.
- [ ] Jarvis evaluates each manifest against a node and returns `recommended`, `compatible`, `degraded`, or `unsupported` with machine-readable reasons.
- [ ] Unsupported configurations cannot be auto-installed without an explicit user override.
- [ ] Recommended manifests can drive a zero/low-configuration install path for a newly enrolled node.
- [ ] Artifact checksums and source/provenance are verified before activation.
- [ ] A failed install or health check leaves the prior working runtime untouched and records a recoverable failure.
- [ ] Runtime Profiles in RFC-0003 can reference a manifest ID while retaining routing/policy settings separately.
- [ ] The Nodes/Models UI shows why a runtime is or is not suitable for a particular node.
- [ ] Tests cover at least x86_64 CPU-only, NVIDIA GPU, and ARM low-power node fixtures plus incompatible-manifest rejection.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | node capability registry/probes, model/runtime registry, installer service |
| Schemas | RuntimeManifest and compatibility result models |
| Frontend | Nodes / Models compatibility and install UI |
| Tests | manifest validation, hardware matching, install rollback fixtures |
| Docs | runtime manifest authoring and trust model |

## Out of scope

Remote node pairing/transport itself, general app/plugin marketplace behavior, model benchmarking methodology, and changing the routing policy defined by RFC-0003.

## Notes

Source: https://www.taos.my/  
Discovery date: 2026-08-30  
Recommendation: ADAPT  

The useful pattern is taOS's hardware-detecting installer and curated model-manifest catalog across heterogeneous local hardware. Jarvis should adapt the compatibility-manifest abstraction and safety/rollback behavior, not copy taOS's desktop, store, branding, or exact manifest inventory. This complements the existing `SWARM_ARCHITECTURE.md` capability registry and RFC-0003 runtime profiles without duplicating either.
