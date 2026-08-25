# Jarvis — Master Development Plan

This document is the persistent source of truth for the Jarvis project.

Jarvis is a local-first autonomous desktop AI agent intended to perform real work on this computer with minimal human intervention.

**Jarvis 1.x** (sections 1–63) is the current local desktop agent: command-driven, Qwen3.5-27B on this machine, FastAPI + React portal, tools, skills, and verification.

**Jarvis 2.0** (sections 64–85) is the long-term Autonomous Operator / Away Mode specification: event-driven, multi-worker, policy-bounded, remotely supervised. It is specified here so future sessions do not lose the product target. Do not treat 2.0 items as the current-session P0 unless the Development Queue has promoted them or the user explicitly asked for 2.0 work.

This file remains the overall source of truth for priorities, current state, and development status. Detailed swarm requirements intentionally live in the separate [`SWARM_ARCHITECTURE.md`](SWARM_ARCHITECTURE.md) specification so this master plan does not duplicate a large evolving subsystem design.

Every development session must read this file before making substantial changes. Any work touching nodes, placement, resource control, distributed execution, role policy, the universal UI shell, or swarm scheduling must also read `SWARM_ARCHITECTURE.md`.

Cursor is responsible for keeping this document accurate.

The user should not be expected to manually maintain technical state, architecture notes, implementation status, or development priorities.

---
# TOP PRIORITY — FAST, LOW-REFUSAL LOCAL MODEL STACK

Status: P0 — highest current development priority.

The current Qwen3.5-27B Q4_K_M configuration is too slow for normal Jarvis operation on the target RTX 5070 Ti 16 GB because the model, vision projector, KV cache, and runtime overhead cannot all remain inside VRAM.

Jarvis must be redesigned around a fast, fully GPU-resident primary model while retaining the larger 27B model as an optional escalation model.

The goal is not maximum benchmark intelligence.

The goal is:

> Highest successful autonomous task completion rate per minute, with minimal refusals, minimal human intervention, and reliable tool execution.

The user prefers a task that completes correctly in 20 minutes over a faster sequence of failed attempts requiring repeated correction.

For professional use, the model should also avoid unnecessary refusals when analyzing legitimate security, forensic, investigative, technical, or otherwise sensitive material.

---

## P0.1 — Primary Model Migration

Change the default Jarvis model from:

Qwen3.5-27B Q4_K_M

to:

**Qwen3.5-9B Abliterated**

Preferred source model:

`wangzhang/Qwen3.5-9B-abliterated`

Preferred GGUF:

**Q8_0**

Fallback:

**Q6_K**

The model must run entirely or essentially entirely on the RTX 5070 Ti 16 GB without routine CPU layer offload.

Do NOT use a highly degraded quant merely to fit the model.

Q8_0 is preferred because the 9B model is small enough that high quantization quality should fit while still leaving VRAM available for:

- KV cache;
- CUDA workspace;
- vision support when required;
- normal Windows GPU overhead.

Acceptance criteria:

- model downloads automatically or through the existing model setup process;
- Jarvis recognizes the new model;
- Q8_0 loads successfully;
- model layers remain GPU-resident during ordinary operation;
- no routine CPU model-layer spill;
- tool calling works;
- reasoning works;
- normal Jarvis workflows execute correctly;
- measured speed is displayed in the Model/System interface.

---

## P0.2 — Preserve Qwen3.5-27B as Expert/Escalation Model

Do NOT remove Qwen3.5-27B.

Keep:

Qwen3.5-27B Q4_K_M

as an optional high-quality escalation model.

It should NOT remain loaded for ordinary Jarvis work.

Jarvis should eventually be able to escalate automatically when the primary model determines that a problem requires substantially deeper reasoning.

Example:

9B agent
→ encounters genuinely difficult problem
→ saves compact task state
→ unloads 9B
→ loads 27B
→ requests expert analysis/plan
→ saves result
→ unloads 27B
→ reloads 9B
→ continues execution.

The 27B model should primarily be used for:

- difficult architecture decisions;
- complex debugging after repeated failure;
- difficult reasoning;
- long-form analytical work where quality matters more than speed;
- second-opinion criticism;
- escalation after the primary model cannot solve a task.

Do NOT use 27B for trivial actions such as:

- reading files;
- running commands;
- selecting obvious tools;
- renaming files;
- simple browser interaction;
- basic Git operations.

---

## P0.3 — New Model Profiles

Replace the current model-profile assumptions with:

### FAST

Model:
Qwen3.5-9B Abliterated

Quant:
Q6_K or Q8_0 depending benchmark results.

Context:
8K–16K.

Thinking:
Off by default.

Purpose:

- simple tool calls;
- filesystem work;
- routine automation;
- basic shell operations;
- simple browser tasks;
- classification;
- quick responses.

Primary objective:
maximum responsiveness without materially reducing successful task completion.

---

### BALANCED — DEFAULT

Model:
Qwen3.5-9B Abliterated

Quant:
Q8_0.

Context:
approximately 16K initially.

Thinking:
Selective.

Use reasoning for:

- initial planning;
- ambiguous choices;
- errors;
- recovery;
- consequential decisions.

Do NOT enable lengthy thinking for every trivial tool call.

Purpose:

Default Jarvis operation.

This should be the model/profile used for most autonomous work.

---

### RELIABLE

Model:
Qwen3.5-9B Abliterated Q8_0.

Context:
16K–32K depending measured VRAM use.

Thinking:
Enabled where useful.

Agent behavior:

- stronger planning;
- best-of-N planning where appropriate;
- critic pass;
- recovery;
- independent verification;
- additional checks before declaring success.

Important:

Reliable mode should primarily increase AGENT EFFORT rather than automatically loading a much larger model.

---

### EXPERT

Model:
Qwen3.5-27B Q4_K_M.

Purpose:

- escalation;
- difficult reasoning;
- specialist analysis;
- second opinion.

This profile may use CPU/RAM offload and therefore may be considerably slower.

It should not be the normal operating profile.

---

## P0.4 — Dynamic Thinking

Current behavior should be changed so expensive reasoning is NOT applied indiscriminately.

Jarvis should distinguish between:

### Actions that normally do NOT require deep thinking

Examples:

- filesystem.read;
- filesystem.list;
- git status;
- run test;
- open URL;
- query running processes;
- call known deterministic skill;
- execute already-selected command.

### Actions that SHOULD trigger stronger reasoning

Examples:

- initial complex plan;
- choosing between several repair strategies;
- diagnosing an unexpected failure;
- repeated tool failure;
- interpreting ambiguous evidence;
- architecture decisions;
- selecting a recovery strategy;
- final verification of consequential work.

The goal is to reduce generated reasoning tokens without sacrificing task quality.

---

## P0.5 — Lazy Vision Loading

Do not reserve substantial VRAM for multimodal/vision components when they are not being used.

Current normal text/tool operation should run without the vision projector where technically practical.

Desired behavior:

text/shell/filesystem task
→ text-only model configuration

Need screenshot interpretation
→ activate/load vision capability
→ inspect screenshot
→ release unnecessary vision resources when practical.

If hot loading/unloading the projector is impractical with the selected inference backend, benchmark whether:

- maintaining vision loaded;
- switching profiles;
- or using a separate small vision model

produces the best real-world result.

Do not sacrifice several GB of useful VRAM permanently for occasional screenshot analysis without benchmarking the cost.

---

## P0.6 — Dynamic Context Size

Do not use 32K context for every task simply because the model supports it.

Select context according to task requirements.

Suggested starting policy:

Simple:
8K.

Normal:
16K.

Long:
32K.

Exceptional:
larger only when required.

The agent's existing context compaction and persistent task memory should reduce the need for enormous live context windows.

Prefer:

structured persistent state
+
compact active context

over:

sending the entire task history every model turn.

---

## P0.7 — Dynamic Tool Exposure

Do NOT send every Jarvis tool definition to the model on every inference call.

Jarvis already classifies tasks.

Use that classification to expose only tools relevant to the current task.

Examples:

Filesystem task:

- filesystem;
- Python if required.

Software development:

- filesystem;
- terminal;
- Python;
- Git;
- coding worker.

Browser research:

- browser;
- web;
- filesystem;
- spreadsheet/document tool when needed.

Windows application task:

- desktop;
- screenshot;
- relevant application adapter.

This should reduce:

- prompt processing;
- context usage;
- model confusion;
- incorrect tool selection;
- latency.

There must still be an escape mechanism allowing Jarvis to request another capability if the initial tool set proves insufficient.

---

## P0.8 — Performance Benchmark Harness

Before buying hardware, Jarvis must benchmark the actual Windows desktop.

Create an automated local benchmark suite.

Measure at minimum:

- model load time;
- time to first token;
- prompt-processing speed;
- output tokens/second;
- VRAM usage;
- RAM usage;
- GPU utilization;
- CPU utilization;
- context size;
- tool-call latency;
- total autonomous task duration.

Benchmark model/configuration combinations including:

1. Qwen3.5-9B Abliterated Q8_0
2. Qwen3.5-9B Abliterated Q6_K
3. official Qwen3.5-9B Q8_0 if practical
4. current Qwen3.5-27B Q4_K_M

Test context sizes:

- 8K
- 16K
- 32K

Test vision:

- disabled
- enabled

Test reasoning:

- off
- selective
- enabled

Do not select a winner based solely on tokens/sec.

---

## P0.9 — Real Jarvis Agent Benchmark

Create a representative benchmark set of at least 20 realistic autonomous tasks.

Examples should include:

- filesystem organization;
- broken Python project diagnosis;
- Git repository modification;
- PowerShell troubleshooting;
- browser navigation;
- unfamiliar website interaction;
- deliberate tool failure and recovery;
- screenshot interpretation;
- multi-step research;
- document processing;
- multi-tool autonomous task;
- verification after code modification.

Record for every model/configuration:

- task success/failure;
- human intervention required;
- total time;
- model time;
- tool time;
- model calls;
- tool calls;
- retries;
- tool-call/schema errors;
- incorrect actions;
- verification result.

Primary performance metric:

**successful autonomous tasks per unit of wall-clock time**

Secondary metrics:

- first-pass completion rate;
- human interventions;
- tool-call accuracy;
- total task duration;
- tokens/sec.

Jarvis should automatically produce a benchmark report.

---

## P0.10 — Automatic Model Escalation

Design model routing so Jarvis can eventually decide when 9B is insufficient.

Do NOT escalate merely because a task is long.

Potential escalation signals:

- repeated reasoning failure;
- multiple failed strategies;
- critic confidence below threshold;
- contradictory observations;
- architecture-level task;
- user explicitly requests maximum-quality analysis.

Suggested escalation flow:

1. Save compact task state.
2. Record exact problem requiring escalation.
3. Unload primary model if necessary.
4. Load Expert 27B.
5. Ask Expert for a focused analysis or plan.
6. Store result.
7. Reload primary 9B.
8. Continue execution.

Avoid sending enormous full trajectories to the Expert model.

Send:

- goal;
- acceptance criteria;
- important observations;
- failed approaches;
- relevant files/data;
- precise unresolved problem.

---

## P0.11 — Low-Refusal Professional Model Requirement

Jarvis may be used for legitimate professional security, forensic, investigative, defensive, technical, or analytical work.

The primary reasoning model should therefore minimize unnecessary refusals when processing legitimate but potentially sensitive material.

Examples may include analysis of:

- malware;
- attack techniques;
- scripts;
- suspicious PowerShell;
- forensic artifacts;
- logs;
- criminal communications;
- exploit evidence;
- phishing;
- credential-theft artifacts;
- security vulnerabilities;
- offensive-security tooling;
- disturbing evidence;
- illicit-market material;
- other case-related technical evidence.

The desired model behavior is:

analyze the material accurately
rather than
refuse merely because the subject is sensitive.

Model permissiveness must remain separate from operational authorization.

---



## P0.12 — Hardware Purchasing Gate

Do not recommend or depend on additional hardware until the new benchmark suite has run on the actual desktop.

Specifically, defer buying:

- additional RAM;
- old Tesla GPUs;
- V100 GPUs;
- NPUs;
- additional inference hardware;

until software/model optimization has been measured.

After benchmarks, Jarvis should report:

- current bottleneck;
- whether GPU VRAM is saturated;
- whether CPU offload occurs;
- whether system RAM is constrained;
- whether CPU inference is limiting;
- whether model switching is costly;
- estimated benefit of more VRAM;
- estimated benefit of more RAM.

Hardware purchases should be driven by measured bottlenecks.

---

## P0.13 — Success Target

The model migration is considered successful when:

1. Qwen3.5-9B Abliterated Q8_0 runs locally and reliably.
2. Ordinary tasks remain entirely GPU-resident where practical.
3. Jarvis is substantially more responsive than the current 27B configuration.
4. Tool-call reliability remains acceptable.
5. Autonomous task completion does not materially degrade.
6. Refusals during legitimate professional analysis are rare.
7. Vision works when requested.
8. Reliable mode still performs robust planning/recovery/verification.
9. Expert 27B escalation works.
10. Benchmark data is stored and visible.
11. A representative 20-task comparison against the old 27B configuration has been completed.

The final decision between Q8_0, Q6_K, official 9B, and abliterated 9B must be based on actual Jarvis task performance rather than assumptions.

---

# UPDATED IMMEDIATE P0 DEVELOPMENT ORDER

The current P0 queue should now be ordered:

1. **Integrate Qwen3.5-9B Abliterated Q8_0.**
2. **Verify full GPU residency on RTX 5070 Ti 16 GB.**
3. **Create benchmark/performance instrumentation.**
4. **Implement lazy vision loading or equivalent VRAM optimization.**
5. **Implement dynamic context sizing.**
6. **Implement task-specific tool exposure.**
7. **Implement selective/dynamic thinking.**
8. **Run 20-task comparison: 9B Q8 vs 9B Q6 vs current 27B Q4.**
9. **Select default Fast/Balanced/Stable configurations from measured results.**
10. **Implement automatic 9B → 27B Expert escalation.**
11. **Only after these tests, reassess whether hardware upgrades are necessary.**

Security/SIEM/forensics implementation is intentionally deferred. The swarm architecture may reserve future roles for those capabilities, but they must be separately respecified and explicitly promoted before implementation.

This optimization effort takes priority over Browser Use, UFO, Cua, OpenHands, voice, phone clients, and other P1/P2/P3 functionality unless one of those is required to complete the benchmark suite.

# HIGH PRIORITY — AUTONOMOUS SOFTWARE DEVELOPMENT WORKER ROUTING

Status: P0/P1 — router implemented for local execution; paid Cursor workers remain disconnected until ACP/credentials exist. Live 9B migration and the 20-task GPU comparison are still the Windows-desktop P0.

Jarvis must be capable of developing software autonomously, including development of Jarvis itself.

Jarvis must NOT depend on one coding model for every task.

Instead, implement a software-development worker router that selects the cheapest sufficiently capable coding worker, escalates automatically when necessary, independently verifies the resulting work, and learns which workers perform well for which task classes.

The target behavior is:

User / event
↓
Jarvis Supervisor
↓
Classify software-development task
↓
Estimate complexity / risk / expected cost
↓
Select cheapest capable worker
↓
Worker performs implementation
↓
Jarvis independently tests/verifies
↓
PASS → complete
FAIL → retry or escalate
↓
Record outcome for future routing

The purpose is to minimize paid AI usage without sacrificing development quality.

---

## 1. Software Development Worker Interface

Implement a common abstraction:

`SoftwareDevelopmentWorker`

Possible implementations:

- `LocalJarvisCodingWorker`
- `CursorACPWorker`
- future `CodexWorker`
- future `OpenHandsWorker`
- future other external coding agents.

The rest of Jarvis should not depend directly on Cursor-specific logic.

Suggested conceptual interface:

- start_task()
- continue_task()
- inspect_task()
- cancel_task()
- send_feedback()
- get_changes()
- get_status()
- get_cost_usage()
- get_model()
- set_model()
- verify_connection()

Worker results should include:

- files changed;
- commands executed;
- tests run;
- worker-reported result;
- errors;
- session ID;
- model used;
- approximate usage/cost where available.

Jarvis remains the supervisor.

A worker claiming success does NOT constitute successful completion.

---

# 2. Coding Intelligence Determination Tree

Jarvis must route coding work according to complexity, previous success, cost, and risk.

The initial routing policy should be:

## Tier 0 — Deterministic Tools

Before invoking any coding model, determine whether the change can be performed deterministically.

Examples:

- update known JSON value;
- bump known version;
- run formatter;
- rename file;
- execute known build;
- regenerate generated files;
- run tests;
- apply previously learned deterministic skill.

Use native tools/scripts.

Do not pay for an AI coding worker unnecessarily.

---

## Tier 1 — Local Coding Worker

Primary model:

Qwen3.5-9B low-refusal local model.

Cost:

effectively zero incremental AI cost.

Use for:

- documentation;
- small configuration changes;
- adding straightforward tests;
- fixing simple exceptions;
- basic API endpoint changes;
- small isolated functions;
- repetitive refactoring;
- minor frontend changes;
- simple dependency/configuration work;
- investigating obvious test failures;
- changes Jarvis has successfully performed before.

Typical criteria:

- small number of files;
- clear acceptance criteria;
- established architecture;
- low ambiguity;
- low blast radius;
- existing tests available.

Jarvis must independently test the result.

If verification succeeds:

STOP.

Do not escalate merely because a paid model may produce prettier code.

If local worker fails to produce a verified result after a reasonable number of attempts:

escalate to Tier 2.

Suggested default:

maximum 2 meaningful local attempts.

Do not repeat the same failed strategy.

---

## Tier 2 — Cursor Composer 2.5 Standard

This should be the DEFAULT paid coding worker.

Prefer:

**Composer 2.5 STANDARD**

Do NOT default to its Fast pricing tier for unattended development.

Use for:

- normal feature development;
- multi-file implementation;
- ordinary refactors;
- test-driven fixes;
- frontend/backend work;
- database changes;
- moderate debugging;
- implementing items from `JARVIS_MASTER_PLAN.md`;
- work where local 9B failed;
- tasks requiring better repository understanding.

Composer should be preferred over Grok 4.6 for routine software development because it is substantially cheaper and explicitly optimized for agentic coding, file editing, terminal usage, tool selection, and long-horizon coding work.

Current relative standard pricing:

Composer 2.5:
- input: ~$0.50 / million tokens
- cached input: ~$0.20 / million
- output: ~$2.50 / million

Grok 4.6:
- input: ~$2.00 / million
- cached input: ~$0.50 / million
- output: ~$6.00 / million

Therefore Grok must not be invoked simply because it is stronger.

Use the cheapest model capable of producing a verified result.

If Composer succeeds and Jarvis verification passes:

STOP.

If Composer repeatedly fails, stalls, contradicts itself, or cannot resolve the problem:

escalate.

---

## Tier 2B — Optional Cheap Alternative

Support optional low-cost third-party coding workers when they are available and economical.

Examples may include models such as:

- GPT-5.6 Luna;
- Gemini Flash-class coding models;
- future low-cost models that benchmark well.

Do NOT hard-code these names permanently.

Maintain a configurable worker/model catalog containing:

- model identifier;
- current price;
- context window;
- measured Jarvis coding success rate;
- average task cost;
- average task duration;
- task classes where it performs well.

The routing engine may choose one of these instead of Composer when empirical results show it is cheaper for equivalent success.

Because Cursor usage pools differ between first-party Cursor models and third-party models, routing should account for remaining monthly pool balances where those values are available.

---

## Tier 3 — Cursor Grok 4.6

Use Grok 4.6 STANDARD for genuinely difficult work.

Do NOT use Grok 4.6 Fast by default.

Suitable tasks:

- difficult architectural implementation;
- large multi-module changes;
- complex debugging;
- long-horizon development;
- ambiguous failures;
- substantial new subsystems;
- tasks where Composer failed;
- tasks with complex interactions between multiple components;
- difficult migrations;
- subtle concurrency/state problems.

Start with an appropriate effort level rather than automatically using maximum effort.

Suggested:

medium/high for difficult work.

Reserve xhigh for unusually difficult cases.

If Grok produces a solution:

Jarvis must still independently:

- inspect diff;
- run tests;
- run build;
- exercise relevant functionality;
- check repository state;
- check acceptance criteria.

---

## Tier 4 — Frontier Specialist

Only use the most expensive available coding/reasoning model when:

- lower tiers failed;
- task risk is unusually high;
- task requires difficult architecture reasoning;
- repeated contradictory failures exist;
- user explicitly requests maximum quality.

Possible workers may include:

- high-end OpenAI coding/reasoning model;
- Claude Sonnet/Opus-class worker;
- future frontier models.

These workers are expensive exceptions.

They must not become the default development path.

---

# 3. Initial Complexity Router

Implement an initial software-task complexity score from 0–100.

This does not need to be perfect.

Use signals such as:

- expected number of files affected;
- repository size;
- test availability;
- ambiguity of request;
- architecture impact;
- database/schema impact;
- external API changes;
- security relevance;
- previous attempts;
- previous successful trajectory;
- dependency changes;
- estimated blast radius.

Initial routing:

0–20:
deterministic/local tools.

21–40:
local Qwen coding worker.

41–70:
Cursor Composer 2.5.

71–90:
Cursor Grok 4.6.

91–100:
strongest suitable specialist.

However:

Historical measured success should override static thresholds.

Example:

If local Qwen has successfully completed 8 similar tasks with 95% verification success:

route the next similar task locally even if its static score would normally select Composer.

---

# 4. Escalation Policy

Escalation must be evidence-based.

Example:

Local Qwen
↓
attempt
↓
tests fail
↓
analyze failure
↓
second materially different attempt
↓
tests fail
↓
ESCALATE

Composer
↓
receives:
- original goal
- acceptance criteria
- relevant repository state
- local worker changes
- tests
- exact errors
- strategies already attempted
↓
continue work

Do NOT simply send the entire raw conversation to the next model.

Pass a compact escalation package.

Suggested:

`EscalationContext`

containing:

- goal;
- acceptance criteria;
- task class;
- relevant files;
- current diff;
- failing tests;
- important logs;
- attempted strategies;
- reason for escalation.

---

# 5. Cost-Aware Routing

Jarvis must treat paid coding intelligence as a limited resource.

Track where technically possible:

- model;
- worker;
- input tokens;
- cached tokens;
- output tokens;
- estimated cost;
- monthly accumulated cost;
- task cost;
- successful task cost.

Important metric:

**cost per verified successful software task**

Do NOT optimize only:

cost per token.

A cheap model that fails repeatedly may be more expensive than a stronger model.

Future routing should use historical data such as:

Local Qwen:
€0
success on task class: 82%

Composer:
average €0.34
success: 96%

Grok:
average €1.40
success: 98%

This allows Jarvis to make rational routing decisions.

---

# 6. Cursor Integration — Use ACP

Jarvis must integrate directly with Cursor Agent.

Primary protocol:

**ACP — Agent Client Protocol**

Do NOT make screen/mouse control of the Cursor IDE the primary integration.

Cursor CLI can run as an ACP server:

`agent acp`

ACP communicates over:

- stdio;
- JSON-RPC 2.0;
- newline-delimited messages.

Jarvis should implement:

`CursorACPWorker`

that starts and supervises the Cursor Agent process.

Conceptual architecture:

Jarvis
↓
SoftwareDevelopmentWorker
↓
CursorACPWorker
↓
ACP JSON-RPC
↓
Cursor Agent
↓
repository/worktree

The actual Cursor graphical IDE does not need to be open.

This is preferable to GUI control because it is:

- deterministic;
- machine-readable;
- resumable;
- observable;
- less fragile;
- easier to automate.

---

# 7. ACP Session Lifecycle

Implement the supported ACP lifecycle approximately as:

1. start `agent acp`;
2. initialize connection;
3. authenticate if required;
4. create or load Cursor session;
5. send task;
6. receive streaming session updates;
7. handle Cursor requests;
8. monitor completion;
9. collect results;
10. persist Cursor session ID;
11. allow follow-up instructions;
12. terminate or retain worker as appropriate.

Jarvis must persist enough information to reconnect/resume after restart.

---

# 8. Cursor Blocking Requests

Cursor ACP may issue blocking requests such as:

- `cursor/ask_question`
- `cursor/create_plan`

Jarvis should be capable of answering these automatically when permitted.

Example:

Cursor asks:

"Should I add a migration or modify the existing schema?"

Jarvis:
↓
consult task goal / architecture / master plan
↓
answer autonomously.

If the question involves a genuinely consequential product decision:

escalate to user.

Plan-approval requests should normally be handled automatically during autonomous development when:

- work is isolated;
- acceptance criteria are clear;
- repository is disposable/recoverable;
- no production action is involved.

Do not wake the user merely for routine Cursor planning approvals.

---

# 9. Cursor Model Selection

Jarvis must be able to select the Cursor model used for a development task.

Do not rely on whatever model happened to be selected in the graphical IDE.

Use supported Cursor CLI/ACP model configuration.

Model selection must be driven by the determination tree.

Typical mapping:

routine external work:
Composer 2.5 standard

difficult work:
Grok 4.6 standard

specialized expensive work:
configured frontier specialist.

Do not use Fast variants unless latency is specifically worth the increased cost.

