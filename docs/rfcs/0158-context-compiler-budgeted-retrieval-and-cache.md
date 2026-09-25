# RFC-0158: Context Compiler — budgeted retrieval, compression and cache

**Status:** accepted  
**Date:** 2026-09-24  
**Updated:** 2026-09-25

## Problem
As Anzu gains memory, tools, agents and evidence, prompt assembly can become the dominant cost and source of context rot. Retrieval latency and consistency also degrade if ingestion/index mutation shares the latency-sensitive query path.

## Decision
Replace ad-hoc prompt concatenation with a Context Compiler. Inputs are typed context candidates from persona, conversation, project, memory, evidence, artifacts, tools and task state. Each declares priority, provenance, freshness, sensitivity, token estimate and cacheability. Compiler selects under model-specific budgets, deduplicates, compresses only derived context, preserves authoritative excerpts, and records an inspectable context manifest. Prefix/provider caches are used where supported without changing semantics.

Separate retrieval index construction from query serving. Ingestion builds a new immutable/versioned index snapshot off the serving path, validates it, then atomically promotes the snapshot. In-flight queries remain pinned to the snapshot they started with. Failed builds never replace the active snapshot. Keep at least one known-good predecessor for rollback. This is an internal retrieval contract: native and optional external retrieval backends may implement it, but they do not own Jarvis memory truth, task state or policy.

## Acceptance criteria
- [ ] One context manifest records selected/dropped candidates and token budget.
- [ ] Sensitive scopes obey routing/privacy constraints.
- [ ] Duplicate and stale context is suppressed.
- [ ] Compression never mutates source-of-truth records.
- [ ] Tool schemas are selected by task instead of always injected.
- [ ] Index construction/compaction does not mutate the active query snapshot in place.
- [ ] Every query records the retrieval backend and snapshot/version identifier used.
- [ ] Snapshot promotion is atomic; failed validation leaves the previous snapshot active.
- [ ] In-flight queries remain consistent across concurrent snapshot promotion.
- [ ] Rollback to the previous known-good snapshot is supported without rebuilding source memory.
- [ ] Native and external retrieval backends conform to the same Jarvis-owned query/provenance contract.
- [ ] Benchmarks report context size, retrieval/query latency, build cost and quality regressions separately.

## Likely files
Prompt/context assembly, Memory Fabric, retrieval/index service, tool registry, model router, provider interfaces, evals and Control Room diagnostics.

## Out of scope
- Replacing Jarvis source-of-truth memory with a search index.
- Vendor-specific search infrastructure.
- Giving an external retrieval backend ownership of task state, approvals or policy.

## Notes
- Source: https://www.perplexity.ai/hub/blog/photon
- Discovery date: 2026-09-25
- Recommendation: ADAPT
- Adaptation: separate build/serve lifecycles and use validated immutable snapshots; do not reproduce Perplexity's proprietary index formats or search stack.
