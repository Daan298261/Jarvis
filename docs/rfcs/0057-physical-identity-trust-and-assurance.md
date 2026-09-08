# RFC-0057 — Physical Identity Trust and Assurance

**Status:** Accepted  
**Priority:** P1 / High  
**Target:** Jarvis Core Security, Red Team, Blue Team, Licensing Administration, Swarm Administration  
**Depends on:** RFC-0054 Local Household Identity Recognition  
**Related:** RFC-0012 Local License / BYO Inference; existing approval, auth, licensing, swarm and security-pack architecture

## Summary

RFC-0054 gives Jarvis a privacy-first local biometric identity resolver. This RFC defines how that signal becomes useful to the wider system without turning face recognition into a single-factor password.

Jarvis SHALL treat physical identity as one input into an assurance engine. Face recognition may increase or decrease trust, trigger step-up authentication, annotate security events, influence session privilege, and gate sensitive administrative actions. It MUST NOT become the sole root of authentication, the cryptographic root of a commercial license, or a general-purpose face-search service.

The primary use cases are:

1. stronger local authentication and step-up authorization;
2. identity-aware Red Team and Blue Team operation;
3. detection of physical/session takeover anomalies;
4. owner-presence requirements for highly sensitive actions;
5. local enforcement of named security-operator seats or roles;
6. biometric-aware but privacy-preserving license administration;
7. swarm-wide physical-presence context without distributing raw face imagery or reusable biometric templates.

## Problem

A recognized face is useful context, but by itself is not sufficient security. Photographs, displays, replayed video, recognition errors, camera failure, model drift, occlusion and deliberate spoofing all make face-only authentication inappropriate for privileged Jarvis operations.

At the same time, ignoring physical identity wastes a valuable local signal. Jarvis may already know that:

- a trusted owner is physically at the workstation;
- the owner has left;
- an unknown person has appeared;
- a privileged session remains unlocked;
- a Red Team or credential-vault action is being requested;
- the physical identity changed during a security-sensitive session;
- the camera became unavailable immediately before a sensitive operation.

These signals are particularly useful for a system that can autonomously inspect, administer and secure its host and network.

## Goals

Jarvis SHALL provide a reusable Physical Identity Trust layer that:

- consumes local identity results from RFC-0054;
- optionally consumes liveness and continuous-presence signals;
- combines them with cryptographic/session/device trust;
- produces a normalized authentication assurance level;
- exposes a bounded authorization context to Red Team, Blue Team, core approval flows and licensing administration;
- supports step-up authentication instead of binary lock/unlock behavior;
- emits auditable security events when identity and session state diverge;
- preserves privacy by keeping biometric processing local and minimizing biometric data movement;
- preserves usability when no camera is present or recognition is unavailable.

## Non-goals

This RFC does NOT:

- make face recognition a password replacement;
- cryptographically bind a Jarvis license to a face;
- permit cloud face matching;
- permit arbitrary face search or forensic identification;
- identify unknown visitors against external databases;
- distribute face embeddings across the swarm by default;
- require every Jarvis node to have a camera;
- authorize destructive or offensive security actions solely because a known face is visible;
- define the production face detector/embedding model package itself; RFC-0054 owns recognition and enrollment.

## Design principle: identity is a signal, not authority

Jarvis MUST distinguish the following concepts:

- **identity claim** — who the face resolver believes is present;
- **liveness** — whether the observed subject appears to be a live physical person rather than a replay/spoof;
- **presence continuity** — whether the same trusted person has remained physically present over time;
- **session identity** — which Jarvis account/session is authenticated;
- **device trust** — whether the machine/node/session key is trusted;
- **cryptographic authentication** — passkey, private key, PIN/password-backed credential, hardware key or equivalent;
- **authorization** — what actions the resolved operator is permitted to perform;
- **license entitlement** — what features the cluster has purchased or is allowed to use.

No one field may silently substitute for another.

## Assurance model

