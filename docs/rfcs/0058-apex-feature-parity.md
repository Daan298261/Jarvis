# RFC-0058: Apex feature parity umbrella

**Status:** draft / umbrella RFC  
**Queue item:** competitor capability parity — distill into child RFCs and PBIs before implementation  
**Author:** ChatGPT synthesis from user-provided Apex capability slides  
**Date:** 2026-09-08

## Problem

Jarvis already has broad architectural ambitions, but its current capability and UX roadmap is fragmented across specialist-agent, voice, automation, workspace, UI, artifact, security and swarm RFCs. The user supplied a 20-slide Reznikov Engineering Apex overview as a concrete benchmark for what a polished personal AI operating layer should feel like in practice.

The goal of this RFC is **feature parity at the capability level**, not product cloning. It records every observed Apex capability from the supplied material as epics, maps obvious overlap with existing Jarvis specifications, and provides a parent backlog from which smaller implementation RFCs / PBIs can be created.

This document intentionally does **not** attempt to design every subsystem in full. Existing Jarvis RFCs remain authoritative where they already cover a concern.

## Product target

Jarvis should be able to operate as a persistent AI chief-of-staff / agent operating layer that:

- coordinates specialist agents through one core;
- knows the user's business/projects from real records rather than only conversational context;
- proactively detects work requiring attention;
- produces useful artifacts and executes workflows across local and connected systems;
- uses deterministic subsystems where reliability matters;
- makes uncertainty, evidence, approval and system state visible;
- is reachable from multiple surfaces while preserving one brain and one source of truth;
- presents all of this through a clean, high-signal UI rather than exposing backend complexity.

Feature parity is a **minimum benchmark**. Jarvis may exceed Apex through its local-first execution, model routing, specialist packs, swarm architecture, security modules and owner-controlled autonomy.

## Source coverage

Observed slide coverage from the supplied screenshots:

- captured: 1–13 and 15–20;
- slide 10 was supplied twice;
- slide 14 was not present in the supplied screenshots and remains an explicit capture gap.

No requirement in this RFC should be represented as an Apex capability unless it was visible in the supplied material. Any future discovery of slide 14 should be appended here before PBI decomposition is considered complete.

---

# Epic APEX-01 — One core, persistent specialist organization

## Observed benchmark

Apex presents one core with **17 active specialists**, grouped as:

- Strategy: Strategist, Chief of Staff, Researcher
- Knowledge: Memory, Analytics, Drive
- Growth: Sales, Social, CRM, Editor
- Operations: Ops, Finance, Calendar, Email
- Build: Engineering, Design, Developer

The product framing is "one engineer, the output of a whole company" and "my AI chief of staff".

## Jarvis parity target

Jarvis shall expose a persistent organization of named specialist agents behind one orchestrator rather than making each capability feel like an unrelated tool.

Minimum parity outcomes:

- persistent specialist identities and responsibilities;
- specialists grouped into domains/departments;
- specialists can be active concurrently subject to resource policy;
- one top-level orchestrator / chief-of-staff experience;
- user can inspect which specialist owns a task;
- delegation does not fragment memory or system state;
- specialists remain independent from the physical worker/model executing them.

## Existing Jarvis alignment

Strong specification overlap already exists in `JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md`, RFC-0006 hierarchical task workers, RFC-0007 domain workspace packs, and RFC-0048 specialist model-stack routing. Child PBIs should reuse these contracts rather than create a second agent system.

---

# Epic APEX-02 — Natural realtime voice, speaker identity and personality controls

## Observed benchmark

Apex voice behavior includes:

1. waits through a mid-sentence pause and does not cut the speaker off;
2. asks when it is not sure it heard correctly instead of guessing;
3. knows the user's voice, with private topics such as money remaining private to that user;
4. exposes personality dials for sarcasm, roughness, warmth and pushback;
5. can hold a strategy such as "your goal is X" and later report how the strategy changed.

## Jarvis parity target

