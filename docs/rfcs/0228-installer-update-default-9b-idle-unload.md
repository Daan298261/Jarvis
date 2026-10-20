# RFC-0228: Installer Update mode, 9B Defiant-Fable default with idle unload, installed/greyed options with "can be updated to"

**Status:** accepted  
**Priority:** P2 (Taco batch 2026-10-17, items 5, 6, 7)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20 (re-sliced 2026-10-20: lands on current `development` without drafts #648/#649; D2 review items 1–9 folded in; D2 re-review items 1–3 and second re-review items 1–2 of 2026-10-20 folded in)

**Owner ask (verbatim intent, 2026-10-17):** "5. Add 'Update' as an installer option. 6. Make the default model the 9B uncensored, qwen3.5-9b-defiant-fable-uncensored, at Q3 or Q4 so it stays fast. 7. Grey out options that are already installed. When a newer model with a similar GPU, RAM and disk profile exists for an installed-but-outdated option, mark it '(can be updated to > modelname)'."  
**Owner context (shared memory):** Taco runs the 9B through LM Studio at `http://127.0.0.1:1234/v1`; `anzu-coder-27b` (Ollama, ~12 GB GPU) is for coding; the 9B should get an **idle unload timer** rather than being pinned forever, and ANZU respawns it on demand.  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §6 (fast when simple), §9 ("**ANZU chooses infrastructure.**"), §19 ("Do remove unnecessary complexity from the user's experience."; "Do not remove useful capability merely to simplify the codebase."), §20 Q1 ("Does it reduce the amount of technical knowledge required from the user?"), Q5, Q8, §21 ("can be installed and used with minimal configuration").  
**Amended 2026-10-20 (CoS follow-up):** LM Studio is an engine ANZU can **drive**, not only stop — owner-consented managed mode (RFC-0225 S3/S4) lets ANZU idle-unload and reload Taco's own 9B and yield VRAM to `anzu-coder-27b`.  
**Extends (do not rewrite):** [RFC-0124 clean install / reinstall](0124-clean-install-reinstall-owned-path-wipe.md) (existing-install page and custom-file contract), [RFC-0093](0093-installer-force-stop-and-prepare-unstick.md) / [RFC-0136](0136-zombie-kill-setup-next-and-start.md) (stop before install), [RFC-0196](0196-native-anzu-manager.md) ("All installer choices except the 27B model are selected by default"), [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) (`prepare_engine_for`, VRAM gate, managed mode, respawn/revive/reload terms), [RFC-0227](0227-model-chooser-and-dropdown-persistence.md) S3 (`model-selector.json`), [RFC-0063](0063-local-inference-voice-presentation-stack.md) (benchmark gate), `INSTALLER.md`.  
**Drafts #648/#649:** no gate. Overlapping pieces are ported per "Relationship to drafts #648/#649".  
**Astra boundary:** Persona/presence/WebGL/appearance out of scope (Astra). Installer branding/theme (`ThemeExistingInstallPage`, `ThemeChecklist`) is reused unchanged.

This PR is **specs-only**. No application code.

---

## Problem

Verified in `development` @ `3f17c3d8`:

1. **No "Update".** `installer/windows/Jarvis.iss::InitializeWizard` shows the existing-install page with "Upgrade to ANZU X (recommended)" only when the installer is newer (`ExistingVersionRelation > 0`), otherwise "Repair"; plus Reinstall / Semi-clean / Clean. There is no option to bring **installed components** (models, voices) up to date without reinstalling.
2. **Default model is old and heavy, and there are two 9Bs.** `config/default.json` uses profile `fast` (`Qwen3.5-9B-abliterated-Q6_K.gguf`, `backend/app/inference/profiles.py`), whose fallback is `bootstrap` = **Ornith 1.5 9B Q4_K_M**, which release installers already ship (`Jarvis.iss:147` payload `models\bootstrap\Ornith-1.5-9B-Q4_K_M.gguf`, staged by `installer/windows/stage-bootstrap-model.ps1` / `build-installer.ps1:57`; `bootstrap.ps1::Ensure-BootstrapGguf` downloads it when missing). `dl_localllm` → `bootstrap.ps1` additionally downloads Abiray **Q8_0 + Q6_K**. Taco wants the Defiant-Fable 9B at Q4/Q3. `lmstudio_graded_profiles.json` already matches `["Qwen3.5-9B", "Defiant", "Q4"]` as "Cheap coding 9B".
3. **"New installs only" has no mechanism.** `config.py::load_settings` deep-merges `data_dir()/settings.json` **over** `config/default.json`; an install whose `settings.json` has no `inference.profile` silently follows whatever `default.json` says, so changing the default would switch existing installs.
4. **RFC-0063 benchmark gate.** `default_candidates.py::ModelCandidate` says "A candidate must win the local Jarvis benchmark before it can be promoted to the default runtime" (`benchmark_required = True`), but nothing enforces or records it.
5. **Model pinned forever.** `InferenceSettings` has no idle unload; the managed llama-server and LM Studio instances stay resident; and `inference/gpu_prefer.py::ensure_ollama_gpu` warms every ANZU-started Ollama model (incl. the Umi persona brain via `ollama_runtime.ensure_local_ollama`) with `keep_alive: "24h"`, competing with `anzu-coder-27b` for VRAM.
6. **The orchestrator default and its idle restore are hard-wired to Ornith.** `inference/profile_roles.py::default_orchestrator_profile_name()` returns `"ornith_9b"` and `orchestrator_profile_names()` returns `("ornith_9b", "bootstrap")`. `inference/model_escalation.py::schedule_orchestrator_restore` (called after every chat turn from `agent/loop.py` and after every visible switch to a heavy model) sleeps `orchestrator_idle_seconds` (default 120 s) and then calls `MANAGER.load(app, "ornith_9b")` whenever the loaded profile is not an orchestrator profile; any exception is swallowed (`except Exception: return`). `effective_answer_profile_name` also falls back to `ornith_9b`. With a Fable-only fresh install this either fails silently (no `Ornith-1.5-9B-Q8_0.gguf`) or swaps the worker away from `fable_9b`, and it is a second reload path racing this RFC's 9B reload.
7. **Installed options are indistinguishable.** The `[Tasks]` checklist (`dl_kokoro`, `dl_personavoices`, `dl_whisper`, `dl_voicestudio`, `dl_pockettts`, `dl_umi_brain`, `dl_localllm`, `dl_expert27b`, voice-pack tasks) is `checkedonce` regardless of what is on disk, with no notion of a newer replacement.

**Verified external fact (2026-10-20, Hugging Face listing):** the GGUF repo is `DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF`; regular quants include `…-NEO-MAX-Q4_K_S.gguf` (≈6.10 GB), `…-Q4_K_M.gguf` (≈6.36 GB), `…-IQ4_XS.gguf` (≈5.96 GB), `…-IQ3_M.gguf` (≈5.23 GB); MTP variants exist. The LM Studio model key Taco uses (`qwen3.5-9b-defiant-fable-uncensored`) is taken from the owner's message and must be confirmed against `lms ls` on Taco's PC (S1).

## Decision

Ship **one RFC with three implement slices** (one named model each, **fast off**). None waits for #648/#649.

### Default model (normative)

- New profile `fable_9b` in `profiles.py` (existing `fast`, `balanced`, `bootstrap`, `ornith_9b`, `expert` and Abiray entries are **kept**, not deleted): repo above, file **Q4_K_S regular** (not MTP — MTP needs temp ≤1 and has acceptance caveats), fallback **IQ3_M** when free VRAM < 7 GB or disk < 8 GB. Repo commit SHA + file SHA256 pinned in `installer/windows/model-catalog.json` at implement time (same pinned-revision + SHA pattern as `runtime_install.py` uses for its downloads); download verified before the profile is selectable.
- **RFC-0063 gate (D2 #4).** `default_candidates.py` gains `benchmark_evidence: str` on `ModelCandidate` and `promotable_default(candidate, incumbent) -> bool`: true only if `benchmark_required` is false, or `benchmark_evidence` names a committed report produced by `inference/harness.py::run_harness` (same report shape as `load_last_report()`) whose score is ≥ the incumbent's on the same machine. S1 runs the harness for the Fable 9B Q4_K_S and the incumbent (`fast`, falling back to Ornith `bootstrap`) on Taco's PC and commits `docs/rfcs/assets/0228-fable-9b-benchmark.json`. The Fable candidate is admitted as default **only** through `promotable_default`; if it loses, S1 stops and reports to the Architect (no default change).
- **Ornith decision (Architect, normative; D2 #5).** Fresh installs ship and use **one** default 9B: the Fable 9B Q4_K_S **replaces** Ornith 1.5 9B Q4_K_M as the installer payload (`Jarvis.iss` payload line, copied only per "Payload copy rule" below; `stage-bootstrap-model.ps1`, `build-installer.ps1`) and as `bootstrap.ps1`'s missing-model download, so a fresh install never downloads a second ~6 GB 9B. If LM Studio is already serving the Fable 9B at install / first run (`installer/windows/detect-lmstudio-model.ps1` probes `http://127.0.0.1:1234/api/v1/models`, else `lms ls`), Setup attaches to it (backend `lmstudio`, port 1234, `remote_model` = that key) and copies/downloads **no** 9B at all; the owner is told which was chosen. Existing installs that have Ornith **keep** it and the `bootstrap` / `ornith_9b` profiles; the installer shows it as `(can be updated to > Qwen3.5 9B Defiant-Fable Q4)`.
- **"New installs only" mechanism (D2 #3).**
  - *Fresh install:* `bootstrap.ps1` (and, as a safety net, the first `load_settings()` that finds no `settings.json`) writes an explicit `inference` block into `data_dir()/settings.json`: `profile: "fable_9b"` (or the LM Studio attach settings above), plus marker `migrations: ["0228_profile_pinned"]`.
  - *Existing install (migration, runs before the default changes):* Inno `PrepareToInstall` (before files are copied) runs `installer/windows/pin-effective-profile.ps1`, which reads the **old** `{app}\config\default.json` and `settings.json`, and writes the currently effective `inference.profile` (and `backend`/`host`/`port`/`remote_model` when absent) into `settings.json` with the marker. Backend safety net in `config.py::load_settings`: if `settings.json` exists, lacks `inference.profile` and lacks the marker, pin `LEGACY_DEFAULT_PROFILE = "fast"` (the `default.json` value before this RFC) and add the marker. Only after both exist does `config/default.json` change to `"profile": "fable_9b"`.
  - Result: `default.json`'s profile is never the effective profile of any install that existed before this change.
- **Payload copy rule (D2 re-review #2).** Inno copies `[Files]` on Upgrade, Repair, Reinstall and (S3) Update too, so the Fable payload line must never copy unconditionally. The line is `Source: "payload\models\bootstrap\<Fable Q4_K_S file>"; DestDir: "{app}\models\bootstrap"; Flags: ignoreversion; Check: ShouldCopyDefault9BPayload`, and `ShouldCopyDefault9BPayload` (S1, `[Code]`) is true **only** when LM Studio is not already serving Fable **and** one of:
  - fresh install (`not ExistingInstallDetected`), or Clean reinstall (models wiped; tested through a named helper `ExistingActionIsClean`, not a raw page index, so S3's new Update entry cannot shift it);
  - existing install whose pinned profile (written by `pin-effective-profile.ps1` in `PrepareToInstall` to `{tmp}\pinned-profile.txt`) is already `fable_9b` and the Fable file is missing under `{app}\models\bootstrap` (repair of its own default);
  - (added by S3) the owner opted in to the successor: `Default9BSuccessorOptedIn` = the `(can be updated to > Qwen3.5 9B Defiant-Fable Q4)` task ticked, or `/UPGRADEMODELS` names `fable_9b`.
  Upgrade / Repair / Reinstall / Semi-clean / Update of an Ornith or Abiray install with the successor unticked therefore copies **no** Fable file. The same rule gates `bootstrap.ps1`'s download: it never fetches Fable on an existing install unless it was opted in (`-UpgradeModels fable_9b`) or that install's own pinned profile is `fable_9b`.

### Idle unload + reload (normative)

Terms are RFC-0225's: **reload** = loading a model into a listening engine (this RFC); **revive** / **respawn** = RFC-0225. `prepare_engine_for()` (RFC-0225 S3) is the single entry; this RFC registers the idle state through `engine_coexistence.note_idle_unload()` so RFC-0225 never treats an idle-unloaded engine as dead or foreign, and supplies the reload routine `prepare_engine_for` delegates to. Single-flight is RFC-0225's (no double reload).

- `InferenceSettings.idle_unload_seconds` (default **900**, `0` = pinned; range 0–86400). Applies to the **worker** model only; the front lane (`front_responder.resident`) is unchanged.
- Managed llama-server: after `idle_unload_seconds` with no request lease held and no task running, `MANAGER.unload()`; next request transparently reloads (same profile/context), with the existing "Loading model…" HUD state and elapsed timer.
- LM Studio selected engine, **managed mode off** (default): pass a native TTL when the installed LM Studio supports it (`lms load --ttl` / REST `ttl`), else ANZU's own timer calls `/api/v1/models/unload` for the instance it loaded; on demand ANZU reloads through `lmstudio_context`/`ensure_local_lmstudio`. "The instance it loaded" is an entry in the RFC-0225 engine ledger's `anzu_loads` section (the S2 reload routine calls `engine_coexistence.record_anzu_load()` after each verified load, and `forget_anzu_load()` after each verified unload). ANZU never unloads LM Studio instances it did not load.
- LM Studio selected engine, **managed mode on** (RFC-0225 `is_managed()`; consent asked once in the RFC-0225 S4 prompt / Model page, remembered, revocable): ANZU may load, unload and reload **any** instance of the selected model(s) on that LM Studio, including instances the owner loaded himself (e.g. Taco's 9B on :1234). It applies `idle_unload_seconds` to them, preferring LM Studio's native TTL (re-load the instance with `ttl` via REST / `lms load --ttl`, same model key + context as the owner's instance) and otherwise its own timer + `/api/v1/models/unload`; on the next request it reloads via the LM Studio API / `lms load` with the recorded model key and context, then answers. Managed mode never stops the LM Studio server or app.
- **Ollama keep-alive (D2 #7, per-engine rule).** Every ANZU-originated Ollama load/warm (`gpu_prefer.ensure_ollama_gpu`, chat/generate requests ANZU sends) uses `keep_alive = f"{idle_unload_seconds}s"`, and `"-1"` (pinned) when `idle_unload_seconds == 0`; the hard-coded `"24h"` is removed from that call. **The Umi persona brain is not an exception:** it follows the same value, and the next Umi turn reloads it through the existing `ensure_local_ollama` path in `api/named_personas.py`. Ollama models ANZU did not load (Taco's `anzu-coder-27b` started from his shell) are never sent a `keep_alive` by the idle timer; requests ANZU routes to them carry the same derived `keep_alive`, which is the only effect.
- **VRAM yielding for `anzu-coder-27b`.** The VRAM gate itself is RFC-0225 S3 (`prepare_engine_for` step 5): an **ANZU-loaded** 9B (the managed llama-server worker, or an LM Studio instance in `anzu_loads`) is unloaded in any mode with one owner line; an **owner-loaded** 9B is unloaded only with managed mode on, and with managed mode off the request fails visibly naming the owner-loaded 9B. This RFC adds the re-warm through the single 9B re-warm coordinator below: once the 27B has left VRAM (its `keep_alive` = `idle_unload_seconds` expired and Ollama `/api/ps` no longer lists it; never earlier, see the coordinator rule), ANZU reloads whichever 9B the gate unloaded (ANZU-loaded: any mode; owner-loaded: managed mode on only, with the recorded key + context) so ordinary chat is warm again, one owner line "Reloaded the 9B.".

### Orchestrator default + one 9B re-warm path (normative; D2 re-review #1, owned by S2)

- **Default follows the saved / selected 9B, derived from the profile catalogue (D2 second re-review #2).** `profile_roles.py`: `fable_9b` joins `_ORCHESTRATOR` (role `orchestrator`, tier 1) and `orchestrator_profile_names()` returns `("fable_9b", "ornith_9b", "bootstrap")`. There is **no hand-written 9B list**. Instead:
  - `catalog_profile(name) -> ModelProfile | None` looks the name up **without fallback** in `profiles.declared_profiles()`, `model_discovery.resolve_discovered_profile`, `qwen38_9b_profile()` and `qwen38_27b_heretic_profile()`. `resolve_profile()` is deliberately not used, because it silently maps unknown names to `bootstrap` / `balanced`.
  - `profile_param_billions(profile) -> float | None` parses the catalogue `alias` with `(?<![\w.])(\d+(?:\.\d+)?)[Bb](?![a-z])` (first match). On `development` this gives `bootstrap` / `ornith_9b` "Ornith-1.5-9B" → 9, `fast` / `balanced` / `quality` "Qwen3.5-9B" → 9, `expert` "Qwen3.5-27B" → 27, `ornith_35b` "Ornith-1.5-35B-A3B" → 35 (the `A3B` is skipped by the look-behind), `front_2b` / `front_4b` → 2 / 4, `qwen38_9b` → 9, `qwen38_27b_heretic` → 27, a `local_gguf` profile → from its file-stem alias, and `fable_9b` (S1 alias "Qwen3.5-9B-Defiant-Fable") → 9.
  - `is_nine_b_worker(profile)` is `7 <= profile_param_billions(profile) <= 10`.
  - `default_orchestrator_profile_name(settings=None) -> str | None` (settings re-read with `load_settings()` when not passed) returns, for **every** saved profile:
    - saved profile in the catalogue and `is_nine_b_worker` → that name: `fable_9b` (fresh install), `bootstrap` / `ornith_9b` (kept Ornith), `fast`, `balanced` and `quality` (kept Abiray; `balanced` and `quality` are the Abiray Q8_0 profiles), `qwen38_9b`, or a 9B `local_gguf`;
    - LM Studio attach (backend `lmstudio`, no profile) → the selected `settings.inference.remote_model`;
    - saved profile in the catalogue but not a 9B worker (`expert`, `ornith_35b`, `qwen38_27b_heretic`, `front_*`) → `None`, meaning the owner chose that model as the worker, so there is no restore target;
    - saved name not in the catalogue (unknown / renamed) → `None`, plus one `orchestrator_restore_skipped reason=unknown_profile name=<n>` log line per process (no per-turn owner line).
  - `None` means `NINE_B_REWARM` does nothing for the orchestrator trigger and **the loaded model is kept**. No swap happens and no "missing file" line is shown on every turn. The literal `"ornith_9b"` is never returned unconditionally. `infer_runtime_role_and_tier` keeps every existing mapping (`tests/test_rfc0115_routing.py` unchanged).
- **One coordinator.** New `backend/app/inference/rewarm.py::NINE_B_REWARM` is the only code that reloads the 9B on a timer. It owns one `asyncio.Lock` and at most one pending timer. Two triggers feed it: `model_escalation.schedule_orchestrator_restore` (after a heavy turn, delay `orchestrator_idle_seconds`) and the 27B-idle re-warm above. A new schedule keeps the earlier due time; it never starts a second timer.
- **A 9B the VRAM gate unloaded is re-warmed only by the 27B-idle trigger (D2 second re-review #1).** When the RFC-0225 gate unloads a 9B to make room for a large model, it records `engine_coexistence.note_gate_unload(nine_b=<target>, heavy=<engine, model>)` (an RFC-0225 S3 hook, next to `note_idle_unload`). `NINE_B_REWARM` reads it through `engine_coexistence.gate_unloaded()` and clears it with `clear_gate_unload()`. While that marker is set:
  - the orchestrator trigger is a **no-op** (dropped, not deferred);
  - the 27B-idle trigger fires only once the heavy model has **left VRAM**: Ollama `/api/ps` no longer lists it (its `keep_alive` = `idle_unload_seconds` expired), or, for an LM Studio / llama-server heavy model, native inventory shows it unloaded. Until then it re-polls `/api/ps` every 30 s off the event loop.
  - Then exactly one reload of the gate-unloaded 9B runs, with one owner line "Reloaded the 9B.", and the marker is cleared.
  - A new request for the heavy model while waiting keeps it resident and the wait continues. A chat request for the 9B while the 27B is resident goes through `prepare_engine_for`, where the RFC-0225 gate decides, never through the timer.
  - **Decision (Architect): defer rather than force-unload the 27B.**
    - *VRAM:* both choices avoid oversubscription. Deferring never holds two large models at once, and it never evicts a model ANZU just loaded for an active coding session.
    - *Latency:* force-unloading the 27B at 120 s would make the next coding request (bursty, minutes apart) pay a ~12 GB reload, then evict the 9B again through the gate. That ping-pong costs two large loads per coding burst. Deferring costs at most one 9B reload (the existing "Loading model…" state) on the first chat turn after a coding burst, and only when that turn arrives before the 27B idles out.
    - The 27B is still never held longer than `idle_unload_seconds` (15 min default).
  - **Last guard:** the coordinator measures free VRAM (RFC-0225 `vram.py`) before any timer reload and skips the reload if free < the 9B requirement + 1 GB. So a restore never loads the 9B while a resident model leaves no room, whoever loaded that model.
- **`schedule_orchestrator_restore` stops calling `MANAGER.load` itself.** It calls `NINE_B_REWARM.schedule(reason="orchestrator_restore", delay=orchestrator_idle_seconds(app))`. On fire, under the lock, the coordinator re-reads settings, resolves the target with `default_orchestrator_profile_name()`, and:
  - target already loaded → no-op;
  - target is `None` (non-9B or unknown saved profile) → no-op, loaded model kept;
  - a gate-unload marker is set → no-op (see above);
  - the 9B was unloaded by the idle timer (`engine_coexistence.idle_unloaded()` true, timestamp `unloaded_idle_at`) → no-op; it is **never** reloaded by a timer, only by the next request through `prepare_engine_for` (the S2 idle unload also cancels any pending re-warm);
  - a request lease is held → waits for it (same bound as the idle timer);
  - target weights missing → no swap away from the loaded model, and one owner-visible line "Couldn't switch back to <target>: its model file is missing." (no silent `return`);
  - otherwise reloads through the **same** S2 reload routine (`prepare_engine_for` → reload: `MANAGER.load(app, target)` for the managed llama-server, the `lmstudio_server` reload routine for LM Studio), so `prepare_engine_for`'s single-flight joins it with any concurrent on-demand reload; a failure is surfaced with the engine error, never swallowed and never retried in a loop.
- `effective_answer_profile_name` falls back to `default_orchestrator_profile_name()` (the saved 9B), then to the loaded profile, then to the saved profile name, never to `ornith_9b`. `agent/loop.py` is not edited (it keeps calling `schedule_orchestrator_restore`).
- **Owner-visible lines:** delivered through RFC-0225's "Owner-line surfaces" (`engine_coexistence.owner_line()`; failures also on the HUD health rail through the `engines` self-check item); exactly one line per unload-for-VRAM (RFC-0225) and per re-warm reload; idle unloads are logged and shown in the HUD model state ("unloaded (idle) for 12 min", consumed by RFC-0229 S2), not announced. Every failed unload/reload is surfaced to the owner with the LM Studio/Ollama error; never swallowed, never retried silently in a loop.
- Never unload during an active stream, tool loop or task stage; the timer resets on every lease.

### Installer Update + installed state (normative)

1. **"Update" option** on the existing-install page, inserted as a new first-class entry: "&Update ANZU — keep everything, refresh the app and bring installed models and voices up to date". Existing entries (Upgrade/Repair primary, Reinstall, Semi-clean, Clean) are **kept with their current text and behaviour**; when the installer is newer, Upgrade stays the default selection; when versions match, Update becomes the default selection (Repair stays available).
2. **Update never auto-switches the model (D2 #1).** Update = Upgrade/Repair file copy + refresh of **installed** components at their current version (re-verify, repair missing files). The saved profile (`settings.json`, pinned per the mechanism above) and the HUD slots (`data_dir()/hud/model-selector.json`, RFC-0227 S3) are kept byte-identical. A successor is downloaded **only** when the owner ticks its `(can be updated to > …)` task (rule 4); after it verifies, the profile switches to it **only because the owner opted in through that tick**, and the old files and profile are kept so slots that reference them keep working. Unticked → nothing downloaded, nothing switched.
3. **Installed detection** from a shared manifest `installer/windows/model-catalog.json` (component id → files/markers, version, GPU/RAM/disk profile, `superseded_by`, pinned repo commit + SHA256) evaluated by `installer/windows/installed-components.ps1` (also usable by the backend). Inno reads its JSON result.
4. **Greyed tasks:** already-installed, up-to-date components are shown checked + disabled with suffix "(installed)". Installed-but-outdated components with a successor whose VRAM, RAM and disk needs are each within **±25 %** (or lower) of the installed one are shown **unchecked** and enabled, labelled `(can be updated to > <successor display name>)`; ticking it is the owner's opt-in (rule 2).
5. Fresh installs: no greying; default selections as RFC-0196 (27B unchecked); single default 9B per the Ornith decision.
6. Silent mode (`/VERYSILENT`) supports `/UPDATE` with the same semantics (no successor unless `/UPGRADEMODELS=<ids>` names it).
7. The `dl_localllm` description changes to the Defiant-Fable 9B; existing Abiray 9B and Ornith 9B installs are "outdated" with successor `fable_9b` (similar profile) → labelled per rule 4.

### Taco's setup fixtures (normative, D2 #2)

`tests/fixtures/rfc0228_taco/` (new), reusing RFC-0227 S3's `tests/fixtures/rfc0227_taco/model_selector_with_27b.json` and `fable_9b_rebind.json`:

| Fixture | Content | Asserted by |
| --- | --- | --- |
| `settings_lmstudio_9b.json` | `settings.json` with `inference.backend: "lmstudio"`, port 1234, `remote_model: "qwen3.5-9b-defiant-fable-uncensored"`, no `profile` key, no marker | S1 migration pins without changing backend/port/remote_model; S3 Update keeps it byte-identical |
| `installed_tree_ornith_abiray.json` | Install tree listing Ornith bootstrap GGUF + Abiray Q6_K + Kokoro + Pocket TTS | S3 detection: Ornith + Abiray labelled `(can be updated to > …)`, voices "(installed)" |
| (RFC-0227) `model_selector_with_27b.json` | Slots incl. `anzu-coder-27b` | S3: Update leaves `model-selector.json` byte-identical |
| (RFC-0227) `fable_9b_rebind.json` | Slot bound to the old LM Studio catalog id | S3: after an opted-in successor download, the slot re-binds to `fable_9b` by fingerprint (RFC-0227 S3 logic, not re-implemented) |

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

Touched live UI: installer existing-install page and task checklist; Settings → Models; HUD model state during reload.

| Current live behaviour | Preserved? | Added alongside |
| --- | --- | --- |
| Existing-install page: Upgrade (newer) / Repair (same) primary, Reinstall, Semi-clean, Clean, with current texts and confirmations | **Yes**, all kept, same order after the new entry | "Update" entry |
| `[Tasks]` checklist with Select-all (`CreateSelectAll`), theming, groups | **Yes** | Disabled+checked "(installed)" items; unchecked "(can be updated to > …)" items |
| RFC-0124 custom-file contract (Upgrade/Repair keep custom files) | **Yes** — Update keeps custom files identically | — |
| 27B Expert unchecked by default | **Yes** | — |
| HUD "Loading model…" + elapsed during load | **Yes** (reused for on-demand reload) | "unloaded (idle)" state |
| Settings → Models pane (every existing select, button and message) | **Yes**, untouched | Self-contained "Unload when idle" control, one mount line |
| Existing model profiles (`fast`, `bootstrap`/Ornith, Abiray Q8/Q6, `expert`, …) selectable | **Yes**, none deleted | `fable_9b` |

### Stub rule

No stubs. A catalog entry with no SHA, an "Update" option that behaves exactly like Repair, a gate function nobody calls, a migration with no test, or a timer setting that is never read, is a fail.

---

## Relationship to drafts #648/#649

PG ruling via CoS (2026-10-20): no gate. Ported pieces are cited "Ported from #648 `<file>::<function>`".

| Draft piece | Decision | Slice |
| --- | --- | --- |
| #648 `inference/lmstudio_server.py::_loaded_model_ids` (native inventory) + model-ready check | Ported in RFC-0225 S3 (sequential predecessor of `lmstudio_server.py`); S2 reuses it to detect idle-unloaded vs loaded instances | 0225-S3 → S2 |
| #648 `config.py` — `InferenceSettings.gguf_path`; `_SETTINGS_WRITE_LOCK`; `_saved_snapshot`; `_merge_settings_changes` (save writes only keys changed since load, merged over the file on disk); atomic temp-file write in `save_settings` | Ported (S2 persists `idle_unload_seconds` and must not clobber the saved selection, which Update relies on) | S2 |
| #648 `inference/manager.py` — `_same_endpoint(settings)` reuse check; `_loaded_profile`; `requested_context_size`; profile/`gguf_path` read from settings; `_load_locked` wrapper that on `Exception`/`CancelledError` clears `loading`/`loaded`/`provider`, records `last_error` and invalidates the status cache; `_active_profile` / `_assemble_snapshot` via `asyncio.to_thread` | Ported (a cancelled idle reload must not leave `loading=True`; reload must not reuse a different endpoint) | S2 |
| #648 `inference/hotswap.py::apply_runtime_profile_to_settings(persist=False)`, save only after a successful load | Ported (a failed reload never overwrites the saved profile) | S2 |
| #648 `api/model.py::load_model` resets `settings.inference.gguf_path = ""` when a profile is chosen | Ported | S2 |
| #648 tests `test_profiles.py::test_unloaded_snapshot_uses_profile_context` (parametrized fast/balanced) and `test_inference_backends.py::test_unloaded_snapshot_uses_configured_fast_profile`, `test_runtime_activate.py` fake signatures (`**kwargs`, `saved == []` on failed activation) | Ported as exactly those changes (required by the ported manager/hotswap behaviour; all other assertions kept) | S2 |
| #649 `frontend/src/settings/ModelsSettingsPane.tsx` (`front_08b` option + "Download quick 0.8B model" button), `profiles.py` `front_08b`, `runtime_install.py::_install_front_08b` | Not needed; S2 adds a separate component and one mount line outside the front-lane `<select>` block #649 edits, so neither side rewrites the other | — |
| #648 `Jarvis.iss` `Excludes` additions, `force-stop-jarvis.ps1` `$null = $polite.WaitForExit(...)` | Not needed by this RFC (packaging hygiene / stop script); S1/S3 hunks in `Jarvis.iss` are in `[Files]` payload, `[Code]` and `[Tasks]` and do not touch those lines | — |

**Reconciliation rule:** if a draft lands first, the slice reuses the draft's code for the ported piece (no second settings lock, no second `_same_endpoint`) and adds only what this RFC specifies beyond it. If a slice lands first, the draft rebases onto it and drops its identical hunk.

---

## Slices (one ticket each)

Assign order: **S1 → S2; S3 after S1.**

### S1 — Defiant-Fable 9B default: gate, single default 9B, profile pinning

**Model:** Grok 4.5 (fast off) · **Lane:** D1 · **Depends:** none

| Path | Why |
| --- | --- |
| `backend/app/inference/profiles.py` | Add `fable_9b` (Q4_K_S) + IQ3_M fallback; keep all existing profiles (incl. `bootstrap`/Ornith) |
| `backend/app/inference/lmstudio_graded_profiles.json` | Bind the existing Defiant Q4 graded row to `fable_9b` |
| `backend/app/inference/default_candidates.py` | Fable candidate; `benchmark_evidence`; `promotable_default()` |
| `docs/rfcs/assets/0228-fable-9b-benchmark.json` (new) | Harness reports (Fable vs incumbent) from Taco's PC |
| `backend/app/config.py` | `LEGACY_DEFAULT_PROFILE`; first-load explicit profile write; existing-install pin + marker (first owner; chain S1 → S2) |
| `config/default.json` | `"profile": "fable_9b"` (after the pin mechanism exists, same PR) |
| `installer/windows/pin-effective-profile.ps1` (new) | Existing-install migration run from `PrepareToInstall`; also writes the pinned profile name to `{tmp}\pinned-profile.txt` for `ShouldCopyDefault9BPayload` |
| `installer/windows/detect-lmstudio-model.ps1` (new) | LM Studio attach detection |
| `installer/windows/bootstrap.ps1` | Fresh install writes explicit `settings.json` profile; `Ensure-BootstrapGguf` → Fable Q4_K_S (IQ3_M by VRAM/disk), SHA256-verified, resumable; skip when Ornith/Fable present or LM Studio serves Fable; `-InstallLocalLLM` no longer downloads a second 9B on fresh installs; on an existing install the Fable download runs only when that install's pinned profile is `fable_9b` and the file is missing (first owner; chain S1 → S3) |
| `installer/windows/stage-bootstrap-model.ps1`, `installer/windows/build-installer.ps1` | Stage the Fable Q4_K_S payload instead of Ornith |
| `installer/windows/Jarvis.iss` | Only: payload `Source:` line (Fable instead of Ornith, `Check: ShouldCopyDefault9BPayload` per the payload copy rule), the `[Code]` functions `ShouldCopyDefault9BPayload` / `ExistingActionIsClean` / `ExistingFable9BMissing`, and the `PrepareToInstall` call to `pin-effective-profile.ps1` (which also writes `{tmp}\pinned-profile.txt`) (first owner; chain S1 → S3) |
| `INSTALLER.md` | Update the Models line |
| `tests/test_rfc0228_default_model.py`, `tests/test_rfc0228_profile_pinning.py`, `tests/test_rfc0228_benchmark_gate.py`, `tests/test_rfc0228_installer_payload.py` (new) | Below |

- [ ] Fresh install config resolves profile `fable_9b` to the Q4_K_S file; low VRAM/disk fixture resolves IQ3_M.
- [ ] Download is SHA256-verified; a corrupted file is rejected and retried, never registered.
- [ ] **(D2 #3)** Fresh install (no `settings.json`) → `settings.json` written with explicit `inference.profile: "fable_9b"` and the marker; changing `default.json` afterwards does not change it.
- [ ] **(D2 #3)** Existing install with `settings.json` lacking `profile` (fixture `settings_lmstudio_9b.json`) → pinned to the effective pre-change profile (`fast`) with backend/port/`remote_model` unchanged; second run is a no-op (marker); `pin-effective-profile.ps1` produces the same result from the old `default.json` (PowerShell test via `tests/test_installer.py` patterns).
- [ ] **(D2 #4)** `promotable_default()` false without evidence or with a lower score; true with the committed report; the configured default candidate passes it (test reads the committed JSON); `tests/test_default_candidates.py` passes unchanged.
- [ ] **(D2 #5)** Fresh install payload contains exactly one 9B GGUF (Fable) and no Ornith; LM Studio serving Fable (fixture) → no 9B copied/downloaded, attach settings written, owner told; existing install with Ornith → Ornith file and profiles untouched.
- [ ] **(D2 re-review #2)** `tests/test_rfc0228_installer_payload.py` (new, static ISS test in the `tests/test_installer.py` style; the ISCC compile runs in the existing `installer-compile` CI job): `test_fable_payload_line_has_copy_check` (the only `[Files]` line sourcing the Fable GGUF carries `Check: ShouldCopyDefault9BPayload`; no Ornith payload line remains; no other line sources a 9B GGUF); `test_copy_check_true_only_for_fresh_clean_or_own_repair` (the function body returns true only through `not ExistingInstallDetected`, `ExistingActionIsClean` and `ExistingFable9BMissing`, and is false when LM Studio serves Fable); `test_existing_install_without_opt_in_never_copies_fable` (Upgrade / Repair / Reinstall / Semi-clean with an Ornith pin → no branch of the function can return true); `test_bootstrap_never_downloads_fable_on_existing_install_without_opt_in` (`bootstrap.ps1` PowerShell test with the Ornith/Abiray fixture tree → no Fable download, no file under `models\`). Windows soak: Upgrade of an Ornith install → no Fable file in `{app}\models`, Setup log shows the file skipped by its Check.
- [ ] LM Studio model key confirmed on Taco's PC and recorded in the PR.

### S2 — Worker idle unload, reload, Ollama keep-alive, ported selection safety

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S1, RFC-0225 S3 (sequential owner of `lmstudio_server.py`, `manager.py`, `hotswap.py`), RFC-0225 S4 (managed-mode consent UI), RFC-0227 S1 (sequential owner of `api/model.py`)

| Path | Why |
| --- | --- |
| `backend/app/config.py` | `InferenceSettings.idle_unload_seconds`; ported #648 `gguf_path`, `_SETTINGS_WRITE_LOCK`, `_saved_snapshot`, `_merge_settings_changes`, atomic write (second owner after S1) |
| `backend/app/inference/manager.py` | Ported #648 `_same_endpoint`, `_loaded_profile`, `requested_context_size`, `_load_locked` cancel/failure cleanup, `to_thread` snapshot; idle timer bound to request lease/task activity; unload (cancels any pending `NINE_B_REWARM`); transparent reload (second owner: 0225-S3 → 0228-S2) |
| `backend/app/inference/rewarm.py` (new) | `NINE_B_REWARM`: the single 9B re-warm coordinator (one lock, one timer) for the orchestrator restore and the 27B-idle re-warm; reads the RFC-0225 `gate_unloaded()` marker and runs the heavy-model residency wait; free-VRAM guard; reloads only through `prepare_engine_for` |
| `backend/app/inference/profile_roles.py` | `fable_9b` in `_ORCHESTRATOR` and `orchestrator_profile_names()`; `catalog_profile()`, `profile_param_billions()`, `is_nine_b_worker()` (catalogue-derived, no hand list); `default_orchestrator_profile_name(settings=None) -> str | None` defined for every saved profile (only owner in the batch: 0228-S2) |
| `backend/app/inference/model_escalation.py` | `schedule_orchestrator_restore` → `NINE_B_REWARM.schedule(...)` (no direct `MANAGER.load`, no swallowed exception); `effective_answer_profile_name` falls back to the saved 9B (only owner in the batch: 0228-S2) |
| `backend/app/inference/hotswap.py` | Ported #648 `apply_runtime_profile_to_settings(persist=False)` + save after successful load (second owner after 0225-S3) |
| `backend/app/api/model.py` | Ported #648 `load_model` `gguf_path` reset (after 0227-S1) |
| `backend/app/inference/lmstudio_server.py` | Native TTL capability detection; reload routine (`lms load` with recorded key/context/TTL) registered with `engine_coexistence` (second owner after 0225-S3) |
| `backend/app/inference/lmstudio_context.py` | Pass TTL on load; unload only ANZU-loaded instances when managed mode is off, any instance of the selected model(s) when `is_managed()` is on (read-only import from RFC-0225 `engine_coexistence.py`; that file is not edited here) |
| `backend/app/inference/gpu_prefer.py` | `ensure_ollama_gpu` `keep_alive` derived from `idle_unload_seconds` (rule above) |
| `frontend/src/settings/IdleUnloadControl.tsx` (new) | "Unload when idle" select (Never / 5 / 15 / 30 / 60 min) reading/writing `idle_unload_seconds` |
| `frontend/src/settings/ModelsSettingsPane.tsx` | One mount line for `<IdleUnloadControl />` below the existing controls (no other hunk) |
| `frontend/idle-unload-control.test.mjs` (new); `frontend/package.json` (`test:idle-unload-control`, one line); `.github/workflows/pr-tests.yml` (one append-only `frontend-build` step `- name: Idle unload control tests (RFC-0228 S2)` / `run: npm run test:idle-unload-control`) | Below (D2 #6) |
| `tests/test_rfc0228_idle_unload.py`, `tests/test_rfc0228_settings_merge.py`, `tests/test_rfc0228_orchestrator_restore.py` (new); `tests/test_profiles.py`, `tests/test_inference_backends.py`, `tests/test_runtime_activate.py` (only the ported #648 changes listed above) | Below |

- [ ] No requests for `idle_unload_seconds` → worker unloaded (VRAM freed in Windows soak); front lane untouched; `engine_coexistence.idle_unloaded()` true.
- [ ] Next request reloads and answers via RFC-0225 `prepare_engine_for` (reload path, no revive/respawn, single call under concurrency); HUD shows the existing loading state; no error banner.
- [ ] Timer never fires during a stream, tool loop or task stage (tests with held lease).
- [ ] LM Studio, managed mode off: ANZU unloads only the instance it loaded; an owner-loaded instance is never unloaded.
- [ ] Managed mode on + Taco's owner-loaded 9B in LM Studio :1234 idle for 15 min (`idle_unload_seconds = 900`) → instance unloaded (native TTL when supported, else ANZU unload); VRAM freed in the Windows soak.
- [ ] Managed mode on, after that idle unload → next chat reloads the 9B via the LM Studio API / `lms load` with the same model key and context, and answers; HUD shows the existing loading state, no error banner.
- [ ] Managed mode on + 27B served after the RFC-0225 VRAM gate unloaded the 9B → after the 27B idles for `idle_unload_seconds` (or Ollama `/api/ps` shows it unloaded) → 9B reloaded, one owner line.
- [ ] Managed mode off, ANZU-loaded 9B (default install) unloaded by the RFC-0225 gate for the 27B → after the 27B idles → that 9B reloaded through `NINE_B_REWARM`, one owner line; the instance is back in `anzu_loads`.
- [ ] Managed mode off → Taco's owner-loaded 9B is untouched by the idle timer and by a 27B request (no unload call issued; asserted in tests).
- [ ] **(D2 re-review #1)** `tests/test_rfc0228_orchestrator_restore.py` (new, fake clock):
  - `test_fresh_install_orchestrator_default_is_fable_9b`: fresh-install settings (S1 pin) → `default_orchestrator_profile_name() == "fable_9b"`, `is_orchestrator_profile("fable_9b")`, `effective_answer_profile_name` with nothing loaded → `fable_9b`.
  - `test_kept_ornith_install_stays_ornith`: saved `bootstrap` → `bootstrap`; saved `ornith_9b` → `ornith_9b`; saved `fast` / `balanced` / `quality` (kept Abiray) → the same name each; LM Studio attach → the selected `remote_model`.
  - `test_profile_param_billions_from_catalogue`: every entry of `declared_profiles()` yields a size (no `None` for a shipped profile), with `expert` → 27, `ornith_35b` → 35 (not 3), `front_2b` → 2 and every Qwen3.5-9B / Ornith-9B entry → 9. A new catalogue entry without a parseable size fails the test, so the derivation cannot silently drift.
  - `test_non_nine_b_saved_profile_never_restores`: saved `expert` (and `ornith_35b`) → `default_orchestrator_profile_name() is None`; a heavy turn's restore fires → no `MANAGER.load`, no owner line, loaded model kept.
  - `test_unknown_saved_profile_never_restores`: saved `"does_not_exist"` → `None`; restore → no load, one log line per process, no owner line; `resolve_profile`'s bootstrap fallback is never used for the target.
  - `test_restore_after_heavy_turn_returns_to_saved_9b`: `expert` loaded, `schedule_orchestrator_restore` → after 120 s exactly one reload of the saved 9B through `prepare_engine_for` (never `ornith_9b` on a Fable install).
  - `test_restore_concurrent_with_s2_reload_loads_once`: the restore fires while a chat request is reloading the same 9B → exactly one load call (single-flight + coordinator lock), both callers see the loaded 9B.
  - `test_restore_never_reloads_idle_unloaded_9b`: the idle timer unloaded the 9B → a pending restore is cancelled; a restore firing afterwards is a no-op; the next request reloads.
  - `test_restore_never_loads_9b_while_27b_resident`: default install (managed off). The coding request makes the RFC-0225 gate `MANAGER.unload()` the ANZU-loaded Fable 9B and load `anzu-coder-27b` in Ollama (`engine_coexistence.gate_unloaded()` set). The `agent/loop.py` restore is scheduled, the fake clock passes 120 s and 600 s with `/api/ps` still listing the 27B → **no** 9B load call, no owner line. `/api/ps` then drops the 27B → exactly **one** 9B reload through `prepare_engine_for` and exactly one owner line "Reloaded the 9B.", and the marker is cleared.
  - `test_restore_skips_when_free_vram_short`: no gate marker, but free VRAM (faked) < 9B requirement + 1 GB because another resident model fills the GPU → restore fires → no load; the next chat request goes through `prepare_engine_for`.
  - `test_coding_request_while_waiting_keeps_27b`: during the wait a second coding request hits the resident 27B → no 9B reload, no 27B unload, wait continues.
  - `test_restore_missing_weights_is_owner_visible`: target GGUF missing → no `MANAGER.load` of another profile, loaded model kept, one owner line; reload error → surfaced, not swallowed.
- [ ] Failed unload or reload (LM Studio/Ollama error, timeout) → surfaced to the owner with the error; state is not reported as unloaded/loaded.
- [ ] `idle_unload_seconds = 0` → never unloads.
- [ ] **(D2 #7)** `ensure_ollama_gpu` sends `keep_alive: "900s"` with the default, `"-1"` with 0; the Umi brain warm (`ensure_local_ollama` for `UMI_OLLAMA_MODEL`) sends the same value; no request contains `"24h"`.
- [ ] **(D2 #9)** Cancelled reload (`CancelledError` mid-load) → `loading` false, `last_error` set, status cache invalidated; reload never reuses a different host/port/model (`_same_endpoint`); saving `idle_unload_seconds` concurrently with a profile change keeps both (merge-safe save); failed activation does not persist settings.
- [ ] **(D2 #6)** "Unload when idle" control: renders the five options, shows the saved value, writes `idle_unload_seconds` (JS test); every existing Models-pane control still present; the JS test runs in `pr-tests.yml`.

### S3 — Installer Update option, installed/greyed tasks, "can be updated to"

**Model:** Grok 4.6 (fast off) · **Lane:** D2 · **Depends:** S1 (sequential owner of `Jarvis.iss`), RFC-0227 S3 (`model-selector.json` fixtures and re-bind)

| Path | Why |
| --- | --- |
| `installer/windows/Jarvis.iss` | Update entry + default selection rule (keeps `ExistingActionIsClean` pointing at Clean after the new entry shifts the list); read detection JSON; disable/label tasks; `/UPDATE` and `/UPGRADEMODELS` silent flags; `Default9BSuccessorOptedIn` added to `ShouldCopyDefault9BPayload` (successor task ticked or `/UPGRADEMODELS=fable_9b`); pass `-Update` / `-UpgradeModels` to bootstrap (second owner after S1) |
| `installer/windows/model-catalog.json` (new) | Components, markers, versions, resource profiles, `superseded_by`, pinned commit + SHA256 |
| `installer/windows/installed-components.ps1` (new) | Detect installed + outdated + eligible successor; JSON out |
| `installer/windows/run-installer-bootstrap.ps1` | Forward `-Update` / successor ids |
| `installer/windows/bootstrap.ps1` | New `-Update` and `-UpgradeModels <ids>` parameters: Update refreshes installed components only; the Fable successor is downloaded only when `-UpgradeModels` names `fable_9b` (second owner after S1) |
| `tests/fixtures/rfc0228_taco/` (new) | Fixtures above |
| `tests/test_rfc0228_installer_update.py` (new) | Below (extends patterns in `tests/test_installer.py`, `tests/test_rfc0124_installer_contract.py`) |

- [ ] Same-version installer → Update is default; newer installer → Upgrade default; Repair/Reinstall/Semi-clean/Clean present with unchanged text.
- [ ] Installed up-to-date component → task checked + disabled + "(installed)"; not re-downloaded.
- [ ] Installed Abiray 9B and installed Ornith 9B → `dl_localllm` / bootstrap rows labelled "(can be updated to > Qwen3.5 9B Defiant-Fable Q4)", **unchecked**; successor outside ±25 % profile → no label.
- [ ] **(D2 re-review #2)** `tests/test_rfc0228_installer_update.py::test_successor_unticked_no_fable_copy` / `::test_successor_ticked_copies_fable` (static ISS + bootstrap PowerShell): with the successor task unticked and no `/UPGRADEMODELS`, `ShouldCopyDefault9BPayload` has no true branch for an existing Ornith/Abiray install and `bootstrap.ps1 -Update` downloads nothing (no Fable file in the fixture tree's `models\`); ticked (or `/UPGRADEMODELS=fable_9b`) → `Default9BSuccessorOptedIn` true, the payload line copies and bootstrap verifies the SHA256. Windows soak: Update of Taco's Ornith install unticked → no ~6 GB copy; ticked → copied.
- [ ] **(D2 #1)** Update with the successor unticked → no download, `settings.json` and `model-selector.json` byte-identical (Taco fixtures `settings_lmstudio_9b.json` + RFC-0227 `model_selector_with_27b.json`, incl. the `anzu-coder-27b` slot); ticked → successor downloaded, verified, profile switched only then, old files/profile kept, `fable_9b_rebind.json` slot re-binds by fingerprint.
- [ ] Update keeps every custom file (RFC-0124 contract test).
- [ ] `/VERYSILENT /UPDATE` performs the same refresh without successors; `/UPGRADEMODELS=fable_9b` opts in; Inno compile passes in CI.

---

## Overall acceptance

- [ ] Fresh install on a 12 GB GPU: one 9B on disk (Fable Q4_K_S), selected and answering; 15 min idle → unloaded; next chat reloads.
- [ ] Taco's PC: Update run → app refreshed, installed items greyed, Ornith/Abiray labelled with the successor and unticked, LM Studio 9B selection, slots (incl. `anzu-coder-27b`) and LM Studio/Ollama untouched.
- [ ] RFC-0124 / installer suites green; Inno compile, frontend build and the S2 JS test in CI.

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0228-S1 | Fable 9B default: gate, single default 9B, profile pinning | Grok 4.5 | D1 | — |
| 0228-S2 | Idle unload, reload, Ollama keep-alive, ported selection safety | Grok 4.6 | D1 | S1, 0225-S3, 0225-S4, 0227-S1 |
| 0228-S3 | Installer Update + installed/greyed + "can be updated to" | Grok 4.6 | D2 | S1, 0227-S3 |

## Likely files

See ownership tables. Sequential chains: `config.py` 0228-S1 → 0228-S2; `Jarvis.iss` 0228-S1 → 0228-S3; `bootstrap.ps1` 0228-S1 → 0228-S3; `lmstudio_server.py` 0225-S3 → 0228-S2; `manager.py` 0225-S3 → 0228-S2 (two owners); `hotswap.py` 0225-S3 → 0228-S2 (two owners); `api/model.py` 0225-S1 → 0225-S3 → 0227-S1 → 0228-S2. `lmstudio_context.py`, `gpu_prefer.py`, `profile_roles.py`, `model_escalation.py` and the new `rewarm.py` are edited only by 0228-S2. Managed-mode state is owned by RFC-0225 S3 (`engine_coexistence.py`); 0228-S2 only reads it and calls its hooks.

`frontend/package.json` and `.github/workflows/pr-tests.yml` are shared by every frontend ticket in the 2026-10-17 batch: each ticket adds exactly one `test:*` script line and one `frontend-build` step (append-only hunks, trivial rebase) and touches nothing else in those files.

## Out of scope

- Persona/presence/WebGL/appearance (Astra).
- Auto-update channel / background updater service (this is the installer's Update choice).
- Changing the 27B coder or its Ollama model configuration.
- Stopping foreign engines and the VRAM gate itself (RFC-0225).

## Risks

- **HF repo churn** (80+ commits, last updated 2026-10-17) → pin by commit SHA + file SHA256 in `model-catalog.json`.
- **Uncensored default** → consistent with the existing abliterated default and owner decision; policy gates (RFC-0002/0031) unchanged.
- **Fable loses the benchmark** → no default change (gate); S1 reports to the Architect.
- **Reload latency after idle** → visible loading state; owner can set "Never".
- **Driving owner-loaded LM Studio instances** → only with managed mode on (explicit, remembered, revocable consent); reload reuses the owner's recorded model key and context so his setup is restored as it was.
