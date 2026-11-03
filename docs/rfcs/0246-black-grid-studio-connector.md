# RFC-0246: ANZU connector to Black Grid Multimedia Studio (one tool path, loopback only, GPU-aware)

**Status:** accepted (specs-only; **implementation is gated**, see *Gating*)
**Priority:** P2 (Taco's order with PG's approval, relayed by Chief of Staff 2026-11-03)
**Author:** Jarvis Architect
**Date:** 2026-11-03 (amended 2026-11-03: #686's keep-warm amendment is present and S3 follows its proposed names; amended again 2026-11-03 with PG's answers to all eight open questions, see *Resolved questions*)
**Traced on:** `development` @ `a62bd454` (every cited Jarvis symbol resolved there). Open PRs cited: #686 (RFC-0242; final head in this PR's body), #655 (RFC-0228; final head in this PR's body), #665 (RFC-0245; final head in this PR's body), #668 (RFC-0233; final head in this PR's body). Studio API read from Black Grid Multimedia (BGM) PRs #32, #33 and #34 (cited by endpoint path and symbol; final heads in this PR's body, as provenance only).

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md):
- §1: "Tell ANZU what you want. ANZU figures out how to accomplish it." The owner says "turn this book into a movie"; ANZU drives the studio instead of the owner learning its screens.
- §5 and §17: "A new specialist pack should extend ANZU. It should not fragment the experience into another application." The studio becomes a specialist capability reached through ANZU's one tool path (Aegir, media).
- §7: "ANZU should eliminate unnecessary approvals without eliminating meaningful control." Reads and small edits just happen; starting a long GPU render, regenerating, stitching, ingesting a book and deleting need the owner's real approval.
- §8: "Confidence should come from evidence rather than cheerful completion messages." A run is reported finished only from the studio's own run and readiness records.
- §9: "ANZU chooses infrastructure." ANZU frees the GPU for a render and takes it back afterwards; the owner never manages VRAM by hand.
- §16: "multimedia workers" are named in the Away Mode roadmap.

**Extends (do not rewrite):**
- [RFC-0096](0096-comfyui-sana-blackgrid-media-gen.md) / [RFC-0097](0097-opencut-openmontage-hyperframes-blackgrid-stitch.md): the BlackGrid media connector idea. The landed `blackgrid_studio` tool (ComfyUI / HR Endless sidecar) gains the studio actions defined here, and its seven legacy ComfyUI actions are retired only in S2's PR, with working replacements and a reviewer-confirmed no-live-caller check (PG ruling; never deleted first).
- [RFC-0031](0031-reversibility-first-action-gates.md) and [RFC-0110](0110-chatgpt-style-approval-popup.md): the action gate, `ApprovalGrant` and the approval popup. This RFC adds no confirmation mechanism of its own.
- [RFC-0244](0244-three-engine-modes.md): engine modes.
- #686 (RFC-0242; final head in this PR's body): its section "Amendment: Keep warm toggle and 5-minute idle unload" (present on #686) and its T3 verified native release (`inference/model_release.py`, **not yet landed**) and T6 explicit owner Load.
- D2's Taco-owned keep-warm ticket. The amendment proposes `keep_warm` (default `false`) and `idle_unload_seconds` (default `300`) on `InferenceSettings`, with Ollama `keep_alive` `"300s"` when off and `"-1"` when on, and says **D2's PR sets the final names, files and test paths**. No D2 PR is open yet; its number is added to this PR's body and to *Gating* when it opens, and any name difference is a one-line edit here.

**Astra boundary:** persona, WebGL, presence, morph and appearance are out of scope (Astra). This RFC edits no persona or presence component. The only UI is one additive status line (S4).

This PR is **specs-only**. It contains no application code.

---

## Gating (read first)

Nothing in S1-S5 starts until **all** of these hold:

1. BGM PRs #32, #33 and #34 are **merged to BGM `main`**. #33 and #34 are stacked (their bases are the previous slice's branch), so today the endpoints below exist only on those branches. BGM-P1 and BGM-P2 are BGM PRs from PG's workers **stacked after #34**, so they merge after it.
2. **BGM-P1** (`GET /api/gpu/status`) and **BGM-P2** (`GET /api/contract`) are merged to BGM `main` (see *Studio-side changes*). The GPU gate reads BGM-P1 and nothing else. **S5 is not blocked by any CI or token question** (no cross-repo CI, no BGM read token; Q5), but its first pinned fixture needs BGM-P2's first response, so it waits for P2 only.
3. #686's T3 (`inference/model_release.py`, not yet landed) and its section "Amendment: Keep warm toggle and 5-minute idle unload" are on `development`, and D2's keep-warm PR (which sets the final names of `keep_warm` and `idle_unload_seconds`) has landed. S3 calls T3's release and the keep-warm setting, and re-traces their final names at assignment.
4. PG tells Chief of Staff the contract is final, and Chief of Staff assigns the tickets.

At assignment each ticket's first step is the **contract re-trace**: re-read every endpoint in *Studio contract* on BGM `main` (or, once S5 lands, diff it against the pinned `tests/fixtures/bgm/contract.json`), resolve each *contract-check item* (C1-C12), and record fixtures (S1). A difference is fixed in an amendment to this RFC before code is written. The studio is PG's repo and PG owns its contract; this RFC follows it and never edits it.

## Problem

Verified on `development` @ `a62bd454`.

