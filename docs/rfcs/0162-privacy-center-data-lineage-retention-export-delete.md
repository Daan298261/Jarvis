# RFC-0162: Privacy Center — data lineage, retention, export and deletion

**Status:** accepted  
**Date:** 2026-09-24

## Problem
A personal assistant accumulates conversations, memory, sensor observations, artifacts and connector data. Users need one comprehensible control surface.

## Decision
Build a Privacy Center over a Data Inventory. Every durable data class declares storage location, purpose, source, sensitivity, retention policy, encryption state, sync/export behavior and deletion semantics. Provide per-class retention controls, project/persona deletion, export, connector revocation and a lineage explorer showing which derived memories/artifacts came from which sources. Deletion propagates to Anzu-owned indexes/caches while preserving minimal tombstones/audit evidence where legally/technically required.

## Acceptance criteria
- [ ] Machine-readable data inventory covers all durable stores.
- [ ] User can inspect/export/delete by conversation/persona/project/data class.
- [ ] Derived indexes are rebuilt/purged after source deletion.
- [ ] Retention jobs are testable and auditable.
- [ ] Connector revocation stops future access and clears brokered tokens.
- [ ] UI states limitations where external providers retain copies.

## Likely files
Storage/memory/artifacts/audit, credential broker, Privacy UI, tests.