- interruption-resistant end-of-turn detection;
- explicit low-confidence ASR clarification path;
- local speaker recognition / identity gating for sensitive work where enabled;
- per-user/per-agent personality control surface;
- persistent goal/strategy state available in voice sessions;
- voice sessions preserve the same canonical memory/task state as desktop/mobile/web;
- privacy decisions are enforced by policy, not just prompt text.

## Existing Jarvis alignment

Relevant existing work includes RFC-0033 reliable realtime voice I/O, RFC-0035 tiny-model voice command front-end, RFC-0036 interaction latency/streaming talkback, RFC-0054 local identity recognition, RFC-0055 social commentary/persona policy and RFC-0056 expressive butler voice runtime.

---

# Epic APEX-03 — Canonical source of truth and business/project awareness

## Observed benchmark

Apex claims:

1. one source of truth — every screen shows the same number;
2. live snapshot of audience, revenue, pipeline and projects;
3. long-term memory for facts, decisions and preferences;
4. knowledge of its own system version, errors and guard results;
5. answers from real records rather than intuition / "vibes".

## Jarvis parity target

Create a canonical data/state layer that separates factual records from model-generated interpretation.

Required parity capabilities:

- common entity and metric store shared by every UI surface;
- normalized connectors for business/project records;
- timestamped live snapshots with freshness metadata;
- long-term memory for facts, decisions and user preferences;
- provenance on factual answers when source records exist;
- visible stale/unknown/unavailable state instead of fabricated values;
- self-observability data: Jarvis version, component health, errors, policy/guard/verifier results;
- consistent values across command deck, workspaces, reports and voice.

## Existing Jarvis alignment

Specification overlap exists in RFC-0011 memory/context repository consolidation, RFC-0020 project knowledge workspaces, RFC-0028 off-context agent journal and the Shared Brain / Goals-KPI concepts in `JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md`.

---

# Epic APEX-04 — Proactive sentinel, briefs, pace tracking and needs-you queue

## Observed benchmark

Apex proactively provides:

1. morning brief — what needs the user before they ask;
2. sentinel every four hours for stock, cold leads and overdue tasks;
3. milestone detection followed by a proposed next goal;
4. pace math that flags a slipping goal and shows per-day numbers;
5. weekly analyst diff versus last week;
6. Sunday review with pace, prediction and one move per goal;
7. reel monitor explaining under/over-performance;
8. "needs-you" queue plus phone ping.

## Jarvis parity target

- recurring sentinel framework driven by schedules and events;
- Morning Brief as a first-class product surface;
- configurable monitoring intervals per workspace/metric;
- goal velocity / required-daily-pace calculations;
- milestone and regression detection;
- previous-period comparisons;
- forecast/prediction layer with evidence and confidence;
- one recommended next action per goal where useful;
- decision / needs-user queue with mobile notification;
- no duplicate alert spam for unchanged conditions;
- user-configurable quiet hours and escalation rules.

## Existing Jarvis alignment

Relevant existing work: RFC-0014 persistence/proactivity controls, RFC-0016 event subscriptions and goal lifecycle, Decision Inbox / Away Mode / Morning Brief requirements in `JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md`.

---

# Epic APEX-05 — Social media operating system

## Observed benchmark

Apex social capabilities include:

1. drafts in the user's voice and learns from edits;
2. posting to Instagram, Facebook and LinkedIn on explicit user click;
3. comment inbox with replies drafted in the user's register;
4. subscriber newsletter that is fact-checked and approval-gated;
5. content calendar with upcoming slots auto-drafted;
6. "what to post next" recommendations cited from the user's own numbers;
7. north-star KPI of followers per 10k views;
8. weekly trend scan producing three concrete post ideas.

## Jarvis parity target

- social account connector abstraction;
- per-brand/per-person voice profile learned from accepted edits;
- post draft -> preview -> approve -> publish workflow;
- unified comment/reply inbox;
- newsletter drafting with fact verification and approval gate;
- content calendar backed by real task/schedule objects;
- auto-drafting for empty upcoming slots;
- recommendations tied to account metrics and source evidence;
- configurable north-star and supporting KPIs;
- recurring trend intelligence -> concrete ideas;
- campaign/post performance feedback loop into future drafting.

