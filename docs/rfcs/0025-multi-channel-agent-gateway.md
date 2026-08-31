# RFC-0025: Multi-channel agent gateway

**Status:** accepted  
**Queue item:** Extensible Agent OS — persistent agents / remote supervision  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-31

## Problem

Persistent Jarvis agents should be reachable where users already work, but the current architecture does not define a channel-neutral way for the same agent identity and task state to continue across the desktop UI, Slack, Discord, Telegram, email-like adapters, or future custom channels. Letta's persistent agents expose this pattern directly. Implementing each channel as a separate bot would fragment memory, permissions, conversation history, and audit state.

## Decision

Add a `ChannelGateway` abstraction that maps authenticated external identities and conversations onto existing Jarvis Agent Profiles, workspaces, GoalRuns, Decision Inbox items, and policy checks.

Each adapter normalizes inbound events into a common `ChannelEvent` envelope containing channel, tenant/account, external user identity, conversation/thread identity, message/event ID, timestamp, attachments/references, reply target, and verified authentication metadata. Outbound responses use a matching normalized interface.

Channel bindings are explicit and revocable. A binding defines which Jarvis agent/workspace is reachable, which external identities may use it, allowed capabilities, whether proactive notifications are permitted, and which kinds of approval can be performed from that channel. Channel policy may only reduce authority relative to the underlying Agent Profile; it cannot increase it.

Conversation continuity is keyed to Jarvis task/goal/thread identity rather than to the transport. A user can start work in one channel and continue it in another without cloning the agent or losing state. Attachments and external links are treated as untrusted input and pass normal ingestion/sandbox rules.

## Acceptance criteria

- [ ] Define normalized `ChannelEvent`, `ChannelBinding`, and outbound message contracts independent of any one provider.
- [ ] A binding identifies Jarvis Agent Profile/workspace, authorized external principals, allowed inbound event types, outbound notification policy, and channel-specific capability ceilings.
- [ ] External identity mapping is explicit, auditable, revocable, and never inferred solely from display name.
- [ ] Channel policy can restrict but never broaden Agent Profile/task authority.
- [ ] A channel event can attach to an existing Jarvis conversation, task, GoalRun, or Decision Inbox item using stable internal IDs.
- [ ] Idempotency keys prevent duplicate webhook/message delivery from causing duplicate task execution.
- [ ] Attachments and URLs are marked with provenance and treated as untrusted until processed by normal Jarvis safety/tool policies.
- [ ] Approval actions performed through an external channel require authenticated identity, exact action preview, nonce/expiry protection, and audit logging.
- [ ] Proactive notifications honor RFC-0014 proactivity and per-binding notification settings; disabling a channel stops outbound delivery without stopping the underlying agent.
- [ ] Adapter failures degrade that channel only and do not corrupt agent/task state.
- [ ] Provide one reference adapter plus a fake/test adapter proving the abstraction; additional production channels can follow separately.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | channel gateway/contracts, identity bindings, webhook/event ingestion, notification service |
| Frontend | Agent/Profile channel bindings and notification settings |
| Tests | idempotency, identity, policy ceilings, cross-channel continuity |
| Docs | integration/channel adapter developer guide |

## Out of scope

Building every Slack/Discord/Telegram/email adapter in one RFC; social-media marketing publishing; replacing existing integration APIs; public guest portals, which remain RFC-0008.

## Notes

Source: https://www.letta.com/agent/  
Discovery date: 2026-08-31  
Recommendation: ADAPT.  
Jarvis is adapting the channel-neutral persistent-agent pattern so one durable Agent Profile can be reached from multiple transports while retaining Jarvis policy, audit, and task identity.
