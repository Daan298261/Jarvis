# RFC-0116: TypeSafe Jev as an optional Jarvis decision tier

**Status:** implemented (superseded in part by [RFC-0171](0171-system-one-reflex-lane-jev-laya-priority.md) Reflex Lane)  
**Queue item:** (none — no new §58 checkbox; **not** in the Jarvis 1.4.0 cut. Implement is a named follow-up after CoS names it **and** TypeSafe public/early-access API is actually available + owner opt-in)  
**Author:** Jarvis Architect (Taco product intent 2026-09-17)  
**Date:** 2026-09-17

> **RFC-0171 availability update (2026-09-24):** TypeSafe Jev is **publicly usable**, not waitlist-only. Settings/status copy must not claim early-access-only. Cloud Jev still requires **owner opt-in** (`jev_optional` / entitled `jev_plus`), a **bound API key**, and a **real probe** before `connected` / `source: "jev"`. Local heuristics + optional local Laya remain default. “Notify when ready” is retained as a legacy interest flag only.

**Parent / index:** light pointer in [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) as a **post-1.4 optional accelerator** (does **not** reorder Taco ladder 0107–0109, does **not** join RFC-0111–0115 core, does **not** block 1.4.0). Architect ledger: [`JARVIS_MASTER_PLAN.md`](../../JARVIS_MASTER_PLAN.md) **§59 Decision Log** only.  
**Related (do not rewrite):** [RFC-0107](0107-obsidian-linked-memory-brain.md) per-turn search over installed/installable tools (backend landed `#295`; this RFC **ranks/selects** that working set when Jev is live). [RFC-0110](0110-chatgpt-style-approval-popup.md) Always/once/Deny modal — this RFC decides **whether** the popup is needed, not the chrome. [RFC-0115](0115-ornith-orchestrator-router-complexity.md) Ornith orchestrator-router + complexity tiers — local default; Jev may accelerate classify/escalate. [RFC-0075](0075-natural-speak-path-and-reply-latency.md) social vs technical speak class (`reply_class.py` hook). [RFC-0003](0003-runtime-model-profiles-routing.md) / [RFC-0048](0048-specialist-model-stack-routing.md) routing. [RFC-0012](0012-local-license-byo-inference.md) lease `features` + `/api/license/entitlements`. [RFC-0027](0027-semantic-action-firewall.md) / [RFC-0031](0031-reversibility-first-action-gates.md) / [RFC-0002](0002-agent-policy-interviews-autonomy.md) policy still owns execution. [RFC-0067](0067-owner-chat-hide-plan-chrome-and-launch-greeting.md) no PLAN chrome in ordinary chat. [RFC-0094](0094-settings-menu-information-architecture.md) / [RFC-0113](0113-admin-settings-submenu-1-4.md) Settings IA. [RFC-0079](0079-computer-use-permission-selector.md) existing network/computer-use catalog — reuse, do not invent LE/Red/Purple/ATO gates.

This PR is **the implement ticket**. Waitlist Settings, real TypeSafe probe, `has_feature(..., "decision.jev_plus")`, and named local fallback ship here. Live Jev account accuracy remains desktop sign-off. Do not ship a fake connected client.

## Problem

Jarvis control-path decisions — which tools this turn needs, whether the reply is social or technical, how complex the ask is, whether to escalate off Ornith, whether RFC-0110 must ask Always/once/Deny — are today **local heuristics + Ornith**. That is the correct default (local-first). It is also slower and less calibrated than a dedicated System One decision model when the owner **opts in** to one.

TypeSafe **Jev** (announced 2026-09-15) is that class of model: unstructured state in, typed probabilistic decisions out. Vendor claims: ~70–500 ms end-to-end, input **$0.042 / MTok**, output free, schema-guaranteed types, calibrated confidence. It is **not** a chat/TTS/coding model.

**Current reality (must be in the spec, not wished away):** Jev is **early access / waitlist**, not a general public release. Specs can land now. **Implement is gated** on (1) public or owner-granted early-access API availability **and** (2) owner opt-in. Until then, Settings shows waitlist/status + “notify when ready.” Shipping a fake Jev client, canned decisions, or a soft-fail local LLM that pretends to be Jev is forbidden.

