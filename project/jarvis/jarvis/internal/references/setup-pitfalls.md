# Setup pitfalls and operational gotchas

Concise answers for the most common Jarvis install and runtime questions. See `docs/INSTALL.md` and `TROUBLESHOOTING.md` for full detail.

## Port-forward / off-LAN access

- Default API bind is **`127.0.0.1:4780`** (portal) and **`127.0.0.1:8088`** (llama-server). Nothing is exposed to the internet by default.
- **LAN access** — enable in Settings or `.\start-jarvis.ps1 -LanAccess`. Binds `0.0.0.0`; requires the **private key** on `/api` requests (`X-Jarvis-Key`, `Authorization: Bearer`, or `?key=`).
- **Do not** use installer or wizard shortcuts to port-forward WAN exposure. Off-LAN phone use follows **Link-device** / Android client flows (`ANDROID_CLIENT.md`, `/api/mobile` for LAN URLs only — never returns the key).
- Copy the private key only at the PC; never email, chat, or screenshot it by default.

## LAN bind / listen address

| Setting | Default | Notes |
| --- | --- | --- |
| `bind_host` / `bind_port` | `127.0.0.1` / `4780` | Portal + REST API |
| `lan_access` | `false` | When true, listens on all interfaces |
| `auth_required` | follows LAN | Private key required on API when LAN is on |

Override via `data/settings.json`, Settings UI, or env `JARVIS_BIND_HOST` / `JARVIS_BIND_PORT`.

## Model download / LM Studio paths

- **Bundled llama.cpp** — `runtime/llama.cpp/llama-server.exe` plus CUDA DLLs; not in git.
- **Default GGUFs** — `models/Qwen3.5-9B-abliterated-GGUF/` (primary), `models/Qwen3.5-27B-GGUF/` (Expert). If a **Qwen3.8-9B uncensored** GGUF is already present under `models/` or `~/.lmstudio/models`, that becomes the everyday autoload default (RFC-0078). Download via install docs or Hugging Face Hub scripts in `docs/INSTALL.md`.
- **LM Studio** — backend `lmstudio` discovers GGUFs under the user LM Studio models folder (RFC-0043 graded catalog). Jarvis does not download models for LM Studio; it binds profiles to on-disk files.
- **Remote inference** — set `inference.backend` to `remote`, `ollama`, `lmstudio`, `vllm`, or `sglang` and configure host/port; Jarvis probes but does not start remote servers.

## GPU / VRAM and graded profiles

- Target desktop: **~16 GB VRAM** (e.g. RTX 5070 Ti). 9B Q8_0 is intended to stay GPU-resident; 27B Q4_K_M uses `--fit on` and may offload.
- **Profiles** — Fast (Q4, thinking off, 16K), Balanced (Q4, thinking on, 32K), Quality (Q5, thinking on, 32K). OOM → retry lower context or Fast profile (`TROUBLESHOOTING.md`).
- **Vision** — mmproj / vision loads extra VRAM; off unless needed.
- LM Studio catalog hides profiles with **>16 GB** declared footprint by default (RFC-0018 / RFC-0043).

## Start / Stop service lifecycle

```powershell
.\start-jarvis.ps1          # verify deps, build frontend if needed, start API, load model, open portal
.\stop-jarvis.ps1           # kill backend PID, llama-server, matching uvicorn
.\start-jarvis.ps1 -SkipModelLoad   # API only (JARVIS_SKIP_MODEL=1)
```

`stop-jarvis.ps1` must not leave orphaned `llama-server.exe`. Tray **Stop** / **Quit** (when present) follow `WINDOWS_SHELL.md`. Queue files in `data/queue/pending/` are processed without restart.

## Private key / secrets handling

- Generate or set via Settings, `JARVIS_PRIVATE_KEY`, or `.\start-jarvis.ps1 -PrivateKey` (dev only — do not commit).
- Stored locally in `data/private_key.sec` when generated; **`auth_token` is stripped** before `data/settings.json` is written.
- **Never echo secrets** in chat, logs shown to users, or grounding snippets — redact `api_key`, `token`, `password`, `private_key`, and bearer values.
- MCP env secrets and `.env` must not be committed.

## Quick error triage

| Symptom | First checks |
| --- | --- |
| Model unloaded | `logs/llama-server.log`, port 8088 conflict, missing GGUF, run `POST /api/model/load` |
| Port 4780 in use | Change `bind_port` or stop other process |
| Browser tool fails | `python -m playwright install chromium` |
| Task stuck on model | Cancel task, reload model, continue from History |