## Existing Jarvis alignment

The Social Manager / Ad Studio concepts already exist at pack level in `JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md`, but this epic requires a dedicated implementation RFC before parity can be claimed.

---

# Epic APEX-06 — Artifact and media production layer

## Observed benchmark

Apex can make:

1. branded graphics as code with exact text and exact brand;
2. photoreal images plus describe-to-edit;
3. short videos with sound or animation from a still;
4. stories auto-fit to 9:16 with exact preview first;
5. slide decks and spreadsheets;
6. deep research briefs with sources included;
7. client quotes with line items and automatic totals.

## Jarvis parity target

- structured brand-kit memory and rendering constraints;
- graphics generated from deterministic templates/code where exact text/layout matters;
- image generation and natural-language image editing;
- short-video generation/animation workflow with sound support;
- target-format adaptation with exact preview before publish/export;
- native slide and spreadsheet artifact generation;
- sourced research brief artifact type;
- quote/estimate artifact with deterministic arithmetic and line-item schema;
- output validation before delivery;
- all artifacts stored as first-class workspace objects with version history.

## Existing Jarvis alignment

RFC-0021 artifact crafts/output layer is the primary existing specification anchor. This epic should extend that output layer rather than create parallel generators.

---

# Epic APEX-07 — Jarvis-owned email identity and triage inbox

## Observed benchmark

Apex:

1. sends from its own address with user confirmation for every send;
2. has its own inbox, sorts mail and can follow verification links itself;
3. triages the user's Gmail and turns human mail into a card.

## Jarvis parity target

- optional Jarvis-owned mailbox identity;
- inbound mail ingestion and classification;
- outbound drafts always routed through configured authority policy;
- verification-link workflow executed through controlled browser/tool actions;
- external-email content converted into structured task/contact/opportunity/decision cards;
- duplicate/thread-aware triage;
- attachment extraction into workspace context;
- audit trail connecting original message -> card -> action -> response;
- phishing/suspicious-link policy checks before automated interaction.

## Existing Jarvis alignment

Email authority and integration concepts already exist in Agent Profiles / Decision Inbox requirements. A dedicated mailbox/triage RFC is still required.

---

# Epic APEX-08 — Calendar, reminders and deterministic commitments

## Observed benchmark

Apex:

1. reads and creates on multiple calendars;
2. converts "remind me" into a real event guaranteed in code;
3. provides personal reminders with phone ping, done and snooze;
4. has a task board used as an approval/go gate and self-grades drafts;
5. finds free slots and books the one selected by the user.

## Jarvis parity target

- calendar connector supporting multiple calendars;
- natural-language reminder requests become durable scheduled objects, not LLM promises;
- delivery acknowledgement, done and snooze state;
- mobile push for reminders;
- free/busy computation and candidate-slot presentation;
- user selection before booking when policy requires;
- task board integrates execution, verification and approvals;
- draft quality/self-grade metadata may inform presentation but cannot replace verifier policy;
- reminder/task persistence survives restart and node failover.

## Existing Jarvis alignment

Scheduler, recurring workflows, Decision Inbox and natural-language task authoring already exist conceptually; a parity PBI set should bind them into one user-facing calendar/reminder experience.

---

# Epic APEX-09 — CRM, orders, finance, prospecting and ads

## Observed benchmark

Apex includes:

1. full CRM with stages and evidence briefs per lead;
2. card orders end-to-end: paid -> design -> confirmation;
3. finance reads anchored to actual bills;
4. prospect hunting with a drafted opener for each lead, sent by the user;
5. complete ad campaigns covering audience, budget and three variants;
6. metering of its own running cost per reply.

## Jarvis parity target

