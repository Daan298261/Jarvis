# Jarvis — Master Development Plan

This document is the persistent source of truth for the Jarvis project.

Jarvis is a local-first autonomous desktop AI agent intended to perform real work on this computer with minimal human intervention.

This file replaces the need to repeatedly provide large architectural prompts to Cursor.

**Jarvis Architect** is the sole editor of this file, [`SWARM_ARCHITECTURE.md`](SWARM_ARCHITECTURE.md), [`ADAPTIVE_DOMAIN_ARCHITECTURE.md`](ADAPTIVE_DOMAIN_ARCHITECTURE.md), [`ANDROID_CLIENT.md`](ANDROID_CLIENT.md), [`JARVIS_2.0.md`](JARVIS_2.0.md), [`HOME_IOT.md`](HOME_IOT.md), [`SECURITY_AGENTS.md`](SECURITY_AGENTS.md), the [`BLUE_TEAM.md`](BLUE_TEAM.md) pointer, [`INSTALLER.md`](INSTALLER.md), [`WINDOWS_SHELL.md`](WINDOWS_SHELL.md), and [`PORTAL_UX.md`](PORTAL_UX.md). Executing bots must not edit spec docs. Spec-change requests come from Taco or Chief of Staff.

Swarm role/placement/resource design lives in `SWARM_ARCHITECTURE.md`.

