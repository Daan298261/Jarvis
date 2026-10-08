# RFC-0205: DeepHat Red 7B auto-start

**Status:** accepted  
**Queue item:** (none — CoS spec; Architect may add a §58 line after merge. Do not tick a ledger in this PR.)  
**Author:** Chief of Staff (Taco-authorized spec exception, parallel to the Architect)  
**Date:** 2026-10-08

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) — ANZU chooses infrastructure; the owner does not babysit a llama-server; a failed optional model leaves the assistant usable and honest.  
**Grounded in:** `development` at `222ac17`.  
**Numbering:** **0204** is [RFC-0204](0204-android-anzu-standalone-upgrade.md) (Android ANZU standalone upgrade) on `development`. This document is **0205**.  
**Extends (does not rewrite):** [RFC-0048](0048-specialist-model-stack-routing.md) specialist catalog and red-team gate. The “no model is automatically downloaded” clause in RFC-0048 is superseded **for DeepHat Red 7B only**, and only after explicit consent in this RFC.

Product name on screen: **DeepHat Red 7B**. Internal ids stay `deephat-red`, `deephat-7b`, and `recommended-deephat-7b`.

## Problem

Selecting DeepHat Red 7B does not start a model. The catalog entry is a disabled OpenAI-compatible template aimed at `http://127.0.0.1:8094/v1` (`backend/app/inference/model_stack.py`, key `deephat-red`). Nothing in the tree downloads its GGUF or spawns `llama-server` for that port.

What the code does today:

1. **Probe, then give up.** `POST /api/runtime-profiles/{id}/activate` calls `activate_runtime_profile` (`backend/app/inference/hotswap.py`). DeepHat’s provider is `openai-compat`, so `apply_runtime_profile_to_settings` only probes `127.0.0.1:8094`. An empty port raises `RuntimeError` and the API returns **503**. Settings are not saved, which is correct, and the server is never started, which is the bug.
2. **Wrong weights if a probe ever succeeded.** `deephat-7b` is not in `PROFILES`. `model_profile` on the template is null. `resolve_profile` (`backend/app/inference/profiles.py`) maps unknown names to `bootstrap` or `balanced`. `MANAGER.load` would attach the worker profile, not DeepHat.
3. **One process owner.** `LlamaCppBackend.start` stops its own previous process. The worker server (default `127.0.0.1:8088`) and the front-lane server (`FrontRuntime`, default port **8089**, log `llama-front.log`) are separate `LlamaCppBackend` instances. DeepHat has no third instance. Reusing `MANAGER` would either refuse to spawn (`RemoteOpenAICompatibleBackend.manages_process` is false) or kill the worker.
4. **Switch calls return 405.** FastAPI returns 405 when the path matches a route whose methods do not include the request method.
   - `POST /api/runtime-profiles/route-role` has no handler. `POST /api/runtime-profiles/route-role/preview` is the only role route (`backend/app/api/runtime_profiles.py`). The POST hits `/{profile_id}` (GET, PUT, DELETE) with `profile_id="route-role"` and returns **405**. Preview does not start a server.
   - `POST /api/runtime-profiles/deephat-7b` and `POST /api/runtime-profiles/recommended-deephat-7b` (and `deephat-red` if used as an id) hit `/{profile_id}` and return **405**. The HUD and Runtimes page call `POST .../activate` instead (`frontend/src/hud/applyRuntimeProfile.ts`, `frontend/src/pages/RuntimeProfiles.tsx`), which is the 503 path above.
   - `GET /api/runtime-profiles/{id}/activate` returns **405** (POST only).
   - When `frontend/dist` exists, `backend/app/main.py` registers `@app.get("/{full_path:path}")` after the API routers. A POST to an unregistered path such as `/api/runtime-profiles/deephat-7b/switch` or `/api/model/deephat/switch` matches that GET catch-all and returns **405** instead of a JSON 404.
