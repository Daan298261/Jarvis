# RFC-0157: Proactive assistant — event rules, digests and interruption budget

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Always-on assistants should notice useful changes without becoming noisy, manipulative or expensive.

## Decision
Add a Proactivity Engine consuming approved events from schedules, channels, Sensorium, Goals and integrations. Rules produce IGNORE, LOG, DIGEST or NOTIFY outcomes using owner-defined priorities and quiet hours. Introduce an interruption budget per time window and deduplicate semantically similar alerts. Models may rank candidate relevance but cannot bypass hard notification policy. Every proactive message explains its trigger and can be muted at source/rule level.

## Acceptance criteria
- [ ] Event→rule→notification provenance is inspectable.
- [ ] Quiet hours, rate limits, dedupe and interruption budgets enforced before model output.
- [ ] Daily/weekly digest compacts low-priority events.
- [ ] One-click mute/tune per source/rule.
- [ ] No notification generated solely to increase engagement.
- [ ] Offline events queue and reconcile safely.

## Likely files
Scheduler/events, notification service, Settings/Inbox, tests.
