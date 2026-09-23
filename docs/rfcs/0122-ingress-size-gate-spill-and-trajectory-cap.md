# RFC-0122: Ingress size-gate, spill-to-store, and trajectory quality cap

**Status:** implemented  
**Queue item:** **Jarvis 1.4.1 priority bugfix** (no new §58 checkbox; implement is a named follow-up after CoS names it)  
**Author:** Jarvis Architect (Taco product direction 2026-09-18)  
**Date:** 2026-09-18

**Jarvis 1.4.1 priority bugfix.** Specs-only in this PR; product code is a **named follow-up**. Does **not** block RFC-0108 #309 land / 1.4.1 cut logistics.

**Related (do not rewrite):** [RFC-0114](0114-context-overflow-preflight-recovery.md) (`implemented`) — recovery **stays**; this RFC owns **what enters** the budget. [RFC-0117](0117-tiny-front-chat-responder.md) (`implemented`) — `front_responder` / chat-tier owns the size check and spoken “processing” ack while spill loads; **do not invent a third persona**. [RFC-0107](0107-obsidian-linked-memory-brain.md) — optional vault spill as a durable mirror; **do not replace 0107**. [RFC-0010](0010-cross-harness-trajectory-ingestion.md) (`implemented`) — trajectory ingest stays; this RFC adds **quality / budget gates** on prompt injection. [RFC-0115](0115-ornith-orchestrator-router-complexity.md) — complexity routing after ingress; **do not duplicate the full Ornith rewrite**. [RFC-0077](0077-local-lmstudio-discovery-and-hotswap-context.md) / [RFC-0073](0073-hud-model-hotswap-selector.md) — HUD/model hotswap must not re-stuff identity/catalog dumps. [RFC-0011](0011-memory-context-repositories-consolidation.md) — DB remains authoritative for structured facts and **turn blobs**. [RFC-0028](0028-off-context-agent-journal.md) — journal is episodic, not the owner brain.

This PR is **specs-only**. Full intent; **no stubs / soft-fail** (catching overflow and reprinting the same lessons block; a size-gate that stuffs the full paste into the small model; injecting “last message → none”; or dumping `NATIVE_TOOLS` for a ports question, is a fail).

## Problem

After upgrading, selecting Neural HUD → Humanoid HUD → switching to Qwen 27B, the owner saw “Recalling earlier similar tasks” / instructions pulled into context. A simple question failed:

```
You
what ports do i need for the companion app, for portforwarding in the router

Jarvis
Context capacity exceeded after compact/expand recovery: required_context=8229 tokens, active_context=16384, profile_cap=16384 (pressure=0.50).
…
Recalled similar earlier tasks
Lessons from similar earlier tasks on this machine. Reuse what worked and avoid repeating what failed: - what was my last message to you? -> completed using none - what was my last message to you? -> completed using none - what was my last message to you? -> completed using none
…
Context Retry / Context Compaction Started (loops)
…
Context capacity exceeded after compact/expand recovery: required_context=8229 tokens, active_context=16384, profile_cap=16384 (pressure=0.50).
```

Budget JSON in the UI: `prompt_tokens≈5134`, `tool_tokens≈1815`, `output_reserve=1024`, `system_reserve=256`, `required=8229`, `active=16384`, `pressure≈0.50` — yet recovery still ends in capacity exceeded. RFC-0114 ran (compact/expand/retry) and **still failed**, so the live prefill is not what `PromptBudget` thinks: junk injection, double-counting, tools not dropped, compact that does not shrink the real system prompt, and/or HUD/hotswap leftovers.

Ordinary short owner Q&A (companion router ports) must not die this way after HUD + model hotswap.

## Root-cause pointer (verified in repo)

### 1. Trajectory “lessons” always inject on class match

In `backend/app/agent/loop.py` (understand path, currently ~1054–1057):

```python
lessons = as_prompt_block(await relevant_trajectories(working.task_class, working.goal))
if lessons:
    system_prompt += "\n\n" + lessons
    await BUS.publish(..., "Recalled similar earlier tasks", ...)
```

Helpers in `backend/app/agent/trajectory.py`:

- `relevant_trajectories` loads the last 200 `Trajectory` rows, scores, keeps `score >= 2.0`, caps at `MAX_PROMPT_ENTRIES = 3`.
- `_score` awards **+2.0 for matching `task_class` alone**, plus +1.5 if `outcome == "completed"`. Keyword overlap is optional gravy.
- `as_prompt_block` formats every picked row as `- {goal} -> {outcome} using {tools}` with no quality filter.

A conversation-class task therefore injects **any** earlier conversation trajectory, including repeated `"what was my last message to you? -> completed using none"`. The owner paste is three identical lines — exactly `MAX_PROMPT_ENTRIES` of garbage. That is RFC-0010 data being used as **unfiltered system-prompt furniture**.

### 2. Compact does not shrink the system prompt that holds the junk

`compact_history` (`backend/app/agent/compaction.py`) keeps `head = cleaned[:2]` (system + first user) and only summarizes the middle. Trajectory lessons, skills, routing blocks, and the tools-essay `SYSTEM_PROMPT` (`backend/app/agent/prompts.py`) **stay in the prefill**. RFC-0114 recovery can loop (`context_retry` / `context_compaction_started`) while `required_context` never drops.

### 3. Budget says 50% pressure; llama.cpp still overflows

`PromptBudget` (`backend/app/inference/prompt_budget.py`) treats `pressure < 0.70` as fine and recovery success as `pressure < 0.85`. The observed `pressure=0.50` with `required_context=8229` on a 16K window **should** pass the estimator. Exhausted recovery still surfaces `context_capacity_error` because the **real** llama.cpp prefill (tokenizer + tool schemas + `n_keep` / hotswap KV + uncompacted system) is larger than the heuristic. RFC-0114 is working as specified on the numbers it can see; it cannot un-inject junk it does not remove.

`tool_tokens≈1815` on a ports question is also wrong product: `tool_exposure.schemas_for` still seeds class tools, always inserts `filesystem`, and always adds `request_tools` / `request_capability` (`backend/app/agent/tool_exposure.py`). RFC-0107 per-turn search exists (`tool_retrieval.py` / `turn_working_set.py`) but ordinary Q&A still ships schemas.

### 4. HUD + hotswap is the trigger, not a second root cause

Neural HUD → Humanoid HUD → Qwen 27B (RFC-0073 / RFC-0077) rebinds conversation context. That must not re-stuff persona packs, full catalogs, or prior HUD identity into the 27B window. This RFC gates **ingress + injection** after that switch; it does not rewrite the HUD.

## Research — SQLite / internal DB vs Obsidian vs hybrid

Taco asked for an explicit comparison. **Prefer hybrid. Do not replace RFC-0107.**

| Option | What it is | Fit for oversized **turn** payloads | Fit for durable owner knowledge | Verdict |
| --- | --- | --- | --- | --- |
| **A. SQLite / internal DB only** | Spill the blob into Jarvis DB (new `ingress_blobs` / ContextRepo / journal row). Large model reads by id, segmented or whole. | Excellent: transactional, provenance, not stuffed into any small-model window, works if Obsidian is unbound. | Weak as the owner-visible brain. RFC-0107 already forbids treating DB as the linked notebook. | Necessary for the hot path. Not sufficient as the only durable store. |
| **B. Obsidian note spill only** | Write the paste to a managed vault note (`_Temporal/Sessions/` or `Sources/`) and retrieve excerpts. | Fragile: vault unbound / Obsidian down must not block a chat turn; notes are the wrong place for ephemeral megabyte pastes; would fight “do not dump raw traces into the vault.” | Excellent for project/decision notes (RFC-0107). | Optional durable **mirror**, never the sole ingress buffer. |
| **C. Hybrid (default)** | **DB is authoritative for the turn blob** (size metadata, bytes/chunks, hash, conversation/task id). **Obsidian is an optional durable mirror** via the existing RFC-0107 managed-note write path when the vault is bound and the payload is worth keeping (owner paste that looks like a spec, log, or project doc — not every “hi”). Small model / `front_responder` reads **metadata + short preview from the DB**, never the full blob. Large model reads DB segments (or whole if it fits the working set). | Matches Taco’s “small model must not require stuffing the full blob into its own window.” | Leaves RFC-0107 as the operational brain. | **Choose this.** |

Rules for the hybrid:

1. Unbound vault, watch lag, or Obsidian process down → **turn still proceeds** from DB. Vault spill is best-effort.
2. Do not replace ContextRepo / RFC-0011 facts with Markdown.
3. Do not dump chain-of-thought, secrets, or raw tool traces into the vault (RFC-0107 already).
4. Episodic chatter stays in DB/journal (RFC-0028), not the brain.
5. Retrieval into the **major-model** prompt remains hop/excerpt-capped (RFC-0107 working set). Spill is so the blob **exists outside the window**, not so it all comes back in.

## Decision

Fix **what enters** the major-model context. Keep RFC-0114 compact/expand/retry. Reuse `front_responder` for the cheap check and spoken ack. Spill large ingress to the internal DB first. Quality-gate trajectory lessons. Cap tool schemas on ordinary Q&A.

**Will not:** rewrite RFC-0114 recovery policy; duplicate RFC-0115 Ornith; replace RFC-0107; invent a third persona; invent LE/Red/Purple/ATO gates; put exploit recipes in help or vault templates; block RFC-0108.

### 1. Ingress size-gate (small model, no third persona)

Every owner chat/task turn hits an **ingress gate** before the major model is given the turn payload.

**Lane:** reuse `front_responder` / chat-tier (`backend/app/agent/front_responder.py`, `runtime_role = front_responder`). Do **not** add a new named assistant.

**Two-stage check** (heuristic first, model second):

1. **Heuristic (no model):** character count, conservative token estimate (`estimate_text_tokens`), attachment/media size, paste-dump markers (multi-thousand-char paste, stack traces, JSON/XML/logs, multiple fenced blocks). Classify `small` vs `big` with a hard byte/token ceiling so a 50 KB paste never waits on a model to notice.
2. **Small-model check (preferred path for ambiguous size/complexity):** `front_responder` (tools disabled, thinking disabled, tiny output cap) sees **only**:
   - size metadata from the store (bytes, estimated tokens, hash, MIME, chunk count);
   - a **short preview** (first/last N chars, capped — implementer picks a small hard cap, on the order of a few hundred tokens);
   - the latest user ask truncated the same way.
   It must **not** receive the full blob in its own window. Preferred: persist first, then classify from the store. If the heuristic already says `big`, skip the model check and spill.

Output (structured, not chat furniture):

```json
{
  "size_class": "small | big",
  "needs_tools": false,
  "complexity_hint": 1,
  "front_action": "final_basic | ack_continue | handoff_notice"
}
```

`complexity_hint` is a **hint for RFC-0115**, not a replacement. The gate may raise a turn toward “needs tools / not `final_basic`”; it must not lower a hard RFC-0115 tier.

### 2. Ingress flow

```text
owner types (or pastes / attaches)
  -> persist payload to internal DB (always for big; cheap for small as the conversation row already does)
  -> size check (heuristic +/- front_responder on metadata)
       small: process immediately
               front lane as today (final_basic may complete; else ack + large)
               large / worker path as today, with trajectory + tool caps below
       big:   DB row is the source of truth for this turn's blob
              optional RFC-0107 managed-note spill (durable mirror)
              front_responder TTS/speaks that it is processing (ack_continue / handoff_notice)
              major model reads from DB (segmented windows, or whole only if PromptBudget says it fits
              after identity + this-ask working set + tool cap)
```

Spoken ack must be safe RFC-0117 speech: no “done,” no invented port numbers, no fake router success. Example register:

```text
That's a large paste. I've stored it and I'm working through it.
```

For the **ports question** (short, `small`): skip spill-of-blob; do not inject garbage lessons; do not ship 1815 tool-schema tokens; answer or retrieve docs-first (RFC-0060) like `ANDROID_CLIENT.md` / companion gateway **4781** vs portal **4780**.

### 3. Spill store (DB authoritative)

