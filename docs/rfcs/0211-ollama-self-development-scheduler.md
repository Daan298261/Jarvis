# RFC-0211 — ANZU-directed Ollama self-development

Status: accepted

## Problem
The owner runs local Qwen models through Ollama and wants ANZU to schedule its own development from repository and Google Drive RFCs. Existing self-dev worktrees and mobile reminders do not provide an RFC intake-to-worker execution path.

## Decision
Provide an owner-controlled self-development queue and recurring scheduler. Repository RFCs and explicitly imported Drive documents have stable source identities and content revisions. Queue approval is bound to the revision; edits invalidate approval. Execute one RFC at a time from a pinned development revision in a registered worktree, using a separate process running ANZU's existing tool/verification agent. This process uses local Ollama without switching the owner's chat model. Require tool capability for the coder and vision capability for the screenshot model; route image-bearing turns to the latter. Retain existing tool authorization and surface pending actions in ANZU. Never automatically merge, deploy, install or restart the trusted application.

Drive supports owner imports and recurring refresh through explicitly configured read-only MCP search/fetch tools. A missing connector is an actionable state, never reported as continuous sync. Drive staging digests are reference material rather than automatically executable tickets. Work-item/revision design follows the work-item-bound sessions proposal in jarvis_specs and its 2026-10-09 adoption digest.

## Acceptance
- ANZU can scan, select, queue, start, pause and stop RFC missions and inspect their tasks, worktrees and results.
- Due schedules serialize missions, survive restarts without replaying interrupted edits, and stop after consecutive failures or the emergency stop.
- Execution uses a development base, bounded duration, actual tool use and the coding verification contract. Worker-reported success alone is not accepted as verified delivery.
- Image turns use an Ollama model advertising vision; text-only coder models are never given images.
- Source changes invalidate queued revisions; duplicate sources do not create duplicate execution.
- Repository and MCP intake are off the event loop where blocking; settings and supervisor writes are atomic.
- Focused tests and frontend build/lint; Windows local-model/tool/vision evidence recorded separately from source checks.

## Likely files
backend/app/agent/development_scheduler.py, development_worker.py, backend/app/api/self_dev.py, backend/app/main.py, backend/app/agent/worktrees.py, frontend/src/pages/SelfDevelopment.tsx, frontend/src/App.tsx, tests/test_rfc0211_*.py.
