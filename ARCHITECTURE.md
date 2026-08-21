# Architecture

Jarvis is a local control plane around a Qwen3.5-27B llama.cpp server.

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
  Qwen3.5-27B GGUF + mmproj
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
3. Inspect with tools
4. Plan
5. Execute the next tool call
6. Persist the observation
7. Classify success vs failure
8. Diagnose
9. Choose a different strategy (identical retries are blocked)
10. Repeat until criteria can be checked
11. Independent verification prompt with tools still available
12. Final report only after that pass

Task state is checkpointed in SQLite after every tool call. `POST /api/tasks/{id}/continue` reloads compacted conversation state.

## Context compaction

Older tool traces are summarized so long tasks do not dump the full history back into the 32K window. The kept tail always starts on a message that leaves each tool result paired with the assistant turn that requested it, and the compact working state (goal, criteria, plan, known failures) is rebuilt on every pass instead of accumulating.

## Memory

`trajectories` records how each task actually went; `skills` holds workflows that succeeded repeatedly with the same tool sequence. Both are injected into the system prompt of similar later tasks. See `TOOLS.md`.

## Recovery

`backend/app/agent/recovery.py` classifies a tool failure and names alternatives ordered by determinism, so a failed COM or GUI path is answered with a library or CLI suggestion rather than a retry. Permission and blocked-command failures get no alternative.

## Autonomy

`interactive` confirms medium+ tools, `trusted` confirms high/irreversible, `autonomous` only pauses for irreversible operations (disk format, credential changes, mass-delete patterns, purchases, unsolicited external communications).

## Frontend

React + TypeScript + Vite, built into `frontend/dist` and served by FastAPI so there is a single local URL.

## Voice-ready API

`POST /api/voice/command` accepts already-transcribed text. Whisper STT and local TTS can wrap this later without changing the agent.
