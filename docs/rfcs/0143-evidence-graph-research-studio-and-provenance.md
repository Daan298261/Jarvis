# RFC-0143: Evidence Graph Research Studio

**Status:** accepted  
**Date:** 2026-09-24

## Problem

Research/intelligence parity requires more than RAG answers: Anzu needs inspectable evidence, contradictions, timelines and exportable dossiers.

## Decision

Build a shared Evidence Graph service used by Nabu/Research and Argus/Intelligence. Nodes: source, observation, claim, entity, event, artifact and assessment. Edges: supports, contradicts, derived-from, mentions, same-as, precedes and confidence relation. Every externally derived claim keeps source URL/record ID, fetch/event time, freshness, extraction method and raw/derived status. Unknown provenance is visibly UNVERIFIED.

Research Studio provides query plan, live source collection, evidence table/graph/timeline, contradiction queue, notes, source health and dossier export. Argus adds intelligence-specific competing hypotheses and confidence; Nabu emphasizes literature/web synthesis. Web content is untrusted data and cannot issue tool instructions.

## Acceptance criteria

- [ ] Typed evidence schema with provenance/freshness and stable deduplication.
- [ ] Claims cannot become “verified” without linked evidence.
- [ ] Contradictory evidence is retained and surfaced, not overwritten.
- [ ] Graph/timeline/dossier exports preserve citations.
- [ ] Research and Argus share the service while retaining persona-specific analysis contracts.
- [ ] Bounded ingestion, prompt-injection isolation and source-health states exist.
- [ ] Tests cover dedupe, contradiction, missing provenance and stale sources.

## Likely files

`backend/app/evidence/`, research/intelligence integrations, DB migrations, Research/Intel UI, tests.
