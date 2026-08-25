# Security

Jarvis is a powerful local agent. Treat it like a logged-in user on this PC.

## Network

- Default bind: `127.0.0.1:4780` (web API and portal) and `127.0.0.1:8088` (llama-server)
- Not exposed to the internet
- LAN access is **off** by default
- `start-jarvis.ps1` binds `127.0.0.1` unless Settings has LAN on **and** `JARVIS_AUTH_TOKEN` is set in the process environment
- Enabling LAN without a usable token (16+ characters) is rejected; bind stays localhost
- llama-server on this PC always binds loopback even when the portal is on the LAN
- Pointing Jarvis at another OpenAI-compatible host is an outbound client connection (`inference.host` / `base_url`); it does not expose llama-server

Set the token in the **user** environment, not in git or `data/settings.json`:

```powershell
setx JARVIS_AUTH_TOKEN "a-long-random-value"
```

Use at least 16 characters. Close and reopen the terminal (or sign out) so `start-jarvis.ps1` sees the variable. Then turn on **Allow LAN access** in Settings and restart Jarvis.

LAN clients must send `Authorization: Bearer <token>` or `X-Jarvis-Token: <token>`. Localhost requests from this machine do not need a token. HTTP query-string tokens are ignored so they do not leak in logs; WebSocket may use `?token=` so a browser can connect. The portal can store the token in `sessionStorage` for a remote browser; it is never written to settings.

If Windows Firewall prompts when LAN bind is enabled, allow **Private** network only. Do not expose port 4780 to the internet.

Optional: `JARVIS_BIND_HOST` selects a specific address when LAN+token are already in effect (ignored otherwise).

## Secrets

- Never commit `.env`, `secrets.json`, or MCP env values
- MCP presets store `${VAR}` / `env_from` names only; GitHub tokens stay in the user environment
- `data/settings.json` stores non-secret preferences; raw MCP env values are stripped on save
- Auth token is read only from `JARVIS_AUTH_TOKEN` and is stripped before settings are saved
- Inference API keys are read only from `JARVIS_INFERENCE_API_KEY` (optional `OPENAI_API_KEY`) and are stripped before settings are saved

## Filesystem policy

Tools resolve paths against `allowed_directories` (Desktop, Documents, Downloads, this repo, and `data/` by default). Mass-delete / format / diskpart patterns are blocked even in Autonomous mode.

## Browser

Playwright uses a persistent local profile under `data/browser-profile`. Cookies stay on this machine.

## Model

Weights stay on this computer by default. The local llama.cpp process binds localhost only. If you point Jarvis at another OpenAI-compatible host, prompts are sent to that host. Set `JARVIS_INFERENCE_API_KEY` in the environment if that host requires a key; it is never written to `settings.json`.

## Autonomy pauses

Autonomous mode still stops before:

- disk formatting / partition destruction
- deleting backups or mass deletion outside the working scope
- changing account credentials
- disabling core security controls
- sending money, purchases, or unsolicited external communications
