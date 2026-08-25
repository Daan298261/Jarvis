# AGENTS.md

Read [`JARVIS_MASTER_PLAN.md`](JARVIS_MASTER_PLAN.md) before making substantial changes. It is the persistent architecture, current state, and development queue.

## Cursor Cloud specific instructions

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
