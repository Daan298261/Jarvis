# Jarvis 2.0 — Autonomous Operator / Away Mode

Status: **approved product specification**, Architect-owned, referenced by `JARVIS_MASTER_PLAN.md`. **Not implemented** as current-session P0 unless the Development Queue promotes an item.

This file restores the Taco-approved Jarvis 2.0 text (original master-plan sections 64–85) from git history on `cursor/local-qwen-desktop-agent`. Every feature in this file stays in the spec set: Away Mode, event-driven intake, multi-worker orchestration, software-engineering worker, isolated environments, CI/CD, policy engine, production self-healing, remote/mobile, **marketing**, **SEO/content**, **NovelProject**, **multimedia**, distributed nodes (see also `SWARM_ARCHITECTURE.md`), GPU scheduler, cloud fallback, hardware roadmap, high-autonomy security, operations dashboard, and the Away Mode flagship benchmark.

Do not invent a thinner replacement that omits approved features. Do not drop marketing, SEO, novel, invoices (invoices also remain under P5 in `ADAPTIVE_DOMAIN_ARCHITECTURE.md`), or multimedia.

Jarvis 1.x remains sections 1–63 of `JARVIS_MASTER_PLAN.md`. Implement 2.0 incrementally, starting with Phase A, without requiring new hardware.

---

# JARVIS 2.0 — AUTONOMOUS OPERATOR / AWAY MODE

The following sections are the Jarvis 2.0 product specification. They do not replace sections 1–63. Jarvis 1.x remains the current implementation target. Implement 2.0 incrementally, starting with Phase A, without requiring new hardware.

---

## 64. Long-Term Goal — Autonomous Operator / "Away Mode"

### Vision

Jarvis should evolve from a local desktop agent into an always-on autonomous operations platform capable of performing useful work while the user is away from the computer.

The target experience is:

> The user gives Jarvis broad objectives and authority boundaries. Jarvis continuously monitors relevant systems, reacts to events, performs work autonomously, verifies its own results, and contacts the user only when approval or genuinely human input is required.

A flagship target scenario is:

1. A user reports a bug in an application or game.
2. Jarvis receives the report automatically.
3. Jarvis correlates the report with telemetry, logs, crash reports, recent releases, and similar reports.
4. Jarvis classifies it as:
   - bug;
   - duplicate;
   - support problem;
   - feature request;
   - security issue;
   - invalid/unreproducible report.
5. Jarvis attempts to reproduce the problem.
6. If reproduced, Jarvis creates an isolated development environment and branch/worktree.
7. Jarvis delegates investigation and implementation to the best available software-engineering worker.
8. Tests are written or updated.
9. Jarvis builds and tests the complete affected application.
10. A separate verifier reviews the implementation and test evidence.
11. Jarvis deploys the result to staging.
12. Jarvis validates the fix in staging.
13. If the change is within pre-authorized low-risk limits, Jarvis merges and deploys it to production.
14. Jarvis monitors production for regressions.
15. Jarvis automatically rolls back if production health degrades.
16. Jarvis updates or closes the original user report.
17. Jarvis records the complete execution trajectory and outcome.
18. Jarvis contacts the owner with a concise summary.
19. If another user submitted a feature suggestion, Jarvis independently investigates, scopes, and estimates the feature.
20. Jarvis asks the owner for approval when required by policy.
21. After approval, Jarvis can independently implement, test, deploy, and monitor the feature.

This complete scenario should eventually become a repeatable end-to-end Jarvis benchmark (section 85).

---

## 65. Event-Driven Jarvis

Jarvis must evolve from primarily command-driven execution into event-driven autonomous operation.

Jarvis should be able to receive and react to events without requiring the user to initiate a conversation.

### Required event sources

Support events from systems such as:

- GitHub Issues;
- GitHub Pull Requests;
- GitHub Discussions;
- CI/CD systems;
- application telemetry;
- crash/error monitoring such as Sentry;
- in-app user feedback;
- support email;
- website contact forms;
- Discord/community platforms;
- social media;
- customer reviews;
- CMS systems;
- deployment systems;
- uptime monitoring;
- analytics platforms;
- scheduled jobs;
- local filesystem events;
- system events;
- custom REST webhooks;
- MCP-connected services.

