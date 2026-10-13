# RFC-0215: Remote (off-LAN) companion pairing over Tailscale

**Status:** implemented (code; on-phone off-LAN sign-off pending)
**Author:** Grok Bot, owner request (Taco)
**Date:** 2026-10-13
**North star:** extend-not-replace. Builds on RFC-0123 (pinned TLS gateway on 4781) and RFC-0213 (pairing).

## Problem

The owner usually works over RDP on VRPC while his phone is on mobile data or another Wi‑Fi. The pairing QR only carried LAN endpoints, so pairing and daily use failed off the home network.

## Decision

1. **Tailscale is the only remote path.** ANZU does not open router ports (no UPnP, NAT-PMP, PCP or manual port forward), does not discover or advertise a public IP (no echo services, no STUN), and runs no tunnel (no cloudflared, no relay, no reverse SSH). That code was removed, not just disabled. This is law-enforcement case data, so the gateway is never put on the public internet.
2. **Remote access is off by default.** A one-time migration (`rfc0215_migrated`) switches `remote` off on existing installs unless the owner set it explicitly (`remote_explicit`). One control (`CompanionRemoteAccess` in the pairing panel, "Allow pairing and use from outside my home network") sets `network.config.remote`. Preparing or building never changes it; disabling the connection forces it off.
3. **Detection.** `remote_access.tailscale_status()` runs `tailscale status --json` and returns the MagicDNS name and 100.64/10 / fd7a:115c:a1e0::/48 addresses. If Tailscale is missing or logged out, the panel shows setup steps. ANZU never installs it. The owner can untick "Use Tailscale addresses" without turning remote off.
4. **QR / pairing payload.** Contains only Tailscale (MagicDNS first, then 100.x) and LAN endpoints, in that order (`remote_access.ordered_entries`). Every other address is dropped. Endpoint kinds are not sent. The phone does not need them because every origin uses the same SPKI pin.
5. **Gateway gate** (`gateway.client_allowed`). LAN clients are always allowed. Tailscale clients are allowed only while remote is on. Public-internet clients are never allowed. Loopback is refused unless it carries the per-boot `x-anzu-self-test` secret, which the desktop sends only to 127.0.0.1/::1/localhost. HTTP and WebSocket both return 403. If reading the setting fails, that is logged and treated as off.
6. **Code lifecycle.** Toggling remote in either direction cancels unclaimed codes (logged). With remote on, a code lives at most 10 minutes. If the setting can't be read, the 10-minute cap applies (fail closed, logged). 10 failed codes from any address within 15 minutes burn the active code and lock pairing for 15 minutes (HTTP 423). The existing per-IP and gateway rate limits stay.
7. **Server proof.** `/challenge/{id}?nonce=` returns `server_key` plus an ECDSA signature over `anzu-server-v1\n<nonce>` from the pinned gateway key. The phone always sends a nonce and refuses the session when the proof is missing, invalid, or `sha256(server_key) != pin`.
8. **Phone trust.** The phone dials only the hosts the pinned desktop listed (QR, then the authenticated `/api/companion/connection`). That list is authoritative, so unlisted origins are pruned and an empty list keeps the known set. The phone remembers the last working origin. When every endpoint fails and the path is Tailscale, it explains whether the Tailscale app is missing or switched off.
9. **Self-test.** After every setup the desktop probes each advertised endpoint's `/api/companion/health` (unauthenticated, `{ok:true}`). Results (ok/failed) and an exposure summary are logged (warning level when remote is on) and shown in the panel. A Tailscale probe from the PC proves the gateway listens on the tailnet, not that the phone's Tailscale is up.

Not in this RFC: any public-internet exposure, hosted relay, DDNS, or installing Tailscale.

## Enabling

1. Install Tailscale on the PC and on the phone and sign in with the same account.
2. In ANZU → pairing panel, turn on "Allow pairing and use from outside my home network".
3. Generate a new code and scan it.

## Acceptance criteria

- [x] Remote off by default, plus the migration (`tests/test_rfc0215_remote_pairing.py`)
- [x] Gateway 403 for loopback without the secret, Tailscale while off, and public clients (unit and TestClient tests)
- [x] Tailscale parsing and missing-binary guidance. QR order is Tailscale then LAN; public addresses and hostnames are dropped
- [x] Codes invalidated on toggle; 10-minute cap; lockout; fail-closed logging
- [x] Server proof returned. The phone rejects a missing proof (`RemoteEndpointsTest`) and prunes unlisted endpoints (`TransportPolicyTest`)
- [ ] Real phone paired off-LAN over Tailscale (VRPC has no Tailscale installed yet)
