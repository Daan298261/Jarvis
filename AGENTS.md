# AGENTS.md

Instructions for **Cursor cloud workers** and other automated agents working in this repo.

## Before you write code

1. Read **[`docs/PROCESS.md`](docs/PROCESS.md)** — the one-ticket development loop (mandatory).
2. Read your **named ticket**:
   - an RFC under [`docs/rfcs/`](docs/rfcs/), **or**
   - **one** item in [`JARVIS_MASTER_PLAN.md`](JARVIS_MASTER_PLAN.md) §58 Development Queue.
3. Skim [`JARVIS_MASTER_PLAN.md`](JARVIS_MASTER_PLAN.md) for architecture context only. **Do not** re-audit the tree or rewrite §57 Current State unless your ticket requires updating specific bullets for work you just merged.

### Launch prompt must name exactly one ticket

Good:

> Implement `docs/rfcs/0003-example.md`. Branch from `cursor/local-qwen-desktop-agent`. PR against that branch.

Bad (forbidden):

> Continue Jarvis development / pick up priority tasks / merge all PRs / audit and update the master plan

## Implement

| Step | Action |
| --- | --- |
| Base branch | `cursor/local-qwen-desktop-agent` (not `main`) |
| New branch | `cursor/<short-slug>-99ea` |
| Scope | One RFC or one queue item only |
| Tests | `python3 -m pytest` |
| Frontend | `npm --prefix frontend run build` (and `lint` if TS changed) |
| Docs | Update **only** matching lines in master plan §57–58 (and §59 if a durable decision) |
| PR target | `cursor/local-qwen-desktop-agent` |

### Model selection (Cursor cloud)

- **Default:** Composer 2.5 **standard** (not Fast) — cost control.
- **Grok 4.6:** only when the ticket explicitly calls for a hard problem; use sparingly.

### What cloud VMs cannot sign off

Linux cloud agents have **no GPU** and **no Windows desktop tools**. You **cannot** verify:

- Live Qwen 9B / 27B GGUF load and tool-calling
- `tests/run_e2e.py` or `tests/smoke_task.py`
- Live harness tok/s / VRAM measurements
- Office / pywinauto automation

Implement and unit-test; leave P0 live-model items as `TODO` / desktop sign-off in the PR.

### Do not

- Merge unrelated PRs (see superseded list in `docs/PROCESS.md`; **PR #25 is closed — do not merge**)
- Rewrite `JARVIS_MASTER_PLAN.md` wholesale or paste large design specs into it
- Start swarm / Browser Use / P4–P5 / model-stack work unless that is the named ticket

Design work belongs in **`docs/rfcs/`** ([template](docs/rfcs/TEMPLATE.md)).

---

## Cursor Cloud environment

### GitHub repository mapping

The canonical public repository is [`Daan298261/Jarvis`](https://github.com/Daan298261/Jarvis) on GitHub. Cursor Cloud agents use the `origin` remote (`origin.cursor.com/git/taco-1/Jarvis`), which mirrors that GitHub repo; pushes to `origin` sync to GitHub. PR numbers and the GitHub UI refer to `Daan298261/Jarvis`, not `taco-1/Jarvis`.

Jarvis is a Windows-tuned local desktop agent (FastAPI backend + React/Vite portal) whose model is a 27B GGUF served by llama.cpp on an NVIDIA GPU. The Cloud VM is headless Linux with no GPU, so the model and the Windows-only tools do not run here, but the backend, portal, tool system, and test suite all run fine for development.

### Environment (already handled by the startup update script)
- Python deps install into the user site with `python3 -m pip install --break-system-packages` (the base image has no `python3-venv`/`ensurepip`, so there is no virtualenv). Console scripts land in `~/.local/bin`, which may not be on `PATH` — invoke tools as `python3 -m pytest`, `python3 -m uvicorn`, etc.
- The Windows-only requirements (`pywin32`, `pywinauto`, `comtypes`) are filtered out on Linux; they will not install. Their imports are lazy, so the backend imports cleanly. The `desktop` and `office` tools return "unavailable" here; `filesystem`, `terminal`, `python`, `browser`, `web_fetch`, `git`, `screenshot`, `mcp` work.
- Frontend deps come from `npm --prefix frontend ci` (lockfile-driven).

### Run / test / lint / build (standard commands live in `README.md` and `frontend/package.json`)
- Backend (dev): `JARVIS_SKIP_MODEL=1 PYTHONPATH=backend python3 -m uvicorn app.main:app --host 127.0.0.1 --port 4780 --app-dir backend`. `JARVIS_SKIP_MODEL=1` skips the llama.cpp auto-load (which cannot succeed here); without it the API still starts but logs a model-load failure.
- Frontend (dev): `npm --prefix frontend run dev` → Vite on `http://localhost:5173`. Vite binds to `localhost` (IPv6 `::1`); use `localhost`, not `127.0.0.1`. Its `/api` proxy targets the backend on `:4780`.
- Single-URL portal: after `npm --prefix frontend run build`, the backend serves the built SPA at `http://127.0.0.1:4780`. The build step is intentionally NOT in the startup script.
- Tests: `python3 -m pytest` (see `pytest.ini`; `pythonpath=backend`). These use an in-process scripted model provider, so no real model is needed.
- Frontend lint: `npm --prefix frontend run lint` (oxlint; it emits warnings but exits 0).

### Running the full agent loop without the 27B model
The model is pluggable: the agent only speaks OpenAI-compatible HTTP (`inference.host`/`inference.port`, default `127.0.0.1:8088`). You can drive the whole plan → act → verify loop against any OpenAI-compatible `/v1` endpoint (a real small model server or a deterministic stub). Caveat: `InferenceManager.load()` first checks that the selected profile's GGUF (`models/Qwen3.5-27B-GGUF/Qwen3.5-27B-Q4_K_M.gguf`) and `runtime/llama.cpp/llama-server.exe` exist on disk before it will attach to an already-running server, so create placeholder files at those paths when pointing at an external/stub endpoint. `tests/run_e2e.py` and `tests/smoke_task.py` require a real model and will not pass without one.