### Event normalization

External events should be normalized into internal Jarvis event types.

Examples:

- `BUG_REPORTED`
- `FEATURE_REQUESTED`
- `CRASH_DETECTED`
- `DEPLOYMENT_FAILED`
- `CI_FAILED`
- `SERVICE_DOWN`
- `REVIEW_POSTED`
- `CUSTOMER_EMAIL_RECEIVED`
- `NEW_ORDER`
- `CAMPAIGN_UNDERPERFORMING`
- `SOCIAL_MENTION_DETECTED`
- `MANUSCRIPT_UPDATED`
- `CONTENT_PUBLISHED`

### Event infrastructure requirements

Implement:

- persistent event queue;
- priorities;
- retries;
- exponential backoff;
- deduplication;
- event correlation;
- dead-letter queue;
- restart-safe processing;
- rate limiting;
- event history;
- event-to-task conversion;
- event ownership;
- event acknowledgement;
- audit trail.

Events should be persisted before execution so that restarting Jarvis cannot silently lose work.

The existing launch-prompt queue (`data/queue/pending/`) is a 1.x precursor. 2.0 event intake must be a durable, typed, restart-safe queue rather than a folder of prompt files.

---

## 66. True Multi-Worker Orchestration

Jarvis should remain the primary orchestrator.

Specialized agents, models, frameworks, and external coding tools should operate as workers under Jarvis control.

Target architecture:

```
                    JARVIS
              Planner / Orchestrator
                      |
      ---------------------------------------
      |           |            |            |
   Coding      Research      Marketing     Novel
   Worker       Worker        Worker       Worker
      |                                      |
   Tester                                  Editor
      |                                      |
   Reviewer                              Proofreader
      |
 Deployment
   Worker
      |
   Verifier
```

Additional workers may include:

- browser worker;
- Windows/computer-use worker;
- security reviewer;
- DevOps worker;
- database worker;
- research worker;
- analytics worker;
- image-generation worker;
- video-generation worker;
- audio/TTS worker;
- translation worker;
- fact-checking worker.

This extends section 23 (Worker Abstraction). Optional 1.x adapters (OpenHands, Open Interpreter, Browser Use, UFO, Cua) become named workers in this tree rather than a rewrite of Jarvis.

### Model roles

Architecture should support dedicated models for:

- router;
- planner;
- executor;
- critic;
- verifier;
- coding;
- research;
- writing;
- editing;
- vision;
- computer use;
- fast/simple tasks;
- multimodal tasks.

Initially several roles may use the same model.

Jarvis should automatically choose the cheapest/smallest capable worker for routine tasks and stronger models for difficult work.

---

## 67. Software Engineering Worker

Implement a first-class abstraction:

`SoftwareEngineeringWorker`

Possible implementations:

- `NativeJarvisCodingWorker`
- `CodexWorker`
- `ClaudeCodeWorker`
- `OpenHandsWorker`
- `OpenInterpreterWorker`
- future local coding models

Jarvis must remain responsible for planning, authority, orchestration, and final verification.

### Worker input

A software-engineering worker should receive structured information including:

- repository;
- branch;
- issue/problem;
- relevant logs;
- reproduction steps;
- acceptance criteria;
- architecture constraints;
- security constraints;
- allowed scope;
- test requirements.

### Worker output

The worker should return:

- branch/worktree;
- changed files;
- diff;
- implementation summary;
- tests created/modified;
- test results;
- build results;
- unresolved problems;
- risks;
- confidence;
- verification evidence.

A worker reporting "fixed" must never be sufficient for task completion.

Jarvis must independently verify the result.

---

## 68. Isolated / Disposable Development Environments

Autonomous coding must not directly modify the production checkout.

Jarvis should automatically create isolated environments.

Possible mechanisms:

- Git worktrees;
- temporary branches;
- Docker containers;
- dev containers;
- virtual machines;
- Python virtual environments;
- isolated Node environments;
- temporary databases.

Target workflow:

```
Issue
↓
Fresh isolated environment
↓
Reproduce
↓
Plan
↓
Modify
↓
Unit tests
↓
Integration tests
↓
Build
↓
Static/security checks
↓
Staging deployment
↓
Independent verification
↓
Merge/deploy
```

If a worker corrupts its environment, Jarvis should be able to discard it and recreate a clean environment.

Jarvis should preserve the original repository state and unrelated user changes.

---

## 69. CI/CD and Deployment Control

Jarvis should eventually control the complete software delivery lifecycle.

Required integrations:

- GitHub Actions;
- equivalent CI systems;
- build servers;
- Docker/container registries;
- hosting providers;
- deployment APIs;
- staging environments;
- production environments;
- feature flag systems.

Jarvis should be capable of:

- creating branches;
- creating commits;
- creating PRs;
- reviewing CI results;
- repairing failed CI;
- merging authorized changes;
- deploying to staging;
- running staging tests;
- deploying to production;
- performing canary releases;
- performing blue/green deployments;
- monitoring deployments;
- rolling back releases.

### Progressive deployment

Preferred production flow:

```
Current healthy version
↓
Deploy new version to small percentage
↓
Monitor
↓
Healthy?
├── No → rollback automatically
└── Yes
     ↓
Increase rollout
     ↓
Monitor
     ↓
Full production deployment
```

Feature flags should become a first-class Jarvis capability.

Jarvis should be able to deploy features disabled, validate them, enable them for selected users, then progressively increase availability.

---

## 70. Authority / Approval Policy Engine

High autonomy requires explicit policy boundaries.

Jarvis should not ask the user for approval for every routine operation.

Instead, the owner should configure reusable authority policies.

This extends section 45 (Permissions / Autonomy). 1.x `interactive` / `trusted` / `autonomous` modes remain. 2.0 adds configurable policies per repository, business, application, environment, worker, task type, financial value, and risk level.

### Example automatically allowed actions

- inspect logs;
- investigate issues;
- reproduce bugs;
- create worktrees;
- create branches;
- write tests;
- fix formatting;
- repair obvious low-risk UI bugs;
- repair broken builds;
- create pull requests;
- deploy to staging;
- run tests;
- rollback failed deployments;
- collect analytics;
- draft responses;
- perform research.

### Example conditionally autonomous actions

Allowed only when predefined criteria are met:

- merge low-risk bug fixes;
- production deployment after complete tests;
- respond to known support questions;
- adjust advertising bids within limits;
- publish scheduled content;
- change feature flags;
- restart failed services.

### Example actions requiring approval

- major new product feature;
- large architecture change;
- database migration;
- authentication changes;
- payment changes;
- major dependency upgrades;
- new recurring expenses;
- increased marketing budgets;
- unusual external communications;
- major destructive data transformations.

### Actions Jarvis should never silently perform

- delete production data;
- destroy backups;
- change account ownership;
- change important credentials;
- disable core security controls;
- perform purchases outside approved limits;
- mass-delete data outside explicit task scope;
- expose private systems publicly.

Policies should be configurable per:

- repository;
- business;
- application;
- environment;
- worker;
- task type;
- financial value;
- risk level.

---

## 71. Production Monitoring and Self-Healing

Jarvis should maintain awareness of systems after deployment.

Monitor:

- application exceptions;
- crash rate;
- HTTP error rate;
- API latency;
- CPU;
- RAM;
- disk;
- GPU;
- database health;
- queue health;
- failed jobs;
- uptime;
- release version;
- deployment status;
- user reports;
- conversion rates;
- business KPIs.

### Anomaly correlation

Jarvis should correlate anomalies with recent actions.

Example:

"Error rate increased from 0.3% to 8.1% six minutes after release 1.6.2. Most errors originate from the authentication handler modified in that release."

Jarvis should then:

1. assess severity;
2. automatically rollback if policy allows;
3. inspect the failed release;
4. reproduce the error;
5. create a repair task;
6. verify the repair;
7. redeploy;
8. continue monitoring;
9. report the incident.

