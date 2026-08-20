# Security

Jarvis is a powerful local agent. Treat it like a logged-in user on this PC.

## Network

- Default bind: `127.0.0.1:4780` (web) and `127.0.0.1:8088` (llama-server)
- Not exposed to the internet
- LAN access is off by default
- Enabling LAN access in Settings sets bind host to `0.0.0.0` and **requires** `JARVIS_AUTH_TOKEN`

Set the token in the user environment, not in git:

```powershell
setx JARVIS_AUTH_TOKEN "a-long-random-value"
```

Clients must send `Authorization: Bearer <token>` or `X-Jarvis-Token: <token>`.

## Secrets

- Never commit `.env`, `secrets.json`, or MCP env values
- `data/settings.json` stores non-secret preferences
- Auth token is read from the environment and stripped before settings are saved

## Filesystem policy

Tools resolve paths against `allowed_directories` (Desktop, Documents, Downloads, this repo, and `data/` by default). Mass-delete / format / diskpart patterns are blocked even in Autonomous mode.

## Browser

Playwright uses a persistent local profile under `data/browser-profile`. Cookies stay on this machine.

## Model

Weights never leave the computer. The OpenAI-compatible endpoint is localhost only.

## Autonomy pauses

Autonomous mode still stops before:

- disk formatting / partition destruction
- deleting backups or mass deletion outside the working scope
- changing account credentials
- disabling core security controls
- sending money, purchases, or unsolicited external communications
