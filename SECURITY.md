# Security

Jarvis is a powerful local agent. Treat it like a logged-in user on this PC.

## Network & Remote Exposure

- Default bind: `127.0.0.1:4780` (web) and `127.0.0.1:8088` (llama-server)
- LAN / Remote exposure: When enabled, binds to `0.0.0.0`
- **Private Key Authentication**: When enabled (`auth_required: true` or `lan_access: true`), every request to `/api` and WebSocket connections must present the valid private key.

### Supplying the Private Key

Clients can authenticate with any of the following:
1. `X-Jarvis-Key: <private_key>` header
2. `Authorization: Bearer <private_key>` header
3. `?key=<private_key>` query parameter (e.g. for WebSockets or URL bookmarks)

Set the private key in your environment or generate one in Settings:

```powershell
setx JARVIS_PRIVATE_KEY "jarvis_pk_your_custom_secret_key"
```

Or pass it at startup:

```powershell
.\start-jarvis.ps1 -LanAccess -PrivateKey "jarvis_pk_secret"
```

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

## Future swarm boundary

The current private-key/LAN mechanism protects the existing single-control-plane API; it is **not** a complete trust or pairing protocol for a future multi-node swarm. P3 remote-node work must define authenticated pairing and least-privilege node/worker access before remote execution is enabled. See `SWARM_ARCHITECTURE.md`.

Security/SIEM/Sentinel/forensics mentioned in the swarm specification are future specialized roles only. Do not implement those subsystems from this note; they will be separately specified and promoted later.