Long-term operational loop:

```
Monitor
↓
Detect
↓
Diagnose
↓
Repair
↓
Verify
↓
Deploy
↓
Monitor
```

---

## 72. Remote Jarvis / Mobile Control

Jarvis should be usable when the owner is away from the desktop.

Required capabilities:

- Android/mobile client;
- push notifications;
- remote task view;
- remote approvals;
- task cancellation;
- voice interaction;
- secure authentication;
- encrypted communications.

Possible communication channels:

- Jarvis mobile application;
- Telegram;
- email;
- optional SMS;
- optional telephone integration;
- local/private notification services.

The existing private-key authentication and launch-prompt queue are 1.x precursors. 2.0 remote control must cover approvals, cancellation, and voice as a task/authority interface — not only prompt submission.

### Voice workflow

Target example:

Jarvis:

"Production issue resolved. Three users reported crashes when loading saved games. I reproduced the issue, fixed a null-state error, added regression tests, deployed version 1.4.3, and have observed no additional crashes.

One user also requested controller remapping. I estimate changes are required in the settings UI and input layer. Shall I implement it?"

User:

"Yes. Put it behind a feature flag."

Jarvis:

- records approval;
- resumes the task;
- implements the feature;
- verifies it;
- deploys it behind a feature flag;
- reports completion.

Voice should therefore function as an interface to Jarvis's task and authority system, not merely as speech-to-chat.

This extends section 44 (Future Voice Interface).

---

## 73. Marketing Manager Worker

Implement a specialized:

`MarketingManagerWorker`

Target workflow:

```
Brand / product knowledge
↓
Market research
↓
Competitor research
↓
Audience research
↓
Campaign proposal
↓
Copy generation
↓
Creative generation
↓
Campaign launch
↓
Analytics
↓
A/B testing
↓
Optimization
↓
Reporting
```

### Required integrations

Eventually support:

- Meta/Facebook;
- Instagram;
- TikTok;
- Google Ads;
- Google Analytics;
- Search Console;
- website CMS;
- email marketing;
- ecommerce/order systems;
- social analytics;
- review platforms.

### Marketing controls

Support:

- campaign budgets;
- daily spending limits;
- total spending limits;
- CPA targets;
- ROAS targets;
- conversion tracking;
- attribution;
- campaign version tracking;
- creative versioning;
- content calendar;
- social listening;
- competitor monitoring;
- A/B testing;
- automatic pausing of poor campaigns;
- scaling inside explicitly authorized limits.

Jarvis should close the marketing feedback loop:

```
Research
→ Create
→ Publish
→ Measure
→ Learn
→ Modify
→ Republish
```

Marketing actions involving money must obey the authority policy engine.

---

## 74. SEO / Content Operations

Jarvis should eventually provide an integrated SEO/content publishing workflow.

Capabilities:

- keyword research;
- search-intent analysis;
- competitor analysis;
- content-gap analysis;
- article planning;
- drafting;
- fact checking;
- citations where appropriate;
- internal linking;
- metadata;
- image generation;
- CMS publishing;
- Search Console monitoring;
- rankings tracking;
- traffic monitoring;
- article refreshes;
- content pruning recommendations.

Jarvis should learn stable publishing workflows and convert them into reusable deterministic skills.

---

## 75. Novel Project Subsystem

Novel writing and editing should not simply feed an entire manuscript into a generic model.

Implement a persistent:

`NovelProject`

### Novel project state

Store structured information including:

- manuscript;
- story bible;
- characters;
- character state by chapter;
- relationships;
- locations;
- timeline;
- chapter summaries;
- scenes;
- POV;
- open plot threads;
- resolved plot threads;
- foreshadowing;
- payoffs;
- mysteries;
- world rules;
- continuity constraints;
- prose/style rules;
- terminology;
- revision goals;
- editorial notes;
- manuscript versions;
- change history.

### Novel workers

Support specialized roles:

- Writer;
- DevelopmentalEditor;
- ContinuityEditor;
- LineEditor;
- CopyEditor;
- Proofreader;
- Translator;
- FactChecker;
- FinalQAReviewer.

Different models may be assigned to different roles.

### Editorial verification

After substantial edits Jarvis should check:

- continuity contradictions;
- timeline contradictions;
- character knowledge;
- POV consistency;
- tense consistency;
- duplicated information;
- accidental plot removal;
- forgotten plot threads;
- foreshadowing/payoff integrity;
- character voice;
- prose-style adherence;
- formatting;
- chapter structure.

Every large revision should preserve the previous version and produce inspectable changes.

This extends the 1.x Office/Word document workflow. A manuscript is a long-lived project with structured state, not a one-shot "edit this file" task.

---

## 76. Multimedia / Creative Worker

Integrate BlackGrid Multimedia Studio or equivalent media pipelines as a Jarvis worker.

Potential workflow:

```
Marketing goal
↓
Script
↓
Storyboard
↓
TTS
↓
Image generation
↓
Video generation
↓
Editing
↓
Subtitles
↓
Music/audio processing
↓
QA
↓
Export
↓
Publish
```

Jarvis should automatically manage GPU-heavy pipelines by:

1. checkpointing current agent state;
2. unloading models when necessary;
3. loading the required generation model;
4. running the generation job;
5. validating output;
6. unloading the generation model;
7. restoring the main agent model;
8. continuing the original task.

---

## 77. Distributed Node / Worker Architecture

The authoritative specification for this subsystem is [`SWARM_ARCHITECTURE.md`](SWARM_ARCHITECTURE.md). Do not duplicate its full role, placement, resource, failover, or UI requirements here.

Core integration requirements:

- `Node` means a physical or virtual participating machine/device.
- `Worker` means a software execution service or agent placed on an eligible Node.
- The Orchestrator is the control plane; the Leader is the strongest general-purpose execution Node and is not inherently the Orchestrator.
- Jarvis must behave as a valid one-node swarm before remote-node transport exists.
- P2 introduces Node identity, capability/resource representation, role policy, resource leases, and local placement.
- P3 adds discovery, secure pairing, remote workers, telemetry, and cross-node placement.
- P4 adds standby Orchestrators and advanced resilience.

The existing `InferenceBackend` split remains useful: a remote inference endpoint is one capability that a Node may expose. Swarm scheduling generalizes this from a single configured endpoint into many possible Nodes and Workers without making inference transport the definition of a Node.

Security/SIEM/forensics are reserved future specialized roles only until separately specified and promoted.

---

## 78. Model / GPU Scheduler

Implement automatic model lifecycle management as a specialized part of the broader placement/resource scheduler defined in `SWARM_ARCHITECTURE.md`. Model selection, software Worker selection, physical Node placement, and resource leasing are distinct decisions even when one scheduler coordinates them.

Jarvis should know:

- which models are loaded;
- which node hosts each model;
- VRAM requirements;
- RAM requirements;
- expected performance;
- model specialization;
- current queue.

Jarvis should be able to:

- load models;
- unload models;
- move tasks between nodes;
- select model quantization;
- reduce context when necessary;
- queue GPU-heavy jobs;
- prioritize urgent tasks;
- preempt low-priority jobs where safe;
- fall back to remote/cloud inference.

Example:

```
Video task arrives
↓
Save planner state
↓
Unload coding model
↓
Load video model
↓
Generate media
↓
Unload video model
↓
Reload main model
↓
Restore task state
↓
Continue
```

---

## 79. Cloud / External Model Fallback

Local-first remains the default.

However, Jarvis should support optional external specialist models when local capability is insufficient.

Potential routing policy:

```
Simple task
→ local model

Routine coding
→ local coding model

Difficult repository-wide coding
→ Codex / Claude Code / OpenHands + strong provider

Sensitive/private task
→ local only

Large creative workload
→ dedicated local worker

Emergency where local worker unavailable
→ authorized cloud fallback
```

External providers must be explicitly enabled and configurable.

