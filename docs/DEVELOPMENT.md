# Develop Jarvis

This guide is for changing the current codebase. Installation of models and llama.cpp is in [INSTALL.md](INSTALL.md). Product intent, unfinished work, and the session bootstrap live in [`JARVIS_MASTER_PLAN.md`](../JARVIS_MASTER_PLAN.md) — read that file before substantial changes, and keep its Current State / Development Queue accurate when you ship something.

Jarvis is a local control plane, not a chatbot wrapper. Optimize for autonomous completion and verification, not for swapping the stack.

---

## 1. What you are working on

```
Browser (localhost:4780, or Vite 5173 in dev)
        │  REST + SSE + WebSocket
        ▼
FastAPI (backend/app)
  ├── Task store (SQLite)
  ├── Agent runtime (plan → act → observe → recover → verify)
  ├── Tool registry + MCP
  └── ModelProvider (OpenAI-compatible HTTP)
            │
            ▼
InferenceBackend
  ├── llama.cpp — Jarvis starts llama-server (localhost:8088)
  └── remote / ollama / lmstudio / vllm / sglang — probe only (LAN GPU box, LM Studio, Ollama, vLLM, SGLang)
```

The React portal is built into `frontend/dist` and served by FastAPI so operators have a single local URL. Vite is for development only.

---

## 2. Repository map

```
backend/app/
  main.py                 FastAPI app, auth middleware, SPA mount, startup/shutdown
  config.py               AppSettings, paths, env overlays
  auth.py                 Private-key extract / verify
  events.py               In-process event bus for WS + SSE
  hardware.py             CPU/RAM/GPU probe (nvidia-smi)
  api/                    REST routers (prefix /api/…)
    agent/
    loop.py               AgentRuntime — create/continue/cancel, verification
    thinking.py           Selective thinking (plan/recover vs routine tools)
    context_policy.py     8K / 16K / 32K from task class + execution mode
    planning.py           ExecutionPolicy, task classification, best-of-N plan parse/select
    coding_workers.py     Software-dev worker router (complexity 0–100, cheapest capable worker)
    agent_benchmark.py    P0.9 20-task representative suite + scoring
    workflows.py          Guide copy + editable templates + compose_prompt
    recovery.py           Failure classes → alternative tools
    compaction.py         History summary that cannot orphan tool results
    trajectory.py         Cross-task lessons (no hidden reasoning)
    skills.py             Promote after 3 identical successful tool sequences
    queue_watcher.py      data/queue/pending file drop
    worktrees.py          Isolated git worktrees for self-development
    self_dev.py           Trial budget, kill switch, verification gate, reports
    prompts.py            System / plan / verify / critic prompts
    inference/
    manager.py            Load/unload, adopt already-running server
    backends.py           LlamaCppBackend vs RemoteOpenAICompatibleBackend
    profiles.py           fast / balanced / quality (9B) plus expert (27B)
  providers/              OpenAI-compatible chat + tool-call parsing
    workers/                Optional Browser Use, OpenHands, Open Interpreter, UFO, Cua adapters
  tools/                  Native tools + MCP proxy + code_worker
  db/                     SQLAlchemy models, aiosqlite session, light migrations
frontend/src/
  App.tsx                 Routes: Command, Phone, History, Guide & Workflows, Memory, Model, Tools, MCP, Settings, System
  api.ts                  fetch helper + X-Jarvis-Key from localStorage
  pages/                  One page per portal tab (Workflows.tsx is Guide & Workflows)
config/default.json       Checked-in defaults (copied into data/settings.json)
tests/                    pytest unit tests; run_e2e.py / smoke_task.py against a live API
start-jarvis.ps1          Operator start (Windows)
stop-jarvis.ps1           Operator stop
```

Gitignored runtime: `data/`, `logs/`, `models/`, `runtime/llama.cpp/`, `frontend/node_modules/`, `frontend/dist/`.

---

## 3. Day-to-day loop

### Backend only (no GGUF)