Model identifiers must be configurable because Cursor may change available models.

At startup, where feasible:

query available models rather than assuming permanent identifiers.

---

# 10. ACP vs MCP

Use the correct protocol direction.

## Jarvis → Cursor

Use:

**ACP**

Purpose:

Jarvis acts as a custom client controlling Cursor Agent.

## Cursor → Jarvis / External Tools

Use:

**MCP**

Purpose:

Cursor can call tools/services exposed by Jarvis.

Therefore implement both directions eventually:

Jarvis
 ├── ACP client → Cursor Agent
 │
 └── MCP server ← Cursor Agent

This enables:

Jarvis supervising Cursor

while simultaneously allowing Cursor to use:

- Jarvis memory;
- Jarvis task context;
- BlackGrid Multimedia;
- internal APIs;
- specialized tools;
- system state.

Do not confuse the roles of ACP and MCP.

---

# 11. Jarvis MCP Server for Cursor

Expose a limited Jarvis MCP server that Cursor can use during development.

Potential read-oriented tools/resources:

- get_master_plan
- get_current_task
- get_acceptance_criteria
- get_known_architecture
- get_relevant_trajectory
- get_previous_failure
- get_environment_info

Potential controlled actions:

- request_verification
- report_worker_result
- request_specialized_tool
- query_Jarvis_status

Do not expose unrestricted recursive self-control by default.

Avoid:

Cursor → Jarvis → Cursor → Jarvis

loops.

Every delegated development task must have a single supervisor:

Jarvis.

---

# 12. Self-Development Mode

Jarvis must eventually be able to modify Jarvis.

This requires a special mode:

`SELF_DEVELOPMENT`

Never allow experimental self-development directly against the trusted production/trunk working tree.

Create an isolated development environment.

Recommended architecture:

trusted Jarvis installation
        │
        ▼
Self-Development Supervisor
        │
        ▼
dedicated Git worktree/fork
        │
        ▼
local Qwen / Cursor
        │
        ▼
modify
        │
        ▼
test
        │
        ▼
benchmark
        │
        ▼
candidate branch

# 13. Self-Development Isolation

When starting autonomous self-development:

1. Confirm trusted source revision.
2. Create a dedicated branch/worktree.
3. Record the starting commit SHA.
4. Never modify the trusted running installation.
5. Give the worker access only to the experimental worktree where practical.
6. Develop there.
7. Commit incremental checkpoints.
8. Run tests.
9. Record benchmark results.
10. Produce a final candidate branch.

Example branch:

`jarvis/autonomous-trial-2026-08-24`

A broken experimental branch must never prevent the trusted Jarvis instance from starting.

---

# 14. No Autonomous Merge During Initial Trials

During early self-development trials, Jarvis may:

- edit;
- test;
- commit;
- create branches;
- create candidate pull requests where authorized;
- compare results.

Jarvis must NOT automatically:

- merge its experimental branch into trusted main;
- overwrite the trusted installation;
- deploy a new Jarvis version over itself;
- delete the known-good branch.

The user should review the first trial results.

Later, automated promotion may be considered after sufficient reliability data exists.

---

# 15. One-Day Autonomous Development Trial

Create an explicit test mode:

`AUTONOMOUS_DEVELOPMENT_TRIAL`

Duration target:

Up to approximately one working day or a configured time budget.

Purpose:

Determine whether Jarvis is genuinely capable of managing software development.

Test environment:

Dedicated Jarvis fork/worktree.

At trial start:

1. Snapshot source commit.
2. Ensure clean Git state.
3. Create experiment branch.
4. Run baseline tests.
5. Record baseline metrics.

Then Jarvis should work autonomously through appropriate items in `JARVIS_MASTER_PLAN.md`.

Jarvis should:

- choose a task;
- determine acceptance criteria;
- select a coding worker;
- implement;
- run tests;
- inspect failures;
- recover;
- escalate models when justified;
- verify;
- commit successful increments;
- continue to the next task.

Do NOT repeatedly ask the user what to work on.

Use the highest-value eligible backlog item.

---

# 16. Trial Task Restrictions

For the first autonomous self-development trial, prefer tasks that are:

- testable;
- reversible;
- isolated;
- clearly specified.

Suitable examples:

- benchmark instrumentation;
- model-profile improvements;
- dynamic tool exposure;
- context optimizations;
- UI improvements;
- worker adapters;
- test coverage;
- documentation;
- performance telemetry.

Avoid initially:

- destructive database migrations;
- deleting major architecture;
- replacing the entire orchestrator;
- security-boundary removal;
- automatic production deployment.

---

# 17. Trial Budget

Self-development must have configurable limits.

Example:

Maximum duration:
12 hours

Maximum paid AI spend:
user-defined

Maximum paid worker invocations:
configurable

Maximum consecutive failures:
configurable

Maximum branch size/change volume:
warning threshold

Jarvis must stop escalating paid models if the configured financial limit is reached.

Continue with local work where possible.

---

# 18. Kill Switch

Provide an immediate stop mechanism.

Examples:

Portal:

`STOP AUTONOMOUS DEVELOPMENT`

API:

Cancel supervisor job.

Local file:

`data/STOP_JARVIS`

or similarly simple emergency stop mechanism.

When activated:

- stop new worker dispatch;
- cancel active coding workers where practical;
- preserve current files;
- preserve logs;
- preserve Git state;
- do not attempt cleanup that could destroy useful work.

---

# 19. Independent Verification

Jarvis must not trust Cursor's final response.

After Cursor says:

> Implemented and tests pass.

Jarvis should independently execute relevant verification.

At minimum:

- inspect Git diff;
- run unit tests;
- run relevant integration tests;
- run build;
- inspect errors;
- ensure acceptance criteria are satisfied.

For changes affecting Jarvis runtime, where practical launch the experimental instance on alternate ports and test it separately.

Example:

Trusted Jarvis:
`127.0.0.1:4780`

Experimental Jarvis:
`127.0.0.1:4781`

Then Jarvis can test its candidate replacement without killing itself.

---

# 20. Self-Development Regression Gate

A candidate change may only be considered successful when:

NEW TESTS PASS  
AND  
OLD TESTS PASS  
AND  
RELEVANT E2E TESTS PASS  
AND  
NO UNEXPLAINED REGRESSION EXISTS

If performance-related, compare against baseline.

Example:

Before:
median task time = 94 s

After:
median task time = 61 s

Task success:
unchanged

Result:
accept improvement.

But:

Before:
success = 95%

After:
success = 75%

Result:
reject even if faster.

---

# 21. Development Learning

Record each delegated coding task in trajectory memory.

Store:

- task class;
- task complexity;
- worker;
- model;
- duration;
- cost;
- first-attempt success;
- retries;
- verification result;
- regression count.

Use these results to improve future routing.

Example:

After enough tasks Jarvis might learn:

> Local Qwen succeeds on Python unit-test additions 93% of the time.

Then route those locally.

Or:

> Local Qwen fails most React state-management changes.

Then route those directly to Composer.

This should evolve from static thresholds into evidence-based routing.

---

# 22. Self-Development Reporting

At the end of an autonomous development session produce a concise report.

Include:

Duration:
Worker time:
Models used:
Estimated paid cost:
Tasks attempted:
Tasks completed:
Tasks failed:
Commits created:
Tests before:
Tests after:
Regressions:
Performance changes:
Human intervention:
Recommended merge candidates:

Also produce:

- experiment branch name;
- starting commit;
- ending commit;
- concise diff summary.

The purpose of the first one-day trial is measurement, not blind trust.

---

# 23. Success Criteria for Initial Trial

The autonomous development system will be considered promising if Jarvis can spend a full trial period working on its own fork and achieve:

- multiple useful commits;
- no damage to trusted Jarvis;
- clean/recoverable Git state;
- no uncontrolled spending;
- correct worker escalation;
- tests passing after successful changes;
- meaningful backlog progress;
- low human intervention.

Measure:

`verified useful work per hour`

and:

`verified useful work per euro`

These are more important than raw tokens generated.

---

# 24. Implementation Priority

Add the following to the active development queue.

P0/P1:

1. Implement `SoftwareDevelopmentWorker` abstraction.
2. Implement `CursorACPWorker`.
3. Verify local Cursor authentication.
4. Verify `agent acp` lifecycle.
5. Add persistent Cursor session IDs.
6. Implement Composer/Grok model routing.
7. Implement worker escalation.
8. Add cost/usage telemetry where available.
9. Implement Self-Development Mode.
10. Implement isolated Git worktree/fork management.
11. Implement experimental alternate-port Jarvis launch.
12. Implement self-development verification gate.
13. Implement spend/time/failure limits.
14. Implement emergency kill switch.
15. Implement end-of-run development report.
16. Run first one-day autonomous-development experiment.

Progress this session (code + unit tests; live Cursor CLI still absent):

- `CursorACPWorker` JSON-RPC lifecycle, persisted session IDs, auto-answer for isolated routine questions.
- Jarvis MCP server for Cursor (`python3 -m app.mcp_stdio`).
- Compact `EscalationContext` packaging after repeated tool failures.

Do not prioritize GUI mouse automation of Cursor.

ACP is the preferred primary integration.

MCP should complement ACP by allowing Cursor to access Jarvis-managed tools and context.

---

# 25. Desired End-State Example

Event:

Jarvis discovers a P1 backlog item:

> Implement Browser Use worker adapter.

Jarvis:

1. Inspects requirement.
2. Estimates complexity = 65.
3. Sees no strong local trajectory.
4. Selects Composer 2.5.
5. Creates isolated branch/worktree.
6. Launches Cursor through ACP.
7. Sends requirement and acceptance criteria.
8. Monitors Cursor.
9. Automatically answers routine Cursor planning questions.
10. Cursor implements adapter.
11. Cursor reports success.
12. Jarvis runs tests independently.
13. A test fails.
14. Jarvis sends the exact failure back to the same Cursor session.
15. Cursor repairs it.
16. Jarvis retests.
17. Tests pass.
18. Jarvis launches experimental Jarvis.
19. Runs relevant E2E test.
20. Verifies behavior.
21. Commits candidate.
22. Records Composer success/cost/duration.
23. Moves to the next backlog item.

If Composer repeatedly fails:

Jarvis packages the current state and escalates to:

`Grok 4.6`

The user does not need to supervise this routine loop.

---

# 26. Core Principle

Jarvis should not attempt to become the world's best programmer using one small local model.

Jarvis should become a competent engineering manager.

Its job is to:

- identify work;
- estimate difficulty;
- choose the right intelligence;
- control cost;
- provide context;
- supervise execution;
- detect failure;
- escalate intelligently;
- verify results;
- remember what worked.

The long-term objective is:

**Use local intelligence whenever it is sufficient and paid frontier intelligence only when it materially increases the probability of successful completion.**

from here on are the regular requirements
## 1. Core Goal

Build a local "Jarvis"-style AI system that can receive a high-level instruction such as:

- organize these files;
- research this subject;
- fix this application;
- install and configure this program;
- debug this repository;
- edit this Word document;
- analyze these logs;
- operate a website;
- create a report;
- use an application;
- perform a browser workflow;
- write or modify software;
- diagnose a system problem;
- continue a previous task;
- perform a long-running multi-step job;

and autonomously determine how to accomplish it.

The user should interact primarily through a simple local web portal or API.

Jarvis should decide which programs, tools, agents, APIs, scripts, browser controls, or desktop-control mechanisms are required.

The user should not normally need to choose tools, models, workers, or execution strategies.

---

## 2. User Experience Goal

The user wants extremely low maintenance.

The desired interaction is:

«"Do X."»

Jarvis should then:

1. understand the desired end result;
2. inspect the relevant environment;
3. formulate a plan;
4. execute the plan;
5. inspect results;
6. diagnose failures;
7. change strategy when necessary;
8. continue working;
9. independently verify the final result;
10. report what was actually accomplished.

The user prefers:

«a task taking 20 minutes and completing correctly»

over:

«an agent making a quick attempt every five minutes and repeatedly requiring human correction.»

Optimize primarily for reliability and autonomous completion rather than maximum token speed.

The user wants to perform almost zero configuration.

Routine engineering decisions should therefore be made autonomously by the system or by Cursor during development.

Only request human input when genuinely necessary, for example:

- credentials;
- physical interaction;
- hardware changes;
- a genuinely ambiguous product decision;
- consequential financial action;
- a new requirement whose desired behavior cannot reasonably be inferred.

Do not ask the user to make routine library, framework, implementation, folder-layout, dependency, or configuration decisions.

---

## 3. Local-First Principle

Jarvis must operate locally by default.

The main model should run on hardware controlled by the user.

Do not silently send:

- prompts;
- files;
- source code;
- screenshots;
- browser contents;
- documents;
- system information;
- private data;

