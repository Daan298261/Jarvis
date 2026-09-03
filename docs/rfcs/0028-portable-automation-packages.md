# RFC-0028: Portable automation packages

**Status:** accepted  
**Queue item:** P4 — workflow automation / portability  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-09-03

## Problem

Jarvis has scheduled/event-triggered workflows and natural-language task authoring, but it does not yet define a portable, reviewable automation package that can be versioned in Git and combine declarative workflow configuration with deterministic helper code. OpenHands' August releases added Automation Git Sync plus script bundles for polling, deduplication, state management, and fixed API calls. Without an equivalent abstraction, Jarvis automations risk becoming opaque prompt blobs, difficult to review, migrate, test, or reproduce across installations.

## Decision

Introduce a versioned `AutomationPackage` format that separates deterministic mechanics from agent judgment.

An automation package contains a manifest, trigger definition, input schema, workflow/goal definition, required capabilities, provider/integration requirements, optional deterministic script bundle, persistent state schema, verification rules, policy requirements, and package provenance/version metadata.

Packages are exportable/importable as plain files and optionally syncable to a user-controlled Git repository. Git is a portability/review layer, not the runtime source of truth: Jarvis stores the active resolved package revision and only applies changes through validation and an explicit import/update flow.

Deterministic code should handle fixed operations such as polling, pagination, deduplication, normalization, state transitions, stable API calls, and data validation where practical. Agents handle interpretation, planning, synthesis, exception reasoning, and other judgment-heavy steps. Script execution uses the normal sandbox/capability model and may not bypass workflow policy.

Imported or updated packages are disabled until Jarvis displays a review diff covering triggers, prompts/instructions, capabilities, integration requirements, scripts, state migrations, spending/external-action permissions, and verification behavior. Secret values are never committed to package repositories; manifests reference secret/integration bindings symbolically.

## Acceptance criteria

- [ ] Define a versioned `AutomationPackageManifest` with package ID/version, trigger, input schema, workflow/goal, required capabilities, integrations/providers, optional scripts, state schema version, verification rules, and provenance.
- [ ] Automations can be exported/imported without secrets, machine-specific credentials, or transient run state.
- [ ] Optional Git sync records package definitions and script bundles in a user-controlled repository with stable paths and revision metadata.
- [ ] Git synchronization never silently activates remote changes; fetched changes require validation and normal update policy before becoming active.
- [ ] Imported/new packages default to disabled until reviewed when they contain executable scripts, external writes, financial actions, credentials/integration changes, or newly expanded capabilities.
- [ ] Update review shows a semantic diff for trigger, schedule/event source, instructions, capabilities, scripts, integration bindings, state migration, and verification changes.
- [ ] Deterministic scripts execute through a bounded runner with declared inputs/outputs, time/resource limits, network/tool capability restrictions, and captured logs/results.
- [ ] Package scripts cannot directly access secret stores; they receive only explicitly bound scoped credentials/tokens through approved adapters.
- [ ] The runtime supports stable idempotency/deduplication keys so repeated polling/webhook delivery does not duplicate side effects.
- [ ] Persistent package state has schema/version metadata and recoverable migration/rollback behavior.
- [ ] Package run history records resolved package version/revision so any historical execution is reproducible/auditable.
- [ ] Natural-language automation authoring can generate a draft package, but generated executable scripts must pass sandbox validation/tests before activation.
- [ ] Provide at least one reference package where deterministic code handles polling/deduplication and an agent performs interpretation/synthesis.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | workflow/automation package schemas, import/export, Git sync service, deterministic runner, state migrations |
| Frontend | package review/diff/import/export/version UI |
| Tests | package round-trip, Git sync, script sandbox, idempotency, migration/rollback |
| Docs | automation package format and authoring guide |

## Out of scope

A public automation marketplace; automatically trusting Git repository changes; replacing Jarvis workflows/GoalRuns; embedding secrets in package files; allowing script bundles unrestricted host execution.

## Notes

Source: https://hub.openhands.dev/blog/new-in-agent-canvas-august-2026 (published 2026-09-02), especially Automation Git Sync and automation script bundles.  
Discovery date: 2026-09-03  
Recommendation: ADAPT STRONGLY.  
Jarvis is adapting portable/versioned automations and the split between deterministic mechanics and agent judgment. The runtime remains Jarvis-native, policy-bounded, and local-first rather than copying OpenHands automation internals.
