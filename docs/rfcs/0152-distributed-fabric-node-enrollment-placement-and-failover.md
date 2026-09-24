# RFC-0152: Distributed Fabric — node enrollment, placement and failover

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Anzu is intended to use desktops, laptops, Raspberry Pis and GPU workers as one system. Manual host selection prevents reliable swarm operation.

## Decision
Build a signed cluster fabric. Nodes enroll through explicit pairing and advertise capabilities: CPU/GPU/VRAM/RAM/storage, models, sensors, tools, power state, latency and owner resource ceiling. Scheduler places inference/tasks using privacy, locality, capability, load, energy and data-gravity constraints. Heartbeats and leases prevent split-brain work. Durable tasks can fail over from checkpoints; hardware-bound actions remain pinned.

## Acceptance criteria
- [ ] Cryptographic node identity and revocation.
- [ ] Capability/resource advertisement with owner-set utilization ceiling.
- [ ] Placement reason is inspectable.
- [ ] Lease expiry prevents duplicate execution after partitions.
- [ ] Checkpointable jobs fail over safely; nonportable jobs do not.
- [ ] LOCAL_ONLY/private data never leaves allowed nodes.

## Likely files
Cluster/node registry, scheduler, companion gateway, resource governor, tests.
