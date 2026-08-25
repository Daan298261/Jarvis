# Install Jarvis

Jarvis is a **self-hosted local desktop agent**. The control plane is a FastAPI app plus a React portal. Inference is **Qwen3.5-27B** through llama.cpp on this machine, or any OpenAI-compatible server you point at.

The portal is [http://127.0.0.1:4780](http://127.0.0.1:4780). The same REST API drives the installable phone PWA at `/phone`, plus later voice or automations.

This is a **Windows** product. Startup scripts, Office COM, and desktop UI automation assume Windows. Linux is only useful for unit tests; see [DEVELOPMENT.md](DEVELOPMENT.md).

---

## 1. Hardware this install was tuned for

- Windows 11 Pro
- Intel Core i7-14700KF
- 64 GB RAM
- NVIDIA GeForce RTX 5070 Ti (16 GB VRAM, CUDA 13.0)
- llama.cpp **b10516**, Windows **CUDA 13.3** build

Q4_K_M (~16.7 GB) does not fully fit in 16 GB VRAM together with the vision projector and KV cache. Jarvis starts llama.cpp with `--fit on` so as many layers as possible go to the GPU and the rest stay in system RAM.

Smaller GPUs can still run the Fast profile (16K context) or a remote OpenAI-compatible backend. Do not substitute a tiny model just because it is easier to download.

---

## 2. Prerequisites

Install these before cloning, or confirm they are already on `PATH`:

| Tool | Version that works in this repo | Why |
| --- | --- | --- |
| Python | 3.11 or 3.12 (`python --version`) | FastAPI backend, pytest, Hugging Face download |
| Node.js | 20+ or 22 LTS (`node --version`) | React + Vite portal |
| npm | ships with Node | `frontend` install and production build |
| Git | any recent | clone / updates |
| NVIDIA driver | CUDA 13-capable | GPU offload for llama.cpp |
| PowerShell | 5.1+ (Windows 11 default) | `start-jarvis.ps1` / `stop-jarvis.ps1` |

Optional, depending on which tools you want the agent to use:

- **Playwright Chromium** — installed in the next section; required for the browser tool
- **Microsoft Office** — Word/Excel/PowerPoint COM (`office` tool). Without it, `.docx` can still be written as files
- **Docker Desktop** — `docker` tool
- **WSL** — extra `bash` shell; PowerShell is the default

Confirm:

```powershell
python --version
node --version
npm --version
nvidia-smi
```

---

## 3. Clone the repository

```powershell
git clone <repository-url> Jarvis
cd Jarvis
```

If you already have a checkout, `cd` into the repo root (the directory that contains `start-jarvis.ps1`).

Git does **not** contain models or llama.cpp binaries. Those directories are listed in `.gitignore`:

- `models/` — GGUF weights
- `runtime/llama.cpp/` — `llama-server.exe` and CUDA runtime DLLs
- `data/` — SQLite, settings, queue, browser profile
- `logs/` — backend and llama.cpp logs
- `frontend/node_modules/` and `frontend/dist/`

---

## 4. Python packages

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
python -m playwright install chromium
```

A venv is recommended so `pywin32` / Playwright stay isolated. `start-jarvis.ps1` uses whatever `python` is first on `PATH`, so activate the venv in that shell before starting Jarvis, or install into the user environment you actually launch with.

`backend/requirements.txt` includes FastAPI, uvicorn, SQLAlchemy + aiosqlite, the OpenAI client, Playwright, pywinauto/pywin32, MCP, Hugging Face Hub, and pytest.

---

## 5. Frontend

```powershell
cd frontend
npm install
npm run build
cd ..
```

FastAPI serves `frontend/dist`. `start-jarvis.ps1` rebuilds automatically if `frontend/dist/index.html` is missing. You still need `npm install` once.

For a hot-reload portal during development, see [DEVELOPMENT.md](DEVELOPMENT.md) — do not use that instead of `npm run build` for a normal desktop install.

---

## 6. llama.cpp (local inference)

Skip this section only if you will use a **remote** OpenAI-compatible server and never start llama.cpp on this PC.

1. Create the runtime folder:

   ```powershell
   New-Item -ItemType Directory -Force -Path runtime\llama.cpp | Out-Null
   ```

2. Download from [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases):

   - `llama-b10516-bin-win-cuda-13.3-x64.zip` (or a newer `llama-b*-bin-win-cuda-13.3-x64.zip`)
   - matching `cudart-llama-bin-win-cuda-13.3-x64.zip`

   RTX 50-series needs a recent CUDA 13 build. CPU-only or old winget builds will not use the 5070 Ti.

3. Extract the server zip **and** the cudart zip into `runtime/llama.cpp` so this file exists:

   ```
   runtime\llama.cpp\llama-server.exe
   ```

   CUDA 13 DLLs (`cudart64_13.dll` and friends) must sit **next to** `llama-server.exe`. If llama-server exits immediately, re-extract the cudart zip.

---

## 7. Model weights (GGUF)

Jarvis loads Unsloth quantizations of official `Qwen/Qwen3.5-27B`, plus the multimodal projector.

Required files under `models/Qwen3.5-27B-GGUF/`:

| File | Used by |
| --- | --- |
| `Qwen3.5-27B-Q4_K_M.gguf` | Fast and Balanced profiles (required to start) |
| `mmproj-F16.gguf` | Vision / screenshots (required to start) |
| `Qwen3.5-27B-Q5_K_M.gguf` | Quality profile (optional; falls back to Balanced if missing) |

Download (Hugging Face Hub is already in `backend/requirements.txt`):

```powershell
$env:HF_XET_HIGH_PERFORMANCE = "1"
python -m huggingface_hub.cli.hf download unsloth/Qwen3.5-27B-GGUF `
  --include "Qwen3.5-27B-Q4_K_M.gguf" `
  --include "Qwen3.5-27B-Q5_K_M.gguf" `
  --include "mmproj-F16.gguf" `
  --local-dir models\Qwen3.5-27B-GGUF
```

Equivalent with the `hf` CLI, if installed:

```powershell
hf download unsloth/Qwen3.5-27B-GGUF `
  --include "Qwen3.5-27B-Q4_K_M.gguf" `
  --include "Qwen3.5-27B-Q5_K_M.gguf" `
  --include "mmproj-F16.gguf" `
  --local-dir models\Qwen3.5-27B-GGUF
```

Weights stay on this computer. Do not commit them.

---

## 8. First start

```powershell
.\start-jarvis.ps1
```

The script:

1. Checks that `python`, `node`, `runtime\llama.cpp\llama-server.exe`, Q4_K_M, and `mmproj-F16.gguf` exist
2. Builds the portal if `frontend/dist` is missing
3. Creates `data/`, `logs/`, and `data/queue/{pending,processed,failed}/`
4. Starts uvicorn on `127.0.0.1:4780` (`app.main:app` with `--app-dir backend`)
5. Waits until `GET /api/health` returns 200 (up to ~6 minutes while the model loads)
6. Opens the portal in the default browser

Stop:

```powershell
.\stop-jarvis.ps1
```

That kills the recorded backend PID, leftover `llama-server.exe`, and uvicorn processes whose command line matches `app.main:app`.

### Start options

```powershell
# Do not open a browser
.\start-jarvis.ps1 -NoBrowser

# API only; do not auto-load the GGUF (sets JARVIS_SKIP_MODEL=1)
.\start-jarvis.ps1 -SkipModelLoad

# Run one prompt at startup and wait until that task finishes
.\start-jarvis.ps1 -Prompt "Inspect directory and generate project report" -Wait

# Same, from a JSON or text file
.\start-jarvis.ps1 -PromptFile .\tasks\sample_task.json -Wait

# Bind 0.0.0.0 and require a private key on API requests
.\start-jarvis.ps1 -LanAccess -PrivateKey "jarvis_pk_secret123"
```

`-ExecutionMode` defaults to `balanced` (agent loop policy: fast / balanced / reliable). That is separate from the **model** profile Fast / Balanced / Quality.

### Launch queue without restarting

Drop `.json`, `.prompt`, `.txt`, or `.task` files into `data/queue/pending/` (or the `data/queue/` root). Jarvis polls those directories and creates tasks automatically.

JSON shape:

```json
{
  "prompt": "Organize the Desktop Jarvis-Test folder",
  "autonomy": "autonomous",
  "profile": "balanced",
  "execution_mode": "balanced"
}
```

A plain `.prompt` / `.txt` file is treated as the prompt body with autonomy `autonomous`.

---

## 9. Configuration

On first boot Jarvis copies defaults from `config/default.json` into `data/settings.json` and fills `allowed_directories` (Desktop, Documents, Downloads, this repo, and `data/` when those paths exist).

| Setting | Default | Meaning |
| --- | --- | --- |
| `bind_host` / `bind_port` | `127.0.0.1` / `4780` | Portal + API |
| `lan_access` / `auth_required` | `false` | LAN bind and private-key gate |
| `inference.backend` | `llama.cpp` | `llama.cpp` (Jarvis starts the process) or `remote` |
| `inference.host` / `port` | `127.0.0.1` / `8088` | OpenAI-compatible `/v1` endpoint |
| `inference.profile` | `balanced` | Model Fast / Balanced / Quality |
| `inference.auto_load` | `true` | Load GGUF on API startup |
| `autonomy` | `trusted` | Confirmation policy |
| `execution_mode` | `balanced` | Agent loop depth / verification |
| `mcp_servers` | `[]` | User-configured MCP servers |

Environment variables (copy `.env.example` to `.env`; never commit secrets):

| Variable | Effect |
| --- | --- |
| `JARVIS_PRIVATE_KEY` | Private key (also `JARVIS_API_KEY` or `JARVIS_AUTH_TOKEN`) |
| `JARVIS_BIND_HOST` / `JARVIS_BIND_PORT` | Override bind address |
| `JARVIS_SKIP_MODEL` | Skip auto-load (`1`) |
| `JARVIS_LAUNCH_PROMPT` | Enqueue this prompt at startup |
| `JARVIS_LAUNCH_PROMPT_FILE` | Enqueue the contents of this file at startup |

The key is also stored in `data/private_key.sec` when generated from the API. `auth_token` is stripped before settings are written to disk.

Change model profile in the portal (**Model → Fast / Balanced / Quality**) or:

```powershell
Invoke-RestMethod -Method POST http://127.0.0.1:4780/api/model/load `
  -ContentType application/json -Body '{"profile":"quality"}'
```

| Profile | Quant | Thinking | Context |
| --- | --- | --- | --- |
| Fast | Q4_K_M | off | 16K |
| Balanced | Q4_K_M | on | 32K |
| Quality | Q5_K_M | on | 32K |

If the first load OOMs, Jarvis retries at 16K context. You can also set `"context_size": 8192` under `inference` in `data/settings.json`.

---

## 10. Remote inference (optional)

Jarvis always chats through an OpenAI-compatible `/v1` client. `llama.cpp` is the local backend Jarvis starts and supervises. Anything else (LAN GPU box, LM Studio, Ollama, vLLM, SGLang) is a `remote` backend that is only health-checked.

```powershell
Invoke-RestMethod -Method PUT http://127.0.0.1:4780/api/settings `
  -ContentType application/json `
  -Body '{"inference_backend":"remote","inference_host":"192.168.1.50","inference_port":8088}'
```

Set `inference_backend` back to `llama.cpp` to run locally again. No agent, tool, or portal code changes.

---

## 11. LAN / remote access

Default bind is localhost only. To expose the portal on the LAN:

```powershell
.\start-jarvis.ps1 -LanAccess -PrivateKey "jarvis_pk_your_custom_secret_key"
```

Every `/api` call and the WebSocket must then present the key as:

1. `X-Jarvis-Key: <key>`
2. `Authorization: Bearer <key>`
3. `?key=<key>` (bookmarks and WebSockets)

`/api/health`, `/api/auth/status`, `/api/auth/verify`, and `/api/mobile` stay reachable without a key. `/api/mobile` lists LAN URLs and install steps; it never returns the private key. Localhost can skip the key when `lan_access` is on but `auth_required` is still false. Treat Jarvis like a logged-in user on this PC — see [SECURITY.md](../SECURITY.md).

### Android / phone client

1. On the PC: Settings → enable **Allow LAN / Remote exposure** and keep a private key.
2. On the phone (same Wi-Fi): open `http://<pc-ipv4>:4780/phone` in Chrome or Samsung Internet.
3. Menu → **Add to Home screen**. The PWA starts on `/phone`.
4. Paste the private key once on the Phone page (or in Settings). Then use **Run on PC**.

Do not mail or message the private key. Copy it from the PC Settings page while you are at the machine.

---

## 12. MCP servers (optional)

Portal: **MCP**. Example stdio filesystem server:

```
name: filesystem
transport: stdio
command: npx
args: -y @modelcontextprotocol/server-filesystem C:\Users\<you>\Desktop
```

Or `POST /api/mcp`. Do not put secrets in git; pass them as environment variables to the MCP process.

HTTP servers use `"transport": "http"` and `"url": "http://127.0.0.1:3000"`.

---

## 13. Confirm the install

With Jarvis running:

```powershell
Invoke-RestMethod http://127.0.0.1:4780/api/health
Invoke-RestMethod http://127.0.0.1:4780/api/model
```

Health should be `{ "ok": true }`. Model should show `loaded: true` after auto-load finishes (watch `logs/llama-server.log` if it stays unloaded).

Open [http://127.0.0.1:4780](http://127.0.0.1:4780). **Command** is the main prompt box. **Guide & Workflows** has operating instructions plus six editable templates (debug a project, research to spreadsheet, organize files, browser extract, collect pages, multi-step maintenance). Fill parameters and run; that creates one normal task.

Full live suite (Windows desktop + loaded model, several minutes):

```powershell
python tests\run_e2e.py
```

A shorter smoke prompt:

```powershell
python tests\smoke_task.py
```

---

## 14. Update

```powershell
.\stop-jarvis.ps1
git pull
python -m pip install -r backend\requirements.txt
cd frontend
npm install
npm run build
cd ..
.\start-jarvis.ps1
```

To update llama.cpp, download a newer `llama-b*-bin-win-cuda-13.3-x64.zip` plus matching `cudart` zip into `runtime/` and extract over `runtime/llama.cpp`.

If a GGUF is corrupt, delete that file under `models/Qwen3.5-27B-GGUF/` and download it again.

---

## 15. Optional auto-start after login

Not enabled by default.

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-WindowStyle Hidden -File `"$PWD\start-jarvis.ps1`" -NoBrowser"
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "Jarvis Local Agent" -Action $action -Trigger $trigger
```

Remove with `Unregister-ScheduledTask -TaskName "Jarvis Local Agent"`.

---

## Logs and data

| Path | Contents |
| --- | --- |
| `logs/backend.log` | uvicorn stdout |
| `logs/backend.err.log` | uvicorn stderr |
| `logs/llama-server.log` | llama.cpp |
| `logs/jarvis.log` | application logger |
| `data/jarvis.db` | tasks, events, tool calls, trajectories, skills |
| `data/settings.json` | non-secret preferences |
| `data/private_key.sec` | generated private key |
| `data/queue/` | launch queue |
| `data/workflows/` | saved Guide & Workflows presets |
| `data/browser-profile/` | Playwright profile |

Stop Jarvis before copying `data/jarvis.db`. If the portal opens but the model stays unloaded, read [TROUBLESHOOTING.md](../TROUBLESHOOTING.md).
