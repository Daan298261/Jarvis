# RFC-0123: Companion reachability and anti-impersonation

**Status:** implemented  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Taco via Chief of Staff / Jarvis Architect  
**Date:** 2026-09-18

**Related (do not rewrite; cite, do not fork ports):** [RFC-0059](0059-android-companion-delivery.md) companion identity / TLS gateway (implemented). [RFC-0063](0063-companion-six-digit-pairing-codes.md) 6-digit codes (implemented). [RFC-0065](0065-companion-pc-endpoint-bringup.md) PC endpoint (implemented). [RFC-0074](0074-companion-pairing-streamline-and-qr.md) pairing + QR. [`ANDROID_CLIENT.md`](../../ANDROID_CLIENT.md) Link-device / WAN walkthrough (PWA `/phone` historically on Leader `:4780`). [`docs/android-companion.md`](../android-companion.md) native companion runbook. [`backend/app/mobile/connectivity.py`](../../backend/app/mobile/connectivity.py) `PORT = 4781`. [`backend/app/mobile/gateway.py`](../../backend/app/mobile/gateway.py) TLS ingress. [`backend/app/mobile/relay.py`](../../backend/app/mobile/relay.py) + `services/mobile-relay/`. [RFC-0108](0108-phone-companion-offline-ai-model.md) offline GGUF pack (sibling; pairing-complete popup uses this session).

This PR is **specs-only**. Product behavior for the next implement ticket. **Hard constraint:** no exploit recipes, PoCs, payloads, or attack steps in this RFC or in implement tests. Defensive product behavior only. Do **not** invent LE / Red / Purple / ATO gates. Do **not** take RFC-0122.

## Problem

Owners ask two things that the native companion still does not answer as product:

1. **How does the phone reach Jarvis?** LAN vs router port-forward vs hosted mobile-relay are implemented as pieces (`Prepare connection`, one-hour UPnP on **TCP 4781**, `JARVIS_RELAY_*`) but are not owner-facing as *when each applies*. `ANDROID_CLIENT.md` still describes forwarding the Leader HTTP port (**4780** `/phone`). The native app talks to the **mobile TLS gateway**, not the owner portal.
2. **Who may connect?** The gateway already allowlists `/api/companion/*` and pairing uses Keystore + owner fingerprint + session Bearer, but the Leader does **not** listen continuously (owner must start the gateway), and there is no product response to **impersonation / MITM suspicion** (detect, tell the owner, kill the session, refuse the port for a cooldown).

A decorative “secure connection” chip with no listen, no pairing-key gate, or no response to a suspected impersonation is a **fail**. A second auth stack or a new port number that fights `:4781` is also a fail.

## Decision

Document and then implement **one** companion reachability story and **one** anti-impersonation loop on the **existing** TLS gateway. Reuse RFC-0074 / RFC-0059 pairing. Do not wait on a separate blue-team bot.

### 1. Ports (cite repo; do not invent)

| Surface | Bind / default | Who talks to it | Forward to WAN? |
| --- | --- | --- | --- |
| Owner portal / full API | `127.0.0.1:4780` (`settings.bind_port`) | Desktop browser, local tools | **No.** Owner APIs stay off companion ingress (`gateway.py` 404s non-`/api/companion/*`). |
| **Companion TLS gateway** | `0.0.0.0:4781` (`experimental_port` / `connectivity.PORT`) | Paired Android companion only | **Only** this TCP port, and only in the port-forward mode below. |
| llama-server | `127.0.0.1:8088` | Leader inference | **No.** |
| Mobile relay control | Operator-hosted HTTPS (`JARVIS_RELAY_URL`) | Leader **outbound** WebSocket | No inbound map on the home router. Phone uses `JARVIS_RELAY_ENDPOINT` with the **same** gateway TLS pin. |

Certificate / pin: `data/mobile/tls/` (`server.key` / `server.crt`, gitignored); `server_pin` is SHA-256 of the gateway SPKI (printed at start; baked into pairing QR / APK). Phone **pins** that value (RFC-0059). Windows private-profile firewall: inbound **TCP 4781** for LAN tests ([`ANDROID_MVP_LAN_CHECKLIST.md`](../ANDROID_MVP_LAN_CHECKLIST.md)).

### 2. When LAN-only vs port-forward vs mobile-relay apply