Useful for API, agent, and tool work. Unit tests mock the model.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
$env:PYTHONPATH = "$PWD\backend"
$env:JARVIS_SKIP_MODEL = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 4780 --app-dir backend --reload
```

Health: `http://127.0.0.1:4780/api/health`. Tasks will fail to run until a model is loaded unless tests inject a fake provider.

### Frontend with HMR

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Vite listens on **5173** and proxies `/api` (including WebSocket) to `127.0.0.1:4780`. CORS already allows `http://127.0.0.1:5173`. Open the Vite URL while uvicorn is running; do not expect the API to live on 5173.

Production check (what FastAPI actually serves):

```powershell
cd frontend
npm run build
npm run lint
```

`npm run build` runs `tsc -b && vite build`. FastAPI mounts `frontend/dist/assets` and falls back to `index.html` for SPA routes.

### Full stack like an operator

```powershell
.\start-jarvis.ps1 -NoBrowser
```

Use `-SkipModelLoad` when you do not want llama.cpp. Remember `start-jarvis.ps1` requires `llama-server.exe`, Q4_K_M, and mmproj even with `-SkipModelLoad` today — for API-only work, start uvicorn yourself as above.

---

## 4. Linux / cloud agents

The product target is Windows. `pywin32` and `pywinauto` in `backend/requirements.txt` do not install on Linux.

On Linux you can still:

- Edit code and docs
- Install the remaining Python deps (omit or comment those two lines)
- Run pytest for non-Windows modules
- Build the frontend (`npm run build`)

You cannot: run `start-jarvis.ps1`, load the desktop GGUF path this repo expects (`llama-server.exe`), or exercise Office/desktop COM. Terminal default is PowerShell on Windows and bash on Linux.

---

## 5. Settings and environment

`load_settings()` merges `config/default.json` ← `data/settings.json` ← environment.

| Env var | Where it is read |
| --- | --- |
| `JARVIS_PRIVATE_KEY`, `JARVIS_API_KEY`, `JARVIS_AUTH_TOKEN` | `config.py` — effective private key |
| `JARVIS_BIND_HOST`, `JARVIS_BIND_PORT` | bind overlay |
| `JARVIS_SKIP_MODEL` | skip auto-load in `main.py` startup |
| `JARVIS_LAUNCH_PROMPT`, `JARVIS_LAUNCH_PROMPT_FILE` | enqueue on startup |
| `JARVIS_URL` | `tests/run_e2e.py` base URL (default `http://127.0.0.1:4780`) |
| `JARVIS_TEST_TIMEOUT` | e2e wait seconds (default 900) |

`PUT /api/settings` is the programmatic settings API (autonomy, directories, inference backend/host/port, LAN/auth, browser headless, `professional_mode`, `vision` lazy/always/off, and so on). `auth_token` is never written back to `data/settings.json`.

Default allowed directories: Desktop, Documents, Downloads, repo root, `data/`. Tools refuse paths outside that list.

---

## 6. REST API (current)

All JSON. When `auth_required` or `lan_access` is on, send `X-Jarvis-Key`, `Authorization: Bearer`, or `?key=`.

