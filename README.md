# Jarvis

Self-hosted local desktop agent. The default model is **Qwen3.5-9B Abliterated** running on this computer through llama.cpp (Qwen3.5-27B remains the Expert escalation model, or you can point at any OpenAI-compatible server). The web portal at [http://127.0.0.1:4780](http://127.0.0.1:4780) is the control surface; the same REST API can later drive voice, Android, or automations. Use **Guide & Workflows** for operating instructions and one-click templates (debug a project, research to spreadsheet, organize files, and others).

**Development process:** [`docs/PROCESS.md`](docs/PROCESS.md) — one RFC or one queue item per worker; branch from `cursor/local-qwen-desktop-agent`. Design specs go in [`docs/rfcs/`](docs/rfcs/), not wholesale edits to the master plan.

Cursor and future development sessions must read [`JARVIS_MASTER_PLAN.md`](JARVIS_MASTER_PLAN.md) for architecture context and the Development Queue (§58). Jarvis 1.x is sections 1–63. Jarvis 2.0 (Autonomous Operator / Away Mode, including novel/marketing/SEO/multimedia) lives in [`JARVIS_2.0.md`](JARVIS_2.0.md) and is not current-session P0 unless the queue promotes it.

Detailed P2+ swarm role, node placement, resource-control, and universal-UI requirements are maintained separately in [`SWARM_ARCHITECTURE.md`](SWARM_ARCHITECTURE.md). The master plan remains authoritative for priority and implementation status.

## Documentation

| Document | Contents |
| --- | --- |
| **[docs/PROCESS.md](docs/PROCESS.md)** | RFC workflow, one-ticket Cursor loop, cloud vs desktop sign-off |
| **[docs/rfcs/](docs/rfcs/)** | Design RFCs (template + index) |
| **[docs/INSTALL.md](docs/INSTALL.md)** | Full Windows install: Python, Node, llama.cpp, GGUFs, start options, LAN auth, updates |
| **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** | Repo map, dev servers, API, agent loop, adding tools, tests |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Control plane, compaction, memory, autonomy |
| [SWARM_ARCHITECTURE.md](SWARM_ARCHITECTURE.md) | P2–P4 node roles, placement, resources, swarm UI, multi-node and resilience requirements |
| [ADAPTIVE_DOMAIN_ARCHITECTURE.md](ADAPTIVE_DOMAIN_ARCHITECTURE.md) | P4/P5 adaptive intelligence and domain packs |
| [ANDROID_CLIENT.md](ANDROID_CLIENT.md) | Android client to the Leader; AI-guided WAN reachability |
| [JARVIS_2.0.md](JARVIS_2.0.md) | Approved Away Mode / novel / marketing / SEO / multimedia (sections 64–85) |
| [HOME_IOT.md](HOME_IOT.md) | Home IoT / mansion house control |
| [SECURITY_AGENTS.md](SECURITY_AGENTS.md) | Blue / Purple / Red-gated security workers (canonical). `BLUE_TEAM.md` is a pointer |
| [BLUE_TEAM.md](BLUE_TEAM.md) | Pointer to `SECURITY_AGENTS.md` |
| [INSTALLER.md](INSTALLER.md) | Windows 11 consumer `.exe` onboarding (P1; not shipped until the `.exe` exists) |
| [TOOLS.md](TOOLS.md) | Native tools, MCP, trajectories, skills |
| [SECURITY.md](SECURITY.md) | Bind address, private keys, filesystem policy |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Unloaded model, CUDA, Playwright, Office, Docker |

## Hardware this install was tuned for

- Windows 11 Pro
- Intel Core i7-14700KF
- 64 GB RAM
- NVIDIA GeForce RTX 5070 Ti (16 GB VRAM, CUDA 13.0)
- llama.cpp b10516, Windows CUDA 13.3 build

The default 9B Q8_0 profile is meant to stay on the GPU. Expert 27B Q4_K_M (~16.7 GB) still uses llama.cpp `--fit on`. The vision projector is off unless you enable it.

## Quick start (already cloned on this machine)

```powershell
python -m pip install -r backend\requirements.txt
python -m playwright install chromium
cd frontend
npm install
npm run build
cd ..
.\start-jarvis.ps1
```

New machine, missing GGUFs, or llama.cpp not extracted: follow **[docs/INSTALL.md](docs/INSTALL.md)** instead of this block.

llama.cpp CUDA binaries live in `runtime/llama.cpp`. Primary weights live in `models/Qwen3.5-9B-abliterated-GGUF`. Expert 27B weights live in `models/Qwen3.5-27B-GGUF`.

## Daily use

```powershell
.\start-jarvis.ps1
.\stop-jarvis.ps1
```

`start-jarvis.ps1` verifies dependencies, builds the frontend if needed, starts the API, loads the model, and opens the portal.

```powershell
# One prompt on launch, wait until the task finishes
.\start-jarvis.ps1 -Prompt "Inspect directory and generate project report" -Wait

# From a JSON or text file
.\start-jarvis.ps1 -PromptFile .\tasks\sample_task.json -Wait

# LAN bind + private key on every API request
.\start-jarvis.ps1 -LanAccess -PrivateKey "jarvis_pk_secret123"

.\start-jarvis.ps1 -NoBrowser
```

Drop `.json` or `.prompt` files into `data/queue/pending/` at any time; Jarvis processes them automatically. Remote clients must send `X-Jarvis-Key`, `Authorization: Bearer <key>`, or `?key=<key>`.

## Model profiles

Portal: **Model → Fast / Balanced / Quality**, or:

```powershell
Invoke-RestMethod -Method POST http://127.0.0.1:4780/api/model/load `
  -ContentType application/json -Body '{"profile":"quality"}'
```

- **Fast**: Q4_K_M, thinking off, 16K context
- **Balanced**: Q4_K_M, thinking on, 32K context
- **Quality**: Q5_K_M, thinking on, more CPU offload

Agent execution modes (Fast / Balanced / Reliable) are separate — they change planning and verification, not the GGUF.

## Move inference off this PC

```powershell
Invoke-RestMethod -Method PUT http://127.0.0.1:4780/api/settings `
  -ContentType application/json `
  -Body '{"inference_backend":"remote","inference_host":"192.168.1.50","inference_port":8088}'
```

No agent, tool, or portal code changes. Set the backend back to `llama.cpp` to run locally again.

## Tests

Unit tests (no GPU):

```powershell
python -m pytest tests -q
```

Live desktop suite (Jarvis running with the model loaded):

```powershell
python tests\run_e2e.py
```

Contributor workflow: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
