# RFC-0228: Installer Update mode, 9B Defiant-Fable default with idle unload, installed/greyed options with "can be updated to"

**Status:** accepted  
**Priority:** P2 (Taco batch 2026-10-17, items 5, 6, 7)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20

**Owner ask (verbatim intent, 2026-10-17):** "5. Add 'Update' as an installer option. 6. Make the default model the 9B uncensored, qwen3.5-9b-defiant-fable-uncensored, at Q3 or Q4 so it stays fast. 7. Grey out options that are already installed. When a newer model with a similar GPU, RAM and disk profile exists for an installed-but-outdated option, mark it '(can be updated to > modelname)'."  
**Owner context (shared memory):** Taco runs the 9B through LM Studio at `http://127.0.0.1:1234/v1`; `anzu-coder-27b` (Ollama, ~12 GB GPU) is for coding; the 9B should get an **idle unload timer** rather than being pinned forever, and ANZU respawns it on demand.  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §6 (fast when simple), §9 ("**ANZU chooses infrastructure.**"), §19 ("Do remove unnecessary complexity from the user's experience."; "Do not remove useful capability merely to simplify the codebase."), §20 Q1 ("Does it reduce the amount of technical knowledge required from the user?"), Q5, Q8, §21 ("can be installed and used with minimal configuration").  
**Extends (do not rewrite):** [RFC-0124 clean install / reinstall](0124-clean-install-reinstall-owned-path-wipe.md) (existing-install page and custom-file contract), [RFC-0093](0093-installer-force-stop-and-prepare-unstick.md) / [RFC-0136](0136-zombie-kill-setup-next-and-start.md) (stop before install), [RFC-0196](0196-native-anzu-manager.md) ("All installer choices except the 27B model are selected by default"), [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) (respawn on demand), `INSTALLER.md`.  
**Open implementation PRs that overlap (rebase gate):** #648 touches `installer/windows/Jarvis.iss`, `backend/app/inference/manager.py`, `lmstudio_server.py`; #649 touches `profiles.py`, `manager.py`, `runtime_install.py`. Slices owning those files start after #648/#649 are merged or closed.  
**Astra boundary:** Persona/presence/WebGL/appearance out of scope (Astra). Installer branding/theme (`ThemeExistingInstallPage`, `ThemeChecklist`) is reused unchanged.

This PR is **specs-only**. No application code.

---

## Problem

Verified in `development` @ `3f17c3d8`:

1. **No "Update".** `installer/windows/Jarvis.iss::InitializeWizard` shows the existing-install page with "Upgrade to ANZU X (recommended)" only when the installer is newer (`ExistingVersionRelation > 0`), otherwise "Repair"; plus Reinstall / Semi-clean / Clean. There is no option to bring **installed components** (models, voices) up to date without reinstalling, and a same-version installer cannot refresh outdated models.
2. **Default model is old and heavy.** `dl_localllm` → `bootstrap.ps1` downloads `Abiray/Qwen3.5-9B-abliterated-GGUF` **Q8_0 + Q6_K**; `config/default.json` uses profile `fast` (`Qwen3.5-9B-abliterated-Q6_K.gguf`, `backend/app/inference/profiles.py`). Taco wants the Defiant-Fable 9B at Q4/Q3 for speed. `lmstudio_graded_profiles.json` already matches `["Qwen3.5-9B", "Defiant", "Q4"]` as "Cheap coding 9B".
3. **Model pinned forever.** `InferenceSettings` has no idle unload; the managed llama-server and LM Studio instances stay resident, competing with `anzu-coder-27b` for VRAM.
4. **Installed options are indistinguishable.** The `[Tasks]` checklist (`dl_kokoro`, `dl_personavoices`, `dl_whisper`, `dl_voicestudio`, `dl_pockettts`, `dl_umi_brain`, `dl_localllm`, `dl_expert27b`, voice-pack tasks) is `checkedonce` regardless of what is already on disk, and there is no notion of a newer replacement.

**Verified external fact (2026-10-20, Hugging Face listing):** the GGUF repo is `DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF`; regular quants include `…-NEO-MAX-Q4_K_S.gguf` (≈6.10 GB), `…-Q4_K_M.gguf` (≈6.36 GB), `…-IQ4_XS.gguf` (≈5.96 GB), `…-IQ3_M.gguf` (≈5.23 GB); MTP variants exist. The LM Studio model key Taco uses (`qwen3.5-9b-defiant-fable-uncensored`) is taken from the owner's message and must be confirmed against `lms ls` on Taco's PC (S1).

## Decision

Ship **one RFC with three implement slices** (one named model each, **fast off**).

### Default model (normative)

