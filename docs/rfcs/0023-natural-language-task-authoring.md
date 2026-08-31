# RFC-0023: Natural-language task authoring

**Status:** accepted  
**Queue item:** Scheduler UX / autonomous task authoring  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-31

## Problem

Jarvis has scheduler and durable-goal primitives, but requiring users to configure schedules, event sources, prompts, budgets, and policies through low-level forms creates unnecessary friction. Competitors make simple follow-ups and recurring AI work feel like a natural extension of chat. Jarvis needs that ease of use while preserving explicit, inspectable runtime configuration.

## Decision

Allow users to create one-shot, recurring, and event/condition-driven Jarvis tasks through natural-language commands. Jarvis converts the request into a structured `TaskDefinition` preview and requires confirmation when the proposed task would create external side effects, spend beyond configured thresholds, access sensitive integrations, or introduce ambiguity that materially changes execution.

Natural language is an authoring interface only. The durable source of truth is always a structured task definition containing schedule/trigger, owner agent/workflow, prompt/objective, workspace/context bindings, routing policy, budget, permissions, retry policy, notification behavior, and lifecycle state.

Simple reminder-like or read-only scheduled tasks may be created with a compact confirmation flow. Advanced users can open/edit the structured representation directly.

## Acceptance criteria

- [ ] Chat/task composer recognizes user intent to create one-shot, recurring, scheduled, or condition/event-driven work and produces a structured preview rather than keeping scheduling semantics only in prompt text.
- [ ] Persist `TaskDefinition` with trigger/schedule, timezone, owner agent/workflow, objective/prompt, workspace/context bindings, routing policy, budget reference, permissions, retry policy, notification behavior, enabled state, and created-by provenance.
- [ ] Natural-language date/time parsing resolves to an explicit timezone-aware schedule and shows the resolved next run before creation.
- [ ] Recurrence is stored as structured schedule data; editing the visible prompt alone cannot silently change cadence.
- [ ] Condition/event-driven tasks link to the `EventSubscription`/GoalRun primitives from RFC-0016 rather than implementing a second event engine.
- [ ] Tasks with external write effects, newly requested integration scopes, sensitive data access, or budget escalation require explicit approval before activation.
- [ ] Users can pause, resume, run now, edit, duplicate, and delete a task from both chat and the task-management UI.
- [ ] UI shows next run/trigger, last outcome, effective agent/runtime policy, budget, and whether the task may perform external side effects.
- [ ] Failed runs follow bounded retry/backoff policy and cannot create unbounded spend or duplicate external side effects.
- [ ] A task can optionally save outputs to a ProjectWorkspace or Artifact rather than only posting a chat message.
- [ ] Audit records preserve the original user instruction, parsed structured definition, approvals, subsequent edits, and each execution result.
- [ ] Tests cover timezone/DST handling, recurrence parsing, ambiguous schedule handling, pause/resume, side-effect approval, duplicate prevention, and task editing.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal code changes, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/scheduler/...`, task-definition schemas/routes, parser/validation service |
| Frontend | chat task preview and task-management editor |
| Tests | schedule parsing, lifecycle, approval, execution tests |
| Docs | task authoring and structured schedule specification |

## Out of scope

Replacing RFC-0016 event subscriptions/GoalRuns, inventing a second scheduler, or allowing arbitrary natural-language instructions to bypass capability/approval policy.

## Notes

Inspiration: Merlin Tasks and similar chat-native scheduling interfaces. Discovery date: 2026-08-31. Recommendation: **ADAPT** the low-friction authoring UX while keeping Jarvis's scheduler, policy, audit, and cancellation model authoritative.
