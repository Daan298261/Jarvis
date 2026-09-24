# RFC-0158: Context Compiler — budgeted retrieval, compression and cache

**Status:** accepted  
**Date:** 2026-09-24

## Problem
As Anzu gains memory, tools, agents and evidence, prompt assembly can become the dominant cost and source of context rot.

## Decision
Replace ad-hoc prompt concatenation with a Context Compiler. Inputs are typed context candidates from persona, conversation, project, memory, evidence, artifacts, tools and task state. Each declares priority, provenance, freshness, sensitivity, token estimate and cacheability. Compiler selects under model-specific budgets, deduplicates, compresses only derived context, preserves authoritative excerpts, and records an inspectable context manifest. Prefix/provider caches are used where supported without changing semantics.

## Acceptance criteria
- [ ] One context manifest records selected/dropped candidates and token budget.
- [ ] Sensitive scopes obey routing/privacy constraints.
- [ ] Duplicate and stale context is suppressed.
- [ ] Compression never mutates source-of-truth records.
- [ ] Tool schemas are selected by task instead of always injected.
- [ ] Benchmarks show context size/latency/quality regression data.

## Likely files
Prompt/context assembly, Memory Fabric, tool registry, model router, evals.
