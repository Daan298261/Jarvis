# RFC-0117: Durable state journal and known-good rollback

**Status:** implemented  
**Queue item:** P4 — resilient autonomous execution / operator recovery  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-09-18

## Problem

Jarvis is intended to run long-lived agents, automations, memory, integrations, and self-improvement with minimal supervision. A bad migration, agent-authored configuration change, corrupted state update, or failed self-repair can therefore leave the system internally inconsistent even when ordinary task retries work correctly. taOS demonstrates a useful local-first pattern: append-only state history plus an operator command that returns the installation to a known-good state. Jarvis needs the same recovery property without copying taOS's storage implementation or turning every large artifact into an event-sourced database.

## Decision

Add a Jarvis-owned durable mutation journal for authoritative control-plane state and checkpoint-based rollback to a verified known-good point.

Journal consequential mutations to agent/profile configuration, automation/workflow definitions, policy/approval settings, model/runtime configuration, pack/plugin enablement, memory metadata/schema changes, and other explicitly registered control-plane resources. Each record SHALL carry a monotonic sequence, timestamp, actor/source, resource identity, operation type, schema version, correlation/GoalRun ID where applicable, and integrity hash. Sensitive values and reusable credentials MUST NOT be copied into the journal; credential mutations record references/metadata only.

Create periodic and pre-risk checkpoints containing a consistent materialized snapshot plus the journal sequence it represents. Risky migrations, self-improvement deployments, bulk configuration changes, and package upgrades SHOULD create a checkpoint before mutation. A checkpoint becomes `KNOWN_GOOD` only after deterministic health/invariant verification.

Rollback is a staged recovery operation: `PLAN -> QUIESCE -> CHECKPOINT_CURRENT -> RESTORE -> REPLAY_IF_REQUESTED -> VERIFY -> COMPLETE`, with `FAILED` and `PARTIAL` terminal outcomes. Jarvis MUST stop admitting affected mutations while rollback is in progress. Default rollback restores the selected known-good checkpoint; optional forward replay may apply only journal entries explicitly classified replay-safe. External side effects such as sent email, purchases, filesystem changes outside managed state, or third-party API actions are never implied to be undone and must be reported separately.

The journal is an audit/recovery primitive, not a second task engine. Existing GoalRun, automation, memory, policy, audit, and database abstractions remain authoritative.

## Acceptance criteria

- [ ] Implement a durable append-only mutation journal for registered authoritative control-plane resources with monotonic sequence IDs, actor/source, resource ID, operation, schema version, correlation ID, timestamp, and integrity hash.
- [ ] Journal writes and their authoritative state mutation are atomic, or use a crash-safe transaction/outbox protocol that cannot silently commit one without the other.
- [ ] Reusable credentials, private keys, OAuth refresh tokens, raw secrets, hidden model reasoning, and unnecessarily sensitive payloads are excluded from journal entries.
- [ ] Support consistent checkpoints tagged `CANDIDATE`, `KNOWN_GOOD`, or `INVALID`; only deterministic verification can promote a checkpoint to `KNOWN_GOOD`.
- [ ] Automatically create or require a checkpoint before registered high-risk operations including schema migrations, self-improvement deployment, bulk policy/config changes, and pack/runtime upgrades.
- [ ] Rollback follows `PLAN -> QUIESCE -> CHECKPOINT_CURRENT -> RESTORE -> VERIFY -> COMPLETE` and persists progress so a process crash can resume or safely fail closed.
- [ ] Rollback admission control prevents concurrent writes to affected resources while preserving read-only operator inspection and emergency stop controls.
- [ ] A rollback plan previews affected resource classes, target checkpoint/sequence, estimated data loss window, non-reversible external effects, and integrations requiring re-auth/reconciliation before APPLY.
- [ ] Forward replay after restore is opt-in and only accepts operations explicitly marked replay-safe/idempotent; ambiguous or externally consequential operations enter reconciliation rather than being executed again.
- [ ] Failed verification leaves the system in `PARTIAL` or `FAILED`, preserves both pre-rollback and target recovery evidence, and never labels the result known-good.
- [ ] Operator UI/API lists checkpoints, age, verification status, journal coverage, last successful recovery point, and rollback result without exposing secret payloads.
- [ ] Retention/compaction can prune old journal detail only after a retained verified checkpoint makes recovery possible; pruning is audited and configurable.
- [ ] Tests cover crash between journal/state commit, corrupt journal/hash detection, rollback across schema versions, concurrent mutation rejection, secret redaction, replay-safe idempotency, ambiguous external side effects, failed verification, and restart during rollback.
- [ ] A recovery drill creates representative agent/automation/policy state, checkpoints it, applies destructive test mutations, restores the checkpoint on the same installation, and verifies deterministic equivalence for covered state.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | state/repository transaction layer, recovery/checkpoint service, migration and self-improvement hooks |
| Frontend | recovery status, checkpoint browser, rollback preview/confirmation |
| Tests | journal atomicity/integrity, checkpoint verification, crash recovery, rollback/replay fixtures |
| Docs | operator recovery and journal coverage documentation |

## Out of scope

Full event sourcing of every Jarvis database table; versioning arbitrary user files; undoing real-world or third-party side effects; replacing GoalRun/audit logs; distributed swarm consensus or cross-node database replication; backup/export to separate media.

## Notes

Source: https://www.taos.my/ — taOS describes append-only storage and `taos rollback` recovery to a known-good state.  
Discovery date: 2026-09-18.  
Recommendation: **ADAPT STRONGLY**.  
Jarvis adapts the recovery invariant, not taOS internals: authoritative Jarvis state remains in existing repositories, while a bounded mutation journal and verified checkpoints provide crash-safe operator rollback. This is deliberately narrower than backup/export and explicitly distinguishes internal state rollback from irreversible external side effects.

## Implementation note

Landed on `development` via #380 @ `049874c7` (durable mutation journal, known-good checkpoints, staged rollback). `tests/test_rfc0117_state_journal_rollback.py`. The other 0117 file, `0117-tiny-front-chat-responder.md`, was already implemented and is unchanged. Live operator rollback on a Windows install remains desktop sign-off.