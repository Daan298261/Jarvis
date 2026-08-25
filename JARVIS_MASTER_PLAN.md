# Jarvis — Master Development Plan

This document is the persistent source of truth for the Jarvis project.

Jarvis is a local-first autonomous desktop AI agent intended to perform real work on this computer with minimal human intervention.

This file replaces the need to repeatedly provide large architectural prompts to Cursor.

**Jarvis Architect** is the sole editor of this file, [`SWARM_ARCHITECTURE.md`](SWARM_ARCHITECTURE.md), and [`ADAPTIVE_DOMAIN_ARCHITECTURE.md`](ADAPTIVE_DOMAIN_ARCHITECTURE.md). Executing bots must not edit spec docs. Spec-change requests come from Taco or Chief of Staff.

Swarm role/placement/resource design lives in `SWARM_ARCHITECTURE.md`. P4/P5 adaptive intelligence and domain packs live in `ADAPTIVE_DOMAIN_ARCHITECTURE.md`. Do not paste those specs into this file.

**Extensible Agent OS (ZoeyOS / FounderOS feature parity)** lives in [`JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md`](JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md). That file specifies persistent Agent Profiles, Specialist Packs, modular command-center dashboard, multi-agent delegation, hybrid inference, offline licensing, and the full owner-control UX needed to match Zoey-style specialist teams and FounderOS-style business autonomy. Do not start its P1–P6 roadmap ahead of active P0–P3 work unless the Development Queue or user explicitly promotes it. Do not paste that spec into this file.

Every development session must read this file before making substantial changes.

The user should not be expected to manually maintain technical state, architecture notes, implementation status, or development priorities.

---

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

Default runtime:

**Qwen3.5-9B Abliterated** (preferred GGUF Q8_0; Q6_K fallback).

Qwen3.5-27B Q4_K_M remains the Expert / escalation model. It is not the everyday model.

Reason: 27B does not stay fully GPU-resident on the user's 16 GB RTX 5070 Ti. Ordinary tool-calling work uses 9B; 27B is consulted when the task needs substantially deeper reasoning.

The 9B model should still support reasoning, tool calling, coding, writing, agentic execution, and vision when the projector is loaded.

Use reasoning/thinking for difficult autonomous tasks where supported. Use a faster mode for simple deterministic requests.

Do not substitute an even smaller model merely because it is easier to install.

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

Current implementation note: chat goes through `ModelProvider` / `OpenAICompatProvider`. Process management is still llama.cpp-specific (`llama-server.exe`). Keep the provider interface; extract a real `InferenceBackend` before adding Ollama/LM Studio/vLLM.

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

Repeated successful workflows may eventually be promoted into skills.

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
- load status.

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

## 42. Settings

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

1. stable Jarvis core;
2. reliable local Qwen inference;
3. task orchestration;
4. state persistence;
5. verification/recovery;
6. deterministic filesystem/shell/Python;
7. Playwright/browser;
8. Browser Use integration;
9. Windows computer control;
10. UFO/Cua adapters;
11. OpenHands/Open Interpreter adapters;
12. reusable skills;
13. trajectory memory;
14. advanced benchmarking;
15. voice/phone features.

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

Audited from the repository on `cursor/local-qwen-desktop-agent`. Live Qwen 9B/27B load and Windows e2e were **not** run in this Linux cloud session (no GPU/GGUF here). Only mark live-model items VERIFIED after a Windows desktop run.

### Hardware

User's Jarvis / Grok Bot desktop (in use; Grok Bot is already installed on this machine):

- OS: Windows 11
- CPU: Intel Core i7-14700KF
- RAM: 64 GB
- GPU: NVIDIA GeForce RTX 5070 Ti
- VRAM: 16 GB

This documentation session:

- OS: Linux (Cursor cloud agent)
- GPU: none in this environment
- Live 9B/27B e2e and tok/s: not run here

### Model

- Default runtime: **Qwen3.5-9B Abliterated** (Q8 preferred, Q6 fallback). **Qwen3.5-27B Q4_K_M** is Expert/escalation only.
- Backend: `InferenceBackend` abstraction; `LlamaCppBackend` supervises `llama-server`; remote OpenAI-compatible backends attach without owning the process.
- Status: **code present and unit-tested; Windows live 9B/27B load not verified this session**

### Core Application

- Backend: Python FastAPI (`backend/app`), served on `127.0.0.1:4780`
- Frontend: React + TypeScript + Vite, built into `frontend/dist` and served by FastAPI
- Database: SQLite `data/jarvis.db` (tasks, events, tool calls, checkpoints)
- Startup: `start-jarvis.ps1` / `stop-jarvis.ps1`
- Status: **working application skeleton with real APIs, agent loop, tools, and portal**

