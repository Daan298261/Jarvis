# Jarvis Android Client — Leader Reachability Specification

Status: **separate specification** referenced by `JARVIS_MASTER_PLAN.md`. **Not implemented** (the existing Phone PWA is LAN-only). Architect-owned.

This is **not** P3 swarm discovery, pairing, or multi-node networking. The **Leader** stays the Windows desktop that already runs Jarvis. The phone is a remote control surface for that Leader.

## 0. Product

Taco wants an Android app whose frontend sends API calls to the Jarvis Leader (the existing local Jarvis on the Windows PC).

There is already a Phone PWA:

- `frontend/src/pages/Phone.tsx`
- `backend/app/api/mobile.py`
- `/phone` with `frontend/public/manifest.webmanifest`
- pairing info via `GET /api/mobile` (must **never** include the private key)

Prefer **evolving that client** into a proper Android client rather than a second competing app:

1. Installable PWA / Trusted Web Activity (TWA), or
2. A thin native WebView/wrapper around the same `/phone` UI and the same REST/WebSocket API.

Do not build a separate Android product with a different task model, auth stack, or backend.

## 1. Talk to the Leader

The phone talks to the **Leader** over the existing API:

- start a task
- live status
- cancel / continue
- Speak (local STT/TTS on the Leader when available)
- recent-task follow

Auth is the **existing private key / pairing** (`X-Jarvis-Key`, `Authorization: Bearer`, or `?key=`). Do not invent a new auth stack.

Default Leader port is whatever the Leader actually uses (`settings.bind_port`, default **4780**); it is never exposed off-LAN. Native companion TLS gateway is **TCP 4781** (LAN, or off-network over Tailscale only: [`docs/rfcs/0215-remote-companion-pairing.md`](docs/rfcs/0215-remote-companion-pairing.md); anti-impersonation: [`docs/rfcs/0123-companion-reachability-and-anti-impersonation.md`](docs/rfcs/0123-companion-reachability-and-anti-impersonation.md)) — do not forward `:4780` owner APIs for the companion.

`GET /api/mobile` remains public enough to show LAN URLs and install hints. It must never leak the private key.

## 1.1 Link device (start of pairing)

When the user starts **linking a mobile device** (portal or `/phone`):

1. **Ask for login / pairing then.** Pair with the six-digit code and confirm the fingerprint. Do not skip pairing because the device is on LAN.
2. **Explain off-LAN:** away from home, the phone reaches the Leader **only over Tailscale** ([RFC-0215](docs/rfcs/0215-remote-companion-pairing.md)). Jarvis never opens router ports, never asks for router admin passwords and never puts the Leader on the public internet.
3. **Remote access is off by default.** The owner turns on "Allow pairing and use from outside my home network" in the pairing panel, then generates a new code.
4. **Credentials:** pairing secrets stay in local storage on the Windows Leader only (never git, never logs, never chat, never the Jarvis room).

LAN-only linking is valid: skip the Tailscale steps if the user stays on the home Wi-Fi.

## 2. Reachability: LAN, then Tailscale

On the home LAN the phone reaches the companion TLS gateway on `https://<leader-lan-ip>:4781`.

Off the home network, the only path is Tailscale. This applies to everyone who runs Jarvis, with no ISP, router-brand or country special cases, and CGNAT does not matter.

## 3. Tailscale setup (owner-run)

1. Install Tailscale on the Leader PC and on the phone, and sign in to the same tailnet. Jarvis never installs Tailscale itself.
2. Jarvis detects it with `tailscale status --json` and advertises the MagicDNS name and tailnet (100.64/10) addresses next to the LAN endpoints in the pairing QR. Public addresses are never advertised.
3. If Tailscale is missing or logged out, the pairing panel shows setup steps instead of an address.
4. The gateway accepts tailnet clients only while remote access is on, and refuses public-internet clients always.

## 4. Security

- Default bind remains localhost until the user enables LAN access or Tailscale remote access.
- Nothing is exposed to the public internet: no router mapping, no public tunnel, no hosted relay.
- Tailscale traffic still goes through the pinned companion TLS gateway and device auth.
- Do not expose llama-server or portal 4780 off-LAN.
- This LAN/Tailscale mechanism is **not** P3 swarm node pairing.

