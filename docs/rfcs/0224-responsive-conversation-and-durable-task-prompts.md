# RFC-0224: Responsive conversation and durable task prompts

**Status:** accepted
**Date:** 2026-10-17

## Problem

The owner observed a 21-second model-status read and expects a small conversational model plus bounded Laya/Jev decisions. The installed configuration instead selects the 2B CPU front and disables Laya. Model-status cache misses can wait for resource probes. Large tasks have durable tool executions and an optional parsed plan, but do not require a committed plan or separate bounded prompts for each deliverable and review phase.

## Decision

Keep status reads independent of slow refreshes and expose honest pending/stale health. Offer the llama.cpp-maintained Qwen3.5 0.8B conversational profile alongside existing fronts; preserve explicit model choices and never represent decision encoders as conversational generators. Measure front and worker latency independently. Use existing bounded decision arbitration and optional local Laya, without requiring hosted credentials.

For large managed requests, generate and commit a plan before executing tools. Store ordered prompt steps, status and compact results in SQLite, retain the complete request, and execute one step at a time using a fresh bounded conversation plus exact-source retrieval and previous deliverable summaries. Append bugfixing, fact-checking and quality-control phases by default. Provide a persistent setting to disable these extra phases without disabling existing tool permissions or verification. A failed/cancelled phase cannot be marked complete; restart/continuation must not silently discard remaining steps. Expose the plan and steps through task detail.

## Acceptance

- Slow or absent status probes never delay ordinary cached status readers; forced probes remain explicit and stale results cannot claim current health.
- Front 0.8B can be selected and installed; 2B/4B remain available and explicit saved choices persist.
- A large task cannot execute its first tool before its plan and prompts are committed. Subsequent prompts retain the original constraints and bounded predecessor outcomes, not accumulated full transcripts.
- All ordered work and enabled review phases run before final completion, with durable outcomes and visible blockers. Existing authorization, cancellation and effect reconciliation remain enforced.
- Review toggle defaults on and is exposed in settings. Small conversations incur no workflow planner calls.
- Tests exercise ordering, persistence, resume, failure, context bounds and disabled review stages. Focused Python checks, frontend build/lint and measured live latency are reported separately from installed delivery.

## Scope

Inference status monitor/front profiles, existing managed agent loop, durable task workflow storage/API, task and model settings, targeted tests. RFC-0211 Away Mode, automatic development publication and unrelated scheduler UI remain separate unfinished work.