Taco 2026-09-17 (source IG [TypeSafe Jev post](https://www.instagram.com/p/DdWTHR5Aqoi/) @albert.olgaard; primary vendor docs [Introducing System One Models & Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)): wire Jev as an **optional** Jarvis decision accelerator, with a free owner toggle **and** a paid monthly packaging path, without blocking 1.4.0.

## Decision

Jev is an **optional cloud decision tier** on the Jarvis control path. Local Ornith + heuristics remain the default. When Jev is **enabled, entitled (if Plus), and actually connected**, it classifies / routes / scores / branches those control decisions. When it is off, waitlisted, or unavailable, Jarvis uses the existing local path and **says so**.

### 1. What Jev is / is not

| Jev **is** | Jev **is not** |
| --- | --- |
| TypeSafe **System One** structured decision model | A chat, TTS, or coding replacement |
| Classify / route / score / branch with typed schema outputs | A replacement for Kokoro (RFC-0111/0092), owner-chat LLM, or Ornith **generation** / `answer_basic` |
| Calibrated confidence on every Choice/Score (Noul is a 0–1 probability) | The orchestrator. Jarvis stays the orchestration layer (RFC-0115) |
| Vendor-claimed ~70–500 ms; input ~$0.042/MTok; output free (vendor; subject to TypeSafe’s published pricing) | In the 1.4.0 cut. Post-1.4 **optional accelerator** |
| Complement to RFC-0107 tool search + RFC-0115 complexity router | A silent upgrade of local heuristics |

Public HTTP shape (vendor, 2026-09-17): `POST https://api.typesafe.ai/v1/systemone` with `Authorization: Bearer <API_KEY>`, `model: "jev-latest"`, a `state`, and a map of typed `questions` (`noul` | `choice` | `score`). Python SDK: `typesafe-sdk` (`TYPESAFE_API_KEY`). Waitlist / console: [typesafe.ai](https://typesafe.ai/). Docs: [docs.typesafe.ai](https://docs.typesafe.ai/introduction.md). Implement binds to the **live vendor contract** at implement time; do not freeze a guessed SDK if TypeSafe ships a different path — but do **not** invent a local fake in the meantime.

Choice cardinality is vendor-capped (255). Tool catalogs larger than that **must** be pre-filtered (RFC-0107 search) then optionally two-stage scored, matching TypeSafe’s own high-cardinality pattern. Do not send the full `NATIVE_TOOLS` list to Jev.

### 2. Availability gate — specs now, implement later, no fake-live

| Gate | Rule |
| --- | --- |
| Specs | This RFC may land while Jev is waitlist-only. |
| Implement | Named ticket **only** after TypeSafe public or early-access API is reachable **or** the ticket is explicitly the **honest waitlist Settings surface** (status + CTA, no decision client). The control-path client is **not** “done” until a real `POST /v1/systemone` (or successor) succeeds in the implementer’s environment **or** the tests use a recorded vendor fixture **labeled as a fixture**, never as production success. |
| Owner opt-in | Default **off**. Cloud Jev never auto-enables. |
| Fake-live | **Forbidden.** No stub client that returns `{connected: true}` without a probe. No local LLM JSON-mode labeled `source: "jev"`. No soft-fail that swallows 401/waitlist into a heuristic and attributes it to Jev. |

**If the owner enabled Jev (`jev_optional` / `jev_plus`) but the API is unavailable, waitlisted, 401, timeout, or overloaded:** surface a **clear error** and waitlist/connect CTA. The turn may continue on **explicit local fallback** (Ornith / RFC-0107 search / RFC-0075 heuristics / RFC-0115 rules). Audit log records `fallback_used: true` and `fallback_reason`. UI/status must **not** say Jev decided. Silent local-LLM-as-Jev is a fail.

### 3. Decision tier preference + paid packaging

Persist owner preference:

```text
decision_tier: local | jev_optional | jev_plus
```

Default: `local`.

| Value | Product | Entitlement | TypeSafe key |
| --- | --- | --- | --- |
| `local` | Local Ornith + heuristics. No TypeSafe calls. | None | None |
| `jev_optional` | Free/owner toggle **“Decision accelerator (Jev)”**. Owner BYO TypeSafe account/key; TypeSafe usage is the owner’s TypeSafe bill. | **Must not** require Plus. | Required to reach `connected` |
| `jev_plus` | Jarvis Plus / paid monthly packaging: include Jev + a TypeSafe usage quota **when billing exists**. | **Required.** Feature id `decision.jev_plus` | May be owner BYO **or** vendor-provisioned quota (when billing ships). Still a real key/session — not a stub. |

Until Stripe (or successor) ships: Plus may be **manual/config** via the **existing signed-lease path** (RFC-0012 `lease.payload.features`, refresh via `/api/license/refresh`) **or** a documented owner-config that `evaluate_cluster_entitlements()` / `has_feature()` still reads. That is “real wiring,” not a fake check.

**Required entitlement API shape** (implement must call this, not `if True`):

```python
from app.licensing.entitlements import has_feature, evaluate_cluster_entitlements
from app.licensing.lease import get_stored_lease

lease = get_stored_lease()
plus_ok = has_feature(lease, "decision.jev_plus")
# equivalent HTTP: GET /api/license/entitlements → entitlements.features
```

Forbidden: `plus_ok = True`, skipping `has_feature`, a comment that billing is unfinished, or a Settings checkbox that enables Plus **without** going through `has_feature` / `evaluate_cluster_entitlements`. A manual config flag is allowed **only** if it is merged into the object those functions read (so tests can assert `has_feature` is False without the flag and True with it).

`jev_plus` selected without the feature → Settings error/CTA (“Plus entitlement required”); control path does **not** call Jev; explicit local fallback + audit. Do not silently treat it as `jev_optional`.

Stripe/price amounts are **out of scope**. This RFC only names the packaging slot and the entitlement flag.

### 4. Waitlist / connection state machine

Persist and show:

```text
jev_availability: unavailable | waitlisted | connected | error
```

| State | Meaning | Settings | Control path |
| --- | --- | --- | --- |
| `unavailable` | No live API (waitlist-only product, no key, WAN blocked, TypeSafe unreachable and never configured). | Copy: Jev is early access. Link to TypeSafe waitlist. Button **Notify when ready** (local interest flag). **Do not** show a fake green “connected.” | Local only. If `decision_tier != local`, error/CTA as in §2. |
| `waitlisted` | Owner recorded interest (Notify when ready and/or confirmed they joined TypeSafe waitlist). Still no usable key/probe. | Same CTA; status = waitlisted, not connected. | Same as `unavailable`. |
| `connected` | Owner key/account bound **and** a **real probe** succeeded (list-models or a tiny `noul` against `api.typesafe.ai`, HTTP 200 with a typed answer). | Green/connected; last probe latency; model id (`jev-latest` or resolved version). | Jev calls allowed when tier is `jev_optional` or entitled `jev_plus`. |
| `error` | Key present or tier enabled, but probe/call failed (401, 422, 429, 529, timeout, TLS, WAN deny). | Red error + retry + waitlist/docs CTA. Never a spinner that eventually “succeeds” locally. | No Jev attribution. Explicit local fallback. |

**Notify when ready** stores `jev_notify_requested_at` locally (and may later hook vendor email if TypeSafe offers it). It does **not** flip `connected`.

**API key / account binding:** write-only field (same secrecy rules as inference API key — never echo on GET, never dump in logs/chat). Persist via the existing credential store pattern (`/api/license/inference-credentials` **or** a dedicated `provider: "typesafe"` record). Probe on save. 401 → `error`, not `connected`.

**WAN / privacy:** Jev is opt-in **cloud**. If existing network / internet permission (RFC-0079 catalog, `INTERNET_TOOLS` / owner WAN-off) would block outbound `api.typesafe.ai`, status is `unavailable` or `error` with that reason — **not** a new LE/Red/Purple gate. Local-first remains default.

### 5. Integration surfaces (when enabled + `connected`)

One System One request per turn **may** batch independent questions over a **small** `state` (latest user message, compact summary, candidate tool names from RFC-0107, proposed action class, current model/tier — **not** the full vault, catalog, persona pack, or hidden CoT). Jarvis **code** owns thresholds and composition (TypeSafe: atomic questions, compose in code).

Canonical question ids (names are stable for tests; instructions may be tuned):

| Id | Primitive | Feeds | Local fallback when Jev off/unavailable |
| --- | --- | --- | --- |
| `tool_select` | `choice` over RFC-0107 candidate names (plus `none`); optional `score` per candidate if cardinality requires a first pass | Per-turn tool working set (RFC-0107 `tool_retrieval` / `turn_working_set`). Pull **only** selected schemas into the chat LLM. | Existing search rank / `MAX_RETRIEVED_TOOLS` |
| `speak_class` | `choice` `social` \| `technical` | RFC-0075 `register_reply_classifier_hook` / `classify_reply_for_speech`. Hard technical shapes (fences, traceback, PLAN) still win locally — Jev must not force `social` over those. | Heuristics in `reply_class.py` |
| `complexity_tier` | `score` levels 1–4 matching RFC-0115 | RFC-0115 router `required_answer_tier`. Jev may **raise**. It must **almost never lower** a hard-rule tier. | Rules + Ornith envelope |
| `escalate` | `noul` “needs a stronger model than the current orchestrator should answer” | RFC-0115 `switch_model` / visible handoff. Confidence threshold in Jarvis code. | Ornith structured `action` + hard rules |
| `approval_needed` | `noul` “this step needs Always allow / Allow this time / Deny before it runs” | **Before** RFC-0110 popup. If policy/firewall already `REQUIRE_APPROVAL` / deterministic deny, those **win** — Jev cannot skip a required popup or override a deny. If Jev is low-confidence, **ask** (show popup) rather than auto-allow. | Existing RFC-0002 / 0027 / 0031 / 0110 gates |
| `tool_intent_risk` (optional) | `noul` or `score` jailbreak/guardrail on the **tool intent** | Additional signal into RFC-0027 semantic firewall. Never the sole allow. Never a new color-tier product gate. | Firewall as today |

**Will not:** replace Ornith as the loaded chat model; stuff Jev output into owner TTS; generate code or long answers with Jev (it cannot); call Jev on every token of a stream (once per turn / once per gated tool step is the budget); put decision dumps in ordinary chat.

### 6. Explicit local fallback

```text
decision_tier == local
    → never call TypeSafe
jev not connected / waitlisted / error / plus missing
    → local Ornith + heuristics; owner-visible error/CTA if they enabled Jev
Jev call timeout / 429 / 529 / low confidence
    → local fallback; audit records latency, HTTP status, confidence, fallback_reason
```

Fallback is **named** in the audit log (`source: "ornith" | "heuristics" | "rfc0107_search" | "rfc0115_rules" | "rfc0075_heuristics"`). It is never `source: "jev"` unless a real System One answer was used.

### 7. Settings / Daybreak IA

Primary home: **Models & Inference** (`models` / RFC-0113). Advanced is an acceptable overflow for the audit log only — the tier picker itself must be findable next to inference, not buried only under Advanced.

Controls:

- **Decision tier:** Local (default) / Jev (optional cloud) / Plus (paid entitlement).
- Toggle label: **Decision accelerator (Jev)** — off unless tier is `jev_optional` or `jev_plus`.
- Waitlist state + **Notify when ready** + link to TypeSafe waitlist.
- API key / account bind (write-only) when early access is granted.
- Plus status: reads `/api/license/entitlements` (`decision.jev_plus` in `features`). If missing: “Plus not entitled” + how to attach a lease feature until billing ships. If present: show tier, not a fake checkmark.
- **Decision audit log** (owner transparency): last N control-path decisions — question ids, answers, confidence, latency_ms, model id, `fallback_used`, `fallback_reason`. Settings / Advanced inspection. **Not** PLAN/ACCEPTANCE chrome in ordinary chat (RFC-0067). Debug “Show work” may link to the same records; default chat does not narrate them.

### 8. Observability events (not chat chrome)

```json
{
  "request_id": "...",
  "decision_tier": "jev_optional",
  "jev_availability": "connected",
  "source": "jev",
  "model": "jev-latest",
  "latency_ms": 140,
  "answers": {
    "speak_class": {"type": "choice", "choice": "social", "confidence": 0.88},
    "complexity_tier": {"type": "score", "score": 1.2, "confidence": 0.81},
    "escalate": {"type": "noul", "noul": 0.04},
    "approval_needed": {"type": "noul", "noul": 0.11}
  },
  "fallback_used": false,
  "plus_entitled": false
}
```

Events: `jev_probe`, `jev_decision`, `jev_fallback`, `jev_error`. Do not print these in the owner transcript.

**Will not:** ship fake-live Jev. Auto-enable cloud. Replace Kokoro / chat LLM / Ornith generation. Invent LE/Red/Purple/ATO gates. Block 1.4.0. Soft-fail `if True` Plus. Put TypeSafe trees in git. Use Jev as TTS or as the vault.

## Acceptance criteria

Specs-only in **this** PR:

- [x] Specs-only in this PR (no product code)
- [x] RFC status `accepted`; waitlist/early-access gate explicit; default `decision_tier: local`
- [x] `jev_availability` state machine specified; Notify when ready does not imply `connected`
- [x] No stub/soft-fail path that pretends Jev is live; enabled-but-unavailable → error/CTA, never silent local-LLM-as-Jev
- [x] Optional free toggle vs Plus packaging specified; Plus uses `has_feature(..., "decision.jev_plus")` / `GET /api/license/entitlements`, not `if True`
- [x] Integration points to RFC-0107 tool select, RFC-0075 speak class, RFC-0115 complexity/escalate, RFC-0110 approval-needed, optional tool-intent guardrail
- [x] Local fallback explicit and named; Jev cannot override deterministic deny or skip a required RFC-0110 popup
- [x] Settings IA: Models & Inference Decision tier + audit log (not chat PLAN chrome)
- [x] Cross-links + INTEGRATION_SPECS optional row + light §59 pointer; **not** in 1.4.0 cut
- [x] No invented LE/Red/Purple/ATO gates; no exploit recipes

Implement follow-up (this ticket; live account remains owner/desktop sign-off):

- [x] Probe is a real HTTP call to TypeSafe; 401/timeout → `error`
- [x] `decision_tier == local` never opens a TypeSafe socket
- [x] Enabled + not `connected` → owner-visible error/CTA; audit `fallback_used: true`; `source != "jev"`
- [x] `jev_plus` without `decision.jev_plus` on the evaluated entitlements object → no TypeSafe call
- [x] Tests: local default; waitlist UI not connected; probe failure; fixture vs live labeled; Plus false/true via `has_feature`; Jev rank does not dump full catalog; speak-class hook defers to hard technical heuristics; RFC-0115 hard tier not lowered; approval noul cannot skip required popup or weaken deny
- [x] `python3 -m pytest` (`tests/test_rfc0116_*.py`); `npm --prefix frontend run build` if Settings touched
- [ ] Live TypeSafe latency/accuracy is **desktop/owner sign-off** (cloud VM may use fixtures). Linux cloud cannot sign off a real Jev account.

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | new `backend/app/decision/jev_client.py` (HTTP/`typesafe-sdk` wrapper + probe); `backend/app/decision/tier.py` (preference + availability + fallback policy); wire `backend/app/licensing/entitlements.py` `has_feature(..., "decision.jev_plus")`; `backend/app/agent/tool_retrieval.py` / `turn_working_set.py` (RFC-0107 rank); `backend/app/tts/reply_class.py` hook; RFC-0115 router/complexity scorer; RFC-0110 approval pre-check beside `backend/app/policy/authorize.py` / `computer_permissions.py`; settings + credential persist; audit store |
| Frontend (implement PR only) | Settings Models & Inference Decision tier + waitlist/CTA + write-only key; Plus entitlement readout from `/api/license/entitlements`; audit log pane; **no** fake connected badge |
| Tests | `tests/test_rfc0116_*.py` (tier default, probe/error, fallback attribution, `has_feature` Plus, no catalog dump, speak/approval/complexity contracts) |
| Docs | this RFC; `INTEGRATION_SPECS.md` optional row; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. Jarvis 1.4.0 packages RFC-0111–0115. Replacing Ornith, Kokoro, or owner chat. Stripe/billing processor. Invented LE/Red/Purple/ATO gates. Exploit/PoC/jailbreak recipes (optional scoring is a **signal** only). Vendoring TypeSafe. Swarm / P4–P5. Persona merge (RFC-0104). Bulk Instagram RFC-0095–0104. Rewriting RFC-0107/0110/0115 contracts except to consume them.

## Notes

- Source: Taco 2026-09-17. IG https://www.instagram.com/p/DdWTHR5Aqoi/ (@albert.olgaard) → TypeSafe Jev. Vendor: https://typesafe.ai/blog/introducing-system-one-models-and-jev — early access / waitlist as of that date. Pricing and 70–500 ms are **vendor claims**, not Jarvis SLAs.
- Next free RFC after 0115 is **0116**.
- Post-1.4 optional / interesting accelerator: do **not** add this to `JARVIS_1.4_SPECS.md` or treat it as blocking 1.4.0 unless Taco later says so.
- Linux cloud can unit-test the waitlist state machine, entitlement wiring, and fallback attribution against fixtures. A live `jev-latest` account is owner/desktop sign-off.
- Implement launch: this RFC only; branch from `development`; pytest (+ frontend build if Settings); do not edit Architect spec docs beyond the named §59 tick; PR against `development`; do not merge other PRs.