| Method | Path | Role |
| --- | --- | --- |
| GET | `/api/health` | Liveness (no auth) |
| GET | `/api/mobile` | Phone/PWA pairing info (no auth, never includes the private key) |
| WS | `/api/ws` | Live task events |
| GET | `/api/auth/status` | Whether auth is on / key present |
| POST | `/api/auth/verify` | Check a key |
| POST | `/api/auth/generate-key` | Create `jarvis_pk_…` and save `data/private_key.sec` |
| POST | `/api/auth/configure` | Toggle auth / LAN / set key |
| POST | `/api/tasks` | `{ prompt, autonomy?, profile?, execution_mode? }` — starts the loop |
| GET | `/api/tasks` | Newest first |
| GET | `/api/tasks/{id}` | Task + events + tool calls |
| POST | `/api/tasks/{id}/continue` | `{ prompt?, approve? }` — resume or confirm a risky tool |
| POST | `/api/tasks/{id}/cancel` | Cooperative cancel |
| GET | `/api/tasks/{id}/events` | SSE stream |
| GET/POST | `/api/queue`, `/enqueue`, `/process` | File-drop queue |
| GET | `/api/model` | Load state + profiles + hardware gate + agent suite |
| GET | `/api/model/hardware-gate` | P0.12 purchase recommendation (always defer until desktop evidence) |
| GET | `/api/model/agent-suite` | P0.9 20-task catalog + recent results |
| POST | `/api/model/agent-suite/run` | `{ case_id, simulate_success? }` prepare/score one case |
| POST | `/api/model/load` | `{ profile? }` |
| POST | `/api/model/unload` | Stop llama-server if Jarvis owns it |
| GET | `/api/model/benchmarks` | Persisted tok/s / VRAM samples |
| POST | `/api/model/benchmarks/snapshot` | Capture current resource snapshot |
| GET | `/api/model/harness` | Last benchmark report + 20-task catalog |
| POST | `/api/model/harness` | `{ live?, background? }` — dry-run matrix by default; live measures the loaded model only |
| GET | `/api/tools`, `/api/tools/catalog` | Registry + optional-worker catalog |
| GET | `/api/tools/coding-workers` | Software-dev worker catalog; `?prompt=` returns a route |
| POST | `/api/tools/{name}/enable` / `disable` | Persist `disabled_tools` |
| GET/PUT | `/api/settings` | Full settings dump / patch |
| GET/POST/DELETE | `/api/mcp`, `/api/mcp/{id}`, `/refresh` | MCP servers |
| GET | `/api/mcp/jarvis` | Built-in Jarvis MCP manifest for Cursor |
| GET/POST | `/api/coding/mcp`, `/api/coding/mcp/call` | Invoke Jarvis MCP tools over HTTP |
| GET | `/api/coding/escalations` | Compact EscalationContext packages |
| GET/POST | `/api/coding/acp`, `/connect`, `/answer` | Cursor ACP status, session persist, auto-answer preview |
| GET | `/api/memory/trajectories` | Trajectory memory |
| GET/POST/DELETE | `/api/memory/skills` | Skills; `POST /skills/promote` |
| POST | `/api/memory/skills/{id}/enable` or `disable` | Toggle skill |
| GET | `/api/system` | Hardware + model + capabilities |
| GET | `/api/workflows/guide` | Operating-instruction copy for the portal tab |
| GET | `/api/workflows` | Builtin + saved templates |
| GET | `/api/workflows/{id}` | One template |
| POST | `/api/workflows` | Save a preset under `data/workflows/` |
| DELETE | `/api/workflows/{id}` | Delete a saved preset (not a builtin) |
| POST | `/api/workflows/run` | Fill placeholders, compose stages, create a task |
| GET | `/api/self-dev` | Isolated trial status, budget, kill switch, worktrees |
| POST | `/api/self-dev/start` | Create a dedicated worktree/branch from a repo (never the running checkout) |
| POST | `/api/self-dev/stop` | Emergency kill switch (`data/STOP_JARVIS`); cancels tasks, preserves Git |
| POST | `/api/self-dev/resume` | Clear the kill switch |
| POST | `/api/self-dev/worktrees/{id}/checkpoint` | Commit only inside the isolated worktree |
| POST | `/api/self-dev/worktrees/{id}/verify` | Independent pytest gate; never auto-merges |
| POST | `/api/self-dev/worktrees/{id}/discard` | Remove the experimental worktree only |
| POST | `/api/self-dev/report` | End-of-run development report |
| POST | `/api/self-dev/merge` | Always 403 during trials |
| POST | `/api/voice/command` | `{ text, autonomy? }` — already-transcribed speech |
| POST | `/api/voice/listen` | multipart `audio` — local Whisper, then create a task |
| POST | `/api/voice/transcribe` | multipart `audio` — transcript only |
| POST | `/api/voice/speak` | `{ text }` — local TTS WAV |