to external AI providers.

Cloud AI backends may eventually be supported as optional providers, but Jarvis must not depend on them.

The system architecture should allow the inference server to later move from the desktop to:

- another local computer;
- a dedicated GPU server;
- a multi-GPU AI machine;
- another OpenAI-compatible endpoint on the LAN;

without requiring a redesign of Jarvis.

---

## 4. Primary Model

Primary model target:

Qwen3.5-27B

The exact quantization should be selected based on actual detected hardware and current upstream recommendations.

Initial likely target:

Q4_K_M or closest current equivalent

Quality mode may optionally use Q5 if performance and memory consumption remain reasonable.

Do not substitute a tiny model simply because it is easier to install.

The model should be capable of:

- reasoning;
- tool calling;
- coding;
- general writing;
- long-context tasks;
- agentic execution;
- multimodal/vision tasks where supported;
- interpreting screenshots;
- understanding program state;
- working with structured tool results.

Use reasoning/thinking mode for difficult autonomous tasks where supported.

Use a faster mode for simple deterministic requests.

---

## 5. Hardware-Aware Configuration

Jarvis must detect the actual machine rather than assuming fixed specifications.

Detect and expose:

- operating system;
- CPU;
- physical cores/threads;
- system RAM;
- NVIDIA GPU;
- GPU architecture;
- VRAM;
- NVIDIA driver;
- CUDA compatibility;
- free SSD space;
- inference-server state;
- current memory consumption.

Tune the model to the actual hardware.

Prefer GPU offloading where appropriate.

Do not automatically allocate the maximum theoretical context window.

Start with a practical working context, likely around:

- 32K;
- or 64K;

depending on benchmark results.

Large context windows should only be used when necessary.

---

## 6. Inference Architecture

Jarvis must interact with models through an abstraction layer.

Suggested interface:

"InferenceBackend"

Possible implementations:

- "LlamaCppBackend"
- "LMStudioBackend"
- "OllamaBackend"
- "VLLMBackend"
- "SGLangBackend"
- "RemoteOpenAICompatibleBackend"

Select the best current inference backend based on:

- Qwen compatibility;
- Windows compatibility;
- multimodal support;
- tool-calling reliability;
- GPU offloading;
- performance;
- stability.

Prefer a local OpenAI-compatible API.

The rest of Jarvis must not depend tightly on one particular inference server.

Current implementation: chat goes through `ModelProvider` / `OpenAICompatProvider`; server lifecycle goes through `InferenceBackend` (`backend/app/inference/backends.py`). `LlamaCppBackend` owns the local process. Everything else OpenAI-compatible resolves to `RemoteOpenAICompatibleBackend`, which only health-checks. Adding LM Studio, Ollama, vLLM, or SGLang as first-class backends means subclassing here, not touching agent code.

---

## 7. Overall Architecture

Target high-level architecture:

                    JARVIS WEB PORTAL
                           │
                           ▼
                     JARVIS API
                           │
                           ▼
                    TASK ORCHESTRATOR
                           │
          ┌────────────────┴────────────────┐
          │                                 │
          ▼                                 ▼
     Qwen3.5-27B                     Persistent State
                                       / Memory
          │                                 │
          └────────────────┬────────────────┘
                           ▼
                      TOOL ROUTER
                           │
      ┌─────────┬──────────┼──────────┬───────────┐
      ▼         ▼          ▼          ▼           ▼
 Filesystem   Shell      Browser    Desktop      MCP
 /Python      tools      workers    workers      tools
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   Browser Use           UFO/Cua          OpenHands
   Playwright        Native Windows     Open Interpreter
                           │
                           ▼
                        RESULT
                           │
                           ▼
                       VERIFIER
                      /        \
                   success    failure
                     │           │
                    done       diagnose
                                 │
                                 ▼
                            new strategy

Jarvis is the orchestrator.

Third-party projects are workers or execution engines.

No third-party agent should own the entire Jarvis architecture.

---

## 8. Explicit Agent Execution Loop

Every substantial autonomous task should follow an explicit lifecycle.

1. Understand the requested end state.
2. Define acceptance criteria.
3. Inspect relevant files/system/applications.
4. Classify the task.
5. Create an execution plan.
6. Select appropriate tools.
7. Execute the next action.
8. Capture the result.
9. Evaluate whether it succeeded.
10. If it failed, determine why.
11. Select a corrected or alternative strategy.
12. Continue execution.
13. Check whether acceptance criteria are satisfied.
14. Perform an independent verification pass.
15. Only then declare completion.

The system must distinguish:

«command successfully executed»

from:

«requested task successfully completed.»

These are not equivalent.

---

## 9. Task Classification

Before substantial execution, classify the task internally.

Possible categories include:

- filesystem;
- shell;
- system administration;
- software engineering;
- research;
- browser automation;
- Windows GUI;
- Office;
- document processing;
- data processing;
- multimodal;
- mixed;
- long-horizon autonomous.

Task classification should influence worker/tool selection.

This classification does not need to be prominently exposed to the user.

---

## 10. Tool Selection Philosophy

Prefer the most deterministic and reliable mechanism.

Default priority:

1. direct API;
2. deterministic library;
3. application API;
4. COM;
5. CLI;
6. filesystem operation;
7. DOM automation;
8. accessibility/UI Automation;
9. specialized agent worker;
10. visual computer-use model;
11. raw coordinate clicking.

Raw mouse-coordinate interaction is a last resort.

Examples:

Renaming 5,000 files:

Use Python/filesystem operations.

Do not automate Explorer.

Editing Excel:

Prefer:

- direct workbook library;
- Excel COM;

before GUI interaction.

Known website API:

Use the API.

Unknown website:

Use Browser Use to discover the workflow.

Known stable website workflow:

Use deterministic Playwright or a reusable Jarvis skill.

Large repository refactor:

Potentially delegate to OpenHands.

Simple PowerShell command:

Use direct PowerShell.

---

## 11. Core Native Tools

Jarvis should have first-class deterministic tools independent of external agent frameworks.

Filesystem

Support:

- list directories;
- search directories;
- glob files;
- read files;
- write files;
- edit files;
- copy;
- move;
- rename;
- create directories;
- inspect metadata;
- calculate hashes;
- compare files;
- detect recent versions;
- safe deletion.

Large destructive file operations should receive additional safeguards.

---

## 12. Shell / Process Tools

Provide controlled execution of:

- PowerShell;
- CMD where necessary;
- Python;
- Git;
- Node/npm;
- installed CLI tools;
- WSL/bash if present.

Capture:

- command;
- stdout;
- stderr;
- exit code;
- duration;
- process ID;
- timeout state.

Support long-running processes.

Jarvis must be able to inspect running processes and determine whether commands are still active.

---

## 13. Python Environment

Allow Jarvis to:

- create scripts;
- run scripts;
- create virtual environments;
- install project dependencies;
- inspect Python environments;
- parse structured results.

Prefer isolated project environments rather than modifying global Python unnecessarily.

---

## 14. Browser Architecture

Use a hybrid browser system.

Two principal modes:

Deterministic browser backend

Use Playwright.

Use when:

- selectors are known;
- workflow is known;
- task is repetitive;
- API/DOM is stable;
- a reusable workflow exists.

Intelligent browser backend

Use Browser Use where appropriate.

Repository:

https://github.com/browser-use/browser-use

Use when:

- the website is unfamiliar;
- the interface requires discovery;
- controls change;
- navigation requires reasoning;
- unexpected UI must be interpreted;
- recovery is required.

Browser Use must not replace Playwright.

Desired relationship:

Jarvis Browser Router
        │
        ├── API
        ├── reusable workflow
        ├── Playwright
        ├── Browser Use
        └── visual fallback

---

## 15. Browser Workflow Learning

Investigate BrowserCode and related approaches.

Desired long-term behavior:

First execution:

«"Publish this article in this CMS."»

Jarvis may use intelligent browser reasoning to discover the interface.

After succeeding, Jarvis should be able to record enough structured information to later create a reusable procedure.

Example:

"publish_article(title, content, image)"

Future runs can then use a deterministic procedure.

Advantages:

- fewer model calls;
- faster execution;
- lower context usage;
- lower failure rate;
- less UI rediscovery.

Do not automatically convert every browser interaction into a skill.

Promote workflows when they are repeated and stable.

---

## 16. Windows Computer Control

Do not reinvent Windows desktop automation from scratch if mature components can be reused.

Evaluate:

Microsoft UFO / UFO²

Repository:

https://github.com/microsoft/UFO

Investigate especially:

- HostAgent/AppAgent concepts;
- Windows UI Automation;
- Win32 interaction;
- COM;
- Office integration;
- application-specific agents;
- screenshots;
- MCP;
- execution architecture.

Jarvis remains the main orchestrator.

Use UFO components only where they materially improve Windows execution.

---

## 17. Cua / trycua

Evaluate:

https://github.com/trycua/cua

Potential advantages:

- Windows computer-use;
- accessibility tree access;
- UI Automation/MSAA;
- synthetic interaction;
- background interaction;
- screenshots;
- mouse/keyboard;
- control-value inspection.

Prefer accessibility/semantic interaction rather than visual coordinate clicking.

Potential target abstraction:

"ComputerUseBackend"

Possible implementations:

- "NativeWindowsBackend"
- "UFOBackend"
- "CuaBackend"

Jarvis should select or fall back between them automatically.

---

## 18. Native Windows Automation

Maintain native Windows tooling where it is more deterministic than agent frameworks.

Potential technologies:

- Windows UI Automation;
- pywinauto;
- Win32 APIs;
- COM;
- application-specific APIs;
- PowerShell;
- WMI/CIM.

Priority:

API
↓
COM
↓
CLI
↓
UI Automation
↓
UFO/Cua
↓
vision
↓
coordinate interaction

---

## 19. Microsoft Office

If Microsoft Office is installed, support:

- Word;
- Excel;
- PowerPoint.

Prefer COM automation where practical.

Jarvis should eventually be able to:

- read documents;
- edit documents;
- preserve formatting;
- save versions;
- export PDFs;
- modify spreadsheets;
- create spreadsheets;
- manipulate slides;
- verify that files reopen successfully.

Potentially destructive document edits should preserve the source or create a backup unless the task clearly requires in-place editing.

---

## 20. Open Interpreter

Evaluate:

https://github.com/openinterpreter/open-interpreter

Potential uses:

- shell execution;
- coding;
- environment handling;
- tool execution;
- MCP;
- computer interaction.

Do not replace Jarvis with Open Interpreter.

Use it behind an adapter if it is stronger for a particular task.

Possible:

"OpenInterpreterWorker"

Simple deterministic execution should remain native.

---

## 21. OpenHands

Evaluate:

https://github.com/All-Hands-AI/OpenHands

Use primarily as a specialist software-engineering worker.

Appropriate tasks:

- large repository modifications;
- complex debugging;
- substantial feature development;
- repository-level refactoring;
- large test/fix cycles.

Possible abstraction:

"SoftwareEngineeringWorker"

with implementations such as:

- internal coding worker;
- OpenInterpreter worker;
- OpenHands worker.

Jarvis remains responsible for final verification.

If OpenHands says:

«fixed»

Jarvis must still inspect/test the result itself.

---

## 22. Agent-S / Agent-S3

Study:

https://github.com/simular-ai/Agent-S

Useful concepts to investigate:

- hierarchical planning;
- trajectory memory;
- GUI grounding;
- recovery;
- long-horizon execution;
- best-of-N planning;
- repeated task improvement.

Integration of the entire framework is not required.

Borrow useful ideas where they improve Jarvis.

---

## 23. Worker Abstraction

Avoid monolithic dependencies.

Use adapters.

Example:

BrowserBackend
    PlaywrightBackend
    BrowserUseBackend

ComputerUseBackend
    NativeWindowsBackend
    UFOBackend
    CuaBackend

CodeAgentBackend
    NativeAgentBackend
    OpenInterpreterBackend
    OpenHandsBackend

InferenceBackend
    LlamaCppBackend
    LMStudioBackend
    OllamaBackend
    RemoteOpenAICompatibleBackend

External projects should be loosely coupled.

Prefer:

- packages;
- subprocess APIs;
- local servers;
- MCP;
- clean adapters;

over copying thousands of lines of third-party code.

---

## 24. Third-Party Integration Rules

Before integrating any major dependency:

1. inspect current upstream project;
2. inspect license;
3. inspect maintenance status;
4. inspect Windows support;
5. inspect local-model compatibility;
6. inspect whether cloud services are required;
7. inspect dependency footprint;
8. inspect security implications;
9. determine whether integration actually improves Jarvis.

Do not integrate software simply because it exists.

Ask internally:

Does this materially improve:

- reliability;
- capability;
- maintainability;
- autonomy?

If not, keep the existing implementation.

