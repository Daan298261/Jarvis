# RFC-0161: Data Studio — tables, charts, notebooks and governed SQL

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Anzu should analyze datasets as first-class artifacts instead of pushing large tables through chat text.

## Decision
Add Data Studio for CSV/XLSX/JSON/Parquet and configured databases. Profile datasets locally, infer schemas, create queryable temporary views, execute bounded Python/SQL in RFC-0151 sandboxes and emit versioned table/chart/report artifacts. Database connectors default read-only; writes require explicit connector capability and approval. Queries, transformations and chart specifications are retained as lineage.

## Acceptance criteria
- [ ] Large datasets use artifact/query paths rather than prompt injection.
- [ ] Schema/profile preview before analysis.
- [ ] Sandboxed Python/SQL with time/memory/result-size caps.
- [ ] Read-only DB default and credential-broker integration.
- [ ] Reproducible transformation/chart lineage.
- [ ] Persona/Goal/Workflow integration.

## Likely files
`backend/app/data_studio/`, sandbox, artifacts, frontend, tests.
