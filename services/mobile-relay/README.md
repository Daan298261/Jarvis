# Jarvis mobile relay

This optional service carries opaque TCP/TLS traffic when a phone cannot directly
reach its Jarvis gateway. TLS terminates at the owner's gateway, not at this relay.
It has no access to conversation/audio/file plaintext. The HTTPS control service
handles swarm registration and opaque push identifiers.

Deploy with Docker Compose on a public Linux host. Set `RELAY_HOSTNAME`, a random
`RELAY_REGISTRATION_CODE`, and `FIREBASE_CREDENTIAL_FILE` in the operator's environment.
The Firebase service account stays only on the service host. Allow TCP 80/443 and
15000–15099. The relay is not a TURN server; configure coturn separately for WebRTC.

1. `docker compose up -d --build`
2. An authorized Jarvis installation posts its operator-provided registration code
   to `https://HOST/v1/register`. Store the returned credential only on that Jarvis
   installation; the returned endpoint is the relay fallback for that swarm.
3. Include the relay hostname in the gateway's TLS certificate SANs. The phone uses
   the same pinned gateway public key on direct and relayed connections.
4. On Jarvis set `JARVIS_RELAY_URL=https://HOST`, `JARVIS_RELAY_CREDENTIAL=...`,
   `JARVIS_PUSH_URL=https://HOST/v1/push`, and the same installation credential as
   `JARVIS_PUSH_CREDENTIAL`. Jarvis starts the outbound relay agent on startup.
5. For APK push support, set `JARVIS_FIREBASE_CLIENT_CONFIG` to a file containing
   Firebase's public Android client fields: `app_id`, `api_key`, `project_id`,
   `sender_id`. Never supply a Firebase admin credential here.

Limits: 100 registered swarms by default, 8 simultaneous TCP connections per swarm,
512 MiB per connection direction, 1-hour connection lifetime, 30 pushes/minute.
The operator registration code must not be embedded in publicly downloadable APKs.
This preview requires operator-provisioned installation credentials; public
self-service registration, automatic commercial hosting provisioning and HA are
not implemented. No deployment is claimed without a live end-to-end check.