5. **Download is a stub.** Setup interview lists `red_deephat` as `downloadable: false` with an empty repo (`backend/app/setup_interview.py`). The base id `DeepHat/DeepHat-V1-7B` is not a GGUF. `llama-server` cannot load it. Existing download progress lives in `runtime_install.ComponentState` (`bytes_done`, `bytes_total`, `status`) and `_hf_download`, which already calls `require_http_url_allowed`. DeepHat is not a component.

The owner sees a model name that does nothing useful. That fails the north star: ANZU should either run the chosen local model or say, in plain language, why it is still on the previous one.

## Decision

One supervisor owns DeepHat Red 7B end to end: consent, download, a private `llama-server` on `127.0.0.1:8094`, health, routing, reuse, and shutdown. Selection either reaches **ready** or a named failure with the previous model still serving. No stub that returns success without a health probe. No soft-fail that saves port 8094 and hopes.

Red-team **tool** authority is unchanged. Starting this model does not grant exploits, payloads, or HexStrike actions. License and case checks below gate the switch itself so an unlicensed click cannot download or bind 8094.

### 1. Weights

| Item | Value |
| --- | --- |
| Catalog identity | `DeepHat/DeepHat-V1-7B` (unchanged `model_id`) |
| Download repo | `mradermacher/DeepHat-V1-7B-GGUF` |
| File | `DeepHat-V1-7B.Q4_K_M.gguf` (~4.68 GB) |
| Install path | `{models_dir}/DeepHat-V1-7B-GGUF/DeepHat-V1-7B.Q4_K_M.gguf` |
| Alias passed to llama-server | `deephat-7b` |
| Context | 32768 (`context_limit` already on the template) |
| Bind | `127.0.0.1:8094` only. Never `0.0.0.0`. |
| OpenAI base | `http://127.0.0.1:8094/v1` |
| Log | `{logs_dir}/llama-deephat.log` |

Download uses the existing Hugging Face path (`huggingface_hub` plus `require_http_url_allowed` on `https://huggingface.co/mradermacher/DeepHat-V1-7B-GGUF/resolve/main/DeepHat-V1-7B.Q4_K_M.gguf`). A file already present and larger than 3 GiB is **ready**; do not download again. A shorter file is incomplete: delete it and treat weights as missing. Record sha256 in the progress detail the way `_hf_download` does. Do not invent a pinned digest in this RFC. A verified digest may be added only after the file is hashed on a machine that actually downloaded it.

Owner-facing label on the runtime template becomes **DeepHat Red 7B**.

### 2. Consent and progress

Missing weights never start a download by themselves.

`consent_download: true` on the switch POST is the only consent. The portal shows one sheet before that POST:

- Name: DeepHat Red 7B
- Size: about 4.7 GB, stored on this PC
- What happens if they decline: ANZU keeps the current model
- Actions: **Download and start** and **Not now**

If the file is already valid, skip the download sentence and do not send `consent_download`.

Progress is the same shape as `ComponentState`: `pending`, `downloading`, `verifying`, `ready`, `error`, with `bytes_done` and `bytes_total`. The portal polls `GET` status at least every second while `state` is `downloading`, `verifying`, or `starting`, and shows a determinate bar when `bytes_total > 0`, otherwise an indeterminate bar and the phase sentence. No second progress framework.

### 3. Server lifecycle

New owner: `backend/app/inference/deephat_runtime.py`, module-level `DEEPHAT_RUNTIME`, modeled on `FrontRuntime` (`backend/app/inference/front_runtime.py`) and `LlamaCppBackend` (`backend/app/inference/backends.py`).