---

## 25. Graceful Degradation

Optional workers must not make the entire platform fragile.

Examples:

If UFO unavailable:

→ use Cua/native UI automation.

If Browser Use unavailable:

→ use Playwright.

If OpenHands unavailable:

→ use internal code worker.

If vision unavailable:

→ use structured APIs/DOM/accessibility where possible.

The Tools/System interface should display backend availability.

---

## 26. Execution Modes

Jarvis should support three main execution modes.

Fast

For simple tasks.

Characteristics:

- minimal planning;
- deterministic tools;
- fewer model calls;
- basic verification.

Examples:

- rename a file;
- run a known command;
- summarize a small document.

Balanced

Default.

Lifecycle:

plan
→ execute
→ observe
→ correct
→ verify

Use this for most tasks.

Reliable

For difficult, ambiguous, or long-running tasks.

Characteristics:

- stronger initial planning;
- additional criticism;
- best-of-N planning where useful;
- stronger verification;
- alternate strategies;
- more persistent recovery.

This mode prioritizes success over speed.

These are agent execution modes. They are distinct from model profiles (Fast / Balanced / Quality), which change quantization, thinking, and context size.

---

## 27. Best-of-N Reasoning

For Reliable mode, support generating multiple candidate strategies where useful.

Do not blindly execute several complete attempts.

Best-of-N is most useful for:

- initial planning;
- ambiguous architecture;
- repeated failures;
- consequential decisions;
- difficult GUI interactions.

Example:

Plan A
Plan B
Plan C
   │
   ▼
Critic
   │
   ▼
Best plan

The same Qwen model may initially act as both planner and critic.

Architecture should allow separate models later.

---

## 28. Model Roles

Initially Qwen3.5-27B can perform all roles.

Architecture should eventually support:

- Router;
- Planner;
- Executor;
- Critic;
- Verifier;
- Vision model;
- Coding specialist;
- fast small model.

Do not require multiple models for initial operation.

---

## 29. Recovery Behavior

Failures are expected.

Jarvis must treat them as observations, not immediate reasons to stop.

Failure workflow:

Action
↓
Failure
↓
Inspect error
↓
Classify cause
↓
Modify strategy
↓
Retry

Do not repeatedly execute exactly the same failing action.

Support:

- bounded retries;
- alternate-tool retries;
- alternate-worker retries;
- browser recovery;
- process recovery;
- environment repair;
- model context recovery.

Only involve the user after reasonable autonomous recovery options have been exhausted or required information truly cannot be obtained.

---

## 30. Verification Engine

Verification is a core Jarvis capability, not an optional extra.

No worker may simply declare itself successful.

Examples:

Software task

After implementation:

- inspect diff;
- run tests;
- build;
- launch;
- inspect logs;
- test relevant behavior.

Website task

After change:

- start application;
- load website;
- perform affected workflow;
- inspect errors;
- verify expected result.

Browser task

After action:

- inspect resulting page;
- confirm expected state;
- verify backend state where possible.

Document task

After editing:

- verify file exists;
- reopen;
- ensure it parses;
- inspect requested modifications.

Installation

After install:

- query version;
- launch;
- perform basic functional test.

A task may only be marked complete after verification.

---

## 31. Persistent Task Memory

Use a durable local database.

SQLite is appropriate initially.

Persist:

- tasks;
- conversations;
- status;
- plans;
- action summaries;
- tool calls;
- outputs;
- errors;
- retries;
- checkpoints;
- worker selection;
- timestamps;
- final result;
- useful execution trajectory.

Users must be able to reopen a previous task and say:

«Continue this.»

Jarvis should reconstruct enough state to continue.

---

## 32. Context Management

Do not continually feed the complete execution history back into the model.

Maintain a compact working state.

Suggested structure:

Current goal
Acceptance criteria
Current plan
Completed steps
Current state
Important observations
Recent tool outputs
Known failures
Current blockers
Next likely action

Old logs remain available in the database.

Compress older history into structured summaries.

This is necessary to prevent long-running tasks from degrading because of context bloat.

---

## 33. Trajectory Memory

Store useful structured execution history.

Examples:

- which worker succeeded;
- which strategy failed;
- why it failed;
- which recovery worked;
- which application workflow was discovered;
- which command sequence solved a problem.

Do NOT store raw hidden chain-of-thought.

Store actionable summaries.

Future tasks should be able to reuse successful trajectories.

---

## 34. Reusable Skills

Jarvis should support reusable workflows/skills.

Example skills:

- "publish_article"
- "build_python_project"
- "export_word_to_pdf"
- "update_website"
- "process_manuscript"
- "generate_social_assets"
- "deploy_application"
- "run_project_tests"

A skill may include:

- description;
- parameters;
- required tools;
- execution steps;
- verification criteria;
- recovery guidance.

Repeated successful workflows may eventually be promoted into skills. When the recorded tool arguments differ across those successes, they become parameters and the skill executes the bound steps itself instead of only advising the model.

Do not create skills indiscriminately.

---

## 35. MCP

Support Model Context Protocol.

Allow configuration of:

- stdio servers;
- HTTP MCP servers.

Potential integrations:

- filesystem;
- GitHub;
- databases;
- APIs;
- web/fetch;
- time;
- internal systems.

Secrets must never be hard-coded into source.

---

## 36. Web Portal

Build a polished local web portal.

Suggested stack:

Backend:

- Python;
- FastAPI;
- Pydantic;
- SQLAlchemy;
- SQLite;
- WebSocket or SSE.

Frontend:

- React;
- TypeScript;
- Vite or similarly lightweight stack.

Do not unnecessarily over-engineer.

---

## 37. Main Task Interface

Primary screen should have a large command input.

Display useful current status:

- task name;
- model;
- execution mode;
- task stage;
- current action;
- active tool;
- active worker;
- elapsed time;
- retries;
- recent observations;
- status.

Stream activity live.

---

## 38. User-Visible Execution Timeline

Show actions such as:

Planning task
↓
Inspecting repository
↓
Running tests
↓
Tests failed
↓
Analyzing failure
↓
Editing configuration
↓
Running tests
↓
Tests passed
↓
Launching application
↓
Opening browser
↓
Verifying login
↓
Task complete

Do not expose hidden chain-of-thought.

Tool calls may have expandable details showing:

- action summary;
- backend;
- stdout;
- stderr;
- exit code;
- duration.

---

## 39. Task History

Provide task history with:

- title;
- created date;
- last activity;
- status;
- duration;
- worker/backend;
- result.

Allow reopening and continuing tasks.

---

## 40. Model Page

Display:

- model;
- quantization;
- inference backend;
- context size;
- GPU offload;
- VRAM usage;
- RAM usage;
- tokens/sec;
- load status;
- persisted benchmark history (tok/s, VRAM, RAM, task success rate).

Support profiles:

- Fast;
- Balanced;
- Quality.

---

## 41. Tools Page

Display available tools and workers.

Allow enabling/disabling optional capabilities.

Examples:

- filesystem;
- PowerShell;
- Python;
- browser;
- Browser Use;
- Windows automation;
- UFO;
- Cua;
- OpenHands;
- Open Interpreter;
- MCP.

Unavailable optional tools should be clearly indicated rather than crashing Jarvis.

---

## 42. Workflows & Instructions Guide Tab

Provide an interactive guide and workflow launcher tab in the Web Portal.

Capabilities:
1. **Instructions Guide**: Clear step-by-step operating instructions for how to interact with Jarvis (Command bar, Execution modes, Private key setup, Launch queue, and Memory/Skills).
2. **Pre-built Workflow Library**: Curated, ready-to-load example workflows for common tasks (e.g. codebase debugging, research to summary/spreadsheet, web scrapers, batch file organization, multi-step maintenance jobs).
3. **Interactive Workflow Editor**: Allow users to load any template into an editable builder, customize parameters (e.g., target paths, URLs, criteria, execution mode, autonomy level), chain sub-prompts or sequential events, and run them with one click.
4. **Custom Workflow Presets**: Enable saving edited custom workflows locally to `data/workflows/` or database for rapid repeat execution.

---

## 43. Settings

Provide settings for:

- autonomy mode;
- reasoning mode;
- allowed working directories;
- retry limit;
- default timeout;
- backup policy;
- inference profile;
- browser settings;
- logging.

Keep sensible defaults.

The user should not need to configure ordinary settings before Jarvis works.

---

## 43. API-First Design

The portal should communicate with a clean local API.

Minimum concepts:

POST /api/tasks
GET /api/tasks
GET /api/tasks/{id}
POST /api/tasks/{id}/continue
POST /api/tasks/{id}/cancel

GET /api/system
GET /api/model
GET /api/tools

POST /api/model/load
POST /api/model/unload

Use WebSocket/SSE for live events.

This enables future:

- Android app;
- phone control;
- voice interface;
- scheduled automations;
- external local applications.

---

## 44. Future Voice Interface

The architecture should eventually support:

speech
↓
Whisper/STT
↓
Jarvis API
↓
Qwen
↓
tools
↓
local TTS
↓
spoken response

Do not let voice implementation delay core Jarvis functionality.

A basic microphone button can be added later if straightforward.

---

## 45. Permissions / Autonomy

Support execution profiles such as:

Interactive

Ask before consequential operations.

Trusted

Automatically execute normal work.

Ask for genuinely high-impact operations.

Autonomous

Allow long-running tasks without repeated interaction.

Even Autonomous mode should pause before clearly consequential actions such as:

- disk formatting;
- deleting partitions;
- destroying backups;
- mass deletion outside task scope;
- credential changes;
- financial transactions;
- purchases;
- disabling important system security controls;
- publishing/sending something externally when not clearly authorized by the original task.

These boundaries exist to prevent accidental autonomous mistakes.

They should not become broad content moderation.

---

## 46. Git / Recoverability

For development work:

- inspect Git state;
- preserve unrelated user changes;
- use diffs;
- create checkpoints before major risky refactors;
- run tests after changes.

Do not leave repositories casually broken.

Jarvis itself should also use safe recoverability mechanisms.

---

## 47. Backups

Potentially destructive operations should create recoverable states when appropriate.

Examples:

- document editing;
- mass file changes;
- configuration changes;
- large code refactors.

Avoid excessive unnecessary backups.

---

## 48. Startup

Provide a simple launcher.

On Windows, preferably:

"start-jarvis.ps1"

It should:

1. verify environment;
2. start inference;
3. start backend;
4. start frontend;
5. open web portal;
6. provide meaningful error output.

Also provide clean shutdown.

Optional future:

start automatically after Windows login.

Do not enable autostart without making it clear.

---

## 49. Security / Networking

Default bind:

"localhost"

Do not publicly expose Jarvis.

LAN access may later be configurable.

If LAN access enabled:

- require authentication;
- bind deliberately;
- document firewall behavior.

Secrets belong in:

- environment variables;
- secure local secret storage.

Never commit credentials.

---

## 50. Initial Test Suite

Maintain end-to-end tests demonstrating actual autonomous ability.

Test 1 — Filesystem

Request:

«Create a folder named Jarvis-Test on the desktop and write a text file containing the current system specifications.»

Verify file exists and contents are correct.

Test 2 — Python

Request:

«Create a Python program calculating the first 100 prime numbers, execute it, and save the result.»

Verify result.

Test 3 — Browser

Request:

«Open a harmless public website, determine its page title and save it to a file.»

Verify result.

Test 4 — Autonomous Debugging

Create a deliberately broken small project.

Request:

«Find out why this project fails, fix it and verify the fix.»

Do not tell Jarvis the cause.

Jarvis must independently diagnose and repair it.

Test 5 — Vision

Give Jarvis a screenshot/image.

Verify the local model can interpret it.

Test 6 — Failure Recovery

Cause a deliberate command/tool failure.

Jarvis must:

- inspect;
- correct strategy;
- retry;
- succeed or give a justified failure.

Test 7 — Persistence

Start a task.

Restart Jarvis.

Verify task remains available.

Test 8 — Mixed Long-Horizon Task

Use a task requiring several tool categories.

Example:

- inspect project;
- modify code;
- start program;
- use browser;
- verify result.

Measure whether human intervention was necessary.

---

## 51. Benchmarking

Record useful operational metrics.

For model:

- model load time;
- tokens/sec;
- prompt processing;
- VRAM;
- RAM;
- context size.

For agent tasks:

- completion success;
- execution duration;
- model calls;
- tool calls;
- retries;
- worker used;
- human interventions;
- verification result.

Reliability matters more than small speed improvements.

---

## 52. Development Philosophy

Do not chase theoretical architecture forever.

The priority is a working system.

For every change:

1. implement;
2. run;
3. inspect;
4. test;
5. debug;
6. verify;
7. record current state.

Do not stop after creating scaffolding when working functionality is achievable.