Owner-facing (Phone pairing / Network copy). One mode is active as the **path the phone uses**; the gateway still listens locally in all of them.

**LAN-only (default, home Wi-Fi).** Phone and PC on the same private IPv4 network. Phone dials `https://<leader-lan-ip>:4781`. No router mapping. No relay. Skip WAN steps (already valid in `ANDROID_CLIENT.md` §1.1). This is the MVP path.

**Port-forward (owner wants cellular / off-LAN without a relay host).** One mapping: **external TCP 4781 → Leader LAN IP → 4781**. Reuse existing UPnP one-hour lease (`map_router` in `connectivity.py`) and the attended router walkthrough in `ANDROID_CLIENT.md` §3 **aimed at 4781, not 4780**. Do not map 4780, 8088, SSH, or the router admin port. CGNAT / no public IPv4: **do not** punch; fall through to relay or overlay. Foreign mappings on 4781 stay preserved (existing rule).

**Mobile-relay (no public IPv4, CGNAT, or owner declines router login).** Operator deploys `services/mobile-relay/` and sets `JARVIS_RELAY_URL` / `JARVIS_RELAY_CREDENTIAL` / `JARVIS_RELAY_ENDPOINT` ([`docs/android-companion.md`](../android-companion.md), `docs/examples/mobile-companion.env.example`). Leader opens an **outbound** tunnel; TLS still terminates on the **owner gateway**; relay does not see companion plaintext. Phone uses the relay HTTPS origin with the **same** `server_pin`. Relay is not a second pairing ceremony and not P3 swarm.

Installer / wizard still **must not** silently WAN-expose anything (`INSTALLER.md`). Overlay (Tailscale-class) remains the `ANDROID_CLIENT.md` CGNAT fallback; it is not a new companion port.

### 3. Leader listens continuously on the companion port

While the Jarvis **Leader process is up**, the companion TLS gateway **listens on TCP 4781** without waiting for **Prepare connection**.

- Prepare connection / remote-checkbox remains the owner path to enable **port-forward lease** and **relay** — not the path to start LAN listen.
- Listen is TLS-only (`gateway.py` + `server_identity`). Upstream stays `http://127.0.0.1:4780`. Allowlist stays `/api/companion/*`.
- Leader down → nothing listens (expected). Leader up → `:4781` is up.
- Existing `probe()` rule stays: unauthenticated `GET /api/companion/models` on the gateway must be **401**, not a 200 owner payload.

### 4. Accept connections only with correct pairing keys

Reuse existing material — do not mint a parallel PKI:

| Stage | What must be correct |
| --- | --- |
| Transport | TLS to the pinned `server_pin`; hostname/IP must be a cert SAN. |
| Enroll | RFC-0063/0074 6-digit code (or unexpired legacy invitation) + phone P-256 Keystore public key; owner **fingerprint confirm** before `active`. |
| Session | `Authorization: Bearer` session + `X-Jarvis-Device` matching that device (`identity.require_device`). Revoked / pending / expired → refuse. |
| Routes | Only `/api/companion/*` on `:4781`. Enroll/session/challenge stay rate-limited as today. |

No pairing keys → no companion API (401/404). Offline GGUF on the phone (RFC-0108) does **not** bypass this when the Leader is reachable. Pack file bytes (`/model-packs/{id}/file`) are **device-authenticated** the same way.

### 5. Continuous impersonation / MITM monitoring (defensive)

The Leader **continuously** evaluates companion connections against the pairing record. This RFC specifies **product signals and responses**, not how an attacker would impersonate.

**Signals** (implement maps each to a probability in `[0, 1]`; names are owner-facing, not tradecraft):

| Signal | Typical probability | Notes |
| --- | --- | --- |
| TLS pin / presented certificate does not match the stored `server_pin` for this Leader | ≥ 0.9 | Phone or a probe reports pin mismatch; or the gateway sees a TLS identity that is not its own file. |
| Session token or device id does not match an `active` paired device | ≥ 0.8 | Including revoked devices and replayed sessions after expiry. |
| Enroll presented without a valid unexpired pairing code after the existing rate limit trips | 0.5–0.7 | Rate limit already exists; this is the **escalation** above 429. |
| Certificate/pin rotation the owner did not just perform | ≥ 0.9 | Unexpected identity change during a live paired session. |
| Isolated 401 / wrong code from a pairing UI | ≤ 0.2 | Do **not** close the port for ordinary mistypes. |

