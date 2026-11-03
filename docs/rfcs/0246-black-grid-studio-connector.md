# RFC-0246: ANZU connector to Black Grid Multimedia Studio (one tool path, loopback only, GPU-aware)

**Status:** accepted (specs-only; **implementation is gated**, see *Gating*)
**Priority:** P2 (Taco's order with PG's approval, relayed by Chief of Staff 2026-11-03)
**Author:** Jarvis Architect
**Date:** 2026-11-03 (amended 2026-11-03: #686's keep-warm amendment is now present; S3 aligned with its proposed names)
**Traced on:** `development` @ `a62bd454` (every cited Jarvis symbol resolved there). Open PRs cited: #686 (RFC-0242; final head in this PR's body), #655 (RFC-0228; final head in this PR's body), #665 (RFC-0245; final head in this PR's body), #668 (RFC-0233; final head in this PR's body). Studio API read from Black Grid Multimedia (BGM) PRs #32, #33 and #34 (cited by endpoint path and symbol; final heads in this PR's body, as provenance only).

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md):
- §1: "Tell ANZU what you want. ANZU figures out how to accomplish it." The owner says "turn this book into a movie"; ANZU drives the studio instead of the owner learning its screens.
- §5 and §17: "A new specialist pack should extend ANZU. It should not fragment the experience into another application." The studio becomes a specialist capability reached through ANZU's one tool path (Aegir, media).
- §7: "ANZU should eliminate unnecessary approvals without eliminating meaningful control." Reads and small edits just happen; starting a long GPU render, regenerating, stitching, ingesting a book and deleting need the owner's real approval.
- §8: "Confidence should come from evidence rather than cheerful completion messages." A run is reported finished only from the studio's own run and readiness records.
- §9: "ANZU chooses infrastructure." ANZU frees the GPU for a render and takes it back afterwards; the owner never manages VRAM by hand.
- §16: "multimedia workers" are named in the Away Mode roadmap.

**Extends (do not rewrite):**
- [RFC-0096](0096-comfyui-sana-blackgrid-media-gen.md) / [RFC-0097](0097-opencut-openmontage-hyperframes-blackgrid-stitch.md): the BlackGrid media connector idea. The landed `blackgrid_studio` tool (ComfyUI / HR Endless sidecar) is kept unchanged and gains the studio actions defined here.
- [RFC-0031](0031-reversibility-first-action-gates.md) and [RFC-0110](0110-chatgpt-style-approval-popup.md): the action gate, `ApprovalGrant` and the approval popup. This RFC adds no confirmation mechanism of its own.
- [RFC-0244](0244-three-engine-modes.md): engine modes.
- #686 (RFC-0242; final head in this PR's body): its section "Amendment: Keep warm toggle and 5-minute idle unload" (present on #686) and its T3 verified native release (`inference/model_release.py`, **not yet landed**) and T6 explicit owner Load.
- D2's Taco-owned keep-warm ticket. The amendment proposes `keep_warm` (default `false`) and `idle_unload_seconds` (default `300`) on `InferenceSettings`, with Ollama `keep_alive` `"300s"` when off and `"-1"` when on, and says **D2's PR sets the final names, files and test paths**. No D2 PR is open yet; its number is added to this PR's body and to *Gating* when it opens, and any name difference is a one-line edit here.

**Astra boundary:** persona, WebGL, presence, morph and appearance are out of scope (Astra). This RFC edits no persona or presence component. The only UI is one additive status line (S4).

This PR is **specs-only**. It contains no application code.

---

## Gating (read first)

Nothing in S1-S5 starts until **all** of these hold:

1. BGM PRs #32, #33 and #34 are **merged to BGM `main`**. #33 and #34 are stacked (their bases are the previous slice's branch), so today the endpoints below exist only on those branches.
2. The studio-side PRs **BGM-P1** (`GET /api/gpu/status`) and **BGM-P2** (`GET /api/contract`) are merged to BGM `main` (see *Studio-side changes*). The GPU gate reads BGM-P1 and nothing else.
3. #686's T3 (`inference/model_release.py`, not yet landed) and its section "Amendment: Keep warm toggle and 5-minute idle unload" are on `development`, and D2's keep-warm PR (which sets the final names of `keep_warm` and `idle_unload_seconds`) has landed. S3 calls T3's release and the keep-warm setting, and re-traces their final names at assignment.
4. PG tells Chief of Staff the contract is final, and Chief of Staff assigns the tickets.

At assignment each ticket's first step is the **contract re-trace**: re-read every endpoint in *Studio contract* on BGM `main`, resolve each *contract-check item* (C1-C12), and record fixtures (S1). A difference is fixed in an amendment to this RFC before code is written. The studio is PG's repo and PG owns its contract; this RFC follows it and never edits it.

## Problem

Verified on `development` @ `a62bd454`.