Voice stays on this machine. If Whisper is missing, type on Command as usual. Windows SAPI / espeak-ng / pyttsx3 provide TTS.

---

## 7. Agent loop (what to preserve)

`backend/app/agent/loop.py` is the orchestrator. A task:

1. Classifies (`planning.classify_task`) and stores `task_class`
2. Exposes only tools for that class (`agent/tool_exposure.py`); mixed/long-horizon tasks still get every enabled tool. `request_tools` expands the set. Command live status shows it.
3. Injects matching skills and trajectories into the system prompt
4. Asks for a plan + acceptance criteria (`PLAN_PROMPT`). In Reliable mode (`best_of_n=3`) the model writes labeled PLAN A/B/C candidates and a critic selects one before any tools run
5. Executes tool calls until the policy budget is spent
6. Blocks identical retries; `recovery_hint()` suggests a different tool for most failure classes (not permission / blocked-command)
7. After several distinct failures, may consult the Expert 27B profile with a compact brief, then reload the primary model (`agent/escalation.py`)
8. Always runs an independent verification pass (`VERIFY_PROMPT`) before `completed`
9. Reliable mode also requires a verification **tool** call and a critic pass
10. Records a trajectory (tools, failures, recovery, verification — never chain-of-thought)
11. Promotes a skill only after the same task class succeeds **three** times with the same tool sequence

Execution modes (`planning.POLICIES`) are **not** model profiles:

| Mode | max_steps | Critic | Must use a verify tool | Best-of-N plans |
| --- | --- | --- | --- | --- |
| fast | 16 | no | no | 1 |
| balanced | 28 | no | no | 1 |
| reliable | 40 | yes | yes | 3 (critic picks one; it does not run three full attempts) |

Model profiles (`inference/profiles.py`): Fast / Balanced / Quality change quant, whether thinking is allowed, and the context ceiling. Per-turn thinking is selective (`agent/thinking.py`). Per-task context is 8K/16K/32K (`agent/context_policy.py`). The vision projector is omitted unless the task needs it (`inference/vision.py`).

Autonomy (`tools/safety.py`): `interactive` confirms medium+ tools, `trusted` confirms high/irreversible, `autonomous` only pauses for irreversible patterns (disk format, credential changes, mass-delete, purchases, unsolicited external communications).

Context compaction (`agent/compaction.py`) must keep tool results paired with the assistant `tool_calls` turn. Do not “summarize the tail” in a way that orphans a `role=tool` message.

`POST /api/tasks/{id}/continue` reloads compacted conversation JSON from SQLite.

---

## 8. Adding a native tool

1. Subclass `Tool` in `backend/app/tools/` (`name`, `description`, JSON Schema `parameters`, `risk`, `async execute`).
2. Return `ToolResult(success, output, data=, error=)`.
3. Register the instance in `ToolRegistry._init_tools` (`registry.py`).
4. If the tool is optional, add a row to `tools/capabilities.py` so Tools/System pages show `unavailable` instead of looking crashed.
5. Honor `allowed_directories` and `classify_command` / `needs_confirmation` for anything destructive.
6. Add tests under `tests/` (sandbox, safety, or a scripted-provider loop test).
7. Document the tool in [`TOOLS.md`](../TOOLS.md).

MCP tools do not need a Python class: configure servers via the MCP page or `mcp_servers` in settings. They appear as `mcp_*` functions through `MCPProxyTool`.

Do not add Browser Use / UFO / Cua / OpenHands / Open Interpreter as the primary app. Those are optional **workers** behind the existing orchestrator (see the master plan). Playwright remains the default browser backend. Adapters live in `backend/app/workers/` and register `browser_use` / `code_worker` / `open_interpreter` / `ufo` / `cua` tools that return "not installed" until the optional packages are present.

---

## 9. Adding an API route and portal page

