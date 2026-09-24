# RFC-0137: Capability parity matrix and continuous benchmark

**Status:** accepted  
**Date:** 2026-09-24

## Problem

“Feature parity” is not testable while competitor capabilities are prose. Anzu needs a durable capability ledger and executable benchmark so new work can be prioritized by measured gaps instead of screenshots or claims.

## Decision

Add a versioned Capability Registry covering Anzu and tracked peer projects. Each capability has: stable ID, user outcome, Anzu implementation path, peer evidence URL/date, parity state (missing/partial/equivalent), local/cloud/offline support, security/approval requirements, test IDs, latency/cost/resource measurements, and last verification date. Never copy competitor code merely to satisfy parity; implement outcomes through Anzu architecture and respect licenses.

Add a benchmark harness with deterministic fixtures and optional live-provider runs. Categories: chat/streaming, routing, memory/RAG, research, coding, computer use, workflows, goals, subagents, skills/plugins, voice/vision, mobile/remote, security/audit, recovery, model routing, observability and installation. Results are historical, hardware-labelled and never claim superiority without a reproducible measurement.

The Modules/Admin UI gets a Capability Lab showing Anzu coverage, failed tests, regressions and resource/cost trends. A scheduled research job may propose registry updates from public evidence, but changes require provenance and review.

## Acceptance criteria

- [ ] Machine-readable capability registry and schema exist.
- [ ] Every parity claim links to dated evidence and one or more executable Anzu tests.
- [ ] Benchmark records hardware, model/provider, version, latency, quality rubric, failures, cost and offline status.
- [ ] Fake/deterministic provider path works without keys; live runs are opt-in.
- [ ] Capability Lab exposes missing/partial/equivalent without unverified “better than” claims.
- [ ] CI detects regressions in implemented capabilities.
- [ ] Licenses/provenance are recorded for researched peers.

## Likely files

`backend/app/evals/`, `backend/app/capabilities/`, `frontend/src/`, `tests/evals/`, `docs/competitive/`.