Jarvis should log whenever data is sent to an external AI provider.

This does not weaken section 3. Prompts, files, source, screenshots, browser contents, documents, and system information still must not be sent silently.

---

## 80. Hardware Roadmap

### Stage 1 — Existing desktop

Use the existing system for:

- Jarvis control plane;
- Qwen3.5-27B;
- orchestration;
- local reasoning;
- browser automation;
- desktop automation;
- lightweight coding;
- STT;
- TTS;
- moderate vision tasks.

Use stronger cloud coding workers when a task exceeds practical local model capability.

Do not require new hardware before continuing development.

### Stage 2 — Dedicated AI worker

Add a dedicated GPU machine.

Suggested target:

- 32 GB or more VRAM;
- 128 GB RAM;
- modern multicore CPU;
- 2–4 TB NVMe;
- 2.5 GbE or faster;
- strong PSU;
- high-quality cooling;
- UPS;
- remote reboot/power control.

Possible GPU class:

- RTX 5090 32 GB or future equivalent.

Use this machine for:

- larger LLMs;
- coding models;
- simultaneous workers;
- image generation;
- video generation;
- larger contexts.

Keep the existing desktop as the Jarvis control plane.

### Stage 3 — High-VRAM local AI node

For near-complete local operation, prioritize VRAM over gaming performance.

Potential future targets:

- 48 GB professional GPU;
- 72 GB professional GPU;
- 96 GB professional GPU;
- multi-GPU node where software support makes it worthwhile.

Use cases:

- large reasoning models;
- large coding models;
- multiple concurrent workers;
- long contexts;
- model ensembles;
- simultaneous planner/verifier;
- heavy media workloads.

Hardware should be added as Nodes exposing capabilities without redesigning Jarvis.

---

## 81. Security Requirements for High Autonomy

**Status: DEFERRED / placeholder only.** Do not implement or expand this subsystem until the user separately respecifies and explicitly promotes security/forensics work. The bullets below preserve earlier long-term intent only.

As Jarvis gains authority, security requirements increase substantially.

Implement:

- encrypted secrets storage;
- credential vault;
- per-worker permissions;
- per-tool permissions;
- network segmentation;
- authenticated Nodes;
- TLS where appropriate;
- signed worker requests;
- immutable audit logging;
- anomaly detection;
- rate limiting;
- deployment credentials separated from development credentials;
- production credentials unavailable to unnecessary workers;
- backup verification;
- automatic credential revocation where possible.

Do not provide every worker unrestricted access to the host or production systems.

Use least privilege.

This extends section 49. 1.x private-key auth for remote API exposure remains required. 2.0 adds vault, per-worker permission, signed node requests, and production/dev credential separation.

---

## 82. Observability / Jarvis Operations Dashboard

Jarvis itself should be observable.

Dashboard should show:

- running tasks;
- queued tasks;
- events;
- active workers;
- active models;
- model locations;
- GPU utilization;
- VRAM;
- RAM;
- CPU;
- active deployments;
- approvals waiting;
- recent incidents;
- failed tasks;
- retries;
- worker health;
- production health;
- marketing campaign health;
- estimated costs;
- external API/model usage.

Provide a global activity timeline.

Example:

```
14:03 User bug report received
14:04 Bug reproduced
14:05 Worktree created
14:06 Coding worker started
14:12 Patch produced
14:14 Tests passed
14:16 Independent verification passed
14:18 Staging deployed
14:20 Staging E2E passed
14:22 Production canary started
14:27 Production stable
14:28 Rollout completed
14:29 Reporter notified
14:29 Owner notified
```

This extends sections 38 and 40. The 1.x Command timeline and Model page are the starting surface; 2.0 needs an operations dashboard covering events, workers, deployments, approvals, and cost.

---

## 83. Autonomous Operations Memory

Trajectory memory should evolve beyond individual task execution.

Jarvis should learn:

- which workers are best for each task;
- typical repository architecture;
- deployment procedures;
- recurring failures;
- common user issues;
- reliable test workflows;
- marketing campaign performance;
- successful creative patterns;
- manuscript style/continuity rules;
- machine-specific behavior;
- node/worker placement performance.