1. Create `backend/app/api/<name>.py` with `APIRouter(prefix="/api/...", tags=[...])`.
2. `app.include_router(...)` in `main.py`.
3. Auth middleware already covers `/api/*` except the health/auth exceptions in `auth.py`.
4. Add a React page under `frontend/src/pages/`, a `<NavLink>` + `<Route>` in `App.tsx`, and calls through `api()` in `frontend/src/api.ts` (it attaches `X-Jarvis-Key` from `localStorage`).
5. Rebuild or use Vite HMR.

Keep the portal low-maintenance: Command is the main surface; History, Guide & Workflows, Memory, Model, Tools, MCP, Settings, and System already exist.

### Guide & Workflows

`backend/app/agent/workflows.py` plus `backend/app/api/workflows.py` and `frontend/src/pages/Workflows.tsx`.

- `GET /api/workflows/guide` — operating-instruction sections for the tab
- `GET /api/workflows` / `GET /api/workflows/{id}` — builtin templates merged with `data/workflows/*.json` presets
- `POST /api/workflows` — save an edited preset (cannot overwrite builtin ids; saves a copy)
- `DELETE /api/workflows/{id}` — delete a saved preset only
- `POST /api/workflows/run` — fill `{{parameter}}` placeholders, concatenate stages into one prompt, `AGENT.create_task(...)`

Builtin templates: `debug-project`, `research-spreadsheet`, `organize-files`, `browser-extract`, `browser-form`, `browser-procedure`, `web-scrape-save`, `maintenance-job`. Placeholders use `{{key}}`. Running a workflow is still **one task**; stages are prompt structure, not separate orchestrator jobs.

---

## 10. Inference changes

- Chat always goes through `ModelProvider` (`providers/base.py` → `OpenAICompatProvider`).
- Process ownership belongs in `InferenceBackend`, not in the agent.
- Local: `LlamaCppBackend.build_args` — `--jinja`, `--reasoning-format deepseek`, `--fit on` (or `--n-gpu-layers 99` if fit is off), optional `--mmproj`.
- Remote: `RemoteOpenAICompatibleBackend` (and Ollama/LM Studio/vLLM/SGLang subclasses) probe `/health`, `/v1/models`, and `/api/tags`. Aliases include `remote`, `lmstudio`, `ollama`, `vllm`, `sglang`, `openai-compatible`.
- Optional `inference.api_key` and `inference.remote_model`. `GET /api/model/probe` reports reachability and advertised models.
- Switching backend from a stock port also sets that family's default port (Ollama 11434, LM Studio 1234, …).
- Unknown backend name + non-localhost host is treated as remote.
- `InferenceManager.load` will adopt a server that is already healthy so a second Jarvis process does not spawn another llama-server.
- `POST /api/model/harness/run` — collect load/TTFT/tok/s/VRAM/RAM/CPU/GPU/context/tool-probe metrics and a **do not buy hardware yet** gate. `GET /api/model` includes the last report.

When changing CLI flags, extend `tests/test_inference_backends.py` rather than relying on a live GPU.

---

## 11. Database

SQLite file: `data/jarvis.db` (aiosqlite). Tests call `configure_database(path=tmp_path / "jarvis.db")` via the `jarvis_env` fixture.

Tables: `tasks`, `task_events`, `tool_calls`, `checkpoints`, `trajectories`, `skills`, `conversations`.

Light additive migrations live in `db/session.py` (`_add_missing_columns`). Prefer a new column + default over a rewrite. There is no Alembic.

Stop the API before copying the DB file.

---

## 12. Tests

`pytest.ini` sets `pythonpath = backend`, `asyncio_mode = auto`, and `testpaths = tests`.

```powershell
python -m pytest tests -q
```

Current unit coverage (no GPU required):