Do not leave TODOs for core capabilities simply because they are difficult.

---

## 53. Current Development Strategy

Do not rewrite the entire project merely because this document introduces improved architecture.

First audit existing code.

Preserve working functionality.

Refactor incrementally.

Priority order:

1. stable Jarvis core and mandatory verification/recovery;
2. P0 fast/reliable local-model migration, Windows inference verification, and benchmarking;
3. dynamic context/tool/thinking behavior and model escalation;
4. P1 autonomous software-development worker routing, Cursor ACP, isolated self-development, and the one-day trial;
5. P2 swarm-ready abstractions from `SWARM_ARCHITECTURE.md` on the existing single machine;
6. deterministic filesystem/shell/Python and Playwright reliability;
7. Browser Use and Windows semantic-computer-control improvements;
8. optional specialist workers such as OpenHands/Open Interpreter/UFO/Cua where they materially improve reliability;
9. reusable skills, trajectory learning, and operational benchmarking improvements;
10. P3 multi-node swarm only after the P2 single-node placement abstractions are sound;
11. voice/phone and other product capabilities according to the active Development Queue;
12. P4 swarm resilience and deferred specialized infrastructure only when explicitly promoted.

---

## 54. Incremental Autonomous Development

This project will be developed over many Cursor sessions.

The user may configure automation to repeatedly trigger Cursor.

Every development run should begin by reading this file.

Then:

1. inspect Git status;
2. inspect current project;
3. read the Current State section below;
4. read the Development Queue below;
5. select the highest-value actionable task;
6. implement it;
7. test it;
8. diagnose failures;
9. continue until a meaningful increment is complete;
10. update Current State;
11. update Development Queue;
12. update architectural sections only when requirements change;
13. leave a recoverable project state.

Do not depend on the previous chat session being available.

This file and the repository are the persistent development memory.

---

## 55. New Requirements From User

When the user gives a new requirement:

1. determine whether it is:
   - product requirement;
   - architecture requirement;
   - feature request;
   - bug;
   - priority change;
   - future idea;
2. add it to the appropriate section of this document;
3. adjust the Development Queue;
4. implement it when appropriate.

The user should be able to say something simple such as:

«Eventually I want Jarvis accessible from my phone.»

Cursor should update this plan appropriately without requiring the user to rewrite architecture documents.

---

## 56. Documentation Maintenance

This file should remain useful rather than endlessly growing.

Do not dump:

- raw logs;
- full chat transcripts;
- chain-of-thought;
- enormous console outputs.

Summarize.

Keep durable information:

- architecture;
- decisions;
- requirements;
- state;
- blockers;
- priorities;
- test status.

Refactor this document periodically if it becomes unwieldy.

---

## 57. CURRENT STATE

Audited from the repository in this session. Windows hardware and live Qwen inference were **not** re-verified here (this Cursor environment is Linux and has no GGUF / llama-server.exe). Only mark something working if the code exists and, where possible, tests passed.

### Hardware

Target desktop (from README; not probed this session):

- OS: Windows 11 Pro
- CPU: Intel Core i7-14700KF
- RAM: 64 GB
- GPU: NVIDIA GeForce RTX 5070 Ti
- VRAM: 16 GB
- Storage: not recorded
- CUDA/driver: CUDA 13.0 reported; llama.cpp Windows CUDA 13.3 build b10516

This development session:

- OS: Linux (Cursor cloud agent)
- GPU: none detected in this environment
- Model binaries: not present (`models/` and `runtime/llama.cpp/` are gitignored)

### Model

- Model: **Qwen3.5-9B Abliterated** is the default Fast/Balanced/Quality profile (GGUF `Abiray/Qwen3.5-9B-abliterated-GGUF` of `wangzhang/Qwen3.5-9B-abliterated`). **Qwen3.5-27B Q4_K_M** is the Expert escalation profile and the fallback when 9B files are missing.
- Quantization: Fast Q6_K (8K, thinking off); Balanced Q8_0 (16K, selective thinking); Quality Q8_0 (32K, thinking on); Expert 27B Q4_K_M (32K, thinking on)
- Backend: `InferenceBackend` abstraction. `LlamaCppBackend` starts and supervises `llama-server`; `RemoteOpenAICompatibleBackend` health-checks a server Jarvis does not own (LAN GPU box, LM Studio, Ollama, vLLM, SGLang). Selectable via `inference_backend` / `inference_host` / `inference_port` on `PUT /api/settings`.
- Context: 8K fast, 16K balanced, 32K quality/expert; load failure retries at 16K
- Vision: projector is **not** attached unless `inference.vision` is true (Settings toggle)
- GPU offload: `--fit on` with `--fit-target 1024`
- Tokens/sec: not measured this session
- Status: **code present and unit-tested, Windows runtime not verified this session**

### Core Application

- Backend: Python FastAPI (`backend/app`), served on `127.0.0.1:4780`
- Frontend: React + TypeScript + Vite, built into `frontend/dist` and served by FastAPI
- Database: SQLite `data/jarvis.db` (tasks, events, tool calls, checkpoints)
- Startup: `start-jarvis.ps1` / `stop-jarvis.ps1`
- Status: **working application skeleton with real APIs, agent loop, tools, and portal**

### Working Tools

- Filesystem: implemented (list/search/read/write/edit/copy/move/rename/mkdir/delete/hash/stat/compare/recent, backups, allowed-directory sandbox)
- PowerShell: implemented as default `terminal` shell (CMD/Python/Git/WSL/bash also supported). `start` backgrounds a command and returns a PID; `inspect`/`wait`/`kill` check whether it is still alive. Python snippets use `python -c`.
- Python: implemented (`run_code`, `run_file`, `create_venv`, `install`); venv lookup checks Windows `Scripts` and Unix `bin`
- Browser: Playwright Chromium (accessibility snapshot, click/type, screenshot, tabs) — default `BrowserBackend`
- Playwright: native backend present
- Browser Use: **adapter integrated** (`browser_use` tool). Status is `missing` until the package is installed; Playwright remains default
- Windows UI: `desktop` tool (pywinauto / screenshot); Windows-only at runtime
- Office: Word/Excel/PowerPoint. Windows COM when Office is installed; python-docx / openpyxl / python-pptx otherwise. Paths are sandboxed.
- Git: status/diff/branch/log/search plus non-destructive `jarvis-checkpoint-*` backup branches (`checkpoint` / `list_checkpoints` / `restore`)
- Docker: optional; `run`/`logs`/`inspect` require an image or container
- Web fetch: HTTP GET/POST/HEAD with optional body, headers, and sandboxed download
- Vision: screenshot tool + llama.cpp `--mmproj`; not verified this session
- MCP: stdio and HTTP/streamable-http client; secrets not stored in git
- Voice: local Whisper STT (when installed) + Windows SAPI / espeak-ng / pyttsx3 TTS wrapping `/api/voice/command` and `/api/voice/listen`

### Optional Workers

- Browser Use: **adapter present** (catalog `missing`/`ready`; MIT; local OpenAI-compatible endpoint only)
- UFO: **not integrated**
- Cua: **not integrated**
- Open Interpreter: **not integrated**
- OpenHands: **adapter present** (`code_worker`; catalog `missing`/`ready`; Jarvis still verifies)

### Jarvis 2.0

- Specification: **appended** as sections 64–85 (Autonomous Operator / Away Mode)
- Event-driven intake, `SoftwareEngineeringWorker`, isolated worktrees, CI/CD control, policy engine, production self-healing, remote/mobile control, marketing/SEO/novel/multimedia workers, `Node` registry / Worker placement / GPU scheduler: **not implemented**
- Flagship benchmark `Away Mode — Autonomous Bug Fix`: **not implemented**
- Hardware Stage 1 remains the existing desktop; no new GPU is required to continue development

### Persistence

- Task storage: SQLite, including conversation JSON and tool-call records
- Resume: `POST /api/tasks/{id}/continue` reloads compacted conversation
- Context compaction: older turns collapse into a structured summary that cannot orphan a tool result from its assistant `tool_calls` turn; the compact working state is refreshed (not stacked) on every pass
- Trajectory memory: `trajectories` table stores ordered tools, failure kinds, the recovery that worked, and verification. Similar new tasks get those lessons injected. No hidden reasoning is stored.
- Skills: `skills` table. A workflow is promoted only after the same task class succeeds 3+ times with the same tool sequence. Differing tool arguments become parameters; a matching later task **runs those bound steps**, then verifies. Browser procedures that use named controls or CSS selectors (not snapshot ids) promote as BrowserCode-style skills (`origin=browser_promoted`) and are replayed instead of rediscovering the page. Password-like fields are parameterized with no stored examples and do not auto-run. `POST /api/memory/skills/{id}/run` executes a skill without waiting for the model.

### Reliability

- Retry engine: identical-call blocking plus per-tool failure counting
- Verification engine: **implemented** — a task cannot complete until an independent verification pass runs; Reliable mode requires a verification tool call
- Failure recovery: **implemented** — failures are classified (permission, missing capability, not found, timeout, usage, network, blocked) and answered with alternatives ordered by determinism; permission/blocked failures deliberately suggest no alternative tool
- Fast / Balanced / Reliable agent execution modes: **implemented**. Model Fast/Balanced/Quality/Expert are separate from those agent modes. Balanced model profile uses selective thinking (planning and recovery only).
- Reliable mode also generates three candidate plans and a critic selects one before execution
- Task classification: keyword-scored classifier stored on the task; that class also selects the tool subset sent to the model (`request_capability` is the escape hatch)
- Acceptance criteria / plan: parsed from the first planning turn and persisted

### Documentation

- Operator + contributor guides for the current tree: `docs/INSTALL.md` (Windows install, llama.cpp, GGUFs, start/stop, LAN auth) and `docs/DEVELOPMENT.md` (repo map, API, agent loop, tools, tests). `README.md` is the landing page and points at those files.

### Portal / API

- Command, History, Guide & Workflows, Memory, Model, Tools, MCP, Settings, System pages exist
- Guide & Workflows has operating instructions, six editable templates, parameter/stage editing, local presets in `data/workflows/`, and 1-click task dispatch
- Model page persists tok/s, VRAM, RAM, load time, and task success rate (`benchmark_samples`; `GET /api/model/benchmarks`). Profiles listed: Fast, Balanced, Quality (9B), Expert (27B). Vision and thinking mode are visible.
- Live status shows execution mode, task class, and verification
- Live elapsed time is anchored to `started_at` so reopening a running task does not reset the clock
- Memory page lists skills and trajectories with promote / enable / run controls
- Tools/System pages list optional workers; Browser Use and OpenHands show `missing` until installed
- Launch queue: `data/queue/pending/` watched in real-time, `.\start-jarvis.ps1 -Prompt ... -Wait` support
- Security: Private key authentication enforced across REST (`Authorization: Bearer`, `X-Jarvis-Key`, or `?key=`) and WebSockets for remote / LAN exposure
- Voice: Command Speak button; `POST /api/voice/listen` transcribes locally; `POST /api/voice/speak` returns WAV; JSON `/api/voice/command` still accepts text

### Known Problems

- Live Qwen3.5-9B / 27B load, tool-calling, and Windows e2e suite have never been run from a Cursor session (no GPU/GGUF here)
- 9B GPU residency, tok/s, and 20-task comparison vs 27B are still Windows-desktop work
- Best-of-N planning is implemented for Reliable mode (three candidates, critic selects one; does not run several complete attempts)
- Browser Use / OpenHands adapters are present but the optional packages are not installed in this environment
- UFO / Cua / Open Interpreter adapters are absent
- Full e2e suite (`tests/run_e2e.py`) requires the Windows desktop install
- Office COM and Docker depend on software that may be missing on the target PC
- Cursor ACP CLI is not on PATH in this environment; the client is catalogued `not_connected`
- Terminal default is PowerShell on Windows and bash on Linux

### Last End-to-End Test

Date: 2026-08-25

Tests performed:

- Unit tests (`python -m pytest tests -q`): planning including best-of-N parse/select, Reliable-mode plan selection loop, safety, filesystem sandbox plus compare/recent, capability catalog, verification loop, persistence checkpoint, compaction tool-pairing, inference backend selection and llama.cpp command building, **9B/27B profiles and 9B→27B fallback**, **task-class tool exposure and selective thinking**, failure classification and recovery routing, trajectory record/recall, skill promotion **and parameterized execution**, private key authentication, launch queue watcher, workflow templates/save/run, terminal start/inspect/wait/kill, model benchmark persistence, docker run-requires-image, browser close reset
- Frontend (`npm run build`): TypeScript build
- Portal: Command, Tools (`code_worker`, Open Interpreter `missing`), Guide (`browser-form` / `browser-procedure`), Settings Inference card (Ollama port 11434), Model Probe, System backends