Jarvis SHALL calculate an assurance level from independent signals rather than using a single Boolean `face_authenticated` flag.

Suggested initial levels:

### A0 — Unknown / unauthenticated

Typical signals:

- no valid Jarvis session; or
- unknown physical identity; or
- explicitly locked state.

Allowed examples:

- public/guest UI where configured;
- non-sensitive chat;
- health/status surfaces explicitly intended for unauthenticated use.

### A1 — Recognized physical presence

Typical signals:

- RFC-0054 confirmed identity;
- face quality above configured minimum;
- recognition margin acceptable;
- no strong liveness guarantee required.

A1 is personalization/trust context only. It MUST NOT authorize privileged security or license actions.

### A2 — Authenticated local session + recognized presence

Typical signals:

- valid Jarvis user/session authentication;
- trusted local device/session;
- physical identity agrees with session role.

Suitable for ordinary owner/household use according to permissions.

### A3 — Strong step-up authentication

Typical signals:

- A2;
- recent passkey/private-key/hardware-key/PIN-backed step-up;
- optional liveness confidence above policy threshold.

Suitable for security administration, credential access and sensitive configuration.

### A4 — Privileged security assurance

Typical signals:

- A3;
- role explicitly authorized for security operations;
- licensed security entitlement present;
- physical presence recent or continuously maintained when policy requires it;
- optional hardware/private-key requirement.

Suitable for high-risk Red Team operations, cluster/license ownership changes, credential-vault export, trust-anchor rotation and equivalent actions.

Assurance levels MUST be policy-driven. Deployments without a camera MUST still be able to reach high assurance using cryptographic authentication and trusted-device mechanisms.

## Physical identity context

The core runtime SHALL expose a normalized, non-image `PhysicalIdentityContext` similar to:

```json
{
  "state": "confirmed",
  "identity_id": "owner",
  "relationship": "owner",
  "recognition_confidence": 0.93,
  "recognition_margin": 0.16,
  "liveness_state": "pass",
  "liveness_confidence": 0.88,
  "continuous_presence": true,
  "present_since": "2026-09-08T17:41:02+02:00",
  "last_confirmed_at": "2026-09-08T17:53:18+02:00",
  "source_node": "office-desktop",
  "camera_available": true
}
```

This object MUST contain no image, face crop, base64 frame or raw biometric template.

`identity_id` MUST refer only to locally enrolled identities. Unknown people SHALL remain anonymous and may be represented by short-lived track IDs such as `unknown:track_8317`. Unknown tracks MUST NOT be persisted as durable identities unless an owner explicitly begins enrollment.

## Liveness

Liveness SHOULD be implemented as an independent provider interface so recognition and anti-spoofing can evolve separately.

Initial liveness may use low-cost temporal signals such as:

- natural landmark movement;
- blink/eye dynamics;
- changing head pose;
- parallax or coarse depth cues where available;
- multi-frame consistency;
- challenge-response only for explicit high-assurance step-up flows.

Passive liveness is preferred for ordinary operation. Active prompts such as "turn your head" SHOULD be reserved for high-risk reauthentication because they create friction.

Liveness results SHALL be normalized into `unknown | pass | fail | unavailable` with confidence and provider metadata.

A failed liveness check MUST reduce assurance and SHOULD generate a Blue Team event when a sensitive action is being attempted.

## Trust engine

A new trust/assurance component SHALL combine:

- session authentication state;
- session role;
- device trust;
- RFC-0054 physical identity;
- liveness;
- continuous presence;
- time since last strong authentication;
- requested operation risk;
- security-pack entitlement;
- cluster/license administration role;
- optional node/location trust metadata.

The engine SHALL return:

```json
{
  "assurance": "A3",
  "operator_id": "owner",
  "session_identity_matches_physical_identity": true,
  "step_up_required": false,
  "risk_reasons": [],
  "expires_at": "..."
}
```

