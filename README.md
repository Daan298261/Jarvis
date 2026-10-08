<div align="center">

# JARVIS

### Your AI. Your hardware. Your rules.

**A self-hosted AI assistant and agent platform built for local-first work, extensible tools, and a future multi-device swarm.**

[Getting started](#getting-started) · [Features](#what-jarvis-does) · [Architecture](#how-it-works) · [Documentation](#documentation) · [Contributing](#development--contributing)

![Platform](https://img.shields.io/badge/platform-Windows%2011-0078D4?style=flat-square) ![Deployment](https://img.shields.io/badge/deployment-self--hosted-202C3A?style=flat-square) ![Inference](https://img.shields.io/badge/inference-local--first-16A34A?style=flat-square) ![Status](https://img.shields.io/badge/status-active%20development-F59E0B?style=flat-square)

</div>

---

## ANZU Superassistant

**ANZU Superassistant** is the end-user product being built by the **Jarvis** engineering project: a polished, local-first, multi-device autonomous AI system designed to feel like one coherent personal superassistant rather than a collection of models, agents and developer tools.

> **Tell ANZU what you want. ANZU figures out how to accomplish it.**

ANZU is intended to understand the desired result, inspect its environment, plan and execute the work, recover when an approach fails, and independently verify the result before reporting completion. A command running successfully is not enough; the requested outcome must actually be achieved.

### Product north star

The project is judged by the intended user experience, not by literal compliance with an older implementation detail. RFCs and architecture specifications define requirements and safeguards, but they serve the product goal rather than replace it.

ANZU should be:

- **Premium and visually finished** — restrained, coherent, smooth and deliberately designed. It should look like a mature commercial product, not an engineering dashboard.
- **Simple by default** — models, context windows, workers, GPU allocation, task graphs and routing should remain hidden unless the owner chooses to inspect or control them.
- **Fast when the task is simple** — deterministic/reflex execution should handle trivial operations without unnecessary large-model reasoning (`RFC-0085`, `RFC-0117`, `RFC-0127/0128`, `RFC-0171`, `RFC-0172`).
- **Powerful when the task is difficult** — complex goals may use planning, specialist agents, multiple models, tools, browser/computer use and parallel workers.
- **Alive and recognisable** — ANZU has a persistent visual and voice presence that communicates listening, thinking, working, speaking, waiting and error states (`RFC-0069`, `RFC-0137`, `RFC-0175–0178`, `RFC-0195`).
- **Natural to talk to** — voice is a primary interface, with real local TTS/STT, low perceived latency, interruption support and no silent fallback masquerading as a premium voice (`RFC-0070`, `RFC-0075`, `RFC-0092`, `RFC-0111`, `RFC-0117`).
- **Autonomous without being reckless** — routine reversible work should proceed without constant approval, while consequential actions remain controlled, auditable and reversible (`RFC-0002`, `RFC-0031`, `RFC-0071`, `RFC-0110`).
- **Verification-driven** — ANZU should verify outcomes rather than confuse activity with success (`RFC-0026`).
- **Local-first and owner-controlled** — local inference and storage remain first-class, with optional escalation to other nodes or cloud models according to privacy, capability, latency and cost policy.
- **One assistant, many specialists** — personas, agents, models and machines are internal resources. The owner should normally experience a single ANZU identity (`RFC-0137`, `RFC-0173`, `RFC-0174`).
- **Hardware-scalable** — adding a workstation, GPU node, laptop, Raspberry Pi or phone should increase available capability without increasing normal interaction complexity.
- **Resilient** — loss of a cloud service, model, node or internet connection should degrade capability gracefully rather than make the product incomprehensible or unusable.

### What already exists

The current codebase already contains substantial foundations for the end state, including:

- Windows desktop application and conversational owner-facing UI foundations;
- local and OpenAI-compatible inference abstraction;
- task execution, checkpoints, persistence and recovery;
- native tool execution and automation controls;
- persistent memory and project foundations;
- ANZU persona/presence system and specialist identities (`RFC-0137`);
- particle/morphable presence architecture and later continuous-presence work (`RFC-0069`, `RFC-0175–0178`);
- natural/local voice foundations and explicit TTS runtime handling (`RFC-0070`, `RFC-0092`, `RFC-0111`);
- low-latency front-response and reflex execution architecture (`RFC-0117`, `RFC-0171`, `RFC-0172`);
- project placement and context foundations (`RFC-0121`);
- Skill Forge for turning successful work into reusable skills (`RFC-0173`);
- Multi-Agent Rooms for bounded parallel specialist work (`RFC-0174`);
- autonomy policy, approval and reversibility foundations (`RFC-0002`, `RFC-0031`, `RFC-0110`);
- explicit execution verification states (`RFC-0026`);
- one-node swarm architecture with Orchestrator, Leader, Senior Worker and Junior Worker concepts, role preferences/forcing and host-resource budgets;
- phone pairing, offline-model and Android presence/voice foundations (`RFC-0074`, `RFC-0108`, `RFC-0123`, `RFC-0139`, `RFC-0140`).

Implementation status varies by feature: some areas are production-usable, while others still require Windows, GPU, phone or physical-device sign-off and UX refinement.

### Where ANZU is going

Major planned capabilities include true secure multi-node swarm execution; richer phone/WAN operation; polished installer and lifecycle management; final visual acceptance under `RFC-0195`; natural low-latency voice refinement; durable project knowledge and richer artifact handling; Agent Profiles and Specialist Packs; adaptive model/node routing; cost and privacy governors; Decision Inbox and richer authority policies; live execution maps; event-driven durable goals; **Away Mode**; autonomous coding and software maintenance; marketing, SEO, publishing and media workers; Home IoT; Household Vision; defensive infrastructure security; grid-down/offline mobile capability; and a wider integration/plugin ecosystem.

The long-term system is an **owner-controlled intelligence fabric**. Models are replaceable resources. Agent identities are not permanently tied to one model. Workers are not permanently tied to one computer. ANZU decides how to use the available resources while the owner controls policy and can override placement when needed.

### The implementation test

A feature is not complete merely because its backend exists or an RFC checkbox can be marked done. Significant work should be tested against the following questions:

1. Does it reduce the technical knowledge required from the user?
2. Does it make ANZU faster, more capable, more reliable or easier to trust?
3. Does it look and behave like part of the same premium product?
4. Can a normal user understand what is happening without reading engineering documentation?
5. Does it hide complexity by default while preserving owner control?
6. Can ANZU recover intelligently when the happy path fails?
7. Does ANZU verify the result rather than merely execute steps?
8. Does it degrade gracefully when optional models, workers, nodes or network connections disappear?
9. Does it preserve privacy and local operation wherever practical?
10. Does it avoid unnecessary approvals and configuration?
11. Does it remain responsive during both simple commands and long-running work?
12. Would the design still make sense when ANZU spans several computers, a phone and the home?
13. Is it aesthetically and ergonomically good enough to ship?
14. Does it move ANZU toward being one coherent superassistant rather than simply adding another feature?

If the final answer is **no**, the implementation is probably moving in the wrong direction even if it technically follows a lower-level specification.

### Canonical product and architecture documents

- [`ANZU_PRODUCT_NORTH_STAR.md`](ANZU_PRODUCT_NORTH_STAR.md) — highest-level product-intent and UX reference.
- [`JARVIS_MASTER_PLAN.md`](JARVIS_MASTER_PLAN.md) — current implementation roadmap and RFC status.
- [`JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md`](JARVIS_EXTENSIBLE_AGENT_OS_REQUIREMENTS.md) — long-term Agent OS, specialist-pack, routing, swarm and governance requirements.

> **Finished ANZU:** an elegant, local-first, multi-device autonomous intelligence with the depth of a professional automation platform and the simplicity of a premium personal assistant. The user should not feel that they are operating the underlying swarm. They are operating **ANZU**.

---

## An assistant that works on your terms

Jarvis brings local language models, tool execution, task management, and an approachable control interface together in one self-hosted system. Run inference on your own machine, connect an OpenAI-compatible inference server when needed, and build workflows around the tools you actually use.

A public clone can start as a **household voice chatbot** (Kokoro) without a 9B/27B GGUF. Add a local model, run `bootstrap.ps1 -InstallLocalLLM`, or point at any OpenAI-compatible server when you want full agent work. The default local LLM when present is **Qwen3.5-9B Abliterated**; **Qwen3.5-27B** is Expert escalation.

The project is being developed toward a larger vision: a coordinated network of devices with specialized agents, persistent services, and configurable autonomy. **The current Windows desktop agent is the foundation; the full swarm and autonomous-operator vision are ongoing development, not features promised in this release.**

## Interface

| Owner HUD | Particle humanoid |
| :---: | :---: |
| ![Jarvis owner HUD with particle humanoid](docs/screenshots/humanoid-hud.png) | ![Cinematic particle humanoid showcase](docs/screenshots/humanoid-showcase.png) |

| Anzu — storm bird | Nabu — owl of knowledge |
| :---: | :---: |
| ![Anzu storm-bird particle avatar](docs/screenshots/anzu-stormbird.png) | ![Nabu owl particle avatar](docs/screenshots/nabu-owl.png) |

![Named-persona picker in the Jarvis HUD](docs/screenshots/persona-gallery.png)

The presence is a live WebGL dot cloud: it forms, breathes, reacts to assistant state, and morphs between the humanoid and each persona-specific mythical avatar.

## What Jarvis does

| Capability | Description |
| :--- | :--- |
| **Local-first AI** | Run GGUF models with llama.cpp, switch model profiles, or use a compatible remote inference endpoint. |
| **Owner HUD** | Chat, voice, appearance, cybersecurity controls, and expandable local health on the desktop portal. |
| **This PC** | Files, terminal, Python, git, Playwright, Windows UI Automation, Office COM, and screenshots. |
| **Memory** | SQLite tasks, Obsidian-linked vault, skills, trajectories, and context repos. |
| **Phone companion** | Android APK with LAN pairing; WAN/4G failover when prepared. |
| **Windows installer** | `JarvisSetup.exe` plus Start/Stop scripts; owner license is issued beside Setup, not inside the payload. |
| **Extensible tools** | Native tools and MCP integrations; see the tool catalog for available integrations and requirements. |
| **Configurable access** | Keep the service on localhost by default or explicitly enable authenticated LAN access. |

**On the roadmap:** a universal desktop experience, richer voice and vision, Android companionship, agent teams, multi-node scheduling, role-based device placement, security workers, and autonomous operator workflows. These are tracked in the design documents below; individual components may be experimental or incomplete.

## Getting started

**Target platform:** Windows 11. The repository's startup scripts and some desktop integrations are Windows-specific. A GPU-capable NVIDIA setup is used for the documented local inference configuration.

For a new machine, start with the **[complete installation guide](docs/INSTALL.md)**. A Windows installer is also under development; see [installer status](INSTALLER.md) before assuming one-click setup is complete.

If you have **already cloned the repository**, you can start without a GGUF as a voice chatbot (`.\start-jarvis.ps1`). For full local inference, install model weights and llama.cpp (see [INSTALL.md](docs/INSTALL.md)), then:

```powershell
python -m pip install -r backend\requirements.txt
python -m playwright install chromium
cd frontend
npm install
npm run build
cd ..
.\start-jarvis.ps1
```

Open **http://127.0.0.1:4780** if the portal does not open automatically.

To stop Jarvis:

```powershell
.\stop-jarvis.ps1
```

> **Important:** Model weights, llama.cpp binaries, and local runtime data are not included in Git. Follow [INSTALL.md](docs/INSTALL.md) for prerequisites, downloads, and initial configuration. Do not expose the portal or API to the public internet without reviewing [SECURITY.md](SECURITY.md).

### Everyday workflows

Start Jarvis with a task and wait for completion:

```powershell
.\start-jarvis.ps1 -Prompt "Inspect directory and generate project report" -Wait
```

Or submit a task file:

```powershell
.\start-jarvis.ps1 -PromptFile .\tasks\sample_task.json -Wait
```

The portal also includes **Guide & Workflows** for operating instructions and task templates. For advanced startup flags, LAN authentication, and model configuration, use the [installation guide](docs/INSTALL.md).

## How it works

```text
                 ┌─────────────────────────────┐
                 │  Portal / client interfaces │
                 └──────────────┬──────────────┘
                                │
                 ┌──────────────▼──────────────┐
                 │      FastAPI control plane  │
                 │ Tasks · tools · settings    │
                 └───────┬─────────────┬───────┘
                         │             │
               ┌─────────▼──────┐  ┌───▼──────────────────┐
               │ Agent + tools  │  │ Inference backend   │
               │ Native / MCP   │  │ llama.cpp / remote  │
               └────────────────┘  └──────────────────────┘
```

The current application combines a **FastAPI backend** with a **React control portal**. Local inference uses **llama.cpp**; an OpenAI-compatible server can be configured as an alternative. A REST API provides the interface for clients and integrations. See [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for implementation details.

The planned swarm architecture separates orchestration, leadership, and worker responsibilities, with configurable placement and host-resource limits. Its design is documented in [SWARM_ARCHITECTURE.md](SWARM_ARCHITECTURE.md); do not treat that document as a description of fully shipped functionality.

## Models and hardware

The documented reference installation uses **Windows 11 Pro, an Intel Core i7-14700KF, 64 GB RAM, and an NVIDIA RTX 5070 Ti with 16 GB VRAM**. This is the development configuration, **not a universal minimum system requirement**.

- **Everyday inference:** Qwen3.5-9B Abliterated via llama.cpp; a locally available Qwen3.8-9B uncensored GGUF is preferred by the current autoload logic when found.
- **Expert escalation:** Qwen3.5-27B, with fitting/offloading as needed.
- **Other backends:** a configurable OpenAI-compatible inference server.

The portal exposes **Fast / Balanced / Quality** model profiles. Agent execution modes are separate from model profiles. See [INSTALL.md](docs/INSTALL.md) for exact model paths and setup, and [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for CUDA or model-loading issues.

## Project direction

| Area | Direction | Reference |
| :--- | :--- | :--- |
| **Multi-device intelligence** | Orchestrator, leader, senior/junior workers, node roles, and resource controls | [Swarm architecture](SWARM_ARCHITECTURE.md) |
| **Autonomous operations** | Away Mode, delegated workflows, publishing, research, and marketing | [Jarvis 2.0](JARVIS_2.0.md) |
| **Specialized intelligence** | Adaptive domain packs and specialized workers | [Adaptive domain architecture](ADAPTIVE_DOMAIN_ARCHITECTURE.md) |
| **Security** | Defensive monitoring and gated security-agent design | [Security agents](SECURITY_AGENTS.md) |
| **Additional interfaces** | Windows desktop shell, phone companion, voice, and home integration | [Windows shell](WINDOWS_SHELL.md) · [Android client](ANDROID_CLIENT.md) · [Home IoT](HOME_IOT.md) |

These documents contain a mixture of designs, implementation work, and future goals. **[JARVIS_MASTER_PLAN.md](JARVIS_MASTER_PLAN.md) is authoritative for priorities and implementation status.**

## Documentation

| Start here | What you will find |
| :--- | :--- |
| [Installation](docs/INSTALL.md) | Prerequisites, models, Windows setup, startup, and authentication |
| [Development guide](docs/DEVELOPMENT.md) | Repository map, local development, APIs, tools, and tests |
| [Architecture](ARCHITECTURE.md) | Control plane, memory, compaction, and autonomy |
| [Tools](TOOLS.md) | Native integrations, MCP, skills, and trajectories |
| [Security](SECURITY.md) | Network binding, keys, and filesystem policy |
| [Troubleshooting](TROUBLESHOOTING.md) | Common model, CUDA, browser, Office, and Docker issues |
| [Task status and approvals](docs/TASK_STATUS_AND_APPROVALS.md) | Approval gates, task phases, and progress feedback |
| [Development process](docs/PROCESS.md) | RFCs, branches, review, and release workflow |
| [RFC index](docs/rfcs/) | Proposals and detailed technical specifications |

For the wider roadmap, see [Jarvis master plan](JARVIS_MASTER_PLAN.md) and [Jarvis 2.0](JARVIS_2.0.md).

## Development & contributing

Jarvis is under active development. Start with [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md), then read the [development process](docs/PROCESS.md) and relevant [RFCs](docs/rfcs/) before making architectural changes.

- **`main`** is the stable release branch; development work branches from **`development`** and targets it with pull requests.
- Keep changes scoped to one RFC or development-queue item per worker.
- Consult [JARVIS_MASTER_PLAN.md](JARVIS_MASTER_PLAN.md) for the current priorities and development queue.

Run unit tests without a GPU:

```powershell
python -m pytest tests -q
```

For the live desktop end-to-end suite, start Jarvis with a model loaded, then run:

```powershell
python tests\run_e2e.py
```

Test commands are provided for contributors; this README does not assert that every test currently passes.

---

<div align="center">

**Built for an AI assistant you can run, extend, and control yourself.**

[Explore the documentation](docs/INSTALL.md) · [View the roadmap](JARVIS_MASTER_PLAN.md) · [Browse the code](https://github.com/Daan298261/Jarvis)

</div>
