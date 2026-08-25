# Jarvis

Self-hosted local desktop agent. The default model is **Qwen3.5-9B Abliterated Q6_K** running entirely on this computer through llama.cpp. The original Qwen3.5-27B profiles remain available as fallbacks. The web portal at [http://127.0.0.1:4780](http://127.0.0.1:4780) is the control surface; the same REST API can later drive voice, Android, or automations.

## Hardware this install was tuned for

- Windows 11 Pro
- Intel Core i7-14700KF
- 64 GB RAM
- NVIDIA GeForce RTX 5070 Ti (16 GB VRAM, CUDA 13.0)
- llama.cpp b10516, Windows CUDA 13.3 build

The 9B Q6_K weights plus vision projector fit comfortably in 16 GB VRAM, reducing model latency and keeping agent/tool loops responsive. Jarvis still uses llama.cpp `--fit on` as an OOM guard.

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

llama.cpp CUDA binaries live in `runtime/llama.cpp`. The default model lives in `models/Qwen3.5-9B-Abliterated-GGUF`; 27B fallbacks remain in their sibling model folders.

The long-term development backlog and master plan live in [`project_goals.md`](project_goals.md). The ordered pickup queue is [`Goals/pickup_order.md`](Goals/pickup_order.md).

If the GGUF files are missing:

```powershell
$env:HF_XET_HIGH_PERFORMANCE = "1"
hf download Abiray/Qwen3.5-9B-abliterated-GGUF Qwen3.5-9B-abliterated-Q6_K.gguf mmproj-f16.gguf --local-dir models\Qwen3.5-9B-Abliterated-GGUF
```

The installed GGUF is a Q6_K quantization of `lukey03/Qwen3.5-9B-abliterated`, with its matching multimodal projector.

## Start

Double-click **Jarvis** on the Desktop, or from the repository root:

```powershell
.\start-jarvis.ps1
```

This verifies dependencies, builds the frontend if needed, starts the API on **127.0.0.1:4780**, loads the model, and opens [http://127.0.0.1:4780](http://127.0.0.1:4780). If Jarvis is already running, it just opens the portal. LAN bind is off unless you set `JARVIS_AUTH_TOKEN` and enable LAN in Settings (see [SECURITY.md](SECURITY.md)).

Skip opening a browser:

```powershell
.\start-jarvis.ps1 -NoBrowser
```

The Desktop `Jarvis.exe` is a thin launcher for `start-jarvis.ps1`. Starting from the repo rebuilds it when the git revision (or start script) changes:

```powershell
.\install-desktop-launcher.ps1
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
.\install-desktop-launcher.ps1
```

To update llama.cpp, download a newer `llama-b*-bin-win-cuda-13.3-x64.zip` plus matching `cudart` zip from [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) into `runtime/` and extract over `runtime/llama.cpp`.

## Change model profile

In the portal: **Model → Abliterated 9B Fast / Abliterated 9B Balanced**. The 27B profiles remain below them.

Or via API:

```powershell
Invoke-RestMethod -Method POST http://127.0.0.1:4780/api/model/load -ContentType application/json -Body '{"profile":"abliterated-balanced"}'
```

- **Abliterated 9B Fast**: Q6_K, thinking off, 16K context
- **Abliterated 9B Balanced**: Q6_K, thinking on, 32K context
- **Official 27B Fast / Balanced / Quality**: retained as slower fallback profiles

Detected hardware (OS, CPU, RAM, GPU, VRAM, CUDA/driver) is on the **System** page and in the sidebar. `GET /api/system` returns `hardware` plus a labeled `hardware_view`.

## Autonomy

Portal: **Settings** or the Autonomy control on **Command**. Default is Trusted.

- **Interactive** — ask before consequential (MEDIUM+) operations. Inspect tools still run.
- **Trusted** — run normal work automatically; ask for HIGH-impact and irreversible actions.
- **Autonomous** — long-running work without repeated prompts. Still pauses for disk format, partition wipe, destroying backups, mass deletion outside the task, credential changes, money/purchases, disabling security, or unsolicited external send.

This is not the Fast/Balanced/Reliable execution mode and not the Fast/Balanced/Quality model profile.

## Backups

Settings → **Backup now** copies `data/settings.json` and `data/jarvis.db` into `data/backups/` (capped at 12). Jarvis also snapshots on startup and before settings saves when the files changed. Restore settings or the database from that list. Agent file edits keep `.bak-*` sidecars (when backups are enabled); `git` checkpoint/restore reverts repository files without switching your current branch.

## LAN access

The portal and API listen on `127.0.0.1` by default. To reach Jarvis from another machine on your network:

1. Set `JARVIS_AUTH_TOKEN` in the user environment (`setx`), not in git or settings.json.
2. Restart the terminal, enable **Allow LAN access** in Settings, then restart Jarvis.
3. On the other machine, open `http://<this-pc>:4780` and paste the same token into Settings (session only), or send `X-Jarvis-Token`.

llama-server on this PC still binds `127.0.0.1:8088`. To use another OpenAI-compatible host (LAN GPU box, vLLM, etc.), open **Model** and Connect, or set `inference.host` / `inference.base_url` / `JARVIS_INFERENCE_BASE_URL`. Details: [SECURITY.md](SECURITY.md).

## Phone / Android

Same task API as the desktop portal. After LAN access is on, Settings lists phone URLs. On the phone open `http://<this-pc>:4780/phone`, paste `JARVIS_AUTH_TOKEN`, or Add to Home screen. Python helper: `clients/phone/jarvis_client.py`. Android Studio project: `clients/android` (WebView + `JarvisApi.kt`). Discovery: `GET /api/phone`.

## Voice

Portal: **Voice**, or **Mic** / **Speak** on Command. Speech-to-text is local Whisper (`faster-whisper`, CPU `tiny.en` by default). Text-to-speech is Windows SAPI, or Piper if you put `piper.exe` in `runtime/piper` and a voice `.onnx` in `models/piper`. The first transcription downloads Whisper into `models/whisper`. Keep `JARVIS_WHISPER_DEVICE=cpu` so Qwen keeps the GPU.

## Add an MCP server

Portal: **MCP**. WhatsApp and email are configured for this install, and the preset catalog also includes filesystem, memory, git, fetch, time, and GitHub.

- WhatsApp: pair once with `npx wappmcp@0.4.0 configure`. Session keys stay in `~/.wappmcp`.
- Email: add an account with `npx @codefuturist/email-mcp@0.2.3 account add`. Use an app password; the account config stays outside this repo.

Or POST `/api/mcp` / `/api/mcp/presets/{id}`. Do not put secrets in source or settings; use environment variables (`env_from` or `${VAR}` references). GitHub needs `GITHUB_PERSONAL_ACCESS_TOKEN` in the user environment.

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
5. If the GGUF is corrupt, delete `models/Qwen3.5-9B-Abliterated-GGUF/Qwen3.5-9B-abliterated-Q6_K.gguf` and download again
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