| File | What it locks in |
| --- | --- |
| `test_planning.py` | Execution modes, task classification, Reliable `best_of_n=3` |
| `test_best_of_n.py` | Parse labeled plans; critic selection |
| `test_safety.py` | Blocked commands / confirmation |
| `test_filesystem.py` | Allowed-directory sandbox; `compare` / `recent` |
| `test_workflows.py` | Builtin templates, save/run, prompt composition |
| `test_capabilities.py` | Catalog includes missing workers as unavailable |
| `test_verification_loop.py` | Cannot complete without verification; Reliable needs a verify tool |
| `test_compaction.py` | Tool results stay paired |
| `test_inference_backends.py` | llama.cpp vs remote/Ollama/LM Studio selection, CLI flags, model-list parsing |
| `test_recovery.py` / `test_recovery_loop.py` | Failure class → alternative tool |
| `test_trajectory.py` | Record / recall |
| `test_skills.py` | Promotion needs 3 repeats |
| `test_auth.py` | 401 without key; header / bearer / query |
| `test_queue.py` | File-drop watcher |
| `test_tool_exposure.py` / `test_tool_exposure_loop.py` | Task-class tool schemas and `request_tools` |
| `test_escalation.py` | Expert 27B consult policy and restore |
| `test_harness.py` | Performance harness + hardware purchase gate |
| `test_qa_guards.py` | Docker targets, browser close, python/sys, terminal default, git checkpoint, web_fetch POST |

`conftest.py` fixture `jarvis_env` points SQLite at a temp path, marks the model loaded, and applies autonomous settings.

Live Windows suite (model must be up):

```powershell
python tests\run_e2e.py
```

That script writes Desktop files, drives Playwright, fixes `tests/broken_project.py`, and checks vision + recovery. Results go to `tests/output/e2e-results.json`.

When you change agent/tool/API behavior, add or extend a unit test. Do not treat “the portal rendered” as verification.

---

## 13. Conventions

- **Local-first.** Do not send prompts, files, screenshots, or system data to cloud AI providers. Optional cloud backends may exist later; they must not become a dependency.
- **Deterministic tools first.** Prefer filesystem, CLI, COM, DOM, accessibility over screenshot computer-use.
- **Jarvis stays the orchestrator.** External frameworks are workers.
- **No drive-by refactors.** Do not replace FastAPI + React + SQLite because a plan document is richer than the code.
- **Windows paths in operator docs; keep tools working with `os.name` checks** where they already exist (llama-server filename, Python venv `Scripts` vs `bin`).
- **Secrets.** Never commit `.env`, `data/private_key.sec`, MCP env values, or GGUFs.
- **Master plan hygiene.** After a real change: update Current State, the queue item, and the decision log if you made a durable choice. Do not paste logs or chain-of-thought into that file.

---

## 14. Known gaps (do not assume they exist)

From the current master-plan state:

- Best-of-N is planning-only in Reliable mode (three candidates, one executed). It is not a full multi-attempt retry
- Parameterized skills execute bound steps after 3 matching successes (`POST /api/memory/skills/{id}/run`)
- Browser Use, UFO, Cua, OpenHands, Open Interpreter adapters are integrated and report `missing` until the optional packages are installed
- Whisper STT / local TTS are not wrapped around `/api/voice/command`
- Live Qwen e2e is a Windows-desktop concern; cloud/Linux sessions cannot sign it off
- Live GPU measurement of every harness configuration requires the Windows desktop GGUFs

---

## 15. Debugging

| Symptom | Where to look |
| --- | --- |
| API never becomes healthy | `logs/backend.err.log` |
| Model unloaded in the portal | `logs/llama-server.log`, port 8088 conflict, missing GGUF |
| Task stuck on “Waiting on model” | llama-server log, GPU usage, then unload/load and **Continue** from History |
| 401 from the portal | Settings / `localStorage` key `jarvis_private_key` |
| Playwright failures | `python -m playwright install chromium`; headless flag in settings |
| SQLite lock | stop Jarvis before copying `data/jarvis.db` |

More operator failure modes: [TROUBLESHOOTING.md](../TROUBLESHOOTING.md).