This memory should improve task routing and execution over time.

Do not store hidden reasoning.

Store structured operational knowledge and outcomes.

This extends sections 33–34. 1.x trajectories and parameterized skills remain. 2.0 memory is operational (workers, repos, deploys, campaigns, nodes), still never hidden chain-of-thought.

---

## 84. Long-Term Development Phases

### Phase A — Autonomous Developer

Implement:

- event/webhook intake;
- software-engineering worker;
- isolated Git worktrees;
- CI integration;
- staging;
- independent verification;
- PR generation.

Success condition:

Jarvis can receive a GitHub bug report, reproduce it, repair it, test it, and create a verified PR without human assistance.

### Phase B — Production Operator

Implement:

- deployment control;
- production monitoring;
- canary deployment;
- rollback;
- policy engine;
- self-healing.

Success condition:

Jarvis can autonomously deploy pre-authorized low-risk bug fixes and safely rollback failures.

### Phase C — Remote Jarvis

Implement:

- Android/mobile client;
- push notifications;
- remote approvals;
- voice STT/TTS;
- secure remote conversations.

Success condition:

The owner can leave the computer and supervise Jarvis entirely from a phone.

### Phase D — Business Operator

Implement:

- marketing integrations;
- social listening;
- campaign management;
- analytics;
- automated optimization;
- content publishing;
- customer-support workflows.

Success condition:

Jarvis can operate recurring marketing/business workflows with limited supervision.

### Phase E — Creative Operator

Implement:

- NovelProject subsystem;
- editorial workers;
- translation workflow;
- multimedia pipeline;
- automated creative campaigns.

Success condition:

Jarvis can manage long-running book and multimedia projects while preserving project state and quality.

### Phase F — Distributed Jarvis

Implement:

- Node registry;
- Worker placement and model/GPU scheduler;
- multiple simultaneous models;
- dedicated AI worker hardware;
- distributed task execution;
- cloud fallback.

Success condition:

Jarvis automatically decides where and how work should run across multiple computers/models.

---

## 85. Flagship End-to-End Benchmark

Create a permanent benchmark named:

`Away Mode — Autonomous Bug Fix`

Scenario:

1. A simulated external user submits a bug report.
2. Jarvis detects the report without owner input.
3. Jarvis triages it.
4. Jarvis reproduces the bug.
5. Jarvis creates an isolated development environment.
6. Jarvis delegates implementation to a coding worker.
7. Jarvis generates or updates tests.
8. Jarvis executes tests.
9. Jarvis independently verifies the fix.
10. Jarvis deploys to staging.
11. Jarvis verifies staging.
12. Jarvis performs a canary production deployment.
13. Jarvis monitors production.
14. Jarvis completes the rollout if healthy.
15. Jarvis automatically rolls back if unhealthy.
16. Jarvis updates the original reporter.
17. Jarvis notifies the owner remotely.
18. Jarvis identifies a separate feature suggestion submitted by another user.
19. Jarvis researches and scopes the suggestion.
20. Jarvis asks the owner for authorization.
21. Owner approves remotely.
22. Jarvis implements the feature.
23. Jarvis tests and verifies it.
24. Jarvis deploys it behind a feature flag.
25. Jarvis reports final completion.

### Benchmark success criteria

The benchmark passes only when:

- no manual desktop interaction is required;
- no hidden failure is ignored;
- all code changes are isolated and recoverable;
- tests pass;
- an independent verification pass succeeds;
- production deployment is monitored;
- rollback is functional;
- every consequential action is auditable;
- authority boundaries are respected;
- the owner can approve the feature remotely;
- Jarvis can complete the complete workflow repeatedly rather than succeeding once by chance.

This benchmark represents the target "Jarvis called me while I was away because it had already fixed the reported bug" level of autonomy.

Until this benchmark exists as a harness, do not claim Jarvis 2.0 is implemented. A skeleton under `tests/` may be added during Phase A; the full path requires Phases A–C.