1. **Only the old studio is reachable.** `tools/blackgrid_studio.py::BlackGridStudioTool` drives a local ComfyUI HR Endless sampler through `studio/blackgrid_runtime.py` (port 8188, `BlackGridSettings` in `config.py`). It cannot reach the new Black Grid Multimedia Studio (local FastAPI on `127.0.0.1:8745`), which has a story bible, durable pipeline runs, streaming book ingest, Wan2.2 clip generation, review and a final stitch (BGM #32-#34).
2. **The tool is nearly unreachable in the live path.** The live loop uses `agent/tool_exposure.py` (`tool_names_for`, `schemas_for`). Its `CLASS_TOOLS` and `CAPABILITY_ALIASES` do not mention `blackgrid_studio`, and `agent/tool_retrieval.py::_SEARCH_TERMS` has no entry for it. Only the older `tools/exposure.py::TASK_TOOL_SETS` lists it (used by `agent/local_harness.py`). In practice the model reaches it only by calling `request_tools` with the exact name.
3. **No policy for studio actions.** `policy/reversibility.py::resolve_action_effect` knows nothing about `blackgrid_studio`, so every action falls into the generic medium-risk path. A multi-hour render and a read look the same to the gate.
4. **ANZU and the studio fight for 16 GB.** The studio's Wan2.2 clip runs need almost all of a 16 GB card. ANZU's models (front and worker seats, LM Studio or llama.cpp instances loaded by ANZU) stay resident, and nothing on `development` checks whether another application is rendering before `InferenceManager.load` or `FrontRuntime.ensure_started` loads a model. The first symptom is a CUDA out-of-memory error halfway through a long render.
5. **The studio cannot say "the GPU is busy".** At the traced heads there is no endpoint that reports it. Runs are listed **per project** (`GET /api/projects/{project_id}/pipeline/runs`), and the legacy JSON-clip flow's jobs (`GET /api/jobs/{job_id}`, kinds `generate`, `video`, `image`, `stitch`) have no list endpoint at all, so a connector cannot know whether anything holds the GPU without walking every project and still missing legacy jobs. That is a studio-side gap (BGM-P1).

## Decision

Ship **one RFC with five implement slices (S1-S5)**, one named model per slice, fast mode off, plus **two studio-side PRs** that belong to the BGM repo and PG's review.

```
owner / model turn ─► agent/tool_exposure.py (alias + retrieval, S2) ─► ToolRegistry.execute("blackgrid_studio", action="studio_*")
        │                                   │
        │                                   ├─ gate: policy.reversibility.resolve_action_effect (new branch, S2) ─► ApprovalGrant for expensive/destructive actions (RFC-0031/0110)
        │                                   └─ BgmClient (S1, loopback only, fixtures-conformant) ─► http://127.0.0.1:8745/api/...
        │
        └─ before ANZU loads ANY model: StudioGpuGate.check (S3) ─► BGM-P1 GET /api/gpu/status
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
| **Studio hold** | The state in which ANZU has no ANZU-loaded model resident and loads none because BGM-P1 says the GPU is busy. |
| **ANZU-loaded model** | A model ANZU started or loaded itself (front/worker seats, ANZU-managed llama.cpp, LM Studio or Ollama instances ANZU loaded). Models the owner loaded in another program are not ANZU-loaded. This is the same boundary RFC-0244, RFC-0228 and RFC-0245 use. |

## 1. Studio contract (what ANZU calls)

Base `http://127.0.0.1:8745`, every route under `/api` (`APIRouter(prefix="/api")` in `studio/backend/main.py`). Schemas are the Pydantic models named in the *defined in* column; ANZU mirrors them as its own Pydantic models in `studio/bgm_models.py` and validates every response with them (S1). Paths use `{pid}` for the string project id and integer ids elsewhere.

| Endpoint | Defined in (BGM symbol; PR) | Request → response | Tool action (class, see §3) |
| --- | --- | --- | --- |
| `GET /api/health` | `main.py::health` (#32 base) | → `{"ok": true}` | `studio_status` (read) |
| `GET /api/contract` | **BGM-P2 (new)** | → `{"contract_version": 1, "stages": [...]}` | `studio_status` (read) |
| `GET /api/gpu/status` | **BGM-P1 (new)** | → `GpuStatus` (below) | `studio_status`, gate (read) |
| `GET /api/projects`, `POST /api/projects` | `main.py::list_projects`, `create_project` | → `list[ProjectSummary]`; `CreateProjectBody{title?}` → `ProjectOut` | `studio_projects` (read), `studio_create_project` (write) |
| `GET /api/projects/{pid}` | `main.py::get_project` | → `ProjectOut` | `studio_projects` (read) |
| `GET /api/projects/{pid}/bible` | `bible_api.py::get_bible` (#32) | → `BibleSummaryOut{bible_version, entity_counts, prompt_counts}` | `studio_bible` (read) |
| `GET/POST /api/projects/{pid}/entities`, `GET/PATCH/DELETE .../entities/{eid}` | `bible_api.py::list_entities`, `create_entity`, `get_entity`, `patch_entity`, `delete_entity` (#32) | `EntityCreate{kind, name, summary?, description?, appearance?, notes?}`, `EntityPatch{... , voice?}` → `EntityOut` (kinds `character`, `place`, `poi`; `voice{instruct, language, temperature, seed}`) | `studio_bible` (read), `studio_entity` (write), `studio_delete_entity` (destructive) |
| `GET /api/projects/{pid}/entity-proposals`, `POST .../{id}/accept\|dismiss` | `bible_api.py::list_proposals`, `accept_proposal`, `dismiss_proposal` (#33) | → `ProposalOut` | `studio_bible` (read); accept/dismiss are **not** exposed (owner review in the studio UI, §3) |
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

`GpuStatus` (BGM-P1, proposed; PG owns the final shape): `{"contract_version": 1, "busy": bool, "checked_at": iso, "holders": [{"kind": "pipeline_run", "project_id", "run_id", "stage", "status": "running|paused", "models_resident": bool, "cursor", "total"} | {"kind": "job", "job_id", "project_id", "job_kind": "generate|video|image", "status": "queued|running"}]}`. `busy` is true while any holder runs a GPU step or keeps GPU models resident. **ANZU's gate reads only `busy` and `holders`.** It never infers GPU state from run status.

**Stage rules the connector relies on** (from `GenerateStage` / `StitchStage` / `PipelineRunner`):
- `generate` renders with Wan2.2 TI2V-5B when `GenerationConfig.video_backend == "wan"` (default) and is the only stage that holds the GPU for minutes at a time. `video_backend == "ffmpeg"` is the no-GPU fallback. `ingest` uses the studio's configured LLM (`Settings.llm_base_url`, default LM Studio `127.0.0.1:1234`), not the GPU directly. `stitch` is ffmpeg (C6).
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
| C5 | `pause_run` finishes the in-flight step (and saves it) before the run stays paused (as the #32 text says). **Whether a paused `generate` run still holds Wan weights is unknown**; BGM-P1's `models_resident` is the answer. | If BGM-P1 cannot say, the gate treats `paused` as busy (conservative). |
| C6 | `stitch` uses CPU ffmpeg only (no NVENC) and `ingest` uses only the HTTP LLM, so neither holds the GPU. | If either does, BGM-P1 lists them as holders and the gate needs no change. |
| C7 | The legacy `POST /api/projects/{pid}/stitch` stays a separate JSON-flow route. | If retired, nothing changes. |
| C8 | `approve_prompt` (pre-generation text review) and `approve_current_take` (post-render review) are the two review approvals; `PromptPatch.status` is not used by the connector. | Mapping changes. |
| C9 | `RunOut.status` values are exactly `running`, `paused`, `completed`, `failed`. | `studio_runs` normaliser changes; a new value fails loudly (unknown status). |
| C10 | `GenerationConfig.video_backend` is `wan` or `ffmpeg`, and `PUT /api/generation/config` is a partial update. | The config summary shown in approvals changes. |
| C11 | The studio has no delete-project route. | A project delete is added only by a later amendment. |
| C12 | A movie's file is reachable on the PC's disk under the BGM `projects/<pid>/final/movie.mp4` path (`MovieOut.path` is relative). ANZU reports the relative path; it never guesses an absolute one. | Path reporting changes. |

## 2. The connector client (S1)

`backend/app/studio/bgm_client.py::BgmClient` is the only code that talks to the studio.

- **Loopback only, enforced twice.** `config.BlackGridSettings` gains `studio_api_enabled: bool = False`, `studio_api_url: str = "http://127.0.0.1:8745"`, and a Pydantic validator that rejects anything else. `BgmClient.__init__` re-validates, so a settings file edited by hand cannot bypass it. Accepted hosts are exactly `127.0.0.1`, `::1` and `localhost` (normalised to `127.0.0.1`), scheme `http` only, no userinfo, no path other than empty or `/`. It deliberately does **not** reuse `tools/safety.py::is_owner_local_host`, which also accepts RFC1918 and `.local` hosts.
- **No detours.** `httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=...)`, so a proxy variable or a redirect cannot carry a call off the loopback interface. A 3xx answer is an error.
- **Timeouts.** Read calls 5 s, writes 15 s, the upload streams the file in 1 MiB blocks with a 300 s total. Studio steps run on the studio's own thread, so these calls never wait for a render.
- **Studio not running is a result, not an exception.** Connection refused (and only that) returns `StudioNotRunning` and the tool answers `{"studio": "not_running", "detail": "Black Grid Multimedia Studio is not running on 127.0.0.1:8745. Start it from its folder (studio/start.ps1) and ask again."}`. Timeouts, 5xx and malformed bodies are different, named errors (`StudioTimeout`, `StudioError`, `StudioContractMismatch`) with the studio's own detail text.
- **Contract conformance.** Every response is parsed by the mirrored Pydantic models with `extra="ignore"` for new optional fields but **required fields missing or a wrong type raises `StudioContractMismatch("<endpoint>: <field>")`**; the tool shows it verbatim. `GET /api/contract` is read once per session: `contract_version` must be `1` (the version this RFC was written for), otherwise every action but `studio_status` answers "studio contract version N is not supported by this ANZU".
- **Recorded fixtures.** `scripts/record_bgm_fixtures.py` calls each endpoint of §1 against a running BGM `main` (on a temp data directory) and writes `tests/fixtures/bgm/<endpoint-slug>.json` plus `tests/fixtures/bgm/manifest.json` (endpoint, method, BGM `main` description, recorded date). The conformance test replays them, so CI needs no studio for it.
- **Files stay in ANZU's policy.** `studio_upload_source` takes an absolute path that must resolve through `tools/safety.py::resolve_allowed_path` against `live_allowed_directories(...)` (the same allow-list the filesystem tool uses), and the extension is checked before any byte is read.

## 3. One tool, extra actions, ANZU's own approval pattern (S2)

`tools/blackgrid_studio.py::BlackGridStudioTool` keeps its legacy actions (`open_workbench`, `open_comfy`, `status`, `install`, `start`, `submit_hr_endless`, `list_outputs`) **byte for byte** and adds the `studio_*` actions of §1. The model sees them through the same `parameters` schema (`action` enum plus `project_id`, `entity`, `prompt_id`, `run_id`, `remarks`, `path`, `config` fields). The legacy ComfyUI sidecar is **not** retired here (open question Q6).

**Reachability fix (live path).** S2 adds, in `agent/tool_exposure.py::CAPABILITY_ALIASES`, the aliases `blackgrid`, `black grid`, `studio`, `multimedia_studio` → `blackgrid_studio`; and in `agent/tool_retrieval.py::_SEARCH_TERMS` an entry `blackgrid_studio` with distinctive terms (`black grid`, `blackgrid`, `story bible`, `movie from`, `book to video`, `video prompts`, `stitch the movie`). Generic words such as "video" or "studio" alone do not retrieve it (the module's own rule against catalog bloat).

**Approval: the existing pattern, no new one.** Mutating actions go through `policy/reversibility_gate.py::evaluate_side_effect` and `ApprovalGrant` (`policy/approval_grant.py`: `park_approval_request`, `decide_approval_request`, `validate_grant_for_action`, `consume_grant`) with the RFC-0110 approval popup. A model's `confirmed=true` never counts (`model_attempted_self_confirm`). S2 adds one branch to `policy/reversibility.py::resolve_action_effect` for tool `blackgrid_studio` and actions starting `studio_` (legacy actions fall through unchanged). The branch is synchronous and makes **no network call**: it uses only the tool arguments.

| Class | Actions | Effect metadata |
| --- | --- | --- |
| Read | `studio_status`, `studio_projects`, `studio_bible`, `studio_prompts`, `studio_runs`, `studio_config`, `studio_takes`, `studio_movie` | `REVERSIBLE`, not side-effecting. No grant. |
| Small write | `studio_create_project`, `studio_entity`, `studio_upload_source`, `studio_run_control` with `pause`, `studio_set_config` | `COMPENSATABLE`, not high-consequence. Normal autonomy applies; no grant at the default level. `studio_set_config` returns the previous config in its result so the owner can undo it. |
| **Expensive** | `studio_start_generation`, `studio_regenerate`, `studio_start_stitch`, `studio_start_ingest`, `studio_run_control` with `resume` (the gate branch is synchronous and cannot look up the run's stage, so every resume is gated) | `UNKNOWN`, `high_consequence=True`. **`ApprovalGrant` required.** Target: `bgm:<pid>:<action>:<scope>` where scope is `all` / `missing` / `prompt:<id>#<sha8 of remarks>` / `source:<id>`. The grant binds the exact target, so approving "regenerate prompt 7 with these remarks" cannot be spent on other remarks. The popup text states the project, how many clips will render, the video backend and resolution (from the last `studio_config` read) and that **ANZU will unload its models while the studio renders**. |
| **Review decisions** | `studio_review_prompt`, `studio_approve_take` | `UNKNOWN`, `high_consequence=True`. **Grant required.** ANZU never approves a prompt or a take on its own authority; approval is the owner's creative gate before the stitch. |
| **Destructive** | `studio_delete_entity` | `IRREVERSIBLE`. Grant required. |

Not exposed on purpose: accepting or dismissing entity proposals (`.../entity-proposals/{id}/accept|dismiss`), deleting prompts, entity image upload and delete, reorder. They stay owner actions in the studio UI until a later amendment proves the need.

**Engine modes (RFC-0244).** The tool is an agent tool, so it is reachable only through the agent loop, which under `reflex_only` stops at `engine_mode.model_enabled(settings)` before any tool call (`agent/loop.py` `_run`). `reflex_only` therefore cannot call a studio action, and S2 changes no mode logic. `model_only` and `hybrid` expose it identically. A `reflex_only` owner who asks for the studio gets the existing `reflex_only_reply` text and no work runs.

## 4. The GPU gate (S3)

`backend/app/studio/gpu_gate.py::StudioGpuGate` is the only new moving part.

**What it reads.** `BgmClient.gpu_status()` (BGM-P1). Result classes: `free` (200, `busy=false`), `busy` (200, `busy=true`), `not_running` (connection refused), `unknown` (timeout, 5xx, malformed, contract mismatch). It never reads project run lists.

**Where it checks.** Exactly the two places ANZU starts a model, so there is no parallel load path:
- `inference/manager.py::InferenceManager.load` and `_load_locked` (covers the worker seat, LM Studio, Ollama and managed llama.cpp loads that go through `MANAGER.load`),
- `inference/front_runtime.py::FrontRuntime.ensure_started` and `_start_local` (the front responder).

A static test classifies every `MANAGER.load(` call site (the same table and test as #686 T3 uses; S3 adds a column) so a new load path cannot appear unguarded.

| Situation | Automatic load (chat turn, startup restore, `RUNNING_MODELS` autoload, keep-warm respawn) | Explicit owner Load (#686 T6 routes) |
| --- | --- | --- |
| `free` or `not_running` | proceeds as today | proceeds as today |
| `busy` | **deferred**: raises `StudioGpuBusy(RuntimeError)` with the reason text below; autoload branches that #686 already skips silently skip silently | **refused**: `POST /api/model/load` and the activate routes answer 409 with the same text; the owner can pause the run (`studio_run_control`) or wait. No silent override. |
| `unknown` | deferred with "Studio status could not be read; ANZU is waiting rather than risk the render." | **allowed** (only a confirmed busy status blocks an explicit owner action) |

Reason text (fixed, tested): `BlackGrid Studio is rendering (project "<title>", clip <cursor>/<total>). ANZU's models stay unloaded so the render keeps the GPU. Ask again when it finishes, or pause the run.` Jev and Laya are CPU deciders and keep answering reflex turns during a hold; only generative turns see the reason.

**Unload on run start.** Two triggers, one action:
- *Started through ANZU:* `studio_start_generation` / `studio_regenerate` / a `resume` of a `generate` run (the tool reads the run's stage at execution time; resuming an ingest run releases nothing), after the grant and **before** the `POST`, calls the verified release of #686 T3 for **every ANZU-loaded model, front seat included** (`reason="studio_run"`). If the release is not verified (T3's own 409/502 result) or ANZU is mid-answer (`MANAGER._request_lease.exclusive()` not acquired), **the studio run is not started** and the tool says why. Nothing is half-started.
- *Started from the studio's own UI:* a watcher polls BGM-P1 every `STUDIO_WATCH_INTERVAL_S = 10` while any ANZU-loaded model is resident, backs off to `STUDIO_WATCH_BACKOFF_S = 60` while the studio is `not_running`, and polls nothing when no ANZU-loaded model is resident and no hold is active. On `free → busy` it runs the same verified release.

The release uses the **verified native path** only (LM Studio `loaded_instances` check, Ollama `/api/ps` check, managed process stop; #686 T3). A studio hold **does not** set `manually_unloaded` (that flag means "stays unloaded until explicit Load" and belongs to an owner Unload, as the amendment's composition table says), and it is **not** recorded as an idle unload (`engine_coexistence.idle_unloaded()` of RFC-0228); it is its own reason, `studio_hold`, reported only after the same verified evidence (R5). A hold clears itself. When an idle unload already released the models, run start finds nothing resident, releases nothing and still holds. Models the owner loaded in another program (Taco's default LM Studio 9B) are **not** ANZU-loaded and stay under the amendment's rule (the RFC-0225 and RFC-0228 managed-mode rule; this RFC does not widen consent): ANZU leaves them running, and the hold text adds `LM Studio's model "<id>" is still resident because you loaded it; unload it from the model menu to give the render the whole GPU.` using the existing explicit Unload (RFC-0244 inventory is read-only; ANZU stops no other program).

**Respawn after the run.** The watcher's next poll sees `busy=false` (or `not_running`, which includes a studio crash) and clears the hold, publishes the cleared state, and does **nothing else**. The next request loads on demand through the normal path. With **Keep warm ON** (`keep_warm` true in the amendment's proposed names) the gate asks for **one** respawn of exactly the seats it released, through RFC-0225 `prepare_engine_for`, the same call the amendment's on-demand respawn uses, never a private loader; ANZU-originated Ollama warms after it use the amendment's `keep_alive` rule (`"-1"` when on, `f"{idle_unload_seconds}s"` when off). With Keep warm OFF (default, `idle_unload_seconds` 300) there is no preload and the normal idle timer applies to whatever loads next. D2's PR sets the final names; S3 follows them.

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
- **Remote use goes through ANZU's existing auth.** A phone or LAN companion reaches the studio only by sending an ANZU task or chat turn. That request is authenticated by `auth.authenticate_request` / `require_owner_private_key` (the owner private key; loopback is the owner console, LAN/companion callers need the key) and by the computer-permission checks, exactly like every other tool. The studio's own port is never published. If BGM later adds auth, the connector sends a configured key header; **this RFC adds no auth code** because the studio has none today (open question Q4).
- No studio credential is stored by ANZU in this RFC. If BGM-P3 (future) adds an API key, it goes in the vault (`vault` / `get_effective_private_key` pattern), never in `settings.json`.

## 6. Studio-side changes (BGM-repo PRs, reviewed by PG; ANZU never pushes to `bgm/*`)

| PR | Change | Why | Needed by |
| --- | --- | --- | --- |
| **BGM-P1** | `GET /api/gpu/status` → `GpuStatus` (§1): `busy`, `holders` covering **pipeline runs and legacy jobs**, `models_resident` per holder | One truthful answer to "does the studio hold the GPU"; today runs are per project and legacy jobs have no list | S3 |
| **BGM-P2** | `GET /api/contract` → `{contract_version, stages}` (or the same keys folded into `/api/health`) | Version check and drift detection | S1 |
| BGM-P3 (future, **not** an ANZU ticket) | API-key header auth | Only when the studio is ever exposed beyond loopback | none |
| BGM-P4 (optional) | Release Wan weights when a `generate` run pauses (C5) | Frees the GPU for ANZU during long pauses | none; BGM-P1's `models_resident` reports whatever BGM does |

## 7. Live-UI add-alongside reasoning pass (2026-10-14 standing order)

The only UI change is one status line in the model dropdown's status area (`frontend/src/hud/modelMenuStatus.ts`, rendered by `HudModelSelector.tsx`), shown **only** while `studio_hold.active`.

| Existing element | What S4 does | Reasoning |
| --- | --- | --- |
| Trigger button, "Serving now", Load, Unload, More, engine-mode control | unchanged | The line is additive and absent in the common case, so the menu looks the same. |
| Load button during a hold | stays enabled; the 409 text from §4 shows in the existing error line | No silently dead control (R7 of #686). |
| Persona, WebGL, presence, chat bubbles | untouched | Astra-owned. |

No `[hidden]`, `display: none` or removal of any element is introduced; new CSS is additive in `frontend/src/hud/nodeModels.css`. Live audit (recorded in the S4 PR, numbers not invented in advance): on Taco's PC at 390 px and 1366 px the line wraps without overflow and `Escape` still closes the menu.

## Slices (one ticket each, fast mode off, lane assigned by Chief of Staff at the gate)

Ticket order: **S1 → S2, S3 (parallel after S1) → S4 (after S3) → S5 (last)**. Every ticket starts with the contract re-trace (*Gating*).

### S1: Client, settings, loopback guard, fixtures and conformance
**Model:** Grok 4.5 (fast mode off). **Depends:** gating items 1, 2, 4.
**Owns:** `backend/app/studio/bgm_client.py` (new), `backend/app/studio/bgm_models.py` (new), `backend/app/config.py` (`BlackGridSettings` fields only, after every earlier chain), `scripts/record_bgm_fixtures.py` (new), `tests/fixtures/bgm/*.json` and `manifest.json` (new), `tests/test_rfc0246_bgm_client.py`, `tests/test_rfc0246_bgm_contract.py`, `.github/workflows/pr-tests.yml` (new step only).
**Tests (named):**
- `tests/test_rfc0246_bgm_client.py`: `test_base_url_rejects_non_loopback` (parametrised: `0.0.0.0`, `192.168.1.20`, `10.0.0.5`, `studio.local`, `example.com`, `http://127.0.0.1@evil.example`, `https://127.0.0.1:8745`), `test_lan_address_accepted_by_is_owner_local_host_is_rejected_here`, `test_localhost_and_ipv6_loopback_accepted_and_normalised`, `test_settings_validator_rejects_remote_url`, `test_hand_edited_settings_cannot_bypass_client_check`, `test_redirect_is_not_followed`, `test_proxy_environment_is_ignored`, `test_connection_refused_returns_studio_not_running_result`, `test_timeout_5xx_and_malformed_are_distinct_errors`, `test_http_409_404_400_422_map_to_named_errors_with_studio_detail`, `test_upload_streams_in_blocks_and_enforces_allowed_directories_and_extension`, `test_contract_version_other_than_1_refuses_all_but_status`.
- `tests/test_rfc0246_bgm_contract.py`: `test_manifest_covers_every_endpoint_in_the_client_registry`, `test_every_recorded_fixture_parses_with_the_mirrored_models`, `test_missing_required_field_raises_studio_contract_mismatch`, `test_extra_optional_fields_are_ignored`, `test_unknown_run_status_fails_loudly` (C9).
**CI step:** new `pytest` job step `BlackGrid Studio connector tests (RFC-0246)` running `python -m pytest -q -rs tests/test_rfc0246_bgm_client.py tests/test_rfc0246_bgm_contract.py`, and the existing `Run full backend suite`.
**Acceptance:**
- [ ] A non-loopback URL is rejected at settings validation and at client construction.
- [ ] Studio not running yields the clear result above and never an exception to the user.
- [ ] Every endpoint of §1 has a recorded fixture and a parsing test, and contract drift names the endpoint and field.
- [ ] No studio call is made while `studio_api_enabled` is false.

### S2: Tool actions, policy branch, exposure
**Model:** Grok 4.6 (fast mode off). **Depends:** S1.
**Owns:** `backend/app/tools/blackgrid_studio.py` (actions added; legacy actions untouched), `backend/app/policy/reversibility.py` (`resolve_action_effect` branch only), `backend/app/agent/tool_exposure.py` (`CAPABILITY_ALIASES` only), `backend/app/agent/tool_retrieval.py` (`_SEARCH_TERMS` entry only), `tests/test_rfc0246_bgm_tool.py`, `.github/workflows/pr-tests.yml` (add the file to S1's step).
**Tests (named):** `tests/test_rfc0246_bgm_tool.py`: `test_studio_actions_live_on_the_existing_tool_not_a_new_one`, `test_legacy_actions_unchanged_byte_for_byte`, `test_every_action_in_the_schema_has_an_effect_class` (static), `test_read_actions_need_no_grant`, `test_start_generation_requires_approval_grant`, `test_regenerate_grant_binds_the_remarks_digest`, `test_start_stitch_requires_grant`, `test_start_ingest_requires_grant`, `test_every_resume_requires_grant_but_pause_does_not`, `test_review_prompt_and_approve_take_require_grant`, `test_delete_entity_requires_grant`, `test_model_self_confirm_never_satisfies_the_gate`, `test_gate_branch_makes_no_network_call`, `test_studio_not_running_is_a_clear_tool_result`, `test_studio_prompt_retrieves_the_tool_on_the_live_path` (`tool_names_for`), `test_generic_video_prompt_does_not_retrieve_it`, `test_reflex_only_turn_never_calls_a_studio_action`, `test_model_only_and_hybrid_expose_the_tool`, `test_stitch_action_uses_the_pipeline_stage_not_the_legacy_route` (C7).
**CI step:** `BlackGrid Studio connector tests (RFC-0246)` plus `Run model and security regression tests` (it already runs `tests/test_tool_exposure.py`, which S2 must keep green).
**Acceptance:**
- [ ] Every action of §1 is reachable through `ToolRegistry.execute` and returns a structured result (`ToolResult.data`).
- [ ] Expensive, review and destructive actions cannot run without a real `ApprovalGrant`, and the grant is bound to the exact target.
- [ ] A studio prompt retrieves the tool in the live loop; unrelated prompts do not.
- [ ] No new tool class, no MCP server and no confirmation mechanism is added.

### S3: GPU gate, unload on run start, respawn after the run
**Model:** Grok 4.6 (fast mode off). **Depends:** S1, gating items 2 and 3.
**Owns:** `backend/app/studio/gpu_gate.py` (new), `backend/app/inference/manager.py` (the guard in `load` / `_load_locked` only, after #686 T3/T6 and D2's keep-warm ticket), `backend/app/inference/front_runtime.py` (the guard in `ensure_started` / `_start_local`, after every earlier chain), `backend/app/inference/status_monitor.py` (the `studio_hold` key only, after #686 T3), `backend/app/main.py` (lifespan start and stop of the watcher only), `backend/app/api/model.py` (409 mapping for `StudioGpuBusy` on the explicit Load routes only), `tests/test_rfc0246_studio_gpu_gate.py`, `.github/workflows/pr-tests.yml` (add the file to the step).
**Tests (named):** `tests/test_rfc0246_studio_gpu_gate.py`: `test_load_deferred_while_run_active`, `test_front_runtime_start_deferred_while_run_active`, `test_unload_on_run_start_through_the_tool_before_the_post`, `test_unload_on_run_start_seen_by_the_watcher`, `test_run_not_started_when_release_is_unverified`, `test_run_not_started_while_a_request_is_in_flight`, `test_respawn_on_demand_after_run_ends`, `test_no_preload_after_run_when_keep_warm_off`, `test_keep_warm_on_studio_run_wins_and_unloads`, `test_keep_warm_on_respawns_released_seats_once_through_prepare_engine_for`, `test_hold_unload_is_not_recorded_as_idle_unload_or_manual_unload`, `test_run_start_with_nothing_resident_releases_nothing_and_still_holds`, `test_reflex_only_no_automatic_load_and_no_respawn`, `test_reflex_only_explicit_load_refused_while_busy`, `test_user_visible_reason_in_snapshot_and_in_the_deferred_turn`, `test_studio_not_running_never_blocks_a_load`, `test_unknown_status_blocks_automatic_load_but_not_explicit_load`, `test_studio_crash_clears_the_hold`, `test_owner_loaded_lm_studio_model_is_not_unloaded_and_the_notice_says_so`, `test_studio_hold_never_sets_manually_unloaded`, `test_watcher_backs_off_while_studio_not_running_and_stops_when_nothing_is_resident`, `test_gate_reads_only_gpu_status_not_run_lists`, `test_every_manager_load_site_is_classified_for_studio_hold` (static).
**CI step:** `BlackGrid Studio connector tests (RFC-0246)`, `Run model and security regression tests`, `Run full backend suite`.
**Acceptance:**
- [ ] While BGM-P1 says busy, no ANZU model starts by any automatic path, and explicit Load answers 409 with the reason.
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

### S5: Live-loopback conformance, CI wiring and tool docs
**Model:** Composer 2.5 (fast mode off). **Depends:** S1, S2, S3.
**Owns:** `tests/test_rfc0246_bgm_live.py`, `scripts/run_bgm_live_ci.py`, `.github/workflows/pr-tests.yml` (one step), `TOOLS.md` (the `blackgrid_studio` entry).
**Tests (named):** `tests/test_rfc0246_bgm_live.py`: `test_live_status_contract_and_gpu_status`, `test_live_project_entity_roundtrip` (mutating; runs only with `BGM_LIVE_MUTATE=1`), `test_live_run_pause_resume_status_on_ffmpeg_backend` (mutating), `test_live_responses_match_recorded_fixtures_shape`. Skip rule: the module skips **only** when `BGM_BASE_URL` (default `http://127.0.0.1:8745`) refuses connections **and** `BGM_LIVE_REQUIRED` is unset, with the skip reason "BlackGrid Studio is not running; live check not run"; the CI step sets `BGM_LIVE_REQUIRED=1`, so a missing studio there fails the job (no silent skip). On a developer PC the result is reported as "skipped: studio not running", never as passed.
**CI step:** `BlackGrid Studio live-loopback conformance (RFC-0246 S5)`: starts BGM `main` (pinned to the commit PG names at the gate, checked out with a read token if the repo is private, Q5) with `video_backend=ffmpeg` on a loopback port in a temp data directory, then runs `python -m pytest -q -rs tests/test_rfc0246_bgm_live.py` with `BGM_LIVE_REQUIRED=1` and `BGM_LIVE_MUTATE=1`.
**Acceptance:**
- [ ] The live check passes against a real BGM `main` in CI with no skip.
- [ ] `TOOLS.md` lists every action with its class and the gating rule.
- [ ] Installed-PC behaviour with real Wan2.2 (the actual VRAM release and respawn) is a **desktop sign-off by Taco/PG**, reported separately; CI proves the contract and the gate logic, not the GPU.

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
| `backend/app/policy/reversibility.py`, `backend/app/tools/blackgrid_studio.py`, `backend/app/studio/*` (new files), `backend/app/api/model.py` (S3 mapping, after 0242-T3/T6) | 0246 only | No cited spec edits the first three. |
| `frontend/src/hud/HudModelSelector.tsx`, `modelMenuStatus.ts` | 0227-S3 → 0242-T2/T4/T6 → 0246-S4 | |
| `.github/workflows/pr-tests.yml` | every batch spec's step → 0246-S1 → S2 → S3 → S4 → S5 | Each ticket adds its own named step or file. |
| `docs/rfcs/README.md` | this PR adds one row; no ticket edits it | |

## Ticket cards

| Ticket | Model (fast mode off) | Depends | Backend CI | Frontend CI |
| --- | --- | --- | --- | --- |
| 0246-S1 | Grok 4.5 | gating 1, 2, 4 | BlackGrid Studio connector tests (RFC-0246); Run full backend suite | n/a |
| 0246-S2 | Grok 4.6 | S1 | same + Run model and security regression tests | n/a |
| 0246-S3 | Grok 4.6 | S1, gating 3 | same | n/a |
| 0246-S4 | Composer 2.5 | S3 | n/a | Studio hold status tests (RFC-0246 S4); Build frontend; HUD model menu status tests (RFC-0244 restore) |
| 0246-S5 | Composer 2.5 | S1, S2, S3 | BlackGrid Studio live-loopback conformance (RFC-0246 S5) | n/a |
| BGM-P1, BGM-P2 | PG's choice (BGM repo) | none | BGM `studio` CI job | n/a |

## Overall acceptance

- [ ] ANZU can list, create and edit studio projects and entities, upload a book and start ingest, read prompts, runs, takes and the movie status, and start generation, regenerate with remarks, approve and stitch, all through the existing `blackgrid_studio` tool and the existing approval gate (S1, S2).
- [ ] Starting a render, regenerating, stitching, ingesting, approving and deleting need a real `ApprovalGrant` bound to the exact target; reads and small edits do not (S2).
- [ ] The connector talks to loopback only, and a non-loopback URL is rejected by settings and by the client (S1).
- [ ] While a studio run holds the GPU, no ANZU model is loaded by any automatic path and explicit Load is refused with a reason; a run start unloads every ANZU-loaded model through the verified path or the ANZU-started run is refused; the next request respawns on demand (S3).
- [ ] Keep warm ON loses to the studio, then respawns the released seats once; `reflex_only` never loads or respawns (S3).
- [ ] The contract is proven against recorded fixtures of merged BGM `main` and a live-loopback run that cannot skip in CI (S1, S5).
- [ ] Real-GPU behaviour on Taco's PC is reported separately as a desktop sign-off (S5).

## Out of scope

Studio code (BGM-P1/P2 are BGM-repo PRs reviewed by PG), studio auth, remote or LAN exposure of the studio port, delivering movie bytes to the phone, retiring the ComfyUI sidecar, project deletion, accepting entity proposals, model routing policy, Astra-owned systems (personas, WebGL, presence), and the RFC-0242/0244 semantics other than the studio-hold interaction stated here.

## Risks

- **BGM is still moving.** #33 and #34 are stacked and open. Mitigation: the gate, the re-trace at assignment, the contract-check items and recorded fixtures; a drift fails a named test and is fixed in an amendment, not worked around.
- **BGM-P1 may not land as proposed.** If PG chooses a different shape, only S3's parser and the fixture change; the rule "the gate reads one studio answer, never run lists" stays.
- **Owner-loaded models keep VRAM.** Taco's LM Studio 9B is not ANZU-loaded, so ANZU will not unload it. The hold text says so and offers the existing explicit Unload; whether ANZU should offer to unload it automatically during runs is a decision for Taco (Q3).
- **Studio hangs while up.** `unknown` defers automatic loads rather than risk the render; explicit owner Load is never blocked by `unknown`, so the owner always has a way out.
- **#686 and D2 names are not final.** The amendment on #686 proposes `keep_warm`, `idle_unload_seconds` and the `keep_alive` values and leaves final names to D2's PR; T3's `inference/model_release.py` has not landed. S3 uses the amendment's names by section and re-traces them when T3 and D2's PR land (gating item 3).
- **Approval fatigue.** Approve-take is gated by design; if Taco wants "approve all ready takes" as one grant, that is an amendment with a bulk target, not a gate bypass.

## Open questions for PG (BGM API)

| # | Question | Default if unanswered |
| --- | --- | --- |
| Q1 | Will BGM-P1 `GET /api/gpu/status` and BGM-P2 `GET /api/contract` be added as proposed, and is `models_resident` for a **paused** `generate` run true (C5)? | ANZU treats `paused` as busy. |
| Q2 | Do `ingest` and `stitch` ever hold the GPU (NVENC, an embedded model) (C6)? | They are not holders; BGM-P1 reports them if they are. |
| Q3 | Does `ingest`'s LLM call (`Settings.llm_base_url`, default LM Studio) share the owner's LM Studio model with ANZU? Taco decides whether ANZU may unload owner-loaded models during a run. | No: ANZU leaves them and tells the owner. |
| Q4 | Will BGM add auth (BGM-P3) before it is ever bound beyond loopback? | None needed; loopback only. |
| Q5 | Is BGM `main` readable by CI (public, or a read token for the S5 checkout)? | S5 stays blocked until answered. |
| Q6 | Should the ComfyUI HR Endless sidecar actions on `blackgrid_studio` be retired once the studio connector lands? | Kept unchanged; no removal in this RFC. |
| Q7 | Is there (or will there be) a project delete or an `entity-proposals` bulk action ANZU should expose (C11)? | Not exposed. |
| Q8 | `MovieOut.path` is relative to `projects/<pid>/`: should ANZU get an absolute path, or is the studio's `projects` directory a setting ANZU should read (C12)? | ANZU reports the relative path only. |