Implement a first-class **ingress blob** (name is implementer's; suggested `ingress_blobs` in SQLite via existing session):

| Field | Role |
| --- | --- |
| `id`, `conversation_id`, `task_id` | Provenance |
| `byte_size`, `token_estimate`, `content_hash` | Size-gate metadata |
| `chunk_index` / body or external path under data dir | Bytes; do **not** inline megabytes into the prompt |
| `status` | `stored` / `spilled_to_vault` / `consumed` |

Large-model read API: `read_ingress(id, offset, limit)` or search-over-chunks. The working set gets **pointers + the segments this ask needs**, never the unused remainder.

Optional vault spill: RFC-0107 `jarvis_managed` note with frontmatter pointing at the blob id. If the vault is bound and the payload looks durable (spec, log the owner asked to keep, project paste), write it. If not, skip. **DB still wins for the live turn.**

### 4. Trajectory lessons — quality gate + budget cap

Change `relevant_trajectories` / `as_prompt_block` so garbage is **never** injected.

Required gates (all must pass):

1. **Relevance:** matching `task_class` **alone is not enough**. Require real overlap (goal keywords / embedding-optional later) **above** a threshold that ignores the class bonus. A completed `conversation` row with zero overlap with “companion ports” must score **out**.
2. **Quality / denylist:** drop goals that match low-value loops, including:
   - “what was my last message” / “what did I just say” / empty-echo trivia;
   - `tools == none` **and** no recovery/verification text (no lesson);
   - identical goal repeated (dedupe before cap);
   - secrets / credential-shaped text (keep RFC-0010 redaction).
3. **Token budget:** the lessons block is capped (implementer picks a small hard cap, e.g. ≤200 tokens / ≤2 distinct high-score rows). If it does not fit the remaining RFC-0114 budget after identity + user ask, **drop it entirely**.
4. **Publish:** `Recalled similar earlier tasks` only when a **gated** block is actually appended. Do not publish the event for denylisted rows.

RFC-0010 ingest/schema is unchanged. This is **injection quality**, not a new trajectory format.

### 5. Tool schema stuffing on ordinary Q&A

Align with RFC-0107 §7 (per-ask search; no full catalog).

For **plain conversation / short factual Q&A** (ports, weather, “what time,” docs-first lookup) when `needs_tools` is false:

- `schemas_for` / `exposure_schemas_for` return **empty tools** (or only `request_capability` if the model must opt in — not a filesystem dump).
- Do **not** always-insert `filesystem`.
- Do **not** serialize `NATIVE_TOOLS` / MCP listings “just in case.”
- `tool_tokens` on the ports question must be ~0, not ~1815.

When tools **are** needed, search then pull a **capped** matched set (existing `MAX_RETRIEVED_TOOLS`). `fit_tools_to_context` remains an emergency clamp, not the design.

`SYSTEM_PROMPT`’s tools essay must not force the 27B to “prefer tools over guessing” on a ports question. Implementer: conversation lane uses the compact identity + docs-first path (RFC-0107 working set / RFC-0060), not the full lifecycle essay. Do not rewrite persona packs here.

### 6. RFC-0114 recovery stays; compact must be able to drop injection

Keep `PromptBudget`, `prepare_inference`, compact/expand/retry ≤2, overflow events.

Additionally, so recovery can actually shrink:

- Stop injecting junk (sections 4–5) — primary fix.
- Compact/recovery **may drop** trajectory lessons, unused skill blocks, and class-wide tool schemas from the system head. Compact must **not** drop the current user ask or compact identity/tone.
- After HUD/hotswap, do not leave previous HUD persona / catalog in `n_keep` (RFC-0077 short identity working set). This RFC does not re-implement hotswap; it forbids re-injection on the next turn.

If estimator `pressure≈0.50` but llama.cpp still 400s, treat that as **undercount** (tokenizer / tools / n_keep): drop tools, drop lessons, re-read spill segments — do not loop compact on an unchanged system prompt. RFC-0115 escalation remains the hook when the **true** required context cannot fit.

### 7. Observability

Events (reuse names where they exist):

```text
ingress_size_classified
ingress_spill_stored
ingress_spill_vault_optional
trajectory_lessons_dropped
trajectory_lessons_injected
tool_schemas_empty_qa
```

Payloads: `size_class`, `byte_size`, `token_estimate`, `lessons_dropped_reason`, `tool_count`, `required_context`, `active_context`, `pressure`. Do not dump the blob into the event bus.

## Acceptance criteria

Specs-only in **this** PR:

- [x] RFC accepted, marked **Jarvis 1.4.1 priority bugfix**
- [x] Research section compares DB vs Obsidian vs hybrid; hybrid default; RFC-0107 not replaced
- [x] Light §59 Decision Log entry
- [x] Cross-links to RFC-0114, RFC-0117, RFC-0107, RFC-0010, RFC-0115

Implement follow-up (named ticket; full intent, no stubs):

- [ ] Ordinary short owner Q&A (e.g. companion router ports) **must not** end in `Context capacity exceeded after compact/expand recovery` after Neural HUD → Humanoid HUD → Qwen 27B hotswap
- [ ] Trajectory lessons injection is **budget-capped** and **quality-gated**; garbage loops like “last message → none” are **never** injected; `Recalled similar earlier tasks` is not published for them
- [ ] Ingress size-gate exists: **small** → process immediately (front and/or large as today); **big** → write to **internal DB first**, `front_responder` speaks processing, large model **reads from the store** (segment or whole)
- [ ] Small-model / front lane size check does **not** require stuffing the full blob into its window (metadata + short preview from the store)
- [ ] Optional Obsidian vault spill is a durable mirror only; unbound vault does not block the turn
- [ ] Tool schema stuffing on simple Q&A is reduced: on-demand search / **empty tools** when no tools needed; no full `NATIVE_TOOLS` dump for a ports question (`tool_tokens≈0`)
- [ ] RFC-0114 recovery remains; compact can drop lessons/tool dumps; no infinite compact loop on unchanged system junk
- [ ] No exploit recipes; no invented LE/Red/Purple/ATO gates
- [ ] `python3 -m pytest` (`tests/test_rfc0122_*.py` plus existing trajectory / prompt-budget / front-responder tests). Live HUD + 27B hotswap + llama.cpp overflow is **Windows desktop sign-off** (cloud VMs cannot sign this off)

## Likely files

| Area | Paths |
| --- | --- |
| Ingress gate | new `backend/app/agent/ingress_gate.py` (heuristic + front_responder classify); `backend/app/agent/front_responder.py`; `backend/app/agent/loop.py` understand path |
| Spill store | `backend/app/db/models.py` + session; `backend/app/memory/db_layer.py` / `store.py` or new `backend/app/memory/ingress_spill.py`; optional `backend/app/memory/obsidian_vault.py` managed-note write |
| Trajectory quality | `backend/app/agent/trajectory.py` (`_score`, `relevant_trajectories`, `as_prompt_block`); `backend/app/agent/loop.py` ~1054–1057 |
| Tool cap / working set | `backend/app/agent/tool_exposure.py`, `tool_retrieval.py`, `turn_working_set.py`; conversation vs lifecycle `prompts.py` only as needed for Q&A |
| Budget / compact | `backend/app/inference/prompt_budget.py`; `backend/app/agent/compaction.py` (drop injection from system head); `backend/app/inference/manager.py` undercount path |
| Tests | `tests/test_rfc0122_*.py` — denylist “last message”; ports Q&A empty tools; size-gate does not pass full blob to front lane; spill then segmented read; compact drops lessons |
| Docs | this RFC; `JARVIS_MASTER_PLAN.md` §59 only; one-line RFC-0107 Related / `INTEGRATION_SPECS.md` pointer |

## Out of scope

Product implementation in **this** PR. RFC-0114 recovery rewrite. Full RFC-0115 Ornith implement. RFC-0107 embedded Obsidian UI. RFC-0108 phone offline (do not block). RFC-0120/0121. HUD chrome rewrite. Persona merge. Invented authorization gates. Exploit/PoC/payload documentation. Swarm P3. New §58 checkbox.

## Notes

- Taco 2026-09-18: 1.4.1 product priority is this overflow / junk-injection path; specs first, implement named follow-up.
- Companion ports themselves are documented in `ANDROID_CLIENT.md` (Leader `bind_port` default 4780; companion gateway typically 4781; do not forward llama-server 8088). This RFC does not change those numbers; it makes the question **answerable**.
- Linux cloud: unit-test gate, denylist, empty tools, spill metadata, compact-drops-lessons. Live 27B + HUD hotswap remains desktop sign-off.
- Implement launch: this RFC only; branch from `development`; pytest; do not edit Architect spec docs in the implement PR (this specs PR is the §59 exception); PR against `development`; do not merge other PRs.

## Implementation note

Landed on `development` via #318 @ `12827aef` (ingress size-gate, spill-to-store, trajectory quality cap). Live HUD + 27B overflow remains Windows desktop sign-off. Acceptance checkboxes left open for that sign-off.
