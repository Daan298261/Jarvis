# RFC-0038: Proactive VoIP/WebRTC call channel

**Status:** accepted  
**Queue item:** P1/P2 — remote owner supervision / realtime voice  
**Author:** ChatGPT architecture synthesis  
**Date:** 2026-09-06

## Problem

Jarvis should be able to proactively call the owner when a task is blocked, an urgent event occurs, or policy explicitly permits a voice escalation. Existing `ANDROID_CLIENT.md` defines a remote-control client and RFC-0025 defines channel-neutral messaging/notifications, while RFC-0033/0035/0036 cover realtime voice, tiny command handling and latency. None currently defines a reliable incoming-call transport from Jarvis to the Android app.

Using Android's deprecated `android.net.sip` stack is not appropriate. Modern Android calling apps should integrate through Core-Telecom/Telecom, while realtime app-to-app media should use WebRTC. SIP remains useful as an optional server-side interop/PSTN gateway, not as the Android client foundation.

## Decision

Add a `RealtimeCallGateway` as a specialized realtime channel beneath RFC-0025.

Primary Jarvis-app call path:

`Goal/Event -> CallPolicy -> CallGateway -> push wakeup -> Android Core-Telecom incoming call -> WebRTC signaling -> DTLS-SRTP/Opus audio -> Jarvis realtime voice pipeline`

### Transport

Use **WebRTC audio** as the native Jarvis-app media protocol. Signaling is Jarvis-owned and provider-neutral. ICE/STUN/TURN support is mandatory for off-LAN reliability. Prefer direct peer connectivity when possible; use TURN relay when NAT/firewall conditions require it.

Do not place raw SDP, audio, transcripts, prompts or private task details in push notifications. A wakeup contains only an opaque short-lived `call_id`/nonce and minimal display-safe metadata. The app authenticates and fetches the call offer/context through the normal paired-device trust path.

A `CallSession` record contains at least: call ID, initiating GoalRun/event, caller AgentProfile, target device/user, reason/urgency, created/expiry timestamps, state, signaling credentials, media policy, and audit linkage.

Call states include `REQUESTED`, `PUSHED`, `RINGING`, `ANSWERED`, `CONNECTING_MEDIA`, `ACTIVE`, `DECLINED`, `MISSED`, `FAILED`, `ENDED`, `EXPIRED`.

### Reachability

Support three deployment modes behind one interface:

1. **LAN/overlay direct** — app reaches Leader over LAN/Tailscale-equivalent; WebRTC direct where possible.
2. **Public rendezvous/TURN** — a minimal relay service carries signaling rendezvous and/or TURN for CGNAT/restricted networks. It does not host Jarvis models or durable memory.
3. **Optional SIP/PBX gateway** — Asterisk/FreeSWITCH or equivalent may bridge Jarvis calls to SIP trunks/PSTN or third-party SIP endpoints. SIP is an adapter behind `RealtimeCallGateway`, not the core mobile protocol.

The initial implementation should prefer WebRTC app-to-app. Add SIP/PSTN only after the app call path is reliable.

### Wakeup and Android lifecycle

For ordinary Android devices, high-priority push is the default incoming-call wake mechanism. A permanently open background socket must not be required for reliable ringing. The app then registers the call with Android Core-Telecom and posts the required incoming-call notification/full-screen surface where permitted.

Push delivery is a wake signal, not authoritative call state. The app must fetch current state after waking, so delayed or duplicate pushes cannot resurrect expired calls.

### Conversation/media bridge

After answer, microphone audio is streamed into the same Jarvis realtime ingress used by local voice. Jarvis ASR/tiny-command/main-model/TTS remain Leader-owned by default. TTS audio is streamed back over the active WebRTC session as soon as stable chunks are available per RFC-0036.

Barge-in is first-class: owner speech while Jarvis is speaking ducks/stops TTS and reaches the priority voice-command path. Calls share existing conversation/task identity rather than creating a separate agent memory.

### Proactive call policy

Calling is consequential and potentially disruptive. RFC-0014 proactivity remains authoritative. Per-user/device policy must define which events may trigger:

- notification only;
- notification then call if unacknowledged;
- immediate call;
- repeated/escalating call attempts;
- never call during configured quiet hours except permitted emergency classes.

The model may request a call, but deterministic policy decides whether one may be placed. A model cannot label its own event as emergency to bypass policy.

## Acceptance criteria

- [ ] Add provider-neutral `RealtimeCallGateway` and persistent `CallSession` contracts.
- [ ] Primary Android media path is WebRTC audio with Opus and encrypted DTLS-SRTP transport.
- [ ] ICE/STUN/TURN are supported and call setup reports whether media is direct or relayed.
- [ ] Incoming push contains only opaque short-lived identifiers/minimal safe metadata; private call context is fetched after authenticated wake.
- [ ] Duplicate/delayed push delivery is idempotent and cannot resurrect an ended/expired call.
- [ ] Android calls integrate with Core-Telecom rather than deprecated `android.net.sip` APIs.
- [ ] Answered mobile audio enters the existing RFC-0033/0035 voice pipeline and TTS returns over the same call session.
- [ ] Barge-in can interrupt Jarvis speech without ending the call.
- [ ] Call sessions attach to existing conversation/task/GoalRun IDs and appear in one audit/activity history.
- [ ] RFC-0014/per-device policy controls notification-vs-call escalation, retries and quiet hours.
- [ ] The model cannot bypass call policy by self-declaring urgency/emergency status.
- [ ] Call failure/missed/declined state does not falsely fail the underlying GoalRun unless contact itself was the task objective.
- [ ] Overlay/direct and public TURN deployment modes can be selected without changing app semantics.
- [ ] A future SIP/PBX adapter can bridge to ordinary SIP/PSTN without changing the Android WebRTC contract.
- [ ] Unit/integration tests cover answered, declined, missed, delayed push, duplicate push, NAT relay, media reconnect and barge-in cases.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | realtime call gateway/session service, signaling, call policy, voice bridge |
| Mobile API | paired-device call offer/state endpoints, push registration |
| Realtime infra | WebRTC adapter, ICE/STUN/TURN configuration, optional SIP/PBX adapter later |
| Tests | signaling/media state machine, policy, push idempotency, reconnect |
| Docs | remote calling deployment/security guide |

## Out of scope

Replacing RFC-0025 ChannelGateway; using deprecated Android SIP APIs; making PSTN/SIP mandatory; video calls in v1; storing raw call audio by default; bypassing normal Jarvis approval/privacy policy during a call.

## Notes

Android deprecated `SipManager`/`android.net.sip` in API 31 and explicitly says it should not be the basis of future VoIP apps. Current Android guidance provides `androidx.core:core-telecom` for standalone calling apps. WebRTC provides standard ICE/STUN/TURN traversal, and Asterisk remains a viable optional SIP/WebRTC interoperability layer.

Recommendation: **ADAPT STRONGLY — direct WebRTC for Jarvis↔app, SIP only as an interoperability gateway.**