Do **not** treat RFC-0108 pack downloads, voice WSS, or heartbeats as impersonation.

### 6. On suspicion: detect, kill, 10-minute refuse

When probability **≥ 0.5** (configurable later; default this threshold):

1. Emit a first-class event **`detected-hack-attempt`** with `probability` (0–1), device id if known, endpoint class (LAN / forwarded / relay), and a **short owner sentence** (e.g. “Someone tried to reach Jarvis as your phone without pairing keys.”). Show it on the desktop Phone pairing / HUD surface; optional speak once (RFC-0067 mute/DND respected). Audit-log locally. **No** exploit text.
2. **Kill** that connection (and the device session if one was bound to the attempt).
3. **Close / refuse TCP 4781 for 10 minutes** (600 seconds): stop accepting new companion connections; in-flight calls drop. After the cooldown, listen again on 4781 with the same pairing rules. A new trip **restarts** the 10 minutes.
4. Ordinary owner chat on **localhost :4780** stays up. Do not shut down inference to “be safe.”
5. Paired phones show honest unreachable during the cooldown (RFC-0108 offline model may answer locally; it must not claim the PC is healthy).

Owner cannot silently skip the cooldown from the phone. Desktop may show remaining minutes. Do not add a password / LE / Purple gate to reopen.

**Will not:** new port numbers; forward 4780 for the native companion; auto WAN from the installer; a second pairing PKI; Blue/Purple/Red workers as a dependency; documenting attacks.

## Acceptance criteria

- [ ] Specs-only in this PR (no product code)
- [ ] Owner copy states when **LAN-only** vs **port-forward (TCP 4781 only)** vs **mobile-relay** apply; cites `:4781` / `:4780` as in this table
- [ ] Leader **listens continuously** on the companion TLS port while the Leader process is up
- [ ] Connections accepted **only** with existing pairing keys (RFC-0059/0063/0074); unauthenticated companion API remains 401
- [ ] Continuous monitoring for impersonation / MITM using the signal table (no attack recipes)
- [ ] On suspicion: **`detected-hack-attempt`** + **`probability`**, kill the connection, refuse `:4781` for **10 minutes**
- [ ] RFC-0108 pack download/popup uses this same session; no extra open port
- [ ] No new LE / Red / Purple / ATO gates; no exploit/PoC/payload text
- [ ] Implement follow-up: `python3 -m pytest` for listen-on-start, 401 without pairing, cooldown refuse, event payload; physical phone + WAN is **desktop sign-off**

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | `backend/app/mobile/gateway.py`, `connectivity.py`, `identity.py`, `relay.py`; startup so `:4781` listens with Leader; suspicion → event + 600s refuse |
| Frontend (implement PR only) | Phone pairing / Network: mode copy + `detected-hack-attempt` + cooldown remaining |
| Android (implement PR only) | Pin mismatch reporting into the same event path; RFC-0108 popup still after **successful** pair only |
| Tests | `tests/test_mobile_connectivity.py`, `tests/test_companion_pairing.py`, new `tests/test_rfc0123_*.py` (401, cooldown, event shape — no attack scripts) |
| Docs | this RFC; RFC-0108 cross-link; `JARVIS_MASTER_PLAN.md` §59 |

## Out of scope

Product implementation in this PR. RFC-0108 GGUF runtime (sibling). RFC-0122. HexStrike / SECURITY_AGENTS workers. Rewriting `ANDROID_CLIENT.md` WAN UI beyond a one-line port pointer. Public relay hosting. Overlay VPN as a required product. Fine-tune of phone weights.

## Notes

- Source: Taco via CoS 2026-09-18. HOLD lifted for this slice only. Number **0123** (do not take 0122).
- Linux cloud cannot sign off physical-phone WAN or live MITM fixtures. Unit-test listen/auth/cooldown/event; desktop + phone is sign-off.
- Implement launch: this RFC only; branch from `development`; PR against `development`; do not merge other PRs; do not edit Architect spec docs in the implement PR.

## Implementation note

Landed on `development` via #319 @ `a6977b74` (companion reachability / anti-impersonation, with the RFC-0108 amend). Physical phone + WAN remains desktop sign-off. Acceptance checkboxes left open for that sign-off and the original specs-only box.
