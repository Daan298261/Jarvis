# Architecture

Jarvis is a local-first control plane for autonomous work. The current implementation is a single-machine FastAPI + React + SQLite application with a local/remote OpenAI-compatible model provider. Long-term swarm design lives in [`SWARM_ARCHITECTURE.md`](SWARM_ARCHITECTURE.md); priority and queue in [`JARVIS_MASTER_PLAN.md`](JARVIS_MASTER_PLAN.md) and [`project_goals.md`](project_goals.md).

Default model path: Qwen3.5-9B Abliterated via llama.cpp (fully GPU-resident), with 27B profiles as fallbacks.

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
llama-server (localhost:8088)  or  another OpenAI-compatible /v1 host
  Qwen3.5-9B Abliterated GGUF + mmproj  (default, fully GPU-resident)
```

## Model provider

`backend/app/providers/base.py` defines `ModelProvider`. The only built-in implementation is `OpenAICompatProvider`, used for:

- local llama.cpp
- another machine on the LAN
- a dedicated multi-GPU server

Swap by pointing `inference.host`/`port` or `inference.base_url` at any OpenAI-compatible `/v1` endpoint (`backend: openai-compat`). Jarvis connects as a client; it does not spawn llama.cpp and does not bind llama-server to the LAN. No agent code changes. Default remains local llama.cpp on `127.0.0.1:8088`. Optional `JARVIS_INFERENCE_API_KEY` is read from the environment only.

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

Older tool traces are summarized so long tasks do not dump the full history back into the 32K window.

## Autonomy

`interactive` confirms medium+ tools, `trusted` confirms high/irreversible, `autonomous` only pauses for irreversible operations (disk format, credential changes, mass-delete patterns, purchases, unsolicited external communications).

## Frontend

React + TypeScript + Vite, built into `frontend/dist` and served by FastAPI so there is a single local URL.

## Voice

Local Whisper (faster-whisper, CPU `tiny.en` by default) and local TTS wrap the same task API. The agent is unchanged.

- `GET /api/voice/status`
- `POST /api/voice/transcribe` — WAV upload → text
- `POST /api/voice/speak` — text → `audio/wav`
- `POST /api/voice/command` — already-transcribed text → task
- `POST /api/voice/command-audio` — audio upload → Whisper → task

Portal: **Voice**, plus Mic / Speak on Command. First transcription downloads the Whisper model into `models/whisper`. Optional Piper: put `piper.exe` in `runtime/piper` and an `.onnx` voice in `models/piper`. `JARVIS_WHISPER_DEVICE=cuda` is available but not the default (keeps VRAM for Qwen).

## Phone client

`/phone` is a mobile UI for the same task API (`POST/GET /api/tasks`, continue, cancel). Native Android can call those endpoints with `X-Jarvis-Token` (`clients/android/JarvisApi.kt`). Discovery: `GET /api/phone`.
