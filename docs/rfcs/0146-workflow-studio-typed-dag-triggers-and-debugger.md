# RFC-0146: Workflow Studio — typed DAGs, triggers and debugger

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Competitors expose visual reusable workflows. Anzu needs durable automation composition without creating a second execution engine beside Goals and Tasks.

## Decision
Add a typed DAG workflow definition compiled onto existing task/goal primitives. Nodes cover tools, agents, conditions, transforms, approvals, waits, schedules/webhooks, loops with hard bounds, subworkflows and artifacts. Validate schemas and permissions before execution. Workflow versions are immutable once run. Provide visual editor, dry-run, breakpoints, step execution, replay and per-node timing/cost/error inspection.

## Acceptance criteria
- [ ] Versioned JSON schema and DAG validation including cycle rules.
- [ ] Trigger support uses existing scheduler/event infrastructure.
- [ ] Approval nodes durably suspend/resume.
- [ ] Dry-run and deterministic replay work without external side effects.
- [ ] Visual editor can inspect/edit/export/import workflows.
- [ ] Goal Runtime can invoke workflows and workflows can delegate bounded goals.

## Likely files
`backend/app/workflows/`, scheduler/events, frontend Workflow Studio, tests.