1. **Only the old studio is reachable.** `tools/blackgrid_studio.py::BlackGridStudioTool` drives a local ComfyUI HR Endless sampler through `studio/blackgrid_runtime.py` (port 8188, `BlackGridSettings` in `config.py`). It cannot reach the new Black Grid Multimedia Studio (local FastAPI on `127.0.0.1:8745`), which has a story bible, durable pipeline runs, streaming book ingest, Wan2.2 clip generation, review and a final stitch (BGM #32-#34).
2. **The tool is nearly unreachable in the live path.** The live loop uses `agent/tool_exposure.py` (`tool_names_for`, `schemas_for`). Its `CLASS_TOOLS` and `CAPABILITY_ALIASES` do not mention `blackgrid_studio`, and `agent/tool_retrieval.py::_SEARCH_TERMS` has no entry for it. Only the older `tools/exposure.py::TASK_TOOL_SETS` lists it (used by `agent/local_harness.py`). In practice the model reaches it only by calling `request_tools` with the exact name.
3. **No policy for studio actions.** `policy/reversibility.py::resolve_action_effect` knows nothing about `blackgrid_studio`, so every action falls into the generic medium-risk path. A multi-hour render and a read look the same to the gate.
4. **ANZU and the studio fight for 16 GB.** The studio's Wan2.2 clip runs need almost all of a 16 GB card. ANZU's models (front and worker seats, LM Studio or llama.cpp instances loaded by ANZU) stay resident, and nothing on `development` checks whether another application is rendering before `InferenceManager.load` or `FrontRuntime.ensure_started` loads a model. The first symptom is a CUDA out-of-memory error halfway through a long render.
5. **The studio cannot say "the GPU is busy".** At the traced heads there is no endpoint that reports it. Runs are listed **per project** (`GET /api/projects/{project_id}/pipeline/runs`), and the legacy JSON-clip flow's jobs (`GET /api/jobs/{job_id}`, kinds `generate`, `video`, `image`, `stitch`) have no list endpoint at all. Run status alone is also the wrong signal: PG confirms a **paused** run still holds the Wan weights today, and a later Pause may release them. That is a studio-side gap (BGM-P1, with the fields PG named: `wan_loaded`, `active_run`, `paused`, `vram_mb`).

## Decision

Ship **one RFC with five implement slices (S1-S5)**, one named model per slice, fast mode off, plus **two studio-side PRs** that belong to the BGM repo and PG's review.

```
owner / model turn ─► agent/tool_exposure.py (alias + retrieval, S2) ─► ToolRegistry.execute("blackgrid_studio", action="studio_*")
        │                                   │
        │                                   ├─ gate: policy.reversibility.resolve_action_effect (new branch, S2) ─► ApprovalGrant for expensive/destructive actions (RFC-0031/0110)
        │                                   └─ BgmClient (S1, loopback only, fixtures-conformant) ─► http://127.0.0.1:8745/api/...
        │
        └─ before ANZU loads ANY model: StudioGpuGate.check (S3) ─► BGM-P1 GET /api/gpu/status (keys on wan_loaded / active_run / ingest_llm.loaded)
              busy ─► defer the load with a visible reason (explicit owner Load: refused, 409)
              free / studio not running ─► load as today
        run starts (seen by poll, or started through this tool) ─► verified release of ANZU-loaded models (#686 T3 path) ─► hold + visible reason
        run ends ─► hold cleared ─► respawn on demand (`keep_warm` true: one respawn of the released seats via RFC-0225 `prepare_engine_for`)
```

**One tool path, not a parallel one.** The connector is extra actions on the existing `blackgrid_studio` tool (same registry entry, same `ToolRegistry.execute`, same gate, same exposure code). There is no new tool class, no MCP server and no second HTTP layer.

### Terms

| Term | Meaning |
| --- | --- |
| **Studio** | Black Grid Multimedia Studio, the BGM repo's `studio/backend` FastAPI app. |
| **Run** | One `pipeline_runs` row (`RunOut`): stage `clip_import`, `ingest`, `generate` or `stitch`; status `running`, `paused`, `completed`, `failed`. |
| **Studio hold** | The state in which ANZU has no ANZU-loaded model resident and loads none because BGM-P1 says the GPU is busy (`wan_loaded`, a running `generate` run, or the studio's own ingest model loaded). |
| **ANZU-loaded model** | A model ANZU started or loaded itself (front/worker seats, ANZU-managed llama.cpp, LM Studio or Ollama instances ANZU loaded). Models the owner loaded in another program are not ANZU-loaded. This is the same boundary RFC-0244, RFC-0228 and RFC-0245 use. |

## 1. Studio contract (what ANZU calls)

Base `http://127.0.0.1:8745`, every route under `/api` (`APIRouter(prefix="/api")` in `studio/backend/main.py`). Schemas are the Pydantic models named in the *defined in* column; ANZU mirrors them as its own Pydantic models in `studio/bgm_models.py` and validates every response with them (S1). Paths use `{pid}` for the string project id and integer ids elsewhere.

| Endpoint | Defined in (BGM symbol; PR) | Request → response | Tool action (class, see §3) |
| --- | --- | --- | --- |
| `GET /api/health` | `main.py::health` (#32 base) | → `{"ok": true}` | `studio_status` (read) |
| `GET /api/contract` | **BGM-P2 (new)** | → `{"contract_version": 1, "stages": [...], "endpoints": [...]}`; also carries `abs_path` next to `path` on movie and take records (C12) | `studio_status` (read); pinned as `tests/fixtures/bgm/contract.json` (S5) |
| `GET /api/gpu/status` | **BGM-P1 (new)** | → `GpuStatus` (below) | `studio_status`, gate (read) |
| `GET /api/projects`, `POST /api/projects` | `main.py::list_projects`, `create_project` | → `list[ProjectSummary]`; `CreateProjectBody{title?}` → `ProjectOut` | `studio_projects` (read), `studio_create_project` (write) |
| `GET /api/projects/{pid}` | `main.py::get_project` | → `ProjectOut` | `studio_projects` (read) |
| `GET /api/projects/{pid}/bible` | `bible_api.py::get_bible` (#32) | → `BibleSummaryOut{bible_version, entity_counts, prompt_counts}` | `studio_bible` (read) |
| `GET/POST /api/projects/{pid}/entities`, `GET/PATCH/DELETE .../entities/{eid}` | `bible_api.py::list_entities`, `create_entity`, `get_entity`, `patch_entity`, `delete_entity` (#32) | `EntityCreate{kind, name, summary?, description?, appearance?, notes?}`, `EntityPatch{... , voice?}` → `EntityOut` (kinds `character`, `place`, `poi`; `voice{instruct, language, temperature, seed}`) | `studio_bible` (read), `studio_entity` (write), `studio_delete_entity` (destructive) |
| `GET /api/projects/{pid}/entity-proposals`, `POST .../{id}/accept\|dismiss` | `bible_api.py::list_proposals`, `accept_proposal`, `dismiss_proposal` (#33) | → `ProposalOut`; one proposal per call, **no bulk** | `studio_bible` (read), `studio_proposal` (single accept or dismiss, gated, see §3) |
| `POST /api/projects/{pid}/sources` (multipart field `file`), `GET .../sources` | `bible_api.py::upload_source`, `list_sources` (#33) | → `SourceOut{id, filename, original_name, kind, size}`; extensions allow-listed by BGM (`txt`, `md`, `epub`, `pdf`), 200 MB cap | `studio_upload_source` (write) |
| `POST /api/projects/{pid}/pipeline/runs` | `bible_api.py::start_run`, body `RunCreate{stage, source_id?, chunk_chars?, prompt_id?, remarks?, all_prompts}` (#32, #33, #34) | → `RunOut` (201) | `stage="ingest"` → `studio_start_ingest`; `stage="generate"` → `studio_start_generation`; `stage="stitch"` → `studio_start_stitch` (all gated) |
| `GET /api/projects/{pid}/pipeline/runs`, `GET .../runs/{run_id}` | `bible_api.py::list_runs`, `get_run` | → `RunOut{id, project_id, stage, status, cursor, total, current_seq, resumable, error, params, created_at, updated_at}` | `studio_runs` (read) |
| `POST .../pipeline/runs/{run_id}/pause`, `.../resume` | `bible_api.py::pause_run`, `resume_run` | → `RunOut` | `studio_run_control` (`pause` is a small write; `resume` can restart a GPU run, so it is gated) |
| `GET /api/generation/config`, `PUT /api/generation/config` | `generation_api.py::get_generation_config`, `put_generation_config` (#34) | → `GenerationConfig`; partial dict update, 422 on invalid | `studio_config` (read), `studio_set_config` (write) |
| `GET /api/projects/{pid}/prompts` | `bible_api.py::list_prompts` | → `list[PromptOut]` (status `pending\|approved\|rejected`) | `studio_prompts` (read) |
| `POST .../prompts/{prompt_id}/approve\|reject` | `bible_api.py::approve_prompt`, `reject_prompt` (body `RemarksBody{remarks?}`) | → `PromptOut` | `studio_review_prompt` (owner-review, gated) |
| `GET .../takes`, `POST .../prompts/{prompt_id}/approve-take` | `generation_api.py::list_takes`, `approve_current_take` (#34) | → `list[TakeOut]`; `PromptOut` (400 when the prompt has no take) | `studio_takes` (read), `studio_approve_take` (owner-review, gated) |
| `POST .../prompts/{prompt_id}/regenerate` | `generation_api.py::regenerate_prompt`, body `RegenerateBody{remarks}` (1-4000 chars) (#34) | → `RunOut` (201; a `generate` run for that prompt) | `studio_regenerate` (gated, GPU) |
| `GET /api/projects/{pid}/movie` | `generation_api.py::get_movie` (#34) | → `MovieStatusOut{movie?, readiness{total, approved, unapproved_seqs, missing_take_seqs, ready}}` | `studio_movie` (read) |

`GpuStatus` (BGM-P1, from PG's workers; **the four field names `wan_loaded`, `active_run`, `paused`, `vram_mb` are PG's, the rest of the shape is proposed and PG's PR sets it**): `{"contract_version": 1, "wan_loaded": bool, "active_run": {"project_id", "run_id", "stage", "status": "running|paused", "cursor", "total"} | null, "paused": bool, "vram_mb": int, "ingest_llm": {"endpoint", "model", "loaded": bool}, "stitch_uses_gpu": false, "checked_at": iso}`.

**The gate's busy rule (normative).** `busy = wan_loaded OR (active_run.stage == "generate" AND active_run.status == "running") OR ingest_llm.loaded`. It keys on `wan_loaded` and `active_run`, **never on run state alone**: a `paused` run with `wan_loaded == true` is busy (PG: a paused run still holds Wan today), and a `paused` run with `wan_loaded == false` is **free**, so on the day a later BGM Pause releases Wan, ANZU frees the hold on its next poll with no ANZU change. A running `generate` run that has not loaded Wan yet (lazy load) is busy because it is about to. `ingest` is busy only while its LLM (`ingest_llm`, `bgm-ingest-9b` in Ollama) is loaded; `stitch` is CPU ffmpeg (libx264) and never holds the GPU, which P1 states as `stitch_uses_gpu: false` (any other value is a `StudioContractMismatch`). `vram_mb` is shown in the hold text and never used to decide. ANZU never reads run lists for this.

**Stage rules the connector relies on** (from `GenerateStage` / `StitchStage` / `PipelineRunner`):
- `generate` renders with Wan2.2 TI2V-5B when `GenerationConfig.video_backend == "wan"` (default); `video_backend == "ffmpeg"` is the no-GPU fallback (then `wan_loaded` stays false). `ingest` calls the studio's LLM, which PG confirms is **`bgm-ingest-9b` in Ollama** (not LM Studio, not ANZU's 9B; the PR text said the default `Settings.llm_base_url` is LM Studio, superseded by PG's answer; P1 exposes the real endpoint and model). `stitch` is CPU ffmpeg (libx264) and never holds the GPU (C6).
- One active (running or paused) run per project (`pipeline_one_active` unique index), so a second start answers 409 (`BibleConflict`).
- `stitch` needs every non-orphaned prompt approved with a take (`StitchStage.prepare`); readiness is `GET .../movie`.
- **Do not use** the legacy JSON-flow routes (`POST /api/projects/{pid}/stitch`, `.../clips/{cid}/generate`, `GET /api/jobs/{job_id}`). The connector's `studio_start_stitch` means the **pipeline stage** `stitch` via `POST .../pipeline/runs`, never the legacy `POST /api/projects/{pid}/stitch` that has the same word in its path (C7).

### Contract-check items (assumptions to verify on BGM `main`, one fixture each)

| # | Assumption (where the PR is ambiguous) | If wrong |
| --- | --- | --- |
| C1 | `/api/health` still returns `{"ok": true}` and every route is under `/api`. | Amend §1; S1 changes only `BgmClient`. |
| C2 | Project ids are opaque strings; entity, prompt, take and run ids are integers. | Models change to the real types. |
| C3 | `POST .../sources` takes multipart field `file` and answers 201 `SourceOut`; `source_id` feeds `RunCreate`. | S1 upload adapter changes. |
| C4 | `stage="stitch"` accepts an empty params body; `generate` accepts `prompt_id`, `remarks`, `all_prompts` as in `RunCreate`. | Gated actions map to the real fields. |
| C5 | `pause_run` finishes the in-flight step (and saves it) before the run stays paused (as the #32 text says). **Resolved (PG):** a paused `generate` run **still holds Wan today**, so `paused` with `wan_loaded == true` is busy; a later BGM Pause may release Wan, after which `wan_loaded == false` frees the hold automatically (test `test_paused_with_wan_loaded_false_frees_the_hold_automatically`). | n/a; the gate keys on `wan_loaded`. |
| C6 | **Resolved (PG):** `stitch` is CPU ffmpeg (libx264) and never holds the GPU (P1 states `stitch_uses_gpu: false`); `ingest` counts as busy only while `bgm-ingest-9b` is loaded (P1 exposes `ingest_llm`). | A different value fails loudly (`StudioContractMismatch`). |
| C7 | The legacy `POST /api/projects/{pid}/stitch` stays a separate JSON-flow route. | If retired, nothing changes. |
| C8 | `approve_prompt` (pre-generation text review) and `approve_current_take` (post-render review) are the two review approvals; `PromptPatch.status` is not used by the connector. | Mapping changes. |
| C9 | `RunOut.status` values are exactly `running`, `paused`, `completed`, `failed`. | `studio_runs` normaliser changes; a new value fails loudly (unknown status). |
| C10 | `GenerationConfig.video_backend` is `wan` or `ffmpeg`, and `PUT /api/generation/config` is a partial update. | The config summary shown in approvals changes. |
| C11 | **Resolved (PG):** v1 has no project delete and no bulk entity proposals; proposals are handled one at a time. | A delete or bulk action is added only by a later amendment. |
| C12 | **Resolved (PG):** BGM-P2 returns `abs_path` alongside `path` (`MovieOut.path` stays relative to `projects/<pid>/`). ANZU reports `abs_path` and has **no studio-directory setting**. Verify at the re-trace which payloads carry it (movie and take records at least). | If `abs_path` is absent from a payload, `StudioContractMismatch` names it; ANZU never guesses an absolute path. |

## 2. The connector client (S1)

`backend/app/studio/bgm_client.py::BgmClient` is the only code that talks to the studio.

- **Loopback only, enforced twice.** `config.BlackGridSettings` gains `studio_api_enabled: bool = False`, `studio_api_url: str = "http://127.0.0.1:8745"`, and a Pydantic validator that rejects anything else. `BgmClient.__init__` re-validates, so a settings file edited by hand cannot bypass it. Accepted hosts are exactly `127.0.0.1`, `::1` and `localhost` (normalised to `127.0.0.1`), scheme `http` only, no userinfo, no path other than empty or `/`. It deliberately does **not** reuse `tools/safety.py::is_owner_local_host`, which also accepts RFC1918 and `.local` hosts.
- **No detours.** `httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=...)`, so a proxy variable or a redirect cannot carry a call off the loopback interface. A 3xx answer is an error.
- **Timeouts.** Read calls 5 s, writes 15 s, the upload streams the file in 1 MiB blocks with a 300 s total. Studio steps run on the studio's own thread, so these calls never wait for a render.
- **Studio not running is a result, not an exception.** Connection refused (and only that) returns `StudioNotRunning` and the tool answers `{"studio": "not_running", "detail": "Black Grid Multimedia Studio is not running on 127.0.0.1:8745. Start it from its folder (studio/start.ps1) and ask again."}`. Timeouts, 5xx and malformed bodies are different, named errors (`StudioTimeout`, `StudioError`, `StudioContractMismatch`) with the studio's own detail text.
- **Contract conformance.** Every response is parsed by the mirrored Pydantic models with `extra="ignore"` for new optional fields but **required fields missing or a wrong type raises `StudioContractMismatch("<endpoint>: <field>")`**; the tool shows it verbatim. `GET /api/contract` is read once per session: `contract_version` must be `1` (the version this RFC was written for, pinned in `tests/fixtures/bgm/contract.json`), otherwise every action but `studio_status` answers "studio contract version N is not supported by this ANZU".
- **Recorded fixtures.** `scripts/record_bgm_fixtures.py` (run locally by PG or on VRPC against a running studio; CI never starts a studio) calls each endpoint of §1 and writes `tests/fixtures/bgm/<endpoint-slug>.json` plus `tests/fixtures/bgm/manifest.json` (endpoint, method, BGM `main` description, recorded date). The conformance test replays them, so CI needs no studio for it.
- **Files stay in ANZU's policy.** `studio_upload_source` takes an absolute path that must resolve through `tools/safety.py::resolve_allowed_path` against `live_allowed_directories(...)` (the same allow-list the filesystem tool uses), and the extension is checked before any byte is read.

## 3. One tool, extra actions, ANZU's own approval pattern (S2)

`tools/blackgrid_studio.py::BlackGridStudioTool` gains the `studio_*` actions of §1 on the same `parameters` schema (`action` enum plus `project_id`, `entity`, `proposal_id`, `prompt_id`, `run_id`, `remarks`, `path`, `config` fields). **The old ComfyUI actions are retired only in S2's own PR, only together with working `studio_*` replacements, and only after the reviewer confirms nothing live calls them. They are never deleted first** (PG ruling 2026-11-03):

| Legacy action | Replacement in S2 |
| --- | --- |
| `status` | `studio_status` |
| `list_outputs` | `studio_movie` (+ `studio_takes`) |
| `submit_hr_endless` | `studio_start_generation` (story-pipeline render, gated) |
| `open_workbench`, `open_comfy` | none on the tool: they open browser tabs; the workbench route and `api/blackgrid.py` stay for the UI |
| `install`, `start` | none: ANZU does not install or start the studio (a separate repo the owner starts; the not-running result says how). The sidecar's own install and start stay in `api/blackgrid.py` and the modules catalog, untouched |

S2's PR body carries the grep evidence (below) and the reviewer's written confirmation. If the reviewer finds a live caller, that action **stays** and the PR says so. `studio/blackgrid_runtime.py`, `api/blackgrid.py` and the modules catalog are **not** touched by this RFC.

**Reachability fix (live path).** S2 adds, in `agent/tool_exposure.py::CAPABILITY_ALIASES`, the aliases `blackgrid`, `black grid`, `studio`, `multimedia_studio` → `blackgrid_studio`; and in `agent/tool_retrieval.py::_SEARCH_TERMS` an entry `blackgrid_studio` with distinctive terms (`black grid`, `blackgrid`, `story bible`, `movie from`, `book to video`, `video prompts`, `stitch the movie`). Generic words such as "video" or "studio" alone do not retrieve it (the module's own rule against catalog bloat).

**Approval: the existing pattern, no new one.** Mutating actions go through `policy/reversibility_gate.py::evaluate_side_effect` and `ApprovalGrant` (`policy/approval_grant.py`: `park_approval_request`, `decide_approval_request`, `validate_grant_for_action`, `consume_grant`) with the RFC-0110 approval popup. A model's `confirmed=true` never counts (`model_attempted_self_confirm`). S2 adds one branch to `policy/reversibility.py::resolve_action_effect` for tool `blackgrid_studio` and actions starting `studio_` (legacy actions fall through unchanged). The branch is synchronous and makes **no network call**: it uses only the tool arguments.

| Class | Actions | Effect metadata |
| --- | --- | --- |
| Read | `studio_status`, `studio_projects`, `studio_bible`, `studio_prompts`, `studio_runs`, `studio_config`, `studio_takes`, `studio_movie` | `REVERSIBLE`, not side-effecting. No grant. |
| Small write | `studio_create_project`, `studio_entity`, `studio_upload_source`, `studio_run_control` with `pause`, `studio_set_config` | `COMPENSATABLE`, not high-consequence. Normal autonomy applies; no grant at the default level. `studio_set_config` returns the previous config in its result so the owner can undo it. |
| **Expensive** | `studio_start_generation`, `studio_regenerate`, `studio_start_stitch`, `studio_start_ingest`, `studio_run_control` with `resume` (the gate branch is synchronous and cannot look up the run's stage, so every resume is gated) | `UNKNOWN`, `high_consequence=True`. **`ApprovalGrant` required.** Target: `bgm:<pid>:<action>:<scope>` where scope is `all` / `missing` / `prompt:<id>#<sha8 of remarks>` / `source:<id>`. The grant binds the exact target, so approving "regenerate prompt 7 with these remarks" cannot be spent on other remarks. The popup text states the project, how many clips will render, the video backend and resolution (from the last `studio_config` read) and that **ANZU will unload its models while the studio renders**. |
| **Review decisions** | `studio_review_prompt`, `studio_approve_take`, `studio_proposal` | `UNKNOWN`, `high_consequence=True`. **Grant required.** ANZU never approves a prompt or a take on its own authority; approval is the owner's creative gate before the stitch. |
| **Destructive** | `studio_delete_entity` | `IRREVERSIBLE`. Grant required. |

**Entity edits and proposals (PG ruling).** Proposals are handled **one at a time**; there is no bulk accept or dismiss. **User edits win over ANZU proposals:** BGM records the fields an owner typed or edited as `EntityOut.user_edited`. `studio_entity` (update) reads the entity first and **does not overwrite any field listed in `user_edited`**; it returns those fields as `skipped_owner_edited` with ANZU's suggested text so the owner decides, and writes only the remaining fields. `studio_proposal` accepts or dismisses exactly one `ProposalOut` per call, and accept needs a grant (it applies text and makes it authoritative). Not exposed on purpose: deleting prompts, entity image upload and delete, reorder, project delete (none exists in v1). They stay owner actions in the studio UI until a later amendment proves the need.

**Engine modes (RFC-0244).** The tool is an agent tool, so it is reachable only through the agent loop, which under `reflex_only` stops at `engine_mode.model_enabled(settings)` before any tool call (`agent/loop.py` `_run`). `reflex_only` therefore cannot call a studio action, and S2 changes no mode logic. `model_only` and `hybrid` expose it identically. A `reflex_only` owner who asks for the studio gets the existing `reflex_only_reply` text and no work runs.

## 4. The GPU gate (S3)

`backend/app/studio/gpu_gate.py::StudioGpuGate` is the only new moving part.

**What it reads.** `BgmClient.gpu_status()` (BGM-P1) and applies the busy rule of §1. Result classes: `free` (200, rule false), `busy` (200, rule true), `not_running` (connection refused), `unknown` (timeout, 5xx, malformed, contract mismatch). It never reads project run lists and never decides from run state alone.

**Where it checks.** Exactly the two places ANZU starts a model, so there is no parallel load path:
- `inference/manager.py::InferenceManager.load` and `_load_locked` (covers the worker seat, LM Studio, Ollama and managed llama.cpp loads that go through `MANAGER.load`),
- `inference/front_runtime.py::FrontRuntime.ensure_started` and `_start_local` (the front responder).

A static test classifies every `MANAGER.load(` call site (the same table and test as #686 T3 uses; S3 adds a column) so a new load path cannot appear unguarded.

| Situation | Automatic load (chat turn, startup restore, `RUNNING_MODELS` autoload, keep-warm respawn) | Explicit owner Load (#686 T6 routes) |
| --- | --- | --- |
| `free` or `not_running` | proceeds as today | proceeds as today |
| `busy` | **deferred**: raises `StudioGpuBusy(RuntimeError)` with the reason text below; autoload branches that #686 already skips silently skip silently | **refused**: `POST /api/model/load` and the activate routes answer 409 with the same text; the owner can pause the run (`studio_run_control`) or wait. No silent override. |
| `unknown` | deferred with "Studio status could not be read; ANZU is waiting rather than risk the render." | **allowed** (only a confirmed busy status blocks an explicit owner action) |

Reason text (fixed, tested): for a render, `BlackGrid Studio is rendering (project "<title>", clip <cursor>/<total>; about <vram_mb> MB of the GPU). ANZU's models stay unloaded so the render keeps the GPU. Ask again when it finishes, or pause the run.`; while only the ingest model is loaded, `BlackGrid Studio is ingesting a book (its model bgm-ingest-9b is loaded). ANZU's models stay unloaded until it finishes.`; for a paused run that still holds Wan, `BlackGrid Studio's run is paused but still holds the GPU (Wan is loaded).` Jev and Laya are CPU deciders and keep answering reflex turns during a hold; only generative turns see the reason.

**Unload on run start.** Two triggers, one action:
- *Started through ANZU:* `studio_start_generation` / `studio_regenerate` / a `resume` of a `generate` run (the tool reads the run's stage at execution time; resuming an ingest run releases nothing), after the grant and **before** the `POST`, calls the verified release of #686 T3 for **every ANZU-loaded model, front seat included** (`reason="studio_run"`). If the release is not verified (T3's own 409/502 result) or ANZU is mid-answer (`MANAGER._request_lease.exclusive()` not acquired), **the studio run is not started** and the tool says why. Nothing is half-started.
- *Started from the studio's own UI:* a watcher polls BGM-P1 every `STUDIO_WATCH_INTERVAL_S = 10` while any ANZU-loaded model is resident, backs off to `STUDIO_WATCH_BACKOFF_S = 60` while the studio is `not_running`, and polls nothing when no ANZU-loaded model is resident and no hold is active. On `free → busy` it runs the same verified release.

The release uses the **verified native path** only (LM Studio `loaded_instances` check, Ollama `/api/ps` check, managed process stop; #686 T3). A studio hold **does not** set `manually_unloaded` (that flag means "stays unloaded until explicit Load" and belongs to an owner Unload, as the amendment's composition table says), and it is **not** recorded as an idle unload (`engine_coexistence.idle_unloaded()` of RFC-0228); it is its own reason, `studio_hold`, reported only after the same verified evidence (R5). A hold clears itself. When an idle unload already released the models, run start finds nothing resident, releases nothing and still holds.

**The studio's own model is never touched (PG ruling 3, matching CoS's keep-warm ruling to D2).** `bgm-ingest-9b` in Ollama belongs to the studio. ANZU **never unloads it and never sets `keep_alive` on it**: the gate's release, the keep-warm/idle-unload path and every ANZU Ollama warm skip it. S3 adds one guard, `StudioModelGuard.is_studio_model(endpoint, model)`, which matches P1's `ingest_llm.endpoint` and `ingest_llm.model` **and** the constant name `bgm-ingest-9b` (so the skip holds even while the studio is down or P1 is unreadable), and D2's path calls it (if D2's PR does not already skip the model, S3 adds the one call). The same P1 fields let the gate tell the studio's model apart from an owner-loaded one. **Owner-loaded models are left alone and the hold message is shown** (PG ruling 3): a model the owner loaded in another program (for example Taco's LM Studio 9B, which the studio does **not** use) is not ANZU-loaded and stays under the amendment's rule (the RFC-0225 and RFC-0228 managed-mode rule; this RFC does not widen consent). ANZU leaves it running, and the hold text adds `LM Studio's model "<id>" is still resident because you loaded it; unload it from the model menu to give the render the whole GPU.` using the existing explicit Unload (RFC-0244 inventory is read-only; ANZU stops no other program).

**Respawn after the run.** The watcher's next poll sees the busy rule false (`wan_loaded` false, no running `generate` run, ingest model unloaded) (or `not_running`, which includes a studio crash) and clears the hold, publishes the cleared state, and does **nothing else**. The next request loads on demand through the normal path. With **Keep warm ON** (`keep_warm` true in the amendment's proposed names) the gate asks for **one** respawn of exactly the seats it released, through RFC-0225 `prepare_engine_for`, the same call the amendment's on-demand respawn uses, never a private loader; ANZU-originated Ollama warms after it use the amendment's `keep_alive` rule (`"-1"` when on, `f"{idle_unload_seconds}s"` when off). With Keep warm OFF (default, `idle_unload_seconds` 300) there is no preload and the normal idle timer applies to whatever loads next. D2's PR sets the final names; S3 follows them.

### Keep warm × studio × engine mode

| | Keep warm OFF (default; `keep_warm` false, `idle_unload_seconds` 300) | Keep warm ON (`keep_warm` true; no idle timer, Ollama `keep_alive` `"-1"`) |
| --- | --- | --- |
| Studio run active, any mode | ANZU-loaded models unloaded at run start (not at the 5-minute mark); loads deferred | **Studio run wins.** Same unload, same deferral, a visible reason. Keep warm's "stay resident" is suspended, not turned off |
| Run ends, `hybrid` / `model_only` | hold cleared; next request respawns on demand | hold cleared; one respawn of the released seats via `prepare_engine_for` |
| Run ends, `reflex_only` | hold cleared; nothing loads | hold cleared; **no respawn** (no model lane is allowed to start) |
| `reflex_only`, run active | there is no automatic load to defer. A model the owner explicitly Loaded under #686 T6 is resident-but-unused; the run-start release unloads it like any other ANZU-loaded model, and an explicit Load is refused while busy | same |

The user-visible reason: `status_monitor` adds one live key `studio_hold: {"active": bool, "reason": str, "project_id": str, "run_id": int, "since": iso}` to the `/api/model` snapshot (additive; #686 T3 owns the same file earlier in the chain), the deferred chat turn shows the reason text as the answer, and the HUD shows one status line (S4). The chat turn is never silent.

## 5. Network and auth

- **Loopback only (S1).** See §2. Nothing in ANZU listens for, proxies or forwards studio traffic; there is no ANZU route that exposes BGM bytes.
- **Remote use goes through ANZU's existing auth.** A phone or LAN companion reaches the studio only by sending an ANZU task or chat turn. That request is authenticated by `auth.authenticate_request` / `require_owner_private_key` (the owner private key; loopback is the owner console, LAN/companion callers need the key) and by the computer-permission checks, exactly like every other tool. The studio's own port is never published. **PG ruling:** BGM has no auth today and token auth is required in BGM before any non-loopback use, so the connector stays loopback only (S1 guard) and this RFC adds no auth code.
- No studio credential is stored by ANZU in this RFC. If BGM-P3 (future, BGM-side token auth) ships, the token goes in the vault (`vault` / `get_effective_private_key` pattern), never in `settings.json`, and lifting the loopback-only rule needs its own RFC amendment.

## 6. Studio-side changes (BGM-repo PRs from PG's workers, reviewed by PG; stacked after BGM #34; ANZU never pushes to `bgm/*`)

| PR | Change | Why | Needed by |
| --- | --- | --- | --- |
| **BGM-P1** | `GET /api/gpu/status` → `GpuStatus` (§1): `wan_loaded`, `active_run`, `paused`, `vram_mb` (PG's names) plus `ingest_llm{endpoint, model, loaded}` and `stitch_uses_gpu: false`. Covers pipeline runs **and** the legacy job flow | One truthful answer to "does the studio hold the GPU"; a paused run still holds Wan today, so run state alone is wrong | S3 |
| **BGM-P2** | `GET /api/contract` → `{contract_version, stages, endpoints}`; adds `abs_path` next to `path` on movie and take records | Version check, drift detection, the pinned `contract.json`, and absolute file paths | S1, S5 |
| BGM-P3 (future, **not** an ANZU ticket) | Token auth | Required in BGM before any non-loopback use (PG ruling) | none |
| BGM-P4 (optional, PG's call) | Release Wan weights when a `generate` run pauses | Frees the GPU for ANZU during long pauses; when it lands, `wan_loaded == false` frees ANZU's hold with no ANZU change | none |

## 7. Live-UI add-alongside reasoning pass (2026-10-14 standing order)

The only UI change is one status line in the model dropdown's status area (`frontend/src/hud/modelMenuStatus.ts`, rendered by `HudModelSelector.tsx`), shown **only** while `studio_hold.active`.

| Existing element | What S4 does | Reasoning |
| --- | --- | --- |
| Trigger button, "Serving now", Load, Unload, More, engine-mode control | unchanged | The line is additive and absent in the common case, so the menu looks the same. |
| Load button during a hold | stays enabled; the 409 text from §4 shows in the existing error line | No silently dead control (R7 of #686). |
| Persona, WebGL, presence, chat bubbles | untouched | Astra-owned. |

No `[hidden]`, `display: none` or removal of any element is introduced; new CSS is additive in `frontend/src/hud/nodeModels.css`. Live audit (recorded in the S4 PR, numbers not invented in advance): on Taco's PC at 390 px and 1366 px the line wraps without overflow and `Escape` still closes the menu.

## Slices (one ticket each, fast mode off, lane assigned by Chief of Staff at the gate)

Ticket order: **S1 → S2, S3, S5 (parallel after S1; S5 also needs BGM-P2's first response) → S4 (after S3)**. Every ticket starts with the contract re-trace (*Gating*).

### S1: Client, settings, loopback guard, fixtures and conformance
**Model:** Grok 4.5 (fast mode off). **Depends:** gating items 1, 2, 4.
**Owns:** `backend/app/studio/bgm_client.py` (new), `backend/app/studio/bgm_models.py` (new), `backend/app/config.py` (`BlackGridSettings` fields only, after every earlier chain), `scripts/record_bgm_fixtures.py` (new; run locally, never in CI), `tests/fixtures/bgm/*.json` except `contract.json` and `manifest.json` (new), `tests/test_rfc0246_bgm_client.py`, `tests/test_rfc0246_bgm_contract.py`, `.github/workflows/pr-tests.yml` (new step only).
**Tests (named):**
- `tests/test_rfc0246_bgm_client.py`: `test_base_url_rejects_non_loopback` (parametrised: `0.0.0.0`, `192.168.1.20`, `10.0.0.5`, `studio.local`, `example.com`, `http://127.0.0.1@evil.example`, `https://127.0.0.1:8745`), `test_lan_address_accepted_by_is_owner_local_host_is_rejected_here`, `test_localhost_and_ipv6_loopback_accepted_and_normalised`, `test_settings_validator_rejects_remote_url`, `test_hand_edited_settings_cannot_bypass_client_check`, `test_redirect_is_not_followed`, `test_proxy_environment_is_ignored`, `test_connection_refused_returns_studio_not_running_result`, `test_timeout_5xx_and_malformed_are_distinct_errors`, `test_http_409_404_400_422_map_to_named_errors_with_studio_detail`, `test_upload_streams_in_blocks_and_enforces_allowed_directories_and_extension`, `test_contract_version_other_than_1_refuses_all_but_status`, `test_gpu_status_model_parses_pinned_fields`, `test_stitch_uses_gpu_true_is_a_contract_mismatch`, `test_abs_path_is_reported_and_no_studio_dir_setting_exists`.
- `tests/test_rfc0246_bgm_contract.py`: `test_manifest_covers_every_endpoint_in_the_client_registry`, `test_every_recorded_fixture_parses_with_the_mirrored_models`, `test_missing_required_field_raises_studio_contract_mismatch`, `test_extra_optional_fields_are_ignored`, `test_unknown_run_status_fails_loudly` (C9), `test_proposals_are_single_accept_dismiss_only_no_bulk_client_method` (C11).
**CI step:** new `pytest` job step `BlackGrid Studio connector tests (RFC-0246)` running `python -m pytest -q -rs tests/test_rfc0246_bgm_client.py tests/test_rfc0246_bgm_contract.py`, and the existing `Run full backend suite`.
**Acceptance:**
- [ ] A non-loopback URL is rejected at settings validation and at client construction.
- [ ] Studio not running yields the clear result above and never an exception to the user.
- [ ] Every endpoint of §1 has a recorded fixture and a parsing test, and contract drift names the endpoint and field.
- [ ] No studio call is made while `studio_api_enabled` is false.

### S2: Tool actions, policy branch, exposure
**Model:** Grok 4.6 (fast mode off). **Depends:** S1.
**Owns:** `backend/app/tools/blackgrid_studio.py` (`studio_*` actions added; the seven legacy ComfyUI actions removed in the same PR, see acceptance), `backend/app/tools/exposure.py` (remove the `comfyui` and `hr_endless` alias entries only), `backend/app/policy/reversibility.py` (`resolve_action_effect` branch only), `backend/app/agent/tool_exposure.py` (`CAPABILITY_ALIASES` only), `backend/app/agent/tool_retrieval.py` (`_SEARCH_TERMS` entry only), `frontend/src/pages/Tools.tsx` (copy only, if it names a retired action), `tests/test_blackgrid_studio.py` (the legacy-action tests are replaced by their `studio_*` equivalents), `tests/test_rfc0246_bgm_tool.py`, `.github/workflows/pr-tests.yml` (add the file to S1's step).
**Tests (named):** `tests/test_rfc0246_bgm_tool.py`: `test_studio_actions_live_on_the_existing_tool_not_a_new_one`, `test_legacy_comfy_actions_removed_only_with_every_studio_replacement_present`, `test_no_live_caller_of_legacy_comfy_actions` (static: the quoted literals `"open_workbench"`, `"open_comfy"`, `"submit_hr_endless"`, `"list_outputs"` and any `blackgrid_studio` call with `action` `install`, `start` or `status` appear nowhere under `backend/app`, `frontend/src` or `android/` outside this RFC's tests; `blackgrid_runtime.submit_hr_endless_job` and the `/api/blackgrid/*` routes are different symbols and stay), `test_comfy_alias_entries_removed_but_blackgrid_aliases_kept`, `test_user_edited_fields_win_over_anzu_edits_and_proposals`, `test_studio_entity_update_skips_owner_edited_fields_and_reports_them`, `test_proposal_accept_or_dismiss_is_one_per_call_and_accept_needs_grant`, `test_no_bulk_proposal_or_project_delete_action_exists`, `test_every_action_in_the_schema_has_an_effect_class` (static), `test_read_actions_need_no_grant`, `test_start_generation_requires_approval_grant`, `test_regenerate_grant_binds_the_remarks_digest`, `test_start_stitch_requires_grant`, `test_start_ingest_requires_grant`, `test_every_resume_requires_grant_but_pause_does_not`, `test_review_prompt_and_approve_take_require_grant`, `test_delete_entity_requires_grant`, `test_model_self_confirm_never_satisfies_the_gate`, `test_gate_branch_makes_no_network_call`, `test_studio_not_running_is_a_clear_tool_result`, `test_studio_prompt_retrieves_the_tool_on_the_live_path` (`tool_names_for`), `test_generic_video_prompt_does_not_retrieve_it`, `test_reflex_only_turn_never_calls_a_studio_action`, `test_model_only_and_hybrid_expose_the_tool`, `test_stitch_action_uses_the_pipeline_stage_not_the_legacy_route` (C7).
**CI step:** `BlackGrid Studio connector tests (RFC-0246)` plus `Run model and security regression tests` (it already runs `tests/test_tool_exposure.py`, which S2 must keep green).
**Acceptance:**
- [ ] Every action of §1 is reachable through `ToolRegistry.execute` and returns a structured result (`ToolResult.data`).
- [ ] Expensive, review and destructive actions cannot run without a real `ApprovalGrant`, and the grant is bound to the exact target.
- [ ] A studio prompt retrieves the tool in the live loop; unrelated prompts do not.
- [ ] No new tool class, no MCP server and no confirmation mechanism is added.
- [ ] **Legacy ComfyUI actions** (`open_workbench`, `open_comfy`, `status`, `install`, `start`, `submit_hr_endless`, `list_outputs`) are removed **in this PR only**, with their replacements (see §3 table) working and tested in the same PR; `test_no_live_caller_of_legacy_comfy_actions` passes; and the PR body carries the grep output and the reviewer's written confirmation that nothing live calls them. If any live caller exists, that action stays and nothing is deleted first. `blackgrid_runtime.py`, `api/blackgrid.py` and the modules catalog are untouched.
- [ ] User edits win: an owner-edited field is never overwritten by ANZU, proposals are accepted or dismissed one at a time, and no bulk or project-delete action exists.

### S3: GPU gate, unload on run start, respawn after the run
**Model:** Grok 4.6 (fast mode off). **Depends:** S1, gating items 2 and 3 (BGM-P1 shape, T3, D2's keep-warm PR).
**Owns:** `backend/app/studio/gpu_gate.py` (new; `StudioGpuGate` and `StudioModelGuard`), `backend/app/inference/manager.py` (the guard in `load` / `_load_locked` only, after #686 T3/T6 and D2's keep-warm ticket), `backend/app/inference/front_runtime.py` (the guard in `ensure_started` / `_start_local`, after every earlier chain), `backend/app/inference/status_monitor.py` (the `studio_hold` key only, after #686 T3), `backend/app/main.py` (lifespan start and stop of the watcher only), `backend/app/api/model.py` (409 mapping for `StudioGpuBusy` on the explicit Load routes only), **the single `StudioModelGuard.is_studio_model` call in D2's keep-warm/idle-unload and Ollama `keep_alive` code, only if D2's PR does not already skip `bgm-ingest-9b` (file named when D2's PR lands)**, `tests/test_rfc0246_studio_gpu_gate.py`, `.github/workflows/pr-tests.yml` (add the file to the step).
**Tests (named):** `tests/test_rfc0246_studio_gpu_gate.py`: `test_load_deferred_while_run_active`, `test_front_runtime_start_deferred_while_run_active`, `test_unload_on_run_start_through_the_tool_before_the_post`, `test_unload_on_run_start_seen_by_the_watcher`, `test_run_not_started_when_release_is_unverified`, `test_run_not_started_while_a_request_is_in_flight`, `test_respawn_on_demand_after_run_ends`, `test_no_preload_after_run_when_keep_warm_off`, `test_keep_warm_on_studio_run_wins_and_unloads`, `test_keep_warm_on_respawns_released_seats_once_through_prepare_engine_for`, `test_hold_unload_is_not_recorded_as_idle_unload_or_manual_unload`, `test_run_start_with_nothing_resident_releases_nothing_and_still_holds`, `test_reflex_only_no_automatic_load_and_no_respawn`, `test_reflex_only_explicit_load_refused_while_busy`, `test_user_visible_reason_in_snapshot_and_in_the_deferred_turn`, `test_studio_not_running_never_blocks_a_load`, `test_unknown_status_blocks_automatic_load_but_not_explicit_load`, `test_studio_crash_clears_the_hold`, `test_owner_loaded_lm_studio_model_is_not_unloaded_and_the_notice_says_so`, `test_studio_hold_never_sets_manually_unloaded`, `test_watcher_backs_off_while_studio_not_running_and_stops_when_nothing_is_resident`, `test_gate_reads_only_gpu_status_not_run_lists`, `test_every_manager_load_site_is_classified_for_studio_hold` (static), `test_paused_with_wan_loaded_true_is_busy`, `test_paused_with_wan_loaded_false_frees_the_hold_automatically` (a later BGM Pause releasing Wan frees the hold on the next poll with no other change), `test_busy_keys_on_wan_loaded_and_active_run_not_run_state_alone`, `test_running_generate_run_before_wan_loads_is_busy`, `test_ingest_is_busy_only_while_bgm_ingest_9b_is_loaded`, `test_running_ingest_run_with_model_unloaded_is_free`, `test_stitch_run_never_holds_the_gpu`, `test_gate_and_keep_warm_idle_unload_both_skip_bgm_ingest_9b`, `test_no_keep_alive_is_ever_sent_for_bgm_ingest_9b`, `test_studio_model_guard_matches_p1_endpoint_and_model_and_the_constant_name_when_p1_is_down`, `test_owner_loaded_model_is_left_alone_and_hold_message_is_shown`, `test_hold_message_variants_for_render_ingest_and_paused_with_wan`.
**CI step:** `BlackGrid Studio connector tests (RFC-0246)`, `Run model and security regression tests`, `Run full backend suite`.
**Acceptance:**
- [ ] While BGM-P1 says busy (`wan_loaded`, a running `generate` run, or `ingest_llm.loaded`), no ANZU model starts by any automatic path, and explicit Load answers 409 with the reason; a paused run frees the hold exactly when `wan_loaded` is false.
- [ ] ANZU never unloads `bgm-ingest-9b` and never sets `keep_alive` on it, in the gate, the keep-warm/idle-unload path or any Ollama warm; owner-loaded models are left alone with the hold message shown.
- [ ] A run starting (through ANZU or the studio UI) unloads every ANZU-loaded model through the verified path, front seat included, or the ANZU-started run is refused with the cause.
- [ ] After the run, loads resume on demand; Keep warm ON respawns the released seats exactly once; `reflex_only` never loads.
- [ ] The owner sees why, in chat, the model menu and `/api/model`, and nothing says "unloaded" unless the verified release said so.
- [ ] Studio not running, or crashed, never blocks ANZU.

### S4: HUD studio-hold status line
**Model:** Composer 2.5 (fast mode off). **Depends:** S3.
**Owns:** `frontend/src/hud/modelMenuStatus.ts` (one pure function, after #686 T4/T6), `frontend/src/hud/HudModelSelector.tsx` (render the line only, after #686 T6), `frontend/src/hud/nodeModels.css` (additive rules only), `frontend/src/api.ts` (type field only), `frontend/studio-hold-status.test.mjs`, `frontend/package.json` (one script), `.github/workflows/pr-tests.yml` (one step).
**Tests (named):** `frontend/studio-hold-status.test.mjs`: `studio hold line shows the reason only while active`, `no line and unchanged status when studio_hold is absent or inactive`, `line text equals the backend reason verbatim`, `load button stays enabled and shows the 409 text in the existing error line`.
**CI step:** `Studio hold status tests (RFC-0246 S4)` running `npm run test:studio-hold-status` in the `frontend-build` job, plus `Build frontend` and `HUD model menu status tests (RFC-0244 restore)`.
**Acceptance:**
- [ ] The line appears only while a hold is active and never replaces an existing status.
- [ ] No element is hidden or removed; Astra-owned components are untouched.

### S5: Pinned contract fixture, conformance in CI, local live check, tool docs
**Model:** Composer 2.5 (fast mode off). **Depends:** S1, and BGM-P2's first response for the first fixture. No cross-repo CI, no BGM checkout and no BGM read token (PG ruling 2026-11-03).
**Owns:** `tests/fixtures/bgm/contract.json` (the pinned response of `GET /api/contract`, committed in the Jarvis repo; **PG refreshes it**), `scripts/refresh_bgm_contract.py` (new; fetches `/api/contract` from a running studio on loopback, rewrites the file and prints the diff), `tests/test_rfc0246_bgm_contract_pin.py`, `tests/test_rfc0246_bgm_live.py`, `.github/workflows/pr-tests.yml` (one step), `TOOLS.md` (the `blackgrid_studio` entry).
**Refresh command (PG, with the studio running):** `python scripts/refresh_bgm_contract.py --base-url http://127.0.0.1:8745`, then commit `tests/fixtures/bgm/contract.json`. The script refuses a non-loopback URL.
**Tests (named):**
- `tests/test_rfc0246_bgm_contract_pin.py` (runs in CI, needs no studio): `test_pinned_contract_declares_version_1_and_the_four_stages`, `test_every_endpoint_in_the_client_registry_is_in_the_pinned_contract`, `test_every_recorded_endpoint_fixture_matches_the_pinned_schema`, `test_pinned_contract_carries_abs_path_on_movie_and_take_records`, `test_pin_file_is_valid_json_and_has_a_recorded_date_and_source_url`, `test_refresh_script_refuses_a_non_loopback_url`.
- `tests/test_rfc0246_bgm_live.py` (local, VRPC only): `test_live_status_contract_and_gpu_status`, `test_live_contract_equals_pinned_contract`, `test_live_project_entity_roundtrip` (mutating; only with `BGM_LIVE_MUTATE=1`), `test_live_run_pause_resume_status_on_ffmpeg_backend` (mutating), `test_live_skip_reason_names_the_url_and_says_not_run`. **Skip rule (explicit, not a soft-fail):** the module skips only when `BGM_BASE_URL` (default `http://127.0.0.1:8745`) refuses the connection, with the reason `BlackGrid Studio is not running at <url>; live check NOT run (this is a skip, not a pass)`. There is no env override that turns a skip into a pass, and `BGM_LIVE_REQUIRED` does not exist. Any other failure (timeout, wrong body) fails the test.
**Local live command (VRPC, studio running):** `BGM_BASE_URL=http://127.0.0.1:8745 BGM_LIVE_MUTATE=1 python -m pytest -q -rs tests/test_rfc0246_bgm_live.py`. Without a studio the same command reports the skip reason above. The S5 PR body pastes the VRPC run, or states "live check not run".
**CI step:** `BlackGrid Studio contract pin tests (RFC-0246 S5)` running `python -m pytest -q -rs tests/test_rfc0246_bgm_contract_pin.py`. The live module is collected by `Run full backend suite` and skips there with its explicit reason, since no studio runs in CI; CI never claims a live pass.
**Acceptance:**
- [ ] CI runs the conformance tests against the pinned `tests/fixtures/bgm/contract.json`; no job checks out, builds or starts BGM, and no BGM token exists in CI.
- [ ] The live check, run on VRPC with the studio up, passes and its output is in the S5 PR; with no studio it reports the explicit skip and is never counted as a pass.
- [ ] `TOOLS.md` lists every action with its class and the gating rule.
- [ ] Installed-PC behaviour with real Wan2.2 (the actual VRAM release and respawn) is a **desktop sign-off by Taco/PG**, reported separately; CI proves the pinned contract and the gate logic, not the GPU.

## Handoff order on shared files

| File | Chain (batch and 0242 as their specs read today, then 0246) | Notes |
| --- | --- | --- |
| `backend/app/inference/manager.py` | 0225-S3 → 0228-S2 → 0233 → 0242-T3 → 0242-T6 → D2 keep-warm → 0246-S3 | S3 adds only the guard. |
| `backend/app/inference/status_monitor.py` | 0230 (read-only) → 0242-T3 → D2 keep-warm → 0246-S3 | One additive live key. |
| `backend/app/inference/front_runtime.py` | 0230 → 0246-S3 | Guard only. |
| `backend/app/config.py` | 0228-S1 → 0228-S2 → 0245-S2 → 0233-S1 → 0246-S1 | `BlackGridSettings` fields only. |
| `backend/app/main.py` | 0225 → 0230 → 0233 → 0245 → 0246-S3 | Watcher start/stop only. |
| `backend/app/agent/tool_exposure.py` | 0232-S2 → 0233-S4 → 0246-S2 | `CAPABILITY_ALIASES` entries only. |
| `backend/app/agent/tool_retrieval.py` | 0232 → 0246-S2 | One `_SEARCH_TERMS` entry. |
| `backend/app/policy/reversibility.py`, `backend/app/tools/blackgrid_studio.py`, `backend/app/tools/exposure.py`, `backend/app/studio/*` (new files; `blackgrid_runtime.py` untouched), `backend/app/api/model.py` (S3 mapping, after 0242-T3/T6), `frontend/src/pages/Tools.tsx` (copy only) | 0246 only | No cited spec edits the first four or the last. |
| the keep-warm/idle-unload and Ollama `keep_alive` code (D2's PR; `gpu_prefer.py::ensure_ollama_gpu`, `ollama_runtime.py::ensure_local_ollama` today) | D2 keep-warm → 0246-S3 (one guard call, only if D2 did not already skip `bgm-ingest-9b`) | |
| `frontend/src/hud/HudModelSelector.tsx`, `modelMenuStatus.ts` | 0227-S3 → 0242-T2/T4/T6 → 0246-S4 | |
| `.github/workflows/pr-tests.yml` | every batch spec's step → 0246-S1 → S2 → S3 → S5 → S4 | Each ticket adds its own named step or file (S5's step is pytest only, no BGM checkout). |
| `docs/rfcs/README.md` | this PR adds one row; no ticket edits it | |

## Ticket cards

| Ticket | Model (fast mode off) | Depends | Backend CI | Frontend CI |
| --- | --- | --- | --- | --- |
| 0246-S1 | Grok 4.5 | gating 1, 2, 4 | BlackGrid Studio connector tests (RFC-0246); Run full backend suite | n/a |
| 0246-S2 | Grok 4.6 | S1; reviewer's no-live-caller confirmation | same + Run model and security regression tests | n/a |
| 0246-S3 | Grok 4.6 | S1, gating 3 | same | n/a |
| 0246-S4 | Composer 2.5 | S3 | n/a | Studio hold status tests (RFC-0246 S4); Build frontend; HUD model menu status tests (RFC-0244 restore) |
| 0246-S5 | Composer 2.5 | S1, BGM-P2 first response | BlackGrid Studio contract pin tests (RFC-0246 S5); live module skips with its explicit reason in CI | n/a |
| BGM-P1, BGM-P2 | PG's workers (BGM repo, stacked after BGM #34) | BGM #34 merged first | BGM `studio` CI job | n/a |

## Overall acceptance

- [ ] ANZU can list, create and edit studio projects and entities, upload a book and start ingest, read prompts, runs, takes and the movie status, and start generation, regenerate with remarks, approve and stitch, all through the existing `blackgrid_studio` tool and the existing approval gate (S1, S2).
- [ ] Starting a render, regenerating, stitching, ingesting, approving and deleting need a real `ApprovalGrant` bound to the exact target; reads and small edits do not (S2).
- [ ] The connector talks to loopback only, and a non-loopback URL is rejected by settings and by the client (S1).
- [ ] A paused run frees ANZU's hold exactly when BGM-P1 says `wan_loaded` is false; `bgm-ingest-9b` is never unloaded or given a `keep_alive` by ANZU (S3).
- [ ] The old ComfyUI actions leave the tool only in S2's PR, with working `studio_*` replacements and a reviewer-confirmed no-live-caller grep (S2).
- [ ] While a studio run holds the GPU, no ANZU model is loaded by any automatic path and explicit Load is refused with a reason; a run start unloads every ANZU-loaded model through the verified path or the ANZU-started run is refused; the next request respawns on demand (S3).
- [ ] Keep warm ON loses to the studio, then respawns the released seats once; `reflex_only` never loads or respawns (S3).
- [ ] The contract is proven in CI against the pinned `tests/fixtures/bgm/contract.json` and recorded endpoint fixtures (no studio, no BGM token in CI), and by a local live check on VRPC with an explicit skip reason when the studio is down (S1, S5).
- [ ] Real-GPU behaviour on Taco's PC is reported separately as a desktop sign-off (S5).

## Out of scope

Studio code (BGM-P1/P2 are BGM-repo PRs from PG's workers, reviewed by PG), studio auth (BGM-P3), remote or LAN exposure of the studio port, delivering movie bytes to the phone, retiring the ComfyUI sidecar **module**, workbench and routes (`blackgrid_runtime.py`, `api/blackgrid.py`, the modules catalog; only the tool's legacy actions are retired, in S2), project delete and bulk entity proposals (neither exists in v1), model routing policy, Astra-owned systems (personas, WebGL, presence), and the RFC-0242/0244 semantics other than the studio-hold interaction stated here.

## Risks

- **BGM is still moving.** #33 and #34 are stacked and open, and P1/P2 stack after #34. Mitigation: the gate, the re-trace at assignment, the contract-check items, recorded fixtures and the pinned contract (which PG refreshes); a drift fails a named test and is fixed in an amendment, not worked around.
- **BGM-P1's final shape is PG's.** Only `wan_loaded`, `active_run`, `paused` and `vram_mb` are fixed; `ingest_llm` and `stitch_uses_gpu` are proposed. If PG's PR differs, only S3's parser, S1's model and the pinned fixture change; the rule "the gate reads one studio answer, keyed on `wan_loaded` and `active_run`, never on run state alone" stays.
- **Owner-loaded models keep VRAM.** Taco's LM Studio 9B is not ANZU-loaded, so ANZU will not unload it (PG ruling 3). The studio does not use it. The hold text says so and offers the existing explicit Unload.
- **Studio hangs while up.** `unknown` defers automatic loads rather than risk the render; explicit owner Load is never blocked by `unknown`, so the owner always has a way out.
- **#686 and D2 names are not final.** The amendment on #686 proposes `keep_warm`, `idle_unload_seconds` and the `keep_alive` values and leaves final names to D2's PR; T3's `inference/model_release.py` has not landed. S3 uses the amendment's names by section and re-traces them when T3 and D2's PR land (gating item 3).
- **Shared Ollama.** `bgm-ingest-9b` lives in the same Ollama ANZU may use. `StudioModelGuard` matches by P1's endpoint and model and by the constant name, so a P1 outage cannot make ANZU's idle unload or `keep_alive` touch it. If D2's path enumerates `/api/ps` generically, S3's guard call is the fix and `test_gate_and_keep_warm_idle_unload_both_skip_bgm_ingest_9b` is the proof.
- **Approval fatigue.** Approve-take is gated by design; if Taco wants "approve all ready takes" as one grant, that is an amendment with a bulk target, not a gate bypass.

## Resolved questions (PG, 2026-11-03, relayed by Chief of Staff)

All eight were answered; each row is folded into the sections named.

| # | Question | Resolution |
| --- | --- | --- |
| Q1 | BGM-P1 and BGM-P2 as proposed; is a paused `generate` run's Wan still resident (C5)? | **Resolved (PG, 2026-11-03):** BGM-P1 `GET /api/gpu/status` and BGM-P2 `GET /api/contract` land as BGM PRs from PG's workers, stacked after BGM #34. A paused run still holds Wan today, so paused counts as busy. P1 reports `wan_loaded`, `active_run`, `paused` and `vram_mb`. The gate keys on `wan_loaded` and `active_run`, not on run state alone, so when a later Pause releases Wan ANZU frees the hold automatically (§1 busy rule, §4, S3 test `test_paused_with_wan_loaded_false_frees_the_hold_automatically`). |
| Q2 | Do ingest or stitch hold the GPU (C6)? | **Resolved (PG, 2026-11-03):** ingest's LLM is `bgm-ingest-9b` in Ollama (not LM Studio); ingest counts as busy only while that model is loaded, and P1 exposes it (`ingest_llm`). Stitch is CPU ffmpeg (libx264) and never holds the GPU; P1 states this (`stitch_uses_gpu: false`). Tests `test_ingest_is_busy_only_while_bgm_ingest_9b_is_loaded`, `test_stitch_run_never_holds_the_gpu` (§1, §4, S3). |
| Q3 | Shared LM Studio model; may ANZU unload owner-loaded models? | **Resolved (PG, 2026-11-03):** owner-loaded models are left alone and the hold message is shown. The studio does not use ANZU's 9B. P1 exposes the studio's LLM endpoint and model so the gate can tell them apart. ANZU never unloads or sets `keep_alive` on `bgm-ingest-9b`; the keep-warm/idle-unload path and the studio gate both skip it (test `test_gate_and_keep_warm_idle_unload_both_skip_bgm_ingest_9b`), matching CoS's keep-warm ruling to D2 (§4, S3). |
| Q4 | BGM auth before any non-loopback use? | **Resolved (PG, 2026-11-03):** there is no BGM auth. Token auth is required before any non-loopback use, so the connector stays loopback only and remote use goes through ANZU's auth (§5, S1 guard). |
| Q5 | Is BGM `main` readable by CI? | **Resolved (PG, 2026-11-03):** no cross-repo live CI. S5 is a pinned contract fixture fetched from `/api/contract`, committed at `tests/fixtures/bgm/contract.json`; PG refreshes it; CI runs the conformance tests against it. The live-loopback test runs locally on VRPC only (`BGM_BASE_URL=http://127.0.0.1:8745 BGM_LIVE_MUTATE=1 python -m pytest -q -rs tests/test_rfc0246_bgm_live.py`) with an explicit skip reason. `BGM_LIVE_REQUIRED` and any BGM read token are removed (S5). S5 is unblocked; its first fixture waits for P2. |
| Q6 | Retire the ComfyUI actions on `blackgrid_studio`? | **Resolved (PG, 2026-11-03):** retire them only in the same PR that adds working `studio_*` replacements (S2), after the reviewer confirms nothing live calls them; never delete them first. S2 acceptance criterion with the static test `test_no_live_caller_of_legacy_comfy_actions` (§3, S2). |
| Q7 | Project delete or bulk entity proposals? | **Resolved (PG, 2026-11-03):** v1 has neither. Proposals are single only, and user edits win over ANZU proposals (test `test_user_edited_fields_win_over_anzu_edits_and_proposals`) (§3, S2). |
| Q8 | Absolute movie path or a studio-dir setting? | **Resolved (PG, 2026-11-03):** BGM-P2 returns `abs_path` alongside `path`; ANZU uses it and there is no studio-directory setting (C12, S1 test `test_abs_path_is_reported_and_no_studio_dir_setting_exists`). |