- **Start.** Own `LlamaCppBackend` instance. Command uses the existing `build_args` shape: `--host 127.0.0.1 --port 8094 --alias deephat-7b --ctx-size 32768 --jinja`, plus the on-disk GGUF. GPU layers follow the worker fit helper when free VRAM remains after the **running** worker (8088) and front server (8089). If the fit fails, start on CPU (`--n-gpu-layers 0`) only when available RAM can hold the file plus the existing headroom used by the front lane. If neither fits, do not spawn. Do not unload the worker or the front model in this RFC.
- **Health.** After spawn, `wait_for_health` on `http://127.0.0.1:8094/health` (same helper as the worker). Then `probe_remote_server` must report `ok` and an advertised model equal to `deephat-7b` or containing `DeepHat`. Routing is forbidden until both succeed.
- **Reuse.** If that probe already matches, do not spawn. State is `ready` with `method: "reused"`.
- **Foreign port.** If 8094 answers but the model does not match, or the port accepts a connection and never becomes the DeepHat alias, do not kill the process. State `port_occupied`.
- **Shutdown.** `stop()` terminates only a pid this supervisor spawned (terminate, wait 8s, then kill — same as `LlamaCppBackend.stop`). Call it from `main.py` shutdown next to `FRONT_RUNTIME.stop()`, and when the owner switches to another runtime. A reused server this process did not spawn stays up; Jarvis only stops routing to it.
- **Settings.** `save_settings` runs only after health matches. Host `127.0.0.1`, port `8094`, `remote_model` `deephat-7b`, backend `openai-compat` so `MANAGER` attaches with `RemoteOpenAICompatibleBackend` and does not spawn an 8088 replacement. On every failure, leave inference settings on the previous model.

`resolve_profile("deephat-7b")` must resolve to this GGUF profile (or `MANAGER.load` must receive `gguf_path` and must not fall through to bootstrap). A successful switch that serves bootstrap weights is a failed switch.

### 4. Endpoint contract

Canonical pair, registered on the runtime-profiles router **before** `/{profile_id}`:

| Method | Path | Role |
| --- | --- | --- |
| `POST` | `/api/runtime-profiles/deephat/switch` | Run the switch |
| `GET` | `/api/runtime-profiles/deephat/switch` | Status snapshot for the progress bar |

`POST` body:

```json
{
  "consent_download": false,
  "authorization_case": "",
  "human_confirmed": false
}
```

`consent_download` is required only when weights are missing. `authorization_case` (non-empty after trim) and `human_confirmed: true` are required on every POST, matching `POST /api/runtime-profiles/route-role/preview` for `red-team`.

**Preconditions**, in order, before any download or spawn:

1. Installed license allows `red-team` (`gate_is_enabled("red-team")`). Else **403** `license_package_denied`. Same reason text the preview route already returns.
2. Case reference and `human_confirmed`. Else **403** `red_authorization_required`.
3. Weights missing and `consent_download` is not true. **200** `needs_consent`. No network call.
4. Otherwise download if needed, then start or reuse, then health-check.

**Response body** (GET and POST share it):

```json
{
  "state": "ready",
  "code": "ready",
  "method": "started",
  "message": "DeepHat Red 7B is ready.",
  "endpoint": "http://127.0.0.1:8094/v1",
  "healthy": true,
  "bytes_done": 0,
  "bytes_total": 0,
  "previous_model": "Qwen3.5-9B"
}
```

`method` is `started`, `reused`, or `""` when nothing was spawned. `previous_model` is the owner-visible label of the model that was serving before this call, so fallback copy can name it.

| `state` | HTTP | `code` | Owner-facing `message` |
| --- | --- | --- | --- |
| `needs_consent` | 200 | `needs_consent` | DeepHat Red 7B is not on this PC yet. Download about 4.7 GB to use it. ANZU is still using {previous}. |
| `declined` | 200 | `declined` | DeepHat was not downloaded. ANZU is still using {previous}. |
| `downloading` | 200 | `downloading` | Downloading DeepHat Red 7B… |
| `verifying` | 200 | `verifying` | Checking the DeepHat download… |
| `starting` | 200 | `starting` | Starting DeepHat Red 7B… |
| `ready` | 200 | `ready` | DeepHat Red 7B is ready. |
| `download_failed` | 502 | `download_failed` | DeepHat could not be downloaded. ANZU is still using {previous}. |
| `start_failed` | 502 | `start_failed` | DeepHat did not start. ANZU is still using {previous}. |
| `health_failed` | 502 | `health_failed` | DeepHat did not become ready. ANZU stopped it and is still using {previous}. |
| `port_occupied` | 409 | `port_occupied` | Something else is using port 8094. ANZU left it alone and is still using {previous}. |
| `unfit` | 409 | `unfit` | This PC does not have enough free memory to start DeepHat beside the current model. ANZU is still using {previous}. |

