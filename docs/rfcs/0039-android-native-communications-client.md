# RFC-0039: Android native communications client

**Status:** accepted  
**Queue item:** P1/P2 — Android client / remote supervision  
**Author:** ChatGPT architecture synthesis  
**Date:** 2026-09-06

## Problem

`ANDROID_CLIENT.md` currently treats the Android experience primarily as an evolution of the existing `/phone` PWA/TWA/WebView. That remains suitable for ordinary remote-control screens, but reliable incoming VoIP calls, background ringing, microphone/audio routing, Bluetooth/headset behavior, secure local device credentials, full-screen incoming-call UI and Android Telecom integration require a native Android layer.

Jarvis needs one Android product, not a second unrelated app: the native layer should add OS-level communications capabilities while reusing the existing Jarvis task/auth/conversation APIs and, where practical, shared web UI for non-native screens.

## Decision

Evolve the Jarvis Android client into a **hybrid native application**:

- **Kotlin + Jetpack Compose** native shell for lifecycle-critical and device-native features;
- **Jetpack Core-Telecom** for VoIP call lifecycle/audio routing/system interoperability;
- **WebRTC** media engine behind a `RealtimeMediaClient` interface;
- **Android Keystore** for paired-device secrets/tokens;
- **FCM high-priority push** as the default wake path for incoming calls/urgent events, with payloads limited to opaque identifiers and safe metadata;
- existing Jarvis REST/WebSocket APIs for tasks, state, approvals, history and normal command traffic;
- existing `/phone` UI may initially be embedded/reused for administration screens, but call handling, push, audio, credential storage and critical notifications are native.

Do not duplicate Jarvis business logic in the app. The Leader remains authoritative for agents, models, memory, policy, tasks and verification. The mobile client is a trusted presentation/input/communications surface.

## Native app architecture

Suggested modules:

`app-shell` — Compose navigation, theme, lifecycle, deep links  
`auth-device` — pairing, Keystore, device identity/revocation  
`jarvis-api` — typed REST/WebSocket client  
`calls` — Core-Telecom integration, call state, notifications  
`media-webrtc` — WebRTC signaling/media, reconnect, stats  
`push` — FCM token registration and call/event wakeups  
`tasks` — task list/detail/control and live execution events  
`decisions` — Decision Inbox display/approval actions  
`voice-command` — push-to-talk/live command UI using the same Leader pipeline  
`local-data` — minimal encrypted/cacheable app state; no separate Jarvis memory  
`settings` — connectivity, notifications, call policy, privacy, diagnostics

Use coroutines/Flow for state propagation. Long-lived state is modeled explicitly rather than hidden in Activities/Fragments. Network operations must survive ordinary rotation/process recreation where applicable. WorkManager is for deferred sync/retry only, not realtime call media.

## Functional capability set

### Calling and realtime voice

The app should be able to:

- receive a proactive Jarvis incoming call while the app is backgrounded/phone locked;
- show native answer/decline UI and caller identity/reason category;
- answer, decline, hang up, mute/unmute and switch audio route;
- support earpiece, speaker, wired headset and Bluetooth through Core-Telecom endpoint handling;
- show connection quality/state: ringing, connecting, active, reconnecting, relayed/direct, degraded;
- support full-duplex speech with Jarvis and barge-in while Jarvis is speaking;
- resume/reconnect short network interruptions without creating a second conversation;
- optionally expose hold later when backend semantics are implemented;
- show missed Jarvis calls and allow one-tap callback/continue by text;
- attach the call to the exact task/event/conversation that caused it.

### Commands and conversation

- text command entry;
- push-to-talk voice commands;
- optional hands-free live voice session when explicitly started by the user;
- stream Jarvis text responses while audio is speaking;
- switch an active voice call into text without losing conversation context;
- show concise transcript during/after call when enabled by privacy settings;
- interruption commands such as stop/cancel/wait get priority handling.

### Task supervision

- view active/recent tasks and GoalRuns;
- show real execution phase/status rather than generic spinners;
- view current step, worker/node, elapsed time and degraded/recovery state where available;
- cancel, pause, resume or continue supported tasks;
- receive task completion/failure/blocked notifications;
- reopen the exact task from a notification/call deep link;
- view relevant verifier result/evidence summaries.

### Decision Inbox and approvals

- receive approval-required notifications;
- inspect exact action, target, consequence/risk and reason for gating;
- approve/reject one exact Decision Inbox item with nonce/expiry binding;
- never use bare conversational `yes` as authorization for consequential actions;
- allow discussion/questions about a pending action without accidentally approving it;
- show expired/superseded decisions clearly.

### Proactive contact controls

- per-category notification/call preferences;
- quiet hours and emergency/critical exceptions defined by policy;
- choose `silent`, `notification`, `call if unacknowledged`, or `immediate call` where allowed;
- configure retry/escalation limits;
- device-specific priority when multiple Jarvis mobile devices are paired;
- one-tap `Do not call me for this type` that updates user-visible policy rather than an opaque model memory.

### Mobile context/actions

Only with explicit permission/policy, the app may provide Jarvis:

- current coarse/precise location on request;
- camera photo capture/upload;
- gallery/file attachment selection;
- microphone input;
- share-to-Jarvis Android share target for URLs/text/files/images;
- notification action shortcuts such as cancel task, call back, open Decision Inbox;
- optional device status such as battery/network type for routing diagnostics.

Do not continuously upload location, microphone, notification contents or other device telemetry merely because the app is installed.

### Connectivity and pairing

- QR/link-based pairing to the existing Leader trust model;
- store secrets in Android Keystore, never plaintext preferences;
- list/revoke this device from Leader and support local sign-out/wipe;
- LAN discovery/reachability where appropriate;
- overlay/WAN endpoint support from `ANDROID_CLIENT.md`;
- automatic connectivity preference: trusted LAN/overlay before public relay where policy permits;
- clear offline/degraded indicator and retry behavior;
- push token refresh/re-registration without forcing re-pairing.

### History and diagnostics

- call history: answered/declined/missed/failed, duration and linked Jarvis event/task;
- message/task activity timeline shared with desktop;
- optional transcript retention with configurable local/server policy;
- network/media diagnostics: RTT, jitter, packet loss, selected audio route and relay/direct status;
- exportable/redacted diagnostic bundle without credentials or raw private content by default.

## UX guidelines

1. **Fast first response.** Ringing/answer UI and command acknowledgement must not wait on the 9B/27B model.
2. **One Jarvis identity.** Calls, chat, tasks and approvals share the same conversation/task records; no mobile-specific memory silo.
3. **Native only where native matters.** Use Compose/Core-Telecom for calling, notifications, audio, permissions and secure storage; reuse shared web/product surfaces where that is cheaper and reliable.
4. **Show real state.** `LISTENING`, `TRANSCRIBING`, `RUNNING`, `USING_TOOL`, `VERIFYING`, `WAITING`, `SPEAKING`, `DONE`, `DEGRADED` come from backend events, never fake animation timers.
5. **Minimize taps for safe actions.** Cancel, callback, mute and task status are immediately reachable; destructive/external approvals retain exact-action confirmation.
6. **Do not make the user manage networking concepts during daily use.** Pair once; reconnect automatically; surface technical diagnostics only when needed.
7. **Privacy by default.** Background access is narrow, visible and revocable. Push payloads and lock-screen content avoid sensitive task details unless the user explicitly enables them.
8. **Graceful degradation.** If WebRTC fails, preserve the notification/task deep link and offer text/push-to-talk rather than leaving a dead call screen.

## Security/reliability requirements

- WebRTC media uses DTLS-SRTP; signaling uses authenticated TLS/WSS or trusted overlay transport.
- Call offers/tokens are short-lived, single-use/bounded and bound to paired device identity.
- Keystore-backed credentials are never placed in WebView JavaScript/localStorage.
- Native↔WebView bridge, if used, is capability-scoped; the embedded page does not receive arbitrary Android privileges.
- Incoming call actions are idempotent and validated against current server call state.
- App process death/restart cannot duplicate task execution or approval.
- Full-screen incoming-call behavior follows Android notification/permission rules; normal alerts must not abuse call UI.
- Audio recording/call media is not retained by default.

## Acceptance criteria

- [ ] One Android app supports both existing Jarvis remote-control functions and native VoIP call handling.
- [ ] Native Kotlin/Compose shell exists with Core-Telecom and WebRTC modules separated from task/business logic.
- [ ] Incoming Jarvis calls can wake/ring a backgrounded compatible Android device, answer and establish audio.
- [ ] Active calls support mute, hangup, earpiece/speaker/Bluetooth routing and reconnect state.
- [ ] Task/chat/Decision Inbox state uses existing Leader APIs and internal IDs rather than a second mobile database of truth.
- [ ] Device secrets are Keystore-backed and inaccessible to embedded web content.
- [ ] Task phase/status, call state and spoken feedback are driven by real backend events.
- [ ] App supports text commands, push-to-talk, task supervision, exact-item approvals and proactive notification/call preferences.
- [ ] User-granted camera/file/location/share-target features are scoped, visible and optional.
- [ ] Missed/failed calls deep-link to the originating Jarvis event/task and allow text continuation/callback.
- [ ] Network/media diagnostics are available without exposing credentials.
- [ ] Tests cover locked/background incoming call, process recreation, push duplication, audio route change, network switch Wi-Fi↔cellular, token expiry, revoke-device and approval binding.

## Likely files

| Area | Paths |
| --- | --- |
| Android | new native app shell/modules; shared `/phone` content only where suitable |
| Backend | mobile device registration/push/call endpoints already defined by related RFCs |
| Tests | Android instrumentation + backend integration fixtures |
| Docs | Android build/pairing/call/privacy guide |

## Out of scope

Becoming the default Android dialer; displaying/managing ordinary carrier calls; native on-device LLM execution in v1; mandatory video calling; replacing the desktop portal; duplicating Jarvis memory/orchestration on the phone.

## Notes

This RFC extends, rather than replaces, `ANDROID_CLIENT.md`: the Leader remains authoritative and the same pairing/task API is reused. The earlier PWA/TWA/WebView-first approach remains valid for ordinary UI, but incoming VoIP requirements justify a native communication shell.

Recommendation: **ADAPT STRONGLY — hybrid native Android client, not a pure PWA and not a separate mobile Jarvis.**