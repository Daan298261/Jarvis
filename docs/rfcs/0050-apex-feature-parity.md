# RFC 0050 — APEX Feature Parity

Status: Proposed / implementation started
Owner: Jarvis
Scope: Product-wide
Reference implementation: `RubenM1990/APEX-UI` (MIT, UI only)

## 1. Purpose

Use the publicly documented APEX product surface as a benchmark for Jarvis UX and capability completeness, while preserving Jarvis's stronger local-first, swarm, model-routing, security and extensibility architecture.

This RFC is intentionally epic-level. Each epic is expected to be decomposed into PBIs with acceptance tests, backend contracts, UI states, telemetry and migration requirements before implementation.

Feature parity means equivalent user outcome, not cloning APEX internals. Jarvis may implement a capability differently where its architecture provides a better local-first or multi-node solution.

## 2. UI foundation decision

Jarvis UI v3 will adopt and adapt the MIT-licensed APEX-UI visual language instead of recreating it from screenshots.

Implementation rules:

- Preserve the APEX-UI MIT copyright/permission notice for copied or substantially derived code.
- Preserve the upstream 21st.dev attribution chain recorded by APEX-UI.
- Do not use the APEX product name or Reznikov Engineering branding as Jarvis branding.
- Port into Jarvis's existing Vite/React/Tauri application rather than adding a second Next.js application.
- Connect UI states to real Jarvis backend state. Demo-only/random state machines are not acceptable as final implementations.
- Existing Jarvis pages remain reachable while capabilities are progressively moved into Command Deck workspaces.
- Classic UI remains available as a fallback during migration.

The first implementation slice ports the APEX SVG orb, command-deck/reasoning-web concept, sparse cyan/gold visual system, and specialist navigation into the existing HUD shell.

## 3. Parity definition

An epic is not considered at parity merely because a screen exists. A capability is parity-complete only when:

1. the user can invoke it from the Command Deck or an appropriate workspace;
2. it operates against real records/tools, not placeholder data;
3. state survives restart where persistence is implied;
4. progress and failures are visible;
5. consequential writes follow the configured approval policy;
6. claims based on external/record data retain provenance where feasible;
7. the capability works in desktop mode and degrades appropriately on web/mobile surfaces;
8. automated tests cover the critical success and failure paths.

## 4. Epics

### EPIC APEX-01 — One core, specialist system

Goal: Present Jarvis as one coherent intelligence with specialist capabilities rather than unrelated pages.

Required outcomes:

- One command surface routes work to specialists automatically.
- Specialist roster is visible and inspectable.
- Specialist state, current work, assigned model and execution node can be inspected.
- Specialists can be invoked directly when desired.
- Existing Agent Profiles, Packs, model routing, delegation and swarm roles become the implementation substrate.
- The UI must distinguish role/persona, model, node and tool capability rather than conflating them.

Benchmark specialist domains include strategy, chief-of-staff/orchestration, research, memory, analytics, drive/files, sales, social, CRM, editing, operations, finance, calendar, email, engineering, design and development.

### EPIC APEX-02 — Chief of Staff / proactive orchestrator

Goal: Jarvis actively runs the user's operational loop instead of waiting for chat prompts.

Required outcomes:

- Morning brief showing what needs attention before the user asks.
- Periodic sentinel checks for configured business/system domains.
- Milestone detection and next-goal proposals.
- Pace calculations against goals using deterministic math.
- Weekly delta analysis.
- Configurable weekly/Sunday review with pace, forecast and recommended move per goal.
- Needs-you queue with mobile/desktop notification.
- Existing scheduler, Away Mode, Decision Inbox, proactivity and task systems should be reused.

### EPIC APEX-03 — Natural voice interaction

Goal: Voice behaves like a conversational interface, not push-to-talk transcription glued to chat.

Required outcomes:

- End-of-turn detection tolerates normal mid-sentence pauses.
- Uncertain transcription causes clarification rather than confident guessing.
- Optional speaker recognition/voice identity policies.
- Sensitive-domain output can be restricted to an authenticated speaker/device.
- Personality controls for warmth, directness, sarcasm/roughness and pushback within policy bounds.
- Goals/strategies can be held as durable objects and Jarvis reports material changes to them.
- Integrate with existing voice latency/talkback RFCs.

### EPIC APEX-04 — Single source of truth

Goal: Every surface reads from canonical Jarvis state.

Required outcomes:

- Canonical records for tasks, goals, projects, contacts/leads, financial facts and other enabled domains.
- Same value appears consistently across Command Deck, workspace, mobile and reports.
- Live snapshot APIs for relevant domain KPIs.
- Long-term memory for facts, decisions and preferences with provenance and correction paths.
- Jarvis can report its own version, runtime state, recent errors, guard/verification results and active configuration.
- Record-grounded answers should prefer source data over model recollection.

### EPIC APEX-05 — Goals, missions and execution plans

Goal: Add a durable abstraction above individual tasks.

Mission object should minimally support:

- goal/outcome;
- constraints;
- channels/resources;
- plan;
- executable child tasks;
- owners/agents;
- status and milestones;
- evidence and results;
- review cadence;
- cost/resource budget.

Jarvis must be able to turn a strategy discussion into a Mission and then execute/monitor the task graph.

### EPIC APEX-06 — Self-evaluation and consultant board

Goal: Jarvis measures whether its own advice worked.

Required outcomes:

- Recommendations can be persisted with expected outcome and confidence.
- Outcome metrics can be attached later.
- Scheduled reviews compare recommendation vs result.
- Advice quality can be graded over time by domain/agent/model.
- Routing may use this historical performance signal.

### EPIC APEX-07 — Verification, epistemic state and trust

Goal: Make trust a first-class system property.

Required outcomes:

- Distinguish verified, inferred, unverified and could-not-verify states.
- Deterministic checks are used where code can establish truth.
- Source-backed claims retain citations/provenance.
- Jarvis may correct the user when records conflict with an assertion.
- News/current-event claims require freshness/source checks when relevant.
- Failed verification is visible and must not be silently converted into confidence.
- Verification state can be consumed by approval policies.

### EPIC APEX-08 — Approval and consequence policy

Goal: Draft freely; execute according to user-configured consequence levels.

Required outcomes:

- External actions have explicit side-effect classes.
- Default approval policy can differ for send, post, purchase/payment, delete, account/security change and other consequential writes.
- Existing user preference for broad auto-approval can coexist with mandatory or configurable gates for high-impact classes.
- Decision Inbox is the common review surface.
- Approval request shows exact intended action and payload where practical.

### EPIC APEX-09 — Capability honesty and self-development backlog

Goal: Jarvis knows what it can actually do.

Required outcomes:

- Tools/workspaces expose capability availability and health.
- UI states include available, unavailable, degraded and not-built-yet.
- Failed attempts caused by missing capability are classified separately from task failures.
- Jarvis logs capability gaps.
- Gaps can be converted into proposed backlog items/RFCs/PBIs.
- Self-development workflow can prioritize accepted gaps.

### EPIC APEX-10 — Command Deck + dedicated workspaces

Goal: One global command surface with domain-scoped workspaces.

Required outcomes:

- Command Deck is the default HUD home.
- Specialist/workspace graph is navigable.
- Workspaces have scoped state and saved conversations.
- A conversation can intentionally reference another workspace when permission/context policy allows it.
- Global command can route into a workspace and return results without forcing manual navigation.
- Multi-monitor panel casting is designed as a first-class extension of the workspace model.

### EPIC APEX-11 — Multi-surface continuity

Goal: One Jarvis brain across desktop/web/mobile/chat/voice surfaces.

Target surfaces:

- desktop/Tauri;
- web;
- mobile companion;
- voice;
- optional messaging adapters such as Telegram where users configure them.

Required outcomes:

- Shared canonical state.
- Surface-specific authentication and capability limits.
- Handoff/continuation of active tasks.
- Notifications deep-link to the relevant Mission/task/approval.

### EPIC APEX-12 — Local computer bridge and multimodal workspace

Goal: Jarvis can work directly with the user's computer through an explicit local bridge.

Required outcomes:

- Read/write files and folders according to policy.
- Run approved commands/tools.
- Attach files, PDFs, folders, images, screenshots and camera input.
- Google Drive and other connected sources appear as file/workspace sources.
- Screen/computer-use actions integrate with visible task progress.
- Multi-screen cockpit can detach/cast selected panels to another display/window.

Existing desktop bridge, filesystem, computer-use, Office and connector tools should be reused.

### EPIC APEX-13 — Email identity and inbox operations

Goal: Jarvis can act as an email-aware operational agent.

Required outcomes:

- Triage connected personal/business inboxes.
- Convert actionable mail into structured cards/tasks.
- Draft replies using relevant context.
- Optional dedicated Jarvis mailbox/identity.
- Process its own inbound operational mail.
- Safe verification-link handling with domain/risk validation.
- Sending respects approval policy.

### EPIC APEX-14 — Calendar, reminders and task guarantees

Goal: Scheduling promises must become deterministic scheduled objects.

Required outcomes:

- Read/create calendar events.
- Find free slots across selected calendars.
- User selects slot before booking when required.
- Natural-language reminders compile into durable scheduler jobs/events.
- Done/snooze interaction.
- Phone/desktop notification delivery.
- Task board acts as a go/no-go and review surface.
- Never rely on an LLM remembering to remind later.

### EPIC APEX-15 — CRM, orders and finance

Goal: Provide an operational business workspace grounded in real records.

Required outcomes:

- CRM leads/contacts/stages.
- Evidence brief per lead.
- Order state machine, configurable by business.
- Financial analysis anchored in imported/connected bills and records.
- Prospect research and individualized opener drafts.
- Human/configurable gate before outreach.
- Campaign budgets and variants.
- AI/runtime cost accounting by task/reply/mission where measurable.

### EPIC APEX-16 — Social media and content operations

Goal: Run a measurable content loop rather than one-off generation.

Required outcomes:

- Draft in user/brand voice.
- Learn from accepted edits through an explicit preference/style system.
- Publish to configured social channels after policy checks.
- Comment inbox and reply drafts.
- Fact-checked, approval-gated newsletters.
- Content calendar with auto-drafts for upcoming slots.
- "What to post next" recommendations grounded in owned performance data.
- Configurable north-star KPIs.
- Scheduled trend scan producing concrete ideas.
- Post/reel performance analysis explaining likely contributors without presenting correlation as certainty.

### EPIC APEX-17 — Creative production studio

Goal: Generate finished artifacts, not merely prompts.

Required outcomes:

- Brand-safe graphics with deterministic text/layout where exact copy matters.
- Photorealistic image generation and describe-to-edit.
- Short video with audio and still-image animation.
- 9:16 story/reel layout with exact preview before publication.
- Slide decks.
- Spreadsheets.
- Deep research briefs with sources.
- Quotes/proposals with deterministic line-item math and totals.

### EPIC APEX-18 — Engineering / workshop workspace

Goal: Add a maker/engineering specialist workspace.

Required outcomes:

- 3D printing guidance.
- Laser engraving guidance.
- DFM analysis for supported manufacturing processes.
- Materials and tolerances library/calculation tools.
- Engineering calculations run in deterministic computation tools, not guessed by the LLM.
- CAD/3D viewing as a future workspace capability.
- AR/gesture control treated as an optional future surface, not a parity blocker for the core release.
- Inventory integration and configurable auto-decrement from recorded sales/orders.

### EPIC APEX-19 — Competitive intelligence and screenshot-to-record

Goal: Turn external observations into durable intelligence.

Required outcomes:

- Deep reads of competitors/suppliers/markets.
- Source snapshots and timestamps.
- Screenshot/image/PDF ingestion into structured cards.
- Entity deduplication.
- Change monitoring.
- Mission/strategy workspace can reference intelligence records directly.

### EPIC APEX-20 — Self-engineering

Goal: Progress from operating Jarvis to safely improving Jarvis.

Required outcomes:

- Capability gaps can produce engineering proposals.
- Accepted proposal becomes RFC/PBIs/task graph.
- Coding agents work in isolated environments/branches.
- Verification agent reviews changes.
- Tests/build checks required before merge eligibility.
- Runtime can explain what changed and why.
- No silent self-modification of the running stable build.

This epic should build on Jarvis's existing self-development, coding-worker and verification architecture rather than creating a parallel system.

## 5. Cross-cutting Jarvis advantages to preserve

Parity must not regress features where Jarvis's architecture is intended to exceed the benchmark:

- local-only and local-first operation;
- selectable privacy/cost/result routing modes;
- swarm execution across heterogeneous machines;
- forced/preferred device roles;
- leader / orchestrator / senior worker / junior worker distinctions;
- host resource caps;
- replaceable model packs and specialist routing;
- explicit security/blue-team capabilities;
- offline operation and licensing model;
- persistent worker environments and isolated coding workers.

## 6. PBI distillation process

For each epic:

1. Inventory existing Jarvis capability and API coverage.
2. Mark each outcome: `done`, `partial`, `missing`, `replace`, or `research`.
3. Write a minimal vertical-slice PBI that reaches a real user-visible outcome.
4. Add contract/API PBIs only where the vertical slice requires them.
5. Add migration/state-model work.
6. Add automated acceptance tests.
7. Add UX states for empty/loading/running/success/degraded/failure/approval-required.
8. Add observability and cost/performance measures.
9. Only then schedule implementation.

Recommended initial PBI sequence:

- PBI 1: APEX-UI attribution + Jarvis Command Deck visual foundation.
- PBI 2: Replace static specialist nodes with live specialist/runtime state.
- PBI 3: Workspace model and scoped chat persistence.
- PBI 4: Mission domain object and task graph.
- PBI 5: Needs-you queue consolidation and notification deep links.
- PBI 6: Verification state/provenance contract.
- PBI 7: Deterministic reminder compilation.
- PBI 8: Capability registry + not-built/degraded states.
- PBI 9: Capability-gap logging to self-development backlog.
- PBI 10: Per-task/model/node cost accounting.

## 7. Current implementation slice

Branch `feat/apex-ui-foundation` starts PBI 1 by:

- preserving the upstream MIT license and credits;
- porting/adapting the APEX SVG orb to Jarvis;
- adding a cyan/gold sparse Command Deck visual system;
- rendering 17 Jarvis specialist/workspace nodes around one core;
- linking those nodes to existing real Jarvis routes;
- keeping the existing Jarvis chat/task engine as the command input;
- driving the orb state from actual task/chat mood state;
- keeping the classic UI available during migration.

Static specialist-node availability in this first slice is navigation only. It must not be interpreted as runtime-health parity; live specialist state is explicitly PBI 2.

## 8. Source gap

The supplied APEX capability reference did not include slide 14/20. No capability is inferred for that slide. If the missing slide is later recovered, add or amend an epic based on its actual contents rather than guessing.