- first-class CRM entities: lead, contact, company, opportunity, stage, evidence;
- configurable business workflow/state machines;
- order lifecycle and status transitions;
- finance ingestion grounded in real invoices/bills/transactions;
- prospect discovery + evidence brief + personalized draft;
- approval-gated outreach;
- campaign planner with audience, budget and variant artifacts;
- campaign outcome ingestion and optimization loop;
- per-task/per-response model/tool/API cost accounting;
- aggregate daily/monthly spend against budget policy.

## Existing Jarvis alignment

Sales, Finance and Ad Studio packs already exist as product concepts. RFC-0015 Amazon Ads integration and RFC-0022 provider budget/quota governance provide partial implementation anchors.

---

# Epic APEX-10 — Strategy, missions and consultant self-evaluation

## Observed benchmark

Apex strategy behavior includes:

1. strategy talks grounded in real numbers;
2. missions containing goal, channels, plan and executing tasks;
3. honest capability flags on every channel, including "not built yet";
4. consultant board graded weekly on its own advice;
5. competitive intelligence with deep reads and screenshot-to-card ingestion.

## Jarvis parity target

Introduce / standardize a **Mission** object above ordinary tasks:

```text
Mission
  goal
  success_metrics
  channels/resources
  strategy
  plan
  executable_tasks
  owners/agents
  dependencies
  evidence
  current_status
  outcome
  retrospective
```

Parity requirements:

- strategy references canonical metrics/data;
- mission decomposes into durable executable tasks;
- capability registry declares available/degraded/not-built/unavailable states;
- Jarvis may explicitly answer "not built yet" rather than simulate unsupported execution;
- weekly advice/outcome retrospective scores recommendations against actual results;
- competitive intelligence stores source provenance and extracted evidence;
- screenshot/image/PDF/web evidence can be converted into structured cards.

## Existing Jarvis alignment

RFC-0016 goal lifecycle, RFC-0020 project knowledge workspaces and the existing workflow/goal architecture are natural anchors. Mission should be a unifying object, not a competing scheduler.

---

# Epic APEX-11 — Workshop / physical engineering workspace

## Observed benchmark

Apex Workshop advertises:

1. 3D-printing and laser-engraving guidance;
2. DFM analysis for CNC and injection molding;
3. materials and tolerances;
4. calculations computed, never estimated;
5. AR CAD viewer with hand-gesture control;
6. live inventory where sales automatically decrement stock.

## Jarvis parity target

Create a Workshop specialist/domain pack supporting:

- 3D-printing design/review workflows;
- laser-engraving job preparation;
- DFM checklists and specialist analysis for CNC/injection molding;
- material/tolerance knowledge with cited or configured engineering rules;
- deterministic calculators for dimensions, tolerances, cost, feeds/speeds where applicable;
- CAD file attachment/preview pipeline;
- future AR/3D viewer extension contract;
- inventory entities and transaction ledger;
- automatic stock movement from verified sales/order events;
- no LLM arithmetic where a deterministic calculation can be used.

AR hand-gesture control is parity scope but should be decomposed as a later PBI after the core CAD/viewer layer exists.

## Existing Jarvis alignment

Domain/Specialist Pack architecture can host this cleanly. No dedicated Workshop RFC was identified during this umbrella pass.

---

# Epic APEX-12 — Local computer bridge, multimodal attachments and multi-screen cockpit

## Observed benchmark

Apex:

1. has a local bridge that reads, writes and runs on the PC;
2. creates folders on Drive or anywhere on disk;
3. can create/list/read from Google Drive and pull images;
4. has a multi-screen cockpit where panels can be cast to other monitors;
5. accepts files, PDFs, folders and camera input;
6. reads images, PDFs and screenshots shown to it.

## Jarvis parity target

- trusted local bridge for filesystem/process/tool execution;
- filesystem read/write/create with explicit permission scopes;
- local + connected-drive file abstraction;
- folder attachment as a scoped context source;
- native image/PDF/screenshot/camera ingestion;
- UI panels as independent window/view objects;
- move/cast/pin a workspace panel to another monitor;
- monitor topology and per-display persistence;
- capability remains available through one shared UI/business-logic path rather than OS-specific frontend forks;
- local bridge status and current action visible to the user.