The trust engine MUST be deterministic and policy-driven. LLMs MAY explain a decision but MUST NOT decide authentication assurance.

## Step-up authentication

Jarvis SHOULD prefer temporary privilege elevation over repeatedly locking the entire application.

Example:

1. owner has a normal authenticated session;
2. owner opens Red Team controls;
3. face/presence agrees with owner, but no recent strong auth exists;
4. Jarvis requests passkey/private-key/PIN step-up;
5. A4 is granted for a short configured period;
6. if physical identity changes or trusted presence is lost, new privileged actions require step-up again.

Running operations SHALL follow explicit policy. Default behavior:

- do not abruptly kill safe long-running analysis just because the owner temporarily leaves view;
- prevent NEW high-risk actions once assurance falls below the operation requirement;
- allow policy to downgrade a privileged UI/session to read-only;
- require reauthentication for destructive, credential-bearing or externally impactful actions.

## Red Team integration

Red Team SHALL consume assurance as an authorization prerequisite, not as an instruction-generation input.

Sensitive Red Team actions may declare minimum assurance, e.g.:

```yaml
operation: credentialed_internal_assessment
requires:
  entitlement: red_team
  role: security_operator
  assurance: A4
  recent_strong_auth_seconds: 300
```

The Red Team module SHOULD include adversarial tests for Jarvis's own physical-auth boundary:

- owner leaves an unlocked privileged session;
- unknown person attempts to continue the session;
- printed-photo spoof attempt;
- screen/video replay attempt;
- camera occlusion immediately before a high-risk request;
- recognition ambiguity between two enrolled identities;
- identity changes mid-session;
- face model unavailable or restarted;
- stale confirmed identity surviving longer than configured timeout;
- mismatched session identity and physical identity;
- compromised low-trust swarm node claiming owner presence;
- replay of old presence events.

These tests SHALL validate defensive policy and audit behavior. They SHALL NOT create a general-purpose biometric attack toolkit.

## Blue Team integration

Blue Team SHALL treat physical identity as a security telemetry source.

Recommended event types:

- `identity.presence.confirmed`
- `identity.presence.lost`
- `identity.presence.changed`
- `identity.unknown_present`
- `identity.multiple_people_present`
- `identity.liveness.failed`
- `identity.camera.unavailable`
- `identity.camera.tamper_suspected`
- `identity.session_mismatch`
- `identity.assurance.downgraded`
- `identity.step_up.required`
- `identity.privileged_action.denied`

Blue Team SHOULD correlate these with host/network actions.

Example rule:

> A privileged local shell or credential-vault request occurs after the owner leaves and an unknown person appears.

Possible response:

- raise local risk score;
- suppress secrets;
- require strong step-up authentication;
- move Red Team UI to read-only;
- preserve an immutable security audit event;
- optionally notify the owner through configured channels.

Physical identity events MUST NOT automatically trigger destructive containment unless a separate policy explicitly allows it.

## Security action audit context

Every material security action SHOULD carry an immutable snapshot such as:

```json
{
  "session_user": "owner",
  "physical_identity": "owner",
  "physical_identity_state": "confirmed",
  "recognition_confidence": 0.93,
  "liveness_confidence": 0.88,
  "continuous_presence": true,
  "device_trust": "trusted",
  "assurance": "A4",
  "entitlement": "red_team",
  "step_up_method": "passkey",
  "step_up_age_seconds": 42
}
```

This snapshot SHALL contain only normalized trust metadata, never images or reusable embeddings.

The purpose is later attribution and forensic reconstruction: who was authenticated, who appeared physically present, which trust level was used, and whether the physical/session identity changed during execution.

## Authorization roles

Physical recognition SHALL resolve identity; it SHALL NOT directly define permissions.

Example local identities:

```yaml
owner:
  relationship: owner
  permissions:
    normal_jarvis: true
    security_admin: true
    red_team: true
    blue_team: true
    license_admin: true
    swarm_admin: true

household_member:
  relationship: household_member
  permissions:
    normal_jarvis: true
    personal_owner_memory: false
    red_team: false
    blue_team: alerts_only
    license_admin: false

security_operator:
  relationship: trusted_person
  permissions:
    personal_owner_memory: false
    red_team: true
    blue_team: true
    license_admin: false
```

The authorization engine SHALL remain authoritative.

## Licensing integration

### License root

Jarvis MUST NOT make a person's face the cryptographic root of a license.

The existing signed cluster/device entitlement remains authoritative:

`license signature -> cluster_id -> node/pack/features -> authorization policy`

Reasons:

- biometric recognition can fail;
- cameras are optional;
- headless nodes need licensing;
- license transfer/recovery must remain possible;
- biometric coupling complicates privacy/compliance;
- central license infrastructure should not need biometric data.

### Owner-presence protected license administration

High-impact license operations MAY require physical owner presence plus strong auth, including:

- transfer cluster ownership;
- add/remove named security operators;
- export or rotate license/trust keys;
- enable remotely reachable Red Team capability;
- change offline lease/trust settings;
- reset entitlement administration state.

Recommended default: recognized owner presence + cryptographic step-up. Face alone is never sufficient.

### Named operator seats

Future commercial/business licensing MAY expose named security-operator seat counts, e.g. `security_operator_seats: 2`.

The licensing service only needs to know the number of licensed seats. Local Jarvis maps enrolled identities to those seats. Face embeddings, images and identity names MUST NOT be uploaded to the licensing service solely for seat enforcement.

This provides local anti-sharing/operator accountability without central biometric collection.

## Swarm integration

Trusted presence MAY be propagated across Jarvis nodes as signed, short-lived assertions rather than face data.

Example:

```json
{
  "event": "presence.identity.confirmed",
  "identity_id": "owner",
  "relationship": "owner",
  "assurance_component": "physical_presence",
  "confidence": 0.94,
  "source_node": "office-camera",
  "issued_at": "...",
  "expires_at": "...",
  "nonce": "..."
}
```

Requirements:

- assertion is signed by an enrolled/trusted node key;
- short TTL;
- anti-replay nonce/counter;
- receiving node may weight assertions according to source-node trust;
- raw face frames and embeddings are not transmitted;
- low-trust/public entry nodes MUST NOT be allowed to elevate cluster-wide assurance merely by asserting owner presence;
- local policy may require presence from the same device for very high-risk actions.

## Camera and privacy rules

- Camera access remains explicit and visible.
- Raw frames remain local and ephemeral.
- No raw frame goes to normal logs, memory, task history, telemetry, licensing or the security event bus.
- Face crops are not retained by default.
- Reusable embeddings stay within RFC-0054 encrypted storage.
- Unknown visitor tracks are short-lived.
- Presence assertions carry only normalized metadata.
- Disabling physical identity immediately stops use of the signal and lowers assurance gracefully rather than corrupting the session.

## Failure behavior

Camera failure, recognition failure or model unavailability MUST fail safely without locking legitimate users out of Jarvis entirely.

Policy examples:

- ordinary authenticated use continues when camera is unavailable;
- operations that explicitly require physical presence require cryptographic step-up or deny according to policy;
- known face becoming `unknown` does not automatically log out the user;
- high-risk capability is downgraded or made read-only when assurance falls below its threshold;
- headless nodes rely on cryptographic/device trust.

## Configuration

Suggested settings:

```yaml
physical_identity_trust:
  enabled: false
  use_for_assurance: true
  require_liveness_for_privileged: true
  presence_grace_seconds: 60
  strong_auth_ttl_seconds: 300
  downgrade_on_identity_change: true
  downgrade_on_unknown_person: policy
  require_same_node_presence_for_a4: false
  allow_swarm_presence_assertions: true
  trusted_presence_source_roles:
    - leader
    - senior_worker
```

Sensitive defaults SHOULD be conservative and disabled until identity enrollment exists.