- New profile `fable_9b` in `profiles.py` (existing `fast`, `balanced`, `bootstrap`, `expert` and Abiray entries are **kept**, not deleted): repo above, file **Q4_K_S regular** (not MTP — MTP needs temp ≤1 and has acceptance caveats), fallback **IQ3_M** when free VRAM < 7 GB or disk < 8 GB. SHA256 pinned from the HF API at implement time; download verified before the profile is selectable.
- `config/default.json` → `"profile": "fable_9b"` for **new** installs only. Existing installs keep their saved profile; Update offers the switch through rule 7 below.
- When LM Studio is installed and already serves the Defiant-Fable 9B (Taco's case), Setup/first-run prefers attaching to it (RFC-0210 "use") over downloading a duplicate copy; the owner sees which one was chosen.

### Idle unload + respawn (normative)

- `InferenceSettings.idle_unload_seconds` (default **900**, `0` = pinned; range 0–86400). Applies to the **worker** model only; the front lane (`front_responder.resident`) is unchanged.
- Managed llama-server: after `idle_unload_seconds` with no request lease held and no task running, `MANAGER.unload()`; next request transparently reloads (same profile/context), with the existing "Loading model…" HUD state and elapsed timer.
- LM Studio selected engine: pass a native TTL when the installed LM Studio supports it (`lms load --ttl` / REST `ttl`), else ANZU's own timer calls `/api/v1/models/unload` for the instance it loaded; on demand ANZU reloads through `lmstudio_context`/`ensure_local_lmstudio`. ANZU never unloads LM Studio instances it did not load.
- Never unload during an active stream, tool loop or task stage; the timer resets on every lease.

### Installer Update + installed state (normative)

1. **"Update" option** on the existing-install page, inserted as a new first-class entry: "&Update ANZU — keep everything, refresh the app and bring installed models and voices up to date". Existing entries (Upgrade/Repair primary, Reinstall, Semi-clean, Clean) are **kept with their current text and behaviour**; when the installer is newer, Upgrade stays the default selection; when versions match, Update becomes the default selection (Repair stays available).
2. Update = Upgrade/Repair file copy + component refresh: for each installed component with a catalog successor (rule 4) the bootstrap downloads the successor, verifies it, and switches the profile only after verification; outdated files are kept until the new one verifies.
3. **Installed detection** from a shared manifest `installer/windows/model-catalog.json` (component id → files/markers, version, GPU/RAM/disk profile, `superseded_by`) evaluated by `installer/windows/installed-components.ps1` (also usable by the backend). Inno reads its JSON result.
4. **Greyed tasks:** already-installed, up-to-date components are shown checked + disabled with suffix "(installed)". Installed-but-outdated components with a successor whose VRAM, RAM and disk needs are each within **±25 %** (or lower) of the installed one are shown enabled and labelled `(can be updated to > <successor display name>)`; checking it downloads the successor.
5. Fresh installs: no greying; default selections as RFC-0196 (27B unchecked).
6. Silent mode (`/VERYSILENT`) supports `/UPDATE` with the same semantics.
7. The `dl_localllm` description changes to the Defiant-Fable 9B; existing Abiray 9B installs are "outdated" with successor `fable_9b` (similar profile) → labelled per rule 4.

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

Touched live UI: installer existing-install page and task checklist; HUD model state during reload.

| Current live behaviour | Preserved? | Added alongside |
| --- | --- | --- |
| Existing-install page: Upgrade (newer) / Repair (same) primary, Reinstall, Semi-clean, Clean, with current texts and confirmations | **Yes**, all kept, same order after the new entry | "Update" entry |
| `[Tasks]` checklist with Select-all (`CreateSelectAll`), theming, groups | **Yes** | Disabled+checked "(installed)" items; "(can be updated to > …)" labels |
| RFC-0124 custom-file contract (Upgrade/Repair keep custom files) | **Yes** — Update keeps custom files identically | — |
| 27B Expert unchecked by default | **Yes** | — |
| HUD "Loading model…" + elapsed during load | **Yes** (reused for on-demand reload) | — |
| Existing model profiles (`fast`, Abiray Q8/Q6, `expert`, …) selectable | **Yes**, none deleted | `fable_9b` |

### Stub rule

No stubs. A catalog entry with no SHA, an "Update" option that behaves exactly like Repair, or a timer setting that is never read, is a fail.

---

## Slices (one ticket each)

Assign order: **S1 → S2; S3 after S1.**

### S1 — Defiant-Fable 9B default profile + verified download

**Model:** Grok 4.5 (fast off) · **Lane:** D1 · **Depends:** #649 resolved (`profiles.py`)

| Path | Why |
| --- | --- |
| `backend/app/inference/profiles.py` | Add `fable_9b` (Q4_K_S) + IQ3_M fallback; keep all existing profiles |
| `backend/app/inference/lmstudio_graded_profiles.json` | Bind the existing Defiant Q4 graded row to `fable_9b` |
| `backend/app/inference/default_candidates.py` | Defiant-Fable 9B as the default worker candidate for fresh installs |
| `config/default.json` | `"profile": "fable_9b"` |
| `installer/windows/bootstrap.ps1` | `-InstallLocalLLM` downloads Q4_K_S (IQ3_M by VRAM/disk), SHA256-verified, resumable |
| `INSTALLER.md` | Update the Models line |
| `tests/test_rfc0228_default_model.py` (new) | Below |

- [ ] Fresh install config resolves profile `fable_9b` to the Q4_K_S file; low VRAM/disk fixture resolves IQ3_M.
- [ ] Download is SHA256-verified; a corrupted file is rejected and retried, never registered.
- [ ] Existing install with profile `fast` keeps `fast` after upgrade.
- [ ] LM Studio already serving the Defiant 9B → first-run attaches instead of downloading (fixture), owner told which.
- [ ] LM Studio model key confirmed on Taco's PC and recorded in the PR.

### S2 — Worker idle unload + on-demand respawn

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S1, RFC-0225 S3 (sequential owner of `lmstudio_server.py`), #648/#649 resolved

| Path | Why |
| --- | --- |
| `backend/app/config.py` | `InferenceSettings.idle_unload_seconds` (only this hunk) |
| `backend/app/inference/manager.py` | Idle timer bound to request lease/task activity; unload; transparent reload on next request |
| `backend/app/inference/lmstudio_server.py` | Native TTL capability detection; reload path |
| `backend/app/inference/lmstudio_context.py` | Pass TTL on load / unload only ANZU-loaded instances |
| `frontend/src/settings/ModelsSettingsPane.tsx` | "Unload when idle" control (Never / 5 / 15 / 30 / 60 min), existing controls untouched |
| `tests/test_rfc0228_idle_unload.py` (new) | Below |

- [ ] No requests for `idle_unload_seconds` → worker unloaded (VRAM freed in Windows soak); front lane untouched.
- [ ] Next request reloads and answers; HUD shows the existing loading state; no error banner.
- [ ] Timer never fires during a stream, tool loop or task stage (tests with held lease).
- [ ] LM Studio: ANZU unloads only the instance it loaded; an owner-loaded instance is never unloaded.
- [ ] `idle_unload_seconds = 0` → never unloads.

### S3 — Installer Update option, installed/greyed tasks, "can be updated to"

**Model:** Grok 4.6 (fast off) · **Lane:** D2 · **Depends:** S1, #648 resolved (`Jarvis.iss`)

| Path | Why |
| --- | --- |
| `installer/windows/Jarvis.iss` | Update entry + default selection rule; read detection JSON; disable/label tasks; `/UPDATE` silent flag; pass `-Update` to bootstrap |
| `installer/windows/model-catalog.json` (new) | Components, markers, versions, resource profiles, `superseded_by` |
| `installer/windows/installed-components.ps1` (new) | Detect installed + outdated + eligible successor; JSON out |
| `installer/windows/run-installer-bootstrap.ps1` | Forward `-Update` |
| `tests/test_rfc0228_installer_update.py` (new) | Below (extends patterns in `tests/test_installer.py`, `tests/test_rfc0124_installer_contract.py`) |

- [ ] Same-version installer → Update is default; newer installer → Upgrade default; Repair/Reinstall/Semi-clean/Clean present with unchanged text.
- [ ] Installed up-to-date component → task checked + disabled + "(installed)"; not re-downloaded.
- [ ] Installed Abiray 9B → `dl_localllm` labelled "(can be updated to > Qwen3.5 9B Defiant-Fable Q4)"; successor outside ±25 % profile → no label.
- [ ] Update keeps every custom file (RFC-0124 contract test) and switches profile only after the successor verifies.
- [ ] `/VERYSILENT /UPDATE` performs the same refresh; Inno compile passes in CI.

---

## Overall acceptance

- [ ] Fresh install on a 12 GB GPU: Defiant-Fable Q4_K_S selected and answering; 15 min idle → unloaded; next chat reloads.
- [ ] Taco's PC: Update run → app refreshed, installed items greyed, Abiray 9B labelled with the successor, LM Studio/Ollama untouched.
- [ ] RFC-0124 / installer suites green; Inno compile and frontend build in CI.

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0228-S1 | Defiant-Fable 9B default + verified download | Grok 4.5 | D1 | #649 |
| 0228-S2 | Worker idle unload + on-demand respawn | Grok 4.6 | D1 | S1, 0225-S3, #648/#649 |
| 0228-S3 | Installer Update + installed/greyed + "can be updated to" | Grok 4.6 | D2 | S1, #648 |

## Likely files

See ownership tables. `lmstudio_server.py` taken over from RFC-0225 S3 after it merges. `config.py`: only the `InferenceSettings.idle_unload_seconds` hunk is owned here.

## Out of scope

- Persona/presence/WebGL/appearance (Astra).
- Auto-update channel / background updater service (this is the installer's Update choice).
- Changing the 27B coder or Ollama configuration.
- Stopping foreign engines (RFC-0225).

## Risks

- **HF repo churn** (80+ commits, last updated 2026-10-17) → pin by commit SHA + file SHA256 in `model-catalog.json`.
- **Uncensored default** → consistent with the existing abliterated default and owner decision; policy gates (RFC-0002/0031) unchanged.
- **Reload latency after idle** → visible loading state; owner can set "Never".