### Working Tools

- Filesystem: implemented (list/search/read/write/edit/copy/move/rename/mkdir/delete/hash/stat, backups, allowed-directory sandbox)
- PowerShell: implemented as default `terminal` shell (CMD/Python/Git/WSL/bash also supported)
- Python: implemented (`run_code`, `run_file`, `create_venv`, `install`); venv lookup checks Windows `Scripts` and Unix `bin`
- Browser: Playwright Chromium (accessibility snapshot, click/type, screenshot, tabs)
- Playwright: native backend present
- Windows UI: `desktop` tool (pywinauto / screenshot); Windows-only at runtime
- Vision: screenshot tool + llama.cpp `--mmproj`; not verified this session
- MCP: stdio and HTTP/streamable-http client; secrets not stored in git

### Optional Workers

- Browser Use / UFO / Cua / Open Interpreter / OpenHands: **adapters present** (catalog `missing`/`ready` until the optional package is installed; native fallbacks remain default)

### Swarm (one-node)

This machine registers as a localhost Node. Software workers bind to that Node. Orchestrator (control plane) and Leader (execution) are distinct roles, colocated on one host. Capability registry, role policy (`AUTO`/`PREFERRED`/`FORCED`/`AVOID`/`DISABLED`), resource budgets/leases, single-node placement, intelligence-vs-placement, and warm-state/data-locality scoring are in the tree. The portal has a Swarm page. P3 multi-node discovery/pairing is not started. See `SWARM_ARCHITECTURE.md`.

### Persistence

- Task storage: SQLite, including conversation JSON and tool-call records
- Resume: `POST /api/tasks/{id}/continue` reloads compacted conversation
- Context compaction: older tool traces summarized; compact working state stored in `tasks.compact_memory`

### Reliability

- Retry engine: identical-call blocking plus consecutive-failure strategy hint
- Verification engine: **implemented** — a task cannot complete until an independent verification pass runs; Reliable mode requires a verification tool call
- Failure recovery: **implemented** — classified failures with alternate-tool routing (`test_recovery.py`)
- Fast/Balanced/Reliable modes: **agent execution modes implemented** (separate from model Fast/Balanced/Quality profiles)
- Task classification: keyword classifier stored on the task
- Acceptance criteria / plan: parsed from the first planning turn and persisted

### Portal / API

- Command, History, Model, Tools, MCP, Settings, System, and Swarm pages exist
- Live status now shows execution mode, task class, and verification
- Tools/System pages list optional workers as unavailable instead of crashing
- Voice: Command Speak button; local STT/TTS when packages are present; JSON `/api/voice/command` still accepts text

### Known Problems

- Live Qwen3.5-9B / 27B load, tool-calling, tok/s, and Windows e2e (`tests/run_e2e.py`) have not been signed off from a Cursor session
- Optional worker packages may be missing on the desktop; adapters report `missing` rather than crashing
- Office COM and Docker depend on software that may be missing on the desktop
- P3 multi-node swarm (discovery, pairing, remote execution) is not started

### Last End-to-End Test

Date: 2026-08-25 (spec restore)

Tests performed:

- Queue ticks against code and squash-merge PRs on `cursor/local-qwen-desktop-agent`
- Windows live model e2e: **not run** (no GPU/GGUF in this environment)

Results: live 9B/27B remains desktop sign-off. Do not treat unit tests as a live-model pass.

---

## 58. DEVELOPMENT QUEUE

Statuses: TODO, IN PROGRESS, BLOCKED, VERIFIED

Priority: P0 core blocker, P1 major capability/reliability, P2 useful improvement, P3 future. Long-term ZoeyOS/FounderOS parity (Agent Profiles, Specialist Packs, command-center dashboard, offline licensing) is specified in `JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md` — promote individual items into this queue via RFCs; do not bulk-import the full spec here.

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
  - Status: VERIFIED in unit tests with a scripted model

- [ ] Reliable Qwen3.5-27B local inference on the Windows desktop
  - Acceptance: model loads, API responds, tool calls work, vision projector loads.
  - Status: TODO (code present; **BLOCKED in this environment** — no Windows GPU/GGUF). Next Windows session must run `tests/run_e2e.py`. Live 9B load is likewise unsigned-off.

### P1

- [x] Fast / Balanced / Reliable agent execution modes
  - Acceptance: setting exists; Reliable requires verification tools; Fast uses a shorter loop.
  - Status: VERIFIED in unit tests

