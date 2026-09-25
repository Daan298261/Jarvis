# RFC-0159: Offline resilience and degraded/grid-down mode

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Local-first claims need explicit behavior when internet, providers, DNS or power-constrained nodes disappear.

## Decision
Define service capability states ONLINE, DEGRADED, LOCAL_ONLY and OFFLINE. Router, modules and UI consume the same state. Cache owner-approved offline knowledge/model packs/maps/docs through managed packages with provenance/version/size. On connectivity loss, suspend impossible cloud work, continue local-safe tasks, queue outbound operations and clearly mark stale external data. Add a power-saving HUD/runtime profile that reduces polling, animations and model size while preserving core chat/search of local knowledge.

## Acceptance criteria
- [ ] Deterministic connectivity/provider state machine.
- [ ] No cloud retries storm while offline.
- [ ] Queued outbound actions require freshness/revalidation before later send when consequential.
- [ ] Offline packs are hash/version managed and removable.
- [ ] UI visibly distinguishes stale cached data from current observations.
- [ ] Release test simulates full network loss and recovery.

## Likely files
Router/provider health, module manager, companion packs, HUD, tests.
