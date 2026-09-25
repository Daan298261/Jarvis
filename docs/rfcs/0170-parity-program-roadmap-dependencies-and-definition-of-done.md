# RFC-0170: Anzu parity program roadmap and definition of done

**Status:** accepted  
**Date:** 2026-09-24  
**Reconciliation:** These #406 parity drafts (0137–0170) came from main and are kept alongside development’s different documents that reuse 0137–0140: `0137-persona-presence-shape-and-voice-binding.md`, `0138-anzu-orb-custom-ui-generation.md`, `0139-android-companion-fancy-orb-humanoid-ui.md`, and `0140-companion-on-device-voice-models.md`. In this roadmap, “0137” means `0137-capability-parity-matrix-and-continuous-benchmark.md` (Capability Lab), “0138” means the durable-goal draft, “0139” means the skill-forge draft, and “0140” means the agent-rooms draft. Development already implemented Skill Forge and Agent Rooms as RFC-0173 and RFC-0174.

## Problem
RFC-0137–0169 define a broad capability program. Implementing them independently would duplicate infrastructure and make “parity” impossible to close systematically.

## Decision
Define implementation waves by dependency, not competitor branding.

**Foundation:** 0137 Capability Lab, 0144 observability/replay, 0151 sandbox, 0169 security, 0158 Context Compiler, 0168 governor.

**Core agency:** 0138 Goals, 0140 Agent Rooms, 0141 Quartermaster/Arena, 0150 Memory Fabric, 0154 Artifacts, 0167 Quality Loop.

**Action surfaces:** 0145 Computer Use, 0146 Workflows, 0156 Browser, 0155 Coding Missions, 0161 Data Studio, 0147 Channels.

**Ambient/distributed:** 0148 Voice, 0149 Sensorium, 0152 Fabric, 0157 Proactivity, 0159 Offline resilience, 0160 IoT.

**Platform/product:** 0139 Skill Forge, 0142 Capability SDK, 0165 Developer SDK, 0153 Setup/Doctor, 0166 auto-repair, 0162 Privacy, 0164 Backup, 0163 Accessibility.

An RFC is not parity-complete when code merely exists. Definition of done: user-facing path works; deterministic tests pass; security/privacy controls pass; install/update/recovery covered; documentation exists; capability registry links evidence; benchmark has current results; observability exposes failures; no regression of local-only path.

“Exceeds peer” is a benchmark state, not a permanent marketing label: it requires a defined metric, comparable scenario, dated peer evidence and reproducible Anzu result. If comparison is not apples-to-apples, report capability differences instead.

## Acceptance criteria
- [ ] RFC-0137 registry tracks every RFC-0138–0169 capability and dependency.
- [ ] Implementation queue follows dependency gates unless explicitly waived with rationale.
- [ ] Each implementation PR declares capability IDs and tests.
- [ ] Release dashboard distinguishes specified / implemented / verified / parity-demonstrated.
- [ ] No RFC is marked implemented solely from UI scaffolding or mocks.
- [ ] Competitive research can add new capability RFCs without renumbering/reworking this architecture.

## Likely files
Capability registry, RFC index/master-plan queue, release tooling and docs.
