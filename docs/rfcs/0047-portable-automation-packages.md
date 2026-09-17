# RFC-0047: Portable automation packages

**Status:** accepted  
**Queue item:** P4 — workflow automation / portability  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-09-03

## Problem

Jarvis has scheduled/event-triggered workflows and natural-language task authoring, but it does not yet define a portable, reviewable automation package that can be versioned in Git and combine declarative workflow configuration with deterministic helper code. OpenHands' August releases added Automation Git Sync plus script bundles for polling, deduplication, state management, and fixed API calls. OpenHands Automation 1.13.0 (2026-09-16) additionally allows an automation to select an agent profile for delegated work, demonstrating a useful separation between the portable workflow definition and the persistent specialist identity that executes its judgment-heavy steps. Without equivalent abstractions, Jarvis automations risk becoming opaque prompt blobs, difficult to review, migrate, test, reproduce, or consistently execute with the intended specialist memory and policy.

## Decision

Introduce a versioned `AutomationPackage` format that separates deterministic mechanics from agent judgment.

An automation package contains a manifest, trigger definition, input schema, workflow/goal definition, required capabilities, provider/integration requirements, optional deterministic script bundle, persistent state schema, verification rules, policy requirements, and package provenance/version metadata.

An installed automation MAY bind judgment-heavy/delegated steps to a selectable Jarvis `AgentProfile`. The package stores a symbolic profile requirement or binding slot rather than embedding agent memory or machine-specific IDs. Installation resolves that slot to an eligible local Agent Profile. The selected profile contributes its specialist instructions, memory, model/runtime preferences, and lower policy ceilings, but it cannot expand the automation's declared capabilities, budget, privacy class, workspace scope, or autonomy. Effective authority is the intersection of automation policy, AgentProfile policy, workspace/owner policy, and runtime/node restrictions. A missing, disabled, quarantined, or ineligible bound profile fails closed or follows an explicitly configured compatible fallback; Jarvis must never silently substitute a more privileged profile.

Packages are exportable/importable as plain files and optionally syncable to a user-controlled Git repository. Git is a portability/review layer, not the runtime source of truth: Jarvis stores the active resolved package revision and only applies changes through validation and an explicit import/update flow.

Deterministic code should handle fixed operations such as polling, pagination, deduplication, normalization, state transitions, stable API calls, and data validation where practical. Agents handle interpretation, planning, synthesis, exception reasoning, and other judgment-heavy steps. Script execution uses the normal sandbox/capability model and may not bypass workflow policy.

Imported or updated packages are disabled until Jarvis displays a review diff covering triggers, prompts/instructions, capabilities, integration requirements, scripts, state migrations, agent-profile binding requirements, spending/external-action permissions, and verification behavior. Secret values are never committed to package repositories; manifests reference secret/integration bindings symbolically.

## Acceptance criteria

- [ ] Define a versioned `AutomationPackageManifest` with package ID/version, trigger, input schema, workflow/goal, required capabilities, integrations/providers, optional scripts, state schema version, verification rules, provenance, and optional symbolic AgentProfile binding requirements.
- [ ] Automations can be exported/imported without secrets, machine-specific credentials, transient run state, or embedded AgentProfile memory.
- [ ] Installation can bind an automation's delegated/judgment-heavy work to an eligible persistent `AgentProfile`, and the resolved binding is visible in UI/API and run provenance.
- [ ] Effective authority for bound-profile execution is the intersection of automation, AgentProfile, workspace/owner, and runtime/node policy; selecting a profile can never expand automation authority.
- [ ] Missing, disabled, quarantined, or policy-incompatible bound profiles fail closed or use only an explicitly configured compatible fallback; no silent privilege-increasing substitution is allowed.
- [ ] Changing an AgentProfile binding is audited and requires the same review/authorization class as changing the automation's execution identity; in-flight runs retain their resolved profile/version snapshot.
- [ ] Optional Git sync records package definitions and script bundles in a user-controlled repository with stable paths and revision metadata.
- [ ] Git synchronization never silently activates remote changes; fetched changes require validation and normal update policy before becoming active.
- [ ] Imported/new packages default to disabled until reviewed when they contain executable scripts, external writes, financial actions, credentials/integration changes, newly expanded capabilities, or privileged profile requirements.
- [ ] Update review shows a semantic diff for trigger, schedule/event source, instructions, capabilities, scripts, integration bindings, AgentProfile requirements/bindings, state migration, and verification changes.
- [ ] Deterministic scripts execute through a bounded runner with declared inputs/outputs, time/resource limits, network/tool capability restrictions, and captured logs/results.
- [ ] Package scripts cannot directly access secret stores; they receive only explicitly bound scoped credentials/tokens through approved adapters.
- [ ] The runtime supports stable idempotency/deduplication keys so repeated polling/webhook delivery does not duplicate side effects.
- [ ] Persistent package state has schema/version metadata and recoverable migration/rollback behavior.
- [ ] Package run history records resolved package version/revision and resolved AgentProfile identity/version so historical execution is reproducible/auditable.
- [ ] Natural-language automation authoring can generate a draft package, but generated executable scripts must pass sandbox validation/tests before activation.
- [ ] Provide at least one reference package where deterministic code handles polling/deduplication and a bound specialist AgentProfile performs interpretation/synthesis.
- [ ] Tests cover profile binding, profile removal/quarantine, incompatible-policy rejection, explicit fallback, no privilege expansion, and binding changes during an in-flight run.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | workflow/automation package schemas, AgentProfile binding resolver, import/export, Git sync service, deterministic runner, state migrations |
| Frontend | package review/diff/import/export/version UI, AgentProfile selector/binding health |
| Tests | package round-trip, profile binding/policy intersection, Git sync, script sandbox, idempotency, migration/rollback |
| Docs | automation package format and authoring guide |

## Out of scope

A public automation marketplace; automatically trusting Git repository changes; replacing Jarvis workflows/GoalRuns; embedding secrets or AgentProfile memory in package files; allowing script bundles unrestricted host execution; allowing automation packages to create or escalate AgentProfile authority.

## Notes

Sources: https://hub.openhands.dev/blog/new-in-agent-canvas-august-2026 (published 2026-09-02), especially Automation Git Sync and automation script bundles; https://github.com/OpenHands/automation/releases/tag/1.13.0 (released 2026-09-16), adding selection of an agent profile for delegated automation work.  
Discovery dates: 2026-09-03 and 2026-09-17.  
Recommendation: **ADAPT STRONGLY**.  
Jarvis is adapting portable/versioned automations, the split between deterministic mechanics and agent judgment, and explicit selection of a persistent specialist identity for delegated work. The runtime remains Jarvis-native, policy-bounded, and local-first rather than copying OpenHands automation internals. The profile binding is deliberately symbolic/portable and cannot grant authority beyond the automation's own policy.