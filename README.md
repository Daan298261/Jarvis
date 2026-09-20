<div align="center">

# JARVIS

### Your AI. Your hardware. Your rules.

**A self-hosted AI assistant and agent platform built for local-first work, extensible tools, and a future multi-device swarm.**

[Getting started](#getting-started) · [Features](#what-jarvis-does) · [Architecture](#how-it-works) · [Documentation](#documentation) · [Contributing](#development--contributing)

![Platform](https://img.shields.io/badge/platform-Windows%2011-0078D4?style=flat-square) ![Deployment](https://img.shields.io/badge/deployment-self--hosted-202C3A?style=flat-square) ![Inference](https://img.shields.io/badge/inference-local--first-16A34A?style=flat-square) ![Status](https://img.shields.io/badge/status-active%20development-F59E0B?style=flat-square)

</div>

---

## An assistant that works on your terms

Jarvis brings local language models, tool execution, task management, and an approachable control interface together in one self-hosted system. Run inference on your own machine, connect an OpenAI-compatible inference server when needed, and build workflows around the tools you actually use.

The project is being developed toward a larger vision: a coordinated network of devices with specialized agents, persistent services, and configurable autonomy. **The current Windows desktop agent is the foundation; the full swarm and autonomous-operator vision are ongoing development, not features promised in this release.**

## What Jarvis does

| Capability | Description |
| :--- | :--- |
| **Local-first AI** | Run GGUF models with llama.cpp, switch model profiles, or use a compatible remote inference endpoint. |
| **Agent workflows** | Submit tasks, use integrated tools, and track execution through the portal and task queue. |
| **Unified control portal** | Access chat, model controls, settings, help, and workflows from a local web interface. |
| **Extensible tools** | Work with native tools and MCP integrations; see the tool catalog for available integrations and requirements. |
| **Configurable access** | Keep the service on localhost by default or explicitly enable authenticated LAN access. |
| **Developer-friendly** | Work with documented architecture, RFCs, tests, and a defined contribution process. |

**On the roadmap:** a universal desktop experience, richer voice and vision, Android companionship, agent teams, multi-node scheduling, role-based device placement, security workers, and autonomous operator workflows. These are tracked in the design documents below; individual components may be experimental or incomplete.

## Getting started

**Target platform:** Windows 11. The repository's startup scripts and some desktop integrations are Windows-specific. A GPU-capable NVIDIA setup is used for the documented local inference configuration.

For a new machine, start with the **[complete installation guide](docs/INSTALL.md)**. A Windows installer is also under development; see [installer status](INSTALLER.md) before assuming one-click setup is complete.

If you have **already cloned the repository and installed the required model weights and llama.cpp runtime**, run the following in PowerShell from the repository root:

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