`declined` is `POST` with weights missing and `consent_download: false` after the client has already been told `needs_consent` and the user chose **Not now**. The portal sends that POST so the snapshot is explicit. A first POST with `consent_download: false` may return `needs_consent` **or** `declined`; both leave settings untouched and download nothing. The portal treats both as “stay on the previous model” and shows `message`.

Failure responses include `detail` with a short operator reason (exception class, log path `llama-deephat.log`). The portal shows `message`, not `detail` and not a stack trace.

Machine `code` values above are stable. Do not overload HTTP 405 for these outcomes.

**Aliases that must stop returning 405** and call the same supervisor (same body fields; missing JSON fields default as in the table):

| Call today | Result today | Required result |
| --- | --- | --- |
| `POST /api/runtime-profiles/route-role` with `role` in `red`, `red-team`, `deephat-red`, `deephat-7b` | 405 | Same as canonical POST. Other roles on this new route return **400** `unknown_role` as JSON, not 405. |
| `POST /api/runtime-profiles/deephat-7b`, `.../recommended-deephat-7b`, `.../deephat-red` | 405 | Same as canonical POST. |
| `POST /api/runtime-profiles/{those ids}/activate` | 503 probe failure, or a worker hotswap | Same as canonical POST. Body may be empty; empty case fields still **403** `red_authorization_required`. |
| `POST /api/runtime-profiles/deephat-7b/switch` and `POST /api/model/deephat/switch` | 405 via the SPA GET catch-all when `frontend/dist` exists; 404 otherwise | Same as canonical POST. |

`POST /api/runtime-profiles/route-role/preview` stays a preview. It must not download or spawn.

`GET /api/runtime-profiles/{id}/activate` stays a non-operation. Response **405** with `Allow: POST` and a JSON body `{"detail":"Use POST /api/runtime-profiles/deephat/switch"}`. The portal must not GET it.

Unmatched methods under `/api/` must not hit the SPA catch-all. Register an API fallback **after** the real routers and **before** `@app.get("/{full_path:path}")` that returns JSON **404** `{"detail":"Not found"}` for any method on `/api/{path}`. Non-API GET behavior for the built portal stays as it is.

### 5. State transitions

```
idle
  → needs_consent          weights missing, consent not granted
  → declined               user chose Not now (settings unchanged)
  → downloading            consent granted, transfer started
downloading
  → verifying
  → download_failed        settings unchanged, partial file removed
verifying
  → starting               file accepted
  → download_failed
starting
  → ready                  health matched; then save settings and route
  → start_failed           owned pid stopped; settings unchanged
  → health_failed          owned pid stopped; settings unchanged
  → unfit                  nothing spawned; settings unchanged
  → port_occupied          nothing killed; settings unchanged
ready
  → ready                  second select while health matches (reuse)
  → idle                   owner selects another runtime, or process shutdown stops an owned pid
```

A transition that is not in this list is a bug. `ready` is the only state in which chat traffic may use port 8094.

### 6. Portal

Surfaces that already select a runtime (`applyRuntimeProfile`, Runtimes “lock / switch”, HUD slot Play) detect DeepHat ids (`deephat-7b`, `recommended-deephat-7b`, `deephat-red`, label containing DeepHat) and call the canonical POST instead of a bare activate.

