# RFC-0170: Anzu parity program roadmap and definition of done

**Status:** accepted  
**Date:** 2026-09-24

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