Results: **90 passed** on this tree. Live Qwen/Windows e2e remains the next desktop-session P0.

---

## 58. DEVELOPMENT QUEUE

Statuses: TODO, IN PROGRESS, BLOCKED, VERIFIED

Priority: P0 core blocker, P1 major capability/reliability, P2 swarm-ready/foundation or useful improvement, P3 multi-node/future capability, P4 resilience/advanced long-term infrastructure.

### P0

- [x] Persistent source-of-truth plan (`JARVIS_MASTER_PLAN.md`)
  - Acceptance: file exists at repo root and is the Cursor session bootstrap.
  - Status: VERIFIED (added this session)

- [x] Stable Jarvis core (API + portal + agent runtime)
  - Acceptance: FastAPI app, React portal, task create/list/get/continue/cancel.
  - Status: VERIFIED (code present; unit-tested orchestration)

- [x] Persistent task execution
  - Acceptance: task rows and conversation survive process restart / DB reload.
  - Status: VERIFIED in unit test (`test_task_survives_restart_checkpoint`)

- [x] Verification loop
  - Acceptance: task cannot be marked successful without an independent verification pass.
  - Status: VERIFIED in unit tests with a scripted model (`python -m pytest tests -q` → 12 passed). Also fixed SQLite timezone-aware duration calculation so completion no longer crashes.

- [x] Qwen3.5-9B Abliterated profiles as the default Fast/Balanced/Quality stack; 27B kept as Expert
  - Acceptance: profiles exist; Balanced is default 9B Q8_0 16K selective thinking; Fast is 9B Q6_K 8K thinking off; Quality is 9B Q8_0 32K thinking on; Expert is 27B Q4_K_M; missing 9B GGUF falls back to 27B; vision projector is opt-in.
  - Status: VERIFIED in unit tests (`test_profiles.py`, `test_inference_backends.py`). Live GPU residency **BLOCKED** in this environment.

- [x] Dynamic / selective thinking (P0.4)
  - Acceptance: Balanced spends reasoning tokens on the first planning turn and on recovery, not on every tool follow-up; Fast never thinks; verification is non-thinking.
  - Status: VERIFIED (`test_tooling.py`)

- [x] Dynamic tool exposure (P0.7)
  - Acceptance: task class selects a tool subset; `request_capability` (and calling an unlisted real tool) expands it.
  - Status: VERIFIED (`test_tooling.py`)

- [ ] Reliable Qwen3.5-9B (and Expert 27B) local inference on the Windows desktop
  - Acceptance: 9B Q8_0 loads GPU-resident, API responds, tool calls work; Expert 27B still loads; vision projector loads only when enabled.
  - Status: TODO (code present; **BLOCKED in this environment** — no Windows GPU/GGUF). Next Windows session must run `tests/run_e2e.py` and measure tok/s / VRAM.

### P1

- [x] Fast / Balanced / Reliable agent execution modes
  - Acceptance: setting exists; Reliable requires verification tools; Fast uses a shorter loop.
  - Status: VERIFIED in unit tests

- [x] Capability catalog for optional workers
  - Acceptance: Tools/System UI shows Browser Use/UFO/Cua/OpenHands/OI as unavailable rather than crashing.
  - Status: VERIFIED (code + API)

- [x] Strengthen failure recovery (alternate tool/worker, not only identical-call blocking)
  - Acceptance: a failed browser path can fall back to web_fetch/library without repeating the same call.
  - Status: VERIFIED in unit tests (`test_recovery.py`, `test_recovery_loop.py`)

- [x] Context compaction quality
  - Acceptance: long tasks keep a compact working-state block, do not dump full tool traces, and never orphan a tool result.
  - Status: VERIFIED in unit tests (`test_compaction.py`)

- [x] Extract `InferenceBackend` from `InferenceManager`
  - Acceptance: llama.cpp process manager is one backend; any other OpenAI-compatible server is health-checked only.
  - Status: VERIFIED in unit tests (`test_inference_backends.py`); live LAN endpoint untested

- [x] Interactive Guide & Workflow Launcher Tab (Instructions, Example Library & Custom Event Chains)
  - Acceptance: New "Guide & Workflows" tab in the web portal containing clear usage instructions, pre-populated editable templates (e.g., project debugging, research + Excel export, multi-file transforms, browser workflows), an editor allowing prompt parameters / event chains customization, and 1-click execution dispatch.
  - Status: VERIFIED (portal tab + `/api/workflows` + unit tests)

- [x] Browser Use adapter
  - Acceptance: optional intelligent browser worker behind `BrowserBackend`; Playwright remains default.
  - Status: VERIFIED in unit tests (`test_workers.py`); package optional — catalog shows `missing` until installed

- [ ] Playwright reliability on the target PC
  - Acceptance: e2e Test 3 (example.com title) passes without human help.
  - Status: CODE PRESENT / unit-tested (`test_browser.py`): navigation retries, named-role click fallback, `title` action, close/missing-URL do not launch Chromium. Live Windows e2e Test 3 still TODO.

- [ ] Windows semantic UI automation hardening
  - Acceptance: named-control interaction works for at least one native app; coordinate click remains last resort.
  - Status: CODE PRESENT / unit-tested (`test_desktop.py`): title/auto_id/best_match lookup; missing name does not fall through to coordinates; non-Windows returns unavailable. Live native-app verification still TODO on Windows.

- [x] OpenHands worker adapter
  - Acceptance: large repo tasks can be delegated; Jarvis still verifies.
  - Status: VERIFIED in unit tests (`test_workers.py`); package optional — catalog shows `missing` until installed; native filesystem/python/git remain the fallback

- [x] Jarvis MCP server for Cursor
  - Acceptance: Cursor can attach to a limited Jarvis MCP server for plan/task/architecture/trajectory context; recursive self-dispatch is refused.
  - Status: VERIFIED in unit tests (`test_mcp_server.py`; `GET /api/mcp/jarvis`, `python3 -m app.mcp_stdio`)

- [x] EscalationContext packaging
  - Acceptance: after repeated coding-tool failures Jarvis stores a compact package (goal, criteria, files, diff, failures) instead of dumping the raw transcript.
  - Status: VERIFIED in unit tests (`test_escalation.py`)

- [x] Cursor ACP session lifecycle (without live CLI)
  - Acceptance: JSON-RPC initialize/session/prompt/cancel, persisted session IDs, auto-answer for isolated routine `cursor/ask_question` and `cursor/create_plan`; consequential decisions stay with the user.
  - Status: VERIFIED in unit tests (`test_acp.py`). Live `agent acp` remains `not_connected` until Cursor CLI is on PATH.

### P2

- [x] Reusable skills — VERIFIED (`test_skills.py`); promotion needs 3 repeats of the same tool sequence
- [x] Trajectory memory (cross-task) — VERIFIED (`test_trajectory.py`)
- [x] Best-of-N planning for Reliable mode — VERIFIED (`test_best_of_n.py`, `test_planning.py`); three labeled candidates, critic selects one, only that plan is executed
- [x] Compare-files / recent-version filesystem helpers — VERIFIED (`test_filesystem.py`); `compare` unified-diffs text / hashes binaries; `recent` lists `.bak` copies
- [x] Parameterized skill execution — VERIFIED (`test_skills.py`); bound steps run on matching tasks and via `POST /api/memory/skills/{id}/run`
- [x] Model benchmark UI (persist tok/s, VRAM, success rates) — VERIFIED (`test_benchmarks.py` + Model page history)
- [x] Office COM coverage when Office is installed
  - Acceptance: Word/Excel/PowerPoint create/read/write/save_as/append/info; COM when Office is present; library backend otherwise; sandbox enforced.
  - Status: VERIFIED in unit tests (`test_office.py`). Live COM on a Windows Office install was not exercised in this environment.
- [x] Long-running process inspection (PID still alive) — VERIFIED (`test_terminal.py`; terminal `start`/`inspect`/`wait`/`kill`)
- [x] Git recoverable checkpoints — VERIFIED (`test_git.py`); `checkpoint` creates `jarvis-checkpoint-*` without removing working-tree changes; `restore` overlays without switching branch
- [x] web_fetch research completeness — VERIFIED (`test_web_fetch.py`); POST body, headers, sandboxed download, http(s) only

#### P2 — Swarm-ready foundation (`SWARM_ARCHITECTURE.md`)

These items make the existing machine a one-node swarm first. They must not require a second computer. Detailed role/resource/UI semantics live in `SWARM_ARCHITECTURE.md`.

- [ ] Introduce first-class `Node` identity/state separate from software Worker abstractions.
- [ ] Preserve software workers (`LocalJarvisCodingWorker`, `CursorACPWorker`, browser/media workers, etc.) as services that execute on eligible Nodes.
- [ ] Separate Orchestrator (control plane) from Leader (strongest general-purpose execution Node).
- [ ] Generalize capability registration so Nodes and Workers advertise capabilities and requirements.
- [ ] Implement node role/class policy: `AUTO`, `PREFERRED`, `FORCED`, `AVOID`, `DISABLED`, including persistence and failover intent without implementing distributed failover yet.
- [ ] Implement host resource budgets, hard/soft caps, reserved capacity, task priority, and resource-lease representation (CPU/RAM/GPU/VRAM/storage/network where meaningful).
- [ ] Implement a single-node placement scheduler that selects an eligible Node from requirements even when only `localhost` exists.
- [ ] Keep intelligence selection separate from physical placement: choose the Worker/model first or jointly, then select the eligible Node based on capability, policy, locality, load, and resource availability.
- [ ] Add model/worker warm-state and data-locality signals to placement scoring so the scheduler does not cause pointless model reloads or large transfers.
- [ ] Extend the existing React portal toward the universal dynamic UI contract and add a Swarm settings surface without creating OS-specific frontends.

### P3

- [x] Voice interface (Whisper STT + local TTS wrapping `/api/voice/command`)
  - Status: VERIFIED (`test_workers.py` + Command Speak button). Optional packages; degrades to typed commands when Whisper is missing. Cloud speech APIs are not used.
- [ ] Phone / Android client against the local API
- [ ] Dedicated LAN inference server
- [x] UFO adapter
  - Acceptance: optional Windows HostAgent worker behind `ComputerUseBackend`; native UI Automation remains default; missing install reports `missing` and names the desktop fallback.
  - Status: VERIFIED (`test_workers.py`; package not installed in this environment)
- [x] Cua adapter
  - Acceptance: optional computer-use worker behind `ComputerUseBackend`; missing install reports `missing` and names the desktop fallback.
  - Status: VERIFIED (`test_workers.py`; package not installed in this environment)
- [ ] Open Interpreter adapter
- [ ] Browser workflow promotion (BrowserCode-style skills)

### Jarvis 2.0 — specified, not implemented

Do not start these instead of Windows P0 unless the user asked for Away Mode / 2.0 work.

Phase A — Autonomous Developer:

- [ ] Event/webhook intake with a persistent queue (priorities, retries, backoff, dedup, DLQ, restart-safe processing)
- [ ] Event normalization into internal types (`BUG_REPORTED`, `FEATURE_REQUESTED`, `CI_FAILED`, …)
- [ ] `SoftwareEngineeringWorker` abstraction (`NativeJarvisCodingWorker` first; Codex / Claude Code / OpenHands later)
- [ ] Isolated Git worktrees / disposable environments (never modify the production checkout)
- [ ] Independent verification of worker output (a worker saying "fixed" is never enough)
- [ ] PR generation from isolated work after tests
- [ ] `Away Mode — Autonomous Bug Fix` benchmark harness (skeleton)

Phase B — Production Operator: deployment control, canary, rollback, policy engine, self-healing.

Phase C — Remote Jarvis: Android/mobile client, push, remote approvals, voice as a task/authority interface.

Phase D — Business Operator: marketing, analytics, content publishing, support workflows.

Phase E — Creative Operator: `NovelProject`, editorial workers, multimedia pipeline.

Phase F — Distributed Jarvis: implement the P2/P3/P4 swarm roadmap from `SWARM_ARCHITECTURE.md` (first-class Nodes, software Workers placed on Nodes, resource-aware scheduling, multi-node execution, and later resilience) plus cloud fallback where explicitly authorized.

---

## 59. DECISION LOG

Decision: Jarvis remains orchestrator

External frameworks such as OpenHands, UFO and Browser Use are execution workers rather than the primary application.

Reason:

Maintains a single persistent agent architecture while allowing specialized mature tooling.

Decision: swarm architecture remains a separate authoritative specification

Detailed role, placement, resource-control, node-management, and universal-UI requirements live in `SWARM_ARCHITECTURE.md`. The master plan references that file and owns priority/status rather than duplicating the full swarm specification.

Reason:

The swarm design is large and will evolve independently; keeping one detailed spec prevents the master plan from becoming contradictory or excessively duplicated.

Decision: Orchestrator and Leader are distinct roles

The Orchestrator owns coordination/control-plane responsibilities. The Leader is the strongest general-purpose execution Node and may disappear without taking the control plane down.

Reason:

Control-plane availability must not depend on the most powerful GPU workstation.

Decision: Node and Worker are distinct concepts

A Node is a physical/virtual participating device. A Worker is a software execution service/agent that can run on an eligible Node. Product labels such as Senior Worker and Junior Worker are node execution classes in the swarm spec and should not become competing software-worker types.

Reason:

The existing code already uses worker to mean software agents. Separating placement from execution prevents scheduler and type-system ambiguity.

Decision: one-node swarm first

P2 introduces Node/capability/resource/placement abstractions on the existing desktop before P3 adds discovery, pairing, and remote execution.

Reason:

This makes multi-device support an extension rather than a rewrite while keeping current development focused and testable.

Decision: deterministic tools first

Prefer APIs/CLI/COM/DOM/accessibility over screenshot-based computer use.

Reason:

Higher reliability and lower model/context usage.

Decision: reliability over speed

Default agent behavior should prioritize autonomous completion and verification.

Reason:

User prefers waiting longer for correct completion over frequent intervention.

Decision: keep the existing FastAPI + React + SQLite core

Do not rewrite the project because this plan introduces a richer architecture.

Reason:

The repo already had a working control plane, tool registry, llama.cpp manager, and portal. Incremental completion is faster and safer.

Decision: verification is mandatory in the runtime, not only in the system prompt

The orchestrator injects a verification pass and refuses to mark `completed` until it runs. Reliable mode additionally requires a verification tool call.

Reason:

Prompt-only verification was unused (`VERIFY_PROMPT` was imported but never applied). Models will otherwise declare success after a single tool call.

Decision: agent execution modes are separate from model profiles

Fast/Balanced/Reliable change planning/verification. Fast/Balanced/Quality model profiles change quantization, thinking, and context.

Reason:

A cheap model profile can still run a Reliable agent loop, and a Quality model can run a Fast loop for a rename.

Decision: private key authentication covers all query vectors

When remote or LAN exposure is active, authentication is required on every `/api` REST call, WebSocket live feed, and batch queue trigger via header (`X-Jarvis-Key`, `Authorization: Bearer`) or query param (`?key=`).

Reason:

Remote exposure without query-level authentication allows anyone on the local network or public internet to run arbitrary commands on the host machine. Private keys stored in `data/private_key.sec` or environment variables provide zero-leakage security.

Decision: the Android client is a PWA against the existing local API

Do not wait for a native APK. `/phone` plus `GET /api/mobile` is the first phone client. The pairing payload must never include the private key.

Reason:

Section 43 already treats the REST API as the phone/voice surface. A PWA ships on this tree without Play Store or Android SDK.

Decision: desktop automation stays named-control first

`desktop` inspects and resolves `name` / `automation_id` / control type before any coordinate click. Coordinates are an explicit last-resort fallback.

Reason:

Matches the deterministic-tools-first rule and the P1 semantic UI acceptance criterion.

Decision: a skill requires repetition, not a single success

A workflow is promoted only after the same task class succeeds several times with the same tool sequence.

Reason:

The plan explicitly warns against creating skills indiscriminately. One success is often luck or a one-off path; repetition is the evidence that a workflow is stable.

Decision: parameterized skills execute themselves

When repeated successes record tool arguments, values that differed become `{parameters}` and a matching later task runs those bound steps, then verifies. Skills without recorded arguments still only guide.

Reason:

A skill that only appears in the system prompt is advice. The queue required skills to run, not merely remind the model of a tool order.

Decision: Jarvis 2.0 is an event-driven autonomous operator, not a larger chat window

The 2.0 target is Away Mode: the owner gives objectives and authority boundaries; Jarvis receives events, works continuously, verifies, and contacts the owner only for approval or genuine human input.

Reason:

The user specified this as the long-term product. Command-driven 1.x remains the implementation base; 2.0 extends it with events, workers, policy, and remote supervision.

Decision: specialized agents are workers; Jarvis stays the orchestrator

Coding tools, marketing pipelines, novel editors, multimedia studios, and remote models execute under Jarvis. Jarvis owns planning, authority, verification, and the audit trail.

Reason:

Same as the 1.x worker decision, applied to 2.0. A worker reporting "fixed" is never sufficient for task completion.

Decision: autonomous coding uses isolated disposable environments

Never modify the production checkout. Use worktrees, branches, containers, or VMs. If a worker corrupts its environment, discard it and recreate a clean one. Preserve unrelated user changes.

Reason:

High autonomy without isolation would risk the owner's working tree and production systems.

Decision: authority is a policy engine, not a prompt for every action

The owner configures reusable policies per repository, business, application, environment, worker, task type, financial value, and risk. Routine low-risk work is automatic. Consequential work needs approval. Some actions are never silent (delete production data, destroy backups, change credentials, disable security, unapproved purchases).

Reason:

Asking for every approval defeats Away Mode; asking for none is unsafe.

Decision: local-first remains the default in 2.0; cloud specialists are explicit fallbacks

Simple and private work stays local. Difficult repository-wide coding may use an authorized external worker. Every send to an external AI provider is logged. External providers must be opted in.

Reason:

The 1.x local-first principle is not relaxed by 2.0. Cloud is a capability, not a dependency.

Decision: do not require new hardware before continuing development

Stage 1 is the existing desktop. Stage 2/3 GPUs are Nodes added later. Hardware should register as a Node exposing capabilities and eligible software Workers without redesigning Jarvis.

Reason:

The user forbade blocking 2.0 design and 1.x development on a new GPU purchase.

Decision: Away Mode — Autonomous Bug Fix is the flagship 2.0 benchmark

The 2.0 product is not done when individual features exist. It is done when the end-to-end bug-report → reproduce → isolate → implement → test → verify → stage → canary → monitor → notify → remote feature-approval loop succeeds repeatedly, with audit, rollback, and policy respected, and with no manual desktop interaction.

Reason:

This is the scenario the user named as the target "Jarvis called me while I was away because it had already fixed the reported bug" level of autonomy.

Decision: permission failures do not get an alternative tool

Recovery routing suggests alternatives for missing capabilities, timeouts, and not-found errors, but stays silent for sandbox and blocked-command failures.

Reason:

Switching tools does not grant more rights. Suggesting one would only teach the agent to probe the safety boundary.

Decision: optional workers are displayed even when absent

The Tools and System pages list optional workers. Browser Use and OpenHands adapters are integrated and report `missing` until installed. UFO, Cua, and Open Interpreter remain `not_integrated`.

Reason:

Graceful degradation should be visible. Missing workers must not look like crashes or silent omissions. Adapters must not pull those frameworks into the default install.

Decision: Browser Use and OpenHands stay optional and local-only

Evaluate license (both MIT), Windows support, and local-model compatibility before integrating. Point worker LLMs at Jarvis's OpenAI-compatible endpoint. Do not add the packages to `requirements.txt`. Playwright remains the default browser backend. Jarvis still verifies OpenHands output.

Reason:

Section 24 forbids integrating a framework just because it exists. The adapters unlock the capability when the owner installs the package, without making the platform fragile.

Decision: voice STT/TTS is local-only

Whisper and SAPI/espeak/pyttsx3 wrap `/api/voice/command`. Do not use cloud speech APIs. The Command Speak button is optional; typed commands remain the primary path.

Reason:

Local-first. Voice must not delay core Jarvis functionality or send audio off-box.

Decision: editable workflow templates with chained prompt dispatch

Provide pre-built and editable chained workflow recipes in the UI to facilitate rapid task launching without manual prompt crafting.

Reason:

Improves ease of use and low-maintenance UX by letting users load, customize parameters for, and fire complex multi-stage tasks directly from the web portal.

Decision: Reliable mode uses best-of-N for planning, not for full retries

Generate three labeled strategies, have the same model critique them, then execute only the winner. Do not run several complete attempts in parallel.

Reason:

The master plan asks for best-of-N on initial planning and consequential decisions. Executing every candidate would waste tools and risk conflicting file changes.

Decision: default model is 9B Abliterated; 27B is Expert-only

Fast/Balanced/Quality load Qwen3.5-9B Abliterated. Expert loads Qwen3.5-27B Q4_K_M. Missing 9B GGUFs fall back to 27B so existing installs keep working. The vision projector is opt-in.

Reason:

The 27B Q4 stack does not stay in 16 GB VRAM with KV cache and mmproj. Ordinary work should be fast and GPU-resident; 27B is for escalation.

Decision: tool schemas follow the task class

Only the tools relevant to the classified task are sent to the model. `request_capability` (or calling a real unlisted tool) expands the set.

Reason:

Dumping every tool on every call wastes context and increases wrong-tool selection.

---

## 60. Expected Example Behavior

Example user request:

«Fix the admin login problem on this website project, launch the site, test the login and keep working until it actually works.»

Desired Jarvis execution:

Understand desired outcome
↓
Inspect repository
↓
Identify software-engineering task
↓
Inspect auth implementation
↓
Run application/tests
↓
Potentially delegate complex work
↓
Modify code
↓
Start application
↓
Open browser
↓
Attempt login
↓
Observe failure
↓
Inspect backend/browser logs
↓
Diagnose
↓
Modify
↓
Restart
↓
Retest
↓
Verify successful authenticated state
↓
Report completion

No human correction should be required unless genuinely unavoidable.

---

Example:

«Fix formatting problems in chapters 3 through 7 of this Word manuscript and save a corrected copy.»

Desired flow:

Locate document
↓
Make backup/copy
↓
Inspect document structure
↓
Use Word COM/direct document tools
↓
Apply requested corrections
↓
Save
↓
Reopen
↓
Verify relevant chapters
↓
Report corrected file

---

Example:

«Research these products, compare them and save the result to Excel.»

Desired flow:

Research web
↓
Extract structured information
↓
Validate data
↓
Create Excel workbook
↓
Format useful output
↓
Save
↓
Reopen workbook
↓
Verify contents
↓
Report location

---

## 61. Completion Definition for Jarvis

Jarvis is not considered mature merely because a chat interface talks to a local model.

The system should eventually demonstrate all of the following:

- local model inference;
- reliable reasoning;
- tool calling;
- filesystem work;
- shell execution;
- Python;
- browser automation;
- unfamiliar browser navigation;
- Windows desktop operation;
- screenshot understanding;
- Office/document operation;
- software development;
- persistent tasks;
- resumable work;
- failure recovery;
- verification;
- context compaction;
- reusable skills;
- worker routing;
- MCP;
- web portal;
- task API;
- observability;
- safe autonomous execution;
- low-maintenance operation.

The overarching success criterion is:

«The user can give Jarvis a desired outcome rather than a sequence of instructions, and Jarvis can independently determine, execute, recover and verify the work with minimal human involvement.»

Jarvis 2.0 is not considered mature until the flagship benchmark in section 85 (`Away Mode — Autonomous Bug Fix`) passes repeatedly under the stated success criteria.

---

## 62. Instructions to Cursor for Every Future Run

When a new Cursor session starts and the instruction is simply:

«Continue Jarvis development.»

Perform the following automatically:

1. Read this entire file, including Jarvis 2.0 (sections 64–85). If the selected work touches nodes, placement, resource control, distributed execution, role policy, or universal UI architecture, also read `SWARM_ARCHITECTURE.md` before changing code.
2. Inspect Git status.
3. Inspect relevant current code.
4. Check the Current State section.
5. Check the Development Queue (1.x first unless the user asked for 2.0 / Away Mode).
6. Select the highest-value task that can be progressed.
7. Implement actual functionality.
8. Run relevant tests.
9. Debug failures.
10. Verify the implementation.
11. Update Current State.
12. Update Development Queue.
13. Add durable architectural decisions to Decision Log if needed.
14. Commit/checkpoint where appropriate.
15. Leave the project runnable and recoverable.

Do not stop after producing a plan if implementation can continue.

Do not ask the user routine implementation questions.

Do not require the user to manually maintain this file.

---

## 63. Initial Instruction After This File Is Added

Immediately after receiving this document:

1. Save it in the Jarvis project root as:

"JARVIS_MASTER_PLAN.md"

2. Read the existing repository.

3. Audit implementation against this master plan.

4. Replace the placeholder Current State section with the real verified state.

5. Replace the example Development Queue with the actual prioritized work queue.

6. Preserve existing working functionality.

7. Continue the most important unfinished implementation task.

8. Test it.

9. Debug failures.

10. Verify the result.

11. Update this file.

Do not stop merely because the planning document has been created.

Begin or continue actual Jarvis development.

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