The sheet collects the case reference and the confirmation checkbox together with download consent when a download is required. One sheet, plain language, no llama-server wording. While work is in progress the control that started it shows the phase sentence and the bar, and it is disabled until a terminal state. Terminal states `ready`, `declined`, `download_failed`, `start_failed`, `health_failed`, `port_occupied`, `unfit`, and the 403s all render `message` in the existing runtime error/status slot. After a failure the selected runtime id in the client stays on the previous profile.

Security model gates (`SecurityModelGates.tsx`) stay a license display. They do not grow a second switch button.

### 7. What this does not change

- Password gates stay retired (HTTP 410).
- Generic `enabled: true` on the DeepHat runtime profile still returns **403** `security_gate_managed`.
- Generic `/api/runtime-profiles/route` and `force_profile` still cannot select a disabled DeepHat template. The switch path is the only writer that routes traffic to 8094.
- Red, Blue, and HexStrike tool exposure is unchanged.
- Worker port 8088 and front port 8089 are not reused for DeepHat.

## Acceptance criteria

Tied to the north star: the owner picks DeepHat Red 7B and ANZU either serves it from this PC or explains the failure and keeps the previous model. No stubbed success.

- [ ] Missing GGUF and `consent_download: false` performs no HTTP download and does not spawn. Response is `needs_consent` or `declined` with the previous model still active.
- [ ] `consent_download: true` downloads `DeepHat-V1-7B.Q4_K_M.gguf` from `mradermacher/DeepHat-V1-7B-GGUF` through `require_http_url_allowed`, reports `bytes_done` / `bytes_total`, and will not mark the file ready under 3 GiB.
- [ ] A second select with a valid file does not download again.
- [ ] After a successful download or a pre-existing file, Jarvis starts `llama-server` bound to `127.0.0.1:8094` with alias `deephat-7b`, or reuses an already-healthy matching server.
- [ ] Chat routing to 8094 happens only after `/health` and a matching advertised model. `save_settings` is not called before that.
- [ ] Download error, spawn error, health timeout, unfit memory, and a foreign listener on 8094 each return the HTTP status and `message` in §4, stop any pid this supervisor spawned, kill nothing it did not spawn, and leave inference settings on the previous model.
- [ ] Declining the sheet does the same leave-in-place behavior.
- [ ] License without `red-team`, or a POST missing case / `human_confirmed`, returns **403** with the existing codes and does not download or listen.
- [ ] `POST /api/runtime-profiles/route-role` (red role), `POST /api/runtime-profiles/deephat-7b`, `POST .../recommended-deephat-7b`, `POST .../deephat-red`, `POST .../{id}/activate` for those ids, `POST .../deephat-7b/switch`, and `POST /api/model/deephat/switch` do not return **405**. They hit this supervisor.
- [ ] Unmatched `POST /api/...` returns JSON **404**, including when `frontend/dist` exists.
- [ ] Process shutdown and switching to another runtime stop only an owned DeepHat pid. Worker 8088 and front 8089 stay up.
- [ ] `resolve_profile("deephat-7b")` or the load path used by the switch does not silently serve bootstrap/balanced weights.
- [ ] Portal sheet: consent, case, confirm, progress bar, and the `message` strings. No “405”, “llama-server”, or stack trace in the owner UI.
- [ ] Unit tests in `tests/test_rfc0205_deephat_autostart.py` cover the rows above with a fake downloader and a fake process/probe. `python3 -m pytest` passes.
- [ ] `npm --prefix frontend run build` and `npm --prefix frontend run lint` pass.
- [ ] Desktop sign-off (not this cloud VM): real GGUF, `llama-server` healthy on 8094, one owner turn answered by DeepHat, then switch back and confirm 8094’s owned process is gone. Live load stays **unverified** until that pass.

## Implementable slices

One developer, in this order. Later slices call the earlier module; they do not grow a second supervisor.