## Security requirements

1. Face recognition alone MUST NOT authorize A3/A4 actions.
2. Trust calculations MUST be deterministic, non-LLM policy code.
3. Identity mismatch MUST never silently select the nearest identity.
4. Unknown is a valid state and must remain safe.
5. Presence assertions MUST be authenticated and replay-resistant.
6. A compromised low-trust node MUST NOT gain cluster-wide privilege by fabricating presence.
7. Biometric data MUST stay local unless a future RFC explicitly defines a stronger privacy-preserving transport.
8. License servers MUST NOT receive face embeddings for ordinary entitlement enforcement.
9. Privileged actions MUST include an assurance snapshot in the audit trail.
10. Physical identity failure MUST degrade gracefully to cryptographic authentication rather than make Jarvis unusable.

## Implementation phases

### Phase 1 — Trust substrate

- define `PhysicalIdentityContext`;
- define assurance levels and deterministic evaluator;
- integrate RFC-0054 resolver state;
- add policy tests;
- emit assurance-change events;
- no liveness dependency required yet.

### Phase 2 — Core step-up and authorization

- integrate session/device/private-key/passkey/PIN-backed step-up;
- annotate high-risk operations with minimum assurance;
- add read-only/downgrade behavior;
- add immutable audit context.

### Phase 3 — Blue Team integration

- event schema;
- correlation rules for identity/session mismatch;
- camera/liveness anomaly events;
- owner notification hooks;
- no automatic destructive containment by default.

### Phase 4 — Red Team integration

- privileged-action assurance requirements;
- adversarial tests of Jarvis's own auth/presence boundary;
- spoof/replay/session-takeover verification scenarios;
- ensure tests cannot become external general-purpose face-search capability.

### Phase 5 — Licensing and swarm integration

- owner-presence protected license administration;
- optional named local security-operator seats;
- signed short-lived presence assertions across trusted swarm nodes;
- anti-replay and source-node trust weighting.

### Phase 6 — Liveness provider

- provider interface;
- passive temporal liveness first;
- active challenge-response only for explicit high-assurance reauthentication;
- benchmark false rejects, false accepts and latency before enabling by default.

## Acceptance criteria

RFC-0057 is considered implemented when:

- [ ] physical identity is represented as a normalized non-image trust signal;
- [ ] a deterministic assurance evaluator combines session, device, crypto and physical signals;
- [ ] face recognition by itself cannot grant privileged security/license authority;
- [ ] ordinary Jarvis still works with no camera;
- [ ] Red Team high-risk actions can require configured assurance;
- [ ] Blue Team receives identity/session mismatch and assurance downgrade events;
- [ ] privileged security actions retain an immutable assurance snapshot;
- [ ] owner-presence can protect sensitive license administration without binding the license cryptographically to a face;
- [ ] swarm presence assertions are signed, short-lived and replay-resistant;
- [ ] low-trust nodes cannot elevate cluster-wide privilege;
- [ ] no raw image/frame/face crop enters memory, logs, telemetry, licensing or security-event payloads;
- [ ] identity loss causes configured downgrade/step-up behavior rather than unconditional logout;
- [ ] tests cover spoofed presence claims, stale assertions, identity changes, unknown persons, camera loss and no-camera environments.

## Recommended ticket split

Implementation SHOULD be split into separate tickets even though this RFC defines the complete architecture:

1. **0057-A:** assurance/trust substrate and policy tests;
2. **0057-B:** step-up authentication and authorization integration;
3. **0057-C:** Blue Team physical-identity telemetry/correlation;
4. **0057-D:** Red Team assurance gates and adversarial self-tests;
5. **0057-E:** licensing administration + named-operator integration;
6. **0057-F:** signed swarm presence assertions;
7. **0057-G:** liveness provider and anti-spoof benchmark.

This preserves the repository's one-ticket/one-concern implementation discipline while keeping one architectural source of truth.