## Existing Jarvis alignment

Trusted workspace/app extensions (RFC-0046), project workspaces (RFC-0020), the Tauri desktop architecture and existing tool framework provide partial foundations. Multi-monitor composable panels require a dedicated child RFC.

---

# Epic APEX-13 — Trust, deterministic verification and approval gates

## Observed benchmark

Apex states:

1. it drafts; the user approves;
2. it never sends, posts or pays on its own;
3. claims are checked in code;
4. truth over agreement — it corrects the user when evidence disagrees;
5. news is verified before dissemination;
6. "could not verify" is a valid answer;
7. it logs its own capability gaps and proposes next builds.

## Jarvis parity target

- policy-driven authority for external side effects;
- default approval gate for send/post/pay in the parity profile, while retaining Jarvis's broader configurable authority levels;
- deterministic validators wherever machine-checkable truth exists;
- verifier agents/tools for non-deterministic claims;
- evidence/confidence state attached to outputs;
- explicit `VERIFIED`, `UNVERIFIED`, `CONFLICTING`, `COULD_NOT_VERIFY` result states;
- factual disagreement is surfaced rather than suppressed to maintain conversational agreement;
- recent-news claims require source/time verification when web access is used;
- every failed/unsupported capability can create a structured capability-gap record;
- capability-gap records can feed the self-development backlog after deduplication and user policy.

## Existing Jarvis alignment

This aligns strongly with RFC-0026 execution/verifier observability, RFC-0027 semantic action firewall, RFC-0029 transactional durable execution, RFC-0031 reversibility-first action gates and the authority/Decision Inbox design in `JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md`.

Jarvis should **not** hard-code Apex's exact autonomy policy globally. The parity requirement is that the conservative profile exists and is reliable; Jarvis may allow more autonomous modes when the owner explicitly configures them.

---

# Epic APEX-14 — One brain across every surface

## Observed benchmark

Apex claims availability through:

- web;
- iPhone app;
- Telegram;
- voice.

It pairs this with:

- one command deck plus dedicated workspaces;
- saved chats with one scoped chat per domain;
- the principle: **one brain — every surface**.

## Jarvis parity target

- one backend/canonical state shared across desktop, web, mobile, messaging and voice;
- channel adapters do not become independent brains;
- Command Deck = global control/overview surface;
- Workspace = scoped domain/project operating surface;
- conversations may be scoped to workspace/domain while still linking to global user state according to policy;
- task/decision/notification state synchronized across surfaces;
- channel-specific UI may differ, but capabilities and permissions derive from the same backend contracts;
- reconnect/session handoff should preserve the active task/conversation where practical.

## Existing Jarvis alignment

RFC-0025 multi-channel agent gateway, RFC-0039 Android native communications client, RFC-0020 workspaces and the existing universal-GUI direction strongly overlap this epic.

---

# Epic APEX-15 — Command Deck and dedicated workspace information architecture

## Observed benchmark

The supplied Apex material repeatedly presents cards, domain workspaces, missions, needs-user items, inbox items and panels rather than treating chat as the entire product.

## Jarvis parity target

The main UI shall be organized around **objects and state**, with chat as one interaction mode.

Command Deck should eventually surface at minimum:

- current objectives/missions;
- running work;
- decisions / needs-user queue;
- alerts;
- recent outputs;
- key metrics;
- system health;
- agent/specialist status;
- spend/resource status;
- shortcuts into dedicated workspaces.

Dedicated workspaces should expose domain-relevant cards, data, files, chats, agents, workflows and metrics without overwhelming the global shell.

## Existing Jarvis alignment

Workspaces, Decision Inbox, modular Home Dashboard and live execution visualization are already specified. This epic is the umbrella parity requirement tying them into one coherent information architecture.

---

# Epic APEX-16 — UI benchmark: high-signal, sparse, polished operational interface

## Observed benchmark

The Apex presentation uses a highly consistent design language:

- near-black / navy backgrounds;
- cyan as a primary informational/status accent;
- orange as a secondary emphasis/accent;
- large condensed uppercase headings;
- generous whitespace;
- thin/subtle circuit-line motifs;
- soft bordered cards;
- small contextual metadata;
- limited visible chrome;
- strong hierarchy and very little visual clutter.

The important product lesson is not the exact colors/fonts. Apex makes a complex system appear simple by showing only the information required for the current context.

## Jarvis parity target

Jarvis UI v3 shall target comparable **clarity, perceived quality and operational legibility**, while retaining Jarvis's own identity and existing black/orange preference options.

Requirements:

- progressive disclosure rather than showing every subsystem at once;
- clean Command Deck with obvious hierarchy;
- card/object-first interaction for tasks, decisions, leads, alerts and missions;
- explicit but compact execution feedback so autonomous work never appears frozen;
- restrained motion tied to truthful system state;
- consistent spacing, typography, component radius/border/elevation tokens;
- domain workspaces share the same design system;
- multi-monitor layouts use the same panel primitives;
- phone/tablet/desktop layouts remain recognizable as one product;
- support theming/presentation modes without forking business logic;
- preserve accessibility and reduced-motion behavior.

Do **not** copy Apex's exact branding, proprietary assets or trade dress. Adapt the design principles.

## Existing Jarvis alignment

RFC-0050 UI v3 Presence Architecture is an important existing foundation, especially its shared-shell principle. A child RFC should focus specifically on the Command Deck/workspace component system and high-signal visual language.

---

# Epic APEX-17 — Self-measurement, outcome grading and visible operating cost

## Observed benchmark

Across the supplied slides Apex measures or grades:

- business KPIs;
- goal pace;
- weekly changes;
- content performance;
- its own advice;
- its own cost per reply.

## Jarvis parity target

- generic KPI registry with formulas, source and freshness;
- task/mission outcome metrics;
- before/after and period comparison primitives;
- recommendation -> outcome linkage;
- self-evaluation stored separately from the original recommendation;
- model/tool/API/token/compute cost per task and aggregate;
- ability to expose cost, latency, quality and success-rate together for routing/optimization;
- avoid meaningless self-scores that have no external result/evidence.

## Existing Jarvis alignment

Cost governor, model-router historical success rate, Goals/KPI engine and live execution metrics already exist in the long-term requirements. This epic requires a unified metrics model and UX.

---

# Epic APEX-18 — Capability registry and honest degraded/not-built states

## Observed benchmark

Apex explicitly advertises honest flags such as "not built yet" and treats "could not verify" as valid.

## Jarvis parity target

Every major feature/integration/tool should publish machine-readable capability state:

```text
AVAILABLE
DEGRADED
NEEDS_CONFIGURATION
NEEDS_PERMISSION
UNAVAILABLE_OFFLINE
NOT_INSTALLED
NOT_ENTITLED
NOT_BUILT
FAILED
```

The planner/router/UI must consult this registry before promising execution. A requested but unavailable capability should return a truthful explanation and, where useful, offer a supported fallback.

This registry should also power:

- setup diagnostics;
- Command Deck health state;
- agent planning constraints;
- gap logging;
- self-development proposals;
- support/debug reports.

---

# Epic APEX-19 — Capability-gap logging and self-engineering trajectory

## Observed benchmark

Apex says it logs its own gaps, proposes the next builds, and describes its direction as moving from running the business toward "the engineering itself".

## Jarvis parity target

- failed task can emit a normalized capability-gap event;
- gap includes requested outcome, missing capability, evidence/log link, frequency, impact and possible workaround;
- duplicate gaps are clustered;
- recurring/high-impact gaps can generate proposed backlog items;
- Jarvis may research a proposed implementation when permitted;
- self-development remains governed by the existing development workflow, tests, verifier and approval policy;
- production code is never silently rewritten merely because a gap was observed;
- proposed self-builds should reference existing RFCs before creating duplicates.

## Existing Jarvis alignment

