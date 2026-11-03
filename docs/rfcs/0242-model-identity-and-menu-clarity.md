# RFC-0242: Accurate model identity, honest node-dropdown rows, verified Unload and verified Load (rescoped onto the RFC-0244 dropdown)

**Status:** accepted (original text by Codex, #682); **rescoped 2026-10-30** by Jarvis Architect on CoS assignment; **amended 2026-11-03** with the Keep warm toggle and 5-minute idle unload contract (section "Amendment: Keep warm toggle and 5-minute idle unload"). This file is the authoritative RFC-0242 on `development`. Where it differs from the text in #682 (RFC-0242; final head in this PR's body), this file wins.
**Author:** Codex, requested by Daan (original, 2026-10-28); Jarvis Architect (rescope, 2026-10-30)
**Date:** 2026-10-28; amended 2026-10-30 and 2026-11-03
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §8 (ANZU must verify its own work; "confidence should come from evidence rather than cheerful completion messages"), §9 (local-first, owner-controlled infrastructure), §19 ("Do expose state when the user needs confidence in what ANZU is doing"; "Do not mark something finished merely because its backend exists"), §20.
**Traced on:** `development` @ `a62bd454` (#685 landed on top of RFC-0244, #684). Every citation below is by file and symbol or by section name; no line numbers.
**Builds on:** [RFC-0244](0244-three-engine-modes.md) sections "Decision" (including its owner follow-up) and "Acceptance criteria". Not affected: [RFC-0241](0241-model-startup-upgrade-reuse-catalog.md) (startup upgrade and catalog reuse).
**Open batch PRs reconciled (final heads in this PR's body):** #652 (RFC-0225; final head in this PR's body), #655 (RFC-0228; final head in this PR's body), #664 (RFC-0232; final head in this PR's body), #665 (RFC-0245; final head in this PR's body), #668 (RFC-0233; final head in this PR's body). #682 (RFC-0242; final head in this PR's body) is the code PR this rescope reworks, and it stays the single code PR (reworked by D2, one commit per ticket).
**Ordering (CoS, 2026-10-30):** RFC-0242's tickets go **last** on every file they share with the batch, after each file's existing chain. The tickets assume the batch (#652, #655, #664, #665, #668 and #670) has landed; D2 merges `development` into #682 once it has. The batch specs need no edit for this RFC's tickets. (The separate 2026-11-03 keep-warm order also reconciles #655 (RFC-0228; final head in this PR's body), see *Amendment: Keep warm toggle and 5-minute idle unload*.)
**Astra boundary:** personas, WebGL and presence are not touched. The model dropdown is shared HUD chrome, not an Astra system; it is changed add-alongside only (see *Live-UI add-alongside reasoning pass*).

## Supersession notice (read first)

RFC-0244 "Decision", owner follow-up ("remove all six pinnable slots and their assignment/reordering UI. Replace them with one model dropdown for the node serving this portal and explicit loading/status") and its acceptance bullet "Six-slot/pin/reorder controls and shortcuts are gone; a current-node dropdown replaces them without silently activating models on selection" **supersede** the following parts of the RFC-0242 text in #682. They are dropped, not deferred, and no ticket in this RFC implements them:

| Dropped from the original RFC-0242 / #682 | Why |
| --- | --- |
| The slot and Pin UI, including the slot chooser and the "visible slot chooser" in the original "Decision" | RFC-0244 removed all six slots and their assignment UI. |
| Registration-only bind endpoints (`POST /api/lmstudio/catalog/{profile_id}/bind`, `POST /api/lmstudio/discovery/bind`) and the frontend `bindLmStudioProfile` / `bindDiscoveredGguf` | Their only purpose was "Pin saves a shortcut without loading". With no shortcut there is nothing to register without activating. The dropdown choice is a client-side draft until the owner presses Load (RFC-0244). |
| Explicit Pin buttons; "Load and Pin are visibly distinct; slot tiles fill their grid width and model names wrap" (original acceptance) | No slot tiles or Pin buttons exist after RFC-0244. |
| "Pinning discovered and graded models creates a shortcut without loading, changing runtime selection or starting tools" (original acceptance) | Same. The remaining half of its intent, "choosing a model never activates it", is already RFC-0244's rule and is kept as a constraint (R1). |
| The slot UI in `HudModelSelector.tsx` and the new `frontend/src/hud/modelSlots.ts` in #682; the "clear running highlights after manual unload" slot-highlight fix | The slot UI no longer exists on `development`. |
| `backend/app/api/lmstudio.py` bind routes and their tests (`test_binding_shortcuts_never_activates_inference`) | See bind endpoints. |

The existing backend pin flag (`pinned` on graded profiles, the catalog `pin` route and the "★" in option labels, all already on `development` after RFC-0244) is **not** touched by this RFC. Removing it is a separate decision.

**What survives is exactly four items**, each re-homed on the RFC-0244 current-node dropdown and sliced into tickets T1-T6 below:

1. Family-identity matching, and absent candidates that cannot load (T1).
2. Honest dropdown rows: actual artifact, GiB, quantization, speed and refusal labels, with live serving identity taking precedence over catalog data, plus the primary-source comparison document (T2).
3. Unload with verified native release (single model and all ANZU-loaded models), and after an explicit Unload background paths never reload anything until an explicit Load while an owner turn respawns on demand, reconciled with RFC-0244's rule that a mode switch never claims VRAM was released (T3, T4).
4. Verify the loaded LM Studio instance before reporting a switch as successful (T5), with the CoS ruling that an explicit owner Load works in every engine mode (T6).

Nothing else from #682 is in scope. In particular the unrelated hunks visible in the #682 diff against `development` (it is based on `2107966d`, before RFC-0244) are stale base noise, not changes to keep.

## Problem

The symptoms that started this RFC are unchanged and still reachable on `development` even after the RFC-0244 dropdown:

- A running Qwen3.8 27B GGUF was labelled as a 9B uncensored candidate. Generic catalog words (`uncensored`, `Q4`, a bare family stem) matched unrelated families, and an absent candidate could appear loadable (`select_catalog_profile` registered it).
- `resolve_advertised_model` in `backend/app/inference/backends.py` reduced a dotted identifier with `Path.stem` (`Qwen3.8-9B` became `Qwen3`), and returned the only advertised model whatever the owner asked for; `lmstudio_server.ensure_local_lmstudio` then accepted a model that was merely advertised as ready, so a switch could be reported successful without a loaded instance.
- The dropdown row shows weights as "GB" and a quantization, but not the actual file, nor an honest speed or restriction label, and a catalog label can sit next to a different live serving identity.
- RFC-0244's Unload only disconnects ANZU (`MANAGER.unload`); it does not release the native LM Studio or Ollama instance, and it reports success from ANZU's own state. The dropdown's inventory cross-check after Unload is a second line of defense, not a verification of the release itself.
- Under `reflex_only` the dropdown's Load button is disabled and the load entry points raise `ModelDisabledError`, so an owner who wants a model resident cannot load one at all. CoS ruled that an explicit owner Load works in every mode.

## Decision

Keep the four items above, implemented on top of the RFC-0244 dropdown, never replacing it.

**Constraints (normative, each has a named test below):**

- **R1. No silent activation on selection (RFC-0244).** Choosing a row only changes the draft. Only the explicit Load button activates. No ticket adds an activating request on `onChange`.
- **R2. An explicit owner Load works in every engine mode, including `reflex_only` (CoS ruling).** Loading weights is not generation. The generation lanes stay governed by RFC-0244: under `reflex_only` a resident model is still never called. Autoload (startup restore, the running-models autoload, context reload, agent and persona paths) stays blocked by RFC-0244 exactly as today, and so does an **owner turn**: under `reflex_only` an owner turn loads nothing (only an explicit Load does, see *Load origin* in the 2026-11-03 amendment).
- **R3. Inventory stays read-only (RFC-0244 "Decision").** `NodeAiInventory` and `node_inventory.py` get no mutating control and no new request. Unload is a separate action on the *selected serving model* through its own endpoint.
- **R4. A mode switch never claims VRAM was released and never unloads (RFC-0244 "Decision": "Switching mode does not … claim VRAM was released").** Only an explicit Unload verifies a release, and only that action may say "released" or "unloaded". See *Reconciling Unload with RFC-0244*.
- **R5. No success is reported without evidence (north star §8).** Load success needs the runtime's own loaded-instance evidence (T5). Unload success needs the runtime's own post-unload inventory (T3). A response that merely says OK is never enough.
- **R6. Security gates, approval checks, system prompts and routing policy are unchanged.** This RFC adds no download, no default promotion and no installer change.
- **R7. A blocked action is never silently dead (CoS ruling).** When a mode, a lease or a runtime refuses an owner action, the owner sees the reason on the control that was pressed: the backend answers 409 with the plain text, and the existing error line of that control (the dropdown status line, the offer card's `setError` line) shows it verbatim. No ticket adds a control that is disabled or ignored without a visible reason, and none leaves a pressed button without a result. T6 implements the mapping: `choose_running_model` and `load_model` answer 409 with the exception text for `ModelDisabledError` and `ModelManuallyUnloaded` (they are `RuntimeError`s, so today they would fall through to 503 and 500).

### RFC-0244 erratum: explicit Load under `reflex_only` (CoS ruling, 2026-10-30)

RFC-0244 section "Decision" says `reflex_only` "excludes generative providers, front/worker model calls and model autoload", and its "Acceptance criteria" bullet "Reflex only cannot start/call front or worker generation, including startup and fallback paths" is about generation and automatic starts. Nothing in either section says an **explicit owner Load** is excluded. The RFC-0244 implementation nevertheless guards loading with the generation guard (`engine_mode.require_model`): `POST /api/model/load` answers 409, the activation helpers raise `ModelDisabledError`, and the dropdown's Load button is disabled under `reflex_only`. That is an implementation overreach, not a specified behaviour. **Erratum:** under `reflex_only` an explicit owner Load (the dropdown Load button, the activate and select routes, and the running-models offer card's "Use model" and "Use ANZU's model" actions) loads weights and nothing else; the resident model is still never called, and autoload stays excluded exactly as the "Decision" sentence says. T6 changes the guard, the button, the offer-card route and the two RFC-0244 tests that asserted the overreach (named in T6). This erratum is recorded here, in the RFC that carries the change; RFC-0244's own text is not edited.

### 1. Family identity and absent candidates (T1)

Matching a local GGUF to a graded catalog row requires **family identity**, not generic tags.

- Each graded seed in `backend/app/inference/lmstudio_graded_profiles.json` carries `match_identity_any` (at least one must appear in the file name or path, e.g. `Qwen3.8-9B-Distill`), and optionally `match_required_substrings` (all must appear, e.g. `Defiant`, `Ortenzya`). `match_substrings` only ranks candidates that already pass identity. A seed with no identity field falls back to its `match_substrings` as identity, so no seed can match on a generic tag alone; seeds for exact artifact names (the two research candidates below) use the exact file name.
- `lmstudio_catalog._match_profile` rejects a file unless `match_identity_any` and `match_required_substrings` pass, then scores `match_substrings`. A 27B Heretic, a Gemma Aggressive file or an arbitrary Q4 file therefore cannot match a different 9B or 4B family row.
- `QUANT_RE` keeps the full variant: `Q4_K_M`, `Q6_K`, `IQ3_M`, `BF16`, `F16`, `FP8` are returned whole, never truncated to `Q4` or `Q6`, and a token inside a longer word is not a quantization.
- **Absent candidates cannot load.** `select_catalog_profile` raises `ValueError("Model is not installed. Download its GGUF before loading it.")` when the graded row has no matched file. The dropdown already lists only matched rows (`nodeModelOptions` skips `!profile.matched`), and that stays; the backend guard makes it true for any caller of the route.
- Two research candidates ship as **unbenchmarked** graded rows with their verified publisher provenance (`huggingface` block: model id, filename, revision, SHA-256, license, byte size) and the label *Provisional rating; local benchmark required*: Qwen3.5 9B HauhauCS Aggressive Q6_K and Dolphin 2.9.3 Mistral Nemo 12B Q4_K_M. No weights are downloaded and neither becomes a default (R6). Their numbers are those recorded in `docs/reviews/2026-10-28-investigative-model-comparison.md` and are checked against it by a test (T2).
- Resolution of the *advertised* name for a chosen hint lives in T5 (item 4), not here.

### 2. Honest dropdown rows and live-identity precedence (T2)

The RFC-0244 dropdown (`HudModelSelector`, options from `nodeModelOptions`) keeps its one `<select>`, its optgroups, its Load/Unload/Refresh/More buttons, `EngineModeControl`, the HexStrike suite row and the trigger. T2 changes only the **text** of each option and its detail line, and adds one status line. The backend adds four fields to catalog rows (all additive; old clients ignore them).

Backend fields (on `build_catalog` rows, `lmstudio_catalog`):

| Field | Graded row | Ungraded (discovered) row |
| --- | --- | --- |
| `filename` | the matched file name (`""` when absent) | the file name |
| `speed_label` | `speed_label(axes["speed_cost"])`: "Very fast / Fast / Moderate / Slower (estimate)", or "Speed unmeasured" when the score is 0 | always "Speed unmeasured" |
| `restriction_label` | `restriction_label(...)`: **"Refusal-reduced (publisher claim)"** when the seed has `refusal_reduced` or the artifact name carries `uncensored`, `abliterated`, `heretic` or `unfiltered`; otherwise **"Restrictions unverified"** | same rule on the file name |
| `rating_label` | "Provisional rating; local benchmark required" | (absent) |

`restriction_label` has exactly those two values. It never contains "uncensored", "no refusals", "unrestricted" or any guarantee: naming is a publisher claim, never a measured refusal guarantee, and the comparison document says "No model card establishes a universal zero-refusal model".

Row text (frontend, `nodeModelOptions`):

- **Option label:** `<file name without .gguf> · <weights> GiB · <quantization>`; a "★ " prefix stays for pinned rows exactly as RFC-0244 ships it. Weights are `weight_gb`, which the backend computes as bytes / 1024³ (`file_weight_gb`), so the unit is **GiB** and the label says GiB, never "GB".
- **Detail line (graded):** `Overall x.y · <display name> · <restriction_label> · <speed_label> · <rating_label>`.
- **Detail line (ungraded):** `Local GGUF · <restriction_label> · <speed_label> · not graded`.
- **Runtime rows** (configured runtimes) keep the RFC-0244 text.

**Live serving identity takes precedence over catalog data.** `servingModel(state)` already prefers `active_model` over `remote_model`; T2 extends that rule to the rows:

- A row is marked "Serving now" only when its `filename` (or native model key) matches the live serving identity after normalisation (lower case, non-alphanumerics removed, `.gguf` stripped). A catalog display name never marks a row.
- When the saved selection's row is not the serving row, the menu shows one extra status line under "Serving now": `Selected: <selected row label> · Serving: <live identity>`. The live identity is shown verbatim, never replaced by a catalog label.
- When the serving identity matches no row, the line reads `Serving: <live identity> (not in this list)`.
- `NodeAiInventory` is unchanged. It already reports native identities, and it is the ground truth the menu agrees with.

**Primary-source comparison document.** `docs/reviews/2026-10-28-investigative-model-comparison.md` (added by #682) stays the evidence record: exact artifacts, publisher evidence, local validation limits, revision and SHA-256 of each added catalog candidate. It is part of this RFC's deliverable. A test keeps the catalog and the document from drifting apart (T2). The document never promises zero refusals and does not invent current illicit-market facts.

### 3. Verified Unload and the stays-unloaded rule for background paths (T3, T4)

`POST /api/model/unload` becomes a verified release of the **selected local model only**.

- **LM Studio:** read the native inventory (`GET /api/v1/models`, `loaded_instances`), unload exactly the selected instance ids (`POST /api/v1/models/unload` with `instance_id`), then re-read the inventory and require that neither the model key nor any targeted instance remains. A 200 from the unload call is not evidence. A malformed or non-verifiable inventory never confirms.
- **Ollama:** find the selected model in `/api/ps`, send `keep_alive: 0`, re-read `/api/ps` and require it gone.
- **ANZU-managed llama.cpp:** stop the managed process (`backend.stop`), as today.
- **Remote hosts and unsupported runtimes** receive **no** unload request; the endpoint answers 409 with the reason. Unrelated models and other runtime applications are preserved: only the selected instance ids are named.
- **Never during inference.** The endpoint takes `MANAGER._request_lease.exclusive()`; when it is not acquired the answer is 409 "ANZU is answering or switching models; try Unload when it finishes". Failed or unverifiable release answers 409 or 502 with the runtime's own detail, leaves `MANAGER.state.loaded` true and does **not** set `manually_unloaded`.
- **Response.** The authoritative runtime snapshot (`runtime_activation_snapshot()`), plus a `release` object: `{"verified": true, "via": "lmstudio_instance" | "ollama_keep_alive_0" | "managed_process", "model": "<identity>"}`. `verified` is only ever true after the post-unload inventory check.
- **Stays unloaded against background paths until an explicit Load (amended 2026-11-03, CoS).** After a verified release `MANAGER.state.manually_unloaded` is true and exposed in `/api/model` and the status monitor's live keys. While it is set, a load whose origin is `background` (or unknown: fail closed) raises `ModelManuallyUnloaded` (a `RuntimeError` subclass with the text "Model was manually unloaded. Use Load to start a model again.") at `InferenceManager._load_impl`, the one function every load converges on, so no refresh, preload, `NINE_B_REWARM`, `RUNNING_MODELS` poll, background `ensure_runtime` or `ensure_vision`, escalation or context-reload path silently brings a model back. An **owner turn** is the owner's own act and respawns on demand (clearing the flag), exactly as after an idle unload; under `reflex_only` it loads nothing. The origin is carried by `load_origin.py` (see *Load origin: owner turn vs background* in the amendment). The flag lives for the backend process only; a restart is a new session. Explicit Load (`POST /api/model/load`, the runtime-profile activate route and the two LM Studio select routes) enters the `explicit_load` origin and clears the flag, in every engine mode.
- **Autoload callers.** Every `MANAGER.load(`, `MANAGER.ensure_runtime(` and `MANAGER.ensure_vision(` call site is classified in the table below and a static test fails when a new one appears unclassified (`agent/loop.py` and `media/analyze.py` reach `ensure_vision`, `persona/inference_context.py` reaches `ensure_runtime`).

| `MANAGER.load` call site | Behaviour while `manually_unloaded` |
| --- | --- |
| `main.py` startup restore (`_autoload_model`) | unaffected: a fresh process has the flag false |
| `inference/running_models.py` autoload branches (`RUNNING_MODELS._poll` and the `leave` branch of `decide`) | **skip silently** (origin `background`): T3 adds the guard; no error, no notice |
| `inference/running_models.py::RunningModels.decide` for the owner's `use` and `replace` actions | explicit owner click: enters the `explicit_load` origin, whose `MANAGER.load` clears the flag |
| `agent/loop.py`, `inference/model_escalation.py`, `inference/live_agent_suite.py`, `persona/owner_chat.py`, `persona/inference_context.py`, `media/analyze.py` | origin decides: inside an owner turn (`owner_turn_scope()`) they **respawn on demand** and clear the flag; reached from a background task (any task, timer or poll that did not enter `owner_turn_scope()`) they **propagate** `ModelManuallyUnloaded` and the existing handlers surface the text. T3 adds the scope at the owner-turn entries; these files are otherwise not edited. |
| explicit entry points (`api/model.py::load_model`, `api/model.py::choose_running_model` with action `use`, the activate and select routes via `hotswap.activate_runtime_profile`) | enter the `explicit_load` origin (T6's `explicit_owner_load()`); clear the flag |

**Frontend (T4).** The dropdown's Unload calls a new `unloadCurrentModel()` in `applyRuntimeProfile.ts`; it throws unless the snapshot says `loaded` false, `loading` false and `manually_unloaded` true **and** `release.verified` is true, and then dispatches `jarvis:model-state-changed` with the snapshot. `App.tsx` listens, applies the snapshot, and bumps a generation counter so an older in-flight `/api/model` poll that resolves afterwards cannot overwrite it. The RFC-0244 inventory cross-check after Unload (`/api/model/node-inventory?refresh=true`, "still resident … see More") **stays** as a second, independent check; its message is only reached when the runtime check and the inventory disagree. Success text: `Unloaded and verified: <model>. Other models on this node were left running.`

#### Reconciling Unload with RFC-0244

RFC-0244 says "Switching mode does not download models, silently enable cloud access or claim VRAM was released" and "Mode applies at request entry; changing it does not forcibly unload resident weights". RFC-0244's inventory is read-only and "never … stops other programs". The reconciliation:

- **Explicit Unload verifies release.** It is the only action in the system allowed to say a model was released, and it says so only with the runtime's own evidence (R5).
- **A mode switch never claims it.** `PUT /api/settings` with a new `engine_mode` calls neither `MANAGER.unload` nor `release_external_model`, does not set `manually_unloaded`, and its response and the `EngineModeControl` status text never contain "unloaded" or "released". A resident model stays resident across `hybrid`, `model_only` and `reflex_only`; the dropdown keeps showing it as "Serving now" (and, under `reflex_only`, notes that generation is off).
- **Unload works in every mode.** It is not gated on engine mode, because releasing VRAM never needs a model lane.
- **Inventory is not an actor.** The More view stays read-only (R3). Unload acts through the unload endpoint on the selected serving model, never through an inventory row, and never on a server application or process group.

### 4. Verified Load, and explicit Load in every mode (T5, T6)

**Verified Load (T5).** "Switching to a downloaded LM Studio model verifies its loaded instance before reporting success; advertising a downloaded model is insufficient."

- `lmstudio_server.ensure_local_lmstudio` reports `ok` only when the native loaded inventory (`_loaded_model_ids`) is readable **and** contains the requested model. The old fallback that accepted "advertised" when the inventory was unreadable is removed.
- `hotswap.apply_runtime_profile_to_settings` resolves the owner's hint to an advertised id with `resolve_advertised_model` and, for LM Studio only when the hint is not itself advertised, `lmstudio_server.resolve_lmstudio_artifact`, which maps a renamed GGUF only when the native display name **and** quantization both match exactly and exactly one model remains. When nothing resolves, the error is "Model '<hint>' is not loaded or is ambiguous in LM Studio at <host>:<port>. Available models: <list>. Select the exact model identifier and try Load again." and **settings are not changed**.
- `resolve_advertised_model` in `backends.py` no longer returns the single advertised model regardless of the hint, no longer uses `Path.stem` (which truncates `Qwen3.8-9B` to `Qwen3`), and returns a match only when exactly one advertised name matches the hint or its `.gguf`-stripped form; otherwise it returns the hint unchanged so the caller fails visibly.
- `activate_runtime_profile` calls `ensure_local_lmstudio` for a loopback LM Studio target before `MANAGER.load`, and a `ready` without `ok` raises with the runtime's detail.
- The dropdown reports `Serving: <live identity>` only after `/api/model` shows `loaded` and the identity; otherwise "Selection saved; no model is serving yet." (RFC-0244 text, unchanged).

**Explicit Load in every mode (T6, CoS ruling).** Today `engine_mode.require_model` guards both generation and loading, so under `reflex_only` `POST /api/model/load` answers 409, the activation helpers raise `ModelDisabledError` and the dropdown's Load button is disabled. T6 separates the two uses:

- `engine_mode.py` adds `explicit_owner_load()` (a context manager that enters T3's `load_origin` origin `explicit_load`) and `require_model_for_load(settings=None)`, which returns only when the current origin is `explicit_load` and otherwise behaves exactly as `require_model` (so under `reflex_only` an `owner_turn` or `background` origin is still refused, and the generation lanes are untouched).
- **The real guards, verified on `development` @ `a62bd454`.** `require_model` sits in `InferenceManager.chat`, `chat_stream`, `load`, `ensure_runtime` and `_load_impl`, and **not** in `_load_locked` (the 2026-10-30 text named `load` and `_load_locked`; that was wrong, and left as written an explicit Load under `reflex_only` would still be refused in `_load_impl`). T6 switches the three load-class guards `InferenceManager.load`, `InferenceManager.ensure_runtime` and `InferenceManager._load_impl` to `require_model_for_load`, plus `hotswap.apply_runtime_profile_to_settings`, `hotswap.activate_runtime_profile` and the `use`/`replace` branch of `running_models.RunningModels.decide`. An explicit owner Load therefore passes every one of them under `reflex_only`; the same three guards still refuse an unscoped caller (a persona or agent `ensure_runtime`, startup restore, `RUNNING_MODELS`). `InferenceManager.chat` and `chat_stream` stay on `require_model`, as do the front lanes, owner chat and the loop's `_run` early return (generation).
- **Only five route handlers enter the scope:** `api/model.py::load_model`, `api/model.py::choose_running_model` (only when the choice action is `use` or `replace`), `api/runtime_profiles.py::activate_profile`, `api/lmstudio.py::select_profile` and `api/lmstudio.py::select_discovered`. Because the scope is entered in the handler and exits with it, autoload paths running in other tasks never see it. Calling the helpers directly without the scope (startup, `RUNNING_MODELS`, persona brain activation, the agent loop) is blocked exactly as in RFC-0244.
- **The running-models offer card's "Use model" and "Use ANZU's model" are explicit owner Loads (CoS rulings).** Both are owner clicks, so both work under `reflex_only` through the same scope: `choose_running_model` enters `explicit_owner_load()` for actions `use` and `replace`, and `RunningModels.decide` calls `require_model_for_load` for those two actions. `replace` still stops the other server first, behind the card's existing confirm dialog, then loads ANZU's own model; it is not a generation call. **`leave` stays non-loading:** it only records the owner's choice, and its autoload branch stays on `require_model`/`model_enabled`, so under `reflex_only` (and while `manually_unloaded`) it loads nothing. `stop` is unchanged. The card (`RunningModels.tsx`) is unchanged: it has no mode disable, and any refusal is shown by its existing error line (R7). If the offer choice runs as a background job (RFC-0227 S1, see *Handoff order*), the job is started inside the handler, inherits the scope through the task's context copy, and a named test pins that.
- The dropdown's Load button is enabled in every mode. After a Load under `reflex_only` it says: `Loaded <identity>. Generation stays off in JEV/Laya only mode.` The model is resident and never called (R2).
- RFC-0244's two tests that assert the old blanket block are amended, not deleted: `test_reflex_only_load_controls_cannot_start_external_runtime` is split so its direct helper calls (`hotswap.activate_runtime_profile`, `hotswap.apply_runtime_profile_to_settings`, `RUNNING_MODELS.decide(..., "use")`) still raise `ModelDisabledError` when called without the scope, and its `model.load_model()` assertion moves to the new explicit-Load test. `test_reflex_only_blocks_model_entrypoints_and_explicit_front_provider` is unchanged (its `manager.load(engines)` is an unscoped call).

## Live-UI add-alongside reasoning pass (2026-10-14 standing order)

The model dropdown is live UI on `development` (RFC-0244, #685). Nothing below removes RFC-0244 behaviour.

| Existing RFC-0244 element | What this RFC does to it | Reasoning |
| --- | --- | --- |
| Trigger button, `triggerMeta`, `Switching model…` | unchanged | Wording and states are covered by the RFC-0244 restore tests. |
| `<select>` with "GGUF files on this node" and "Configured runtimes" optgroups | same control and groups; only option text changes (file, GiB, quantization) | A row is longer but is still one native `<option>`; no new widget. |
| "Serving now" status | unchanged; one additional status line under it only when selection and serving differ | The new line is add-only and appears only in the mismatch case, so the common case looks the same. |
| Detail line under the select | text extended with speed and restriction labels | Same element. |
| Load | enabled in every mode (R2); request path unchanged except the verified resolution in T5 | CoS ruling; the only RFC-0244 behaviour that changes, and it changes because the ruling says so. |
| Unload | same button, same position; the request is now a verified release; the inventory cross-check stays | The RFC-0244 safety net is kept; the new check is added in front of it. |
| Running-models offer card (`RunningModels.tsx`) | unchanged UI; the backend now lets "Use model" and "Use ANZU's model" through under `reflex_only` | The buttons never had a mode disable; only the 409 behind them changes (CoS rulings). `Leave alone` only records a choice and loads nothing; `Stop model` is unchanged. |
| Refresh, More, `NodeAiInventory` | unchanged | Read-only (R3). |
| `EngineModeControl` | unchanged | R4: a mode switch still never unloads or claims release. |
| HexStrike suite row, "All model settings →" link | unchanged | Not related. |
| Pin flag (★) and the catalog pin route | untouched | Out of scope; this RFC removes nothing RFC-0244 left. |

No `[hidden]`, `display: none` or removal of an RFC-0244 element is introduced. New CSS is limited to additive rules in `frontend/src/hud/nodeModels.css` (the existing dropdown stylesheet) for the mismatch line; `hud-v2.css` is not edited. Live audit (S-level, recorded in the T2/T4/T6 PRs, numbers not invented in advance): on Taco's PC at 390 px and 1366 px, open the menu with a long file name and the mismatch line visible and confirm the menu does not overflow and `Escape` still closes it.

## Amendment: Keep warm toggle and 5-minute idle unload

**Owner order (Taco, via CoS, 2026-11-03).** Two new top-right HUD controls: an **Unload model** button and a **Keep warm** toggle that defaults to **off**. D2 is already building them as a Taco-owned ticket (the *keep-warm ticket*, "KW" below). This amendment records the contract and how it composes with R1-R7 and T1-T6; it does not block KW. Revised 2026-11-03 after D1's review (unload-all, LM Studio TTL, turn-reset, load guards, 409 mapping) and CoS rulings (idle unload covers every model ANZU loaded, including on the owner's explicit Load; background paths never reload after an explicit Unload, an owner turn does).

**Source of truth for names.** When this amendment was written, no PR for KW existed on `Daan298261/Jarvis` (all states searched for keep warm, idle unload and `keep_alive`; only #655 (RFC-0228; final head in this PR's body) mentions an idle policy). The names below are proposals: `keep_warm` (bool, default `false`) and `idle_unload_seconds` (default `300`), both on `InferenceSettings`; `idle_unload_seconds` is the key RFC-0228 section "Idle unload + reload (normative)" already uses. **D2's PR sets the final names, files and test paths.** When it opens, its number goes into this PR's body and any difference is a one-line edit here, not a blocker.

### Contract (normative; each line has a named test below)

- **Keep warm OFF (default).** Every model ANZU loaded unloads after `idle_unload_seconds` (300 s) with no request lease, stream, tool loop or task stage in flight, and respawns on demand on the next **owner turn** (see *Load origin*). "ANZU loaded" includes a model ANZU loaded because of the owner's explicit Load (dropdown Load, activate and select routes, the offer card's "Use ANZU's model"): that Load makes it ANZU-loaded, so the idle unload covers it (CoS ruling). Scope: the front responder, the 9B worker, the 27B coder, and any LM Studio, Ollama or llama-server model ANZU loaded.
- **Exemptions (the only ones).** (a) A model ANZU did not load and never sends a request to, such as the studio's `bgm-ingest-9b`: ANZU never sends it a request, an unload or a `keep_alive` (CoS/PG ruling; enforced by a deny constant in the one Ollama request helper below, and by the unload-all enumeration, which lists only ANZU's own ledger and managed processes). (b) An LM Studio instance the owner started himself and ANZU did not load stays under RFC-0225 / RFC-0228 managed-mode consent (never unloaded unless managed mode is on). An Ollama model the owner started himself is not unloaded by an ANZU call, but because ANZU sends `keep_alive` on every Ollama request it makes (next bullet), Ollama's own expiry applies to it once ANZU routes a request there.
- **Keep warm ON.** Today's always-warm behaviour: no idle timer for any model. ANZU-originated Ollama requests pin (`keep_alive: "-1"`), so "always warm" no longer depends on a 24 h expiry. Turning it on re-pins **every currently loaded model**: Ollama models get a native `"-1"` request at once, and LM Studio instances ANZU loaded with a TTL are re-pinned as described under *LM Studio TTL*. Turning it off resumes the idle clocks (measured from each model's last use).
- **`keep_alive` on EVERY Ollama request ANZU makes.** Ollama applies its server default (5 min) to a request that omits the field, so omission would shorten Keep warm ON and lengthen/shorten the OFF window. Every native Ollama request ANZU sends (`/api/generate`, `/api/chat`, including warms, refreshes, preloads and the keep-alive touch below) carries `keep_alive`: `f"{idle_unload_seconds}s"` (`"300s"`) with Keep warm OFF, `"-1"` with it ON. The explicit unload (`keep_alive: 0`) is the only other value. This replaces the 2026-10-30 draft wording that said models ANZU did not load get no `keep_alive` with Keep warm on. **One helper sends them:** new `backend/app/inference/engine_requests.py::ollama_request(host, port, path, body, *, origin)` (owner: T3; KW sets the values in place at its two call sites, `gpu_prefer.ensure_ollama_gpu` and `ollama_runtime.ensure_local_ollama`, and T3 moves them and `running_models.RunningModels.decide`'s unload onto the helper). The helper injects the policy `keep_alive`, refuses any request naming `bgm-ingest-9b`, and applies the *Load origin* rule to requests that can load a model.
- **The OpenAI-compatible path cannot carry it.** ANZU chats with Ollama through `providers/base.py::ModelProvider.chat` and `chat_stream` (`POST /chat/completions` on `/v1`). Ollama's `/v1` endpoint does not accept `keep_alive` (Ollama maintainers, ollama/ollama issue 9355: "The OpenAI endpoint doesn't support `keep_alive`"), and whether it resets a resident model's expiry depends on the Ollama version. So ANZU makes the policy version-independent with a **keep-alive touch**: when an Ollama-served turn finishes, `ollama_request` sends `POST /api/generate {"model", "prompt": "", "keep_alive": <policy>}` for each Ollama model that turn used, only if `/api/ps` lists it (a touch never loads). D2 verifies the `/v1` behaviour on Taco's Ollama version in the live audit; the touch stays either way.
- **LM Studio TTL.** An ANZU-originated LM Studio load carries a TTL equal to the policy: Keep warm OFF passes `ttl = idle_unload_seconds` (`lms load --ttl 300` in `lmstudio_server.ensure_local_lmstudio` and `gpu_prefer.lmstudio_cli_load_args`, and the `ttl` field in the REST load payloads of `gpu_prefer._lmstudio_rest_load`; `lmstudio_context` already re-applies a recorded `--ttl` when it rebuilds `lms load`, so a re-load keeps the policy value). Keep warm ON passes no TTL (pinned). ANZU's own idle timer and verified unload remain the enforcer; the TTL is the backstop when ANZU is down. Turning Keep warm ON re-pins instances ANZU loaded: it re-issues the load without a TTL (a verified unload and reload at a moment with no lease held if the installed LM Studio cannot change a TTL in place, with the loading state visible). Owner-started instances are never reloaded (managed-mode rule).
- **No 24 h keep-alive survives.** Jarvis set `keep_alive: "24h"` in `gpu_prefer.ensure_ollama_gpu` and `ollama_runtime.ensure_local_ollama` earlier today, and KW removes it. RFC-0228 section "Idle unload + reload (normative)" carries the same rule for its 9B timer and has no separate 9B timeout.
- **The idle clock resets on any turn that uses the model.** Any owner or agent turn resets the idle clock, at start and at finish, of each model that turn uses (a turn served only by the front responder resets the front responder's clock and no other). This is per model by design: a model nothing used for 300 s unloads even while another model is busy. Lease holds, streams, tool loops and task stages also count as use. A background refresh or touch is not a turn and never resets a clock by itself (see *Refresh vs idle*).
- **Refresh vs idle (CoS K2 mirror).** RFC-0245's lease refresh may never stretch a model past the idle window: it runs only while a child task stage is actively running (not while a lease is merely held, not while the parent is `waiting`), and each tick re-checks that the target is listed in `/api/ps` and that no explicit Unload happened. When the parent enters `waiting` the refresh stops and the idle clock counts from the last model use, so the 27B unloads `idle_unload_seconds` after that use, not 2x. The setting persists across restart through the merge-safe `save_settings`; a settings file without the key means OFF.

### Load origin: owner turn vs background (CoS ruling)

After an **explicit Unload**, no **background** path reloads anything until an explicit Load; an **owner turn** respawns on demand, because it is the owner's own act, exactly as after an idle unload. The stays-unloaded guard must tell the two apart, and it fails closed.

- **How the origin is carried.** New `backend/app/inference/load_origin.py` (owner: T3) holds a `ContextVar` with three values: `explicit_load` (entered by T6's `explicit_owner_load()`, the five route handlers), `owner_turn` (`owner_turn_scope()`, entered once at each owner-turn entry: the handlers that start a reply or task for an owner message, enumerated by a static scan so a new entry fails the test until classified) and `background` (`background_scope()`). `current_origin()` returns `background` when the variable is unset or holds anything else: **an unknown origin is background**. Every timer or spawned task enters `background_scope()` as its first statement, because `asyncio` copies the context into a new task: the refresh, preload's late reconcile task, `NINE_B_REWARM`, the `RUNNING_MODELS` poll, recovery, the keep-alive touch's idle path and every `asyncio.create_task` started from inside an owner turn. A test proves a task spawned inside an owner turn is still `background`.
- **Where it is enforced (two choke points).** (1) `InferenceManager._load_impl`, the one function every load converges on (`load`, `ensure_runtime` and therefore `ensure_vision`, and `release_vision` all reach it through `_load_locked`): first statements are `require_model_for_load(settings)` and the manual-unload check. (2) `engine_requests.ollama_request` and the LM Studio load helper for direct-HTTP warms, which never touch `_load_impl`.
- **Rule table.**

| Origin | `manually_unloaded` true (explicit Unload) | Idle-unloaded | `reflex_only` |
| --- | --- | --- | --- |
| `explicit_load` | loads, clears the flag | loads | loads weights only (R2) |
| `owner_turn` | **respawns on demand**, clears the flag | respawns on demand | loads **nothing** (generation off; RFC-0244 bounded reply) |
| `background` (or unknown) | raises `ModelManuallyUnloaded` at `_load_impl`; a direct-HTTP warm that would load is refused with the same text | background warms only touch a model `/api/ps` or the native inventory already lists; existing RFC-0228 rules stand (a timer never reloads an idle-unloaded 9B) | refused as in RFC-0244 |

- **Why `_load_impl` and not `_load_locked`.** `_load_locked` wraps `_load_impl` and is its only caller, so both see every load. The check goes into `_load_impl` because that is where `require_model` already sits on `development`, so the mode check and the manual-unload check are one place, and `manual_resume` threads through `load` → `_load_locked` → `_load_impl`. A refusal raised first in `_load_impl` does not mutate state: `_load_locked`'s cleanup only rewrites `loaded`, `provider` and `last_error` when `state.loading` is true, and the guard runs before `loading` is set.

### How it composes with this RFC

| Case | Behaviour | Why |
| --- | --- | --- |
| HUD **Unload model** button | An explicit owner Unload of **everything ANZU loaded**: it calls the new `POST /api/model/unload-all` (below), not the dropdown's single-model `POST /api/model/unload`. | Taco's order is one click, every model. |
| Dropdown Unload (T3, T4) | Unchanged: `POST /api/model/unload`, the selected local model only. | The two actions stay distinct. |
| Idle unload | Not a manual unload: `manually_unloaded` stays false; recorded as RFC-0228's `engine_coexistence.idle_unloaded()`. Reports "unloaded" only after the runtime's own post-unload evidence (R5); a failed release is shown once and the next attempt waits a full window. | Policy, not an owner decision. |
| Owner turn after an idle or explicit Unload | Respawns on demand through RFC-0225 `prepare_engine_for` with the existing "Loading model…" state (origin `owner_turn`). | The owner asked for a reply. |
| Background path after an explicit Unload | Never reloads (refresh, preload started by a timer or recovery, `NINE_B_REWARM`, background `ensure_runtime`/`ensure_vision`, direct-HTTP warms, the `RUNNING_MODELS` poll). | CoS ruling; fail closed. |
| Unload with nothing loaded | 409 with a visible reason ("Nothing to unload: <model> was unloaded after 5 minutes idle and loads again on your next request"); `manually_unloaded` not set. | R7. |
| Unload or toggle refused (a model request in flight, runtime error, settings write failed) | 409 or 502 with the runtime's text on the control; the toggle reverts and shows the error. | R7. |
| Unload while a RFC-0245 pipeline holds an engine lease | Not refused for the lease: unload-all stops the refresh, releases the lease through `release_request_lease`, calls `large_prompt.on_owner_unload(models)` (0245-S4) which cancels the running child and remaining parts through `on_parent_cancel`, fails the parent visibly and sets `preload_status = "released:owner_unload"`. A model request actually in flight still returns 409. | #665 (RFC-0245; final head in this PR's body), section "Owner Unload and the lease". |
| `reflex_only` (RFC-0244) | Idle unload and unload-all still run (releasing VRAM needs no model lane). An owner turn loads nothing; only an explicit Load brings a model back. | R2, R4. |
| `model_only` and `hybrid` | Owner turns respawn on demand (`model_only` still excludes JEV and Laya). | RFC-0244 routing unchanged. |
| Mode switch | Never unloads and never claims release (R4). | R4. |
| Toggle ON → OFF | Idle measured from each model's last use. | One clock. |
| Startup restore (`_autoload_model`) | Unchanged; a fresh process has the flag false and the idle clock starts at load. | Not part of this order. |

### Unload-all (owner: T3; HUD wiring: KW; function in T4)

- **Endpoint:** `POST /api/model/unload-all`, body empty. It is **owned by T3** (route in `api/model.py`, implementation `model_release.release_all_anzu_loaded(settings)`, verified release per model through `release_external_model`). `POST /api/model/unload` stays single-model and unchanged. KW's HUD button calls the endpoint through `unloadAllModels()` in `applyRuntimeProfile.ts` (T4 adds it next to `unloadCurrentModel()`); if KW lands first it adds the route with the release helpers on `development` and the response shape below is the contract either way, so T3 only swaps the body to the verified helper.
- **What it releases:** the selected serving model (as the explicit dropdown Unload would) plus every model in RFC-0225's `anzu_loads` ledger section and every ANZU-managed llama-server process (worker and front responder): Ollama models by native `keep_alive: 0` and an `/api/ps` re-check, LM Studio instances by instance id and an inventory re-check, managed llama-server by `backend.stop`. It never touches an owner-started model that is not the selected one, and never `bgm-ingest-9b` (deny constant, test).
- **Lease and mode:** it takes `MANAGER._request_lease.exclusive()` (409 "ANZU is answering or switching models; try Unload when it finishes" when not acquired), works in every engine mode, and sets `manually_unloaded` when the active model was released and verified.
- **Response (never silent about partial failure):** `200` when every listed model verified; `207` with the same body when some failed; `409` when nothing was attempted. Body: `{"results": [{"model", "backend", "via", "verified": bool, "error": str | null}], "released": n, "failed": m, "skipped": [{"model", "reason"}], "snapshot": <runtime snapshot>}`. The HUD shows one line per model (`Unloaded and verified: <model>` or `Could not unload <model>: <error>`) and a summary; a `207` is never rendered as success.

### Live-UI add-alongside reasoning pass (2026-10-14 standing order) for the two controls

`HudShell.tsx` renders `.hud-top-right` with `HelpTrigger`, the Admin button (with its setup dot), the Classic toggle and `HudModelSelector`.

| Existing element | What KW does | Reasoning |
| --- | --- | --- |
| `HelpTrigger`, Admin button and setup dot, Classic toggle, `HudModelSelector` | unchanged, same order, same handlers | Nothing live is removed or re-parented. |
| `.hud-top-right` reflow rules when the model menu is open (`.hud-model-trigger.open`) | unchanged; the new controls carry the existing `hud-icon-btn` class, so the existing reflow rule orders them with the other buttons | No existing CSS rule is edited; new rules are additive and live in a new stylesheet or `nodeModels.css`, never `hud-v2.css`. |
| Dropdown Unload (T4) and `EngineModeControl` | unchanged | The HUD button is a second entry point to a different (all-models) endpoint. |
| Persona, WebGL, presence | untouched | Astra's. |

New controls are two additive children of `.hud-top-right`, rendered by one new component mounted by one added line in `HudShell.tsx`. No `[hidden]`, `display: none` or removal is introduced. Live audit (recorded in the KW PR, numbers not invented in advance): at 390 px and 1366 px the row does not overflow its `max-width` and both controls are reachable with the menu open and closed.

### Conformance tests (named here; D2's PR sets the final paths)

Backend, `tests/test_keep_warm_idle_unload.py` (KW): `test_keep_warm_defaults_off_and_idle_window_is_300`; `test_idle_unload_after_300s_for_every_anzu_loaded_model` (parametrised: front responder, managed llama-server 9B, Ollama 27B coder, ANZU-loaded LM Studio instance, and a model ANZU loaded on an explicit owner Load); `test_idle_unload_leaves_models_anzu_did_not_load` (including `bgm-ingest-9b`: zero requests of any kind); `test_idle_unload_waits_for_lease_stream_and_task`; `test_any_turn_using_a_model_resets_its_idle_clock` (an owner turn served only by the front responder resets the front clock and leaves the 27B's running); `test_keep_warm_on_never_idle_unloads_and_cancels_timers`; `test_keep_warm_off_resumes_idle_clock_from_last_use`; `test_toggle_on_repins_every_loaded_model_with_minus_one` (Ollama native `"-1"` to each loaded model, including one warmed with `"300s"`); `test_every_ollama_request_path_sets_keep_alive` (a request spy over `ensure_ollama_gpu`, `ensure_local_ollama`, the keep-alive touch, preload, refresh and the unload paths: each body carries `keep_alive` = `"300s"` OFF, `"-1"` ON, or `0` for an unload; plus a static scan that no `/api/generate` or `/api/chat` call in `backend/app` bypasses `ollama_request`); `test_ollama_v1_turn_is_followed_by_a_keep_alive_touch_only_if_resident` (the touch carries the policy value and never loads); `test_lmstudio_load_ttl_300_when_off_none_when_on` (CLI `--ttl 300` and the REST `ttl` field when OFF; neither when ON; a `lmstudio_context` rebuild keeps the value); `test_keep_warm_on_repins_lmstudio_instances_without_ttl`; `test_no_ollama_24h_keep_alive_remains` (static scan of `backend/app` plus the payloads); `test_keep_warm_setting_persists_across_restart`; `test_idle_unload_does_not_set_manually_unloaded`; `test_idle_unload_failure_is_surfaced_not_reported_unloaded`; `test_poll_autoload_does_not_undo_idle_unload`.

Backend, `tests/test_rfc0242_model_unload.py` (T3): `test_unload_all_releases_every_anzu_loaded_model_and_verifies` (front responder, 9B, 27B, an Ollama and an LM Studio model; each verified by `/api/ps` or the native inventory); `test_unload_all_partial_failure_returns_207_with_per_model_results` (one release fails: that model is `verified: false` with its error, the others are released, the status is 207, never 200); `test_unload_all_never_touches_owner_started_or_studio_models` (`bgm-ingest-9b` and an owner-started LM Studio instance get zero requests); `test_unload_all_works_in_every_engine_mode_and_refuses_while_answering`; `test_unload_all_sets_manually_unloaded_only_after_verified_active_release`; `test_unload_endpoint_stays_single_model` (`POST /api/model/unload` untouched by unload-all); `test_unload_with_nothing_loaded_returns_409_reason_and_sets_no_flag`.

Backend, `tests/test_rfc0242_load_origin.py` (T3, new): `test_no_background_warm_after_explicit_unload` (parametrised: the lease refresh, a preload started by a timer or recovery, `NINE_B_REWARM`, background `ensure_runtime`, background `ensure_vision`, a direct-HTTP Ollama warm and an LM Studio load: each raises `ModelManuallyUnloaded` or is refused with zero provider, process or HTTP load calls); `test_owner_turn_after_explicit_unload_respawns_on_demand` (the owner-turn origin loads once and clears `manually_unloaded`); `test_owner_turn_under_reflex_only_after_explicit_unload_loads_nothing`; `test_unknown_origin_counts_as_background` (no scope, a stray value, and a task spawned inside an owner turn without `background_scope()` all fail closed); `test_background_task_spawned_in_owner_turn_stays_background`; `test_ensure_runtime_and_ensure_vision_cannot_respawn_background_after_explicit_unload` (managed backend: zero `backend.start`); `test_explicit_load_origin_clears_flag`; `test_owner_turn_entries_are_classified` (static scan, as the call-site table); `test_every_manager_load_caller_is_classified` (extended in `tests/test_rfc0242_load_callers.py` to `MANAGER.load(`, `MANAGER.ensure_runtime(` and `MANAGER.ensure_vision(`, including `agent/loop.py`, `media/analyze.py` and `persona/inference_context.py`).

Frontend, `frontend/keep-warm-hud.test.mjs` (`npm run test:keep-warm-hud`, KW): the toggle renders OFF by default; the Unload model button calls `unloadAllModels()` and renders one line per model, never success on a 207; a refused toggle write reverts and shows the error; every existing `.hud-top-right` child is still present, in order. **CI:** backend step **"Run model and security regression tests"** (append the three files above) and **"Run full backend suite"**; frontend, one new append-only `frontend-build` step **"Keep warm HUD tests (keep-warm ticket)"**.

**Ticket card (Taco-owned, already in flight).** *KW:* lane D2; model Grok 4.6 · fast mode off (recorded for the card; D2 is already building it and the model is not a gate); depends none. Files: `backend/app/config.py` (`keep_warm`, `idle_unload_seconds`), the idle-timer owner chosen by D2's PR, `backend/app/inference/gpu_prefer.py` and `backend/app/inference/ollama_runtime.py` (the `keep_alive` and LM Studio `ttl` values above), `frontend/src/hud/HudShell.tsx` (one mount line), the new HUD component, its stylesheet and the test files. **Ordering:** KW lands before T3, T4 and T6 on every file they share (it is in flight, and "0242 tickets go last" already covers it). After it lands, T3 moves the Ollama call sites onto `ollama_request`, adds `load_origin.py` and the `_load_impl` guard, and re-points the idle-unload release call at `model_release.py` if KW used an earlier helper.

## Slices (one ticket each, one developer each, fast off)

Lane for every ticket: **D2** (the #682 code rework is a development merge into `cursor/model-menu-clarity-99ea`, no rebase; see *Rework of #682*). Tickets can use #682's code as the starting point but must drop every item in the supersession table.

### Rework of #682 (D2 procedure, normative)

1. In the #682 branch, merge `origin/development` (a merge commit; no rebase, no force-push).
2. `docs/rfcs/0242-model-identity-and-menu-clarity.md` conflicts add/add: **take `development`'s file** (this RFC). #682's original text is superseded.
3. `frontend/src/hud/HudModelSelector.tsx` conflicts: **take `development`'s dropdown** and re-apply only the T2, T4 and T6 edits below. Delete `frontend/src/hud/modelSlots.ts`, the bind endpoints, `bindLmStudioProfile` / `bindDiscoveredGguf`, and their tests.
4. Start only after the batch has landed (see *Handoff order*): merge `development` in again at that point, so every shared file is on top of its batch chain.
5. **#682 stays the single code PR.** Land the rework as **one commit per ticket** on its branch (T1 → T2, T3 → T4, T5 → T6; the pairs are ordered). Every commit must pass its own ticket's CI step alone. No rebase, no force-push, no split PRs.

### Handoff order on shared files

"A → B" means A merges first. **RFC-0242's tickets go last on every shared file** (CoS ruling, 2026-10-30), after each file's chain as the batch specs currently read it. The batch PRs are #652 (RFC-0225; final head in this PR's body), #655 (RFC-0228; final head in this PR's body), #664 (RFC-0232; final head in this PR's body), #665 (RFC-0245; final head in this PR's body), #668 (RFC-0233; final head in this PR's body) and #670 (RFC-0211; final head in this PR's body). No batch spec is edited by this RFC: each already names its own chain, and RFC-0242 appends after it. The tickets assume those chains have landed on `development`; D2 merges `development` into #682 once they have and works on top of the merged files. `.github/workflows/pr-tests.yml` and `frontend/package.json` are append-only for every ticket and batch PR, in any order; on a conflict, merge `development` in (merge commit).

| File | Chain (batch chain as each spec reads today, then 0242) | Notes |
| --- | --- | --- |
| `backend/app/inference/lmstudio_catalog.py` | 0242-T1 → 0242-T2 | No batch spec edits it. |
| `backend/app/inference/lmstudio_graded_profiles.json` | 0228-S1 → 0242-T1 | 0228-S1 binds the existing Defiant row to `fable_9b`; T1 adds identity fields to every seed on top of that. |
| `backend/app/inference/backends.py` | 0230-S2 → 0225-S2 → 0242-T5 | T5 touches only `resolve_advertised_model`. |
| `backend/app/inference/lmstudio_server.py` | 0225-S3 → 0228-S2 → 0242-T5 | T5 touches the readiness decision and adds `resolve_lmstudio_artifact`. |
| `backend/app/inference/hotswap.py` | 0225-S3 → 0242-T5 → 0242-T6 | 0225-S3 is the batch's only owner. |
| `backend/app/inference/manager.py` | 0225-S3 → keep-warm ticket → 0228-S2 → 0242-T3 → 0242-T6 | T3: `manually_unloaded`, the origin check in `_load_impl`, `unload(release_external=)`. T6: `require_model_for_load` in `load`, `ensure_runtime` and `_load_impl`. |
| `backend/app/inference/running_models.py` | 0225-S3 → 0227-S1 → 0242-T3 → 0242-T6 | T3: skip guard on autoload branches (origin `background`), the unload moves onto `ollama_request`. T6: `require_model_for_load` for `use`/`replace`. |
| `backend/app/api/model.py` | 0225-S3 → 0227-S1 → 0242-T3 → 0242-T6 | T3: `unload_model`, `unload_all_models` (`POST /api/model/unload-all`), the `explicit_load` clear in `load_model`. T6: scope and the 409 mapping in `load_model` and `choose_running_model`. |
| `backend/app/inference/load_origin.py`, `backend/app/inference/engine_requests.py` (new) | 0242-T3 only | T3 creates both; KW edits the two `keep_alive` call sites first and T3 moves them onto `ollama_request`. T6's `explicit_owner_load()` composes `load_origin`. |
| `backend/app/inference/gpu_prefer.py`, `backend/app/inference/ollama_runtime.py`, `backend/app/inference/lmstudio_server.py` (keep-warm values) | 0225-S3 → keep-warm ticket → 0228-S2 → 0242-T3 | KW: `keep_alive` and `ttl` values; T3: call sites onto `ollama_request`. |
| `backend/app/api/runtime_profiles.py` | 0227-S3 → 0242-T6 | T6 enters the scope in `activate_profile` only. |
| `backend/app/api/lmstudio.py`, `backend/app/engine_mode.py` | 0242-T6 only | No batch spec edits them (the batch cites `engine_mode.py` read-only). |
| `backend/app/inference/status_monitor.py`, `backend/app/inference/model_release.py` (new) | 0242-T3 only | RFC-0230 lists `status_monitor.py` as read-only. |
| `frontend/src/api.ts` | 0230-S0 → 0218-S3 → 0227 → 0245-S6 → 0233-S6 → 0242-T2 | T2 adds type fields only. |
| `frontend/src/hud/HudModelSelector.tsx` | 0227-S3 → 0242-T2 → 0242-T4 → 0242-T6 | 0227-S3's row there is a slot-restore edit that RFC-0244 made obsolete; D2 works on whatever `development` holds after the batch, and does not re-add slots. |
| `frontend/src/hud/HudShell.tsx` | keep-warm ticket only | One added mount line in `.hud-top-right`; no 0242 ticket edits it. |
| `frontend/src/hud/nodeModelOptions.ts`, `frontend/src/hud/nodeModels.css`, `frontend/src/hud/applyRuntimeProfile.ts`, `frontend/apply-runtime-profile-api-stub.mjs` | 0242 only (T2, T2, T4, T4) | No batch spec edits them. |
| `frontend/src/hud/modelMenuStatus.ts` | 0242-T4 → 0242-T6 | |
| `frontend/src/App.tsx` | 0225-S5 → 0225-S3 → #670 (RFC-0211; final head in this PR's body) → 0242-T4 | T4's generation guard goes into the `/api/model` poll effect on top of 0225-S5's state-machine edit. |
| `tests/test_rfc0244_engine_modes.py` | 0242-T6 only | Amends two tests as stated in §4. |
| `docs/rfcs/README.md` | this PR adds one row; no ticket edits it | |

### T1: Family identity and absent candidates

**Model:** Grok 4.5 · **fast mode off** · **Lane:** D2 · **Depends:** 0228-S1 on the graded JSON (batch landed).

| File | Change |
| --- | --- |
| `backend/app/inference/lmstudio_catalog.py` | `QUANT_RE` keeping the full variant; `_match_profile` identity and required-substring checks; `select_catalog_profile` refuses an unmatched row; no new endpoint |
| `backend/app/inference/lmstudio_graded_profiles.json` | `match_identity_any` / `match_required_substrings` on every graded seed; the two research seeds (HauhauCS Q6_K, Dolphin Nemo Q4_K_M) with their `huggingface` provenance and `refusal_reduced` |
| `tests/test_lmstudio_catalog.py` | the named tests below (existing file) |

Tests (`tests/test_lmstudio_catalog.py`):
- `test_generic_refusal_and_quant_tags_cannot_substitute_model_identity`
- `test_named_variants_do_not_match_another_variant_in_the_same_family`
- `test_absent_catalog_model_cannot_be_selected_or_loaded` (an unmatched graded row: `select_catalog_profile` raises `ValueError`, no runtime profile is written, `activate_runtime_profile` is never reached through `POST /api/lmstudio/catalog/{id}/select`)
- `test_every_graded_seed_declares_family_identity` (static over the JSON: each graded seed has `match_identity_any`, or its `match_substrings` are exact file names)
- `test_quantization_keeps_full_variant` (parametrized: `Q4_K_M`, `Q6_K`, `IQ3_M`, `BF16`, `F16`, `FP8`; `Q4` inside a word is ignored)
- `test_research_candidates_are_unbenchmarked_and_carry_provenance` (revision, SHA-256, license, byte size present; `overall == 0`; no default promotion)

**CI:** step **"Run model and security regression tests"** in `.github/workflows/pr-tests.yml` (append `tests/test_lmstudio_catalog.py` to its file list) and **"Run full backend suite"**.

**Acceptance:**
- [ ] A 27B Heretic, Gemma Aggressive or arbitrary Q4 file cannot match a different 9B or 4B family row.
- [ ] An absent candidate cannot load, from any caller of `select_catalog_profile`.
- [ ] Full quantization names survive matching and display.
- [ ] The two research candidates exist unbenchmarked, with provenance, and nothing is downloaded or promoted.
- [ ] No new route is added and no bind endpoint exists anywhere.

### T2: Honest dropdown rows, live-identity precedence, comparison document

**Model:** Grok 4.5 · **fast mode off** · **Lane:** D2 · **Depends:** T1 (shared `lmstudio_catalog.py`).

| File | Change |
| --- | --- |
| `backend/app/inference/lmstudio_catalog.py` | `filename`, `speed_label`, `restriction_label`, `rating_label` on graded and ungraded rows; `speed_label()` and `restriction_label()` helpers |
| `frontend/src/api.ts` | optional `filename`, `speed_label`, `restriction_label`, `rating_label` on `LmStudioGradedProfile` and `LmStudioUngradedModel` |
| `frontend/src/hud/nodeModelOptions.ts` | row label and detail text (§2); `servingOptionKey` and `selectionMismatch` helpers |
| `frontend/src/hud/HudModelSelector.tsx` | one added mismatch status line under "Serving now"; nothing removed |
| `frontend/src/hud/nodeModels.css` | additive rules for the mismatch line |
| `docs/reviews/2026-10-28-investigative-model-comparison.md` | kept as the evidence record (added by #682); T2 updates it only if a catalog number changes |
| `tests/test_lmstudio_catalog.py`, `tests/test_rfc0242_comparison_doc.py` (new), `frontend/node-model-options.test.mjs`, `frontend/hud-model-selector-render.test.mjs` | named tests below |

Tests:
- `tests/test_lmstudio_catalog.py::test_exact_family_gets_artifact_and_honest_behavior_metadata`
- `tests/test_lmstudio_catalog.py::test_ungraded_file_has_unmeasured_speed_and_unverified_restrictions`
- `tests/test_lmstudio_catalog.py::test_restriction_label_has_two_values_and_never_guarantees`
- `tests/test_lmstudio_catalog.py::test_graded_rows_are_labelled_provisional`
- `tests/test_rfc0242_comparison_doc.py::test_document_records_revision_and_sha256_for_each_added_candidate` (the revision and SHA-256 in the document equal the `huggingface` block in the seed JSON for both research candidates)
- `tests/test_rfc0242_comparison_doc.py::test_document_makes_no_zero_refusal_promise` (contains the "No model card establishes a universal zero-refusal model" sentence; does not contain "guarantee" or "zero refusals" outside publisher-claim quotes)
- `frontend/node-model-options.test.mjs`: `option rows show the actual file, GiB, quantization, speed estimate and restriction label`; `weights are labelled GiB never GB`; `serving identity precedes a catalog label that differs`; `a row is marked serving only by file or native key, never by display name`
- `frontend/hud-model-selector-render.test.mjs`: `the menu shows Selected and Serving when they differ and the live identity verbatim`; `the menu shows a not-in-this-list line when serving matches no row`; `the inventory view contains no button and makes only GET requests` (R3); `choosing a row sends no activating request` (R1)

**CI:** existing frontend steps **"Node model dropdown identity tests (RFC-0244)"** and **"HUD model menu status tests (RFC-0244 restore)"** (the `test:hud-model-menu` script covers the render test); backend: **"Run model and security regression tests"** (append `tests/test_rfc0242_comparison_doc.py`) and **"Run full backend suite"**.

**Acceptance:**
- [ ] Every row shows file, GiB, quantization, speed and restriction labels; labels never promise zero refusals.
- [ ] The live serving identity is shown verbatim and wins over any catalog label.
- [ ] The comparison document records exact artifacts, published evidence and local validation limits, and the catalog numbers match it.
- [ ] RFC-0244's dropdown elements are all still present (existing render tests pass unchanged).
- [ ] Live audit on Taco's PC recorded in the PR.

### T3: Verified native release, unload-all and the stays-unloaded origin rule (backend)

**Model:** Grok 4.6 · **fast mode off** · **Lane:** D2 · **Depends:** 0225-S3, 0228-S2 and 0227-S1 on `manager.py`, `running_models.py` and `api/model.py` (batch landed), and the keep-warm ticket (KW) on `gpu_prefer.py`, `ollama_runtime.py` and `lmstudio_server.py`.

| File | Change |
| --- | --- |
| `backend/app/inference/model_release.py` (new) | `release_external_model(settings, backend, model)`: LM Studio instance unload and inventory re-check, Ollama `keep_alive: 0` and `/api/ps` re-check, loopback only; `release_all_anzu_loaded(settings)` (the unload-all set, per-model verified results) |
| `backend/app/inference/load_origin.py`, `backend/app/inference/engine_requests.py` (new) | `owner_turn_scope()`, `background_scope()`, `current_origin()` (unknown is `background`); `ollama_request(...)` (policy `keep_alive`, `bgm-ingest-9b` deny constant, origin rule for loading requests) |
| `backend/app/inference/manager.py` | `InferenceState.manually_unloaded`; the manual-unload and origin check as the first statements of `_load_impl` (with `manual_resume` threaded through `load` → `_load_locked` → `_load_impl`), raising `ModelManuallyUnloaded` for a `background` origin; `unload(*, release_external=False)`; live-state keys |
| `backend/app/api/model.py` | `unload_model`: exclusive lease, 409 and 502 mapping, `release` object in the response; `unload_all_models` (`POST /api/model/unload-all`: exclusive lease, 200/207/409, per-model results, calls `large_prompt.on_owner_unload` when a RFC-0245 pipeline holds a lease); `load_model` enters the `explicit_load` origin |
| the owner-turn entries (found by a static scan of the handlers that start a reply or task for an owner message: owner chat and owner task creation) | each enters `owner_turn_scope()` once; no other edit |
| `backend/app/inference/status_monitor.py` | `manually_unloaded` added to the live keys |
| `backend/app/inference/running_models.py` | autoload branches (`_poll`, the `leave` branch of `decide`) skip while `MANAGER.state.manually_unloaded` (origin `background`); the `use`/`replace` load runs in the `explicit_load` origin; the unload request goes through `ollama_request` |
| `tests/test_rfc0242_model_unload.py` (existing file), `tests/test_rfc0242_load_callers.py` (new), `tests/test_rfc0242_load_origin.py` (new) | named tests below, plus the unload-all, load-origin and `ensure_*` tests named in the 2026-11-03 amendment (section "Conformance tests") |

Tests (`tests/test_rfc0242_model_unload.py` unless noted):
- `test_lmstudio_unloads_exact_selected_instance_and_preserves_other_model`
- `test_success_response_is_insufficient_if_instance_still_loaded`
- `test_malformed_inventory_never_confirms_unload`
- `test_verified_external_release_pauses_manager_and_clears_active_identity`
- `test_remote_or_unsupported_runtime_never_gets_an_unload_request` (parametrized)
- `test_ollama_releases_selected_model_without_loading_another`
- `test_failed_unload_keeps_manager_loaded_and_does_not_pause`
- `test_managed_unload_stops_process_and_blocks_automatic_reload`
- `test_unload_endpoint_refuses_while_answering`
- `test_unload_endpoint_returns_authoritative_unloaded_snapshot_with_release_object`
- `test_unload_is_allowed_in_every_engine_mode` (R4; `reflex_only` with a resident model still verifies and releases)
- `test_mode_switch_never_unloads_or_claims_release` (`PUT /api/settings` with each `engine_mode`: zero calls to `MANAGER.unload` and `release_external_model`, `manually_unloaded` unchanged, no "unloaded" or "released" in the response)
- `test_running_models_autoload_skips_while_manually_unloaded`
- `test_explicit_load_clears_manual_unload` (`POST /api/model/load` runs in the `explicit_load` origin)
- `test_offer_use_clears_manual_unload` (`POST /api/model/running/{id}/choice` with `use` loads and clears the flag)
- `tests/test_rfc0242_load_callers.py::test_every_manager_load_caller_is_classified` (static scan of `backend/app`: each `MANAGER.load(`, `MANAGER.ensure_runtime(` and `MANAGER.ensure_vision(` call site is in the §3 table; a new unclassified site fails)
- `tests/test_rfc0242_load_origin.py::test_ensure_runtime_and_ensure_vision_cannot_respawn_background_after_explicit_unload`, `::test_no_background_warm_after_explicit_unload`, `::test_owner_turn_after_explicit_unload_respawns_on_demand`, `::test_owner_turn_under_reflex_only_after_explicit_unload_loads_nothing`, `::test_unknown_origin_counts_as_background`, `::test_background_task_spawned_in_owner_turn_stays_background`, `::test_owner_turn_entries_are_classified` (amendment, "Conformance tests")
- `test_unload_all_releases_every_anzu_loaded_model_and_verifies`, `test_unload_all_partial_failure_returns_207_with_per_model_results`, `test_unload_all_never_touches_owner_started_or_studio_models`, `test_unload_endpoint_stays_single_model` (amendment)

**CI:** **"Run model and security regression tests"** (append `tests/test_rfc0242_model_unload.py`, `tests/test_rfc0242_load_callers.py` and `tests/test_rfc0242_load_origin.py`) and **"Run full backend suite"**.

**Acceptance:**
- [ ] Unload releases and verifies only the selected local model through its native runtime, preserves unrelated models and applications, refuses during inference, and never claims success on failure.
- [ ] Until an explicit Load, no background path reloads a model in this session, and an owner turn respawns on demand (and loads nothing under `reflex_only`); callers behave per the §3 table.
- [ ] `POST /api/model/unload-all` releases every ANZU-loaded model, verifies each, reports per-model results (207 on partial failure), and leaves `POST /api/model/unload` single-model.
- [ ] A mode switch never unloads and never claims a release; Unload works in every mode.
- [ ] The inventory code is unchanged (R3).

### T4: Unload UI and state propagation (frontend)

**Model:** Composer 2.5 · **fast mode off** · **Lane:** D2 · **Depends:** T3.

| File | Change |
| --- | --- |
| `frontend/src/hud/applyRuntimeProfile.ts` | `unloadCurrentModel()` and `unloadAllModels()` (`POST /api/model/unload-all`; throws on a 409, returns the per-model results on 200 and 207 and never reports success while any `verified` is false; the HUD button of the keep-warm ticket calls it); `finishModelActivation` dispatches `jarvis:model-state-changed`; snapshot type gains `active_model`, `manually_unloaded`, `release` |
| `frontend/src/App.tsx` | event listener and a generation counter in the `/api/model` poll effect (a poll that started before the event is discarded) |
| `frontend/src/hud/HudModelSelector.tsx` | Unload calls `unloadCurrentModel()`; the RFC-0244 inventory cross-check stays; success and failure text per §3 |
| `frontend/src/hud/modelMenuStatus.ts` | `unloadResultLine()` |
| `frontend/apply-runtime-profile-api-stub.mjs` | unload stub fields |
| `frontend/model-unload-state.test.mjs` (new), `frontend/package.json` | `test:model-unload` script |

Tests (`frontend/model-unload-state.test.mjs`):
- `verified unload publishes the unloaded state and keeps the selected row`
- `a still-loaded response never publishes unloaded state`
- `a response without release.verified is rejected`
- `runtime failure stays visible instead of claiming success`
- `a poll started before the unload event cannot overwrite the unloaded state` (the full-App generation guard, with the poll held across the event)
- `the inventory cross-check still reports a resident model after a verified unload` (RFC-0244 behaviour kept)
- `unload success text names the model and says other models were left running`
- `unloadAllModels returns per-model results and a 207 is surfaced as partial failure, never success`
- `unloadAllModels publishes the unloaded state only when the active model verified`

**CI:** new `frontend-build` step **"Verified Unload state tests (RFC-0242 T4)"**: `npm run test:model-unload` (append-only in `pr-tests.yml`).

**Acceptance:**
- [ ] The UI shows "unloaded" only after a verified release response; failures stay visible.
- [ ] A stale in-flight poll never resurrects a running state.
- [ ] RFC-0244's inventory cross-check, Refresh and More still work and are unchanged.

### T5: Verified Load (instance evidence before success)

**Model:** Grok 4.6 · **fast mode off** · **Lane:** D2 · **Depends:** 0230-S2, 0225-S2, 0225-S3 and 0228-S2 on `backends.py`, `lmstudio_server.py` and `hotswap.py` (batch landed).

| File | Change |
| --- | --- |
| `backend/app/inference/lmstudio_server.py` | `resolve_lmstudio_artifact`; `ensure_local_lmstudio` readiness requires the native loaded inventory to contain the model |
| `backend/app/inference/backends.py` | `resolve_advertised_model`: no single-model shortcut, no `Path.stem`, unique-match only |
| `backend/app/inference/hotswap.py` | `apply_runtime_profile_to_settings`: artifact resolution and the exact error text, settings untouched on failure; `activate_runtime_profile`: `ensure_local_lmstudio` before `MANAGER.load` for a loopback LM Studio target |
| `tests/test_runtime_activate.py` (existing file) | named tests below |

Tests (`tests/test_runtime_activate.py`):
- `test_explicit_9b_hint_does_not_resolve_to_other_qwen_versions_or_sizes`
- `test_ambiguous_partial_hint_is_not_silently_resolved`
- `test_single_advertised_model_does_not_replace_a_different_explicit_hint`
- `test_native_lmstudio_alias_requires_exact_display_identity_and_quant` (parametrized rows)
- `test_wrong_or_ambiguous_model_never_changes_settings`
- `test_lmstudio_activation_does_not_claim_downloaded_model_is_loaded` (advertised but not in the loaded inventory: `ensure_local_lmstudio` returns not ok and the route answers 503)
- `test_unreadable_native_inventory_is_not_success`

**CI:** **"Run model and security regression tests"** (append `tests/test_runtime_activate.py`) and **"Run full backend suite"**.

**Acceptance:**
- [ ] A switch is reported successful only when the runtime's own loaded inventory contains the resolved instance.
- [ ] An explicit hint never resolves to another family, version or size; an ambiguity fails visibly with the available identifiers.
- [ ] Failed resolution leaves saved settings unchanged.

### T6: Explicit owner Load in every engine mode

**Model:** Grok 4.6 · **fast mode off** · **Lane:** D2 · **Depends:** T3 and T5 (shared `manager.py`, `hotswap.py`, `api/model.py`, `running_models.py`), and 0227-S3 on `runtime_profiles.py` (batch landed).

| File | Change |
| --- | --- |
| `backend/app/engine_mode.py` | `explicit_owner_load()`, `require_model_for_load()` |
| `backend/app/inference/manager.py` | `load`, `ensure_runtime` and `_load_impl` call `require_model_for_load` (`chat` and `chat_stream` untouched) |
| `backend/app/inference/hotswap.py` | `apply_runtime_profile_to_settings` and `activate_runtime_profile` call `require_model_for_load` |
| `backend/app/inference/running_models.py` | `RunningModels.decide`: `require_model_for_load` for actions `use` and `replace` (the `leave` autoload stays on `require_model`/`model_enabled`) |
| `backend/app/api/model.py`, `backend/app/api/runtime_profiles.py`, `backend/app/api/lmstudio.py` | enter `explicit_owner_load()` in `load_model`, `choose_running_model` (actions `use` and `replace` only), `activate_profile`, `select_profile`, `select_discovered` and only there; replace `load_model`'s `model_enabled` 409; **R7 mapping (owner decision 2026-11-03, assigned to T6, Grok 4.6, fast mode off):** `choose_running_model` currently maps only `ValueError` to 409 and everything else to 503 (`"The model choice failed: …"`), and `load_model` maps everything to 500, but `ModelDisabledError` and `ModelManuallyUnloaded` are `RuntimeError`s. Both handlers add `except (ModelDisabledError, ModelManuallyUnloaded) as exc: raise HTTPException(409, str(exc))` before the generic clause, so a refusal reaches the pressed control verbatim; genuine failures stay 503/500 |
| `frontend/src/hud/HudModelSelector.tsx` | Load no longer disabled by `reflex_only`; the `reflex_only` note after Load |
| `frontend/src/hud/modelMenuStatus.ts` | `reflexLoadNote()` |
| `tests/test_rfc0242_explicit_load.py` (new), `tests/test_rfc0244_engine_modes.py` (two tests amended), `frontend/hud-model-selector-render.test.mjs` | named tests below |

Tests:
- `tests/test_rfc0242_explicit_load.py::test_explicit_load_endpoint_works_in_every_engine_mode` (parametrized `hybrid`, `model_only`, `reflex_only`)
- `tests/test_rfc0242_explicit_load.py::test_activate_and_select_routes_work_in_reflex_only` (`activate_profile`, `select_profile`, `select_discovered`)
- `tests/test_rfc0242_explicit_load.py::test_reflex_only_explicit_load_never_enables_generation` (after Load, `MANAGER.chat`, `chat_stream`, the front lane and `_run` raise or answer with `reflex_only_reply`; zero provider calls)
- `tests/test_rfc0242_explicit_load.py::test_offer_use_works_under_reflex_only_via_route` (`POST /api/model/running/{id}/choice` with `use`, in `reflex_only`: 200, the model loads, `MANAGER.state.loaded` true, zero generation calls)
- `tests/test_rfc0242_explicit_load.py::test_offer_use_scope_reaches_a_background_job` (if the choice runs as a job, the job's load sees the scope for `use` and `replace`; written against whichever `decide` shape `development` holds)
- `tests/test_rfc0242_explicit_load.py::test_offer_replace_works_under_reflex_only_via_route` (`POST /api/model/running/{id}/choice` with `replace`, in `reflex_only`: 200, the other server is stopped, ANZU's own model loads, zero generation calls)
- `tests/test_rfc0242_explicit_load.py::test_offer_leave_loads_nothing_under_reflex_only` (action `leave` in `reflex_only` and while `manually_unloaded`: choice recorded, zero `MANAGER.load` calls, no unload)
- `tests/test_rfc0242_explicit_load.py::test_offer_stop_is_unchanged_in_reflex_only` (`stop` behaves as on `development`)
- `tests/test_rfc0242_explicit_load.py::test_refused_owner_actions_return_a_visible_reason` (R7: an unscoped `decide(..., "use")` raises `ModelDisabledError` whose text names the mode, and the choice route maps a refusal, including a held request lease or `ModelManuallyUnloaded`, to a 409 with that text; the card shows it through its existing `setError` line)
- `tests/test_rfc0242_explicit_load.py::test_choice_route_maps_mode_and_manual_unload_refusals_to_409` (a `decide` patched to raise `ModelDisabledError`, then `ModelManuallyUnloaded`, answers 409 with the exception text, not 503; a plain `RuntimeError` still answers 503; the same for `load_model`, 409 vs 500)
- `tests/test_rfc0242_explicit_load.py::test_explicit_load_passes_load_guard_in_reflex_only` , `::test_explicit_load_passes_ensure_runtime_guard_in_reflex_only` , `::test_explicit_load_passes_load_impl_guard_in_reflex_only` (one per guard: `InferenceManager.load`, `ensure_runtime` and `_load_impl` each reached under `explicit_owner_load()` with `engine_mode == "reflex_only"` and a fake backend: the load completes and zero generation calls are made)
- `tests/test_rfc0242_explicit_load.py::test_unscoped_load_class_guards_still_refuse_in_reflex_only` (the same three guards refuse an unscoped, an `owner_turn` and a `background` origin with `ModelDisabledError`)
- `tests/test_rfc0242_explicit_load.py::test_chat_and_chat_stream_stay_generation_guards` (`chat` and `chat_stream` raise `ModelDisabledError` under `reflex_only` even inside `explicit_owner_load()`)
- `tests/test_rfc0242_explicit_load.py::test_autoload_paths_stay_blocked_in_reflex_only` (startup `_autoload_model`, `RUNNING_MODELS` autoload, `ensure_runtime`, persona and agent callers: each raises `ModelDisabledError` or skips; zero load calls)
- `tests/test_rfc0242_explicit_load.py::test_explicit_scope_does_not_leak_to_other_tasks` (an autoload attempt running concurrently with an explicit Load is still blocked; the `ContextVar` is reset after the handler)
- `tests/test_rfc0242_explicit_load.py::test_mode_switch_never_loads_a_model` (R4 mirror: no load on `PUT /api/settings`)
- `tests/test_rfc0244_engine_modes.py::test_reflex_only_helpers_blocked_without_the_explicit_scope` (the split-out half of `test_reflex_only_load_controls_cannot_start_external_runtime`)
- `frontend/hud-model-selector-render.test.mjs`: `Load is enabled under reflex_only and says generation stays off after loading`; `Load stays disabled while a load is in progress`

**CI:** **"Run model and security regression tests"** (append `tests/test_rfc0242_explicit_load.py` and `tests/test_rfc0244_engine_modes.py`; `tests/test_rfc0210_running_models.py` is not edited), **"Run full backend suite"**, and the existing **"HUD model menu status tests (RFC-0244 restore)"** step for the render test.

**Acceptance:**
- [ ] An explicit Load (the dropdown button, the activate route, both LM Studio select routes, and the running-models offer card's "Use model" and "Use ANZU's model") works in `hybrid`, `model_only` and `reflex_only`.
- [ ] Under `reflex_only` the loaded model is never called and no generation lane starts (RFC-0244 acceptance bullets "Reflex only cannot start/call front or worker generation" and "Reflex-only chat/task requests provide a bounded response" still pass).
- [ ] Every autoload path stays blocked as RFC-0244 ships it; `leave` loads nothing.
- [ ] A refused owner action always shows its reason on the control that was pressed (R7).
- [ ] No RFC-0244 element other than the Load disable, the offer-card `use` and `replace` block and the two amended tests changes.

## Ticket cards

| Ticket | Model (fast mode off) | Lane | Depends | Backend CI | Frontend CI |
| --- | --- | --- | --- | --- | --- |
| 0242-T1 | Grok 4.5 | D2 | none | Run model and security regression tests; Run full backend suite | n/a |
| 0242-T2 | Grok 4.5 | D2 | T1 | same | Node model dropdown identity tests (RFC-0244); HUD model menu status tests (RFC-0244 restore) |
| 0242-T3 | Grok 4.6 | D2 | none | same | n/a |
| 0242-T4 | Composer 2.5 | D2 | T3 | n/a | Verified Unload state tests (RFC-0242 T4) |
| 0242-T5 | Grok 4.6 | D2 | none | same | n/a |
| 0242-T6 | Grok 4.6 | D2 | T3, T5 | same | HUD model menu status tests (RFC-0244 restore) |

Every ticket starts only after the batch chain for each of its files has landed on `development` (see *Handoff order*); each lands as one commit on #682.

## Overall acceptance

- [ ] A 27B Heretic, Gemma Aggressive or arbitrary Q4 file cannot match a different 9B/4B family; absent candidates cannot load (T1).
- [ ] The dropdown shows actual artifact, GiB, quantization, speed estimate and an honest restriction label per row; the live serving identity takes precedence over a stale label (T2).
- [ ] The primary-source comparison records exact artifacts, published evidence and local validation limits, and matches the catalog (T2).
- [ ] Unload releases and verifies the selected local model through the runtime's own inventory, refuses during inference, never claims success on failure; after an explicit Unload background paths never reload anything until an explicit Load, while an owner turn respawns on demand (T3, T4).
- [ ] A mode switch never unloads and never claims VRAM was released (T3, T6).
- [ ] Switching to a downloaded LM Studio model verifies its loaded instance before reporting success (T5).
- [ ] An explicit owner Load works in every engine mode, and no generation lane starts under `reflex_only` (T6).
- [ ] Choosing a dropdown row never activates a model; the inventory stays read-only (R1, R3).
- [ ] Keep warm defaults off; with it off every ANZU-loaded model (front responder included) unloads after 5 minutes idle and respawns on demand, and after an explicit Unload only an owner turn (not a background path) respawns on demand; the HUD Unload model button releases every ANZU-loaded model through `POST /api/model/unload-all` with per-model verified results; with Keep warm on nothing idle-unloads; every Ollama request ANZU makes carries `keep_alive` (`"300s"` off, `"-1"` on) and no 24 h keep-alive remains; LM Studio loads carry a 300 s TTL when off (section "Amendment: Keep warm toggle and 5-minute idle unload", `tests/test_keep_warm_idle_unload.py`).
- [ ] No slot, Pin, bind endpoint or `modelSlots.ts` exists after the rework.
- [ ] Backend regressions, full pytest, frontend build and lint, and the frontend test steps above pass; installed-app status is reported separately.

## Out of scope

Security-gate changes, automatic model downloads or promotion, installer replacement, removing the backend pin flag, routing policy, unrelated model or voice architecture, Astra-owned systems (personas, WebGL, presence), the RFC-0244 engine-mode semantics other than the explicit-Load ruling, and the batch RFCs' own content (none of them is edited).

## Risks

- **#682 add/add conflict on this file.** Resolved by the rework procedure (take `development`'s file). Merge-tree against #682 shows exactly that conflict plus the stale-base noise.
- **`reflex_only` explicit Load changes two RFC-0244 tests** (named in T6). CoS ruling; if it is withdrawn, T6 is dropped (including the offer-card change) and nothing else depends on it.
- **LM Studio inventory shape.** `loaded_instances` is read from the native API; a runtime version without it makes Unload and Load fail closed with a message (never a false success).
- **Ordering with the batch.** RFC-0242 goes last on every shared file, so D2 cannot start a ticket until its files' batch chains have landed; that is the cost of leaving #652 and #655 untouched. If a batch PR slips, only the tickets on its files wait.
- **Cold first word after an idle unload.** With Keep warm OFF the first request after 5 idle minutes reloads the model, including the front responder, so RFC-0230's first-word budget applies to a warm lane only. The loading state is visible and Keep warm ON restores the warm path (owner order).
- **Keep-warm ticket and T3 overlap on `manager.py`, `running_models.py` and `api/model.py`.** The keep-warm ticket lands first and 0242 stays last on shared files; if D2's PR names a setting, file or test differently, this section is edited to match, and D2's PR is the source of truth.
- **`replace` stops another application's server.** It is an explicit owner click behind the card's existing confirm dialog, and it now also works under `reflex_only` (CoS ruling). Its stop path is unchanged and is verified by the existing unload-verification code (`verify_unloaded`).