## 5. Client shape

Keep one frontend:

- `/phone` remains the Android-oriented UI (command, live status, cancel/continue, Speak, recent tasks, key paste).
- Install: “Add to Home screen” / TWA / thin WebView wrapping that origin.
- On LAN: Leader LAN URL. Off-LAN: the Tailscale MagicDNS name or 100.x address, same pin, same pairing.

Leader stays the Windows desktop. The phone does not run the model, tools, or swarm workers.

## 6. Out of scope

- P3 multi-node swarm (discovery, secure pairing, remote workers, cross-node placement)
- A second Android app with its own API
- Router port-forwarding, UPnP, public tunnels or hosted relays of any kind
- Disabling the firewall
- Asking for or storing router passwords
- Claiming a second machine is a swarm Node because the phone can call the API

## 7. Acceptance (when implemented)

- [ ] Link-device flow asks for pairing and explains that off-LAN use is Tailscale only
- [ ] `GET /api/mobile` still does not include the private key
- [ ] Remote access is off by default and only the owner's explicit toggle turns it on
- [ ] Pairing QR lists Tailscale then LAN endpoints only; no public address is ever advertised
- [ ] Gateway refuses tailnet clients while remote is off and public clients always
- [ ] No router port is opened and no router credentials are requested
- [ ] Not treated as P3 swarm work

---

## Appendix — Spec gaps from the restored 63-section master plan

Items in `JARVIS_MASTER_PLAN.md` §§1–63 that have **no Development Queue line** and are **not** covered by `SWARM_ARCHITECTURE.md`, `ADAPTIVE_DOMAIN_ARCHITECTURE.md`, or this Android spec. Do not invent product areas beyond that plan.

Covered elsewhere (not gaps): core/portal/tools, verification/recovery/modes, skills/trajectory/best-of-N, Office, optional workers, voice, Phone PWA, LAN inference, swarm P2, P4/P5 headings, this Android client, home IoT, security agents (Blue / Purple / Red-gated), Jarvis 2.0 (`JARVIS_2.0.md`), lazy mmproj (PR #50), Windows consumer installer (`INSTALLER.md`).

| Plan section | Gap | Notes |
| --- | --- | --- |
| §22 Agent-S / Agent-S3 | No queue item | Borrow ideas only; full framework not required. Trajectory / best-of-N / recovery already landed separately. Remaining: hierarchical planning / GUI grounding *from Agent-S* if still useful. |
| §28 Model roles | No queue item | 9B default + 27B Expert exists. Separate Router/Planner/Executor/Critic/Verifier/Vision/coding-specialist models are still “eventually”. |
| §35 MCP | No original queue item | **Code present** (stdio/HTTP client; Jarvis MCP server). Missing a queue tick, not missing a spec. |
| §45 Permissions / Autonomy | No queue item for Interactive / Trusted / Autonomous *profiles* | Fast/Balanced/Reliable execution modes exist; safety pauses exist. Named Interactive/Trusted/Autonomous profiles are only partial vs §45. |
| §46 Git / recoverability | No original queue item | **Code present** (`jarvis-checkpoint-*`). Missing a queue tick. |
| §47 Backups | No original queue item | Filesystem `.bak` / compare-recent exists. Broader “destructive ops create recoverable state” is only partial. |
| §48 Startup | Autostart after Windows login | `start-jarvis.ps1` exists. Optional autostart is unspecified as a queue item; do not enable without making it obvious. |
| §49 TLS | Portal HTTP on LAN today | The companion uses the pinned TLS gateway on 4781 (LAN or Tailscale); there is no separate “TLS everywhere” queue line. |
| §50 Live e2e | Queued under P0 | Windows `tests/run_e2e.py` remains unsigned-off (not missing from the queue). |

P4/P5 remain specified in `ADAPTIVE_DOMAIN_ARCHITECTURE.md` (Founder OS patterns from https://github.com/thecloudtips/founder-os translated into native Jarvis concepts; **not** a runtime dependency). Nothing in P4/P5 is implemented.

Jarvis 2.0 Away Mode is specified in `JARVIS_2.0.md` (approved sections 64–85). It is not current-session P0 unless the queue promotes an item.
