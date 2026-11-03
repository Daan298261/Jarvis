# RFC-0242: Accurate model identity, honest node-dropdown rows, verified Unload and verified Load (rescoped onto the RFC-0244 dropdown)

**Status:** accepted (original text by Codex, #682); **rescoped 2026-10-30** by Jarvis Architect on CoS assignment; **amended 2026-11-03** with the Keep warm toggle and 5-minute idle unload contract (section "Amendment: Keep warm toggle and 5-minute idle unload"). This file is the authoritative RFC-0242 on `development`. Where it differs from the text in #682 (RFC-0242; final head in this PR's body), this file wins.
**Author:** Codex, requested by Daan (original, 2026-10-28); Jarvis Architect (rescope, 2026-10-30)
**Date:** 2026-10-28; amended 2026-10-30 and 2026-11-03
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §8 (ANZU must verify its own work; "confidence should come from evidence rather than cheerful completion messages"), §9 (local-first, owner-controlled infrastructure), §19 ("Do expose state when the user needs confidence in what ANZU is doing"; "Do not mark something finished merely because its backend exists"), §20.
**Traced on:** `development` @ `a62bd454` (#685 landed on top of RFC-0244, #684); `e1a0e7d6` (#687) merged in without changes to any cited file. Keep-warm names are traced on #690 @ `aa40d53a` (open; final head in this PR's body). Every citation below is by file and symbol or by section name; no line numbers.
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
- **Stays unloaded against background paths until an explicit Load (amended 2026-11-03, CoS; mechanism: #690).** After a verified release `MANAGER.state.manually_unloaded` is true (`keep_warm_release.release_models("manual")` sets it). While it is set, every background caller is refused: `InferenceManager._guard_background_load()` raises `ModelManuallyUnloaded` (a `RuntimeError` subclass, text "Model was manually unloaded. Use Load to start a model again.") in `load`, `ensure_runtime`, `ensure_vision`, `_load_locked` and `_load_impl`, and every direct-HTTP warm asks `idle_unload.warm_blocked()` first, so no refresh, preload, `NINE_B_REWARM`, `RUNNING_MODELS` poll, background `ensure_*`, escalation or context-reload path silently brings a model back. An **owner turn** is the owner's own act and respawns on demand: `IDLE_UNLOAD.touch()` at the turn entry clears the flag before the turn calls `ensure_*` (exactly as after an idle unload); under `reflex_only` it loads nothing. The flag lives for the backend process only; a restart is a new session. Explicit Load (`POST /api/model/load`, `hotswap.activate_runtime_profile`, the offer card's `use` / `replace`, and the two LM Studio select routes) calls `IDLE_UNLOAD.explicit_load()` and clears it, in every engine mode. #690 sets and exposes none of this in `/api/model`; T3 adds the live key. See *Reconciliation with #690* for the contract lines #690 does not yet meet.
- **Autoload callers.** Every `MANAGER.load(`, `MANAGER.ensure_runtime(` and `MANAGER.ensure_vision(` call site is classified in the table below and a static test fails when a new one appears unclassified (`agent/loop.py` and `media/analyze.py` reach `ensure_vision`, `persona/inference_context.py` reaches `ensure_runtime`).

| `MANAGER.load` call site | Behaviour while `manually_unloaded` |
| --- | --- |
| `main.py` startup restore (`_autoload_model`) | unaffected: a fresh process has the flag false |
| `inference/running_models.py` autoload branches (`RUNNING_MODELS._poll` and the `leave` branch of `decide`) | **skip silently** (`IDLE_UNLOAD.background_blocked()`, #690): no error, no notice |
| `inference/running_models.py::RunningModels.decide` for the owner's `use` and `replace` actions | explicit owner click: `IDLE_UNLOAD.explicit_load()` (#690) clears the flag before the load |
| `agent/loop.py`, `inference/model_escalation.py`, `inference/live_agent_suite.py`, `persona/owner_chat.py`, `persona/inference_context.py`, `media/analyze.py` | inside an owner turn (`IDLE_UNLOAD.touch()` at `AGENT._start_runner`, `stream_owner_chat`, `generate_front_reply`) they **respawn on demand** and the flag is already clear; reached from a background task they **propagate** `ModelManuallyUnloaded` (`model_escalation.py` also checks `warm_blocked()`) and the existing handlers surface the text. T3 edits none of these files; its static test classifies the sites. |
| explicit entry points (`api/model.py::load_model`, `api/model.py::choose_running_model` with action `use`, the activate and select routes via `hotswap.activate_runtime_profile`) | `IDLE_UNLOAD.explicit_load()` (#690); T6 additionally enters `explicit_owner_load()` so the load-class guards pass under `reflex_only` |

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

- `engine_mode.py` adds `explicit_owner_load()` (a context manager over its own `ContextVar` in `engine_mode.py`; it only exempts the load-class guards from `require_model`, and every route that enters it is one of #690's `IDLE_UNLOAD.explicit_load()` sites) and `require_model_for_load(settings=None)`, which returns only while that scope is active and otherwise behaves exactly as `require_model` (so under `reflex_only` an owner turn or a background caller is still refused, and the generation lanes are untouched).
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

**Owner order (Taco, via CoS, 2026-11-03).** Two new top-right HUD controls: an **Unload model** button and a **Keep warm** toggle that defaults to **off**. D2 built them as a Taco-owned ticket: **#690** (`feat/hud-unload-keep-warm`, final head in this PR's body), "KW" below. **#690 is canonical for names, files, endpoints and test paths**; this amendment keeps the *behaviour contract* and records, in one place, where #690 (at `aa40d53a`) does not yet meet it (section "Reconciliation with #690"). Revised 2026-11-03 after D1's review (unload-all, LM Studio TTL, turn-reset, load guards, 409 mapping), CoS rulings (idle unload covers every model ANZU loaded, including on the owner's explicit Load; background paths never reload after an explicit Unload, an owner turn does) and the appearance of #690.

### Names (#690, canonical)

| What | #690 name |
| --- | --- |
| Settings | `InferenceSettings.keep_warm` (default `False`), `InferenceSettings.idle_unload_seconds` (default `300`, `ge=30`, `le=86400`) in `config.py`; `/api/settings` keys `inference_keep_warm`, `inference_idle_unload_seconds` |
| The one keep-alive helper | `inference/keep_alive.py`: `keep_warm_enabled()`, `idle_unload_seconds()`, `ollama_keep_alive()` (`"300s"` off, `"-1"` on), `lmstudio_ttl_seconds()` (`300` off, `None` on), `request_extras(base_url, model)`; consumed by `gpu_prefer.ensure_ollama_gpu`, `gpu_prefer.lmstudio_cli_load_args`, `gpu_prefer._lmstudio_rest_load`, `ollama_runtime.ensure_local_ollama`, `lmstudio_server.ensure_local_lmstudio`, `lmstudio_context.instance_load_args`, `providers/base.py::_runtime_extras`, `providers/local_qwen_text.py` |
| The ANZU-loaded ledger and per-model idle clock | `inference/loaded_models.py`: `LOADED` (`LoadedModels`), `Entry.last_use`, `record`, `match`, `touch`, `touch_primary`, `defer`, `forget`, `idle_for`; backends `OLLAMA`, `LMSTUDIO`, `LLAMA_SERVER` with the seats `WORKER` and `FRONT` |
| Idle timer, turn hooks, background gate | `inference/idle_unload.py`: `IDLE_UNLOAD` (`IdleUnload.tick`, `touch`, `used`, `explicit_load`, `note_released`, `background_blocked`), `warm_blocked()`, `UNLOADED_DETAIL` |
| Release and verify | `inference/keep_warm_release.py::release_models(source, targets)` |
| Unload-all endpoint | `POST /api/model/unload-all` (`api/model_unload_all.py`); the dropdown's `POST /api/model/unload` is unchanged |
| Unload flag and refusal | `InferenceState.manually_unloaded`, `ModelManuallyUnloaded` (`manager.py`); `InferenceManager._guard_background_load()` in `load`, `ensure_runtime`, `ensure_vision`, `_load_locked` and `_load_impl`; `FrontRuntime.ensure_started` checks `IDLE_UNLOAD.background_blocked()` |
| Turn entry hooks | `IDLE_UNLOAD.touch()` in `AGENT._start_runner` (`agent/loop.py`), `persona/owner_chat.py::stream_owner_chat` and `agent/front_responder.py::generate_front_reply`; `IDLE_UNLOAD.explicit_load()` in `POST /api/model/load`, `hotswap.activate_runtime_profile` and `RunningModels.decide` for `use` / `replace` |
| HUD | `frontend/src/hud/HudModelRelease.tsx`, `modelRelease.ts`, `modelRelease.css`, one mount line `<HudModelRelease />` in `HudShell.tsx` |
| Tests | `tests/test_keep_warm_idle_unload.py`, `frontend/keep-warm-hud.test.mjs` (wired into `pr-tests.yml` and `frontend/package.json` by #690) |

Names this RFC used before #690 existed and that are now **aliases**: `engine_requests.ollama_request` → `keep_alive.py`; the `anzu_loads` ledger section (RFC-0225, unlanded) → `LOADED`; `model_release.release_all_anzu_loaded` → `keep_warm_release.release_models("manual")`; `load_origin.py` and `owner_turn_scope()` / `background_scope()` → `IDLE_UNLOAD.touch()` / `explicit_load()` and `warm_blocked()` / `_guard_background_load()`; the HUD component "named when D2's PR lands" → `HudModelRelease.tsx`. RFC-0225's `prepare_engine_for` and RFC-0228's `NINE_B_REWARM` do not exist on `development` or in #690; when #652 and #655 land they must call `warm_blocked()` / `MANAGER._guard_background_load()` (#690's static scan then lists them).

### Contract (normative; each line has a named test below)

- **Keep warm OFF (default).** Every model ANZU loaded unloads after `idle_unload_seconds` (300 s) with no request lease, stream, tool loop or task stage in flight, and respawns on demand on the next **owner turn**. "ANZU loaded" means "recorded in `LOADED`", and includes a model ANZU loaded because of the owner's explicit Load (dropdown Load, activate and select routes, the offer card's "Use ANZU's model"): that Load registers it (CoS K3; #690 confirmation 4). Scope: the front responder, the 9B worker, the 27B coder, and any LM Studio, Ollama or llama-server model ANZU loaded.
- **Exemptions (the only ones).** (a) A model ANZU did not load and never sends a request to, such as the studio's `bgm-ingest-9b`: it is not in `LOADED`, so ANZU sends it no unload and no `keep_alive` (CoS/PG ruling; fail-closed ownership: no ledger entry, no action). #690 has no name guard on purpose; #688's S3 adds a name-based second layer for the studio model on top of the ledger. (b) An LM Studio instance the owner started himself and ANZU did not load stays under RFC-0225 / RFC-0228 managed-mode consent (never unloaded unless managed mode is on). An Ollama model the owner started himself is never sent an unload by ANZU.
- **Keep warm ON.** Today's always-warm behaviour: no idle timer for any model; ANZU-originated Ollama requests pin (`"-1"`), so "always warm" no longer depends on a 24 h expiry. Turning it on re-pins **every currently loaded ANZU-loaded model**: Ollama models get a native `"-1"` request at once, and LM Studio instances ANZU loaded with a TTL are re-pinned (re-issued without a TTL; a verified unload and reload at a moment with no lease held if LM Studio cannot change a TTL in place, with the loading state visible). Turning it off resumes the idle clocks from each model's last use (#690: the next check, also triggered on the settings save).
- **`keep_alive` on EVERY Ollama request ANZU makes.** Ollama applies its own 5-minute default to a request that omits the field, so omission would shorten Keep warm ON. Every native Ollama request ANZU sends (`/api/generate`, `/api/chat`, warms, refreshes, preloads, the keep-alive touch below) carries `keep_alive` from `keep_alive.ollama_keep_alive()`: `"300s"` OFF, `"-1"` ON, plus `0` for an explicit unload. This includes requests ANZU routes to a model it did not load (RFC-0228's `"300s"` rule for Taco's shell-started 27B), with the single exception of the studio's model, which gets no request at all. The 2026-10-30 draft wording that said models ANZU did not load get no `keep_alive` with Keep warm on is withdrawn.
- **The OpenAI-compatible path.** ANZU chats with Ollama through `providers/base.py::ModelProvider.chat` and `chat_stream` (`POST /chat/completions` on `/v1`); #690 puts `keep_alive` into the request body there via `_runtime_extras()`. Ollama's `/v1` endpoint does not accept `keep_alive` (ollama/ollama issue 9355) and whether it resets a resident model's expiry depends on the version, so the contract also requires the **keep-alive touch**: when an Ollama-served turn finishes, `POST /api/generate {"model", "prompt": "", "keep_alive": <policy>}` for each ANZU-loaded Ollama model that turn used, only if `/api/ps` lists it (a touch never loads, and is a background path under *Load origin*). D2 verifies the `/v1` behaviour on Taco's Ollama version in the live audit; the touch stays either way.
- **LM Studio TTL.** An ANZU-originated LM Studio load carries `ttl = lmstudio_ttl_seconds()` (`--ttl 300` in `gpu_prefer.lmstudio_cli_load_args` and `ensure_local_lmstudio`, the `ttl` field in `gpu_prefer._lmstudio_rest_load`; `lmstudio_context.instance_load_args` re-applies it to an instance in `LOADED` and rebuilds any other instance exactly as it was) with Keep warm OFF, and none with it ON. ANZU's idle timer and verified unload remain the enforcer; the TTL is the backstop when ANZU is down.
- **No 24 h keep-alive survives.** #690 removes `keep_alive: "24h"` from `gpu_prefer.ensure_ollama_gpu` and `ollama_runtime.ensure_local_ollama`; RFC-0228 has no separate 9B timeout.
- **The idle clock resets on any turn that uses the model.** Per model: `LOADED` keeps `Entry.last_use`; `MANAGER.chat` and `chat_stream` record the model at start and finish (`_register_loaded`), and a turn entry calls `IDLE_UNLOAD.touch()` (resets the primary entries) and `used()` at its end. A turn served only by the front responder resets the front clock and no other model's. Lease holds, streams, tool loops and task stages count as use. A background refresh or touch is not a turn and never resets a clock by itself.
- **Refresh vs idle (CoS K2 mirror).** RFC-0245's lease refresh may never stretch a model past the idle window: it runs only while a child task stage is actively running, each tick re-checks `/api/ps` residency and `MANAGER.state.manually_unloaded`, entering `waiting` stops it, and the 27B unloads `idle_unload_seconds` after its last use (`LOADED.idle_for`), not 2x. The setting persists across restart through `save_settings`; a settings file without the key means OFF.

### After an explicit Unload: background paths stay off, an owner turn respawns (CoS ruling; #690's mechanism)

After an **explicit Unload**, no **background** path reloads anything until an explicit Load; an **owner turn** respawns on demand, because it is the owner's own act, exactly as after an idle unload.

- **How it is carried (#690).** `release_models("manual")` sets `MANAGER.state.manually_unloaded` after a fully verified release. While it is set, every background caller is refused: `_guard_background_load()` raises `ModelManuallyUnloaded` (the text "Model was manually unloaded. Use Load to start a model again.") in `load`, `ensure_runtime`, `ensure_vision`, `_load_locked` and `_load_impl`; every direct-HTTP warm (`ensure_ollama_gpu`, `ensure_local_ollama`, `ensure_lmstudio_gpu`, `ensure_local_lmstudio`, `lmstudio_context.grow_local_instance`, `FrontRuntime._warmup`) asks `warm_blocked()` first and returns an "unloaded" result; `FrontRuntime.ensure_started` asks `background_blocked()`. An owner turn lifts it at the turn entry points (`IDLE_UNLOAD.touch()` clears `manually_unloaded` before the turn calls `ensure_*`), an explicit Load lifts it through `IDLE_UNLOAD.explicit_load()`. An idle release sets `IDLE_UNLOAD.held` (background starters stay off until the next turn) but not `manually_unloaded`.
- **Why `_load_impl` stays the choke point.** `_load_locked` wraps `_load_impl` and is its only caller, so `load`, `ensure_runtime`, `ensure_vision` and `release_vision` all reach it, and `require_model` already sits in `_load_impl`; a refusal there leaves state untouched. #690 repeats the guard in all five methods, which is equivalent; T6's `require_model_for_load` is placed in `load`, `ensure_runtime` and `_load_impl` (§4).
- **Rule table.**

| Caller | `manually_unloaded` true (explicit Unload) | Idle-unloaded | `reflex_only` |
| --- | --- | --- | --- |
| explicit Load (`explicit_load()`) | loads, clears the flag | loads | loads weights only (R2) |
| owner turn (`touch()` at the turn entry) | **respawns on demand**, flag cleared first | respawns on demand | loads **nothing** (generation off; RFC-0244 bounded reply) |
| background caller (anything else: refresh, preload from a timer or recovery, rewarm, poll, background `ensure_*`, direct-HTTP warm, keep-alive touch) | refused with `ModelManuallyUnloaded` or an "unloaded" warm result | held until the next turn when the idle release stopped the front responder; existing RFC-0228 rules otherwise | refused as in RFC-0244 |

### Reconciliation with #690 (as of `aa40d53a`; the contract above is unchanged)

#690 does not yet meet these contract lines. They are **not** silently changed here; T3 (below) lands rows 1-8 as edits on top of #690 once it merges, #688's S3 lands rows 9 and 10, and the list is reported to CoS.

| # | Contract | #690 today | T3 follow-up (test) |
| --- | --- | --- | --- |
| 1 | Unload-all answers 200 / **207** (partial failure, with the per-model results) / 409 | answers 200 / 409 / **502**; the 502 body is the reason string only (`HTTPException(detail=reason)`), the per-backend rows are lost | `test_unload_all_partial_failure_returns_207_with_per_model_results` |
| 2 | Unload during a RFC-0245 pipeline is **not refused**: it cancels the pipeline visibly | `release_models("manual")` answers 409 "ANZU is working on a task" while any `AGENT` task is not done (`IDLE_UNLOAD.is_busy`) | `test_unload_all_cancels_pipeline_instead_of_refusing_for_task` |
| 3 | Fail-closed ownership: only models ANZU loaded; an owner-started model is never unloaded | `MANAGER._register_loaded` records the attached Ollama / LM Studio model of `MANAGER.state` as `primary` after any `chat`, so an owner-started instance ANZU merely talks to enters `LOADED` and can be idle-unloaded, bypassing the managed-mode rule (RFC-0225 / RFC-0228) | `test_owner_started_instance_never_enters_the_ledger_without_an_anzu_load` |
| 4 | `keep_alive` on every Ollama request ANZU makes, including requests routed to a model ANZU did not load | `request_extras` returns `{}` for a model not in `LOADED` (test name: "for anzu models only") | `test_every_ollama_request_path_sets_keep_alive_except_the_studio_model` |
| 5 | Keep-alive touch after an Ollama-served `/v1` turn | not present | `test_ollama_v1_turn_is_followed_by_a_keep_alive_touch_only_if_resident` |
| 6 | Toggle ON re-pins every loaded ANZU-loaded model with `"-1"` | not present (a model warmed with `"300s"` expires inside 300 s unless a request carries `"-1"`) | `test_toggle_on_repins_every_loaded_anzu_model_with_minus_one` |
| 7 | Per-model idle clock: a front-only turn resets only the front | `IDLE_UNLOAD.touch()` calls `LOADED.touch_primary()`, which resets every `primary` entry (worker and front) at any turn | `test_front_only_turn_resets_only_the_front_clock` |
| 8 | Owner turn respawns; a background caller never does (fail closed: an unknown caller is background) | the flag is cleared at the turn entry, including a `reflex_only` turn that loads nothing, and stays clear for any background task that runs afterwards | `test_reflex_only_turn_does_not_clear_manually_unloaded` |
| 9 | Name guard for `bgm-ingest-9b` (CoS ruling on #688) | ledger only, by design | `test_name_guard_is_a_second_layer_even_when_the_ledger_lists_bgm_ingest_9b` (owned by #688 S3) |
| 10 | A studio hold releases models without setting `manually_unloaded`, and the Keep-warm-ON respawn after the run is a background path (#688 §4) | `release_models` calls `IDLE_UNLOAD.note_released(...)` for every source, so `held` makes `warm_blocked()` true after any release, including a studio one, and the respawn would be refused | `test_respawn_clears_hold_but_never_manually_unloaded` (owned by #688 S3, which adds `IDLE_UNLOAD.clear_hold()`: it clears `held`, never `manually_unloaded`) |

### How it composes with this RFC

| Case | Behaviour | Why |
| --- | --- | --- |
| HUD **Unload model** button (`HudModelRelease.tsx`) | An explicit owner Unload of **everything ANZU loaded** through `POST /api/model/unload-all` (not the dropdown's single-model `POST /api/model/unload`). | Taco's order is one click, every model. |
| Dropdown Unload (T3, T4) | Unchanged: `POST /api/model/unload`, the selected local model only (any loader), verified. | The two actions stay distinct. |
| Idle unload | Not a manual unload: `manually_unloaded` stays false. Reports "unloaded" only after the runtime's own post-unload evidence (R5); a failed release is shown once and `LOADED.defer` makes the next attempt wait a full window. | Policy, not an owner decision. |
| Owner turn after an idle or explicit Unload | Respawns on demand with the existing "Loading model…" state. | The owner asked for a reply. |
| Background path after an explicit Unload | Never reloads (refresh, preload, rewarm, background `ensure_*`, direct-HTTP warms, the `RUNNING_MODELS` poll, the front-responder restart). | CoS ruling. |
| Unload with nothing loaded | 409 with a visible reason ("Nothing to unload: <model> was unloaded after 5 minutes idle and loads again on your next request"); `manually_unloaded` not set. | R7; #690 `_nothing_reason`. |
| Unload or toggle refused (request or load in flight, runtime error, settings write failed) | 409 or the failure status with the runtime's text on the control; the toggle reverts and shows the error. | R7. |
| Unload while a RFC-0245 pipeline holds an engine lease | Not refused for the lease: **before** taking its exclusive lease, unload-all calls `large_prompt_queue.on_owner_unload(models)` (0245-S5) for the models it is about to release; whenever the pipeline's target is in that set (whoever loaded it: preload makes the target the selected model) it stops the refresh, cancels the running child and remaining parts through `on_parent_cancel(task_id, reason="owner_unload")`, releases the lease, cancels the parent visibly and sets `preload_status = "released:owner_unload"`. A request that does not belong to a cancelled pipeline child and is still in flight returns 409. | #665 (RFC-0245; final head in this PR's body), section "Owner Unload and the lease". |
| `reflex_only` (RFC-0244) | Idle unload and unload-all still run (releasing VRAM needs no model lane). An owner turn loads nothing; only an explicit Load brings a model back. | R2, R4. |
| `model_only` and `hybrid` | Owner turns respawn on demand (`model_only` still excludes JEV and Laya). | RFC-0244 routing unchanged. |
| Mode switch | Never unloads and never claims release (R4). | R4. |
| Toggle ON → OFF | Idle measured from each model's last use. | One clock. |
| Startup restore (`_autoload_model`) | Unchanged; a fresh process has the flag false and the idle clock starts at load. | Not part of this order. |

### Unload-all (endpoint and release code: #690; contract closers: T3)

- **Endpoint:** `POST /api/model/unload-all` (`api/model_unload_all.py` → `keep_warm_release.release_models("manual")`), body empty. `POST /api/model/unload` stays single-model and unchanged.
- **What it releases (#690):** every `LOADED` entry: Ollama models by native `keep_alive: 0` and an `/api/ps` re-check, LM Studio instances by the native unload API (or `lms unload <instance>` when the native inventory is missing) and an inventory re-check, the managed llama-server worker by `MANAGER.unload()` and the front responder by `FRONT_RUNTIME.stop()`, each with a process-gone check. A model not in `LOADED` is left alone and listed under `left_alone`.
- **Response shape (#690):** `{ok, refused, reason, source, released_count, results: [{backend, endpoint, running, released[], left_alone[], ok, detail}], keep_warm}`. **Contract codes:** `200` every listed model verified; `207` with the same body when some failed (T3: today #690 answers 502 and drops the rows); `409` refused with nothing touched. The HUD shows one line per backend and a summary (`modelRelease.ts::releaseNote`); a partial failure is never rendered as success.
- **Lease and mode:** it takes `MANAGER._request_lease.exclusive()` (409 "ANZU is answering a request; try again when it finishes" when not acquired), works in every engine mode, and sets `manually_unloaded` only after a fully verified release.

### Live-UI add-alongside reasoning pass (2026-10-14 standing order) for the two controls

`HudShell.tsx` renders `.hud-top-right` with `HelpTrigger`, the Admin button (with its setup dot), the Classic toggle and `HudModelSelector`.

| Existing element | What #690 does | Reasoning |
| --- | --- | --- |
| `HelpTrigger`, Admin button and setup dot, Classic toggle, `HudModelSelector` | unchanged, same order, same handlers | Nothing live is removed or re-parented. |
| `.hud-top-right` reflow rules when the model menu is open | unchanged; the new controls are one component `HudModelRelease` with its own `modelRelease.css` | No existing CSS rule is edited. |
| Dropdown Unload (T4) and `EngineModeControl` | unchanged | The HUD button is a second entry point to a different (all-models) endpoint. |
| Persona, WebGL, presence | untouched | Astra's. |

One component mounted by one added line in `HudShell.tsx` (`<HudModelRelease />`); no `[hidden]`, `display: none` or removal is introduced. Live audit (recorded in #690, numbers not invented in advance): at 390 px and 1366 px the row does not overflow its `max-width` and both controls are reachable with the menu open and closed.

### Conformance tests

**#690's own tests** (`tests/test_keep_warm_idle_unload.py`, `frontend/keep-warm-hud.test.mjs`; the final test list is #690's): `test_keep_warm_defaults_off_and_idle_window_is_300_seconds`; `test_keep_warm_is_off_on_a_fresh_install_and_persists_through_the_settings_api`; `test_keep_alive_helper_values_for_off_and_on`; `test_no_hardcoded_keep_alive_string_outside_the_helper`; `test_static_scan_finds_no_hardcoded_keep_alive_anywhere_in_backend`; `test_ollama_gpu_warm_carries_the_policy_keep_alive`; `test_ollama_cpu_warm_carries_300s_when_off_and_minus_one_when_on`; `test_lm_studio_cli_load_gets_a_300_second_ttl_unless_keep_warm_is_on`; `test_lm_studio_rest_load_and_restored_instances_carry_the_ttl`; `test_a_rebuilt_lm_studio_instance_follows_the_policy_only_when_anzu_loaded_it`; `test_every_ollama_request_anzu_sends_carries_keep_alive_for_anzu_models_only`; `test_idle_unload_fires_only_after_300_idle_seconds`; `test_every_turn_resets_the_idle_timer`; `test_agent_tasks_front_replies_and_owner_chat_all_touch_the_timer`; `test_nothing_unloads_while_keep_warm_is_on`; `test_toggling_keep_warm_off_unloads_models_already_idle_past_the_window_immediately`; `test_a_running_task_or_a_refused_release_defers_the_unload`; `test_an_idle_unload_is_policy_not_an_owner_decision`; `test_a_front_responder_released_by_idle_unload_respawns_on_the_next_turn`; `test_release_unloads_every_anzu_loaded_model_and_verifies`; `test_a_foreign_model_is_never_unloaded_by_the_button_or_the_idle_timer`; `test_an_explicit_load_registers_the_model_so_the_idle_timer_unloads_it`; `test_release_fails_with_a_reason_when_ollama_keeps_the_model_resident`; `test_unload_all_is_a_separate_endpoint_and_the_dropdown_unload_is_unchanged`; `test_unload_all_returns_the_verified_per_backend_result`; `test_unload_all_refusals_are_409_with_a_visible_reason_and_touch_nothing`; `test_after_unload_all_background_ensure_and_load_are_refused_and_make_no_http_call`; `test_after_unload_all_every_direct_http_warm_and_refresh_stays_silent`; `test_a_turn_after_unload_all_clears_the_flag_before_ensure_and_respawns_the_model`; `test_an_owner_chat_turn_clears_the_flag_before_it_reaches_ensure`; `test_an_explicit_load_clears_the_flag_even_when_the_load_itself_fails`; `test_ownership_comes_from_the_ledger_not_from_a_model_name`; `test_static_scan_every_direct_load_and_warm_call_site_sits_behind_the_manually_unloaded_guard`; `test_static_scan_the_manager_load_paths_and_front_respawn_check_the_flag`. Frontend: the eight rendered tests in `frontend/keep-warm-hud.test.mjs` (Unload button and Keep warm switch, OFF by default; one POST and a busy state; a 409 shows its reason; a failing backend shows its own reason; the switch persists through the settings API; a failed save keeps the old value; every existing top-bar control stays ahead of the model menu).

**T3 follow-up tests** (the reconciliation rows above; `tests/test_rfc0242_keep_warm_contract.py`, new, in CI step "Run model and security regression tests" and "Run full backend suite"): `test_unload_all_partial_failure_returns_207_with_per_model_results`; `test_unload_all_cancels_pipeline_instead_of_refusing_for_task`; `test_owner_started_instance_never_enters_the_ledger_without_an_anzu_load`; `test_every_ollama_request_path_sets_keep_alive_except_the_studio_model` (request spy over every `/api/generate` and `/api/chat` call in `backend/app`, plus a static scan); `test_ollama_v1_turn_is_followed_by_a_keep_alive_touch_only_if_resident`; `test_toggle_on_repins_every_loaded_anzu_model_with_minus_one` (including a model warmed with `"300s"`); `test_keep_warm_on_repins_lmstudio_instances_without_ttl`; `test_front_only_turn_resets_only_the_front_clock`; `test_reflex_only_turn_does_not_clear_manually_unloaded`; `test_unload_with_nothing_loaded_returns_409_reason_and_sets_no_flag`.

**Ticket card (Taco-owned, built).** *KW = #690:* lane D2; model recorded in its body ("Grok Bot, built locally on D2's box; CoS asked for Grok 4.6, which wasn't available for this local build"), not a gate for this PR. **Ordering:** #690 lands before T3, T4 and T6 on every file they share. T3 depends on #690.

## Slices (one ticket each, one developer each, fast off)

Lane for every ticket: **D2** (the #682 code rework is a development merge into `cursor/model-menu-clarity-99ea`, no rebase; see *Rework of #682*). Tickets can use #682's code as the starting point but must drop every item in the supersession table.

### Rework of #682 (D2 procedure, normative)

1. In the #682 branch, merge `origin/development` (a merge commit; no rebase, no force-push).
2. `docs/rfcs/0242-model-identity-and-menu-clarity.md` conflicts add/add: **take `development`'s file** (this RFC). #682's original text is superseded.
3. `frontend/src/hud/HudModelSelector.tsx` conflicts: **take `development`'s dropdown** and re-apply only the T2, T4 and T6 edits below. Delete `frontend/src/hud/modelSlots.ts`, the bind endpoints, `bindLmStudioProfile` / `bindDiscoveredGguf`, and their tests.
4. Start only after the batch has landed (see *Handoff order*): merge `development` in again at that point, so every shared file is on top of its batch chain.
5. **Keep-warm pieces are not in the rework.** #690 (`feat/hud-unload-keep-warm`) lands the keep-warm, unload-all, ledger, guard and HUD code; #682's T3 commit contains only what *T3* lists (dropdown release, live key, contract closers). #682 merges `development` again after #690 lands.
6. **#682 stays the single code PR.** Land the rework as **one commit per ticket** on its branch (T1 → T2, T3 → T4, T5 → T6; the pairs are ordered). Every commit must pass its own ticket's CI step alone. No rebase, no force-push, no split PRs.

### Handoff order on shared files

"A → B" means A merges first. **RFC-0242's tickets go last on every shared file** (CoS ruling, 2026-10-30), after each file's chain as the batch specs currently read it. The batch PRs are #652 (RFC-0225; final head in this PR's body), #655 (RFC-0228; final head in this PR's body), #664 (RFC-0232; final head in this PR's body), #665 (RFC-0245; final head in this PR's body), #668 (RFC-0233; final head in this PR's body) and #670 (RFC-0211; final head in this PR's body). No batch spec is edited by this RFC: each already names its own chain, and RFC-0242 appends after it. The tickets assume those chains have landed on `development`; D2 merges `development` into #682 once they have and works on top of the merged files. `.github/workflows/pr-tests.yml` and `frontend/package.json` are append-only for every ticket and batch PR, in any order; on a conflict, merge `development` in (merge commit).

| File | Chain (batch chain as each spec reads today, then 0242) | Notes |
| --- | --- | --- |
| `backend/app/inference/lmstudio_catalog.py` | 0242-T1 → 0242-T2 | No batch spec edits it. |
| `backend/app/inference/lmstudio_graded_profiles.json` | 0228-S1 → 0242-T1 | 0228-S1 binds the existing Defiant row to `fable_9b`; T1 adds identity fields to every seed on top of that. |
| `backend/app/inference/backends.py` | 0230-S2 → 0225-S2 → 0242-T5 | T5 touches only `resolve_advertised_model`. |
| `backend/app/inference/lmstudio_server.py` | 0225-S3 → 0228-S2 → 0242-T5 | T5 touches the readiness decision and adds `resolve_lmstudio_artifact`. |
| `backend/app/inference/hotswap.py` | 0225-S3 → 0242-T5 → 0242-T6 | 0225-S3 is the batch's only owner. |
| `backend/app/inference/manager.py` | 0225-S3 → #690 (keep-warm) → 0228-S2 → 0242-T3 → 0242-T6 | #690: `manually_unloaded`, `ModelManuallyUnloaded`, `_guard_background_load`, `_register_loaded`. T3: `unload(release_external=)`, the live key, the ledger fix. T6: `require_model_for_load` in `load`, `ensure_runtime` and `_load_impl`. |
| `backend/app/inference/running_models.py` | 0225-S3 → 0227-S1 → #690 → 0242-T6 | #690: `background_blocked()` on the autoload branches, `explicit_load()` on `use`/`replace`. T6: `require_model_for_load` for `use`/`replace`. T3 does not edit it. |
| `backend/app/api/model.py` | 0225-S3 → 0227-S1 → #690 → 0242-T3 → 0242-T6 | #690: router include for `api/model_unload_all.py`, `explicit_load()` in `load_model`. T3: `unload_model` (single-model verified release). T6: scope and the 409 mapping in `load_model` and `choose_running_model`. |
| `backend/app/inference/loaded_models.py`, `keep_alive.py`, `idle_unload.py`, `keep_warm_release.py`, `backend/app/api/model_unload_all.py` (new in #690) | #690 → 0242-T3 → (0246-S3 adds a studio name guard, see #688) | T3 edits them only for the *Reconciliation with #690* rows. |
| `backend/app/inference/gpu_prefer.py`, `backend/app/inference/ollama_runtime.py`, `backend/app/inference/lmstudio_server.py`, `backend/app/inference/lmstudio_context.py`, `backend/app/inference/front_runtime.py`, `backend/app/providers/base.py` (keep-alive, TTL and guards) | 0225-S3 → #690 → 0228-S2 → 0242-T3 (T3 only through `keep_alive.py`) | #690 owns the `keep_alive`, `ttl` and `warm_blocked()` edits. |
| `backend/app/api/runtime_profiles.py` | 0227-S3 → 0242-T6 | T6 enters the scope in `activate_profile` only. |
| `backend/app/api/lmstudio.py`, `backend/app/engine_mode.py` | 0242-T6 only | No batch spec edits them (the batch cites `engine_mode.py` read-only). |
| `backend/app/inference/status_monitor.py`, `backend/app/inference/model_release.py` (new) | 0242-T3 only | RFC-0230 lists `status_monitor.py` as read-only. `model_release.py` is the dropdown's single-model release only; unload-all lives in #690's `keep_warm_release.py`. |
| `frontend/src/api.ts` | 0230-S0 → 0218-S3 → 0227 → 0245-S6 → 0233-S6 → 0242-T2 | T2 adds type fields only. |
| `frontend/src/hud/HudModelSelector.tsx` | 0227-S3 → 0242-T2 → 0242-T4 → 0242-T6 | 0227-S3's row there is a slot-restore edit that RFC-0244 made obsolete; D2 works on whatever `development` holds after the batch, and does not re-add slots. |
| `frontend/src/hud/HudShell.tsx`, `HudModelRelease.tsx`, `modelRelease.ts`, `modelRelease.css` | #690 only | One added mount line in `.hud-top-right`; no 0242 ticket edits them. |
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

### T3: Verified native release for the dropdown, and the contract closers on top of #690 (backend)

**Model:** Grok 4.6 · **fast mode off** · **Lane:** D2 · **Depends:** **#690** (keep-warm; final head in this PR's body: it creates `loaded_models.py`, `keep_alive.py`, `idle_unload.py`, `keep_warm_release.py`, `api/model_unload_all.py` and edits `manager.py`, `running_models.py`, `api/model.py`, `gpu_prefer.py`, `ollama_runtime.py`, `lmstudio_server.py`, `lmstudio_context.py`, `front_runtime.py`), plus 0225-S3, 0228-S2 and 0227-S1 on the shared files (batch landed).

**What #690 already covers, so T3 does not rebuild it (and no #682 rework of these pieces is needed):** the `manually_unloaded` flag and `ModelManuallyUnloaded`, the guards in `load`, `ensure_runtime`, `ensure_vision`, `_load_locked`, `_load_impl`, `FrontRuntime.ensure_started` and every direct-HTTP warm, the autoload skips in `running_models.py` (`_poll`, the `leave` branch), `POST /api/model/unload-all` with verified release per backend, the ledger, the keep-alive and TTL helper, the idle timer, the HUD Unload and Keep warm controls. **What T3 still owns** (the #682 rework keeps `inference/model_release.py`, now for the dropdown only): the single-model **verified release of the selected model whoever loaded it** (#690's release acts on the ledger only), the live key, the caller-classification test, and the eight contract closers of rows 1-8 in *Reconciliation with #690* (rows 9 and 10 belong to #688's S3). #688's S3 targets #690's symbols, not `model_release.release_all_anzu_loaded` (which no longer exists in this plan).

| File | Change |
| --- | --- |
| `backend/app/inference/model_release.py` (new) | `release_external_model(settings, backend, model)`: LM Studio instance unload and inventory re-check, Ollama `keep_alive: 0` and `/api/ps` re-check, loopback only; used by the dropdown's `POST /api/model/unload` for the **selected** model. Reuses `keep_warm_release`'s readers (`_verified` and the backend probes) rather than a second copy |
| `backend/app/inference/manager.py` | `unload(*, release_external=False)`; `manually_unloaded` added to the live keys (the flag itself is #690's); `MANAGER._register_loaded` stops recording a model that ANZU did not load (reconciliation row 3) |
| `backend/app/api/model.py` | `unload_model`: exclusive lease, 409 and 502 mapping, `release` object in the response (the route stays single-model) |
| `backend/app/api/model_unload_all.py`, `backend/app/inference/keep_warm_release.py` (#690's files) | 207 with the per-backend rows on partial failure; `large_prompt_queue.on_owner_unload(models)` before the exclusive lease; no 409 "task running" for a pipeline task (reconciliation rows 1, 2) |
| `backend/app/inference/keep_alive.py`, `loaded_models.py`, `idle_unload.py` (#690's files) | rows 3 to 8 of the reconciliation: policy `keep_alive` for routed non-ANZU models (never the studio model), the post-turn touch, the toggle-ON re-pin (also LM Studio), a per-model turn reset, a `reflex_only` turn that does not clear the flag |
| `backend/app/inference/status_monitor.py` | `manually_unloaded` added to the live keys |
| `tests/test_rfc0242_model_unload.py` (existing file), `tests/test_rfc0242_load_callers.py` (new), `tests/test_rfc0242_keep_warm_contract.py` (new) | named tests below and in the amendment's "Conformance tests" |

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
- `test_mode_switch_never_unloads_or_claims_release` (`PUT /api/settings` with each `engine_mode`: zero calls to `MANAGER.unload`, `release_external_model` and `release_models`, `manually_unloaded` unchanged, no "unloaded" or "released" in the response)
- `test_selected_owner_started_model_is_released_by_dropdown_unload_and_not_by_unload_all` (the dropdown releases the selected model whoever loaded it; unload-all leaves an owner-started model alone)
- `test_manually_unloaded_is_a_live_key_in_api_model_and_status_monitor`
- `test_offer_use_clears_manual_unload` (`POST /api/model/running/{id}/choice` with `use` loads and clears the flag through `explicit_load()`)
- `tests/test_rfc0242_load_callers.py::test_every_manager_load_caller_is_classified` (static scan of `backend/app`: each `MANAGER.load(`, `MANAGER.ensure_runtime(` and `MANAGER.ensure_vision(` call site is in the §3 table; a new unclassified site fails; complements #690's `test_static_scan_every_direct_load_and_warm_call_site_sits_behind_the_manually_unloaded_guard`)
- `tests/test_rfc0242_keep_warm_contract.py`: the ten tests in the amendment's "T3 follow-up tests".

**CI:** **"Run model and security regression tests"** (append `tests/test_rfc0242_model_unload.py`, `tests/test_rfc0242_load_callers.py` and `tests/test_rfc0242_keep_warm_contract.py`) and **"Run full backend suite"**.

**Acceptance:**
- [ ] The dropdown's Unload releases and verifies only the selected local model through its native runtime, preserves unrelated models and applications, refuses during inference, and never claims success on failure.
- [ ] Until an explicit Load, no background path reloads a model in this session (#690's guards), and an owner turn respawns on demand (and loads nothing under `reflex_only`); callers behave per the §3 table.
- [ ] Every row of *Reconciliation with #690* is closed by a named test: `POST /api/model/unload-all` answers 207 with per-model results on partial failure and is not refused for a pipeline task, and `POST /api/model/unload` stays single-model.
- [ ] A mode switch never unloads and never claims a release; Unload works in every mode.
- [ ] The inventory code is unchanged (R3).

### T4: Unload UI and state propagation (frontend)

**Model:** Composer 2.5 · **fast mode off** · **Lane:** D2 · **Depends:** T3.

| File | Change |
| --- | --- |
| `frontend/src/hud/applyRuntimeProfile.ts` | `unloadCurrentModel()` (the HUD **Unload model** button is #690's `HudModelRelease.tsx` / `modelRelease.ts`, not T4); `finishModelActivation` dispatches `jarvis:model-state-changed`; snapshot type gains `active_model`, `manually_unloaded`, `release` |
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
- `the model-state event from #690's Unload model button (a refreshed /api/model snapshot) is applied by the same App generation guard`

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
- `tests/test_rfc0242_explicit_load.py::test_unscoped_load_class_guards_still_refuse_in_reflex_only` (the same three guards refuse an unscoped caller, an owner turn (`IDLE_UNLOAD.touch()` only) and a background caller with `ModelDisabledError`)
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
| 0242-T3 | Grok 4.6 | D2 | #690 | same | n/a |
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
- [ ] Keep warm defaults off (#690: `inference.keep_warm`, `inference.idle_unload_seconds` 300); with it off every ANZU-loaded model (front responder included) unloads after 5 minutes idle and respawns on demand, and after an explicit Unload only an owner turn (not a background path) respawns on demand; the HUD Unload model button (#690) releases every ANZU-loaded model through `POST /api/model/unload-all` with per-model verified results (200 / 207 / 409 once T3 lands the reconciliation rows); with Keep warm on nothing idle-unloads; every Ollama request ANZU makes carries `keep_alive` (`"300s"` off, `"-1"` on) and no 24 h keep-alive remains; LM Studio loads carry a 300 s TTL when off (amendment, `tests/test_keep_warm_idle_unload.py`).
- [ ] No slot, Pin, bind endpoint or `modelSlots.ts` exists after the rework.
- [ ] Backend regressions, full pytest, frontend build and lint, and the frontend test steps above pass; installed-app status is reported separately.

## Out of scope

Security-gate changes, automatic model downloads or promotion, installer replacement, removing the backend pin flag, routing policy, unrelated model or voice architecture, Astra-owned systems (personas, WebGL, presence), the RFC-0244 engine-mode semantics other than the explicit-Load ruling, and the batch RFCs' own content (none of them is edited).

## Risks

- **#682 add/add conflict on this file.** Resolved by the rework procedure (take `development`'s file). Merge-tree against #682 shows exactly that conflict plus the stale-base noise.
- **`reflex_only` explicit Load changes two RFC-0244 tests** (named in T6). CoS ruling; if it is withdrawn, T6 is dropped (including the offer-card change) and nothing else depends on it.
- **LM Studio inventory shape.** `loaded_instances` is read from the native API; a runtime version without it makes Unload and Load fail closed with a message (never a false success).
- **Ordering with the batch.** RFC-0242 goes last on every shared file, so D2 cannot start a ticket until its files' batch chains have landed; that is the cost of leaving #652 and #655 untouched. If a batch PR slips, only the tickets on its files wait.
- **#690 differs from the contract in nine places** (*Reconciliation with #690*). The contract stays normative; T3 closes each row with a named test, and until it lands the HUD answers 502 (not 207) on a partial failure and refuses Unload while any task runs.
- **Cold first word after an idle unload.** With Keep warm OFF the first request after 5 idle minutes reloads the model, including the front responder, so RFC-0230's first-word budget applies to a warm lane only. The loading state is visible and Keep warm ON restores the warm path (owner order).
- **#690 and T3 overlap on `manager.py`, `running_models.py` and `api/model.py`.** #690 (keep-warm; final head in this PR's body) lands first and 0242 stays last on shared files; T3 is re-gated on #690 and re-traces its symbols when #690 merges (its final names are #690's, mapped in the amendment's "Names" table). If #690 changes a name or a status code before it lands, that table is edited, not the contract.
- **`replace` stops another application's server.** It is an explicit owner click behind the card's existing confirm dialog, and it now also works under `reflex_only` (CoS ruling). Its stop path is unchanged and is verified by the existing unload-verification code (`verify_unloaded`).