| Order | Slice | Files |
| --- | --- | --- |
| 1 | Supervisor: start, health, reuse, foreign port, unfit, stop owned pid only | `backend/app/inference/deephat_runtime.py` (new), `backend/app/main.py` shutdown hook, `tests/test_rfc0205_deephat_autostart.py` |
| 2 | Profile + GGUF path so `deephat-7b` cannot fall through to bootstrap. Template label **DeepHat Red 7B**. Quant `Q4_K_M`. | `backend/app/inference/profiles.py`, `backend/app/inference/model_stack.py` |
| 3 | Consented download and progress, using `_hf_download` / `ComponentState` or a thin wrapper that updates the same fields | `backend/app/runtime_install.py` or `deephat_runtime.py`, `backend/app/policy/network_http.py` (call site only) |
| 4 | Canonical GET/POST plus the 405 aliases; API `/api/*` fallback returns JSON 404 | `backend/app/api/runtime_profiles.py`, `backend/app/api/model.py` (alias only if the model router owns `/api/model/deephat/switch`), `backend/app/main.py` |
| 5 | Activate / hotswap for DeepHat ids delegates to the supervisor and attaches `MANAGER` only after health | `backend/app/inference/hotswap.py` |
| 6 | Portal sheet, progress poll, fallback copy, previous-profile restore | `frontend/src/hud/applyRuntimeProfile.ts`, `frontend/src/pages/RuntimeProfiles.tsx`, `frontend/src/api.ts`, one small component next to those call sites |

Slice 4 depends on 1 and 3. Slice 5 depends on 1 and 2. Slice 6 depends on 4. Do not split the portal to a second developer; the copy and the status enum are one contract.

## Out of scope

- Auto-start for RedSage (`8092`) or Imperum (`8093`). Same shape, separate RFC.
- Unloading the worker to free VRAM for DeepHat.
- Editing `JARVIS_MASTER_PLAN.md` or other Architect spec docs.
- Red-team tools, payloads, exploit generation, or HexStrike policy.
- Reviving password unlock (HTTP 410 stays).
- Letting generic `force_profile` select DeepHat while the template is disabled.
- A cloud or remote DeepHat host. This RFC is loopback only.

## Risks and open questions

- **Memory.** A 7B Q4 beside a 27B worker and the front server may not fit. This RFC refuses (`unfit`) instead of killing the worker. Parking the worker first is a later product choice.
- **Chat template.** Some DeepHat GGUFs need a llama.cpp that accepts the Jinja `tojson` filter. Health failure must surface `health_failed` and `llama-deephat.log` in `detail`. Do not claim the switch worked because the process pid exists.
- **Foreign 8094.** Reuse is allowed only when the advertised model matches. Anything else is `port_occupied`. Do not adopt RFC-0136’s install-tree killer for this port.
- **Digest.** No sha256 is pinned here. Truncation is caught by the 3 GiB floor. A bad-but-large file is a residual risk until a desktop-verified digest lands.
- **License friction.** Case reference plus confirmation is an existing red-team rule (`route-role/preview`, RFC-0048). It is one sheet with the download question, not a silent start. Removing it would let an unlicensed click pull a gated model.
- **SPA 405.** The JSON 404 fallback must be registered after real `/api` routes so it does not shadow them, and before the GET `/{full_path:path}` handler.
- **Cloud VM.** No GPU and no Windows `llama-server.exe`. Unit tests mock spawn and probe. Live tok/s is desktop sign-off.
- **Setup interview.** `red_deephat` stays unselected and is not downloaded by interview apply. The picker in §6 is the selection surface. Wiring interview as another caller is optional and must use the same POST.

## Notes

- Front-lane pattern to copy: `FrontRuntime.ensure_started`, `LlamaCppBackend.start` / `stop`, `probe_remote_server`, `wait_for_health`.
- Download pattern to copy: `runtime_install._hf_download` and `ComponentState`.
- Red gate pattern to copy: `preview_role_route` in `backend/app/api/runtime_profiles.py` (403 codes). Do not copy its “preview only” behavior into the switch.
- Queue hint for the Architect: optional §58 line “DeepHat Red 7B auto-start (RFC-0205)” after this spec merges. No ledger tick in the implementation PR until desktop sign-off.
