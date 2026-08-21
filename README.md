# Jarvis

Self-hosted local desktop agent. The model is **Qwen3.5-27B** running entirely on this computer through llama.cpp. The web portal at [http://127.0.0.1:4780](http://127.0.0.1:4780) is the control surface; the same REST API can later drive voice, Android, or automations.

Cursor and future development sessions must read [`JARVIS_MASTER_PLAN.md`](JARVIS_MASTER_PLAN.md) before making substantial changes. That file is the persistent architecture, current state, and development queue.

## Hardware this install was tuned for

- Windows 11 Pro
- Intel Core i7-14700KF
- 64 GB RAM
- NVIDIA GeForce RTX 5070 Ti (16 GB VRAM, CUDA 13.0)
- llama.cpp b10516, Windows CUDA 13.3 build

Q4_K_M (~16.7 GB) does not fully fit in 16 GB VRAM together with the vision projector and KV cache, so Jarvis uses llama.cpp `--fit on` to offload as many layers as possible to the GPU and keep the rest in system RAM.

## Install

From the repository root (already done on this machine):

```powershell
python -m pip install -r backend\requirements.txt
python -m playwright install chromium
cd frontend
npm install
npm run build
cd ..
```

llama.cpp CUDA binaries live in `runtime/llama.cpp`. Models live in `models/Qwen3.5-27B-GGUF`.

If the GGUF files are missing:

```powershell
$env:HF_XET_HIGH_PERFORMANCE = "1"
python -m huggingface_hub.cli.hf download unsloth/Qwen3.5-27B-GGUF --include "Qwen3.5-27B-Q4_K_M.gguf" --include "Qwen3.5-27B-Q5_K_M.gguf" --include "mmproj-F16.gguf" --local-dir models\Qwen3.5-27B-GGUF
```

The GGUFs are Unsloth quantizations of the official `Qwen/Qwen3.5-27B` weights, including the multimodal projector.

## Start

```powershell
.\start-jarvis.ps1
```

This verifies dependencies, builds the frontend if needed, starts the API, loads the model, and opens [http://127.0.0.1:4780](http://127.0.0.1:4780).

Skip opening a browser:

```powershell
.\start-jarvis.ps1 -NoBrowser
```

## Stop

```powershell
.\stop-jarvis.ps1
```

## Update

```powershell
git pull
python -m pip install -r backend\requirements.txt
cd frontend
npm install
npm run build
cd ..
```

To update llama.cpp, download a newer `llama-b*-bin-win-cuda-13.3-x64.zip` plus matching `cudart` zip from [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) into `runtime/` and extract over `runtime/llama.cpp`.

## Change model profile

In the portal: **Model → Fast / Balanced / Quality**.

Or via API:

```powershell
Invoke-RestMethod -Method POST http://127.0.0.1:4780/api/model/load -ContentType application/json -Body '{"profile":"quality"}'
```

- **Fast**: Q4_K_M, thinking off, 16K context
- **Balanced**: Q4_K_M, thinking on, 32K context
- **Quality**: Q5_K_M, thinking on, more CPU offload

## Move inference to another machine

Jarvis talks to an `InferenceBackend`. `llama.cpp` is the local one Jarvis starts and supervises; anything else OpenAI-compatible (a LAN GPU box, LM Studio, Ollama, vLLM, SGLang) is a `remote` backend Jarvis only health-checks.

```powershell
Invoke-RestMethod -Method PUT http://127.0.0.1:4780/api/settings -ContentType application/json -Body '{"inference_backend":"remote","inference_host":"192.168.1.50","inference_port":8088}'
```

No agent, tool, or portal code changes are needed. Set the backend back to `llama.cpp` to run locally again.

## Add an MCP server

Portal: **MCP**. Example stdio filesystem server:

```
name: filesystem
transport: stdio
command: npx
args: -y @modelcontextprotocol/server-filesystem C:\Users\daanv\Desktop
```

Or POST `/api/mcp`. Do not put secrets in source; use environment variables referenced by the MCP process.

## Inspect logs

- `logs/backend.log` — FastAPI
- `logs/backend.err.log` — uvicorn stderr
- `logs/llama-server.log` — llama.cpp
- `logs/jarvis.log` — application logger
- `data/jarvis.db` — tasks, events, tool calls

## Recover from a broken model/backend

1. `.\stop-jarvis.ps1`
2. Confirm no leftover `llama-server.exe` in Task Manager
3. Read `logs/llama-server.log`
4. If VRAM OOM, Jarvis already retries with 16K context; you can also set `"context_size": 8192` under `inference` in `data/settings.json`
5. If the GGUF is corrupt, delete `models/Qwen3.5-27B-GGUF/Qwen3.5-27B-Q4_K_M.gguf` and download again
6. `.\start-jarvis.ps1`

## Optional auto-start after login

Not enabled by default. To register a login task:

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -File `"$PWD\start-jarvis.ps1`" -NoBrowser"
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "Jarvis Local Agent" -Action $action -Trigger $trigger
```

Remove it with `Unregister-ScheduledTask -TaskName "Jarvis Local Agent"`.

## Tests

With Jarvis running:

```powershell
python tests\run_e2e.py
```
