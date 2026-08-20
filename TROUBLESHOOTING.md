# Troubleshooting

## Portal opens but model shows unloaded

The API started and auto-load failed. Open `logs/llama-server.log`.

Common causes:

- Another `llama-server` still bound to port 8088 — run `.\stop-jarvis.ps1`
- GGUF path missing — files must be in `models/Qwen3.5-27B-GGUF/`
- VRAM pressure from other apps — close Chrome/games, retry **Model → Balanced**

Then `POST /api/model/load`.

## llama-server exits immediately

CUDA 13 DLLs must sit next to `llama-server.exe` in `runtime/llama.cpp` (`cudart64_13.dll` and friends). Re-extract `cudart-llama-bin-win-cuda-13.3-x64.zip`.

RTX 50-series needs a recent llama.cpp (this install uses **b10516**). Older CPU-only winget builds will not use the 5070 Ti.

## Gibberish or missing tool calls

- Context too small: raise `inference.context_size` toward 32768 if RAM allows
- Thinking/parser: server is started with `--jinja --reasoning-format deepseek`
- For Fast profile, thinking is off on purpose

## Browser tool fails

```powershell
python -m playwright install chromium
```

The first launch of Chromium may be slow. Headless can be enabled in Settings.

## Office tools fail

Microsoft Office is not installed on this machine, so Word/Excel/PowerPoint COM automation reports that. Install Office to enable those tools; `.docx` can still be written as XML/text via the filesystem tool when needed.

## Docker tools fail

Docker Desktop is not installed. The docker tool returns a clear error and the agent should use a different strategy.

## WSL/bash unavailable

WSL is present but no distro is installed. PowerShell remains the primary shell.

## Task stuck on "Waiting on model"

Check `logs/llama-server.log` and GPU usage in Task Manager. Cancel the task, unload/load the model, continue the task from History.

## SQLite locked / history missing

Stop Jarvis before copying `data/jarvis.db`. After restart, History should list previous tasks; **Continue this** reloads compacted state.

## Port 4780 in use

Change `bind_port` in `data/settings.json` or stop the other process. Update `start-jarvis.ps1` usage accordingly.