- [x] Capability catalog for optional workers
  - Acceptance: Tools/System UI shows Browser Use/UFO/Cua/OpenHands/OI as unavailable rather than crashing.
  - Status: VERIFIED (code + API)

- [x] Strengthen failure recovery (alternate tool/worker, not only identical-call blocking)
  - Acceptance: a failed browser path can fall back to Playwright/web_fetch without repeating the same call.
  - Status: VERIFIED in code (`test_recovery.py`; PR unknown, landed on cursor/local-qwen-desktop-agent)

- [x] Context compaction quality
  - Acceptance: long tasks keep a compact working-state block and do not dump full tool traces.
  - Status: VERIFIED in code (`test_compaction.py`; PR unknown, landed on cursor/local-qwen-desktop-agent)

- [x] Extract `InferenceBackend` from `InferenceManager`
  - Acceptance: llama.cpp process manager is one backend; remote OpenAI-compatible remains a provider.
  - Status: VERIFIED in code (`test_inference_backends.py`; PR unknown, landed on cursor/local-qwen-desktop-agent)

- [ ] Playwright reliability on the target PC
  - Acceptance: e2e Test 3 (example.com title) passes without human help.
  - Status: CODE PRESENT / unit-tested (`test_browser.py`, PR #19). Live Windows e2e Test 3 still TODO.

- [x] Browser Use adapter
  - Acceptance: optional intelligent browser worker behind `BrowserBackend`; Playwright remains default.
  - Status: VERIFIED in code (PR #4)

- [ ] Windows semantic UI automation hardening
  - Acceptance: named-control interaction works for at least one native app; coordinate click remains last resort.
  - Status: CODE PRESENT / unit-tested (`test_desktop.py`, PR #19). Live native-app verification still TODO on Windows.

- [x] OpenHands worker adapter
  - Acceptance: large repo tasks can be delegated; Jarvis still verifies.
  - Status: VERIFIED in code (PR #4)

- [ ] RFC-0002 Agent policy interviews and per-capability autonomy
  - Acceptance: guided interview UI + runtime `authorize()` before every tool. Portal UI is this ticket; the loop hook is PR #72.
  - Status: IN PROGRESS — frontend interview UI against landed `/api/agent-policy`. Do not mark implemented until this UI and #72 are both on canonical.

### P2

- [x] Reusable skills
  - Status: VERIFIED in code (`test_skills.py`; PR unknown, landed on cursor/local-qwen-desktop-agent)
- [x] Trajectory memory (cross-task)
  - Status: VERIFIED in code (`test_trajectory.py`; PR unknown, landed on cursor/local-qwen-desktop-agent)
- [x] Best-of-N planning for Reliable mode
  - Status: VERIFIED in code (PR #1)
- [x] Model benchmark UI (persist tok/s, VRAM, success rates)
  - Status: VERIFIED in code (PR #2)
- [x] Office COM coverage when Office is installed
  - Status: VERIFIED in code (PR #14). Live COM on a Windows Office install was not exercised here.
- [x] Compare-files / recent-version filesystem helpers
  - Status: VERIFIED in code (PR #1)
- [x] Long-running process inspection (PID still alive)
  - Status: VERIFIED in code (PR #2)

#### P2 — Swarm-ready foundation (`SWARM_ARCHITECTURE.md`)

These items make the existing machine a one-node swarm first. They must not require a second computer.

- [x] Introduce first-class `Node` identity/state separate from software Worker abstractions.
  - Status: VERIFIED in code (PR #28)
- [x] Preserve software workers (`LocalJarvisCodingWorker`, `CursorACPWorker`, browser/media workers, etc.) as services that execute on eligible Nodes.
  - Status: VERIFIED in code (PR #32)
- [x] Separate Orchestrator (control plane) from Leader (strongest general-purpose execution Node).
  - Status: VERIFIED in code (PR #34)
- [x] Generalize capability registration so Nodes and Workers advertise capabilities and requirements.
  - Status: VERIFIED in code (PR #35)
- [x] Implement node role/class policy: `AUTO`, `PREFERRED`, `FORCED`, `AVOID`, `DISABLED`, including persistence and failover intent without implementing distributed failover yet.
  - Status: VERIFIED in code (PR #37)
- [x] Implement host resource budgets, hard/soft caps, reserved capacity, task priority, and resource-lease representation (CPU/RAM/GPU/VRAM/storage/network where meaningful).
  - Status: VERIFIED in code (PR #39) for budgets, HARD/SOFT caps, and leases. Reserved capacity and task priority are not first-class fields yet.
- [x] Implement a single-node placement scheduler that selects an eligible Node from requirements even when only `localhost` exists.
  - Status: VERIFIED in code (PR #41)
- [x] Keep intelligence selection separate from physical placement: choose the Worker/model first or jointly, then select the eligible Node based on capability, policy, locality, load, and resource availability.
  - Status: VERIFIED in code (PR #44)
- [x] Add model/worker warm-state and data-locality signals to placement scoring so the scheduler does not cause pointless model reloads or large transfers.
  - Status: VERIFIED in code (PR #45)
- [x] Extend the existing React portal toward the universal dynamic UI contract and add a Swarm settings surface without creating OS-specific frontends.
  - Status: VERIFIED in code (PRs #30, #33, #36, #38, #40, #42, #46). Full device-adaptive universal UI / Tauri shell is not in the tree.

### P3

- [x] Voice interface (Whisper STT + local TTS wrapping `/api/voice/command`)
  - Status: VERIFIED in code (PR #4)
- [x] Phone / Android client against the local API
  - Status: VERIFIED in code (PR #13)
- [x] Dedicated LAN inference server
  - Status: VERIFIED in code (PR #6)
- [x] UFO adapter
  - Status: VERIFIED in code (PR #8)
- [x] Cua adapter
  - Status: VERIFIED in code (PR #8)
- [x] Open Interpreter adapter
  - Status: VERIFIED in code (PR #6)
- [x] Browser workflow promotion (BrowserCode-style skills)
  - Status: VERIFIED in code (PR #6)
- [ ] Multi-node discovery, secure pairing, remote workers, and cross-node networking
  - Status: TODO / not started. One-node swarm only. Do not claim a second machine works.

---

## 59. DECISION LOG

Decision: Jarvis Architect is sole editor of spec docs

Jarvis Architect is the only role that may edit `JARVIS_MASTER_PLAN.md`, `SWARM_ARCHITECTURE.md`, and `ADAPTIVE_DOMAIN_ARCHITECTURE.md`. Executing bots must not edit those files. Spec-change requests come from Taco or Chief of Staff and are implemented only by Architect. New design for implementation still goes in `docs/rfcs/`.

Reason:

Bot sessions repeatedly bloated and restated the master spec. Status ticks belong in the queue; architecture belongs in the Architect-owned specs.

Decision: default runtime is Qwen3.5-9B Abliterated; 27B is Expert/escalation

Approved by Taco. Preferred 9B GGUF is Q8_0 (Q6_K fallback). Qwen3.5-27B Q4_K_M stays the Expert consult model, not the everyday model.

Reason:

27B does not stay fully GPU-resident on the user's 16 GB RTX 5070 Ti.

Decision: Jarvis 2.0 Away Mode is deferred and not in this master spec

Sections 64–85 (Autonomous Operator / Away Mode) were bot-appended after the original 63-section plan. They are not restored here. Git history retains them. Do not treat 2.0 as current-session P0.

Reason:

Keep the master spec readable. Do not restuff a second product spec into this file.

Decision: swarm architecture remains a separate specification

Detailed role, placement, resource-control, and universal-UI requirements live in `SWARM_ARCHITECTURE.md` (PR #9). This file owns priority/status only.

Reason:

The swarm design is large and must not be duplicated into the master plan.

Decision: Jarvis remains orchestrator

External frameworks such as OpenHands, UFO and Browser Use are execution workers rather than the primary application.

Reason:

Maintains a single persistent agent architecture while allowing specialized mature tooling.

Decision: extensible Agent OS requirements remain a separate authoritative specification

Detailed product requirements for ZoeyOS/FounderOS-style feature parity — persistent Agent Profiles, Specialist Packs, modular command-center dashboard, multi-agent delegation, hybrid inference, offline licensing, and full owner-control UX — live in `JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md`. The master plan references that file and owns priority/status rather than duplicating the full specification.

Reason:

The extensible Agent OS design is large and will evolve independently; keeping one detailed spec prevents the master plan from becoming contradictory. ZoeyOS and FounderOS are product-pattern references only — not Jarvis dependencies.

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

Decision: optional workers are displayed even when absent

The Tools and System pages list Browser Use, UFO, Cua, Open Interpreter, and OpenHands as `not_integrated`.

Reason:

Graceful degradation should be visible. Missing workers must not look like crashes or silent omissions.

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

---

## 62. Instructions to Cursor for Every Future Run

When a new Cursor session starts and the instruction is simply:

«Continue Jarvis development.»

Perform the following automatically:

1. Read this entire file.
2. Inspect Git status.
3. Inspect relevant current code.
4. Check the Current State section.
5. Check the Development Queue.
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