P4 (resilient + adaptive intelligence) and P5 (domain packs / business operating platform) remain in the spec set. Detailed requirements live in [`ADAPTIVE_DOMAIN_ARCHITECTURE.md`](ADAPTIVE_DOMAIN_ARCHITECTURE.md). That file translates useful patterns from [Founder OS](https://github.com/thecloudtips/founder-os) into native Jarvis concepts. Founder OS is **not** a runtime dependency. Do not start P4/P5 implementation ahead of active P0–P3 work unless this queue or the user promotes it. Do not paste the full adaptive spec into this file. **Invoices and business workflows stay in P5.**

**Extensible Agent OS (ZoeyOS / FounderOS feature parity)** lives in [`JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md`](JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md). That file specifies persistent Agent Profiles, Specialist Packs, modular command-center dashboard, multi-agent delegation, hybrid inference, offline licensing, and the full owner-control UX needed to match Zoey-style specialist teams and FounderOS-style business autonomy. Do not start its P1–P6 roadmap ahead of active P0–P3 work unless the Development Queue or user explicitly promotes it. Do not paste that spec into this file.

**Jarvis 2.0** (Away Mode, event-driven operators, **marketing**, **SEO**, **NovelProject**, **multimedia**, policy, self-healing) is restored in [`JARVIS_2.0.md`](JARVIS_2.0.md) — the approved sections 64–85 from git history. Do not drop those features. Do not treat 2.0 as current-session P0 unless this queue promotes an item.

The Android client that talks to the Windows Leader (link-device, AI-guided router port-forward, not P3 swarm) is specified in [`ANDROID_CLIENT.md`](ANDROID_CLIENT.md). Home IoT: [`HOME_IOT.md`](HOME_IOT.md). Home-network security agents (Blue / Purple / Red-gated): [`SECURITY_AGENTS.md`](SECURITY_AGENTS.md) (`BLUE_TEAM.md` is a pointer). Offensive / red capability: Taco or PolitieGPT only — ordinary executing bots must not add it. Windows consumer `.exe` installer: [`INSTALLER.md`](INSTALLER.md). Windows tray/Stop: [`WINDOWS_SHELL.md`](WINDOWS_SHELL.md). Portal shell: [`PORTAL_UX.md`](PORTAL_UX.md). Do not paste those specs into this file.

Filter: if a **new** idea would make home-network JARVIS more real, spec it. Never delete Taco-approved features.

**Must remain in the spec set** (do not drop):

1. This file: original 63-section body; Development Queue ticked with PR numbers; P2 swarm ticked; lazy mmproj **VERIFIED in code (PR #50)**.
2. [`JARVIS_2.0.md`](JARVIS_2.0.md): approved sections 64–85, including **NovelProject**. Unchecked 2.0 queue headings in §58.
3. [`ADAPTIVE_DOMAIN_ARCHITECTURE.md`](ADAPTIVE_DOMAIN_ARCHITECTURE.md): P4/P5 kept. Founder OS is a reference, **not** a runtime dependency.
4. [`ANDROID_CLIENT.md`](ANDROID_CLIENT.md): AI-guided brand-agnostic router. Link-device asks login/pairing, explains WAN exposure, DIY vs Jarvis+router password, router access later used by security agents.
5. [`HOME_IOT.md`](HOME_IOT.md): local-first house control.
6. [`SECURITY_AGENTS.md`](SECURITY_AGENTS.md) (`BLUE_TEAM.md` is a pointer): Blue home SIEM (detect/contain/evidence); Purple owned-net tests; Red/counter **disabled by default**. Offensive capability may be added **only** by Taco (manually) or PolitieGPT (LE bot) under the LE gate. Developers / CoS / PR fixer / home self-dev cannot; attempts refuse + audit.
7. Architect owns all spec files (this file, `SWARM_ARCHITECTURE.md`, `ADAPTIVE_DOMAIN_ARCHITECTURE.md`, `ANDROID_CLIENT.md`, `JARVIS_2.0.md`, `HOME_IOT.md`, `SECURITY_AGENTS.md`, `BLUE_TEAM.md`, `INSTALLER.md`, `WINDOWS_SHELL.md`, `PORTAL_UX.md`). Executing bots do not edit them.
8. [`INSTALLER.md`](INSTALLER.md): Windows 11 consumer `.exe` for non-technical onboarding. Smoke (PR #51): `JarvisSetup.exe`, Start Jarvis → health 200, Stop kills backend + llama-server, 9B Q8 on disk. Remaining P1: wizard copy, GPU fork, no-WAN first-run. Do not overwrite `installer/windows/` product files from Architect PRs.
9. [`WINDOWS_SHELL.md`](WINDOWS_SHELL.md): tray Stop/Quit and Apps Uninstall/Modify must not leave `llama-server` orphaned.
10. [`PORTAL_UX.md`](PORTAL_UX.md): ChatGPT-style app shell; orange/black; keep Swarm/Phone; no API redesign. Shell landed PR #53; Stop/settings findability still open.


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

**Lazy mmproj:** attach the vision projector only when a request actually needs vision, then unload it (`release_vision`). Do not keep mmproj resident for ordinary text/tool work. Idle llama.cpp does not pass `--mmproj`; `vision_mode=always` still does not attach at idle load. VRAM on 16 GB is the constraint. Landed in code (PR #50).

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

**Constraint (do not expand here):** llama.cpp chat must keep the **system message at the beginning**. Voice/listen must **not** inject a system turn mid-conversation. Product fix is D1’s P0 (503 listen + 500 “System message must be at the beginning”). Architect PRs must not implement it or edit voice backend files.

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

1. pull latest `development` (`git fetch origin development && git checkout development && git pull origin development`);
2. inspect Git status;
3. inspect current project;
4. read the Current State section below;
5. read the Development Queue below;
6. select the highest-value actionable task;
7. implement it;
8. test it;
9. diagnose failures;
10. continue until a meaningful increment is complete;
11. update Current State;
12. update Development Queue;
13. update architectural sections only when requirements change;
14. leave a recoverable project state.

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

**Branch model:** daily work and open PRs land on `development` (integration). `main` is stable/release (GitHub default); promote `development` → `main` only when CoS or Taco call an explicit stable cut.

Audited from the repository on `main` (stable tip at audit time). Live Qwen 9B/27B load and Windows e2e were **not** run in this Linux cloud session (no GPU/GGUF here). Only mark live-model items VERIFIED after a Windows desktop run.

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
- Vision: screenshot tool + llama.cpp `--mmproj`. Lazy attach in code (PR #50): projector only for a vision turn, then `release_vision`. Idle llama.cpp does not pass `--mmproj`; `vision_mode=always` still does not attach at idle load. Live Windows vision not verified this session.
- MCP: stdio and HTTP/streamable-http client; secrets not stored in git

### Optional Workers

- Browser Use / UFO / Cua / Open Interpreter / OpenHands: **adapters present** (catalog `missing`/`ready` until the optional package is installed; native fallbacks remain default)

### Swarm (one-node)

This machine registers as a localhost Node. Software workers bind to that Node. Orchestrator (control plane) and Leader (execution) are distinct roles, colocated on one host. Capability registry, role policy (`AUTO`/`PREFERRED`/`FORCED`/`AVOID`/`DISABLED`), resource budgets/leases, single-node placement, intelligence-vs-placement, and warm-state/data-locality scoring are in the tree. The portal has a Swarm page. P3 multi-node discovery/pairing is not started. See `SWARM_ARCHITECTURE.md`.

### Adaptive intelligence / domain packs (P4/P5)

Specified in `ADAPTIVE_DOMAIN_ARCHITECTURE.md`. **Not implemented.** Do not start ahead of active P0–P3 work. Founder OS is an architecture reference only, not a Jarvis dependency.

### Android client

Specified in `ANDROID_CLIENT.md`. Phone PWA (`/phone`) exists for LAN. Installable Android client + link-device + AI-guided WAN port-forward is **not implemented**. Not P3 swarm.

### Home IoT / security agents

Specified in `HOME_IOT.md` and `SECURITY_AGENTS.md` (Blue default-on household SIEM; Purple owned-net simulation; Red LE-gated stub). **Not implemented.**

### Jarvis 2.0

Specified in `JARVIS_2.0.md` (approved Away Mode / novel / marketing / SEO / multimedia / operators). **Not implemented** as current-session P0.

### Windows consumer installer

Specified in `INSTALLER.md`. Smoke on canonical (PR #51): `JarvisSetup.exe`; Start Jarvis → `http://127.0.0.1:4780` health 200; Stop kills backend + llama-server; 9B Q8 on disk. Remaining: wizard copy, GPU/VRAM fork, no-WAN first-run. Tray/Stop from Windows: `WINDOWS_SHELL.md` (not implemented). Do not edit `installer/windows/` product files from this Architect ticket.

### Portal UX

Specified in `PORTAL_UX.md`. Shell landed (PR #53): left projects + recents, main chat/task, orange/black, Swarm/Phone kept, `api.ts` swarm contracts kept. Remaining: Stop/settings findability. Do not overwrite `frontend/src` or swarm backend from this Architect PR.

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
- Voice: Command Speak button; local STT/TTS when packages are present; JSON `/api/voice/command` still accepts text. Constraint: llama.cpp chat must keep the system message at the beginning; voice/listen must not inject a system turn mid-conversation (D1 P0; do not implement from Architect PRs).
- Agent policy interviews (RFC-0002): guided interview UI PR #75; runtime `authorize()` before every tool PR #72 (`8265560`). Backend policy store PR #70.
- Guest portals (RFC-0008): backend PR #71; owner/guest portal UI PR #76 (`f003c4e`).
- Packs portal (RFC-0007): backend PR #61; portal UI PR #78 (`c1d2634`).
- Worker environments (RFC-0004): backend PR #58; portal UI PR #80 (`48ac107`).
- Task tree (RFC-0006): backend PR #59; portal UI PR #81 (`d2a1fcc`).
- License (RFC-0012): backend PR #66; portal UI PR #82 (`93e0555`).
- Advisor disclosure (RFC-0013): backend PR #67; portal UI PR #83 (`ee745f9`).
- Context repo (RFC-0011): backend PR #65; portal UI PR #84 (`fc111c9`).
- Trajectories (RFC-0010): backend PR #63; portal UI PR #85 (`599a30e`).
- Portability (RFC-0009): backend PR #62; portal UI PR #86 (`7a8f526`); 409 visibility PR #87 (`ce557d4`).
- Coding isolation (RFC-0005): backend PR #57; portal UI PR #88 (`ba1bb66`); blocked-integrate PR #89 (`1ff1135`).

### Known Problems

- Live Qwen3.5-9B / 27B load, tool-calling, tok/s, and Windows e2e (`tests/run_e2e.py`) have not been signed off from a Cursor session
- Optional worker packages may be missing on the desktop; adapters report `missing` rather than crashing
- Office COM and Docker depend on software that may be missing on the desktop
- P3 multi-node swarm (discovery, pairing, remote execution) is not started
- Android WAN reachability / AI-guided router port-forward is specified, not implemented
- Home IoT and security agents (Blue / Purple / Red-gated) are specified, not implemented
- Windows consumer `.exe`: smoke PR #51 (`JarvisSetup.exe`, Start/Stop, health 200, 9B Q8 on disk). Remaining: wizard copy, GPU fork, no-WAN first-run (`INSTALLER.md`). Tray/Stop from Windows: specified (`WINDOWS_SHELL.md`), not implemented.
- Portal UX shell (`PORTAL_UX.md`): PR #53 (projects + recents, orange/black, Swarm/Phone, swarm API contracts). Remaining: Stop/settings findability

### Last End-to-End Test

Date: 2026-08-25 (spec restore)

Tests performed:

- Queue ticks against code; daily PRs squash-merge onto `development`; promote to `main` only on explicit stable cut
- Windows live model e2e: **not run** (no GPU/GGUF in this environment)

Results: live 9B/27B remains desktop sign-off. Do not treat unit tests as a live-model pass.

---

## 58. DEVELOPMENT QUEUE

Statuses: TODO, IN PROGRESS, BLOCKED, VERIFIED

Priority: P0 core blocker, P1 major capability/reliability, P2 useful improvement / swarm-ready foundation, P3 multi-node/future, P4 adaptive intelligence, P5 domain packs. Long-term ZoeyOS/FounderOS parity (Agent Profiles, Specialist Packs, command-center dashboard, offline licensing) is specified in `JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md` — promote individual items into this queue via RFCs; do not bulk-import the full spec here.

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

- [x] Lazy mmproj (attach vision projector only when needed, then unload)
  - Acceptance: ordinary text/tool tasks do not keep `--mmproj` resident. When a request needs vision, attach the projector; when it no longer needs vision, unload it.
  - Status: VERIFIED in code (PR #50, squash-merge onto canonical; not PR #47). Attach only for a vision turn, then `release_vision`. Idle llama.cpp does not pass `--mmproj`. `vision_mode=always` still does not attach at idle load. Live Windows vision remains desktop sign-off.

### P1

- [x] Fast / Balanced / Reliable agent execution modes
  - Acceptance: setting exists; Reliable requires verification tools; Fast uses a shorter loop.
  - Status: VERIFIED in unit tests

- [x] Capability catalog for optional workers
  - Acceptance: Tools/System UI shows Browser Use/UFO/Cua/OpenHands/OI as unavailable rather than crashing.
  - Status: VERIFIED (code + API)

- [x] Strengthen failure recovery (alternate tool/worker, not only identical-call blocking)
  - Acceptance: a failed browser path can fall back to Playwright/web_fetch without repeating the same call.
  - Status: VERIFIED in code (`test_recovery.py`; PR unknown, landed on `main`)

- [x] Context compaction quality
  - Acceptance: long tasks keep a compact working-state block and do not dump full tool traces.
  - Status: VERIFIED in code (`test_compaction.py`; PR unknown, landed on `main`)

- [x] Extract `InferenceBackend` from `InferenceManager`
  - Acceptance: llama.cpp process manager is one backend; remote OpenAI-compatible remains a provider.
  - Status: VERIFIED in code (`test_inference_backends.py`; PR unknown, landed on `main`)

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

- [x] RFC-0002 Agent policy interviews and per-capability autonomy
  - Acceptance: guided interview UI + runtime `authorize()` before every tool.
  - Status: VERIFIED in code — interview UI PR #75; `authorize()` loop hook PR #72 (`8265560`); backend policy store PR #70. Both UI and hook are on `main`.
- [x] RFC-0008 Scoped guest portals
  - Acceptance: revocable guest portals with scoped tokens, deny-all default, owner revoke, permission preview, isolation tests, owner/guest UI.
  - Status: VERIFIED in code — backend PR #71; guest portal UI PR #76 (`f003c4e`). On `main`.
- [x] RFC-0007 Domain/workspace packs
  - Acceptance: preview before install/upgrade/uninstall; rollback/export; trust keys.
  - Status: VERIFIED in code — backend PR #61 (`8bb4145`); packs portal UI PR #78 (`c1d2634`). On `main`. P5 Domain Pack architecture / business-platform list remains unimplemented.
- [x] RFC-0004 Persistent worker environments
  - Acceptance: lifecycle; status/disk/last-active; start/suspend/resume/reset/inspect.
  - Status: VERIFIED in code — backend PR #58 (`56cc70d`); portal UI PR #80 (`48ac107`). On `main`.
- [x] RFC-0006 Hierarchical short-lived task workers
  - Acceptance: parent/child graph, status/events, spawn clamped so no extra authority.
  - Status: VERIFIED in code — backend PR #59 (`4fd6be0`); portal UI PR #81 (`d2a1fcc`). On `main`.
- [x] RFC-0012 Local license with BYO inference
  - Acceptance: entitlement separate from inference; status vs local cost; no secrets in UI.
  - Status: VERIFIED in code — backend PR #66 (`7b44ebe`); portal UI PR #82 (`93e0555`). License entitlement only, not a backend inference rewrite. On `main`.
- [x] RFC-0013 Compact local harness and advisor escalation
  - Acceptance: preview what leaves the box; advisor has no tools.
  - Status: VERIFIED in code — backend PR #67 (`1d614a0`); portal UI PR #83 (`ee745f9`). New files; no harness/compaction rewrite. On `main`.
- [x] RFC-0011 Versioned context repositories
  - Acceptance: inspect/diff/revert/pin/delete; Memory page kept.
  - Status: VERIFIED in code — backend PR #65 (`5c17b5e`); portal UI PR #84 (`fc111c9`). Does not replace the existing skills Memory page. On `main`.
- [x] RFC-0010 Cross-harness trajectory ingestion
  - Acceptance: list/inspect, Cursor import, native emit; no secrets.
  - Status: VERIFIED in code — backend PR #63 (`412ce01`); portal UI PR #85 (`599a30e`). Compose with `agent/trajectory.py`; stay off `db/models.py`. On `main`.
- [x] RFC-0009 Agent runtime portability
  - Acceptance: stable identity across lease/migrate/suspend/resume; 409s visible; no extra authority.
  - Status: VERIFIED in code — backend PR #62 (`82a5ef7`); portal UI PR #86 (`7a8f526`); 409 visibility PR #87 (`ce557d4`). On `main`.
- [x] RFC-0005 Isolated parallel coding workers
  - Acceptance: worktrees, decision inbox, no silent merge; integrate blocked unless ready.
  - Status: VERIFIED in code — backend PR #57 (`430e31b`); portal UI PR #88 (`ba1bb66`); blocked-integrate PR #89 (`1ff1135`). On `main`.
- [x] Windows consumer .exe installer — smoke (`INSTALLER.md`, PR #51)
  - `JarvisSetup.exe`; **Start Jarvis** → `http://127.0.0.1:4780` health **200**; **Stop** kills backend + `llama-server`; **9B Q8 on disk**.
  - Status: VERIFIED by Windows smoke (PR #51 squash-merge onto `main` (via cursor/local-qwen-desktop-agent)). Not a live 9B tool-calling e2e.
- [ ] Windows consumer installer — wizard copy, GPU fork, no-WAN first-run (`INSTALLER.md`)
  - Plain-language first-run wizard (progress UI; data dir; private key; optional LAN; Q6 fallback / 27B optional). If GPU/VRAM is missing or too small: explain and offer CPU-degraded or stop. First-run must **not** expose WAN without the Link-device flow.
  - Status: TODO / specified. Do not overwrite `installer/windows/` product files from Architect PRs.
- [ ] Windows tray / Stop from Settings (`WINDOWS_SHELL.md`)
  - While running: tray with Open portal, Start, Stop, Quit. Quit = Stop backend + llama-server + tray helper. Stop must not leave llama-server orphaned. Uninstall/Modify from Settings → Apps → Jarvis must not leave those processes. Startup toggle (if any) matches §48. Not P3; no WAN. D1 is on voice P0; CoS assigns this later.
  - Status: TODO / specified. Do not touch `installer/windows/` or voice backend from this Architect PR.
- [x] Portal UX app shell (`PORTAL_UX.md`, PR #53)
  - Orange/black; left projects + recents; main chat/task; existing destinations including Swarm and Phone; `api.ts` swarm contracts kept.
  - Status: VERIFIED in code (PR #53 squash-merge onto `main` (via cursor/local-qwen-desktop-agent)). Remaining: Stop/settings findability (`PORTAL_UX.md`; tray Stop is `WINDOWS_SHELL.md`, D1 in flight). Do not overwrite `frontend/src` from Architect PRs.

### P2

- [x] Reusable skills
  - Status: VERIFIED in code (`test_skills.py`; PR unknown, landed on `main`)
- [x] Trajectory memory (cross-task)
  - Status: VERIFIED in code (`test_trajectory.py`; PR unknown, landed on `main`)
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
  - Status: VERIFIED in code (PR #13) for the LAN Phone PWA (`/phone`, `GET /api/mobile` does not leak the key). Live Android home-screen install is still a desktop-session check.
- [ ] Android client to the Leader with AI-guided WAN reachability (`ANDROID_CLIENT.md`)
  - Evolve `/phone` into an installable Android client (TWA/PWA or thin WebView). Link-device: ask for pairing then; explain WAN exposure; user self-setup **or** Jarvis with router admin passwords; router access may later be used by Blue (and Purple on owned net). Red does not get those credentials unless the LE gate is on and the action is in authorized scope. Brand-agnostic walkthrough. Forward only the Jarvis port. CGNAT → overlay fallback. Not P3 swarm.
  - Status: TODO / specified. Do not hardcode ISP or brand adapters.
- [ ] Home IoT / mansion house control (`HOME_IOT.md`)
  - Discover and safely control LAN devices (HA/Matter/local APIs). Locks/garage extra confirm. Not swarm Nodes.
  - Status: TODO / specified
- [ ] Blue (home, default on) — household SIEM (`SECURITY_AGENTS.md`)
  - Detect, alert, contain, evidence on the user’s own LAN. Local SIEM; portal+phone alerts; owned-router containment with autonomy gates. Reuses link-device router secrets. No exploits or off-LAN attacks.
  - Status: TODO / specified
- [ ] Purple (owned-network only) — authorized adversary simulation (`SECURITY_AGENTS.md`)
  - Tests Blue on assets the user owns and lists. Explicit user confirm + autonomy profile; never silent. Goal is to improve detection, not to attack anyone else. No simulation techniques, payloads, or exploit steps in the spec or product. **Not a back door** to install red tools.
  - Status: TODO / specified
- [ ] Red / counter-response — law-enforcement gate only (`SECURITY_AGENTS.md`)
  - Spec the **gate**, not the attacks. Default disabled in the consumer/home build; no UI toggle a normal user can flip. Until Taco provides a distinct LE authorization module (identity + authorization artifact — do not invent a fake badge check), Red is a stub that refuses to run. Even when gated on: case/authorization record, human confirm, full SIEM audit; autonomy cannot silently enable it. Identify/isolate/evidence stay in Blue. Not a shipped hack-back kit.
  - **Hard guardrail:** offensive / red / counter-response capability MUST NOT be added by ordinary executing bots (developers, PR fixer, CoS, generic cloud agents, home Jarvis self-dev). MAY be added only by Taco (manually) or PolitieGPT (named LE bot) under the LE gate. Do not invent PolitieGPT internals. Home/product workers have no API to register offensive tools, payloads, or hack-back skills; attempts refuse and audit-log. Purple is not a back door to Red.
  - Status: TODO / specified
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

### P4 — Adaptive intelligence (`ADAPTIVE_DOMAIN_ARCHITECTURE.md`)

Specified, not implemented. Complements swarm resilience in `SWARM_ARCHITECTURE.md`. Detailed requirements stay in the adaptive spec; this queue only tracks headings.

- [ ] Structured execution event layer (central event model; correlation IDs; outcome states)
- [ ] Memory confidence lifecycle (`CANDIDATE` → `CONFIRMED` → `APPLIED` → `DISMISSED`)
- [ ] Memory categories, reinforcement, and confidence-gated context injection
- [ ] Adaptive Intelligence layer (observation → learning → routing → self-healing)
- [ ] Adaptive worker/model routing and node placement with warm-worker/data-locality bonuses
- [ ] Learned recovery reliability and graceful degradation (`CAPABILITY_UNAVAILABLE`)
- [ ] Standard multi-agent patterns (pipeline, parallel gathering, batch, competing hypotheses, map/reduce, supervisor)
- [ ] Workflow composition engine, idempotent automation, universal scheduling bridge
- [ ] Capability/automation audit and optional coverage score
- [ ] Business/project context profiles with least-context isolation

### P5 — Domain packs / business platform (`ADAPTIVE_DOMAIN_ARCHITECTURE.md`)

Specified, not implemented. Domain Packs are enableable Jarvis modules, not a Founder OS runtime.

- [ ] Domain Pack architecture (enableable packs; namespace convention)
- [ ] Core business workflows: daily briefing, inbox, meeting intelligence, follow-up tracker
- [ ] Report generation pipeline; competitive intelligence; proposal generation
- [ ] Invoice/expense processing; goals/milestones; knowledge base
- [ ] Cross-domain workflow composition; domain dashboard views
- [ ] Domain Pack dependency declaration, health/coverage, enablement lifecycle
- [ ] Domain-specific verification per pack; domain learning into shared P4 layer
- [ ] External integrations as sync targets — Jarvis owns canonical state

### RFC backlog — specified, not implemented

Canonical RFC bodies live under `docs/rfcs/`. Do not rewrite them from the master plan.

- [ ] RFC-0015 Amazon Ads integration and optimization — accepted; blocked on real OAuth (do not tick until OAuth lands)
- [ ] RFC-0016 Event subscriptions and durable goal lifecycle — accepted
- [ ] RFC-0017 MCP 2026-07-28 protocol upgrade — accepted
- [ ] RFC-0018 Hardware-aware runtime manifest catalog — accepted
- [ ] RFC-0019 Browser context companion — accepted
- [ ] RFC-0020 Persistent project knowledge workspaces — accepted
- [ ] RFC-0021 Artifact/Crafts output layer — accepted
- [ ] RFC-0022 Provider budget pooling and quota governance — accepted
- [ ] RFC-0023 Natural-language task authoring — accepted
- [ ] RFC-0024 Agent self-improvement skill lifecycle — accepted
- [ ] RFC-0025 Multi-channel agent gateway — accepted
- [ ] RFC-0026 Execution phase and verifier observability — accepted
- [ ] RFC-0027 Semantic action firewall — accepted
- [ ] RFC-0046 Trusted workspace app extensions — accepted
- [ ] RFC-0028 Off-context agent journal — accepted
- [ ] RFC-0047 Portable automation packages — accepted
- [ ] RFC-0029 Transactional durable execution — accepted
- [ ] RFC-0030 Selectable inference offload backends — accepted

### Jarvis 2.0 — Away Mode (`JARVIS_2.0.md`)

Approved text restored (sections 64–85). Specified, not implemented. Do not drop marketing, SEO, novel, multimedia, or other approved 2.0 features.

- [ ] Event-driven intake (queue, retries, backoff, dedup, DLQ)
- [ ] Event normalization (`BUG_REPORTED`, `FEATURE_REQUESTED`, `CI_FAILED`, …)
- [ ] SoftwareEngineeringWorker + isolated worktrees / verification (1.x trial isolation exists; 2.0 event-driven remains TODO)
- [ ] Authority / approval policy engine
- [ ] Production monitoring and self-healing
- [ ] Marketing Manager worker
- [ ] SEO / content operations
- [ ] NovelProject subsystem (story bible, chapter state, editorial workers) — Taco writes novels with Jarvis
- [ ] Multimedia / creative worker
- [ ] Away Mode — Autonomous Bug Fix flagship benchmark

---

## 59. DECISION LOG

Decision: Jarvis Architect is sole editor of spec docs

Jarvis Architect is the only role that may edit `JARVIS_MASTER_PLAN.md`, `SWARM_ARCHITECTURE.md`, `ADAPTIVE_DOMAIN_ARCHITECTURE.md`, `ANDROID_CLIENT.md`, `JARVIS_2.0.md`, `HOME_IOT.md`, `SECURITY_AGENTS.md`, the `BLUE_TEAM.md` pointer, `INSTALLER.md`, `WINDOWS_SHELL.md`, and `PORTAL_UX.md`. Executing bots must not edit those files. Spec-change requests come from Taco or Chief of Staff and are implemented only by Architect. New design for implementation still goes in `docs/rfcs/`.

Reason:

Bot sessions repeatedly bloated and restated the master spec. Status ticks belong in the queue; architecture belongs in the Architect-owned specs.

Decision: default runtime is Qwen3.5-9B Abliterated; 27B is Expert/escalation

Approved by Taco. Preferred 9B GGUF is Q8_0 (Q6_K fallback). Qwen3.5-27B Q4_K_M stays the Expert consult model, not the everyday model.

Reason:

27B does not stay fully GPU-resident on the user's 16 GB RTX 5070 Ti.

Decision: Jarvis 2.0 stays in the spec set as `JARVIS_2.0.md`

Taco: all previously approved features stay. Sections 64–85 are restored into `JARVIS_2.0.md` (not omitted, not thinned). Marketing, SEO, NovelProject, multimedia, Away Mode, and related operators remain. Invoices remain under P5 as well. Do not treat 2.0 as current-session P0 unless the queue promotes an item.

Reason:

Hold was lifted. The 63-section master plan stays readable; the approved 2.0 text is a first-class spec file.

Decision: never delete Taco-approved features

If a **new** idea would make home-network JARVIS/Cortana more real, add a spec. Do not remove approved product from the spec set to “simplify.”

Reason:

Filter going forward is additive for home-JARVIS; deletion of approved work is forbidden.

Decision: spec-set completeness (Taco pass)

The spec set must keep all of: original 63-section master plan body; queue ticks with PR numbers; P2 swarm ticks; lazy mmproj VERIFIED in code (PR #50); Jarvis 2.0 §§64–85 including Novel (`JARVIS_2.0.md`); P4/P5 (`ADAPTIVE_DOMAIN_ARCHITECTURE.md`, Founder OS not a dependency); Android link-device / AI-guided brand-agnostic router (`ANDROID_CLIENT.md`); home IoT (`HOME_IOT.md`); Blue / Purple / Red-gated (`SECURITY_AGENTS.md`); Windows consumer `.exe` (`INSTALLER.md`); Windows tray/Stop (`WINDOWS_SHELL.md`); portal shell (`PORTAL_UX.md`); Architect-owns-specs. Offensive/red capability: Taco or PolitieGPT only.

Reason:

Taco: when this pass finishes, the PR must contain all of that. Do not drop any approved feature.

Decision: Windows consumer .exe installer is a first-class spec

Non-technical Windows 11 onboarding lives in `INSTALLER.md`. Smoke (PR #51): `JarvisSetup.exe`, Start Jarvis → health 200, Stop kills backend + llama-server, 9B Q8 on disk. Remaining P1: wizard copy, GPU/VRAM fork, no-WAN first-run. This spec does not prescribe Inno line-by-line. Architect PRs must not overwrite `installer/windows/` product files. Not P3 swarm.

Reason:

New users should not perform a manual Python/Node/llama.cpp dance. Developer/manual install stays in `docs/INSTALL.md`.

Decision: Windows tray / Stop from Settings is a separate spec

`WINDOWS_SHELL.md`. While Jarvis is running, a tray icon is required (Open portal, Start, Stop, Quit). Quit stops backend + llama-server + tray helper. Stop must not leave llama-server orphaned. Settings → Apps Uninstall/Modify must not leave those processes. Later CoS ticket; D1 is on voice P0. Do not touch `installer/windows/` from Architect PRs. Not P3; no WAN.

Reason:

Start Menu Stop is not enough for non-technical Windows users.

Decision: portal UX is a ChatGPT-style app shell

`PORTAL_UX.md`. Keep orange/black and existing destinations including Swarm and Phone. Home is talk/work: left projects + recents, main chat/task. Admin pages remain reachable, not the home screen. Shell landed in code via PR #53 (`api.ts` swarm contracts kept). Remaining: Stop/settings findability. Do not overwrite `frontend/src` from Architect PRs.

Reason:

Taco/CoS: current tabs feel like a stack of admin dashboards.

Decision: llama.cpp system message stays first

llama.cpp chat must keep the system message at the beginning. Voice/listen must not inject a system turn mid-conversation. D1 owns the product fix. Do not implement from Architect PRs; do not edit voice backend files.

Reason:

Constraint only. Avoid a voice rewrite in this spec pass.

Decision: swarm architecture remains a separate specification

Detailed role, placement, resource-control, and universal-UI requirements live in `SWARM_ARCHITECTURE.md` (PR #9). This file owns priority/status only.

Reason:

The swarm design is large and must not be duplicated into the master plan.

Decision: P4/P5 remain in the spec set as a separate file

Adaptive intelligence and domain-pack requirements live in `ADAPTIVE_DOMAIN_ARCHITECTURE.md` (Taco upload, commit `c2d6386eb0`). This master plan keeps queue headings only. Source inspiration is useful patterns from https://github.com/thecloudtips/founder-os translated into native Jarvis concepts. Founder OS is **not** a Jarvis dependency.

Reason:

P4/P5 must stay visible in the Development Queue without pasting the adaptive spec into this file.

Decision: Android client talks to the Leader; router setup is AI-guided and brand-agnostic

The phone is a remote control for the Windows Leader, evolving `/phone`. Link-device asks for pairing then, explains WAN exposure, and offers self-setup or Jarvis-with-router-password. Router access may later be used by Blue (and Purple on owned net). Red does not get those credentials unless the LE gate is on and the action is in authorized scope. WAN setup is AI-guided and brand-agnostic. See `ANDROID_CLIENT.md`.

Reason:

One client, one Leader, every household's router — not a Netherlands-vendor special case.

Decision: home IoT and security agents (Blue / Purple / Red-gated) are first-class specs

House control: `HOME_IOT.md` (local-first HA/Matter). Security workers: `SECURITY_AGENTS.md` (`BLUE_TEAM.md` is a pointer). Blue is the household default (detect/alert/contain/evidence on the user’s own LAN). Purple is owned-network adversary simulation to test Blue, explicit confirm only. Red is a locked future worker behind a law-enforcement authorization module Taco must provide; until then it is a stub that refuses; no consumer toggle; this spec does not describe attacks. Blue (and Purple on owned net) may reuse link-device router secrets; Red does not unless the LE gate is on and the action is in authorized scope.

Reason:

Mansion-JARVIS includes the house and the home LAN, not only the desktop agent. Counter-response is not a home-user feature.

Decision: only Taco or PolitieGPT may add red / offensive / counter-response capability

Hard guardrail (`SECURITY_AGENTS.md` §3.4). Ordinary Jarvis executing bots — developers, PR fixer, Chief of Staff, generic cloud agents, home Jarvis self-dev — MUST NOT add it. Home/product workers have no API to register offensive tools, payloads, or hack-back skills; attempts refuse and audit-log. Purple is not a back door. PolitieGPT is the named LE bot; do not invent its internals. Spec the interface only: Taco (manual) or PolitieGPT (under the LE gate) can enable/add red capability; everyone else cannot.

Reason:

Taco confirmation. Red is not a product feature ordinary workers may grow into.

Decision: lazy mmproj

Attach the vision projector only when a request needs vision, then unload (`release_vision`). Do not keep it resident. Landed in code via squash-merge PR #50 (not #47): idle llama.cpp does not pass `--mmproj`; `vision_mode=always` still does not attach at idle load.

Reason:

16 GB VRAM cannot spare a resident projector during ordinary text/tool work.

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

Decision: RFC-0067 and RFC-0068 landed on development

Owner chat hides plan/approval chrome by default and greets once per session start (RFC-0067: specs #154, greeting+streaming #153, UX #156). Long jobs may speak one rate-limited persona think-aloud (RFC-0068: specs #157, backend #159). Live TTS/HUD remain desktop sign-off. Not added to the RFC backlog (already implemented).

Reason:

Taco: HUD felt like a ticket runner; conversational talk plus brief spoken commentary during long work.

Decision: RFC-0069 accepts the #166 presence shape-catalog / morph surface

Presence remains a humanoid of thousands of glowing orbs (parity baseline #165). RFC-0069 locks the accepted contract to implement PR #166: expandable `registerPresenceShape` catalog (default `humanoid_bust`, stub `energy_core`), `avatarId` → shape id (`jarvis_base` / empty / `shape:<id>`), and fixed-budget A/B orb morph (`uMorph`) without remounting `HumanoidPresence`. Field layers may swap rather than lerp. No new §58 backlog checkboxes. Now implemented on development via #168+#166 (`4e7b97d`).

Reason:

CoS assigned this ledger so specs can land then #166 without renaming the shipped surface. Morph/catalog shipped ahead of the RFC; this entry accepts that API.

Decision: RFC-0070 higher-quality local TTS engines (implemented)

Taco (2026-09-10) wants a less robotic Jarvis voice — a massive quality jump via better local-friendly engines, not cloud lock-in or IP-clone packs. RFC-0070 extends the RFC-0062 profile `tts` block with an engine adapter. Canonical desktop ranking (RTX 5070 Ti): Kokoro-82M (Apache-2.0) default low-latency English; Chatterbox/Turbo (MIT) optional quality when ~4–6 GB VRAM free, original butler packs only; Orpheus 3B (Apache-2.0) catalog, not default. Piper remains edge/Dutch/baseline. Do not ship XTTS v2 or F5-TTS (CC-BY-NC) as product defaults. Default household butler pack must work out of the box after Setup; other voices bundle or one-click “Get more voices” (listing-only `install_required` fails). TTS speaks final conversational text and allowed persona lines only — never thought-process / plan chrome, URLs, or code. “Codsworth-like” is feel, not a clone. Chat→TTS, think-aloud, and Android host TTS keep the same active `voice_profile_id`. Now implemented on development via #171+#173 (`9ff1fff`). No new §58 backlog checkboxes.

Reason:

Current host TTS still falls through to robotic OS/espeak-class backends despite the voice-profile catalog. Owner asked for quality, not another picker.

Decision: RFC-0073 HUD model hotswap selector (implemented)

RFC-0073 is implemented on development via #180+#181 (`0b9cfa1`). HUD ModelSelector top-right, pinnable slots, More → `/model`. No new §58 backlog checkboxes.

Reason:

CoS assigned this ledger tick after #181 landed on tip; specs #180 accepted the contract.

Decision: RFC-0074 / 0075 / 0076 accepted (Taco 1.2.5 desktop test)

CoS → Jarvis Architect. Three accepted specs from the 1.2.5 owner test: RFC-0074 companion pairing streamline + QR + spoken pair-vs-explore onboarding; RFC-0075 social vs technical speak path, first-sentence TTS, thought-process chevron; RFC-0076 APK build progress + Download to Desktop + WhatsApp/email send when configured. No new §58 backlog checkboxes. Implement is UX/D1/D2 after this specs-only land.

Reason:

Taco 1.2.5: pairing failed without a private key and without QR; default TTS still robotic / late / markup-aloud; APK generation had no visible progress or Desktop/send path.

Decision: RFC-0075 natural speak path + reply latency (implemented)

RFC-0075 is implemented on development via #188 (`99e1028`): social vs technical speak path, speak filter, natural prose, early TTS. Thought-process chevron was not in #188; RFC-0067 Show work / hide-chrome remains the owner-chat contract (UX follow-up). No new §58 backlog checkboxes. RFC-0074 and RFC-0076 are implemented in the following ledger tick. Prior ledger tick #190 closed without merge.

Reason:

CoS assigned this re-tick after #188 landed on development.

Decision: RFC-0074 companion pairing + RFC-0076 companion APK delivery UX (implemented)

RFC-0074 is implemented on development via #191 (`ee643eca`): companion pairing streamline, QR fields, spoken onboarding hooks. RFC-0076 is implemented on development via #189 (`8ab2c28`) + #193 (`f31d2f2`): APK build progress / Download to Desktop + WhatsApp/email send when configured. No new §58 backlog checkboxes. Specs status updated from accepted → implemented (late ledger catch-up 2026-09-22 against development tip `25d1c53`; code landed 2026-09-11).

Reason:

CoS assigned Architect tick-only after room flagged that defaulting re-implement to 0074/0076 would collide with already-merged work.

Decision: RFC-0077 local LM Studio discovery + play/hotswap context (implemented)

RFC-0077 is implemented on development via #187 (`b806080`) + #186 (`3f8f6a4`) + #185 (`1aed4a8` chrome overlap). Home-relative LM Studio discovery, local + play in ModelSelector, conversation rebind, HudTopChrome reflow. No new §58 backlog checkboxes. Prior ledger tick #190 closed without merge.

Reason:

CoS assigned this re-tick after #187+#186 landed on development. Taco wants all local LM Studio models discovered for whoever is logged in, play-to-load without resetting chat, and no overlapping HUD chrome when the selector opens.

Decision: RFC-0092 neural TTS default, no silent SAPI (accepted)

CoS urgent 2026-09-15. Default spoken profile is `butler_original_v1` (Kokoro `bm_daniel`), never Windows SAPI / `windows_natural_en_v1` labeled `natural`. Neural engine failure must surface/retry, not silently return SAPI (closes RFC-0089 unchecked TTS criterion). Chatterbox (or in-tree MIT/Apache successor) is a Desktop Setup one-click quality path without `JARVIS_TTS_CHATTERBOX` on the shipping Windows build. Preview/samples record engine + profile id. OpenViking is not TTS. Specs-only; implement follow-up.

Reason:

Through 1.3.9 the spoken default is still robotic SAPI; catalog prefers and can migrate owners off Kokoro; `synthesize.py` swallows Kokoro errors into SAPI.

Decision: RFC-0093 installer force-stop and prepare unstick (implemented)

RFC-0093 is implemented on development via #264 (`9ecf9bd`): force-stop before Inno copy/uninstall, bounded bootstrap watchdog, skip-heavy prepare, durable PID/step logs, contract tests. Specs PR #262 (`96d3421`). Live JarvisSetup on a running Jarvis remains Windows desktop sign-off. RFC-0092 untouched. No new §58 backlog checkboxes.

Reason:

CoS assigned this ledger tick after #264 landed on development. 1.3.13 clean reinstall failed after polite `stop-jarvis.ps1`; upgrade froze on the full-bar Preparing screen.

Decision: RFC-0094 settings menu information architecture (implemented)

RFC-0094 is implemented on development via specs #265 (`01bd56e`) + implement #267 (`73d93d2`): six-group Settings IA (Voice, Appearance, Models / Inference, Network / Companion, Integrations, Advanced), Daybreak Voice/Appearance split, `/settings/:submenu` + last-submenu persistence. RFC-0092 not folded. Live Daybreak desktop HUD remains desktop sign-off. No new §58 backlog checkboxes.

Reason:

CoS assigned this ledger tick after #267 landed on development. `Settings.tsx` was a stacked dump; Daybreak left-bar was one mixed Appearance & voice panel (`AppearancePresenceControls`, #263).

Decision: RFC-0095 Instagram jarvis collection module catalog + Download (accepted)

Taco Instagram `@tacotcr` Saved→jarvis (~140) ingest is a four-step pipeline (Download → usefulness review → integrate decision → implement). Module Catalog/Packs **Download** clones or zips to Desktop/`projects` (library `projects/` on Architect’s box). Full-assistant repos tagged `persona_candidate` (no persona merge). Offensive/pentest (Strix, Pentagi, Claude-Red, Exploitarium, …) stay `le_gated` / archive-only — PolitieGPT/LE only. Black Grid media children reserved RFC-0096/0097. Specs-only; no new §58 checkbox.

Reason:

Owner saves UI/repo inspiration on Instagram with no path into Jarvis modules/skills/DLCs or a downloadable module pack.

Decision: RFC-0096–0104 Instagram jarvis child integrations (accepted)

Parent RFC-0095 ([#270](https://github.com/Daan298261/Jarvis/pull/270); umbrella on development — not rewritten here). Nine accepted children, four-step pipeline (Download already local under `/workspace/projects/{rfc|persona}/<name>` — do not commit clones → usefulness score → integrate decision → implement later): **0096** ComfyUI+SANA BlackGrid gen (`partial`); **0097** OpenCut/OpenMontage/Hyperframes stitch + optional Real-ESRGAN preprocess (`partial`); **0098** Browser-Use deepen (`partial`; Playwright default); **0099** OpenViking+RAGFlow memory (`partial`; OpenViking is not TTS); **0100** Firecrawl+Crawl4AI research (`partial`); **0101** Pipecat realtime voice (`partial`; do not rewrite RFC-0092); **0102** LocalSend LAN share (`partial`); **0103** RuView Wi‑Fi home presence (`partial`; not HexStrike, not RFC-0069 HUD); **0104** persona_candidate pack later (hermes-agent, openhuman, F.R.I.D.A.Y, deer-flow, openclaude, opencode, locally-uncensored — full assistants, no butler merge). Offensive (Strix/Pentagi/Claude-Red) stay LE-gated under 0095 — no child RFCs. Specs-only; no new §58 checkbox. Taco may override integrate decisions.

Reason:

Instagram Saved→jarvis high-value subset needs scored child tickets so implementers do not start from the umbrella alone or merge personas/offensive tools.

Decision: RFC-0105 cybersecurity module (implemented)

RFC-0105 is implemented on development via specs #272 (`8d607b5`) + Daybreak UI #274 (`ca5fac8`) + backend hooks #277 (`7e6338c`): one Module Catalog pack `cybersecurity` (six members, **partial** connectors), Daybreak left-bar panel (enable / status / path / open-folder / Download), catalog API + generic module-worker supervisor. HexStrike (RFC-0078/0086) stays beside it. RFC-0106 is implemented (sibling; not rewritten here). Gating/authorization still out of scope (owner). No new §58 checkbox. Live Daybreak HUD / Open folder / subprocess remains desktop sign-off.

Reason:

CoS assigned this ledger tick after #277 landed on development. Owner directed these former archive clones into a Jarvis cybersecurity module on Daybreak (surface + wiring), not six orphan tools, not a Settings dump, and not a HexStrike rewrite.

Decision: RFC-0106 HexStrike Jarvis full operator control (implemented)

RFC-0106 is implemented on development via specs #276 (`7c1be3f`) + backend #279 (`175b2dc`) + Daybreak UX #283 (`69eebd7`): Jarvis is the HexStrike operator (Daybreak HUD + owner chat). RFC-0106 **intent wins** over RFC-0086’s Blue-only enum / no-MCP / no-command-proxy product stance for this module; loopback bind and install pinning remain. Operator catalog / MCP / `/api/hexstrike` operate→jobs; Daybreak tabbed console (Runtime / Catalog / Operate / Jobs). No invented LE/Red/Purple/ATO gates (owner later). RFC-0105 cybersecurity module stays a sibling. No new §58 checkbox. Live pinned install / HUD+chat invoke remains desktop sign-off.

Reason:

CoS assigned this ledger tick after #283 landed on development. Taco: complete control over HexStrike and its toolchain; Jarvis is the “human” using it; do not ship stubs.

Decision: INTEGRATION_SPECS.md + RFC-0107–0109 (accepted)

Living architect priority list for third-party / reel-sourced integrations lives at repo-root [`INTEGRATION_SPECS.md`](INTEGRATION_SPECS.md) (not a master-plan rewrite). Taco ladder, quick/highest impact first: **0107** Obsidian linked memory/brain; **0108** phone companion on-device model (PC orchestrator when online); **0109** media/file/video upload on Android + Desktop/portal. Then reel children in impact order (0098 Browser-Use, 0101 Pipecat, 0096 ComfyUI, 0097 stitch, 0099 memory, 0100 research, 0103 RuView, 0102 LocalSend; 0104 persona later; 0105 cyber implemented; 0106 HexStrike operator implemented). RFC-0095 remains the umbrella + Module Catalog Download. Local clones stay under `C:\Users\daanv\projects\jarvis-ig\` and `/workspace/projects/` (not git). Specs-only; no new §58 checkbox; no invented LE gates.

Reason:

Taco: separate integration specs document; Instagram Saved→jarvis plus three new high-impact adds; do not merge product code in this pass.

Decision: RFC-0107 durable-brain strengthen (accepted) + RFC-0110 approval popup (implemented)

RFC-0107 end-state is an **external durable brain** (Obsidian linked vault/graph + Jarvis DB/cache, synced with RFC-0011) plus **per-turn internal search** over installed **or** installable tools — pull only what the ask needs; do **not** pre-stuff persona packs, full tool catalogs, or history dumps into every inference prompt. Immediate `n_keep ≥ n_ctx` 400 band-aids stay a separate inference ticket; this is not “compress forever.” RFC-0108 phone offline and RFC-0109 media upload stay on the same Taco ladder. RFC-0110 is implemented on development via specs #284 (`5b512d8`) + grants API #288 (`f43d797`) + UI #290 (`6a01f22`): ChatGPT-style modal (**Always allow** / **Allow this time** / **Deny**, optional free-text, persist Always allow per tool/action class) shown only when the model/tool flow actually needs a decision or typed input; ordinary owner chat stays ungated and streams — not the always-on “Review or approval is required” gate. `/api/approvals/pending*` park/decide. No new §58 checkbox; no invented LE/Red/Purple gates. Live HUD modal + spoken grants remain desktop sign-off.

Reason:

Taco: large durable context out of the prompt; search tools per ask; approval popup like ChatGPT only when needed. CoS assigned the RFC-0110 ledger tick after #290 landed on development.

Decision: Jarvis 1.4.0 release scope lock (RFC-0112–0113, RFC-0115 accepted; RFC-0111 implemented; RFC-0114 implemented)

Living spec [`JARVIS_1.4_SPECS.md`](JARVIS_1.4_SPECS.md) is on `development` (copied from `main` @ `6f6a633`; light path note only). Implementable contracts:

- **RFC-0111** Kokoro as real runtime — **implemented** on development via specs #286 (`1f8320d`) + implement #296 (`99a0463`): `TtsRuntimeState`, `KokoroAdapter`, pinned `kokoro==0.9.4` / `soundfile==0.14.0`, no pip during speak, no silent SAPI, synthesis health probe, requested-vs-actual engine. Deepens RFC-0070 / RFC-0092; does not change 0092 defaults. **RFC-0112** voice preview remains HOLD. Live A/B listen after Setup rebuild remains desktop sign-off.
- **RFC-0112** Voice preview uses the exact selected profile (canonical route, error preservation, playback failure is failure). **HOLD** (Sol/Taco) — do not tick.
- **RFC-0113** Admin > Settings 1.4 IA deltas (Appearance & Voice composed, Phone Pairing, Network & Swarm, redirects) — RFC-0094 remains implemented; HUD Voice/Appearance split stays.
- **RFC-0114** Context overflow preflight + automatic recovery — **implemented** on development via specs #286 (`1f8320d`) + implement #293 (`265b758`): canonical `PromptBudget`, preflight, expand 8K→16K→32K, recoverable 400, compact/expand/retry ≤2. Identity-only `n_keep` + per-message tools preserved. **No** RFC-0115 escalate placeholder (same-model recovery only). RFC-0107 durable brain stays the non-compress-forever end-state. Live llama.cpp 400 remains desktop sign-off.
- **RFC-0115** Ornith 9B orchestrator-router + complexity tiers + visible model handoff (gates before warm-score; no Continue button).

**IN 1.4.0:** core packages above (**0111 implemented**, **0114 implemented**) **plus** already-filed interesting integrations **RFC-0107** Obsidian durable brain, **0108** phone offline, **0109** media upload, **0110** approval modal (**implemented**), **plus** HexStrike / Daybreak / cyber already in flight (**0105** implemented, **0106** implemented).

**OUT of the 1.4 cut:** bulk Instagram / catalog RFCs **0095–0104** — they stay on [`INTEGRATION_SPECS.md`](INTEGRATION_SPECS.md) / later queue. Do **not** re-scope them into 1.4 RFCs or block the cut.

Specs-only; no new §58 checkbox; no invented LE/Red/Purple/ATO gates; no exploit recipes.

Reason:

Taco 1.4.0 scope lock: split `JARVIS_1.4_SPECS.md` into RFC-0111–0115; keep interesting 0107–0110 and in-flight HexStrike/cyber; leave bulk reel catalog for later. CoS assigned the RFC-0114 ledger tick after #293 landed on development. CoS assigned the RFC-0111 ledger tick after #296 landed on development.

Decision: RFC-0116 TypeSafe Jev optional decision tier (accepted; post-1.4)

TypeSafe **Jev** (System One) is an **optional cloud decision accelerator** for Jarvis control-path classify/route/score/branch — not chat/TTS/coding, not a Kokoro/Ornith-generation replacement. Default remains local Ornith + heuristics (`decision_tier: local`). Owner may opt into `jev_optional` (BYO TypeSafe key) or `jev_plus` (paid monthly packaging when billing exists; until then a real `has_feature(..., "decision.jev_plus")` / `GET /api/license/entitlements` check, not `if True`). **Jev is early access / waitlist** as of 2026-09-17: specs land now; implement is gated on public/early-access API availability + owner opt-in. Settings show waitlist/status + “notify when ready”; **no fake-live stubs** (enabled but unavailable → error/CTA, never silent local-LLM-as-Jev). Wires RFC-0107 tool select, RFC-0075 speak class, RFC-0115 complexity/escalate, RFC-0110 approval-needed. **Not** in the 1.4.0 cut (optional / post-1.4 interesting). No new §58 checkbox; no invented LE/Red/Purple/ATO gates.

Reason:

Taco 2026-09-17: IG TypeSafe Jev (@albert.olgaard) as optional Jarvis decision tier; free toggle + Plus packaging; waitlist-honest until the API is actually available.

Decision: RFC-0107 amend — embed real Obsidian UI (accepted)

Taco 2026-09-17: Obsidian is the **operational** durable brain (vault bind + agent read/write/wiki-link/graph + per-turn tool search — not décor). Owner surface is the **real Obsidian UI hosted inside Jarvis** (Desktop Tauri/WebView2 native host of official Obsidian; official embed if it exists; Electron BrowserView only if that is the shell). Do **not** ship a custom note browser, graph viewer, or “Jarvis brain” clone. Specs: RFC-0107 amend + [`INTEGRATION_SPECS.md`](INTEGRATION_SPECS.md) 0107 row. Backend bind/index/working-set already on development (#295); RFC stays **accepted** until UX embed lands. No new §58 checkbox; no invented LE gates.

Reason:

Taco: operational soon and actually used; embed Obsidian inside Jarvis; do not build a custom brain UI.

Decision: RFC-0117 tiny front-chat responder (implemented; post-1.4)

Tiny always-warm **front responder** lane for first visible/audible owner-chat replies while the larger router/worker continues on the same Jarvis turn. **Implemented** on development via specs #303 (`49f6af4`) + implement #305 (`4eb25d9`): `front_responder` role with tools/thinking disabled and 96–160 token cap; `final_basic` / `ack_continue` / `ask_clarification` / `handoff_notice`; one-transcript merge; immediate safe TTS (`speak_immediately`); diagnostics (`front_responder.last_turn`). **Not** in the 1.4.0 cut (optional / post-1.4 interesting, same class as RFC-0116). Duplicate-number [`docs/rfcs/0117-durable-state-journal-rollback.md`](docs/rfcs/0117-durable-state-journal-rollback.md) from #304 stays **accepted** (separate ticket; not ticked). Windows first-visible/first-audible across two larger models remains desktop sign-off. No new §58 checkbox; no invented LE/Red/Purple/ATO gates.

Reason:

Taco via Codex: delay is systemic across models, not 27B-specific; tiny front-chat first, larger model continues. CoS assigned the RFC-0117 ledger tick after #305 landed on development.

Decision: RFC-0118 Taco goals highest-leverage memo (accepted) + RFC-0109 OCR amend + RFC-0120/0121

Specs-only ranking for Taco’s four goals (speed; coding+3D real tools; OCR+media upload; projects folder / chats-in-DB / media placement). Memo: [`docs/rfcs/0118-taco-goals-highest-leverage.md`](docs/rfcs/0118-taco-goals-highest-leverage.md). Ranked reuse: **1** amend/implement **RFC-0109** (explicit OCR on phone+desktop — not a third media RFC); **2** implement **RFC-0115** Ornith router (0117 front responder already implemented; do not duplicate); **3** new **RFC-0120** coding+3D real tools; **4** new **RFC-0121** projects folder + chats-in-DB + media colocation vs storage node (extends RFC-0020); **5** residual **RFC-0107** hot-path use / desktop sign-off (embed landed in code; ledger stays **accepted** — do not tick implemented). **RFC-0119 reserved** for a parallel license-package entitlements RFC — unused here. **RFC-0108 continues**; 0109 after 0108. Bulk 0095–0104 later; HOLD 0092/0112; draft #282 out of scope. No new §58 checkbox; no §57 rewrite; no invented LE/Red/Purple/ATO gates.

Reason:

Taco 2026-09-18: at most five highest-leverage next steps against those four goals; prefer amend/reuse; 0108 in flight; CoS 0109 after 0108.

---

Decision: RFC-0119 license-package entitlements + release unrestricted license + HexStrike overview (accepted)

RFC-0119 ([`docs/rfcs/0119-license-package-entitlements-and-release-unrestricted.md`](docs/rfcs/0119-license-package-entitlements-and-release-unrestricted.md)): the **License Manager signed package** is the **sole capability gate** for modules, functionalities, and LE/red/blue packs (`has_feature` / pack entitlements / `modules[]`). **Password gates are retired** for unlocking HexStrike / Daybreak / cyber / modules (RFC-0086/0087 ATO+LE fields stay; no new officer/ATO policy). Each Windows Setup / release cut **must emit** a full **owner-unrestricted** `.jarvis-license` into `installer/windows/dist/` beside Setup (not the customer Inno payload). HexStrike select/load speaks/chats **one short product overview** only — no exploit recipes / PoCs / payloads / attack steps. Specs-only; no new §58 checkbox. Do not block RFC-0108. RFC-0118 is a parallel memo (do not take that number).

Reason:

Taco via CoS 2026-09-18: License Manager package is the central entitlement; Taco must not hand-regen unrestricted licenses; HexStrike load gets a product overview, not tradecraft.

---

Decision: RFC-0108 amend (offline GGUF pack path) + RFC-0123 companion reachability / anti-impersonation (accepted)

Taco via CoS 2026-09-18 (HOLD lifted for this slice only). [RFC-0108](docs/rfcs/0108-phone-companion-offline-ai-model.md) keeps the #309 llama.cpp / routing / Outbox / sync contract and adds: pinned allowlisted phone GGUF URL (empty catalog URL is a fail), Leader `data/companion-packs/` cache with weights **gitignored**, first Leader-up **background** download (non-blocking, progress visible), post-pair **popup** offering phone download with **size in MB**. Fine-tune later. [RFC-0123](docs/rfcs/0123-companion-reachability-and-anti-impersonation.md): owner-facing LAN-only vs port-forward (**TCP 4781** only) vs mobile-relay; Leader **listens continuously** on the companion TLS port; accept **pairing keys** only (RFC-0074/0059); continuous impersonation/MITM watch; on suspicion emit **`detected-hack-attempt`** + **probability**, kill the connection, refuse `:4781` for **10 minutes**. No exploit recipes. No new §58 checkbox. Do not take RFC-0122. Do not invent LE/Red/Purple gates.

Reason:

Owner asked for a real offline pack download (not a catalog stub) and a clear companion-port / anti-impersonation product on the existing gateway — not a second blue-team bot.

---

Decision: RFC-0122 ingress size-gate + trajectory cap (accepted; Jarvis 1.4.1 priority bugfix)

RFC-0122 ([`docs/rfcs/0122-ingress-size-gate-spill-and-trajectory-cap.md`](docs/rfcs/0122-ingress-size-gate-spill-and-trajectory-cap.md)): after HUD + model hotswap, ordinary owner Q&A must not die on `Context capacity exceeded after compact/expand recovery`. Reuse `front_responder` for a cheap size/complexity check (no third persona). Large payloads **spill to the internal DB first** (optional Obsidian durable mirror via RFC-0107 — **hybrid default**, DB authoritative for the turn blob). Trajectory “lessons” injection is quality-gated and budget-capped (never inject “last message → none”). Simple Q&A gets on-demand / empty tools, not a full catalog dump. RFC-0114 recovery **stays**; this ticket fixes **what enters** the budget. Specs-only; implement is a named follow-up. Do **not** block RFC-0108. No new §58 checkbox; no invented LE/Red/Purple/ATO gates.

Reason:

Taco 2026-09-18: Jarvis 1.4.1 product priority is the context-overflow / junk-injection path after Neural HUD → Humanoid HUD → Qwen 27B; specs first.

---

Decision: RFC-0124 Clean Install / Reinstall owned-path wipe (accepted; P0)

Taco via CoS 2026-09-18 (blocked on local install). [RFC-0124](docs/rfcs/0124-clean-install-reinstall-owned-path-wipe.md): owner **Clean Install / Reinstall** from Settings → Advanced (and Setup.exe Clean / optional `/setup` recovery — same helper). Reuse RFC-0093 `force-stop-jarvis.ps1` (not polite `stop-jarvis.ps1` alone). Wipe **only** an explicit Jarvis-owned path allowlist (default `%LOCALAPPDATA%\Jarvis` / `{app}` from `Jarvis.iss`; never Documents/Desktop/`allowed_directories` / vendor `license-issuer`). Leftover lockers or undeletable owned files **abort** with 0093-family log; then force-launch Setup. Specs-only; D1 implements after. No new §58 checkbox. Do not take ≤0123. Do not invent LE/Red/Purple gates.

Reason:

Taco needs a portal/Setup Clean Install that actually kills lockers, deletes only Jarvis-owned trees, and reinstalls — not a polite hang or a wipe of unrelated AppData.

---

Decision: RFC-0136 zombie-kill on Setup Next and Start (accepted)

Taco 2026-09-22 (post-1.4.10): a wedged uvicorn held **4780** (`CLOSE_WAIT`, health fail) so Start died with `Errno 10048`; a second `.venv` uvicorn was also stuck. [RFC-0136](docs/rfcs/0136-zombie-kill-setup-next-and-start.md) extends RFC-0093 `force-stop-jarvis.ps1` (does **not** rewrite [RFC-0124](docs/rfcs/0124-clean-install-reinstall-owned-path-wipe.md)). Setup installation-method **Next** and `start-jarvis.ps1` (before bind) must kill hung Jarvis backends that still own 4780/4781, tray helpers, and Jarvis-started llama-server / supermemory. Exit 0 while a Jarvis PID still holds the port is a **fail**. Specs-only; no new §58 checkbox. 0130–0135 were taken.

Reason:

Path-only force-stop plus a Start script that binds immediately cannot recover a listener that fails health. Task Manager must not be the fix.

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
