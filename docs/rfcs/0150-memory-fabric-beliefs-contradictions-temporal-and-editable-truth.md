# RFC-0150: Memory Fabric — temporal facts, beliefs, contradictions and editable truth

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Vector recall alone cannot distinguish current facts, superseded facts, uncertain beliefs, source documents and user corrections.

## Decision
Unify existing ContextRepo/Supermemory/Obsidian paths behind a Memory Fabric API while retaining owner-editable authoritative stores. Memory objects are typed: fact, preference, decision, episode, project state, entity relation, source excerpt and hypothesis. Store valid-time/observed-time, provenance, confidence and supersession links. Contradictions create review items rather than overwriting truth. Retrieval combines lexical/vector/graph/recency and persona/project scope with a strict token budget.

## Acceptance criteria
- [ ] Typed temporal memory schema and provenance.
- [ ] User corrections supersede prior memory while preserving history.
- [ ] Contradictions are surfaced and resolvable.
- [ ] Retrieval reports why each memory was selected.
- [ ] Cross-persona/project access follows explicit scope rules.
- [ ] Existing Obsidian/native fallback remains usable if semantic sidecars fail.

## Likely files
Memory/context repo, Supermemory adapter, Obsidian bridge, Memory UI, tests.
