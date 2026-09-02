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

## Implementation recommendation

Treat channels as transports only. Do not create separate per-channel agent memories, schedulers, policies, or task databases. The durable identity remains the Jarvis Agent Profile / Workspace / GoalRun; the channel only authenticates a principal, carries messages, attachments, approvals, and notifications, and provides presentation metadata.

The first production adapter should be a channel that is useful for remote owner supervision and has a stable bot/webhook model. A Telegram-like adapter is a good reference target because it proves mobile continuation, proactive notification, reply threading, attachments, and authenticated commands without requiring the complexity of an enterprise multi-tenant integration. Slack/Discord/email can follow using the same contracts. The RFC does not require that provider specifically if implementation constraints favor another adapter.

Cross-channel continuation should be explicit and inspectable. A message may attach to an existing `conversation_id`, `task_id`, or `goal_run_id`; otherwise Jarvis creates a new internal thread. The UI should show the transport history so a task started on desktop and continued remotely remains understandable in one activity timeline.

Approvals must not become vague chat commands such as `yes`. An external approval response must reference one exact Decision Inbox item or signed approval token with action summary, scope, nonce, and expiry. Where a channel cannot provide sufficient identity assurance, it may notify and discuss but must not authorize consequential operations.

Use a normalized outbound notification policy with urgency, channel preference, quiet-hours handling, deduplication, retry/backoff, and fallback. Example: a low-priority task completion can wait for desktop visibility while an expiring approval may be allowed to notify a mobile channel. RFC-0014 remains authoritative for whether proactive contact is permitted at all.

Support a `delivery_state` model such as `PENDING`, `SENT`, `DELIVERED` where the provider supports it, `FAILED`, `EXPIRED`, and `SUPPRESSED`. Channel delivery failure must not mark the underlying Jarvis task as failed unless delivery itself is the task goal.

Channel secrets/tokens are integration credentials, not agent memory. Store them through the existing secret/credential mechanism and never inject raw credentials into model context. Adapters receive only the minimum credential handle required for transport operations.

Rate limits and duplicate provider events are expected. Adapters must implement provider event IDs/idempotency, bounded retry/backoff, and per-binding ingress/egress rate limits. Floods from one binding must not starve local Jarvis execution.

Remote command authoring should use the same natural-language task authoring and policy stack as desktop commands. The channel must not invent an alternate command parser with different authority semantics.

## Acceptance criteria

- [ ] Define normalized `ChannelEvent`, `ChannelBinding`, and outbound message contracts independent of any one provider.
- [ ] A binding identifies Jarvis Agent Profile/workspace, authorized external principals, allowed inbound event types, outbound notification policy, and channel-specific capability ceilings.
- [ ] External identity mapping is explicit, auditable, revocable, and never inferred solely from display name.
- [ ] Channel policy can restrict but never broaden Agent Profile/task authority.
- [ ] A channel event can attach to an existing Jarvis conversation, task, GoalRun, or Decision Inbox item using stable internal IDs.
- [ ] New inbound work without an explicit continuation target creates a new internal Jarvis thread rather than silently reusing unrelated context.
- [ ] The activity/audit view records which transport carried each user or Jarvis message without duplicating the underlying conversation state.
- [ ] Idempotency keys prevent duplicate webhook/message delivery from causing duplicate task execution.
- [ ] Attachments and URLs are marked with provenance and treated as untrusted until processed by normal Jarvis safety/tool policies.
- [ ] Approval actions performed through an external channel require authenticated identity, exact action preview/reference, nonce/expiry protection, and audit logging.
- [ ] Ambiguous responses such as bare `yes` cannot approve more than one exact outstanding consequential action.
- [ ] Channels without sufficient identity assurance are technically prevented from authorizing configured high-risk action classes.
- [ ] Proactive notifications honor RFC-0014 proactivity and per-binding notification settings; disabling a channel stops outbound delivery without stopping the underlying agent.
- [ ] Outbound messages have observable delivery state and delivery failure does not falsely fail the underlying task.
- [ ] Notification routing supports deduplication, retry/backoff, urgency and per-binding/channel preferences.
- [ ] Provider credentials remain outside model context and are accessed through scoped credential handles.
- [ ] Per-binding rate limits and bounded queues prevent one external channel from exhausting orchestrator resources.
- [ ] Remote natural-language task creation passes through the same task-authoring and policy evaluation path used by the Jarvis UI.
- [ ] Adapter failures degrade that channel only and do not corrupt agent/task state.
- [ ] Provide one reference production-style adapter plus a fake/test adapter proving the abstraction; additional production channels can follow separately.
- [ ] Demonstrate a continuity test where a task is created in one transport, inspected/approved or continued in a second transport, and completed with one shared internal GoalRun/activity history.
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

Target UX example: start a task in the desktop command center, receive an approval request on a configured mobile channel, inspect the exact action and evidence, approve that one action, and later reopen the same task on desktop with the full shared history. The external channel is a window into Jarvis, not a separate Jarvis instance.