RFC-0024 agent self-improvement / skill lifecycle and Jarvis's autonomous self-development direction provide the foundation. This epic connects runtime failure telemetry directly to product backlog intelligence.

---

# Epic APEX-20 — Missing source slide 14

Slide 14/20 was not present in either supplied screenshot batch.

Before this umbrella RFC is marked source-complete:

- obtain slide 14;
- transcribe its heading and every listed capability;
- decide whether it maps to an existing epic or requires a new epic;
- record any related Jarvis RFCs;
- then close this capture-gap epic.

---

# Cross-cutting acceptance criteria for feature parity

Parity is not satisfied by a screenshot or a prompt that says Jarvis can do something. For each child epic/PBI, the relevant capability must have:

- a durable backend object/state where appropriate;
- deterministic persistence across restart where appropriate;
- explicit tool/integration contract;
- authority and permission policy;
- visible execution state;
- failure/degraded state;
- evidence/provenance when factual claims depend on records;
- tests for critical deterministic behavior;
- usable desktop UI and, where applicable, channel/mobile exposure;
- documentation of what is actually implemented versus planned.

For actions with external side effects, test at least:

```text
draft -> verify/policy -> approval when required -> execute -> confirm -> audit
```

For scheduled/autonomous actions, test at least:

```text
schedule/trigger -> durable job -> execute -> outcome -> notify/escalate -> retry/fail state
```

For facts/metrics, test at least:

```text
source -> normalize -> store/cache -> freshness/provenance -> UI/answer
```

---

# PBI distillation rule

This RFC is intentionally too large for one implementation worker. **Do not implement RFC-0058 wholesale.**

For each epic:

1. audit existing code + RFC coverage;
2. mark capability as `implemented`, `partial`, `specified only`, or `gap`;
3. reuse existing architecture where present;
4. create the smallest child RFC/PBI that closes one coherent gap;
5. include acceptance tests and user-visible proof;
6. link the PBI back to `APEX-XX` in this RFC;
7. after merge, update the epic status rather than duplicating requirements in the master plan.

Suggested PBI metadata:

```text
PBI ID
Parent epic (APEX-XX)
User outcome
Current-state evidence
Gap
Design/contract
Likely files
Dependencies
Authority/security considerations
Acceptance criteria
Demo/proof requirement
```

---

# Suggested priority order

The sequence below is about **product leverage**, not implementation ease.

## Wave 1 — Make Jarvis feel like a coherent operating system

- APEX-03 canonical source of truth
- APEX-04 proactive sentinel / needs-user queue
- APEX-10 missions
- APEX-13 trust / verification / approval
- APEX-14 one brain across surfaces
- APEX-15 Command Deck/workspaces
- APEX-16 high-signal UI system
- APEX-18 capability registry

## Wave 2 — Make it operationally useful every day

- APEX-02 voice/personality/identity
- APEX-07 email
- APEX-08 calendar/reminders
- APEX-05 social
- APEX-06 artifacts/media
- APEX-09 CRM/finance/ads
- APEX-17 metrics/cost/outcome grading

## Wave 3 — Expand specialist depth and self-development

- APEX-01 specialist organization completion
- APEX-11 Workshop
- APEX-12 multi-screen/local bridge completion
- APEX-19 capability-gap -> self-engineering loop
- APEX-20 recover missing slide 14

Existing active Jarvis P0/P1 work and repository development process still take precedence unless the owner explicitly promotes one of these parity PBIs.

---

# Definition of success

Jarvis reaches Apex feature parity when a user can reasonably experience the following without knowing which models, workers or integrations are underneath:

> I have one persistent Jarvis that knows my real projects and records, coordinates specialists, watches what matters, tells me when I am needed, drafts and builds useful outputs, operates my connected/local tools under explicit policy, remembers decisions, exposes uncertainty and evidence, follows me across devices/surfaces, and presents the whole system through a clean Command Deck and focused workspaces.

At parity, Jarvis should still retain its differentiators: local-first execution, owner-controlled model selection, swarm compute, installable specialist/security packs, hardware-aware routing and configurable autonomy.