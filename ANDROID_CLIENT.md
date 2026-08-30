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

Default Leader port is whatever the Leader actually uses (`settings.bind_port`, default **4780**). Forward only that port.

`GET /api/mobile` remains public enough to show LAN URLs and install hints. It must never leak the private key.

## 1.1 Link device (start of pairing)

When the user starts **linking a mobile device** (portal or `/phone`):

1. **Ask for login / pairing then** — paste or confirm the existing private key on the phone. Do not skip pairing because the device is on LAN.
2. **Explain off-LAN:** reaching Jarvis from cellular may require exposing the Leader API to the internet (one forwarded port, still private-key gated).
3. **User chooses how WAN is set up:**
   - they configure port-forward / overlay themselves, or
   - Jarvis does it if they **supply router admin passwords** and run the AI-guided brand-agnostic walkthrough in §3.
4. **Explain reuse:** router access granted here can later be used by **Blue** (and **Purple** on owned net) in [`SECURITY_AGENTS.md`](SECURITY_AGENTS.md) to read router logs and apply user-confirmed isolation on the user’s own LAN. Same secret store, same attended policy. Not a second login product. **Red** does not receive these credentials unless the law-enforcement gate is on **and** the action is in authorized case scope.
5. **Credentials:** local secret storage on the Windows Leader only (never git, never logs, never chat, never the Jarvis room).

LAN-only linking is valid: skip WAN/router steps if the user stays on the home Wi-Fi.

## 2. Reachability: LAN first, then WAN

On the home LAN the phone already opens `http://<leader-lan-ip>:<port>/phone` when LAN access is enabled.

For **cellular**, the phone must reach the Leader through the home router. Setup is an **attended, AI-guided agent task on the Leader**, not a hardcoded vendor SDK.

This feature is for **everyone who runs Jarvis**, not an ISP or country special case. Whatever gateway is on the LAN (Taco’s happens to be a Zyxel from Odido) is discovered at setup time. Do **not** ship a hardcoded brand/ISP adapter matrix.

## 3. AI-guided, brand-agnostic router setup

Jarvis on the Leader PC discovers the gateway and **walks the user through** login and port-forward in the portal (and phone UI once the Leader is reachable).

### 3.1 Discover the gateway

Without assuming brand:

- default route / LAN gateway IP
- UPnP / IGD service advertisement on the LAN
- HTTP/HTTPS admin on the gateway (common ports, captured page title, HTML vendor strings, TLS cert CN)
- hostname / MAC OUI as hints only, never as a required match table

Explain what it found in the UI before asking for credentials.

### 3.2 Try UPnP/IGD first (no password)

If IGD can add a mapping for the Jarvis Leader port → Leader LAN IP, do that. No admin password. Verify the mapping exists. Then verify the phone (or an external probe the user confirms) can reach the Leader **with private-key auth**.

### 3.3 If UPnP fails: attended admin-UI task

Open the gateway admin UI with the **existing** browser / computer-use tools. Proceed as a normal attended Jarvis task:

1. Show the user the admin page Jarvis opened.
2. **Ask for admin user/password at setup time** when the page requires login.
3. Drive the UI: find NAT / virtual server / port-forward / gaming / applications.
4. Create **one** mapping: external TCP port → Leader LAN IP → Leader Jarvis port. Do not forward llama-server (8088), SSH, or the router admin port.
5. Save, re-read the mapping list, verify the row.
6. Confirm the phone can reach the Leader with the private key.

If the UI is unknown, Jarvis **still tries**: read the page, identify the port-forward section, ask the user when stuck. Do not brute-force passwords. Do not disable the firewall. Do not change Wi-Fi, DHCP, or DNS except as required to add that single mapping (and only with user confirmation).

### 3.4 Skills after success

After a verified success, Jarvis may promote a **parameterized skill** (gateway admin URL, which labels were clicked, where the mapping was). The next run on the same gateway is faster. That is learned procedure, **not** a hardcoded vendor SDK shipped in git.

### 3.5 Credentials

