# Architecture

Jarvis is a local control plane around llama.cpp. The default model is Qwen3.5-9B Abliterated; Qwen3.5-27B is the Expert escalation profile.

Overall project priority and current implementation state live in [`JARVIS_MASTER_PLAN.md`](JARVIS_MASTER_PLAN.md). Detailed P2+ swarm role, placement, resource-control, node-management, and universal-UI requirements live in [`SWARM_ARCHITECTURE.md`](SWARM_ARCHITECTURE.md).

## Current 1.x topology

```text
Browser (localhost:4780)
        │  REST + SSE + WebSocket
        ▼
FastAPI backend / Orchestrator
  ├── Task store (SQLite)
  ├── Agent runtime (plan → act → observe → recover → verify)
  ├── Tool registry (filesystem, terminal, python, browser, browser_use, code_worker, desktop, office, git, docker, web_fetch, screenshot, MCP)
  └── Model provider interface
            │  OpenAI-compatible HTTP
            ▼
llama-server (localhost:8088)
  Qwen3.5-9B Abliterated GGUF (default) or Qwen3.5-27B Expert
  mmproj only when vision is enabled
```

Today the host PC implicitly performs every physical role. Swarm work must refactor that assumption incrementally rather than replace the working control plane.

## Core terminology

These concepts must remain distinct:

- **Orchestrator** — Jarvis control plane: task decomposition, scheduling, policy, workflow state, tool/worker coordination, recovery, verification, and eventually node placement.
- **Node** — a physical or virtual participating device/machine.
- **Worker** — a software execution service or agent, such as a local coding worker, `CursorACPWorker`, browser worker, model worker, or multimedia worker. Workers run on eligible Nodes.
- **Leader** — the strongest or most capable general-purpose execution Node currently available. It is an execution designation, not the control plane.
- **Senior / Junior / Peripheral** — node execution classes from `SWARM_ARCHITECTURE.md`. In code these should be represented as Node class/role data rather than software Worker subclasses.
- **Capability** — something a Node/Worker can technically perform.
- **Role policy** — what the user/Jarvis prefers or requires a Node/service to perform.
- **Resource budget / lease** — how much host capacity Jarvis may consume and what a task temporarily requires.

The scheduler must ultimately answer two different questions: **which Worker/model should do the task?** and **which Node should host that execution?** Do not collapse intelligence routing into physical placement.

## One-node swarm invariant

Jarvis must become swarm-ready before it becomes distributed. P2 should make the existing desktop register as a Node and route work through Node/capability/resource abstractions even when every placement decision resolves to `localhost`.

```text
Current desktop
Node class: Leader
Possible roles: Orchestrator + Leader
Workers: local model, tools, Cursor ACP, browser, desktop, future media workers
```

Adding another machine later should extend the registry/placement choices, not require a scheduler rewrite.

## Model provider

`backend/app/providers/base.py` defines `ModelProvider`. The built-in `OpenAICompatProvider` can talk to local llama.cpp or another OpenAI-compatible endpoint. Server lifecycle is abstracted separately through inference backends.

- local llama.cpp
- another machine on the LAN
- a dedicated multi-GPU server

Swap by pointing `inference.host`/`port` at any OpenAI-compatible `/v1` endpoint, or pick `ollama` / `lmstudio` / `vllm` / `sglang` / `remote` on Settings. `GET /api/model/probe` lists advertised models. No agent code changes.

## Agent lifecycle

`backend/app/agent/loop.py` runs an explicit loop:

1. Understand the requested end state.
2. Capture acceptance criteria.
3. In Reliable mode, generate candidate plans and select one.
4. Inspect with deterministic tools.
5. Plan and execute the next action.
6. Persist the observation.
7. Classify success vs failure.
8. Diagnose failures and choose a materially different strategy.
9. Repeat until acceptance criteria can be checked.
10. Run an independent verification pass.
11. Report completion only after verification.

Task state is checkpointed in SQLite after tool calls. `POST /api/tasks/{id}/continue` reloads compacted state.

## Context, memory, and recovery

Older tool traces are compacted so long tasks do not continually resend raw history. `trajectories` record useful execution outcomes and `skills` store repeatable workflows; hidden reasoning is not stored. Recovery classifies failures and prefers deterministic alternatives rather than identical retries.

These systems remain Orchestrator-owned when Workers become remote. A remote Worker may report execution evidence, but the Orchestrator retains task state and final verification authority unless a later explicit architecture decision changes that boundary.

`trajectories` records how each task actually went; `skills` holds workflows that succeeded repeatedly with the same tool sequence. Parameterized skills execute their bound tool steps instead of only injecting advice. Repeated stable browser procedures become BrowserCode-style skills. Both are injected into the system prompt of similar later tasks. See `TOOLS.md`.

Live model timings (tok/s, VRAM, RAM, load time) and task success rates are persisted in `benchmark_samples` and shown on the Model page. llama.cpp starts without the vision projector unless vision mode is `always` or a screenshot is attached. Balanced/Quality profiles keep the reasoning parser available and toggle `enable_thinking` per turn.

Worker selection must remain compatible with swarm placement:

```text
Task
  ↓
Intelligence / Worker routing
  ↓
Capability + policy + resource requirements
  ↓
Node placement
  ↓
Execution
  ↓
Independent verification
```

## P2 swarm-ready target

P2 implements the local abstractions from `SWARM_ARCHITECTURE.md` without requiring networking:

- first-class Node identity/state;
- software Worker registration separate from Nodes;
- Orchestrator vs Leader separation;
- capability registry;
- role policies (`AUTO`, `PREFERRED`, `FORCED`, `AVOID`, `DISABLED`);
- host resource budgets and hard/soft caps;
- resource leases;
- task priority;
- data-locality and warm-worker/model signals;
- single-node placement scheduler;
- universal dynamic UI contract / Swarm settings surface.

## P3 multi-node target

P3 adds actual distribution:

- discovery and secure pairing;
- authenticated remote execution;
- heartbeats and resource telemetry;
- cross-node placement;
- network/data-transfer-aware scheduling;
- role recommendations/re-evaluation;
- universal join/install flow;
- node management UI.

## P4 resilience target

P4 adds fault tolerance and advanced infrastructure:

- active/passive standby Orchestrators;
- restart-safe control-plane state replication/failover;
- affinity/anti-affinity and advanced placement constraints;
- optional service separation/replication when justified.

Security/SIEM/forensics are future specialized roles only. Their appearance in the swarm specification reserves architectural placement semantics; it does not authorize implementation before those systems are separately specified.

## Frontend

The existing React + TypeScript + Vite portal is the basis of the universal UI. Do not create separate Windows/Linux/Pi frontends. Future desktop/mobile wrappers should reuse the same frontend and expose host-specific capabilities through APIs/bridges. Tauri is the preferred future desktop-shell candidate in the swarm specification, with Electron as an alternative.

## Voice

`GET /api/voice/status` reports local STT/TTS. `POST /api/voice/command` still accepts already-transcribed text. `POST /api/voice/listen` transcribes uploaded audio with local Whisper when installed. `POST /api/voice/speak` returns WAV from Windows SAPI, espeak-ng, or pyttsx3. Cloud speech APIs are not used. The Command page has a Speak button and an optional Speak-results toggle.

## Implementation rule

Do not replace the FastAPI + React + SQLite core merely to obtain swarm terminology. Introduce P2 abstractions incrementally, preserve the current one-machine behavior, test them locally, then add P3 networking. The detailed swarm spec is intentionally separate so `ARCHITECTURE.md` can describe the implemented/current shape without duplicating the full future requirement set.
