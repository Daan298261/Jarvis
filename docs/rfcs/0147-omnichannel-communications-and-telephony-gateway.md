# RFC-0147: Omnichannel communications and telephony gateway

**Status:** accepted  
**Date:** 2026-09-24

## Problem
A daily assistant must be reachable beyond its desktop while preserving identity, consent and conversation continuity.

## Decision
Create a Channel Gateway with adapters for supported messaging, email, push and optional telephony/voice-room providers. Normalize inbound messages into authenticated conversation envelopes and outbound actions into approval-aware sends. Bind channel identities to owner-approved principals/devices; never infer identity from display name alone. Route each channel to a persona/conversation and preserve threading. Add quiet hours, allowlists, rate limits, attachment quarantine and anti-spoof signals.

## Acceptance criteria
- [ ] Typed adapter contract for inbound/outbound/thread/attachment/call events.
- [ ] Identity binding and revocation are explicit and auditable.
- [ ] Sending/calling obeys approval and quiet-hour policies.
- [ ] Attachments are size/type scanned before agent access.
- [ ] Conversation continuity works across desktop/phone/channel without transcript duplication.
- [ ] Provider outage queues safely and retries idempotently.

## Likely files
`backend/app/channels/`, credential broker, companion gateway, conversations UI, tests.
