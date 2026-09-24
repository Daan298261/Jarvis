# RFC-0153: Zero-config onboarding, Doctor, updates and recovery

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Capability is irrelevant if installation, model setup and recovery require developer knowledge.

## Decision
Create one guided Setup state machine for install/upgrade/recovery. Detect hardware, disk, runtimes, microphones/cameras, GPU backends and reachable model providers; recommend but never silently buy/use cloud services. Provision isolated dependencies, run smoke tests, then present a readiness report. Add `Anzu Doctor` diagnostics with safe automated fixes. Updates are signed/pinned, staged, health-checked and rollback-capable. Preserve user data/license/credentials according to existing owned-path contracts.

## Acceptance criteria
- [ ] Fresh supported machine reaches working chat without terminal use.
- [ ] Hardware/model recommendation explains constraints and disk/VRAM impact.
- [ ] Doctor diagnoses voice/model/network/module/DB problems and can repair safe cases.
- [ ] Failed update rolls back application/runtime without losing owner data.
- [ ] Offline/local-only onboarding path exists.
- [ ] Install/update/recovery scenarios are release-gated.

## Likely files
Installer/setup, module lifecycle, model catalog, Settings/Setup UI, release tests.
