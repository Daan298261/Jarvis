# RFC-0171: Priority System-One Reflex Lane — Jev + local Laya

**Status:** implemented — P0 / priority accelerator  
**Date:** 2026-09-24  
**Prior status (main @ `ac18fb32`, #406):** accepted — P0 / priority accelerator. The spec body matches that draft; the ledger below is the development implementation record.  
**Implemented:** #409 @ `f7bf66a943b4d365f6a5f6084d8d774f76358f4b` (`backend/app/decision/`, `tests/system_one/`).  
**Residuals (do not block implemented):** live TypeSafe/Laya GPU soak + latency budgets; production Laya sha256 fills (empty pin still fail-closed / refuses install); release-gate speed claims need reproducible Desktop evidence.  
**Supersedes/extends:** RFC-0116 implementation assumptions; does not remove local fallback or policy authority.

## Problem

Anzu still sends too many bounded decisions through generative LLM paths. Current System-One projects show that routing, action selection, scoring and guardrails can execute in tens to hundreds of milliseconds when outputs are constrained. The perceived speed improvement is architectural: do not generate language when the program only needs a decision.

Current evidence (2026-09-24): TypeSafe Jev exposes typed Choice/Score/Noul decisions and is now publicly usable rather than merely waitlisted. Browser Use's `jev-ultrafast` uses one decision request for operation + target, with a small text model only when text must be generated. Its controlled Google Flights comparison reports median 7.092 s vs 9.450 s for the frozen original runtime, 17 vs 22 TypeSafe requests, and 101 vs 1,092 browser-protocol calls; this is a small 3-pair comparison, not a universal benchmark. Laya is an Apache-2.0 open System-One implementation using non-autoregressive encoder checkpoints; its published T4 measurements are ~32.8 ms for one multilingual decision and ~72.3 ms for 10 batched questions. Independent sysone-bench results show neither Jev nor Laya dominates every decision suite, so Anzu must benchmark and route between them rather than assume one winner.

## Decision

Promote System One from optional integration to a **P0 Reflex Lane** for bounded decisions. It is additive to the normal LLM lane:

```
request/event
  -> deterministic hard rules
  -> Reflex Lane (typed bounded decisions)
  -> ordinary code executes/routs
  -> generative model only when language/reasoning is actually required
```

Providers:

1. **Laya local** — preferred zero-cloud low-latency provider when installed and benchmark-qualified for the decision class. Managed optional model/module; pinned Apache-2.0 source/checkpoints, hashes, isolated runtime, loopback-only service or in-process worker. Preload hot checkpoint(s) when resource governor permits; never reload per request.
2. **Jev cloud** — TypeSafe provider for decision classes where measured quality/reliability or hardware pressure favors it. Owner opt-in and network/privacy policy still apply. Update RFC-0116's obsolete waitlist assumptions to current public availability, but keep real probe, explicit attribution and fallback.
3. **Rules** — exact code remains first for permissions, arithmetic, invariants and known safety requirements.
4. **Generative fallback** — only when the decision cannot be represented safely as bounded typed questions or confidence/quality is inadequate.

Expose one provider-neutral API: `decide(state, questions, decision_class, deadline_ms, privacy)`. Questions use typed `choice`, `score` and probability/boolean semantics. Multiple independent judgments over the same state are batched into one forward/API call whenever supported.

### Hot-path decision classes

Immediately target: persona/model routing; tool shortlist/selection; complexity/escalation; memory/evidence relevance; workflow branch; retry/stop; verifier/critic scoring; notification relevance; browser/computer operation + target selection; artifact/document classification; source prioritization; safe deterministic risk *signals* (never final permission authority).

Do **not** use Reflex Lane for open-ended writing, long plans, coding generation, explanations, summaries, exact calculations or policy authorization.

### Latency architecture

- Keep local Laya worker/model warm; health and warm-state are visible.
- Batch questions sharing the same state.
- Cache only pure/idempotent decisions keyed by provider/version/state/question hash and short TTL.
- Run independent Reflex decisions concurrently.
- Use compact state projections instead of full transcripts/tool catalogs.
- Hard deadline: missing the deadline falls back without blocking the owner-chat fast path.
- Record queue, serialization, network, inference and total latency separately.
- Avoid subprocess/model startup per decision.

### Quality routing

RFC-0141 Arena/Quartermaster owns per-decision-class provider selection. Start with explicit profiles, then use measured EWMA quality/latency. Jev and Laya are evaluated on byte-identical Anzu fixtures. High-cardinality choice spaces must shortlist first; Laya's own published results identify this as a weaker zero-shot case. Confidence is a signal, not proof. Calibrate thresholds per decision class and provider/version.

### Browser/computer fast loop

Adopt the transferable `jev-ultrafast` pattern without copying its application wholesale: build an atomic semantic snapshot of currently actionable controls; assign stable ephemeral indexes; ask one Reflex call for operation + target; resolve the target back to the observed native/DOM/accessibility node; recheck freshness/occlusion/focus; execute; verify postcondition. Generate text only for TYPE_TEXT or genuinely generative operations. Model output must never become arbitrary selectors, coordinates, shell commands or executable JavaScript.

## Acceptance criteria

- [x] Provider-neutral System-One API with Jev, Laya and deterministic/fallback adapters.
- [x] RFC-0116 availability UI/docs updated from waitlist-era assumptions; Jev still requires real probe and explicit cloud opt-in.
- [x] Managed Laya install pins source/checkpoint versions + hashes and validates Apache-2.0 provenance.
- [x] Laya service is loopback-only/in-process, authenticated if networked, and kept warm when enabled.
- [x] At least routing, tool selection, memory relevance and browser operation/target use typed Reflex decisions.
- [x] Same-state questions batch into one call; no repeated LLM calls for independent bounded judgments.
- [x] Per-class byte-identical Jev/Laya/rules/generative-fallback benchmark fixtures exist.
- [x] Quartermaster selects provider from measured quality + p50/p95 latency + privacy + cost + hardware fit.
- [x] Hard policy/approval rules cannot be weakened by Jev/Laya output.
- [x] Reflex timeout/failure never strands the turn; fallback source is explicit and audited.
- [x] Control Room reports p50/p95/p99 end-to-end and inference-only latency, throughput, confidence/calibration, fallback rate and quality per decision class/provider/version.
- [x] Browser fast loop uses semantic/native node identity, freshness and postcondition verification — *landed via sibling RFC-0172 #408; D2 tip wire follow-up in flight*
- [ ] Release gate prevents claiming a speed improvement without reproducible hardware/model/provider evidence — *open residual: Desktop/GPU sign-off; does not block code implemented*

## Performance targets

Targets are Anzu engineering budgets, not claims about providers: local Reflex p50 <= 50 ms and p95 <= 100 ms on qualified GPU hardware for short single/batched decisions after warmup; cloud Jev p50 <= 350 ms where network conditions permit; router decision overhead <= 10 ms excluding provider inference; no hot-path model cold load. If a machine cannot meet the local budget, Quartermaster may choose rules/Jev/another qualified provider under owner policy.

## Likely files

`backend/app/decision/` (provider-neutral API, Jev adapter, Laya adapter, batching/cache), model/module lifecycle, RFC-0141 Arena, RFC-0168 governor, tool retrieval, memory retrieval, browser/computer runtime, Control Room, Settings Models & Inference, `tests/system_one/`.

## Sources / evidence snapshot

- TypeSafe: https://typesafe.ai/ and https://typesafe.ai/blog/introducing-system-one-models-and-jev
- Browser Use Jev Ultrafast: https://github.com/browser-use/jev-ultrafast and `docs/performance.md`
- Laya: https://github.com/NandhaKishorM/laya
- Independent comparison: https://github.com/instax-dutta/sysone-bench

Evidence is dated 2026-09-24 and must be refreshed by the RFC-0137 Capability Lab (`0137-capability-parity-matrix-and-continuous-benchmark.md`, the #406 parity draft now on this branch) before comparative claims are surfaced. That draft is a different document from `0137-persona-presence-shape-and-voice-binding.md`.