Requested from the user at setup time in the Leader portal (not in the Jarvis room, not in chat, not in git).

Store only in **local secret storage on the Windows Leader** (Windows Credential Manager or DPAPI-protected, gitignored). Never log the password. Never put it in task transcripts, trajectory memory examples, or `GET /api/mobile`. Redact it from tool traces.

### 3.6 Hostname vs WAN IP

If the household already has DDNS / a stable hostname, use that in the phone client.

Else show the current WAN IPv4 and **warn it can change**. Optional later: remind the user when the WAN IP changes; do not require a Jarvis-operated DDNS vendor in v1.

### 3.7 CGNAT is a hard blocker

If the WAN address is CGNAT (shared IPv4, typical 100.64/10, or IGD/admin reports no public mapping), **stop**. Do not punch through CGNAT.

Fallback: an overlay such as **Tailscale** (or equivalent) from phone to Leader. Spec that as **WAN fallback**, not P3 swarm, not a second machine in the node registry.

## 4. Security

- Default bind remains localhost until the user enables LAN or WAN reachability.
- WAN exposure of the Jarvis port still requires the **existing private-key gate**. No open unauthenticated WAN.
- Prefer enabling the forwarding mapping **only after** a key exists and the user has paired the phone (key stored on the phone, not returned by `/api/mobile`).
- TLS is preferred in front of the forwarded port when practical (existing cert on the Leader, or a reverse proxy the user already has). If TLS is not yet available, the private-key gate is mandatory; HTTP on WAN is a documented risk, not a reason to skip the key.
- Do not expose llama-server to WAN.
- This private-key/LAN/WAN mechanism is **not** P3 swarm node pairing.

## 5. Client shape

Keep one frontend:

- `/phone` remains the Android-oriented UI (command, live status, cancel/continue, Speak, recent tasks, key paste).
- Install: “Add to Home screen” / TWA / thin WebView wrapping that origin.
- On LAN: Leader LAN URL. On cellular: forwarded hostname or WAN IP, same path, same key.

Leader stays the Windows desktop. The phone does not run the model, tools, or swarm workers.

## 6. Out of scope

- P3 multi-node swarm (discovery, secure pairing, remote workers, cross-node placement)
- A second Android app with its own API
- Hardcoded ISP/brand router adapters
- Disabling the firewall or forwarding extra ports
- Storing router passwords in git, logs, or chat
- Claiming a second machine is a swarm Node because the phone can call the API

## 7. Acceptance (when implemented)

- [ ] Link-device flow asks for pairing, explains WAN exposure, offers self-setup vs Jarvis-with-router-password, and notes later Blue/Purple reuse of router access (Red only under the LE gate)
- [ ] Same `/phone` client (PWA/TWA/WebView) talks to the Leader API with the existing private key
- [ ] `GET /api/mobile` still does not include the private key
- [ ] UPnP/IGD attempted first; no password if it succeeds
- [ ] Failed UPnP → attended gateway-admin task; user is asked for admin credentials; mapping verified
- [ ] Unknown admin UI: Jarvis reads the page and asks when stuck; no vendor SDK required
- [ ] Only the Jarvis Leader port is forwarded
- [ ] Router password only in local secret storage; never git/logs/chat
- [ ] CGNAT detected → stop and offer overlay fallback (not swarm)
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
| §49 TLS | LAN/WAN HTTP today | This Android spec prefers TLS on the forwarded port; there is no separate “TLS everywhere” queue line. |
| §50 Live e2e | Queued under P0 | Windows `tests/run_e2e.py` remains unsigned-off (not missing from the queue). |

P4/P5 remain specified in `ADAPTIVE_DOMAIN_ARCHITECTURE.md` (Founder OS patterns from https://github.com/thecloudtips/founder-os translated into native Jarvis concepts; **not** a runtime dependency). Nothing in P4/P5 is implemented.

Jarvis 2.0 Away Mode is specified in `JARVIS_2.0.md` (approved sections 64–85). It is not current-session P0 unless the queue promotes an item.
