# RFC-0168: Resource, energy, thermal and cost governor

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Always-on local AI can saturate VRAM/RAM, fight games/workloads, overheat small nodes and unexpectedly spend cloud budget.

## Decision
Create a global governor over model loading, agents, Sensorium and workflows. Inputs: owner utilization slider, foreground activity, CPU/GPU/RAM/VRAM, temperature where available, battery/power state, provider budget and deadlines. It can queue, downshift model/profile, evict idle models, move work to another node or defer background tasks, while never changing privacy policy. Show decisions and estimated/actual cloud cost.

## Acceptance criteria
- [ ] Hard owner ceilings for host resources and cloud spend.
- [ ] VRAM-aware model admission prevents known overcommit.
- [ ] Foreground/gaming profile can reserve resources.
- [ ] Thermal/battery pressure degrades background work gracefully.
- [ ] Scheduler/Quartermaster/Fabric consume one governor API.
- [ ] Cost/resource decisions are auditable.

## Likely files
Resource monitor/governor, router, cluster scheduler, Models UI, tests.
