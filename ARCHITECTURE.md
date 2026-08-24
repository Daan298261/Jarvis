# Architecture

Jarvis is a local control plane around llama.cpp. The default model is Qwen3.5-9B Abliterated; Qwen3.5-27B is the Expert escalation profile.

```
Browser (localhost:4780)
        │  REST + SSE + WebSocket
        ▼
FastAPI backend
  ├── Task store (SQLite)
  ├── Agent runtime (plan → act → observe → recover → verify)
  ├── Tool registry (filesystem, terminal, python, browser, desktop, office, git, docker, web_fetch, screenshot, MCP)
  └── Model provider interface
            │  OpenAI-compatible HTTP
            ▼
llama-server (localhost:8088)
  Qwen3.5-9B Abliterated GGUF (default) or Qwen3.5-27B Expert
  mmproj only when vision is enabled
```

## Model provider

`backend/app/providers/base.py` defines `ModelProvider`. The only built-in implementation is `OpenAICompatProvider`, used for:

- local llama.cpp
- another machine on the LAN
- a dedicated multi-GPU server

Swap by pointing `inference.host`/`port` at any OpenAI-compatible `/v1` endpoint. No agent code changes.

## Agent lifecycle

`backend/app/agent/loop.py` runs an explicit loop:

1. Understand the requested end state
2. Capture acceptance criteria (model + prompt)
3. In Reliable mode, generate three candidate plans and select one
4. Inspect with tools
5. Plan
6. Execute the next tool call
7. Persist the observation
8. Classify success vs failure
9. Diagnose
10. Choose a different strategy (identical retries are blocked)
11. Repeat until criteria can be checked
12. Independent verification prompt with tools still available
13. Final report only after that pass

Task state is checkpointed in SQLite after every tool call. `POST /api/tasks/{id}/continue` reloads compacted conversation state.

## Context compaction

Older tool traces are summarized so long tasks do not dump the full history back into the 32K window. The kept tail always starts on a message that leaves each tool result paired with the assistant turn that requested it, and the compact working state (goal, criteria, plan, known failures) is rebuilt on every pass instead of accumulating.

## Memory

`trajectories` records how each task actually went; `skills` holds workflows that succeeded repeatedly with the same tool sequence. Parameterized skills execute their bound tool steps instead of only injecting advice. Both are injected into the system prompt of similar later tasks. See `TOOLS.md`.

Live model timings (tok/s, VRAM, RAM, load time) and task success rates are persisted in `benchmark_samples` and shown on the Model page.

## Recovery

`backend/app/agent/recovery.py` classifies a tool failure and names alternatives ordered by determinism, so a failed COM or GUI path is answered with a library or CLI suggestion rather than a retry. Permission and blocked-command failures get no alternative.

## Autonomy

`interactive` confirms medium+ tools, `trusted` confirms high/irreversible, `autonomous` only pauses for irreversible operations (disk format, credential changes, mass-delete patterns, purchases, unsolicited external communications).

## Frontend

The portal is React + TypeScript + Vite, built into `frontend/dist` and served by FastAPI so there is a single local URL. Pages: Command, History, Guide & Workflows, Memory, Model, Tools, MCP, Settings, System. Guide & Workflows loads templates from `/api/workflows`, lets you edit parameters and chained stages, saves presets to `data/workflows/`, and dispatches one task via `POST /api/workflows/run`.

## Voice-ready API

`POST /api/voice/command` accepts already-transcribed text. Whisper STT and local TTS can wrap this later without changing the agent.

## Jarvis 2.0 target

The 1.x control plane above is the foundation. Jarvis 2.0 (see `JARVIS_MASTER_PLAN.md` sections 64–85) adds event-driven intake, a `SoftwareEngineeringWorker` under Jarvis orchestration, isolated worktrees, a policy engine, remote approvals, and eventually distributed `WorkerNode`s. None of that is implemented yet. Do not redesign the FastAPI + SQLite core to get there.
