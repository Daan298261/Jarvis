# Jarvis documentation

These guides describe the **current** Jarvis repository: a local-first desktop agent around Qwen3.5-27B, a FastAPI control plane, and a React portal.

| Document | Audience |
| --- | --- |
| **[PROCESS.md](PROCESS.md)** | **How design (RFCs) and implementation (one ticket per worker) flow — read first** |
| [rfcs/](rfcs/) | Short RFCs (problem, decision, acceptance criteria); design handoff from ChatGPT/Codex |
| [INSTALL.md](INSTALL.md) | First-time setup on the Windows desktop (Python, Node, llama.cpp, GGUFs, start/stop) |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Contributors changing backend, portal, tools, inference, or tests |
| [../README.md](../README.md) | Operator overview and daily commands |
| [../ARCHITECTURE.md](../ARCHITECTURE.md) | Control-plane diagram and agent lifecycle |
| [../TOOLS.md](../TOOLS.md) | Native tools, MCP, trajectories, and skills |
| [../SECURITY.md](../SECURITY.md) | Bind address, private-key auth, filesystem policy |
| [../TROUBLESHOOTING.md](../TROUBLESHOOTING.md) | Model load, CUDA, Playwright, Office, Docker |
| [../JARVIS_MASTER_PLAN.md](../JARVIS_MASTER_PLAN.md) | Persistent architecture, current state, and development queue |

Product intent and unfinished work live in the master plan. Installation and day-to-day development live here so those sections stay short and accurate.
