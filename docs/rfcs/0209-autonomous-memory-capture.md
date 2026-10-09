# RFC-0209: Autonomous memory capture

**Status:** accepted  
**Queue item:** (none — no §58 checkbox; Architect may add one after this spec merges)  
**Author:** Chief of Staff (Taco-authorized spec exception: specs may be written in parallel with the Architect)  
**Date:** 2026-10-09

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) — one assistant, local-first, persistent memory with provenance, routine continuity without a prompt, meaningful control when the content is consequential, honest about what was stored.  
**Builds on (does not edit):** [0206](0206-jev-laya-every-turn-arbitration.md).  
**Store path already on `development`:** PR [#574](https://github.com/Daan298261/Jarvis/pull/574) (`owner_facts.py`, owner context repo, `Memory/owner-facts.md`).  
**Numbering:** **0207** and **0208** are reserved for the Jarvis Architect's reverse-engineering specs. This ticket is **0209**. Do not take 0207 or 0208.  
**Sequencing:** implement after RFC-0206 has landed on `development`, and before RFC-0205.

Product name in owner-facing answers is **ANZU Superassistant**. The engineering tree stays Jarvis.

Taco's order (2026-10-09 02:45): ANZU remembers things of interest by itself, without being told "remember this", and Jev/Laya make the store / don't-store decision.

## Problem

ANZU stores an owner fact only when the utterance matches a remember-phrase. Everything else is discarded, including preferences, people, projects, and decisions the owner just stated in ordinary conversation.

Verified on `development` at `4fc4619`:

1. **Capture is a keyword gate.** `is_memory_store_request` in `backend/app/memory/owner_facts.py` matches `remember`, `don't forget`, `note that`, and `keep in mind`. `AgentLoop._ensure_owner_memory` (`backend/app/agent/loop.py`) calls `remember_owner_fact` only when that regex hits. A sentence such as "I prefer oat milk in coffee" never enters the store. Recall (`recall_owner_facts`) can only return what that gate wrote.

2. **There is no capture decision.** `REFLEX_DECISION_CLASSES` in `backend/app/decision/types.py` includes `memory_relevance`. That class only scores retrieval excerpts (`score_memory_relevance` in `backend/app/decision/surfaces.py`, used by `_reflex_rerank_memory_hits` in `backend/app/memory/obsidian_vault.py`). It does not decide whether to write. `decide_owner_turn` from RFC-0206 is the every-turn routing call and is not on this tree yet (`backend/app/decision/owner_turn.py` is absent at `4fc4619`). Owner chat does not ask Jev or Laya what to keep.

3. **The files that look like a post-turn memory job are a different job.** `backend/app/memory/scheduler.py` exports `rank_nodes_for_consolidation`. It scores swarm nodes (idle / junior preferred). It has no queue and no owner-turn hook. `backend/app/memory/consolidation.py` `consolidate_agent` promotes verified trajectories into `lessons`, `skills`, and `procedures` via `find_duplicate` and `add_entry`. The HTTP entry is `POST /api/context-repo/consolidate` and `GET /api/context-repo/consolidate/schedule-preference` (`backend/app/api/context_repo.py`). Neither function reads owner chat. Calling them to "capture a preference" would write task-recovery text into the owner repo and would still not see the utterance.

4. **The #574 writer is the one store, and it is exact-duplicate only.** `remember_owner_fact` writes `agent_id="owner"`, category `identity`, through `repository.add_entry`, then mirrors a bullet into `Memory/owner-facts.md` (`VAULT_FACTS_PATH`) when `public_binding_status()` is bound. `add_entry` rejects a second row with the same `title_key` and `content_hash` (`find_duplicate` in `backend/app/memory/db_layer.py`). A near-duplicate ("I like oat milk" after "I prefer oat milk") is a second row. A changed fact with the same title is a `detect_conflicts` flag, not an update. `ContextEntry` has no `update` mutation. Provenance today is `source_type="owner_memory"`, `source_id=task_id`, `note="owner asked to remember this"`, `created_at`. Confidence and decision source are not stored. A `ContextRepoError` whose text contains "duplicate" is treated as success, so the caller can report stored when nothing new was written. Vault failure still allows `stored` to be true when the repo write failed and the vault write succeeded (`stored = repo_ok or vault_path`).

5. **Secrets, opt-outs, and case material have no capture policy.** Redaction exists and is unused by this writer: `backend/app/ingest/redaction.py` `redact_text` and `backend/app/trajectories/redaction.py` `redact_string` (bearer, AWS, `ghp_`, `sk-`, password assignments). Nothing in `owner_facts.py` calls them. There is no "off the record" / "don't remember" scope. There is no case-material gate. Taco's work is law-enforcement digital forensics; a silent write of a case number or a suspect or victim name would be a trust failure.

6. **The owner cannot see or undo an autonomous write, because none exist.** `frontend/src/chat/OwnerChatTranscript.tsx` renders task `events` and messages. It has no remembered row. `delete_entry` and `revert_mutation` exist on the context repo and are not wired to a chat control or to the phrase "forget that". Settings have vault binding (`KnowledgeVaultSettings` in `backend/app/config.py`, shown by `KnowledgeVaultSettingsSection` inside `frontend/src/settings/IntegrationsSettingsPane.tsx`) and no capture toggle. The rotating decision log `decision/jev_audit.json` (`backend/app/decision/audit.py`, cap 80) is not an owner-facing capture list.

That fails the north star. Continuity should accumulate without the owner translating "I prefer oat milk" into a remember-command. The write must be one store, with provenance, reversible, and quiet on chit-chat. Case material is a consequential decision and must be surfaced. A miss of Jev or Laya must not delay the reply and must not invent a second brain or a second database.

## Decision

One new reflex class, `memory_capture`, scheduled from the RFC-0206 owner turn after the reply is already published. One writer, the #574 owner repo plus `Memory/owner-facts.md`. Jev, Laya, or the rules classifier decides. The reply path does not await the decision or the write.

```text
owner utterance
  -> RFC-0206 decide_owner_turn (route + reply shape; unchanged by this RFC)
  -> owner-visible reply is published
  -> schedule_memory_capture (not awaited)
       -> redact + floors
       -> ONE decide() class memory_capture, deadline 50 ms, off the reply
       -> on miss: one deferred decide() at DEFAULT_DEADLINE_MS (100), same task
       -> commit_owner_fact through the owner context repo, then the vault bullet
```

Explicit "remember this" stays a synchronous task write inside `_ensure_owner_memory`. It calls the same `commit_owner_fact`. Autonomous capture does not call `_ensure_owner_memory`.

### 1. Decision class `memory_capture`

Add `"memory_capture"` to `REFLEX_DECISION_CLASSES` in `backend/app/decision/types.py`. It is not added to `POLICY_HARDENED_CLASSES`. It does not grant a tool, skip an approval, or override `harm_veto`.

**Integration with RFC-0206.** `decide_owner_turn` remains the single routing `decide()` for `request_routing` (questions `request_route` and `reply_shape`, outer wall clock 50 ms, before `generate_front_reply`). This RFC does not add capture questions to that call and does not spend any of that 50 ms. Capture is a second class with its own `decide()`, started only after the owner-visible reply has been published.

`backend/app/decision/owner_turn.py` does not exist at `4fc4619`. Implementation of this RFC does not begin until that module is importable from the merged RFC-0206 work. Do not fork a private copy of routing.

Call site, both shells of "every owner turn":

| Turn | When capture is scheduled | Snapshot passed in |
| --- | --- | --- |
| `stream_owner_chat` (`backend/app/persona/owner_chat.py`) | Immediately after `publish_owner_text` returns, beside the existing `schedule_background_verification(...)` call. The SSE generator does not stay open to wait for capture. `done` is not held. | `user_message`, `conversation_id`, `turn_id`, `reply_shape`, `request_route`, `decision_tier`, the `AppSettings` object the caller already holds |
| Agent loop, after the owner-visible task result is published | A `schedule_memory_capture` call. Not inside `_ensure_owner_memory`. | Same snapshot. `turn_id` is the task id. `reply_shape` / `request_route` come from `OwnerTurnDecision` once RFC-0206 slice 2 threads it into the loop. Until those fields exist on the loop result, pass the baseline route from `decide_owner_turn` and leave `reply_shape` empty only if that function failed closed; do not re-run `route_request` as a second classifier. |

`turn_id` for owner chat is `f"{conversation_id}:{n}"` where `n` is the user-message count in that conversation at schedule time. It is stable for provenance and for the pending-confirm key.

`schedule_memory_capture` follows `schedule_background_verification`: `asyncio.create_task`, a strong reference set, `add_done_callback` discard, returns immediately. The coroutine `await asyncio.to_thread(...)` around `decide()` so the synchronous reflex call does not block the event loop. A capture exception is logged and audited. It does not fail the chat turn and does not change task success.

**Deadline.** First `decide()` uses `deadline_ms=50`. That budget is the capture task's budget. It is not added to time-to-first-text. RFC-0206 already spends up to 50 ms before the front reply; this RFC does not add another wait on that path.

**Miss.** A miss is any of: `source=deadline_fallback`, provider timeout, Jev or Laya unavailable, out-of-domain rejection, missing `action`, or `action` in `{store, update}` with confidence below **0.75**. On a miss the same scheduled task runs `decide()` once more with `deadline_ms` equal to the existing `DEFAULT_DEADLINE_MS` (100 in `backend/app/decision/reflex.py`). Do not change that constant. Do not loop a third time. A confident `skip` (confidence ≥ 0.75) is a decision, not a miss, and does not run the deferred call.

**What the deferred pass is.** It is not `consolidate_agent` and it is not `rank_nodes_for_consolidation`. Those stay the trajectory-lesson job and the swarm-node score. The deferred pass reuses the dedup helpers those lessons already use: `find_duplicate` and `detect_conflicts` in `backend/app/memory/db_layer.py`, called from the capture writer before `add_entry` / `update_entry`. Scheduling is the same `asyncio.create_task` pattern as `schedule_background_verification` in `backend/app/agent/background_verify.py`. There is no separate daemon and no new table.

**Questions.** One batched `decide()`:

| id | type | choices | Meaning |
| --- | --- | --- | --- |
| `action` | choice | `store`, `update`, `skip`, `confirm` | `store`: new fact. `update`: replace the `match_id` entry. `skip`: write nothing. `confirm`: case material; ask before any write. |
| `category` | choice | `identity`, `projects`, `priorities`, `constraints` | See §2. `constraints` is legal only for an opt-out scope. |
| `confidence` | score 0.0–1.0 | — | Store and update require ≥ 0.75 after the provider returns. |
| `match_id` | choice | up to 8 candidate entry ids, then `none` | Candidates are preselected in code (§3). Cardinality stays under Laya `MAX_CHOICE_OPTIONS` (16) in `backend/app/decision/laya/runtime.py`. |

Descriptions on each choice are required (Laya scores descriptions). The provider does not write the fact text. Open-ended generation stays off this class, as in RFC-0171 and RFC-0206.

**State** (`compact_state`, no system prompts, no API keys, no vault paths, no tool catalogs, no raw multi-turn transcript):

| Field | Content |
| --- | --- |
| `user_message` | The utterance after secret rejection. If a secret detector fires, the provider is not called. |
| `candidate_fact` | One clause, ≤ 240 characters, already redacted. Empty when the rules extractor found nothing. |
| `reply_shape` | From `OwnerTurnDecision`. |
| `request_route` | From `OwnerTurnDecision`. |
| `decision_tier` | The tier the caller already resolved. |
| `candidates` | `{id, category, excerpt}` for the ≤ 8 match candidates. Excerpt ≤ 120 characters, normalized, secrets already rejected. |
| `constraint_hashes` | SHA-256 hex of active do-not-store hashes. Plaintext of case scopes is not included. |

Do not call `load_settings()` inside `decide()`. Pass the settings object in, as RFC-0206 requires for the routing call. Unknown tier → privacy `local_only`.

**Privacy.** `privacy_for_tier(decision_tier)` from `backend/app/decision/surfaces.py`. Provider order stays `quartermaster.select_provider_order` inside `decide()`. This RFC does not replace that chain.

| Provider | When it runs | When it does not | Owner-visible failure |
| --- | --- | --- | --- |
| **Laya** (`laya_adapter`, in-process `laya_runtime.decide_local`) | Installed, enabled, and warm. The capture task's deadline bounds the wait. Test injection stays `set_decide_fn` and is always labelled `fixture=True`. | Not installed, not warm, or the forward pass exceeds the remaining budget. | `fallback_used=true`. Source is the next provider or `deadline_fallback`. Never `source=laya` for a fixture presented as the live encoder. |
| **Jev** (`jev_adapter` → `post_systemone`) | `privacy` is `allow_cloud` (`jev_optional` or entitled `jev_plus`) and `jev_calls_allowed` is true: tier is not `local`, probe availability is `connected`, key is bound, Plus is present when the tier is `jev_plus` (`backend/app/decision/tier.py`). Remaining budget is enough to try. | Tier `local`, WAN deny, missing key, probe not `connected`, Plus missing, or privacy `local_only` / `require_local`. `available()` already returns false. | Do not open a TypeSafe socket. Do not label rules or the generative adapter as Jev. A timeout becomes `deadline_fallback` with an explicit reason. |
| **Rules** (`adapters/rules.py`) | The real `memory_capture` classifier in §2, and the deadline / exhaustion fallback. | — | A real classifier with the fixture table below. A function that returns `skip` for every utterance is a failed implementation. |
| **Generative adapter** | Only after typed providers miss, as today: it reuses rules and sets `source=generative`. | — | Do not add a chat-model JSON mode and label it Jev or Laya. |

**Audit.** `decide()` already writes `reflex_decision` or `reflex_deadline_fallback` through `audit.record_event` (`backend/app/decision/audit.py`), including `decision_class`. Capture adds one event, kind `memory_capture`, after the attempt:

| Field | Value |
| --- | --- |
| `turn_id`, `action`, `category`, `confidence`, `decision_source` | From the decision. `decision_source` is `rules`, `laya`, `jev`, `generative`, `deadline_fallback`, or `owner_confirm`. |
| `fallback_used`, `fallback_reason` | From `DecisionResult`. |
| `stored` | True only when the context-repo write succeeded. |
| `entry_id` | Set when `stored` is true. |
| `case_sensitive` | True when the case floor matched. |
| `content` | Omitted when `case_sensitive` is true and the owner has not confirmed. Included for ordinary stored facts (the title, ≤ 80 characters). |

The ring buffer stays capped at 80 (`_MAX_EVENTS`). Stored facts do not depend on that ring. Their durable record is the context-repo mutation (§4). A skip older than the ring is gone; that is an honest limit, not a second log file.

**Floors (after the provider answer, one guard).** A provider cannot weaken these.

| Floor | Rule |
| --- | --- |
| Secret | If `ingest.redaction.redact_text` or `trajectories.redaction.redact_string` changes the utterance or the candidate, `action=skip`. Write nothing, including the `[REDACTED]` residue. Do not send the original to Jev. |
| Opt-out | Patterns in §2 force `action=skip` for the content and a `constraints` write of the scope. |
| Do-not-store match | Candidate hash or topic matches an active constraint → `action=skip`. |
| Case | Patterns in §2 force `action=confirm`. No repo write and no vault write until the owner accepts. |
| Explicit remember | `is_memory_store_request` → autonomous `action=skip`. `_ensure_owner_memory` owns that utterance. |
| Literal | `reply_shape=literal` → `skip`. |
| Chit-chat | Greeting / thanks / weather with no keep-clause → `skip`. |
| One-off | `request_route=managed_task` and no keep-clause → `skip`. |
| Low confidence | `store` or `update` below 0.75 → `skip`. |
| Update without a match | `action=update` and `match_id=none` → `skip`. Do not invent a new row from a correction fragment. |
| Category | Provider `constraints` without an opt-out floor → rewrite category to the rules category, or `skip` if no keep-clause. |
| Toggle off | `memory_capture.enabled` is false → do not call `decide()` and do not write. Explicit remember still runs. |

### 2. What counts as of interest

One candidate fact per turn. The reflex lane does not generate a list. The rules extractor returns the first keep-clause, ≤ 240 characters, with the remember-prefix stripped using the existing `fact_body` helper when that prefix is present.

**Keep**

| Kind | Category | Rules signal (real classifier, not a stub) |
| --- | --- | --- |
| Durable owner fact, preference | `identity` | `\b(?:i (?:like|prefer|hate|always|never)\|my favorite)\b` |
| Person | `identity` | `\bmy (?:wife\|husband\|partner\|brother\|sister\|mother\|father\|son\|daughter\|friend\|colleague)(?:'s name)? is\b` |
| Project | `projects` | `\b(?:i(?:'m\| am) working on\|the project is\|this repo is)\b` |
| Decision | `priorities` | `\b(?:we decided\|i decided\|the decision is\|let's go with)\b` |
| Correction | category of the matched entry | `\b(?:actually\|correction:)\|i meant\b`, and only when §3 finds a match. No match → `skip`. |

`identity`, `projects`, and `priorities` already exist on `ENTRY_CATEGORIES` in `backend/app/memory/schema.py`. Add `constraints` to that tuple and to `CONTEXT_ENTRY_CATEGORIES` in `frontend/src/api.ts`. `add_entry` rejects unknown categories; the new value has to be in the set or the opt-out write fails closed.

**Exclude**

| Kind | Outcome |
| --- | --- |
| Chit-chat | `skip`. Reuse `is_plain_conversation` / `_TRIVIAL_CHAT` in `backend/app/agent/planning.py` as a signal inside the rules classifier. A greeting that also contains a keep-clause still keeps the clause. |
| Secrets and credentials | `skip` the whole candidate. Detectors: `redact_text` and `redact_string`, plus the trajectory key pattern (password, token, `api_key`, bearer, private key). |
| One-off task noise | `skip` when the route is `managed_task` or the utterance is only an app/file/tool request (`requests_agent_tools`, `simple_app_control`, `simple_file_control`) and no keep-clause remains. "Always open reports in dark mode" still matches the preference pattern and may `store`. |
| Explicit don't-keep | Honour it, and remember the scope. Patterns, case-insensitive: `don't remember`, `do not remember`, `forget this`, `off the record`, `keep this off the record`, `don't store this`, `do not store this`. |

**Do-not-store scope.** The opted-out content is not the stored fact. The stored row is category `constraints`, `source_type=do_not_store`, `active=true`.

| Scope | Content written | Later match |
| --- | --- | --- |
| This utterance, or a declined case confirm | `do-not-store hash:<sha256>` of the normalized candidate. `metadata.plaintext_omitted=true`. | SHA-256 of a future candidate equals the hash. |
| Owner named a non-case topic ("don't remember my coffee order") | `do-not-store topic: coffee order` | Token overlap with the topic uses the same Jaccard threshold as §3. |
| Owner named a case-shaped topic ("don't remember the Miller case") | Hash only, plaintext omitted. The audit line reads "Case-related do-not-store scope (details not kept)". | Future case-detector span hashes equal the stored hash. |

This is the owner asking to remember the boundary. It is not silent capture of the case.

**Case material — confirm, do not skip and do not write silently.** Chosen behavior: **ask with a visible confirmation, and write only after a yes.**

Justification against the north star: §7 separates routine reversible work from consequential and security-sensitive action, and says important decisions are surfaced. §11 wants continuity, including for a forensic owner who will want a case available next session. §19 says expose state when the owner needs confidence. Quality test 5 hides complexity while keeping control. Quality test 10 avoids unnecessary prompts: coffee preferences do not ask; case numbers, suspect names, victim names, and evidence identifiers do. A silent skip would drop case continuity and hide the refusal. A silent store would put evidence-adjacent names into the vault without a decision. One visible question is the control.

Case floor (forces `confirm` even when Laya or Jev returned `store`):

- `\b(?:case|docket|incident|report)\s*(?:no\.?|number|#)?\s*[:#]?\s*[A-Z0-9][A-Z0-9-]{2,}`
- `\b(?:exhibit|evidence item|badge)\s+#?\s*[A-Za-z0-9-]+`
- `\b(?:suspect|victim|witness|complainant|decedent)\b` followed within six words by a capitalized name

The detector is lexical and incomplete. A case detail with none of these cues can still be stored if the classifier calls it an ordinary fact. The remembered row and Forget exist for that residue. Do not claim the floor sees every forensic detail.

**Confirm lifecycle.** Pending state is an in-process dict keyed by `turn_id`, holding the candidate, category, match id, and confidence. It is not a context-repo row and not a vault bullet. It dies on process restart, on the next unrelated owner turn, or after 10 minutes, whichever comes first. Expiry audits `stored=false`, `action=confirm`, content omitted.

Acceptance utterances: `yes`, `remember that`, `yes, remember that`. Decline utterances: `no`, `don't remember`, `forget that` while a confirm is pending. Buttons hit `POST /api/owner/memory/confirm` with `{turn_id, accept}`. Voice uses the same phrases because speech already arrives as an owner utterance (`frontend/src/chat/useLocalVoiceListen.ts` is not modified).

The confirm line shows the proposed fact so the owner sees the exact text. Publish it with `BUS.publish(..., persist=False)` (`backend/app/events.py`) so the case text is not inserted into `TaskEvent`. On accept, `commit_owner_fact` runs with `decision_source=owner_confirm` and `metadata.case_confirmed=true`. On decline, write only the hash constraint.

### 3. Store path

Authority is the owner context repo (`agent_id="owner"`, `repository.py` / `store.py` / `db_layer.py`). The bound vault file `Memory/owner-facts.md` is the owner-editable mirror, written only after the repo write succeeds. Supermemory stays the optional sidecar: `_snapshot_version` already calls `mirror_mutation`, and a mirror failure must not roll back the repo write (the `except` already in `_snapshot_version`). Session notes from `mirror_owner_chat_turn` (`_Temporal/Sessions/...`) are a chat mirror. `persist_verified_correction` (`Decisions/`) stays the background-verify correction note. Capture does not write either of those paths.

`remember_owner_fact` becomes a wrapper: `fact_body`, then `commit_owner_fact` with `category=identity`, `source_type=owner_memory`, `confidence=1.0`, `decision_source=owner_request`, `note="owner asked to remember this"`. `_ensure_owner_memory` keeps its current contract: the task fails when the repo write fails. `stored` is true only when the repo write succeeded. A vault-only write is not success. Report `vault_error` on the result. This tightens the #574 return flag so the product cannot claim a fact that recall will not see.

**Provenance on every stored or updated fact**

| Slot | Field |
| --- | --- |
| `EntryProvenance.source_type` | `autonomous_capture`, `owner_memory`, or `do_not_store` |
| `EntryProvenance.source_id` | `turn_id` |
| `EntryProvenance.created_at` | UTC ISO timestamp, the existing field |
| `EntryProvenance.note` | One line, ≤ 160 characters, why it was kept. No secret and no case body on an unconfirmed row. |
| `ContextEntry.metadata` | `confidence` (float), `decision_source`, `turn_id`, `conversation_id`, `capture_action` (`store` or `update`), `case_confirmed` (bool) |

Do not add a parallel provenance model. `EntryProvenance` stays the source identity. The extra fields fit the existing `metadata` dict (`update_fact` already persists `metadata_json`).

**Dedup and update.** Normalize with the same `_normalize_key` as `db_layer.py` (strip, lowercase, collapse whitespace). Tokens are the recall rule: split on whitespace, keep length > 2.

| Step | Match | Action |
| --- | --- | --- |
| 1 | `find_duplicate` (same category, `title_key`, `content_hash`) | `skip`. Do not append another vault bullet. Do not treat the duplicate exception as a new store. |
| 2 | `detect_conflicts` (same category, same `title_key`, different `content_hash`) | `update` that id. |
| 3 | Token Jaccard ≥ 0.6 against active owner entries in the chosen category, at most 8, highest first | Those ids are the `match_id` choices. Rules with exactly one candidate at or above 0.6 select it. Several candidates: highest Jaccard. A tie: `skip` rather than guessing. |
| 4 | No candidate | `store` for a keep-clause. `skip` for a correction. |

Jaccard is `|intersection| / |union|`. An empty token set does not match.

`update_entry` is new in `repository.py`, next to `add_entry`. It loads the active entry, copies content, title, provenance, and metadata, calls the existing `update_fact`, and snapshots a `MutationRecord` with `action="update"`. It does not insert a second active row. Title remains the first 80 characters of the body, the same truncation `remember_owner_fact` uses.

**Vault bullet.** After repo success, when `vault_root()` is bound:

- Create `Memory/owner-facts.md` with `# Owner facts` if missing (`create_note`), else update that file.
- New fact: `append_note` one bullet: `- {body} <!-- capture: entry={id} turn={turn_id} at={created_at} confidence={confidence} source={decision_source} -->`
- Update: `read_note`, replace the bullet whose comment contains `entry={id}`, `edit_note`. A user-edit conflict (`_user_edit_conflict`) leaves the repo update in place, sets `vault_error`, and does not clobber the owner's edit.
- Unbound vault: repo row stands. The indicator says the vault mirror is absent. Recall uses `recall_owner_facts`, which reads the repo.

Forget removes the bullet the same way (replace with nothing). A missing bullet sets `vault_error` and still deletes the repo row.

### 4. Owner control and visibility

**Toggle.** Default **on**.

`MemoryCaptureSettings` on `AppSettings` in `backend/app/config.py`: `enabled: bool = True`. Patch field `memory_capture_enabled` on `SettingsUpdate` in `backend/app/api/settings.py`, same flat style as the `social_commentary_*` fields. UI: a new `frontend/src/settings/MemoryCaptureSettingsSection.tsx` rendered by `frontend/src/settings/IntegrationsSettingsPane.tsx`, under the existing vault section. Copy states that ANZU keeps useful facts on its own, that case details still ask first, and that "remember this" still works when the toggle is off.

Default on is the order: the product defect is that ANZU waits to be told. North star §11 is continuity without starting from zero. §7 says routine work happens. An off-by-default switch would leave every preference on the remember-phrase path. The owner can turn it off. Case confirmation stays in force while the toggle is on.

**Remembered indicator.** One row in `frontend/src/chat/OwnerChatTranscript.tsx`, under the assistant reply for that turn. Plain text and a Forget button. No persona, no presence import, no WebGL.

| Event | How it is published | What the row says |
| --- | --- | --- |
| `memory_captured` | `BUS.publish(task_id, ..., persist=True)` when the turn has a task id. Detail JSON: `entry_id`, `title`, `category`, `confidence`, `decision_source`, `vault_mirrored`. | "Remembered" plus the title. If `vault_mirrored` is false, add "Not in the Obsidian vault yet." |
| `memory_confirm` | `BUS.publish(task_id, ..., persist=False)` or `publish_ephemeral` on `OWNER_CHAT_CHANNEL` when there is no task. Detail includes the proposed fact and `turn_id`. | "This looks like case material. Remember it?" with Remember and Don't remember. |

`filterWorkEvents` in `frontend/src/chat/ownerChatView.ts` excludes both kinds so the row is not buried in the work drawer. `pages/Chat.tsx` and `hud/HudChat.tsx` already pass `events` into the transcript. This RFC does not edit `frontend/src/hud/**`. A task-scoped row shows in the HUD thread because that file already forwards events. `pages/OwnerChat.tsx` reloads messages without events; extend `GET /api/owner/chat/conversations/{id}` with a `captures` list read from active owner-repo entries whose `metadata.conversation_id` matches, and pass that list into the transcript. That is a read of the same store.

**Forget / undo.** The button calls `POST /api/owner/memory/forget` `{entry_id}`, implemented as `forget_owner_fact`: `delete_entry` for agent `owner`, vault bullet removal, and the existing supermemory mirror via the snapshot path (`forget_entry` already runs from `mirror_mutation` on delete). Autonomous rows are created unpinned. A pinned row raises the existing "Pinned entries cannot be deleted" error; the owner-visible line is "That fact is pinned. Unpin it on Context Repo, then forget it." Do not auto-unpin.

Voice and text "forget that", with no confirm pending, forgets the newest autonomous or explicit owner fact whose `metadata.conversation_id` matches, else the newest such fact in the owner repo. The reply is one sentence, "Forgotten.", through the normal owner-chat reply. It is not itself captured.

`revert_mutation` remains available on the context repo for a full version undo. The chat control is delete-by-entry, which is the owner-facing forget. Do not build a second undo log.

**Audit list.** A "Captured" section on `frontend/src/pages/Memory.tsx`. It reads `GET /api/context-repo/owner/history` (`list_history`) and shows mutations whose `source.source_type` is `autonomous_capture`, `owner_memory`, or `do_not_store`: time, action, title or constraint label, confidence, decision source, note. Case constraints with `plaintext_omitted` show the fixed label, not the hash input. The 80-event decision ring is not this list. Context Repo (`frontend/src/pages/ContextRepo.tsx`) keeps its existing history UI; add the `constraints` label to `CATEGORY_LABELS` so the new category is readable there. Do not create a capture table.

**Files this RFC does not touch.** `frontend/src/presence/**`, `frontend/src/persona/**`, `frontend/src/hud/**`, WebGL renderers, morph, particle presence, and anything whose job is to feed those. Voice listen, the waveform, and `VoiceSettingsPane.tsx` stay as they are. Speech arrives as text; the backend floors handle "forget that" and the confirm phrases.

### 5. Acceptance

**This spec**

- [x] RFC-0209 accepted: class `memory_capture`, off-reply 50 ms decide, deferred pass named against `scheduler.py` / `consolidation.py`, #574 store path, case confirm, default-on toggle, real-store tests.
- [x] `docs/rfcs/README.md` indexes 0209. 0207 and 0208 stay unused.

**Implementation (follow-on; unchecked)**

- [ ] `"memory_capture"` is in `REFLEX_DECISION_CLASSES` and not in `POLICY_HARDENED_CLASSES`. Every owner-chat reply and every completed owner task schedules capture without awaiting it. `decide_owner_turn` is still the only routing call. A test fails if capture runs before the first owner-visible text.
- [ ] Local tier and a disconnected Jev probe open no TypeSafe socket. Connected `jev_optional` may call Jev only inside the capture task's remaining budget. `source=jev` only when `provider=jev` and `fallback_used` is false.
- [ ] Rules fixtures: preference, person, project, decision, and correction-with-match return `store` or `update` at confidence ≥ 0.75. Greeting, secret, one-off tool request, explicit remember-phrase, and literal reply return `skip`. Opt-out writes a constraint and does not write the content. The rules module is not a constant `skip`.
- [ ] Exact duplicate does not add a row or a second bullet. Near-duplicate Jaccard ≥ 0.6 updates the existing entry in place. A vault user-edit conflict does not clobber the note. `stored` is false when the repo write fails, even if a vault write would have worked.
- [ ] Each stored fact's provenance has turn id, timestamp, confidence, and decision source, on the repo entry and in the vault bullet comment.
- [ ] Case utterance writes nothing until Remember / "yes, remember that". Decline writes a hash constraint and not the case text. Task event log has no persisted confirm body (`persist=False`).
- [ ] Toggle default is on. Off skips autonomous `decide()` and still allows "remember this". Forget and "forget that" remove the repo row and the vault bullet. Pinned rows are refused with the unpin sentence.
- [ ] Transcript shows Remembered for a stored fact and the case question for a confirm. Memory page lists capture mutations from the owner repo history.
- [ ] Two-session recall: a preference captured in one session is returned by `recall_owner_facts` in a later read of the same temp store, and the second utterance does not match `is_memory_store_request`.
- [ ] Latency: a labelled Laya fixture that sleeps 2 seconds is entered only after the first owner-visible text. The first text is not delayed by that sleep. The store is the real repo and temp vault, not a mock.
- [ ] `python3 -m pytest` passes. Portal slice runs `npm --prefix frontend run build` and `npm --prefix frontend run lint`.
- [ ] Desktop sign-off (not claimable from the Linux cloud VM): in a live owner-chat session, state a preference without saying "remember"; in a later session after restart, ask about it and receive it. Warm-Laya capture stays off the first-text path.

### Implementable slices

Land in order. Each slice is one PR against `development` and keeps `python3 -m pytest` green. Do not start slice N+1 by reverting slice N's tests. Do not start slice 1 until RFC-0206's `decide_owner_turn` is on `development`.

| Slice | Owns | Files | Done when |
| --- | --- | --- | --- |
| 1. Contract + rules | Decision class and classifier | `backend/app/decision/types.py`, `backend/app/decision/adapters/rules.py`, `backend/app/decision/memory_capture.py` (new), `tests/test_rfc0209_memory_capture_decision.py` | Real `decide()` with Laya and Jev unavailable returns the fixture table. Floors beat a contradictory provider answer. No chat call site yet. Tests do not mock `decide`. |
| 2. Store | One writer | `backend/app/memory/owner_facts.py`, `backend/app/memory/repository.py` (`update_entry`), `backend/app/memory/schema.py` (`constraints`), `backend/app/memory/obsidian_vault.py` (bullet replace only through existing `edit_note` / `append_note`), `tests/test_rfc0209_memory_capture_store.py` | Temp vault, real `add_entry` / `update_fact`. Provenance present. Duplicate skip. Near-dup update. Unbound vault still recalls from the repo. `stored` requires the repo. |
| 3. Schedule | Off the reply path | `backend/app/decision/memory_capture.py` (`schedule_memory_capture`), `backend/app/persona/owner_chat.py`, `backend/app/agent/loop.py` (after the result, not inside `_ensure_owner_memory`), `tests/test_rfc0209_memory_capture_latency.py` | Labelled slow Laya fixture. First owner-visible text precedes fixture entry. Capture failure does not fail the turn. Deferred 100 ms pass runs only on a miss. |
| 4. Control | Opt-out, case confirm, forget | `backend/app/decision/memory_capture.py`, `backend/app/api/owner_chat.py` (confirm + forget routes), `tests/test_rfc0209_memory_capture_control.py` | Opt-out scope blocks a later store. Case text absent from the repo until accept. Decline stores a hash. "forget that" deletes the real row and the bullet. |
| 5. Portal | Indicator, toggle, audit | `frontend/src/chat/OwnerChatTranscript.tsx`, `frontend/src/chat/ownerChatView.ts`, `frontend/src/pages/OwnerChat.tsx`, `frontend/src/pages/Memory.tsx`, `frontend/src/settings/MemoryCaptureSettingsSection.tsx`, `frontend/src/settings/IntegrationsSettingsPane.tsx`, `frontend/src/api.ts` (`constraints` category), `frontend/src/pages/ContextRepo.tsx` (label only), `backend/app/config.py`, `backend/app/api/settings.py` | Remembered row and case question render from events. Toggle defaults on and round-trips through `/api/settings`. Memory page lists repo history. `npm --prefix frontend run build` and `lint` pass. No file under `presence/`, `persona/`, or `hud/`. |

Slice 2 depends on slice 1. Slice 3 depends on slices 1 and 2 and on RFC-0206. Slice 4 depends on slice 2. Slice 5 depends on slices 3 and 4.

## Likely files

| Area | Paths |
| --- | --- |
| Decision | `backend/app/decision/types.py`, `reflex.py` (callers only; do not fork the provider chain), `memory_capture.py`, `adapters/rules.py`, `adapters/jev_adapter.py`, `adapters/laya_adapter.py`, `surfaces.py` (`privacy_for_tier` only) |
| Store | `backend/app/memory/owner_facts.py`, `repository.py`, `db_layer.py` (call `find_duplicate` / `detect_conflicts` / `update_fact`; do not fork them), `schema.py`, `obsidian_vault.py`, `store.py` |
| Call sites | `backend/app/persona/owner_chat.py`, `backend/app/agent/loop.py`, `backend/app/api/owner_chat.py`, `backend/app/api/settings.py`, `backend/app/config.py` |
| Redaction | `backend/app/ingest/redaction.py`, `backend/app/trajectories/redaction.py` (call, do not rewrite the patterns) |
| Portal | `frontend/src/chat/OwnerChatTranscript.tsx`, `frontend/src/chat/ownerChatView.ts`, `frontend/src/pages/OwnerChat.tsx`, `frontend/src/pages/Memory.tsx`, `frontend/src/pages/ContextRepo.tsx`, `frontend/src/settings/IntegrationsSettingsPane.tsx`, `frontend/src/settings/MemoryCaptureSettingsSection.tsx`, `frontend/src/api.ts` |
| Tests | `tests/test_rfc0209_memory_capture_decision.py`, `tests/test_rfc0209_memory_capture_store.py`, `tests/test_rfc0209_memory_capture_latency.py`, `tests/test_rfc0209_memory_capture_control.py` |
| Docs | this RFC; one index line in `docs/rfcs/README.md` |

## Out of scope

- Editing RFC-0206, RFC-0205, or the reserved 0207 / 0208 numbers.
- `consolidate_agent`, `rank_nodes_for_consolidation`, and `POST /api/context-repo/consolidate` as a capture writer. They remain trajectory consolidation and node scoring.
- A second memory database, a capture log file, or Supermemory as the authority (RFC-0132 stands: the context repo is authoritative).
- Putting capture questions inside the RFC-0206 `request_routing` batch, or raising `DEFAULT_DEADLINE_MS`.
- `persist_verified_correction`, session mirrors under `_Temporal/Sessions/`, and trajectory lesson categories (`lessons`, `skills`, `procedures`) as the place a preference goes.
- UI personas, WebGL, Presence, morph, `frontend/src/hud/**`, `frontend/src/presence/**`, `frontend/src/persona/**`, voice waveform, and `VoiceSettingsPane.tsx`.
- Tool permission, approval popups, and `harm_veto`.
- Swarm placement of owner memory, Browser Use, and model-stack work.
- Editing Architect-owned spec docs. A §58 line is a note for the Architect.

## Risks and open questions

**Risks**

- **Jev will often miss 50 ms.** Same fact as RFC-0206: the vendor range is slower than this budget. On the capture task that miss schedules the single 100 ms deferred pass and then the rules classifier. It must not move onto the reply path to "give Jev time."
- **Rules are the product when both models are down.** A constant `skip` means ANZU never remembers. A constant `store` means the vault fills with chit-chat. Slice 1's fixture table is the guard.
- **Case cues are lexical.** Uncued case details can be stored. The row is visible and forgettable. Do not paper over a missed cue by silently dropping every proper noun; that would also drop "my sister is Ann."
- **`compact_state` compresses long utterances.** The extractor runs on the raw utterance before `compact_state`, and `candidate_fact` is the short field the provider sees.
- **Confirm text in a persisted task event would be a second copy of case material.** `persist=False` is the guard. A test reads `TaskEvent` and expects no confirm body.
- **Shared transcript.** `OwnerChatTranscript` is also mounted by `hud/HudChat.tsx`. The new row is text and buttons. The HUD file is not edited. Do not import presence into the transcript to "style" the row.
- **Vault unbound is normal.** Recall still works from the repo. The indicator has to say the mirror is missing. Reporting "Remembered" with an implied vault write is a bug.
- **RFC-0206 is in flight.** A capture scheduler that classifies the route itself will diverge from `decide_owner_turn`. Block this implementation on that import.
- **Cloud VM cannot sign the restarted live session.** The pytest two-session read is the cloud bar. Desktop restart stays unchecked.

**Open questions**

- Non-English opt-out and preference phrasing have no rules pattern in v1. Warm Laya may still return `skip` or `store`. Widen the floor only with fixtures.
- One candidate per turn drops a second fact in the same sentence ("I prefer tea and my sister is Ann"). v1 keeps the first keep-clause. A second class of multi-fact extraction is a later RFC if owners hit it.
- Whether a declined confirm should also suppress near-duplicate paraphrases, or only the exact hash. v1 is the exact normalized hash plus, for a named case topic, the hash of the case-detector span. Paraphrase suppression waits until the exact-hash behavior is tested.

## Notes

- Implement model: Composer 2.5 standard. One slice per worker prompt. After RFC-0206, before RFC-0205.
- North-star check for the implementer: a preference said once is back next session; the first reply did not wait; Jev is named only when Jev answered; secrets and unconfirmed case text are absent from the repo and the vault; the owner can see the row and forget it; one store is the owner context repo.
