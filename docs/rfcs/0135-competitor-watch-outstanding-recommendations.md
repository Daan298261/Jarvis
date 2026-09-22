# RFC-0135: Outstanding competitor-watch recommendations

**Status:** accepted
**Queue item:** Competitor-watch audit — close unrepresented recommendations
**Author:** Codex repository audit
**Date:** 2026-09-22

## Problem

The referenced Jarvis competitor-watch conversation contains several recommendations that were reported as written, but the current GitHub branches do not all contain those changes. Current `development` already covers most of the conversation through existing RFCs, including policy/autonomy, runtime manifests, trajectories and self-improvement, durable execution, PAIR, external sandboxing, managed harnesses, backup bundles, module installation/catalog behavior, and Supermemory. Two recommendations remain unrepresented on the current branch: a first-class model-sharded inference runtime and decision-level failure learning.

## Audit decision

This RFC records only the two gaps that are not duplicates of current Git content.

### 1. Model-sharded inference runtime

RFC-0030 explicitly limits PAIR to one-request-to-one-node routing and leaves model/tensor parallelism for a separate backend. The conversation's claimed RFC-0128 commit (`26cae2e63085393b0c810fdda6d05a3b0a5f7427`) is present only as a dangling local Git object; it is not reachable from the current `main` or `development` refs, and current RFC-0128 is the unrelated progressive-answer/background-verification RFC.

Jarvis should add a provider-neutral distributed inference contract with these placement modes:

- `SINGLE_NODE` — one model invocation on one node;
- `REQUEST_ROUTED` — independent requests routed across nodes, including PAIR;
- `MODEL_SHARDED` — one model invocation executed across multiple participants.

The contract must:

- reserve all participants atomically before execution and release the lease on every terminal path;
- validate model, quantization, runtime, topology, transport, memory and participant health before admission;
- expose participant roles, topology, runtime identity, version/digest, transport and measured capability in the Runtime Manifest;
- define timeout, participant-loss, partial-result, cancellation, retry and recovery behavior without silently duplicating an uncertain external effect;
- require end-to-end benchmarks for correctness, first useful response, latency, throughput, load time, memory and failure recovery;
- allow `AUTO` to select model sharding only after the exact model/runtime/topology combination is validated, with a safe request-routed or single-node fallback;
- show the selected topology and degraded state to the operator;
- integrate maintained providers such as TensorRT Edge-LLM behind the Jarvis contract rather than reimplementing MPI/NCCL/tensor-parallel execution;
- never describe arbitrary networked machines as pooled VRAM. Combined capacity is valid only for an explicitly validated distributed runtime.

### 2. Decision-level failure learning

RFC-0024 governs candidate skill creation and promotion, but it does not isolate the particular decision that caused a failed tool call, user correction or avoidable recovery. The conversation's proposed RFC-0129 was not written to the current repository.

Add a durable `DecisionFailureRecord` linked to the immutable trajectory and containing:

- agent/profile, task/run and decision identifiers;
- tool or model invocation, normalized error class and observable pre-decision context;
- outcome, correction/recovery, suspected root-cause decision and confidence;
- attribution class: model judgment, tool/schema, infrastructure/outage, authorization/policy, ambiguous instruction or unknown;
- provenance, verifier evidence, promotion history, expiry/decay and rollback state.

Use this lifecycle:

`CAPTURED -> ATTRIBUTED -> CORRECTION_PROPOSED -> VERIFIED -> PROMOTED | REJECTED`

The implementation must:

- preserve successful steps and failed trajectories as immutable evidence;
- classify deterministic tool/schema/authorization failures before asking a model to infer blame;
- ground correction proposals only in information available before the failed decision, preventing hindsight learning;
- exclude secrets and unnecessary personal data, with redaction and retention controls;
- require multiple verifier signals for ambiguous attribution and retain disagreement;
- promote first to advisory memory, tool-use guidance and regression fixtures, not autonomous policy or permission changes;
- replay representative cases and prove the promoted correction reduces its target failure without regressing successful behavior;
- support confidence decay, quarantine, revoke and rollback with operator inspection;
- distinguish model errors from outages, unavailable tools, denied authority and underspecified user intent.

This layer feeds RFC-0024's governed skill lifecycle; it does not replace that lifecycle or permit an agent to grant itself authority.

## Acceptance criteria

- [ ] Add a provider-neutral `MODEL_SHARDED` runtime contract without changing PAIR's `REQUEST_ROUTED` semantics.
- [ ] Add atomic multi-node leases, topology/participant health checks, admission validation, cancellation, timeout, participant-loss and recovery tests.
- [ ] Add Runtime Manifest fields for distributed topology, provider/runtime version or digest, transport and measured capability.
- [ ] Add `AUTO` gating and fallback tests proving unvalidated model/runtime/topology combinations cannot consume combined capacity.
- [ ] Add operator-visible topology and degraded-state behavior.
- [ ] Add persistent `DecisionFailureRecord` storage with immutable trajectory linkage and secret/PII filtering.
- [ ] Add deterministic attribution for tool/schema, authorization and infrastructure failures before model attribution.
- [ ] Add the correction lifecycle, verifier evidence, confidence decay, revoke and rollback behavior.
- [ ] Add replay/regression fixtures proving promoted corrections improve the targeted failure without regressing successful cases.
- [ ] Add tests proving promotion cannot directly alter permissions or autonomous policy.
- [ ] Run `python3 -m pytest` and `git diff --check`.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/`, `backend/app/swarm/`, `backend/app/agent/`, `backend/app/trajectories/`, `backend/app/memory/` |
| Runtime manifests | Existing RFC-0018 manifest/catalog and inference-backend contracts |
| Tests | `tests/test_rfc0135_*.py`, runtime failure/replay fixtures |
| Docs | This RFC only; do not rewrite Architect-owned spec documents |

## Out of scope

Reimplementing TensorRT Edge-LLM, MPI or NCCL; claiming arbitrary RTX machines can shard a model; replacing RFC-0030 PAIR routing; foundation-model training or fine-tuning; autonomous permission escalation; rewriting RFC-0024; and duplicating module install/catalog work already covered by RFC-0090, RFC-0095, RFC-0105 and RFC-0132.

## Existing coverage verified during audit

- Guided autonomy, reversibility and policy boundaries: RFC-0002.
- Hardware/runtime manifests and vendor-optimized runtime candidates: RFC-0018.
- Trajectory, memory/consolidation, compact harness/advisor and persistence/proactivity controls: RFC-0010, RFC-0011, RFC-0013 and RFC-0014.
- Durable goals, channels, execution/verifier observability and governed self-improvement: RFC-0016, RFC-0025, RFC-0026 and RFC-0024.
- Durable execution, selectable request-routing backends and external policy sandboxing: RFC-0029, RFC-0030 and RFC-0031.
- Managed agent harnesses and portable backup/restore: RFC-0073 and RFC-0074.
- Optional worker installation, module catalog/download, cybersecurity module lifecycle and Supermemory sidecar installation: RFC-0090, RFC-0095, RFC-0105 and RFC-0132.

No new RFC is created for those covered items.

## Notes

- The current repository's RFC-0128 is `progressive-answer-background-verify`, not model sharding.
- The current repository's RFC-0129 is `projects-chats-portal-implement`, not decision-level failure learning.
- Conversation provenance: NVIDIA TensorRT Edge-LLM multi-node tensor parallelism and Perplexity decision-level mistake learning, as reviewed in the referenced ChatGPT conversation.
- Provider and model claims require live provider documentation and runtime benchmarks before implementation is marked complete.
