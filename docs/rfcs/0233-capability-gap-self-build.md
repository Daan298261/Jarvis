# RFC-0233: Capability-gap self-build (detect, propose, owner-approved install or build, sandboxed, audited)

**Status:** accepted
**Priority:** P1 (Taco ask, relayed by Chief of Staff 2026-10-20; queued after RFC-0231)
**Author:** Jarvis Architect
**Date:** 2026-10-20
**Traced on:** `development` @ `30076969` (#662 landed on top of `a44da353`; it touches only `backend/app/manager/*` and appends two steps to `.github/workflows/pr-tests.yml`, so every file:line cited below from `a44da353` is unchanged and was re-checked on `30076969`). Open PRs read at their current heads: #670 (RFC-0211, supersedes #585; final head in this PR's body), #652 (RFC-0225; final head in this PR's body), #655 (RFC-0228; final head in this PR's body), #664 (RFC-0232; final head in this PR's body), #665 (RFC-0231; final head in this PR's body), #666 (RFC-0230; final head in this PR's body). #661 (RE allow-list-first gate) has landed as `bd2558bd`. Re-checked on `development` @ `e56740c` (`bd2558bd` plus #669, which touches only `mcp/` lockfiles); #661's only backend change is `reverse_engineering/store.py` (and `apk_sidecar.py`), cited below at its landed lines. Of the landed PRs only #649 (RFC-0224 durable prompt steps) touches what this RFC builds on: `agent/task_workflow.py`, `TaskPromptPlan` / `TaskPromptStep` in `db/models.py:66-88`, `prompt_steps` in `api/tasks.py:287-288`, and the workflow hooks in `agent/loop.py:2344-2348`, `:2672-2722`, `:3639-3660`. None of the landed PRs has a hunk in `tools/capability.py`, `tools/exposure.py`, `tools/registry.py`, `agent/tooling.py`, `policy/approval_grant.py`, `policy/computer_permissions.py`, `policy/network_http.py`, `packs/` or `skills/`.

**Owner ask (intent as relayed):** when ANZU gets a request it can't fulfil because a tool or capability is missing, it notices the gap, proposes building or installing that capability, and builds it only after Taco explicitly approves.

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md):
- §1: "Tell ANZU what you want. ANZU figures out how to accomplish it." A missing tool becomes a proposal instead of a dead end.
- §7: "ANZU should eliminate unnecessary approvals without eliminating meaningful control." Installing or running new code is the textbook consequential action, so it always gets one clear ask, and nothing else gets a new ask.
- §8: "Confidence should come from evidence rather than cheerful completion messages." Every install is hash-verified and self-tested, and every run is recorded in a hash-chained audit log.
- §15: "Security should be part of the platform." Built tools run sealed: no network, read-only inputs, never a write to case data.
- §17: "A new specialist pack should extend ANZU. It should not fragment the experience into another application." Capabilities register as RFC-0007 packs and ordinary registry tools, not as a second plugin system.
- §19: "Do use fast deterministic mechanisms where they are superior to AI reasoning." Gap detection is a rules floor on the existing single decide.

**Owner context that shapes the security posture:** Taco is a digital-forensics specialist working for Dutch law enforcement. Case data is evidence. A built or installed tool must never be able to write to an evidence path, and its reads of case data must be provably read-only (hashes before and after, recorded in the audit log).

**Extends (do not rewrite):**
- [RFC-0171](0171-system-one-reflex-lane-jev-laya-priority.md) / [RFC-0206](0206-jev-laya-every-turn-arbitration.md): one decide per owner turn, 50 ms deadline, rules fallback.
- [RFC-0218](0218-persona-surfaces-and-intent-switch.md) S1: the rider-question pattern on that decide.
- [RFC-0224](0224-responsive-conversation-and-durable-task-prompts.md) (#649, landed `ee786dc`): the durable prompt-step engine in `agent/task_workflow.py` (`TaskWorkflow` L41, `load_workflow` L101, `prepare_workflow` L115, `workflow_payload` L172), used unchanged.
- [RFC-0231](0231-large-prompt-pipeline.md) (#665): child tasks through `AgentRuntime.create_task` with a keyword-only marker, `task_workflow.seed_workflow` (0231-S2, appended to the landed `task_workflow.py` after `workflow_payload`), the terminal hook next to `advance_intake_chain`, `resolve_target` / `preload`, startup recovery.
- [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) (#652) S3: `engine_coexistence.owner_line(...)`, the only owner-line channel.
- [RFC-0031](0031-reversibility-first-action-gates.md): `policy/approval_grant.py`, the unforgeable human grant store.
- [RFC-0007](0007-domain-workspace-packs.md): `packs/manager.py` install / rollback / uninstall with the recovery journal.
- [RFC-0026](0026-execution-phase-and-verifier-observability.md) / [RFC-0029](0029-transactional-durable-execution.md): durable tasks.

**Amended 2026-10-20 (joint push with #664/#665/#666; CoS):** re-pinned to `development` @ `e56740c`, #652 (RFC-0225; final head in this PR's body), #655 (RFC-0228; final head in this PR's body), #661 landed (`bd2558bd`), #664 (RFC-0232; final head in this PR's body), #665 (RFC-0231; final head in this PR's body), #666 (RFC-0230; final head in this PR's body); `owner_turn.py` chain is #649 → 0218-S3b → 0230-S5 → 0232-S2 → 0231-S1 → 0233-S1 in every file; the 27B wait/release rule is RFC-0231's (#665 §2 *While the parent is `waiting`*): release after `idle_unload_seconds`, only if ANZU loaded it, reload on `/continue` or approval; the gap-rider RE skip uses #664's narrowed explicit-phrase list. **Then (UX round 3 on #665, CoS N8/N9):** re-pinned to #652 (RFC-0225; final head in this PR's body), #664 (RFC-0232; final head in this PR's body), #665 (RFC-0231; final head in this PR's body), #666 (RFC-0230; final head in this PR's body) with moved line refs; the waiting rule includes 0231's keep-alive refresh while the lease is held. **Then (D2 round 4 at the old head + CoS):** the build/register card hash covers the plan (spec_sha256, every package name, version and hash, the catalog entry) and the card displays it; approvals need a server-minted one-time card token bound to the card hash, with `origin_channel` derived by the server, never supplied by callers (replay and forged-origin tests); installs are deny-by-default through `software.install` with a catalog entry only, and launcher commands are checked against `PERMITTED_INVOCATIONS` (14 named negatives); the gap precheck sits in `decide_owner_turn` after 0231's `large_precheck` and reaches `_apply_floors` by keyword; dev-worker refs point at #670 (RFC-0211, supersedes #585) with its line numbers; chains match #652's canonical ones (`main.py`, `config.py` and `App.tsx` end at #670; #670 doesn't edit `loop.py`); #664's four owner phrases are restated with D2's five negatives; open batch PRs cited by number and RFC only. **Then (CoS correction):** the restated RE list uses CoS's exact four phrases (`reverse engineer`, `full FFS`, `full file system extraction`, `extraction of my phone`, strict literal); `npm run` / `npm test` / `yarn run` / `pnpm run` / `bun run` removed from `PERMITTED_INVOCATIONS`, with `test_install_guard_neg_package_script_runners`.
**Reconciles with (in flight):** RFC-0211 / #670 (supersedes #585, which it ports onto `development` with the same RFC text) (scheduler, `resource_hold`, Away Mode, self-development merge and build), RFC-0232 / #664 (the RE-intent floor in `_apply_floors` and its helper `planning.re_intent_match`), RFC-0230 / [#666](0230-pc-first-response-latency.md) (PC first-response latency; its slices go first on `loop.py` and `owner_turn.py`), #661 (landed `bd2558bd`: the RE allow-list-first gate `reverse_engineering.store.admit_allowed_target`, reused for capability inputs).

**Astra boundary:** persona, WebGL, presence, morph and appearance are out of scope. This RFC emits no persona events and edits no persona or presence file.

Some links point at RFC files that live only on their open PRs. They resolve once those PRs land. This PR is **specs-only**.

---

## Problem

Verified on `development` @ `30076969`.

1. **A missing capability is a silent dead end.**
   - The model's escape hatch is `request_capability` (`tools/capability.py:9-64`). When it names something that isn't a registered tool, `ToolExposure.grant` returns `Unknown capability … Known: …` (`tools/exposure.py:150-156`), and the loop's `apply_capability_request` returns the observation "No new tools were added. … Unknown capabilities: …" (`agent/tooling.py:57-90`). The model then improvises (usually a terminal or Python attempt) or gives up. The owner is never told what was missing and is never offered a way to get it.
   - Calling a tool that doesn't exist ends in `Unknown tool {name}` (`tools/registry.py:182-184`), also invisible to the owner.
2. **The decide never asks "can ANZU do this at all?"** `OWNER_TURN_QUESTIONS` (`decision/owner_turn.py:46-73`) has `request_route` and `reply_shape`. RFC-0218 adds the persona rider (`_decide_sync`, L419-469), RFC-0231 adds the large-prompt riders. Nothing compares the request against the capabilities ANZU actually has.
3. **The tool registry is static.** `ToolRegistry._init_tools` builds a fixed list (`tools/registry.py:59-101`). `NATIVE_TOOLS` is a fixed tuple (`tools/exposure.py:97`), and `ensure_named_tool` refuses anything outside it except `mcp_*` (L172-182). There is no path to add a tool at runtime other than an owner-configured MCP server, which runs unsandboxed (`tools/mcp_runtime.py:89 prepare_stdio_launch`).
4. **Today the model's improvised install is silent.** `pip install`, `npm i`, `git clone`, `docker pull`, `winget install` and `hf download` inside `terminal` / `python` / `open_interpreter` arguments only match `_OUTBOUND_RE` (`policy/computer_permissions.py:33-45`), which classifies them as `network.internet` (`permission_ids_for_tool`, L479-538, shell branch L494-495). That permission defaults to `"allow"` (`CATALOG`, L83-89). The `git` tool's own `clone` action (`tools/git_tools.py:144-155`) and the `docker` tool's `run` / `build` actions (`tools/docker_tools.py:134-182`, which pull a missing image) are further ways in. So the most likely route after a gap is an unasked install.
5. **Pieces exist, but nothing joins them:**
   - **Grants:** `policy/approval_grant.py` (RFC-0031) gives trusted-channel grants (`TRUSTED_CHANNELS = {ui, api, voice, physical, decision_inbox, mobile}`, L22) with a pending store, expiry (L181-209) and `decide_approval_request` (L212-339). Any of those channels can mint an `allow_once` today, for example through `POST /api/reversibility/pending/{id}/decide` (`api/reversibility.py:88-113`). It also allows `always` (L236-237, L386-407), which must never apply to installing or running new code. Its audit is capped at 500 rows (`_MAX_AUDIT`, L30, trimmed in `_save` L78-83), which is not an evidence-grade log.
   - **Packs:** `packs/manager.py` (RFC-0007) installs, rolls back and uninstalls packs with a recovery journal (`install_pack` L336-394, `rollback_pack` L471-513, `uninstall_pack` L516-547), and `tool` is already a resource type (`packs/schema.py:10-21`). No tool is ever installed through it.
   - **Skill Forge:** `skills/` (RFC-0173) turns verified traces into skills: "No automatic publication" (`skills/approval.py:1`), effective permissions = declaration ∩ profile ∩ task ∩ node (`skills/permissions.py:1`). Skills compose existing tools. They can't supply a missing binary.
   - **Downloads:** `policy/network_http.gated_download_to` (L180-221) calls `require_http_url_allowed(current, tool=…)` on every redirect hop, but has no host allow-list hook and no byte cap while streaming. `runtime_install.py` downloads llama.cpp from a pinned tag (L40-43) and has `_sha256` (L243). `modules/catalog_download.py` only clones allowlisted GitHub URLs (L25, L205-222).
   - **Sandbox:** `agent/local_harness.sandbox_available()` (L148) probes for Docker. `reflex_loop/sandbox.py` describes itself as "Minimal in-ticket sandbox posture … not a full port" (L1). Neither runs untrusted code.
   - **Evidence roots:** LE-gated folders (`modules/catalog_download.le_gated_roots`, L141-163), REA investigation roots (`security/rea_paths.configured_investigation_roots`, L55-72) and successful LTA extract dirs (`rea_paths.succeeded_lta_extract_dirs`, L100). No common "evidence path" notion protects them from a new tool.
6. **Anything running as the owner on this PC can approve.**
   - Loopback requests skip auth (`auth.is_auth_required_for_request`, `auth.py:163-191`: `is_local_owner_host` → no key).
   - `POST /api/auth/desktop-session` hands the owner key to any loopback caller (`api/auth.py:62-72`).
   - So the model's own `terminal`, `python`, `web_fetch`, browser or computer-use tools could post `grant_mode=allow_once` to `/api/tasks/{id}/continue` (`api/tasks.py:310-338`) or click an Approve button. For ordinary RFC-0031 confirmations that risk is already accepted. For "install and run new code" it is not acceptable.
7. **The self-development pipeline can add dependencies.** #670's Away Mode has standing authorization to implement, merge and build (`0211-…md` L9, L44-47 in #670 (RFC-0211, supersedes #585; final head in this PR's body)). Its "do not install" rule is a prompt line (`development_worker.py:234`), and its `verification` (L159-192) only refuses architect-owned docs (L178-180). A mission that edits `backend/requirements.txt` or `frontend/package.json` would be merged and built with no owner ask.

## Decision

Ship **one RFC with seven implement slices**, one named model per slice and fast mode off.

```
owner turn ─► decide_owner_turn (one decide, rider capability_gap)          model calls request_capability(unknown, missing=…)
   │ gap                                                                         │ (runtime trigger), or an install command
   │                                                                             │ (install guard, §3.5: never executed)
   └───────────────┬─────────────────────────────────────────────────────────────┘
                   ▼
         proposals.propose()  ── catalog match → kind "install" │ buildable spec → kind "build" │ else → not offered (visible)
                   ▼
   asking task → waiting_for_confirmation (payload kind "capability_build") + RFC-0031 parked request
               + owner_line(ask, task_id) → engine_notice + chat_tts on the task stream     [approval window open: model tools wait]
                   ▼
   Approve (tap on the desktop or Android card only, allow_once, payload hash) ─► build child task (create_task(capability_build=…))
   Deny (card, voice, API, physical or inbox) / 15 min timeout ─► final, visible, audited; the asking task continues without it
                   ▼
   child: broker fetch (pinned URL + sha256) → unpack to ANZU-owned dir → sealed self-test → [build kind: gate 2 with code hash]
        → RFC-0007 pack "capability.<id>" + REGISTRY tool cap_<id> → audit → asking task resumes with the new tool
          (resume injects the stored observation; request_capability is never re-run, §5.5)
```

### Terms

| Term | Meaning |
| --- | --- |
| **Capability** | A catalog entry (install kind) or an owner-approved built tool (build kind), exposed as one registry tool `cap_<id>`. |
| **Proposal** | One `capability_proposals` row: what, from where, which permissions, and its status. |
| **Asking task** | The task that hit the gap. It waits while the owner decides. |
| **Build child** | The ordinary task created after approval that installs or builds the capability. |
| **Approval window** | The interval in which any capability ask is open. Every model-driven tool call waits during it unless the tool is on `WINDOW_SAFE_TOOLS` (§3.4). |
| **Install guard** | The classifier that turns any package or model install a tool would run into a refusal plus a gate ask, never an execution (§3.5). |
| **Spec model / code model** | The uncensored 9B `qwen3.5-9b-defiant-fable-uncensored` (LM Studio, `127.0.0.1:1234`) writes every build spec and build prompt; `anzu-coder-27b` (Ollama, `127.0.0.1:11434`) writes the code (§5.3). |
| **Evidence roots** | Paths a capability must never write to (§4.3). |
| **Sealed profile** | The only sandbox profile in v1: no network, read-only file inputs, one scratch output dir (§4). |

### 1. Detection (S1): one decide, one rider, plus the runtime trigger

**Catalog (the allowed-sources root of trust).** `backend/app/capability_build/catalog.json`, shipped in the repo and changed only by reviewed PR. The model and the owner can't add entries at runtime. Each entry has:
- `id`, `title`, `summary_spoken` (≤ 90 chars, no URLs);
- `kind: "binary_zip" | "wheel_set"`;
- `version`, `license`;
- `source`: `url`, `host`, `project`, `sha256` (64 hex), `size_bytes`;
- `entrypoint` (relative path inside the unpacked tree), and `entry_sha256` for that single file;
- `tool`: name `cap_<id>`, description, JSON schema, `task_classes`;
- `permissions`: always exactly `{"network": "none", "inputs": "files_readonly", "output": "scratch", "max_runtime_s": ≤ 600, "max_memory_mb": ≤ 2048}`;
- `triggers`: en and nl regexes, plus `aliases` (names the model might pass to `request_capability`);
- `self_test`: argv plus the expected exit code and a stdout regex, run sealed after install.

**v1 catalog** (versions pinned to the newest stable release at implementation time; the S1 CI step proves every pin):

| id | What | Source host |
| --- | --- | --- |
| `sqlite_cli` | SQLite command-line shell (`sqlite3.exe`), for reading app databases from extractions | `www.sqlite.org` |
| `ffmpeg` | `ffmpeg.exe` / `ffprobe.exe` (BtbN/FFmpeg-Builds win64 GPL release, pinned dated tag, not `latest`) | `github.com` |
| `python_evtx` | `python-evtx` and its full dependency closure, every wheel `py3-none-any`, each hashed | `files.pythonhosted.org` |
| `sandbox_python_win` | Python 3.12 embeddable amd64 zip: the interpreter for wheel-set and built tools on Windows | `www.python.org` |
| `sandbox_image_linux` | `python:3.12-slim` pinned by digest: the interpreter image for non-Windows nodes and CI | `registry-1.docker.io` |

`ALLOWED_SOURCE_HOSTS` (module constant in `catalog.py`) is exactly those hosts plus the GitHub release-asset redirect hosts (`objects.githubusercontent.com`, `release-assets.githubusercontent.com`), and only as a **redirect hop** from a `github.com/<project>/releases/download/` URL. The two runtime entries are never offered on their own. They are listed as a dependency inside any ask that needs them (§3.1).

**Capability index (in memory, never read on the decide path).** `capability_build/index.py::CAPABILITY_INDEX` holds `{id: available, version}` and the compiled trigger regexes. S1 builds it at module import from `catalog.json` (every entry unavailable, since nothing can be installed before S4). S4 adds `index.rebuild()` at startup (`main.py`, right after the `tool_registry` step at L250) and after every install, rollback or uninstall. `available` means installed, registered, and integrity OK (§5.4).

**Precheck (rules, sync, under 1 ms)** in `decide_owner_turn`, **inside** the `try` at `owner_turn.py:567`, right after RFC-0231-S1's `large_precheck` and before `started` is re-taken (so, like 0231's, it is outside the 50 ms decide budget; the `owner_turn.py` order is #649 → 0218-S3b → 0230-S5 → 0232-S2 → 0231-S1 → 0233-S1). The local is `gap_precheck`. It reaches the rest of the turn the same way 0231's result does: `_decide_sync`, `_deadline_rules_result` (L373-400) and `_apply_floors` each gain one keyword `gap_precheck=None`, passed at all three call sites (`:461` normal, `:600` timeout, `:623` exception). `_decide_sync` only appends the gap rider to its one `decide()` (L453-460) when `gap_precheck` has candidates; it never computes the precheck itself, and still makes exactly **one** `decide()`. The precheck produces candidates only when **all** of these hold:
- `settings.capability_build.enabled` is true;
- `security_role == ""`;
- `planning.re_intent_match(user_message)` returns `None`. RFC-0232-S2 (#664 (RFC-0232; final head in this PR's body), L111-117) defines that helper and memoises it per turn, so this is a memo hit, not a second probe. It reads the owner's allow-list from settings and never passes `None` to the gate. The routing precedence shared by #664 and #665 is, verbatim:
  > A turn whose prompt contains an absolute filesystem path together with RE intent (RFC-0232's narrowed dump/extraction detection) routes to reverse engineering and is never split by RFC-0231; a path with a plain or coding question routes normally.
  RFC-0232 enforces it as a **floor in `_apply_floors`** (after the `task_class` block, L347-356, before `covers`, L358), not as an early return. Only that RE-intent match skips the gap rider, because the RE tool already exists. What counts as RE intent is #664's narrowed list (#664 L124-154), summarised here: **explicit** is exactly the **four CoS owner phrases**: `reverse engineer`, `full FFS`, `full file system extraction` and `extraction of my phone` (strict literal: no device synonyms, no `this|the|a`, no trailing noun such as `id|module|parser|backup|tests`). `FFS of my …`, `decompile` / `disassemble`, an `.apk` / `.apks` / `.xapk` path, `extraction of my Pixel|device|iPhone`, `forensic image` / `forensic extraction`, `full file system dump` / `image` and every other wording are at most **weak**, and a weak match (a path component such as `ffs` / `dump` / `extraction`, a forensic-only layout, a forensic image extension, or the narrowed wording) counts only when the probe returns `dump`. D2's round-3 phrases (Android filesystem API, phone image, device image, device dump handler, file system dump command) and D2's five non-owner phrases (`forensic image parser`, `full file system image backup`, `extraction of the device id`, `the device extraction module`, `ffs of the tests`) are not RE intent, so they **get** the gap check (`test_non_owner_re_phrases_still_get_gap_check`, S1, one case each). A path on its own never skips it: `C:\code\etl what does the extraction step do?` has a path and the word `extraction`, but `re_intent_match` returns `None`, so the turn routes normally **and gets the gap check** (`test_path_with_coding_question_still_gets_gap_check`, S1).
- at least one floor rule below fires.

**Gap floor in `_apply_floors`** (after RFC-0232-S2's RE floor and RFC-0231-S1's large floor): it applies the floor semantics below to the rider answer. When the RE floor fired on this turn (`re_intent_match` non-`None`), `capability_gap` is forced to `None`, so even a deadline-fallback result can't carry a gap past the RE route. Because `_apply_floors` is also the deadline-fallback path (L600, L623), explicit G2/G3 gaps survive a timeout. `_deadline_rules_result` (L373-400) carries the rules answer for the `capability_gap` question, the same way RFC-0231-S1 carries its riders.

Without candidates no rider is appended and the decision is unchanged byte for byte.

**Rules floor** (`decision/capability_gap.py`, new; rider branch in `decision/adapters/rules.py` next to the persona branch at L238):
- **G1, implicit gap:** a catalog trigger matches, the entry is not available, and `route_kind == "managed_task"`. Gives `kind="install"` with `trigger="rider"`.
- **G2, explicit install:** `^(?:please\s+)?(?:install|add|get|installeer|voeg)\b.*\b<alias>\b` matches a catalog alias, on any route, and the entry is not available. Gives `kind="install"` with `trigger="explicit"`.
- **G3, explicit build:** `\b(?:build|make|create|give)\s+(?:yourself|anzu)\s+(?:a|an|the)?\s*(?:new\s+)?(?:tool|capability)\b`, or the nl `\b(?:bouw|maak)\s+(?:jezelf|voor jezelf)\s+(?:een\s+)?(?:tool|functie)\b`. Gives `kind="build"` with `trigger="explicit"`, and the spec is the owner's prompt.
- At most 3 candidates, catalog order. G2 and G3 beat G1.

**Rider** (appended for that call only): `Question(id="capability_gap", type="choice", choices=("none", *candidate_ids), decision_class="tool_selection", descriptions=…)`. `tool_selection` is already in `REFLEX_DECISION_CLASSES` (`decision/types.py:14-39`), so `decision/types.py` is not edited.

**Floor semantics** (same rule as `reflex.py:398-410`):
- A typed provider may pick another listed candidate, or `none`, only at confidence ≥ 0.75.
- It can never name an id that is not in the candidates.
- G2 and G3 (explicit) can't be lowered to `none`.
- The deadline fallback (`_deadline_rules_result`, `OWNER_TURN_DEADLINE_MS = 50`, L39) is the rules answer, passed through `_apply_floors`.

**Output:** a new field `OwnerTurnDecision.capability_gap: CapabilityGapIntent | None` (next to `persona_intent`, L157), with fields:
- `verdict` (`none` | `gap`);
- `capability_id` (catalog id, or `""` for build);
- `kind`;
- `trigger`;
- `rules_fired`;
- `decision_source`;
- `confidence`.

`request_routing` passes it through unchanged. There is still exactly one decide per owner turn.

**Runtime trigger (S3).** `request_capability` gains an optional string argument `missing` ("describe the ability you lack when no listed tool fits"). This is an add-only schema field in `tools/capability.py:18-31`. In the loop's `request_capability` branch (`agent/loop.py:3462`), when `apply_capability_request` reports unknown names, `capability_build.proposals.runtime_gap(task_id, unknown, missing)` runs:
- an alias or trigger hit on an unavailable catalog entry gives an install proposal;
- otherwise, when `settings.capability_build.allow_build` is on and the build-eligibility rules pass (§5.6), a build proposal;
- otherwise no proposal. The observation tells the model "Not something ANZU can add safely: <reason>", and the task gets one parent event with the same text, so the owner can see why.
- `runtime_gap` never hands a gap to RFC-0211's self-development backlog: `capability_build` imports nothing from `development_scheduler` / `development_worker` and writes no backlog item (static test `test_runtime_gap_never_feeds_self_dev_backlog`, S3).

The existing observation lines from `tooling.py:83-89` are kept unchanged. The proposal outcome is appended after them.

**Ask throttle (no ask spam):**
- At most one open ask per task.
- At most 3 asks per rolling hour across ANZU. An ask over the limit isn't raised; the task gets the visible event "I need <title> for this, but I've asked about new tools several times this hour; ask me to install it when you're ready."
- A capability the owner denied isn't asked about again implicitly (G1, runtime or install guard) for 24 h. An explicit request (G2 or G3) always asks.
- Dependency asks (§3.4.2) are not throttled: there is exactly one per mission diff hash.

### 2. Lifecycle and storage (S3, S4)

**Tables** (`db/models.py`; created by `create_all`, no ALTER needed).

`capability_proposals`:
- `id`;
- `task_id` (the asking task);
- `kind` (`install` | `build` | `dependency`; `dependency` is the #670 self-development gate, §3.4.2);
- `capability_id`, `title`, `version`, `source_json`, `permissions_json`;
- `deps_json` (runtime entries pulled in);
- `trigger` (`rider` | `runtime` | `explicit` | `install_guard` | `self_dev`);
- `spec_text` (build only, ≤ 4000 chars, the **checked** spec, §5.3), `spec_sha256`;
- `status`: proposed | asking | approved | denied | timed_out | building | awaiting_register | installed | failed | register_denied | register_timed_out | cancelled | applied;
- `pending_approval_id`, `grant_id`, `register_pending_id`, `register_grant_id`;
- `child_task_id` (unique, nullable);
- `artifact_sha256` (install: the verified download's sha256; build: the built tree's sha256; dependency: the mission diff's sha256);
- `decided_via` (`card_ui` | `card_mobile` | `deny_channel:<origin>` | `timeout` | `cancel`);
- `failure`;
- `created_at`, `decided_at`, `updated_at`.

`capability_installs`:
- `capability_id`, `version` (PK pair);
- `pack_id` (`capability.<id>`);
- `install_dir`;
- `tree_sha256`, `entry_sha256`;
- `state`: active | previous | removed;
- `installed_at`, `removed_at`;
- `proposal_id`.

**Audit log** (§4.6) is a separate append-only file, not a table, so a DB restore can't rewrite history.

#### 2.1 State transitions (every status and column has a named writer and reader)

Every write goes through one function in `capability_build/proposals.py` (S3) unless the row names another module; `test_every_proposal_status_reachable` (S4) drives a fixture proposal through every row of this table and asserts each status is written by exactly the named function, and `test_every_column_has_writer_and_reader` (S4, static AST scan of `backend/app`) fails on a `CapabilityProposal` / `CapabilityInstall` column with no assignment or no read outside `db/models.py`.

| Status | Written by (slice) | Transition | Read by (slice) |
| --- | --- | --- | --- |
| `proposed` | `proposals.propose` (S3) | row insert | `proposals.open_ask` (S3: only `proposed` rows are asked); `spec_writer.write_spec` (S5: a build row stays `proposed` while the spec is written and checked); `GET /api/capabilities` recent asks (S4) |
| `asking` | `proposals.open_ask` (S3) | `proposed` → `asking`, after the RFC-0031 row is parked and the payload committed | `window.approval_window_open` (S3), the expiry timer (S3), `queue.blocking` (S4), `queue.on_parent_cancel` (S4), `queue.recover_on_startup` (S4) |
| `approved` | `proposals.record_decision` (S3), called only from `confirm_task`'s capability branch | `asking` → `approved` on an `allow_once` card tap | `queue.start_build` (S4: only `approved` rows start); `dependency_gate.require_for_publication` (S3) |
| `denied` | `proposals.record_decision` (S3) | `asking` → `denied` (card Deny or a deny-only channel, §3.2) | 24 h dedupe in `proposals.propose` (S3); `queue.resume_parent` (S4: "without it" observation); panel (S6) |
| `timed_out` | `proposals.expire` (S3: timer, or `recover_on_startup` step 3) | `asking` → `timed_out` | same readers as `denied` |
| `building` | `queue.start_build` (S4) | `approved` → `building`, in the session that commits the child `Task` row | `queue.recover_on_startup` step 4 (S4), `queue.blocking` (S4), panel (S6) |
| `awaiting_register` | `builder.request_register` (S5) | `building` → `awaiting_register`, with `register_pending_id` | `confirm_task` capability branch (S3: `gate="register"` is accepted only on this status), `proposals.expire` (S3), `queue.recover_on_startup` (S4) |
| `installed` | `installer.run` final `register` step (S4); `builder.register` (S5) after the register grant | `building` / `awaiting_register` → `installed` | `index.rebuild` (S4), `queue.resume_parent` (S4: "cap_<id> is now available"), panel (S6) |
| `failed` | `installer.run` / `builder` on any failed step (S4, S5); `spec_writer.write_spec` after the second failed check (S5) | `proposed` / `building` → `failed` | `queue.resume_parent` (S4: failure observation), the owner line (S3 texts), panel (S6) |
| `register_denied` / `register_timed_out` | `proposals.record_decision` / `proposals.expire` on the register gate (S3) | `awaiting_register` → either | `builder.discard` (S5: deletes the build dir), `queue.resume_parent` (S4), panel (S6) |
| `cancelled` | `queue.on_parent_cancel` (S4) | any non-terminal → `cancelled` | `queue.recover_on_startup` (S4: skipped), panel (S6) |
| `applied` | `dependency_gate.require_for_publication(action="merge")` (S3) when it consumes the grant | `approved` → `applied` (dependency kind only) | `dependency_gate.require_for_publication(action="build")` (S3: a build is allowed only for an `applied` row with the same `artifact_sha256`), panel (S6) |

| Column | Written by | Read by |
| --- | --- | --- |
| `kind`, `capability_id`, `title`, `version`, `source_json`, `permissions_json`, `deps_json`, `trigger` | `proposals.propose` (S3) | the card payload (`open_ask`, S3), `installer.run` fetch (S4), dedupe (S3: `trigger` decides implicit vs explicit), panel (S6) |
| `spec_text`, `spec_sha256` | `spec_writer.write_spec` (S5) after a passing check | gate 1 binding in `open_ask` (S3), `builder` prompts (S5) |
| `pending_approval_id` | `proposals.open_ask` (S3) | `confirm_task` capability branch, `proposals.expire`, `queue.on_parent_cancel` |
| `grant_id` | `proposals.record_decision` (S3) | `proposals.require_grant` (S3) at every step |
| `register_pending_id` | `builder.request_register` (S5) | `confirm_task` capability branch, `proposals.expire` |
| `register_grant_id` | `proposals.record_decision` (S3) on the register gate | `builder.register` → `require_grant` (S5) |
| `child_task_id` | `queue.start_build` (S4) | `queue.on_child_terminal` lookup, `on_parent_cancel`, `recover_on_startup` (S4) |
| `artifact_sha256` | `installer.run` verify step (S4); `builder.request_register` (S5); `dependency_gate.open_dependency_ask` (S3) | register binding (S3), `installed` audit row (S4), `require_for_publication` (S3), panel (S6) |
| `failure` | whoever sets `failed` | the "Failed" owner line, panel |
| `decided_at`, `decided_via` | `proposals.record_decision`, `proposals.expire`, `queue.on_parent_cancel` | audit rows (S3), panel recent asks (S6) |
| `created_at`, `updated_at` | `propose` / every writer | throttle window (S3: asks per rolling hour), panel |
| `capability_installs.state` | `capability_build/packs.py` (S4): `install` (new `active`, old `active` → `previous`, older `previous` dir deleted), `rollback` (swap), `uninstall` (`removed`) | startup re-register (S4: `active`), rollback availability (S4/S6: `previous` exists), panel |
| `capability_installs.install_dir`, `tree_sha256`, `entry_sha256` | `packs.install` (S4) | `SandboxedCapabilityTool` integrity checks and `run_sealed` (S4), panel |
| `capability_installs.installed_at`, `removed_at`, `proposal_id`, `pack_id` | `packs.install` / `packs.uninstall` (S4) | panel (S6: installed time, "from ask", pack id), `packs.rollback` (S4: `pack_id`) |

The install child's step rows (`fetch`, `verify`, `unpack`, `self_test`, `register`) are advanced only with the landed `TaskWorkflow.mark_running()` and `finish_current(result)` (`task_workflow.py:79-99`, used the same way at `loop.py:3640-3642`). 0233 adds no step-advance code of its own.

### 3. The owner approval gate (S3)

#### 3.1 What the owner sees and hears

The asking task goes to `status="waiting"` with `waiting_for_confirmation=True`, the same mechanism as the existing tool pause (`loop.py:3426-3452`). It gets:
- `confirmation_payload = {"kind": "capability_build", "gate": "install" | "build" | "register" | "dependency", "proposal_id", "pending_approval_id", "title", "version", "source": {"url", "host", "project", "sha256", "size_bytes", "license"}, "deps": [...], "permissions": {...}, "sandbox": "sealed", "expires_at", "code": {"sha256", "files", "lines", "tests_passed"} (register gate only), "dependency": {"mission_id", "diff_sha256", "files", "added", "changed"} (dependency gate only), "plan": {"spec_sha256", "summary", "modules": [...], "packages": [{"name", "version", "sha256", "source_url"}], "catalog_entry": {"id", "version", "sha256", "permissions"} | null} (build and register gates; the install gate carries `catalog_entry` and `packages` too)}`. The payload is built by `proposals.render_payload(proposal)` from the stored proposal, with keys sorted, so the plan the owner sees is the plan that is hashed.
- The card authenticates the exact payload by its hash: `_task_dict` (`api/tasks.py:89`, next to `"confirmation_payload"` at L184) gains the add-only key `confirmation_payload_sha256` = `sha256(task.confirmation_payload.encode()).hexdigest()` (the same digest `mobile/service.task_snapshot` already computes at L76), or `null` when there is no payload. Because `plan` is inside the payload, this **card hash covers the plan**: `spec_sha256`, every package name and version (and its hash) and the catalog entry. A change to any of them after the card rendered changes the hash, and the approval gets 409 (`test_build_card_hash_covers_plan`).
- **No `spoken_prompt` key.** `PermissionPrompt` would otherwise speak it (`PermissionPrompt.tsx:115-130`) and the line would be spoken twice. **No `pending_id` key**, so the RFC-0110 modal store is not involved (`OwnerChatTranscript.tsx:107-108`).
- A parked RFC-0031 request: `park_approval_request(action_id=action_id_for("capability_build", gate, target, task_id=…)` with `target` per gate: install `f"install:{capability_id}@{version}#{sha256}"`; build `f"build:{proposal_id}#{card_hash}"`, where `card_hash` is the `confirmation_payload_sha256` above (so it covers the plan); register `f"register:{capability_id}@{version}#{tree_sha256}"`; dependency `f"dependency:{mission_id}#{diff_sha256}"` (, tool_name="capability_build", ttl_seconds=settings.capability_build.ask_ttl_s, …)` (`approval_grant.py:94-153`). The target string binds the grant to the exact artifact hash.

**Spoken and shown on the task stream.** The ask is delivered with `engine_coexistence.owner_line(text, level="info", task_id=<asking task>, title="New capability")`. Per RFC-0225 S3 that publishes one `engine_notice` on the owner channel plus, because `task_id` is set, an `engine_notice` and a `chat_tts` titled "New capability" on the task stream (`useTaskSpeech.ts` speaks it; the title is not "Speak reply", so it never joins the reply prefix). It is **never** sent through `publish_owner_text`, whose channel has no client (#663). An install ask is published ≤ 150 ms after `evaluate_request_route` returns (same budget and test style as RFC-0231 S4). A build ask follows the spec and its fact-check (§5.3); inside the same 150 ms the asking task shows the event "Working out what that tool would need".

**Owner texts** (en, module constants in `capability_build/texts.py`; spoken text has no URLs or hashes, per North Star §4; the card shows them):

| Case | Spoken and shown |
| --- | --- |
| Install ask | "To do this I need {title}: {summary_spoken}. I can install version {version} from {project}'s official release, checked against a pinned fingerprint. It would run sealed off: no internet, read-only access to the files you give it, and it can never change your case folders. Approve or deny it on screen." |
| Install ask with runtime dependency | the same text, with "It also needs ANZU's sealed Python runtime, {rt_version}, from python.org." before "Approve or deny" |
| Build ask | "There's no tool for this yet. I can write one: {spec_summary ≤ 90}. I'd build and test it sealed off, with no internet and no access to your files, and I'll show you the finished code's fingerprint before I add it. Approve or deny it on screen." |
| Register ask (build gate 2) | "The {title} tool is built, passed {n} tests, and its output on the test files checked out. Approve on screen to add it, or deny to throw it away." |
| Install refused by the guard (§3.5), catalog match | "I tried to install {name}, but ANZU only installs new software with your approval." followed by the Install ask |
| Install refused by the guard, no catalog match | "I tried to install {name}. ANZU doesn't install software from package indexes, so I'll continue without it." (level info; no ask) |
| Dependency ask (#670, §3.4.2) | "A development change adds or changes {n} dependencies ({names ≤ 90}). Approve on screen to let it merge and build, or deny to keep it out." |
| Code model refused by the VRAM gate (§5.3) | "The coding model doesn't fit next to the loaded 9B right now, so I'm writing this tool with the 9B instead." (level info) |
| Spec failed its check twice (§5.3) | "I couldn't write a plan for this tool that checks out: {reason ≤ 120}. Nothing was built." (level error) |
| Built tool output failed its check (§5.3) | "The {title} tool gave wrong results on its test files, so I threw it away: {reason ≤ 120}." (level error) |
| Denied | "Okay, I won't install {title}. I'll do what I can without it." (level info) |
| Timed out | "I didn't get an answer, so I haven't installed {title}. Ask me again any time." (level error) |
| Installed | "{title} is installed and checked. Continuing." |
| Failed | "Installing {title} failed: {reason ≤ 160}. Nothing was added, and anything partly installed was removed." (level error) |

**The card** (S6 desktop and phone web, S7 Android; §7) shows title, version, source URL, host, sha256, size, license, every runtime dependency with its own URL and hash, the permission list in plain words, the sandbox name, the expiry time in the owner's local time, for the register gate the code hash, file count, line count and test count, and for the dependency gate the mission, diff hash and every added or changed manifest line. **It displays the plan** for the build and register gates: the spec summary and `spec_sha256`, every module, every package with its name, version and hash, and the catalog entry (id, version, hash, permissions); the install card shows its catalog entry and packages the same way. The desktop, phone-web and Android cards render the same `plan` object (`test_card_displays_plan_desktop_phone_android`). It has exactly two buttons: **Approve** and **Deny**.

#### 3.2 Decision rules (normative)

**Only the owner's tap on the hash-bound card approves.** Two surfaces show the card: the desktop app (HUD and classic transcript, and the phone web page `pages/Phone.tsx`), and the Android companion (S7). Every other channel can **deny** an ask but can never **approve** one.

- **One-time card token, server-minted.** When the ask is raised, and again on every card render, `proposals.mint_card_token(proposal)` creates `secrets.token_urlsafe(32)` and stores only its sha256, the `card_hash` it is bound to (the `confirmation_payload_sha256` above), `expires_at` (`min(ask expiry, now + 300 s)`) and `used = false` on the proposal row. Minting a new token invalidates the previous one. The token is **never** in `_task_dict`, `/api/tasks*`, the task event stream, `confirmation_payload`, an audit row or any tool output. It is returned only by the card-render endpoints: `GET /api/tasks/{id}/capability-card` (desktop and phone web; `Depends(require_owner_private_key)` from `auth.py:107`, i.e. the owner private key even when localhost API auth is off) and, for Android, the existing companion snapshot (`mobile/service.task_snapshot`, L76-83), which already mints its own one-time approval token per payload hash; S3 binds that token to the same `card_hash`. Tool subprocesses (`terminal`, `python`, `open_interpreter`, `code_worker`, MCP servers) are started with an environment that carries neither the owner private key nor the API token (`test_tool_subprocess_env_has_no_owner_key`), and while the ask is open no new model tool call runs (§3.4).
- **Desktop / phone web.** The decision arrives on the new `POST /api/tasks/{id}/capability-card/decide` (in `api/tasks.py`, whose router is already registered, so `main.py` is not touched by S3; `Depends(require_owner_private_key)`), body `{"approved": bool, "card_token": str, "card_hash": str}`. **The server derives `origin_channel`**: this endpoint sets `"ui"`, and only after `secrets.compare_digest(sha256(card_token), stored)` and `card_hash == stored card_hash == sha256(current confirmation_payload)` both hold and the token is unused and unexpired; it marks the token `used` in the same transaction. A wrong, reused, expired or other-card token → 409 "This card is out of date; open the current one." **Callers never supply `origin_channel`**: `ContinueBody` gets no such field, and `POST /api/tasks/{id}/continue` on a capability payload accepts only a deny (any other body → 403 "Only a tap on the card can approve a new capability."). A body that tries to smuggle `origin_channel: "ui"` or `"mobile"` into `/continue` is ignored by the model and still refused (`test_forged_origin_channel_refused`).
- **Android.** The companion approves through `POST /api/companion/tasks/{id}/approve` (`api/companion.py:319-321`) → `mobile/service.approve` (`mobile/service.py:86-97`). That function already checks the one-time token and that `sha256(task.confirmation_payload)` equals the snapshot's `payload_hash` (L94). S3 adds one branch before its `confirm_task` call (L97): when the parsed payload has `kind == "capability_build"`, it marks that token used and calls `confirm_task(task_id, approved, origin_channel="mobile", grant_mode="allow_once" if approved else "deny", expected_payload_hash=approval["payload_hash"])` (`origin_channel` set by the server from the endpoint, never from the request) instead of the `expected_payload=` call. A changed payload still raises its existing 409 ("The pending action has changed"). Other payload kinds keep the existing call unchanged.
- **`confirm_task` capability branch.** `confirm_task` (`loop.py:592-731`) gains keyword-only `origin_channel: str | None = None` and `expected_payload_hash: str | None = None` (defaults keep every existing caller unchanged; only the two server-side card endpoints above pass them, with the server-derived channel) and one branch, taken first when the stored payload's `kind == "capability_build"`:
  1. **Deny first.** A deny (`approved is False` or `grant_mode == "deny"`) is accepted from any caller with no hash, because a deny can't run anything. It calls `decide_approval_request(pending, decision="deny", origin_channel=origin_channel or "api", actor="owner", session_id=task_id)` and `proposals.record_decision` with `decided_via = "card_ui"`, `"card_mobile"` or `"deny_channel:<origin>"`.
  2. `grant_mode` in `{"always", "allow_session"}` → `CapabilityDecisionRefused("This can only be approved once.", status_code=400)`. Nothing changes; the task stays waiting.
  3. An approval (`grant_mode == "allow_once"`) requires `origin_channel in {"ui", "mobile"}`; otherwise `CapabilityDecisionRefused("Only a tap on the card can approve a new capability.", status_code=403)`. Nothing changes.
  4. **Hash check.** `expected_payload_hash` is required for an approval (missing → `ValueError("This card is out of date; open the current one.")`). It is compared with `hmac.compare_digest` to the sha256 of the stored `confirmation_payload`, and then the same atomic `update(Task)… where waiting_for_confirmation and confirmation_payload == <stored string>` as the existing binding (L604-613) clears `waiting_for_confirmation`. A mismatch or `rowcount != 1` raises `ValueError` (→ 409), so a stale card can never act on a replacement ask.
  5. Only then: `decide_approval_request(pending, decision="allow_once", origin_channel=origin_channel, actor="owner", session_id=task_id, decide_via="task_confirm_card")` and `proposals.record_decision(...)` with `decided_via = "card_ui" | "card_mobile"`.
- **Approval refusal in the grant store, enforced in code.** `approval_grant.py` gets `ONCE_ONLY_TOOLS = frozenset({"capability_build"})` and a keyword-only `decide_via: str = ""` on `decide_approval_request` (L212). For a pending row whose `tool_name` is in `ONCE_ONLY_TOOLS`:
  - `always` → `PermissionError` (no `always`, anywhere);
  - an approving decision (`allow_once` / `approve` / `allow` / `yes`) → `PermissionError("Only a tap on the capability card can approve this.")` unless `decide_via == "task_confirm_card"` **and** `origin_channel in {"ui", "mobile"}`;
  - `deny` / `reject` / `no` from any `TRUSTED_CHANNELS` value → accepted.
  So `POST /api/reversibility/pending/{id}/decide` (`api/reversibility.py:88-113`, which never passes `decide_via`) returns its existing 403 for an approve on a capability row and its normal result for a deny. `api/reversibility.py` itself is not edited.
- **Other `confirm_task` callers can't approve.** `_resume_task_with_grant` (`api/reversibility.py:56-86`, call at L85) and `api/guest_portals.py:241` call `confirm_task(task_id, True, …)` without `origin_channel` / `expected_payload_hash`; on a capability payload that is step 1's `ValueError`. Their deny calls (`api/reversibility.py:127`, `:145`) take step 1 and need no hash.
- **No voice approval.** An STT mishear must never authorize running new code. The spoken line says "on screen", and the card has no microphone. Saying "yes" in chat is an ordinary follow-up message, and a test proves it does not approve. A voice "no" goes through the ordinary deny path.
- **No silent auto-approve path.**
  - There is no setting, autonomy level, Away Mode or grant that approves a capability.
  - RFC-0211's Away Mode standing authorization (#670 RFC text, "Decision") explicitly does **not** cover capability installs or new dependencies (§3.4.2). Asks raised in Away Mode wait for the owner and time out like any other ask.
  - A static test asserts that `decide_via="task_confirm_card"` appears in `backend/app` only inside `confirm_task`'s capability branch.
- **Denial and timeout are final.**
  - The proposal becomes `denied` or `timed_out`, and the pending row is terminal (`approval_grant.py:251-254` already refuses a second decision).
  - The owner line from the table is published, and an audit row is written.
  - The asking task resumes without the capability (§5.5).
  - The same proposal can't be approved later. A new explicit request creates a new proposal.
- **Timeout timer.** `capability_build/proposals.py` schedules `asyncio` expiry at `expires_at` (`settings.capability_build.ask_ttl_s`, default 900 s = 15 min). Startup recovery (§5.7) expires any ask whose time passed while ANZU was down, using the same text. `approval_grant._expire_pending_unlocked` (L181-209) marks the pending row `timeout`, and the proposal follows it.

#### 3.3 Gates per kind

| Kind | Gate | Covers | Bound to |
| --- | --- | --- | --- |
| install | one ask | download from the pinned URL(s), hash check, unpack into the ANZU-owned dir, sealed self-test, registration of `cap_<id>` | `capability_id@version#sha256` (+ each dependency's hash) |
| build | ask 1 (`gate="build"`) | ANZU writing code into an ANZU-owned build dir; running that code's tests sealed; fetching any listed pinned wheels | the **checked** spec's `spec_sha256` + each dependency's hash |
| build | ask 2 (`gate="register"`) | registering the built tool | the built tree's sha256 |
| dependency | one ask (`gate="dependency"`) | one #670 merge of that mission diff and the build of its merge SHA (§3.4.2) | `dependency:<mission_id>#<diff_sha256>` |

Nothing is downloaded, executed or registered before the matching grant exists. `proposals.require_grant(proposal, gate)` calls `validate_grant_for_action` (`approval_grant.py:342-383`) and `consume_grant` (L386-422) at the start of each step, and a test proves each step refuses without a grant.

#### 3.4 Approval window: ANZU can't approve itself (deny by default)

While any capability ask is open (any `asking` or `awaiting_register` row, every kind including `dependency`), `capability_build.window.approval_window_open()` is true, and the marker file `data/capabilities/approval_window.json` exists, so another ANZU process can honour it (§3.4.1).

In the window **every** model-driven tool call waits, unless `window.tool_allowed_in_window(name, arguments)` is true. That function allows only:
- `WINDOW_SAFE_TOOLS = frozenset({"search_internal_references", "read_ingress", "request_tools", "request_capability", "chat_projects", "vault_memory", "screenshot", "capability_workshop"})` (tools with no network, no subprocess, no input injection and no loopback client; `screenshot` only captures or describes, `capability_workshop` only writes its build dir and runs sealed);
- `WINDOW_SAFE_ACTIONS = {"filesystem": frozenset({"list", "search", "read", "hash", "stat", "compare", "recent"})}` (read-only actions; every write, move, delete, extract or restore waits);
- registered `cap_*` capability tools (sealed: no network, §4.1).

Everything else waits, including `terminal`, `python`, `open_interpreter`, `code_worker`, `browser`, `browser_use`, `web_fetch`, `external_ingest`, `desktop`, `cua`, `ufo`, `reflex_computer_use`, `apps`, `mobile_apps`, `mobile_call`, `office`, `git`, `docker`, `verify_code`, `blender` (runs `--python` scripts, `tools/dcc_tools.py:76-113`), `freecad`, `openscad`, `reverse_engineer`, `rea_investigate`, `lta_protected_folder`, `intelligence`, `hexstrike_defensive`, `hexstrike_operator`, `blackgrid_studio`, `mcp_call`, every `mcp_*`, and any tool added later that is not on the allow-list. The allow-list is the only list; there is no held-tools list to keep in sync.

The wait is `await window.wait_closed()` in `_run`, right after the tool's metadata lookup (`loop.py:3374-3376`) and before the permission check (`_permission_denied_observation`, L3377) and the side-effect decision (L3382). The task gets one event, "Paused while you decide about a new capability", and `current_action` is set to the same text. The longest pause is the ask TTL (default 15 min). A held tool call that already started before the ask opened is not interrupted; the window gates every new call.

A test runs a second task that tries `web_fetch` against `/api/tasks/{id}/continue` during an open ask and proves the call only runs after the ask is decided by the test's simulated owner click. `test_window_allowlist_deny_by_default` enumerates `REGISTRY.tools` and asserts `tool_allowed_in_window` is true exactly for the allow-list (plus the read-only `filesystem` actions and `cap_*`), and that a synthetic tool registered by the test waits.

#### 3.4.1 The #670 development worker honours the window (concrete obligation)

#670 (RFC-0211, supersedes #585; final head in this PR's body) runs missions in a separate process, `backend/app/agent/development_worker.py`. Its `execute(control)` builds its own `AGENT` and calls `AGENT.create_task(...)` (#670 `development_worker.py:195`, `create_task` at L239), so its tool loop is the same `_run`. But in that process the in-memory window flag is always false, and `data_dir()` may not be the owner's (`execute` already reads the owner's `data/STOP_JARVIS` through `mission["owner_root"]`, L242). Without a bind, a mission's `terminal` or `browser` call could reach the owner's loopback API while a capability ask is open.

One function closes it: `capability_build.window.bind_worker_process(owner_root: Path)`. It:
- points `approval_window_open()` and `wait_closed()` at `owner_root / "data/capabilities/approval_window.json"`, so the 0233-S3 wait in `_run` (before the permission check at `loop.py:3377`) holds every non-allow-listed tool in that process too;
- disables proposals in that process: `proposals.runtime_gap` and the install guard's ask (§3.5) return the visible observation "Capabilities can't be added from a development mission" and create no proposal, because the worker's task stream has no owner client to hear or approve an ask. The install guard's refusal itself still applies in the worker.

**Who adds the call.** Whichever of 0233-S3 and #670 lands **second** adds exactly one line to `development_worker.execute`, before `AGENT.create_task`: `bind_worker_process(Path(mission["owner_root"]))`. It also adds the #670-side test below. The obligation can't be parked, because a 0233 guard test fails the full suite until the line exists:

| Side | Test (file :: name) | Asserts |
| --- | --- | --- |
| 0233-S3 (always ships with S3) | `tests/test_rfc0233_approval_gate.py::test_worker_process_honours_owner_marker` | after `bind_worker_process(tmp_owner)`, with the marker written under `tmp_owner/data/capabilities/`, a held tool (`web_fetch`) waits until the marker is removed; `runtime_gap` returns the "development mission" observation and writes no `capability_proposals` row |
| 0233-S3 (guard, always ships with S3) | `tests/test_rfc0233_approval_gate.py::test_development_worker_binds_capability_window` | static (AST) check: if `backend/app/agent/development_worker.py` exists, `execute` calls `bind_worker_process` with `mission["owner_root"]` before its first `AGENT.create_task` call; if the file doesn't exist, the test asserts that and passes (not a skip) |
| second lander (#670 or 0233-S3) | `tests/test_rfc0211_development_scheduler.py::test_development_worker_binds_capability_window_before_task` | runs `development_worker.execute` against a `tmp_path` control dir with a minimal `mission.json`, monkeypatched `MANAGER.load` / `init_db` / providers (the fixture style of #670's `test_launch_keeps_owner_model_and_uses_trusted_code`, L278), a fake `bind_worker_process` and a fake `AGENT.create_task`; the bind is called once with `Path(mission["owner_root"])`, before `create_task` |

So if 0233-S3 lands first, #670's CI ("Run full backend suite") is red until #670 adds the line and its test. If #670 lands first, S3's own guard is red until S3 adds them. `backend/app/agent/development_worker.py` is in 0233-S3's file list for that case.

#### 3.4.2 #670 self-development: new dependencies go through the same gate (enforced in code)

A capability gap that needs a change to ANZU's own source is never turned into a self-development mission by this RFC (§5.6, `test_runtime_gap_never_feeds_self_dev_backlog`). But #670's own missions can still add a dependency, so the gate is enforced on the #670 side too, in code, not by the prompt line (`development_worker.py:234`).

**`capability_build/dependency_gate.py` (S3, new):**
- `DEPENDENCY_MANIFESTS` (glob list, repo-relative): `backend/requirements*.txt`, `frontend/package.json`, `frontend/package-lock.json`, `mcp/package.json`, `mcp/package-lock.json`, `android/app/build.gradle.kts`, `android/build.gradle.kts`, `android/gradle/**`, `backend/app/inference/model_stack.py` (`MODEL_CATALOG`, L85), `backend/app/reverse_engineering/engine-lock.json`, `backend/app/reverse_engineering/rea-package-lock.json`, `backend/app/capability_build/catalog.json`, `installer/windows/Jarvis.iss`, `installer/windows/assets/**`, `installer/windows/*download*.ps1`, `installer/windows/stage-*.ps1`, and `backend/app/tools/registry.py` (registering a new tool is a new capability).
- `dependency_changes(changed_files: list[str]) -> list[str]`: the changed paths that match.
- `open_dependency_ask(*, mission_id: str, title: str, diff_sha256: str, files: list[str], added: list[str], changed: list[str]) -> str`: creates a `kind="dependency"`, `trigger="self_dev"` proposal and an owner-side asking task through `AGENT.create_task(..., capability_build=proposal_id)` whose `_run` branch only parks the `gate="dependency"` ask (§3.1) and waits. Returns the proposal id.
- `require_for_publication(*, mission_id: str, diff_sha256: str, changed_files: list[str], action: Literal["merge", "build"], away_mode: bool) -> None`:
  - no dependency changes → returns;
  - `away_mode=True` → raises `DependencyApprovalRequired("Away Mode never merges or builds a new dependency.")`, **even if a grant exists**;
  - `action="merge"` → requires an `approved` dependency proposal bound to `dependency:<mission_id>#<diff_sha256>`, consumes its grant through `proposals.require_grant` and sets `applied`; otherwise raises `DependencyApprovalRequired`;
  - `action="build"` → requires an `applied` row with the same `artifact_sha256`; otherwise raises.

**#670-side obligation (same "second lander" rule as §3.4.1).** Whichever of 0233-S3 and #670 lands **second** adds:
1. In `development_worker.verification` (#670 (RFC-0211, supersedes #585; final head in this PR's body), L159-192), right after the architect-docs refusal (L178-180): `deps = dependency_changes(changed.splitlines())`; when non-empty the payload is `{"ok": False, "blocked": "dependency_approval", "dependency_changes": deps, "diff_sha256": <sha256 of git diff base_sha>, ...}`, so the run ends `verification_failed` and never `review_ready`.
2. In #670's trusted merge and build controller (RFC-0211 §"Merge and build", not yet on the branch): `require_for_publication(..., action="merge", away_mode=<Away Mode active>)` immediately before the merge and `require_for_publication(..., action="build", ...)` immediately before the build of that merge SHA. When Away Mode is off and a mission is blocked on dependencies, the controller calls `open_dependency_ask` once per mission diff.
3. The #670-side test below.

| Side | Test (file :: name) | Asserts |
| --- | --- | --- |
| 0233-S3 | `tests/test_rfc0233_dependency_gate.py::test_dependency_changes_matches_every_manifest` | each glob above matches a sample path, and `backend/app/agent/loop.py` does not |
| 0233-S3 | `tests/test_rfc0233_dependency_gate.py::test_away_mode_never_publishes_dependency_even_with_grant` | an approved row + `away_mode=True` → `DependencyApprovalRequired` for merge and build |
| 0233-S3 | `tests/test_rfc0233_dependency_gate.py::test_merge_requires_card_grant_then_build_requires_applied` | no grant → raises; card-approved grant → merge passes and sets `applied`; build with another diff hash → raises; same hash → passes; the grant is consumed once |
| 0233-S3 (guard, always ships with S3) | `tests/test_rfc0233_dependency_gate.py::test_development_worker_gates_dependency_changes` | static (AST) check: if `backend/app/agent/development_worker.py` exists, `verification` calls `dependency_changes` and returns `ok: False` when it is non-empty; if the file doesn't exist, the test asserts that and passes (not a skip) |
| second lander (#670 or 0233-S3) | `tests/test_rfc0211_development_scheduler.py::test_dependency_change_blocks_merge_and_build_without_grant` | a disposable repo where the mission edits `backend/requirements.txt`: `verification` returns `blocked == "dependency_approval"`; the controller's merge raises in Away Mode even with an approved row, and outside Away Mode merges only after a card grant |

The guard test `test_development_worker_binds_capability_window` (§3.4.1) stays as it is.

#### 3.5 Install guard: installing packages is its own capability (S3)

Installing software is **not** internet use. It is a separate capability, **deny-by-default**, whatever tool would launch it. Its only way in is `software.install` through the owner approval gate for a **catalog entry**; nothing else installs. The enumerated classifier below exists only to give a precise owner line and to map a catalog alias to its ask. It is **not** what makes installs deny-by-default: the launcher allow-list below is.

**Classifier** (`capability_build/install_guard.py::install_intent(tool_name, arguments) -> InstallIntent | None`, pure, sync, no disk except reading a script file named in the arguments, ≤ 1 MiB):
- **Command forms**, matched case-insensitively on `computer_permissions._blob(arguments)` (L390) with quotes, commas and brackets normalised to spaces, so `["pip", "install", "x"]` in Python source matches like a shell line:
  - Python: `pip install`, `pip3 install`, `python -m pip install`, `py -m pip install`, `uv pip install`, `uv add`, `uv tool install`, `pipx install`, `conda install`, `pip.main(`;
  - Node: `npm install` / `npm i` / `npm ci` / `npm add`, `yarn add`, `pnpm add` / `pnpm install`, `npx <pkg>`;
  - Windows: `winget install`, `choco install` / `chocolatey install`, `scoop install`, `msiexec`, `Add-AppxPackage`, `Install-Module` / `Install-Package` / `Install-Script`, running an `.exe` / `.msi` installer;
  - other ecosystems: `cargo install`, `go install` / `go get`, `gem install`, `poetry add` / `poetry install`, `pnpm dlx`, `npm exec`, `bunx` / `bun add`, `dotnet tool install`, `apt-get install` / `apt install`;
  - fetch-and-run: `iwr … | iex` / `Invoke-Expression`, `curl … | sh` / `bash`;
  - containers: `docker pull`, and `docker run` / `docker build` / `docker compose up` without `--pull=never`;
  - models: `hf download`, `huggingface-cli download`, `snapshot_download(`, `hf_hub_download(`, `ollama pull`, `lms get`;
  - source: `git clone`, `git submodule add`, `git submodule update`.
- **Tool actions:** `git` with `action == "clone"` and a remote source (`looks_remote_git_source`, `computer_permissions.py:464`); `docker` `run` / `build` (`tools/docker_tools.py:134-182`) when an image it names (`image`, or each `FROM` in the build context's Dockerfile) is not present locally (`docker image inspect` exit code), and `run` always gets `--pull=never` appended by the guard so Docker itself can't fetch; `blender` / `freecad` / `openscad` script actions, by classifying the referenced script text.
- **Launchers covered:** every registered tool's arguments are classified, not only `terminal` / `python` / `open_interpreter`. The named launcher tests below cover `terminal`, `python`, `open_interpreter`, `code_worker` (`goal` text), `git`, `docker`, `mcp_call`, `blender`, `freecad` and `openscad`. ANZU's own broker downloads (§4.4) are not model tool calls and are not classified.

**Launcher allow-list (deny-by-default for commands).** `terminal`, `python`, `open_interpreter` and `code_worker` command text (and the script text `python` runs, and every `subprocess` / `os.system` / `Start-Process` / `ShellExecute` call inside it) is parsed into invocations (`install_guard.invocations(tool_name, arguments)`: split on `;`, `&&`, `||`, `|` and newlines; PowerShell aliases resolved). Each invocation must match `install_guard.PERMITTED_INVOCATIONS`, a frozen table of permitted executables and argument shapes:
- read and inspect: `dir` / `ls` / `Get-ChildItem`, `type` / `cat` / `Get-Content`, `rg`, `findstr` / `Select-String`, `where` / `Get-Command`, `git` with `status|log|diff|show|branch|rev-parse|ls-files|blame|grep`;
- local build and test in an allowed directory: `python` / `py` with a script path or `-m pytest|unittest|ruff|mypy` (never `-m pip`), `pytest`, `ruff`, `node <script>`, `git add|commit|checkout|switch|stash|restore` on a local repo;
- network read only: `curl` / `Invoke-WebRequest` / `iwr` **without** a pipe into any interpreter or shell and without writing an executable or script file (`.exe .msi .ps1 .psm1 .bat .cmd .sh .py .whl .nupkg`).
**No package-manager script runner is permitted**: `npm test`, `npm run <script>`, `yarn run` / `yarn <script>`, `pnpm run` / `pnpm <script>` and `bun run` execute arbitrary `package.json` scripts, which can install packages, so they need owner approval like any unlisted invocation. Anything that matches no row, including any pipe into `iex` / `Invoke-Expression` / `sh` / `bash` / `python`, running a downloaded or unknown executable (`.\setup.exe`, `Start-Process setup.exe`, any `*.exe` not on the table), `msiexec`, and every package-manager or installer verb, is **not executed** and needs owner approval: an invocation with an install intent goes to the catalog route below (ask for a catalog alias, else the visible "no catalog match" refusal); any other unlisted invocation becomes the existing per-call tool confirmation (`waiting_for_confirmation`, `loop.py:3426-3452`) with the parsed invocation shown, and never runs on a grant of `software.install` (which can't be granted). The table is the only list; a new executable is denied until it is added in a reviewed PR.

**Permission (backstop for every caller).** `policy/computer_permissions.py` gets a new `PermissionSpec("software.install", "software", "Install software", "Install packages, models, images or repositories.", "deny")` in `CATALOG`, and `permission_ids_for_tool` (L479-538) appends `"software.install"` whenever `install_intent(...)` is non-`None`. `apply_grant` (L267) and `operator_intent_grant` (L302) raise `PermissionError` for `software.install` with any mode other than `deny`, so neither a spoken "yes" (`interpret_spoken_grant`, L619) nor the permissions page can open it. The tools' own self-checks (`terminal.py:6285-6287`, `interpreter.py:45-47`, through `tool_permission_error`, L570) therefore refuse it even outside the loop.

**Loop hook (the route to the gate).** In `_run`, right after the window wait (§3.4) and before `_permission_denied_observation` (`loop.py:3377`), `install_guard.intercept(task_id, name, arguments)` runs. On an install intent the tool is **never executed**, and:
- if the intent's package or model name matches an alias of an unavailable catalog entry → `proposals.propose(kind="install", trigger="install_guard")` and the normal ask (§3.1); the observation is "Installing <name> needs the owner's approval on screen; I've asked. Wait for the result." and the call pauses exactly like a runtime ask (§5.5);
- otherwise → no ask; the observation and one task event are the "no catalog match" text from §3.1, and the model continues without it.
Throttle and 24 h dedupe (§1) apply; the worker-process rule in §3.4.1 applies.

Tests (`tests/test_rfc0233_install_guard.py`, S3), one per launcher plus the shared rules:
- `test_install_guard_terminal` (`pip install x`, `npm i x`, `winget install x`, `choco install x`, `docker pull x`, `hf download x`, `git clone https://…`, `ollama pull x`: none executed, each refused, `software.install` in `permission_ids_for_tool`);
- `test_install_guard_python` (`subprocess.run(["pip", "install", "x"])`, `pip.main(["install", "x"])`, `snapshot_download("x")`);
- `test_install_guard_open_interpreter`;
- `test_install_guard_code_worker` (a `delegate` goal containing `npm install`);
- `test_install_guard_git_tool_clone_remote` (a local-path clone is not an install);
- `test_install_guard_docker_tool_missing_image_and_pull_never` (present image runs with `--pull=never`; missing image refused);
- `test_install_guard_mcp_call`;
- `test_install_guard_blender_freecad_openscad_scripts`;
- `test_software_install_permission_cannot_be_granted` (`apply_grant` with `allow_once` / `allow_session` / `always` and `interpret_spoken_grant("yes")` paths all leave it `deny`);
- `test_terminal_self_check_refuses_install_outside_loop`;
- `test_catalog_alias_install_raises_gate_ask_not_execution` (`pip install python-evtx` → install proposal for `python_evtx`, asking task `waiting`, no subprocess spawned);
- `test_non_catalog_install_refused_visibly_no_ask`;
- `test_plain_network_use_unchanged` (`curl https://example.org` and `web_fetch` still classify as `network.internet` only);
- `test_launcher_allowlist_permits_listed_invocations` (each row of `PERMITTED_INVOCATIONS` runs without a prompt);
- `test_install_guard_neg_package_script_runners` (`npm run build`, `npm test`, `yarn run build`, `yarn build`, `pnpm run build`, `pnpm build`, `bun run build`: none in `PERMITTED_INVOCATIONS`, none executed, each becomes the per-call owner confirmation; a `package.json` whose `build` script is `npm install x` is never run);
- `test_unlisted_invocation_needs_owner_approval` (a synthetic `foo.exe --bar` → not executed, per-call confirmation, nothing run on a `software.install` grant attempt);
- named negatives, one test each, every one **not executed**, `software.install` in `permission_ids_for_tool` where it is an install and owner approval required otherwise: `test_install_guard_neg_install_module` (`Install-Module x`, also `Install-Package` / `Install-Script`), `test_install_guard_neg_iwr_iex` (`iwr https://x/i.ps1 | iex`), `test_install_guard_neg_curl_sh` (`curl https://x/i.sh | sh`), `test_install_guard_neg_exe` (`.\setup.exe /S` and `Start-Process setup.exe`), `test_install_guard_neg_msiexec` (`msiexec /i x.msi /qn`), `test_install_guard_neg_cargo` (`cargo install x`), `test_install_guard_neg_go` (`go install x@latest`, `go get x`), `test_install_guard_neg_gem` (`gem install x`), `test_install_guard_neg_poetry` (`poetry add x`, `poetry install`), `test_install_guard_neg_pnpm_dlx` (`pnpm dlx x`), `test_install_guard_neg_npm_exec` (`npm exec x`), `test_install_guard_neg_bunx` (`bunx x`, `bun add x`), `test_install_guard_neg_dotnet_tool` (`dotnet tool install -g x`), `test_install_guard_neg_apt_get` (`apt-get install -y x`).

### 4. Security posture (S2)

#### 4.1 Sandboxing: one profile, kernel-enforced, least privilege

`capability_build/sandbox.py::run_sealed(spec) -> SealedResult`.

- **There is no unsandboxed fallback.** If no backend is available, the capability is shown as "unavailable on this PC" and is never registered.
- Probe order: `win_appcontainer` on Windows, else `docker` when `local_harness.sandbox_available()` (L148) is true.

**`win_appcontainer`** (Windows 10+, ctypes only, no admin; the installer runs `PrivilegesRequired=lowest`, `Jarvis.iss:46`, and installs to `{localappdata}\Jarvis`, L24):
- A per-capability AppContainer profile `ANZU.Capability.<id>` (`CreateAppContainerProfile`, userenv). The process starts with `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` and **zero capabilities**. That means no `internetClient`, no `privateNetworkClientServer`, so no network at the kernel level, and no access to the user's files.
- ACL grants, only on ANZU-owned dirs:
  - read+execute for the container SID on `data/capabilities/installed/<id>/<version>/` and `data/capabilities/runtime/`;
  - modify on `data/capabilities/runs/<run_id>/out/` only.
- `data/` itself (`config.data_dir`, `config.py:24-27`), `settings.json`, `private_key.sec` (`auth.py:16-17`) and the owner's profile are never ACL'd, so the container can't read them.
- A Job Object with:
  - `KILL_ON_JOB_CLOSE`;
  - `ACTIVE_PROCESS_LIMIT=32`;
  - `PROCESS_MEMORY_LIMIT=max_memory_mb`;
  - wall-clock kill at `max_runtime_s`;
  - UI limits `READCLIPBOARD`, `WRITECLIPBOARD`, `GLOBALATOMS`, `DESKTOP`, `EXITWINDOWS`, `SYSTEMPARAMETERS`, `HANDLES`, so the clipboard can't leak secrets;
  - `CREATE_NO_WINDOW`.

**`docker`** (non-Windows nodes, CI):
- `docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 32 --memory {m}m --cpus 2 --user 65534:65534 --tmpfs /tmp:size=256m`;
- install dir mounted at `/opt/cap:ro`, each input file at `/in/<n>:ro`, the run's out dir at `/out:rw`;
- the image is `sandbox_image_linux` by digest;
- no `-e`, no env file.

#### 4.2 Inputs: read-only, files only (the #661 allow-list-first gate)

- A capability tool call takes `inputs: list[str]` (file paths) and `args: list[str]` (validated against the tool schema).
- **Admission order** (`capability_build/inputs.py::admit_input(path) -> Path`, S2), the same order #661 uses for RE prepare (`reverse_engineering/store.py` on `development` @ `e56740c`, landed with #661 `bd2558bd`: `admit_allowed_target` L295, `resolve_admitted_target` L309, link refusal as in `prepare_ffs`):
  1. `store.admit_allowed_target(path, settings.allowed_directories)`: the lexical path, then the parent's real path, **before** any exists / link / stat probe of the target;
  2. link and reparse refusal: `Path(path).is_symlink()`, or `lstat().st_file_attributes & 0x400` on Windows → refused;
  3. `store.resolve_admitted_target(path, settings.allowed_directories)`;
  4. not a regular file → refused ("give me the files"; directories are out of scope).
- `settings.allowed_directories` is always passed. `None` (the trusted in-process bypass) is never used here, and an empty list admits nothing.
- Every refusal for a target outside the allowed folders is the same `OUTSIDE_ALLOWED` text whether the target exists, is missing or is a link, so a capability call can't be used as an existence or link oracle (`test_input_outside_missing_link_same_error`, S2).
- `tools/safety.resolve_allowed_path` (L194-225) is **not** called directly: it realpaths first, which is the oracle #660/#661 closed.
- **Windows:** the broker (ANZU, outside the container) opens each admitted input with `GENERIC_READ`, share mode `FILE_SHARE_READ` only (denies concurrent writers and deletion for the run) and `FILE_FLAG_OPEN_REPARSE_POINT`, then checks that `GetFinalPathNameByHandleW` of the handle equals the admitted path. The handles are passed through `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`. The child gets `ANZU_INPUT_HANDLES=<json list>` and no path. The container itself can't open the original path.
- **docker:** the broker opens the input with `O_RDONLY | O_NOFOLLOW` first (same final-path check through `/proc/self/fd`), then bind-mounts that path `:ro`.
- At most 64 inputs per call.
- **Dependency (met):** `admit_allowed_target` and `resolve_admitted_target` are on `development` since #661 landed (`bd2558bd`). S2 imports both names from `reverse_engineering.store`, unchanged, and always passes `settings.allowed_directories` (never `None`, which is the gate's trusted-in-process bypass; an empty list admits nothing).

#### 4.3 Evidence integrity (normative)

`capability_build/evidence.py::evidence_roots()` is the union of:
- `le_gated_roots()` (`catalog_download.py:141`);
- `configured_investigation_roots()` (`rea_paths.py:55`);
- `succeeded_lta_extract_dirs()` (`rea_paths.py:100`);
- `settings.capability_build.evidence_roots` (new, owner-editable).

Rules:
1. **No write path can point into an evidence root.** The install dir, the runtime dir, the build dir and every run's out dir live under `data/capabilities/`. `evidence.assert_not_evidence(path)` is called on each of them before use, and refuses if `data/` itself is under an evidence root. This is a hard error, shown to the owner.
2. **Reads of evidence are provably read-only.** For every input under an evidence root, the broker records `sha256`, size and mtime before the run and again after it.
   - Files over 4 GiB get size, mtime, and the sha256 of the first and last 64 MiB, with the audit row marked `partial_hash`.
   - Any difference creates an `integrity_violation` audit row, disables the capability (the install row stays, the tool is unregistered), and publishes `owner_line("{title} was switched off: a case file changed while it was reading it. Check {file}.", level="error", task_id=…)`.
   - In normal operation this can't happen (kernel read-only plus the share mode). The check proves it for the case file.
3. **Built tools never see case data during a build.** Build-kind tests use synthetic fixtures the build child writes into the build dir. No evidence path is ever passed to a build child (§5.6).

#### 4.4 Allowed sources and downloads

- Only the broker downloads, never the sandboxed tool and never the model. It uses `network_http.gated_download_to(url, dest, tool="capability_build", allowed_hosts=ALLOWED_SOURCE_HOSTS_DIRECT, redirect_only_hosts=GITHUB_REDIRECT_HOSTS, max_bytes=entry.size_bytes)` (L180-221).
- **Add-only parameters on `gated_download_to` (S2 owns `policy/network_http.py`):**
  - `allowed_hosts: Collection[str] | None = None` and `redirect_only_hosts: Collection[str] = ()`. When `allowed_hosts` is set, **every hop**, the first URL and each redirect target, is checked before its request is sent: the host must be in `allowed_hosts`, or in `redirect_only_hosts` when the hop is a redirect (hop index ≥ 1). A failing hop raises `PermissionError` before any body byte is read, next to the existing `require_http_url_allowed` call (L204), which still runs.
  - `max_bytes: int | None = None`. When set, a `content-length` above it aborts before the body is read, and the streaming loop (L215-220) aborts as soon as `done > max_bytes`. On either abort, or any exception while one of the new parameters is set, the `.partial` file is deleted.
  - With all three left at their defaults the function is byte-for-byte today's behaviour (every existing caller unchanged).
- **The size cap:** `max_bytes` is the entry's pinned `size_bytes` exactly, and `catalog.py` validation refuses any `size_bytes` above `CAPABILITY_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024` (512 MiB).
- `ALLOWED_SOURCE_HOSTS_DIRECT` is the source hosts in the §1 table; `GITHUB_REDIRECT_HOSTS = ("objects.githubusercontent.com", "release-assets.githubusercontent.com")`. Together they are `ALLOWED_SOURCE_HOSTS`. The redirect-only hosts are accepted only after a hop from a `github.com/<project>/releases/download/` URL (checked by the broker's own hop record).
- After download: the size must equal `size_bytes` and the sha256 must equal the pinned value, or the file is deleted and the proposal fails. There are no retries with a different URL.
- Archives are unpacked with a path-traversal guard: no absolute paths, no `..`, no symlinks or reparse points. Afterwards `entry_sha256` is verified.
- Wheel sets install with `pip install --no-deps --no-index --only-binary=:all: --require-hashes --target <install_dir> <verified wheels>`, run by the broker with the sandbox runtime's interpreter. Wheels don't execute code at install time, and `--no-index` means pip can't fetch anything.
- The Linux image is pulled only as `docker pull <repo>@sha256:<digest>`.
- **Forbidden by construction:** `curl | sh`, PowerShell `iex`, MSI or EXE installers, `pip install` from an index, `npm`, `git clone`, and MCP servers. None of them is a catalog `kind`. `catalog.py` validation rejects unknown kinds, non-https URLs, hosts outside the allowlist, missing hashes, and `latest`-style tags.

**Network egress summary:** at install time, only the broker talks to the network, only to the allowlisted host of a pinned URL, with every redirect hop re-checked. At run time and build time, sandboxed code has **no** network (kernel-enforced on Windows, `--network none` on Docker). The model's own network tools are unchanged by this RFC outside the approval window, except that any install they would run is refused by the install guard (§3.5).

#### 4.5 Secrets isolation

- **Environment:** the sandboxed process gets only `SystemRoot`, `TEMP`/`TMP` (pointing at its out dir), `PATH` (its install and runtime dirs only), `ANZU_INPUT_HANDLES` and `ANZU_OUT`. No `JARVIS_*`, no `*_KEY`, `*_TOKEN` or `*_SECRET`, no proxy variables, and no inherited environment. A test enumerates the child's environment.
- **Files:** the AppContainer can't read `data/`, so `settings.json` (`api_key` and others, `config.py:88, 127, 159`) and `private_key.sec` are out of reach. Docker mounts nothing but the dirs above.
- **Clipboard:** blocked by the job UI limits.
- **Build-time:** a build child's prompt holds only the spec and synthetic fixtures. Before the register gate, the built tree is scanned with Skill Forge's secret regex (`skills/eligibility._SECRET_VALUE_RE`, L61). A hit fails the build ("the code contains something that looks like a secret").

#### 4.6 Audit log (who approved what, when, and the hash)

`data/capabilities/audit.jsonl`, written only by `capability_build/audit.py`:
- Append-only, with `fsync` after each row.
- **Never truncated**, unlike the RFC-0031 store's 500-row cap.
- **Hash-chained:** `row_hash = sha256(prev_hash + canonical_json(row_without_hash))`.

Each row: `seq`, `ts` (UTC ISO; the UI shows the owner's local time), `event`, `proposal_id`, `capability_id`, `version`, `prev_hash`, `row_hash`, plus the per-event fields:

| Event | Fields |
| --- | --- |
| `proposed` | trigger, kind, task_id, source url/host/sha256/size, deps, permissions |
| `asked` | pending_approval_id, gate, expires_at |
| `approved` / `denied` | gate, actor (`owner`), origin_channel (`ui`/`mobile`), client host (`request.client.host`, and whether `auth.is_local_owner_host`, `auth.py:33`), session_id, grant_id, decided_at, bound hash |
| `timed_out` | gate, pending_approval_id |
| `downloaded` | url, final hop host, bytes, sha256 actual, match |
| `installed` | install_dir, tree_sha256, entry_sha256, pack_id |
| `self_test` | exit code, passed |
| `registered` / `unregistered` | tool name, tree_sha256 |
| `run` | tool, task_id, input list (path, sha256 before/after, partial flag), exit code, duration_ms, out tree sha256 |
| `integrity_violation` | file, before/after |
| `rolled_back` / `uninstalled` | from/to version, actor |
| `failed` | step, reason |

The approval grant's own audit (`approval_grant._append_audit`) still runs. This log is the evidence-grade copy.

`audit.verify_chain() -> {ok, rows, first_bad_seq}` runs at startup. A broken chain disables every capability tool until the owner looks at it, and publishes `owner_line("The capability audit log doesn't verify (row {n}). New tools are switched off until you check it.", level="error")`.

`GET /api/capabilities/audit?format=jsonl` returns the raw file for case documentation.

#### 4.7 Rollback and uninstall

- Every capability is an RFC-0007 pack `capability.<id>` with one `tool` resource: data = tool schema, entrypoint, `tree_sha256`, sandbox profile. It is installed with `install_pack` (`packs/manager.py:336`), or `upgrade_pack` (L397) for a new version, which snapshots the previous one. The install is therefore journalled by `journal_mutate` like every pack.
- **Rollback** (`POST /api/capabilities/{id}/rollback`): `rollback_pack` (L471), switch `active` to the kept `previous` install dir, re-verify `tree_sha256`, re-register, write an audit row. ANZU keeps exactly one previous version on disk.
- **Uninstall** (`POST /api/capabilities/{id}/uninstall`): unregister the tool, `uninstall_pack` (L516), delete the ANZU-owned install dir (after `assert_not_evidence`), set state `removed`, write an audit row. The audit log and run out-dirs are kept.
- **Automatic cleanup** happens only on a failed install of the version being installed: a failed self-test or a failed hash leaves nothing registered and deletes the partial dir. It never touches another capability.
- These two endpoints are owner actions from the Capabilities panel (§7). They need no extra ask: they remove ANZU-owned files and are fully audited.

### 5. Build children, registration, resume (S4, S5)

#### 5.1 One task system

After the first grant, `capability_build.queue.start_build(proposal)` calls:

```
AGENT.create_task(child_prompt, request_id=uuid5(NS, f"capability:{proposal.id}"), capability_build=proposal.id)
```

`create_task(..., capability_build: str | None = None)` is **keyword-only, default `None`**, so every existing call is unchanged. It has exactly the shape of RFC-0231's `pipeline_section`:
- the route is fixed to MANAGED with **no decide**;
- no persona block, no large branch, no gap rider, no generic ack;
- the title is "Installing {title}", "Building {title}" or, for a dependency ask, "New dependencies for {mission title}" (that task only parks its ask and finishes with the outcome; it runs no model);
- the request id is stable, so a re-dispatch after a crash reuses the child (`loop.py:494-501`).

The kill switch check at `create_task` entry (`loop.py:488-492`) applies unchanged.

#### 5.2 Install child (no model)

`_run` sees `capability_build` on the task and runs `capability_build.installer.run(proposal, publish)` instead of the model loop, the same deterministic pre-model branch shape as RFC-0232 S3. The steps are seeded with `task_workflow.seed_workflow` (RFC-0231 S2, on the landed #649 engine) as `fetch`, `verify`, `unpack`, `self_test`, `register`, so the landed prompt-steps payload (`api/tasks.py:287-288`, `workflow_payload` at `task_workflow.py:172`) and `TaskActivity.tsx` show progress without new UI. The installer advances them only with the landed `workflow.mark_running()` before a step and `workflow.finish_current(<plain result>)` after it (`task_workflow.py:79-99`, the same calls `loop.py:3640-3642` makes). Seeded children never auto-plan: `load_workflow` (`task_workflow.py:101`) returns the seeded rows, so `_run` never reaches the `prepare_workflow` planner call (`loop.py:2686-2701`), and `is_large_request` (`task_workflow.py:31`) is never consulted for them. Each step:
1. calls `require_grant`;
2. does its work;
3. writes an audit row;
4. publishes a task event in plain text ("Downloading FFmpeg 7.1 (84 MB)", "Fingerprint matches", "Self-test passed").

#### 5.3 Build child (model, sealed tests): S5

**Which model does what (CoS ruling, normative):**

| Work | Model | How it is reached |
| --- | --- | --- |
| The build spec, `{spec_summary ≤ 90}`, every build-child step prompt, and the landed `fact_check` review step | the uncensored 9B `qwen3.5-9b-defiant-fable-uncensored` | `capability_build/models.py::spec_provider()` = `OpenAICompatProvider(settings.capability_build.spec_base_url, model=settings.capability_build.spec_model)` (defaults `http://127.0.0.1:1234/v1` and `qwen3.5-9b-defiant-fable-uncensored`, §6) (constructor `providers/base.py:174-179`), LM Studio |
| Code (`implement` rounds, through `capability_workshop`) | `anzu-coder-27b` | RFC-0231's `large_prompt.resolve_target` / `preload` (0231-S4; the profile and `MODEL_CATALOG["anzu-coder-27b"]` entry come from 0231-S0), Ollama `127.0.0.1:11434` |

The spec model is never swapped silently. If LM Studio doesn't list `spec_model` in `GET /v1/models`, no build proposal is made and the owner sees "The 9B that writes build plans isn't running in LM Studio, so I can't plan a new tool right now." `models.spec_provider()` takes **no** RFC-0225 request lease and **no** `NINE_B_REWARM` hold, so nothing 0233 does blocks RFC-0228's 9B idle-unload timer.

**1. Spec (before any ask; `capability_build/spec_writer.py`, `spec_check.py`, `fixtures.py`).** For a build proposal (`proposed`), the 9B writes a JSON spec: `summary_spoken` (≤ 90 chars), `purpose`, `inputs` (formats), `modules` (every import), `uses_catalog` (catalog ids with version), `permissions`, `fixtures` (≤ 5, each `{name, format, content}` in the `fixtures.py` generator vocabulary for `sqlite`, `zip`, `json`, `csv`, `xml`, `text`) and `examples` (≤ 5, each `{fixture, request, expected}`). The asking task shows "Working out what that tool would need" within 150 ms; the ask itself follows the check.

**2. Spec fact-check (deterministic, `spec_check.check(spec, proposal) -> SpecCheck`):**
- every name in `modules` is in `sys.stdlib_module_names` and not in `BUILD_FORBIDDEN_MODULES`, or is a top-level module of a catalog wheel named in `uses_catalog`;
- every file-format claim is checked against the synthetic fixtures: `fixtures.py` writes each fixture into the build dir, and a stdlib probe for that format (`sqlite3` read-only `PRAGMA schema_version`, `zipfile.is_zipfile`, `json.loads`, `csv.Sniffer`, `xml.etree.ElementTree.parse`, UTF-8 decode) must accept it;
- every `expected` value uses only the closed fact vocabulary (`tables`, `row_counts`, `members`, `keys`, `header`, `rows`, `lines`) and equals the fact the probe derives from that fixture;
- every title, version, source and permission claim matches `catalog.json` (`uses_catalog` ids exist with that version; `permissions` equals the sealed profile exactly).

On failure the 9B regenerates **once** with the failure list. A second failure sets `failed` and publishes the "Spec failed its check twice" line; no ask is raised for an unchecked spec. On success `spec_text` and `spec_sha256` are stored, and build gate 1 binds `spec_sha256` (§3.3).

**3. After gate 1: the build child.**
- **Code model, gate first.** `start_build` calls `engine_coexistence.gate_outlook(target)` (added by 0231-S0, #665 §2a) before saying anything about loading the 27B, then `large_prompt.preload(child_id, target, outlook)` for build kind. If the outlook is `refuse`, or the real RFC-0225 step-5 gate refuses (`preload_status == "gate_refused:<reason>"`), the code rounds run on the 9B through `spec_provider()`, and the owner hears the "Code model refused by the VRAM gate" line once (`owner_line(..., task_id=<asking task>, title="New capability")`). The build does not fail for that reason.
- The exposed tools are exactly `{"capability_workshop"}`, a new registry tool that only:
  - writes files inside `data/capabilities/build/<proposal>/` (relative paths only, ≤ 40 files, ≤ 2000 lines total);
  - runs the build's own tests through `run_sealed` with build-dir inputs.
- The seeded workflow steps are `implement`, `test`, `verify`, the landed `fact_check` review step (`REVIEW_STEPS[1]`, `task_workflow.py:15-19`, unchanged prompt) and `output_check`, with at most 3 implement/test rounds. After the third failed round the proposal fails with the "Failed" line. They advance with `mark_running` / `finish_current` only.
- **`output_check` (the built tool's output, before it is offered):** `builder.output_check` runs the built tool sealed on every spec fixture with the example's `request`, and its returned dict must contain every `expected` key with exactly the probe-derived value. Any mismatch fails the build with the "Built tool output failed its check" line; nothing is offered.
- **Tool contract:** a Python 3.12 package with `tool.py::run(request: dict, inputs: list[BinaryIO], out_dir: Path) -> dict`, executed by a fixed ANZU-owned launcher `capability_build/launcher_template.py` that opens the inherited handles. Imports are limited to the stdlib minus `BUILD_FORBIDDEN_MODULES` (`socket`, `ssl`, `http`, `urllib`, `ftplib`, `smtplib`, `subprocess`, `multiprocessing`, `ctypes`, `winreg`, `_winapi`, `asyncio.subprocess`), plus catalog wheels named in the proposal.
- `build_policy.scan(tree)` (AST) rejects forbidden imports, `__import__` or `importlib` with non-literal names, `eval`/`exec`/`compile`, and `open()` outside `out_dir`. It also runs the secret scan (§4.5). The sandbox enforces all of this anyway; the scan gives a clear failure before the register gate.

**4. Register gate (the 27B follows RFC-0231's `waiting` rule while the owner decides).** When `output_check` passes, the child computes `tree_sha256` and `builder.request_register` parks the **register** ask (§3.1, ask 2). Before the child goes `waiting`:
- The 27B rule is **RFC-0231's `waiting` rule, unchanged** (#665 §2 *While the parent is `waiting`*): the child keeps its request lease (and 0231's keep-alive refresh every `idle_unload_seconds / 2`) when it enters `waiting`, and 0231's `idle_unload_seconds` timer (RFC-0228 S2's setting, default 900 s) starts. When it fires, the lease is released and, **only if ANZU loaded the 27B** (it is in `anzu_loads`), the 27B is left to RFC-0228's normal expiry and RFC-0225's reverse gate; an owner-loaded 27B is never unloaded and its `keep_alive` is never touched. 0231 never pins the 27B (it is warmed with RFC-0228's normal `keep_alive`), so nothing is handed back. `models.on_wait(child_id)` calls 0231-S4's `large_prompt.start_wait_timer(child_id)` and `models.reacquire_coder(child_id)` calls `large_prompt.cancel_wait_timer(child_id)` then, if the timer had fired, 0231's re-preload; neither copies 0231's logic.
- Approve → the timer is cancelled if it has not fired; otherwise `models.reacquire_coder(child_id)` re-runs 0231's re-preload (same gate, same outcomes) only if work remains, as `/continue` does in 0231. Then register (§5.4). Register itself needs no model, so a plain approval registers without reloading.
- Deny or timeout → the build dir is deleted, the proposal becomes `register_denied` or `register_timed_out`, and an audit row is written. Nothing is reloaded.

#### 5.4 Registration

- `ToolRegistry` gains `register_capability(tool: SandboxedCapabilityTool)` and `unregister_capability(name)` (`tools/registry.py`, add-only methods). `_init_tools` (L59-101) is unchanged, and startup loads active `capability_installs` rows after it.
- `SandboxedCapabilityTool` (`tools/sandboxed_capability.py`, new):
  - `risk=RiskLevel.MEDIUM`, `effect_class="internal"`, `reversibility="REVERSIBLE"`, because it only writes its own out dir;
  - `execute` → `run_sealed`, with the output capped at 8000 chars plus a list of out files;
  - writes a `run` audit row.
- Before every run it re-hashes the entrypoint (`entry_sha256`). At startup it re-hashes the whole tree. A mismatch unregisters the tool and publishes an error owner line.
- `tools/exposure.py` accepts names that start with `cap_` **and** are currently registered capability tools, in `grant` (L150) and `ensure_named_tool` (L172). `NATIVE_TOOLS` is unchanged. `agent/tool_exposure.tool_names_for` (L173) adds the registered `cap_` tools whose `task_classes` match, and keeps a registered `cap_` name passed in `requested_tools`, so ANZU just uses an installed capability without asking again.

#### 5.5 Resume the asking task

`capability_build.queue.on_child_terminal(child_id, status)` is called from `_update`'s terminal block, next to `advance_intake_chain` (`loop.py:813`) and RFC-0231's `on_child_terminal`. `queue.resume_parent(proposal)` then resumes the asking task:
- **Decide-time ask** (the asking task never ran its model): `cap_<id>` is added to the task's `working.requested_tools` (persisted in `compact_memory`) when installed, then `_start_runner(_run(task, continue_existing=False))`. `_run` builds `exposed_tools` from `tool_names_for(..., working.requested_tools, ...)` (`loop.py:2658-2665`), so the new tool is exposed.
- **Runtime ask** (paused inside `request_capability`, or on an install-guard refusal): `cap_<id>` is added to `working.requested_tools` the same way, and `_run(task, continue_existing=True, pending_tool=payload)` resumes with `payload = {"name": <paused tool name>, "id": <call id>, "arguments": {...}, "capability_observation": <text>}`. The text is one of:
  - "cap_<id> is now available. Use it."
  - "The owner did not approve <title>; continue without it and say what you could not do."
  - "Installing <title> failed: <reason>."
- **The resume never re-runs the tool.** Today the `pending_tool` path re-executes the paused call through `_execute_tool` (`loop.py:2944-2965`, the call at L2949-2957), which would run `RequestCapabilityTool` (or the refused install command) again instead of delivering the stored result. S4 adds one short-circuit at the top of that block: when `pending_tool.get("capability_observation")` is a string, the loop appends `ChatMessage(role="tool", name=pending_tool["name"], tool_call_id=pending_tool.get("id") or "confirmed", content=<observation>)` and updates `exposed_tools` and the task's `exposed_tools` column with `_exposed_csv(working, ...)`, **without** calling `_execute_tool`. Every other `pending_tool` payload takes the existing path unchanged.
- **Denied or timed-out asks** resume the same way, with the "without it" observation. The final result therefore states what couldn't be done (North Star §8).
- **Cancel:** `AGENT.cancel(asking)` (`loop.py:733-738`) also cancels an open ask (status `cancelled`, pending row denied with actor `owner-cancel`) and the build child. `on_parent_cancel` is called from `cancel`, next to RFC-0231's hook.

#### 5.6 Build eligibility (rules, deterministic)

A build proposal is offered only when the spec (G3 prompt or runtime `missing`):
- names a local-file transformation or analysis (parse, convert, extract, decode, count, compare, summarise, or the nl equivalents);
- does **not** mention network, internet, download, upload, API, account, login, email, send, post, camera, microphone, screen, keyboard, registry, service, driver, or admin (en and nl lists in `capability_build/eligibility.py`);
- and fits the sealed profile.

Anything else gets the visible "not something ANZU can add safely" event with the matched word. A gap that needs a change to ANZU's own source is **not** a capability build, and this RFC never hands it to RFC-0211's self-development backlog either (§1, runtime trigger). This RFC never edits the repository, creates branches or merges. #670's own dependency changes go through the gate in §3.4.2.

#### 5.7 Startup recovery

In `main.py`, after RFC-0231's `recover_on_startup` call:
1. `audit.verify_chain()`.
2. Rebuild `CAPABILITY_INDEX`, and re-register active installs after a tree re-hash.
3. Expire overdue asks (§3.2).
4. For proposals in `building`: if the child is terminal, run `on_child_terminal`; otherwise `continue_task(child)` (RFC-0029 durable resume), re-running `preload` first for a build child that is past gate 1 and not waiting (0231's "Re-preload on resume" rule). A child in `awaiting_register` gets no preload. Partial download or unpack dirs are deleted and the step restarts from `fetch`. The grant check accepts the same `allow_once` grant, recorded as `resumed` in the audit log; it is never consumed twice and never re-minted.
5. Re-create the approval-window marker if an ask is still open, or remove a stale one.

#### 5.8 Interplay with the large-prompt pipeline (RFC-0231) and RFC-0232

- When one turn has both `large_prompt == "large"` and a gap: the large ack goes first (RFC-0231 §2), then the gap ask on the **parent**. `large_prompt_queue.dispatch_next` (0231-S5) does not dispatch part 1 while `capability_build.queue.blocking(parent)` is true. It shows the parent event "Waiting for your decision on {title}". When the ask resolves, dispatch continues, and each child's exposed tools include `cap_<id>` if it was installed.
- Part children never run the gap rider (they have no decide). A runtime gap inside a part asks on that part's own task stream, and the parent shows "Part n is waiting for your decision on {title}".
- **A part waiting on a capability ask follows RFC-0231's `waiting` rule** (#665 §2 *While the parent is `waiting`*, tests `test_waiting_releases_anzu_loaded_27b_after_idle_unload_seconds` and `test_waiting_never_touches_owner_loaded_target`): the lease is kept until `idle_unload_seconds`, then released; only an ANZU-loaded 27B is then left to expire; the owner's decision resumes the part through 0231's `/continue` path, which re-preloads (same gate, same outcomes, including the honest 9B fallback) when the lease was released. There is no capability-specific exception.
- RFC-0232's precedence rule applies verbatim (§1): a path with RE intent routes to reverse engineering and gets no gap rider; a path with a plain or coding question routes normally and gets the gap check like any other turn.

### 6. Settings (S1 adds the block; owned in `config.py`)

```python
class CapabilityBuildSettings(BaseModel):
    enabled: bool = True
    allow_build: bool = True
    ask_ttl_s: int = Field(default=900, ge=120, le=3600)
    evidence_roots: list[str] = Field(default_factory=list)
    spec_model: str = "qwen3.5-9b-defiant-fable-uncensored"
    spec_base_url: str = "http://127.0.0.1:1234/v1"
```

- `AppSettings.capability_build` is added next to `decision` (`DecisionSettings` at `config.py:456`, field `AppSettings.decision` at L512) and RFC-0231's `large_prompts`, and exposed on the existing settings GET and PUT.
- There is deliberately **no** auto-approve, allow-always, trusted-source or allow-install setting, and no setting that changes the code model (that is RFC-0231's `large_prompts.target_runtime`).
- `enabled=false` restores today's behaviour exactly: no rider, the same `request_capability` observation, no new events. A test proves the decision and `create_task` are byte-identical in that case.

### 7. Owner UI (S6 desktop and phone web, S7 Android), add-alongside only

- **`frontend/src/chat/CapabilityPrompt.tsx` (new):** the card from §3.1, with Approve and Deny only. It fetches `GET /api/tasks/{id}/capability-card` when it renders (plan, `card_hash`, one-time `card_token`) and posts `/api/tasks/{id}/capability-card/decide` with `{approved, card_token, card_hash}`; it never sends an `origin_channel`. On error it shows the server text. It has no microphone and no speech: the ask is spoken once, by `useTaskSpeech`, from the `chat_tts` event. Times are shown in the browser's local time.
- **Render sites:** one added conditional at each existing site, chosen before `PermissionPrompt` only when `parsed.kind === "capability_build"`:
  - `OwnerChatTranscript.tsx:198-200` (HUD and classic);
  - `pages/Phone.tsx:256` (phone web; same endpoint, the server records `ui`).
- **`frontend/src/pages/CapabilitiesPanel.tsx` (new)**, mounted with one line in `pages/Tools.tsx` (`ToolsPage`, L31) under the existing tools list. It shows:
  - installed capabilities with version, source, tree hash, installed time and last run;
  - **Roll back** (shown when a previous version exists) and **Uninstall** buttons;
  - the audit-chain status ("Audit log verified, 214 entries" or the error);
  - an **Export audit log** link (`/api/capabilities/audit?format=jsonl`);
  - recent asks with their outcome.
- **`frontend/src/api.ts`:** add-only types `CapabilityPromptPayload`, `CapabilitySummary`, `CapabilityAuditStatus`.
- **Android companion (S7):** in `MainActivity.kt`'s approval block (L1023-1030), one added conditional: when `approval.action` parses as a `capability_build` payload, `CapabilityApprovalCard` (new composable) renders the same fields as the desktop card with exactly two buttons, **Approve** and **Deny**, which call the existing `model.approve(taskId, token, true|false)` (`CompanionModel.kt:1201-1202`); the server maps them (§3.2). Every other payload keeps the existing "Approve this action" / "Reject" row unchanged.
- **API (S4):** `GET /api/capabilities`, `GET /api/capabilities/audit` (JSON status, or `?format=jsonl` for the raw file), `POST /api/capabilities/{id}/rollback`, `POST /api/capabilities/{id}/uninstall`, in `backend/app/api/capabilities.py` (new), registered in `main.py`.

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

Touched live UI: the task transcript (HUD and classic), Phone, the Tools page, task speech.

| Surface | Existing behaviour kept? | Addition |
| --- | --- | --- |
| `OwnerChatTranscript` confirm area (`:198-200`) | **Yes.** Every existing payload kind still renders `PermissionPrompt` with the same props. The new branch is taken only for `kind === "capability_build"`, a kind no backend emits today. | `<CapabilityPrompt …/>` for that kind |
| `PermissionPrompt.tsx` | **Yes, file not edited** | — |
| RFC-0110 modal (`PendingApprovalHost`, `App.tsx:147-150`) | **Yes, not edited.** Capability payloads carry no `pending_id`, so the modal never sees them. | — |
| Phone confirm (`Phone.tsx:256`) | **Yes.** Same rule as the transcript. | the same conditional |
| `useTaskSpeech` / `chat_tts` | **Yes, unchanged** | The ask is an ordinary `chat_tts` with title "New capability" (≠ "Speak reply") |
| RFC-0225 `EngineNotices` chip | **Yes, unchanged** | The ask appears as an `engine_notice` titled "New capability"; RFC-0225's controller renders any title |
| `ToolsPage` (L31) | **Yes.** The list, toggles and every row are untouched. | One mount line for `<CapabilitiesPanel />` below the list |
| Task activity / prompt steps (RFC-0231 S2/S6) | **Yes** | Install and build children appear as ordinary tasks with seeded steps |
| Android approval block (`MainActivity.kt:1023-1030`) | **Yes.** Every existing payload keeps the "Approve this action" / "Reject" row. | `CapabilityApprovalCard` only for `capability_build` payloads |
| Persona, presence, WebGL | **Not touched** (Astra) | — |

Nothing existing is removed, renamed or re-styled. The behaviour changes for existing flows are the approval-window pause (§3.4), which runs only while a capability ask is open, and the install guard (§3.5), which refuses package, model, image and repository installs that today run as plain internet use.

### Stub rule

Every function named here ships complete, with tests. Not allowed:
- `TODO` or `NotImplementedError`;
- `except Exception: pass` around any install, sandbox or audit step;
- a catalog entry with a placeholder hash or `latest` tag;
- a sandbox backend that "runs anyway" when unavailable;
- a status that nothing sets;
- a button whose endpoint is missing;
- a test that skips on CI (the sandbox steps fail on `SKIPPED`, like the RFC-0198 LTA step in `pr-tests.yml`).

---

## Reconciliation

| With | Rule |
| --- | --- |
| **RFC-0211 / #670** (scheduler, `resource_hold`, Away Mode, merge and build) | Build children are persisted `Task` rows before dispatch, so #670's upcoming-task list shows them when it lands, with no second queue. Build-kind children use the coder model, so while #670's `DevelopmentConfig.resource_hold` (`development_scheduler.py:28`, checked at L279-280 and L405) names Ollama, `start_build` defers with the event "Waiting for the scheduler's model hold" (the same rule as RFC-0231 §Reconciliation). Install children use no model and are not held. Away Mode's standing authorization never approves a capability (§3.2) and never merges or builds a new dependency (§3.4.2, enforced by `dependency_gate.require_for_publication`, with the worker's `verification` blocking `review_ready`). #670's `development_worker` process honours the approval window through `bind_worker_process` (§3.4.1). For both obligations, whichever of 0233-S3 and #670 lands second adds the #670-side lines and tests (`test_development_worker_binds_capability_window_before_task`, `test_dependency_change_blocks_merge_and_build_without_grant`); 0233-S3's guards `test_development_worker_binds_capability_window` and `test_development_worker_gates_dependency_changes` enforce them. `runtime_gap` never feeds the self-development backlog. #670 also edits `tools/registry.py` (+2) and `tools/exposure.py` (+1), which is ordered in the chain below. |
| **RFC-0231 / #665** (final head in this PR's body) | Self-build children are ordinary `AgentRuntime.create_task` tasks with a keyword-only marker, exactly like `pipeline_section`. They reuse `seed_workflow` (0231-S2, on the landed #649 engine), the terminal-hook placement, `gate_outlook` (0231-S0), `resolve_target` / `preload` / restore / the `waiting` timer `start_wait_timer` / `cancel_wait_timer` (0231-S4; neither 0231 nor 0233 edits `hotswap.py`, 0225-S3 only, or `rewarm.py`, 0228-S2 only) for the build kind's code model, and the startup-recovery pattern (0231-S5). One hook goes into `large_prompt_queue.dispatch_next` (§5.8). One deliberate exception to 0231's "lease held across `waiting`" rule: a capability ask releases the 27B and re-preloads after the decision (§5.3 step 4, §5.8); 0231's own test is unaffected. The gap precheck sits after 0231-S1's precheck and the gap floor after 0231-S1's large floor; both skip on `planning.re_intent_match`. There is no second pipeline. |
| **Decision lane** (`decision/*`) | One decide per owner turn, with one extra rider on `tool_selection`. The 50 ms deadline is unchanged, rules are the fallback, and the provider can't lower an explicit request. `decision/types.py`, `reflex.py` and `surfaces.py` are not edited. |
| **Tool registry** (`tools/registry.py`, `tools/exposure.py`, `tools/capability.py`, `agent/tooling.py`) | Existing tools, `NATIVE_TOOLS` and `_init_tools` are unchanged. Capabilities are added through two add-only registry methods and a `cap_` exposure rule. `request_capability` keeps its contract and gains the optional `missing` field. |
| **RFC-0031** (`policy/approval_grant.py`) | The only grant store. Additions: `ONCE_ONLY_TOOLS`, the keyword-only `decide_via` on `decide_approval_request`, and the rule that an approving decision on a capability row is accepted only with `decide_via="task_confirm_card"` from `ui` / `mobile`, while every trusted channel can still deny (§3.2). `api/reversibility.py` is not edited; its existing `PermissionError` → 403 mapping (L110-111) covers the refusal. The evidence-grade audit is a separate append-only file (§4.6). |
| **RFC-0007 packs** | Each capability is a pack with one `tool` resource. Install, upgrade, rollback and uninstall go through `packs/manager.py` and its recovery journal. |
| **RFC-0173 Skill Forge** / RFC-0105 skill packs (`agent/skill_packs.py`) | Different layer: skills compose registered tools, and SKILL.md packs register module connector skills (`skill_packs.register_module_pack`, L36). Once `cap_<id>` is registered, Skill Forge can extract skills that use it under its own approval (`skills/approval.py`). Skill Forge never installs a capability, and this RFC never publishes a skill. |
| **MCP** (`tools/mcp_runtime.py`) | Not a capability kind: MCP servers run unsandboxed with network. Owner-configured MCP stays exactly as it is. |
| **RFC-0225 S3** | The ask, outcome and failure lines go through `owner_line(..., title="New capability")`. RFC-0225's static title test (`test_rfc0225_and_rfc0228_lines_use_default_title`) scans only RFC-0225/0228 modules, so this caller doesn't collide with it. |
| **RFC-0232 / #664** (final head in this PR's body) | The shared precedence rule applies verbatim: "A turn whose prompt contains an absolute filesystem path together with RE intent (RFC-0232's narrowed dump/extraction detection) routes to reverse engineering and is never split by RFC-0231; a path with a plain or coding question routes normally." RFC-0232-S2 enforces it as a floor in `_apply_floors`, not a `_decide_sync` early return, and names the helper `planning.re_intent_match(prompt)` (#664 L110-113). 0233 calls that helper (memo hit) in the gap precheck and forces `capability_gap = None` in its floor when it matches; a path alone never skips the gap check. 0233 adds no RE detection of its own. The RE tool and REA are capabilities that already exist and are never proposed. `agent/tool_exposure.py` is edited by 0232-S2 first, then 0233-S4 (`cap_` names in `tool_names_for`). |
| **RFC-0230 / #666** (final head in this PR's body) | Overlapping files, checked against #666's file list: `agent/loop.py` (0230-S0 latency marks, S2 first-sentence wiring, S3 `prewarm_worker` in `create_task`), `decision/owner_turn.py` (0230-S5 reflex executor) and `main.py` (0230-S0 router line, S5 async Laya restore). 0230 does not edit `config.py`, `api/tasks.py`, `db/models.py`, `api/settings.py`, `rules.py`, `request_routing.py`, `tools/*`, `policy/*`, `mobile/*`, Android or any frontend file this RFC edits. 0230's slices go first on `loop.py` and `owner_turn.py`. 0230-S5 runs `_decide_sync` on a dedicated one-worker reflex executor (#666 §S5); the gap precheck is sync, reads only the `re_intent_match` memo, adds no await, and runs in `decide_owner_turn` before that executor is used (after 0231's `large_precheck`, outside the 50 ms budget); its result is passed into `_decide_sync` and `_apply_floors` by keyword, so the busy and timeout paths, which go through `_apply_floors`, still apply the gap floor. 0230-S0's `TurnTrace` marks in `create_task` are kept; the 0233 decide-time ask is published after `decide_done`. |
| **#648 / #649 (landed)** | #649's prompt-step engine is reused unchanged (`task_workflow.py`, `TaskPromptStep`, `prompt_steps` in `get_task`); 0233 adds no workflow code and edits no #649 function. `tests/test_rfc0224_task_workflow.py` is not edited. #648 touches none of 0233's files beyond line shifts. |
| **#661** (landed `bd2558bd`) | Capability inputs use #661's `reverse_engineering.store.admit_allowed_target` → link/reparse refusal → `resolve_admitted_target`, always with `settings.allowed_directories` (§4.2). 0233 imports them unchanged and never edits `store.py`. #661 has landed, so this dependency is met. |
| **RFC-0079 computer permissions** (`policy/computer_permissions.py`) | One new catalog entry, `software.install` (default `deny`, never grantable except as `deny`), added by the install guard (§3.5). `network.internet` and every other entry keep their defaults and classification. |
| **Android companion** (`android/`, RFC-0123 / RFC-0204) | The phone approves through the existing token + payload-hash route (`api/companion.py:319-321` → `mobile/service.approve`); S3 maps a capability payload onto `origin_channel="mobile"`, `allow_once` / `deny` and `expected_payload_hash`; S7 adds the card. No new endpoint. |

---

## Slices (one ticket each, one developer each, fast off)

Every backend test file below runs in the `pytest` job's existing step "Run full backend suite" (`python -m pytest -q -rs`, `pr-tests.yml:94-95`). Slice-specific CI steps are listed per slice.

### S1: Catalog, capability index, gap rider

**Model:** Grok 4.5 · **Depends:** RFC-0232 S2 (#664: `planning.re_intent_match` and the RE floor in `_apply_floors`) and RFC-0231 S1 (the last prior owner of `owner_turn.py` / `rules.py`; order #649 → 0218-S3b → 0230-S5 → 0232-S2 → 0231-S1 → 0233-S1)

| File | Change |
| --- | --- |
| `backend/app/capability_build/__init__.py` (new) | package |
| `backend/app/capability_build/catalog.json` (new) | v1 entries (§1), real pins, every `size_bytes` ≤ 512 MiB |
| `backend/app/capability_build/catalog.py` (new) | load and validate (kinds, https, host allowlist, 64-hex hashes, no `latest`, `size_bytes` ≤ `CAPABILITY_MAX_DOWNLOAD_BYTES`), `ALLOWED_SOURCE_HOSTS_DIRECT`, `GITHUB_REDIRECT_HOSTS`, `ALLOWED_SOURCE_HOSTS`, alias and trigger lookup |
| `backend/app/capability_build/index.py` (new) | `CAPABILITY_INDEX`, `rebuild()` |
| `backend/app/decision/capability_gap.py` (new) | G1-G3, `CapabilityGapIntent`, precheck (calls `planning.re_intent_match`), `intent_from_result` |
| `backend/app/decision/owner_turn.py` | `gap_precheck` in `decide_owner_turn` inside the `try` at `:567`, right after 0231-S1's `large_precheck`, passed as `gap_precheck=` to `_decide_sync` (rider on the one `decide()`, count unchanged), `_deadline_rules_result` and `_apply_floors` at `:461` / `:600` / `:623`; gap floor in `_apply_floors` after 0232-S2's RE floor and 0231-S1's large floor; rider answer in `_deadline_rules_result`; `capability_gap` field on `OwnerTurnDecision` (L146-158) |
| `backend/app/decision/adapters/rules.py` | `capability_gap` rider branch next to the persona branch (L238) |
| `backend/app/agent/request_routing.py` | pass-through |
| `backend/app/config.py` | `CapabilityBuildSettings` (§6) |
| `backend/app/api/settings.py` | expose the block |
| `scripts/verify_capability_catalog.py` (new) | downloads every catalog source through `gated_download_to` and checks size and sha256, plus `docker manifest inspect` for the image digest; exits non-zero on any mismatch |
| `tests/test_rfc0233_gap_decision.py` (new) | below |
| `tests/test_rfc0233_catalog.py` (new) | below |
| `.github/workflows/pr-tests.yml` | append the step `Capability catalog pins (RFC-0233 S1)` at the end of the `pytest` job: `git fetch --no-tags --depth=1 origin ${{ github.base_ref }}`, then run `python scripts/verify_capability_catalog.py` when `git diff --name-only FETCH_HEAD HEAD -- backend/app/capability_build/catalog.json` is non-empty, else print "catalog unchanged". Until S2 has merged, the script calls `gated_download_to` without the new keywords and checks size and hash after the download; S2 switches it to the capped call. |

Tests (`tests/test_rfc0233_gap_decision.py`):
- `test_g1_implicit_gap_fires_for_unavailable_entry`;
- `test_g1_silent_when_available`;
- `test_g2_explicit_install_any_route`;
- `test_g3_explicit_build_en_nl`;
- `test_provider_cannot_invent_id_or_lower_explicit`;
- `test_provider_switches_only_at_075`;
- `test_deadline_fallback_is_rules_through_apply_floors` (Timeout and Exception paths, L600 and L623: an explicit G2 survives);
- `test_one_decide_per_turn` (a `decide` spy is called exactly once per turn, with and without the rider, and on the RE-intent turn);
- `test_path_plus_re_intent_never_gets_rider`: `D:\cases\x full file system extraction of my phone: which accounts are on it? Install ffmpeg first.` (explicit wording from #664's list, `full file system extraction`; the probe runs with `require_marker=False` and is stood in as `present`) and a `tmp_path` dump dir containing `data/data` with `ffs which accounts are on the phone? Install ffmpeg first.` (weak match + probe) → route `reverse engineering`, `capability_gap is None`, no `capability_gap` question in the one decide call, also on the deadline-fallback path;
- `test_non_owner_re_phrases_still_get_gap_check` (parametrized over D2's five: `C:\code\tool what does the forensic image parser do?`, `C:\code\backup where is the full file system image backup written?`, `C:\code\mdm how is the extraction of the device id done?`, `C:\code\agent what does the device extraction module do?`, `C:\Users\taco\proj ffs of the tests fail again, why?`, with a floor rule firing and the probe stubbed to `present`): `re_intent_match` is `None` and the gap rider is appended; the four owner phrases (`reverse engineer`, `full FFS`, `full file system extraction`, `extraction of my phone`) skip it, and `FFS of my Pixel` with the probe returning `absent` gets the gap check (weak, unconfirmed).
- `test_gap_precheck_outside_decide_budget_and_reaches_floors`: injected clock; `gap_precheck` runs after `large_precheck` inside the `try`, is not charged to the 50 ms budget, and the same object reaches `_apply_floors` on the normal, timeout and exception paths.
- `test_path_with_coding_question_still_gets_gap_check`: `C:\code\etl what does the extraction step do?` → `planning.re_intent_match` returns `None`, the turn routes normally, and the gap precheck runs (spy called once, not skipped); the same prompt with " Install ffmpeg first." appended → `capability_gap.verdict == "gap"`, `capability_id == "ffmpeg"`, `trigger == "explicit"` (also parametrized with RFC-0232's named negatives `C:\Users\taco\proj ffs why does the build fail?` and `C:\code\app what does the dump() function do?`);
- `test_gap_floor_cleared_when_re_floor_fires`;
- `test_security_role_excluded`;
- `test_disabled_is_byte_identical`;
- `test_precheck_reads_no_disk` (the test warms the `re_intent_match` memo for the prompt, as the baseline route does in production, then patches `open` / `Path.read_text` / `os.stat` to raise during `_decide_sync`).

Tests (`tests/test_rfc0233_catalog.py`):
- `test_catalog_rejects_http_latest_unknown_host_missing_hash_oversize`;
- `test_every_entry_has_sealed_permissions_and_64hex`;
- `test_redirect_hosts_only_as_hops`.

### S2: Sealed sandbox, evidence guard, input admission, broker fetch, audit chain

**Model:** Grok 4.6 · **Depends:** S1, #661 (landed `bd2558bd`: `admit_allowed_target`, `resolve_admitted_target`)

| File | Change |
| --- | --- |
| `backend/app/capability_build/sandbox.py` (new) | `run_sealed`, backend probe, `win_appcontainer` (ctypes: AppContainer profile, ACL grant, handle list, Job Object) and `docker` |
| `backend/app/capability_build/inputs.py` (new) | `admit_input` (§4.2): #661 gate, link/reparse refusal, `resolve_admitted_target`, regular-file check; no-follow open and final-path check |
| `backend/app/capability_build/evidence.py` (new) | `evidence_roots`, `assert_not_evidence`, before/after hashing |
| `backend/app/capability_build/fetch.py` (new) | broker download through `gated_download_to(..., allowed_hosts=…, redirect_only_hosts=…, max_bytes=entry.size_bytes)`, size and sha256, safe unpack, wheel install with `--require-hashes --no-index`, digest-pinned image pull |
| `backend/app/policy/network_http.py` | add-only `allowed_hosts`, `redirect_only_hosts`, `max_bytes` keywords on `gated_download_to` (L180-221), `.partial` cleanup when one is set (§4.4) |
| `backend/app/capability_build/audit.py` (new) | append-only hash chain, `verify_chain`, export |
| `backend/app/capability_build/launcher_template.py` (new) | the fixed launcher that opens inherited handles and calls `run` |
| `scripts/verify_capability_catalog.py` | switch to the capped, host-checked call |
| `tests/test_rfc0233_sandbox_docker.py` (new) | below (real Docker) |
| `tests/test_rfc0233_sandbox_windows.py` (new) | below (real AppContainer) |
| `tests/test_rfc0233_evidence_fetch_audit.py` (new) | below |
| `.github/workflows/pr-tests.yml` | append the step `RFC-0233 sealed sandbox (Docker, no skips)` at the end of the `pytest` job (runs the Docker file with `-rs` and fails when the output contains `SKIPPED`, the same guard as the RFC-0198 LTA step); append a new job `capability-sandbox-windows` (`windows-latest`, Python 3.12, installs `backend/requirements.txt` and pytest, runs the Windows file with the same no-skip guard) |

Tests:
- Docker and Windows files, each:
  - `test_no_network_kernel` (connecting to `1.1.1.1:443` and to the ANZU loopback port both fail);
  - `test_cannot_write_evidence_root`;
  - `test_reads_input_via_readonly_handle`;
  - `test_cannot_open_input_by_path`;
  - `test_cannot_read_anzu_data_dir` (a fake `settings.json` and `private_key.sec`);
  - `test_env_has_no_secrets`;
  - `test_out_dir_writable_only`;
  - `test_runtime_and_memory_limits_kill`.
- Windows file only: `test_clipboard_blocked`, `test_reparse_input_refused_and_final_path_checked`.
- `test_rfc0233_evidence_fetch_audit.py`:
  - `test_no_backend_refuses_never_runs_unsealed`;
  - `test_evidence_hash_before_after_and_violation_disables`;
  - `test_assert_not_evidence_refuses_data_dir_under_root`;
  - `test_input_outside_missing_link_same_error` (an outside existing file, an outside missing path and an outside symlink all raise the identical `OUTSIDE_ALLOWED` text; the target is never stat'ed before admission, checked with a stat spy);
  - `test_input_admission_always_passes_allowed_directories` (never `None`; an empty list admits nothing);
  - `test_hop_outside_allowlist_aborts_before_body` (first URL and a redirect hop to a non-listed host: no body byte read, `.partial` absent);
  - `test_redirect_only_host_refused_as_first_hop`;
  - `test_oversize_stream_aborted` (a lying `content-length` and a server that streams past `max_bytes`: aborted at the cap, `.partial` deleted);
  - `test_gated_download_defaults_unchanged` (no new keyword → today's behaviour, existing caller tests still pass);
  - `test_fetch_rejects_wrong_hash_size_host_and_bad_hop`;
  - `test_unpack_rejects_traversal_and_links`;
  - `test_wheels_require_hashes_no_index`;
  - `test_audit_chain_append_verify_and_tamper_detect`;
  - `test_audit_never_truncated` (10 000 rows).

### S3: Proposals, owner approval gate, approval window, install guard, dependency gate, runtime trigger

**Model:** Grok 4.6 · **Depends:** S1, S2, RFC-0225 S3 (`owner_line`), RFC-0231 S5 (the last prior `loop.py` owner; `loop.py` order #649 → 0218-S3b → 0230-S0 → 0230-S2 → 0230-S3 → 0232-S3 → 0232-S4 → 0232-S5 → 0231-S4 → 0231-S5 → 0233-S3)

| File | Change |
| --- | --- |
| `backend/app/db/models.py` | `CapabilityProposal`, `CapabilityInstall` (§2) |
| `backend/app/capability_build/proposals.py` (new) | `propose`, `runtime_gap`, throttle and 24 h dedupe, `open_ask`, `record_decision`, `expire`, `require_grant`, expiry timer, `CapabilityDecisionRefused` |
| `backend/app/capability_build/texts.py` (new) | owner texts (§3.1) |
| `backend/app/capability_build/window.py` (new) | `approval_window_open`, `wait_closed`, `tool_allowed_in_window`, `WINDOW_SAFE_TOOLS`, `WINDOW_SAFE_ACTIONS`, marker file, `bind_worker_process` |
| `backend/app/capability_build/install_guard.py` (new) | `install_intent`, `intercept` (§3.5) |
| `backend/app/capability_build/dependency_gate.py` (new) | `DEPENDENCY_MANIFESTS`, `dependency_changes`, `open_dependency_ask`, `require_for_publication`, `DependencyApprovalRequired` (§3.4.2) |
| `backend/app/capability_build/eligibility.py` (new) | build eligibility (§5.6) |
| `backend/app/policy/approval_grant.py` | `ONCE_ONLY_TOOLS`; keyword-only `decide_via` on `decide_approval_request`; refuse `always` and any non-card approval for those tools |
| `backend/app/policy/computer_permissions.py` | `software.install` catalog entry (default `deny`); `permission_ids_for_tool` appends it on an install intent; `apply_grant` / `operator_intent_grant` refuse any non-`deny` mode for it |
| `backend/app/tools/docker_tools.py` | `DockerTool.execute` (L182): `--pull=never` on `run`, and the install guard's local-image check before `run` / `build` |
| `backend/app/agent/loop.py` | the decide-time ask in `create_task` (after RFC-0231's large branch); the `confirm_task` capability branch and its two keywords; the window wait and `install_guard.intercept` after the tool lookup (L3374-3376) and before `_permission_denied_observation` (L3377); the runtime trigger in the `request_capability` branch (L3462) |
| `backend/app/api/tasks.py` | `continue_task` refuses a capability approval (deny only, 403 otherwise); `CapabilityDecisionRefused` / `ValueError` mapping; `confirmation_payload_sha256` in `_task_dict`. No `origin_channel` field. Adds the two card endpoints `GET /api/tasks/{id}/capability-card` (plan, `card_hash`, one-time `card_token`; owner private key) and `POST /api/tasks/{id}/capability-card/decide` (§3.2) |
| `backend/app/mobile/service.py` | the capability branch in `approve` before L97 (§3.2) |
| `backend/app/tools/capability.py` | optional `missing` field and its description |
| `backend/app/agent/tooling.py` | return the unknown names in structured form for the loop (observation text unchanged) |
| `backend/app/agent/development_worker.py` (only if #670 landed first) | `bind_worker_process(Path(mission["owner_root"]))` before `AGENT.create_task` (§3.4.1); `dependency_changes` block in `verification` (§3.4.2) |
| `tests/test_rfc0211_development_scheduler.py` (only if #670 landed first) | `test_development_worker_binds_capability_window_before_task`, `test_dependency_change_blocks_merge_and_build_without_grant` |
| `tests/test_rfc0233_approval_gate.py` (new) | below |
| `tests/test_rfc0233_install_guard.py` (new) | the 13 tests in §3.5 |
| `tests/test_rfc0233_dependency_gate.py` (new) | the four 0233-side tests in §3.4.2 |

Tests (`tests/test_rfc0233_approval_gate.py`):
- `test_ask_published_via_owner_line_chat_tts_within_150ms`;
- `test_ask_never_uses_publish_owner_text`;
- `test_ask_title_new_capability_not_speak_reply`;
- `test_payload_has_no_spoken_prompt_or_pending_id`;
- `test_ask_states_what_where_permissions` (the payload and spoken text contain title, version, project, and the no-internet / read-only / case-folder words; the payload holds url, sha256, size, license and deps);
- `test_card_tap_approves_ui_and_mobile` (`POST /api/tasks/{id}/capability-card/decide` with the minted token and card hash, and the companion approve with its token → `allow_once` grant, `decided_via` `card_ui` / `card_mobile`, origin set by the server);
- `test_card_token_replay_rejected_409_desktop_and_mobile` (a second approve with the same token or the same hash → 409 on both the desktop endpoint and the companion; one grant only);
- `test_card_token_rotates_on_rerender` (a re-render mints a new token; the old one → 409);
- `test_card_token_never_in_task_dict_events_or_payload`;
- `test_forged_origin_channel_refused` (`/continue` with `origin_channel: "ui"` / `"mobile"`, the right `confirmation_payload_sha256` and `allow_once` → 403, task still waiting, no grant; the same from a client without the owner private key on the card endpoint → 401);
- `test_tool_subprocess_env_has_no_owner_key` (the env passed to `terminal`, `python`, `open_interpreter`, `code_worker` and MCP server launches has no owner private key or API token);
- `test_build_card_hash_covers_plan` (change the spec, a package version or the catalog entry after the card rendered → the approval gets 409 and nothing is granted);
- `test_card_displays_plan_desktop_phone_android` (spec summary, `spec_sha256`, modules, each package name + version + hash and the catalog entry are rendered by `CapabilityPrompt.tsx`, `Phone.tsx` and the Android card);
- `test_always_and_allow_session_refused_400`;
- `test_approve_refused_from_api_channel` (`/continue` with an approval body, and `decide_approval_request(origin_channel="api", decision="allow_once")` → 403 / `PermissionError`, task still waiting);
- `test_approve_refused_from_voice_channel` (`origin_channel="voice"`, and a chat or voice "yes" turn: no grant);
- `test_approve_refused_from_physical_channel`;
- `test_approve_refused_from_decision_inbox_channel`;
- `test_reversibility_api_cannot_allow_once_capability` (`POST /api/reversibility/pending/{id}/decide` with `allow_once` and `always` → 403; with `deny` → 200 and the proposal `denied`);
- `test_deny_accepted_from_every_trusted_channel` (parametrized over `TRUSTED_CHANNELS`);
- `test_resume_and_guest_paths_cannot_approve` (`_resume_task_with_grant` and `guest_portals` `confirm_task(task_id, True)` on a capability payload → refused, nothing granted);
- `test_untrusted_channel_refused`;
- `test_expected_payload_hash_required_on_capability_approve` (missing → 409);
- `test_stale_payload_hash_rejected_409` (the ask was replaced; the old card's hash → 409, the new ask still waiting);
- `test_confirmation_payload_sha256_in_task_dict`;
- `test_android_approve_maps_to_allow_once_mobile_with_hash` (`POST /api/companion/tasks/{id}/approve` with a valid token, `approved=true` → `confirm_task` called with `origin_channel="mobile"`, `grant_mode="allow_once"`, the snapshot hash; grant created);
- `test_android_reject_maps_to_deny`;
- `test_android_stale_card_rejected` (payload changed after the snapshot → the existing 409, nothing granted);
- `test_android_non_capability_payload_unchanged`;
- `test_deny_final_visible_audited_task_resumes_without`;
- `test_timeout_final_visible_audited` (fake clock, 15 min default);
- `test_timeout_survives_restart`;
- `test_no_step_runs_without_grant`;
- `test_no_auto_approve_path_static` (AST scan of `backend/app`: `decide_via="task_confirm_card"` only inside `confirm_task`'s capability branch);
- `test_away_mode_does_not_approve`;
- `test_window_holds_non_allowlisted_tools_and_releases` (a second task's `web_fetch` to `/continue` runs only after the simulated owner click);
- `test_window_allowlist_deny_by_default` (enumerates `REGISTRY.tools`; a synthetic tool waits);
- `test_window_holds_blender_freecad_openscad_external_ingest_git`;
- `test_window_filesystem_reads_run_writes_wait`;
- `test_window_marker_file_lifecycle`;
- `test_worker_process_honours_owner_marker` (§3.4.1);
- `test_development_worker_binds_capability_window` (§3.4.1 guard);
- `test_runtime_unknown_capability_creates_install_proposal`;
- `test_runtime_unbuildable_gives_visible_reason`;
- `test_runtime_gap_never_feeds_self_dev_backlog` (static: no import of `development_scheduler` / `development_worker` under `capability_build/`; behavioural: a source-change gap writes no backlog item);
- `test_throttle_and_24h_dedupe_explicit_bypasses`;
- `test_disabled_runtime_observation_unchanged`.

### S4: Install child, registration, rollback/uninstall, resume, 27B release for part asks, recovery, API

**Model:** Grok 4.6 · **Depends:** S3, RFC-0231 S2 (`seed_workflow`), RFC-0231 S4 (`preload`, restore, `gate_outlook` from S0) and RFC-0231 S5 (`large_prompt_queue`), RFC-0232 S2 (`agent/tool_exposure.py`)

| File | Change |
| --- | --- |
| `backend/app/capability_build/installer.py` (new) | the install child steps (§5.2), advanced with `mark_running` / `finish_current` |
| `backend/app/capability_build/queue.py` (new) | `start_build`, `on_child_terminal`, `on_parent_cancel`, `blocking`, `resume_parent`, `recover_on_startup`, the #670 hold deferral |
| `backend/app/capability_build/models.py` (new) | `spec_provider`, `on_wait` (→ `large_prompt.start_wait_timer`), `reacquire_coder` (→ `cancel_wait_timer`, re-preload only if the timer fired) (§5.3, §5.8) |
| `backend/app/capability_build/packs.py` (new) | pack manifest for `capability.<id>`; install, upgrade, rollback and uninstall via `packs/manager.py` |
| `backend/app/tools/sandboxed_capability.py` (new) | `SandboxedCapabilityTool` (inputs through `inputs.admit_input`) |
| `backend/app/tools/registry.py` | `register_capability`, `unregister_capability` (add-only) |
| `backend/app/tools/exposure.py` | `cap_` acceptance in `grant` and `ensure_named_tool` |
| `backend/app/agent/tool_exposure.py` | `tool_names_for` (L173) adds matching registered `cap_` tools and keeps a registered `cap_` name from `requested_tools` |
| `backend/app/agent/loop.py` | `capability_build` keyword in `create_task`; the deterministic child branch in `_run` (install and dependency kinds); the `capability_observation` short-circuit at the top of the `pending_tool` block (L2944); terminal and cancel hooks |
| `backend/app/agent/large_prompt_queue.py` | `dispatch_next` waits on `capability_build.queue.blocking(parent)`; a part's capability ask calls `models.on_wait(parent)` / `reacquire_coder(parent)` (§5.8), i.e. RFC-0231's own `waiting` timer |
| `backend/app/api/capabilities.py` (new) | the endpoints in §7 |
| `backend/app/api/tasks.py` | `capability` object in `get_task` (L256): open proposal summary |
| `backend/app/main.py` | router registration; `index.rebuild()` after the `tool_registry` step (L250); startup `recover_on_startup` after RFC-0231's |
| `tests/fixtures/rfc0233/` (new) | a fixture catalog: a 2 KB zip holding a `selftest` script, its real sha256 and size, and a local HTTP server fixture that serves it |
| `tests/test_rfc0233_install_lifecycle.py` (new) | below |

Tests:
- `test_install_end_to_end_fixture` (approve → fetch → verify → unpack → self-test → pack → registered → the asking task resumes with `cap_x` and calls it);
- `test_new_tool_reaches_task` (decide-time and runtime asks: after install, the resumed task's `exposed_tools` column and the tool list sent to the model contain `cap_x`, and a model call to `cap_x` executes `SandboxedCapabilityTool`);
- `test_runtime_resume_injects_observation_and_exposes_cap` (the tool message carries the stored observation; `_execute_tool` and `RequestCapabilityTool.execute` spies are never called on resume; an install-guard pause resumes the same way without re-running the command);
- `test_non_capability_pending_tool_path_unchanged`;
- `test_install_steps_advance_with_landed_workflow_api` (only `mark_running` / `finish_current` touch `TaskPromptStep` rows);
- `test_every_proposal_status_reachable` (§2.1);
- `test_every_column_has_writer_and_reader` (§2.1, static);
- `test_child_ids_stable_uuid5`;
- `test_child_no_decide_no_persona_no_ack`;
- `test_failed_hash_leaves_nothing_registered`;
- `test_failed_self_test_auto_cleans`;
- `test_rollback_restores_previous_and_rehashes`;
- `test_uninstall_removes_dir_keeps_audit`;
- `test_tree_tamper_unregisters_with_owner_line`;
- `test_run_audit_row_has_input_hashes`;
- `test_exposure_accepts_registered_cap_only`;
- `test_large_parent_waits_for_ask_then_dispatches`;
- `test_part_runtime_gap_asks_on_part_stream`;
- `test_part_ask_releases_anzu_loaded_27b_after_idle_unload_seconds` (ANZU-loaded 27B: lease held at 899 fake seconds, released at 900 s; one `keep_alive` refresh at 450 s (RFC-0231's refresh while leased, every `idle_unload_seconds / 2`) and none after release; the decision afterwards re-preloads before the part resumes; a decision at 600 s cancels the timer and reloads nothing);
- `test_part_ask_never_unloads_owner_loaded_27b`;
- `test_cancel_asking_cancels_ask_and_child`;
- `test_recovery_expire_resume_reregister`;
- `test_resource_hold_defers_build_kind_only`;
- `test_capability_payload_in_get_task`;
- `test_api_rollback_uninstall_audit_export`.

### S5: Build kind: spec model and fact-checks, workshop, build policy, code model, register gate

**Model:** Grok 4.6 · **Depends:** S4, RFC-0231 S0 (`anzu-coder-27b` profile and `MODEL_CATALOG` entry, `gate_outlook`) and S4 (`resolve_target` / `preload` / restore)

| File | Change |
| --- | --- |
| `backend/app/capability_build/spec_writer.py` (new) | `write_spec` on the 9B (`models.spec_provider`), one regeneration, `failed` + owner line on the second failure |
| `backend/app/capability_build/spec_check.py` (new) | the deterministic spec fact-check (§5.3 step 2) |
| `backend/app/capability_build/fixtures.py` (new) | fixture generators and stdlib format probes (`sqlite`, `zip`, `json`, `csv`, `xml`, `text`) |
| `backend/app/capability_build/workshop.py` (new) | `CapabilityWorkshopTool` (write within the build dir; run tests sealed); exposed only to build children |
| `backend/app/capability_build/build_policy.py` (new) | AST scan, `BUILD_FORBIDDEN_MODULES`, secret scan, size caps |
| `backend/app/capability_build/builder.py` (new) | build-child workflow seeding (`implement` / `test` / `verify` / landed `fact_check` / `output_check`), round cap, code-model choice with the 9B fallback, `output_check`, `request_register` (releases the 27B first), `register`, `discard`, `tree_sha256` |
| `backend/app/tools/registry.py` | register the workshop tool (not in `NATIVE_TOOLS`, not in any task class) |
| `tests/test_rfc0233_build_kind.py` (new) | below |
| `tests/test_rfc0233_spec_check.py` (new) | below |

Tests (`tests/test_rfc0233_spec_check.py`):
- `test_build_spec_generated_by_default_9b` (the provider is `OpenAICompatProvider` at `127.0.0.1:1234/v1` with model `qwen3.5-9b-defiant-fable-uncensored`; `MANAGER.chat` and the 27B are never called for the spec or step prompts);
- `test_spec_model_missing_no_proposal_visible_line`;
- `test_spec_check_rejects_unknown_or_forbidden_module`;
- `test_spec_check_format_claims_against_fixtures`;
- `test_spec_check_expected_facts_derived_from_fixture`;
- `test_spec_check_catalog_title_version_permission_claims`;
- `test_fact_check_failure_blocks_ask` (two failures → `failed`, owner line, no parked request, no card);
- `test_gate1_binds_checked_spec_hash` (a spec edited after the check → `require_grant` refuses);
- `test_spec_writer_takes_no_lease_and_schedules_no_rewarm`.

Tests (`tests/test_rfc0233_build_kind.py`):
- `test_build_ask_then_register_ask_two_grants`;
- `test_build_workflow_keeps_landed_fact_check_step` (the seeded `fact_check` row's prompt equals `REVIEW_STEPS[1]`);
- `test_output_check_fails_build_on_wrong_output` (and passes on correct output; no register ask after a failure);
- `test_code_runs_on_anzu_coder_27b` (`preload` targets `anzu-coder-27b` on Ollama `127.0.0.1:11434`);
- `test_gate_refused_build_runs_on_9b_with_owner_line` (outlook `refuse` and a real step-5 refusal: the code rounds use `spec_provider`, the owner line is published once with title "New capability", the build completes);
- `test_register_wait_follows_0231_waiting_rule` (ANZU-loaded 27B: lease kept until `idle_unload_seconds`, then released through `large_prompt.start_wait_timer`; `keep_alive` refreshed at 450 s while leased and never after release; approval after the timer re-preloads only if work remains);
- `test_owner_loaded_27b_not_unloaded_during_wait`;
- `test_reload_after_approval_only_when_work_remains`;
- `test_9b_idle_unload_not_blocked_during_ask` (RFC-0228's idle-unload path for the 9B runs during a 20 fake-minute register wait);
- `test_workshop_cannot_write_outside_build_dir`;
- `test_build_child_tools_are_workshop_only`;
- `test_policy_rejects_socket_subprocess_ctypes_eval_dynamic_import`;
- `test_secret_in_code_fails_build`;
- `test_three_rounds_then_visible_failure`;
- `test_register_denied_deletes_build_dir`;
- `test_registered_built_tool_runs_sealed_with_handles`;
- `test_build_never_receives_evidence_paths`;
- `test_not_buildable_spec_refused_with_word`.

### S6: Capability prompt (desktop and phone web) and Capabilities panel

**Model:** Composer 2.5 · **Depends:** S4 (API), S5 (register payload), RFC-0231 S6 (`api.ts` order)

| File | Change |
| --- | --- |
| `frontend/src/chat/CapabilityPrompt.tsx` (new) | the card (§3.1, §7) |
| `frontend/src/chat/capabilityPrompt.ts` (new) | plain-TS controller (payload parse, decide request with `expected_payload_hash`, local-time formatting), imported by the node tests |
| `frontend/src/chat/OwnerChatTranscript.tsx` | one conditional at `:198-200` |
| `frontend/src/pages/Phone.tsx` | one conditional at `:255-258` |
| `frontend/src/pages/CapabilitiesPanel.tsx` (new) | the panel (§7) |
| `frontend/src/pages/Tools.tsx` | one mount line |
| `frontend/src/api.ts` | add-only types (`confirmation_payload_sha256` on the task type, `CapabilityPromptPayload`, `CapabilitySummary`, `CapabilityAuditStatus`) |
| `frontend/capability-prompt.test.mjs` (new) | below |
| `frontend/capabilities-panel.test.mjs` (new) | below |
| `frontend/package.json` | append `test:capabilities` (runs both files with `node --test`) |
| `.github/workflows/pr-tests.yml` | append the step `Capability prompt and panel tests (RFC-0233 S6)` → `npm run test:capabilities` at the end of `frontend-build`, after RFC-0231 S6's step |

Tests (`frontend/capability-prompt.test.mjs`):
- `capability payload renders card not PermissionPrompt`;
- `other payloads still render PermissionPrompt` (static, on both render sites);
- `only approve and deny exist, no always, no microphone`;
- `approve posts allow_once with expected_payload_hash and origin ui`;
- `phone posts origin mobile`;
- `hash is the one captured at render` (a task refresh with a new hash does not change the hash of the card already shown);
- `card shows url sha256 size license deps permissions expiry in local time`;
- `register gate shows code hash files lines tests`;
- `dependency gate shows mission diff hash and manifest lines`;
- `server error text is shown` (403 and 409 bodies);
- `card does not speak` (no `speakChatReply` / `queueChatSpeech` import).

Tests (`frontend/capabilities-panel.test.mjs`):
- `lists installs with hash and version`;
- `rollback only when previous exists`;
- `uninstall posts endpoint`;
- `audit status ok and broken`;
- `export link points at jsonl`;
- `recent asks show outcome and decided_via`;
- `Tools page still renders its existing list` (static).

**Live audit** (on Taco's PC; numbers and screenshots recorded in the PR): ask "what's in this SQLite database: <case path>\msgstore.db" with `sqlite_cli` absent. Verify:
- the ask is heard, and the card shows source, hash and permissions on the desktop and on the Android companion;
- a spoken "yes" does not approve; deny → the line is heard and the task finishes saying what it couldn't do;
- repeat and approve on the phone → installed, and the query answers;
- the audit log verifies, and the run row shows identical before/after hashes of `msgstore.db`;
- uninstall from the panel works.

### S7: Android capability card

**Model:** Composer 2.5 · **Depends:** S3 (the `mobile/service.approve` mapping and payload), S5 (register payload)

| File | Change |
| --- | --- |
| `android/app/src/main/java/com/jarvis/companion/CapabilityApproval.kt` (new) | pure parser: `parseCapabilityApproval(action: String): CapabilityApproval?` (returns `null` unless `kind == "capability_build"`), plain-word permission lines, expiry in the phone's local time |
| `android/app/src/main/java/com/jarvis/companion/CapabilityApprovalCard.kt` (new) | the composable: the §3.1 fields, buttons **Approve** and **Deny** only, calling `model.approve(taskId, token, true|false)` |
| `android/app/src/main/java/com/jarvis/companion/MainActivity.kt` | one conditional in the approval block (L1023-1030): `parseCapabilityApproval(approval.optString("action"))?.let { CapabilityApprovalCard(...) } ?: <existing row unchanged>` |
| `android/app/src/test/java/com/jarvis/companion/CapabilityApprovalTest.kt` (new) | below |

Tests (`CapabilityApprovalTest`, run by the existing `:app:testDebugUnitTest` in `android-companion.yml`'s "Assemble debug + release (generic companion)" step; that workflow already triggers on `android/**`):
- `capabilityPayloadParses`;
- `otherPayloadReturnsNullSoExistingRowRenders`;
- `onlyApproveAndDenyLabels` (no "always", no "this session");
- `showsUrlHashSizeLicenseDepsPermissionsAndLocalExpiry`;
- `registerAndDependencyGatesShowTheirFields`;
- `malformedPayloadReturnsNull`.

## Ownership chains (handoff order on shared files)

The orders on `loop.py` and `owner_turn.py` are the CoS ruling (2026-10-20). The `loop.py` row is identical to #664 (RFC-0232; final head in this PR's body) (L349), #665 (RFC-0231; final head in this PR's body) (L858) and #666 (RFC-0230; final head in this PR's body) (L294), including 0232-S5's place after 0232-S4 and before 0231-S4. The `owner_turn.py` row (#649 → 0218-S3b → 0230-S5 → 0232-S2 → 0231-S1 → 0233-S1) is identical to #664 (L348), #665 (L859) and #666 (L295). 0233-S1 is last on that file in both readings, so it merges after 0218-S3b whenever that lands. The `main.py` order puts RFC-0225 first (CoS) and follows #652 (RFC-0225; final head in this PR's body), where 0225-S1 does not edit `main.py` and the chain 0225-S2 → S3 → 0230-S0 → S5 → 0231-S0 → S5 → 0233-S4 → #670 is at L497. A later slice merges `development` into its branch (merge commit) and ports around the earlier hunk, citing it; no rebase, no force-push.

| File | Order |
| --- | --- |
| `backend/app/agent/loop.py` | #649 (landed) → 0218-S3b → 0230-S0 → 0230-S2 → 0230-S3 → 0232-S3 → 0232-S4 → 0232-S5 → 0231-S4 → 0231-S5 → 0233-S3 → 0233-S4 (#670 does not edit it) |
| `backend/app/decision/owner_turn.py` | #649 (landed) → 0218-S3b (not landed) → 0230-S5 → 0232-S2 → 0231-S1 → 0233-S1 |
| `backend/app/decision/adapters/rules.py` | 0231-S1 → 0233-S1 (0230 and 0232 do not edit it) |
| `backend/app/agent/request_routing.py` | 0231-S1 → 0233-S1 (pass-through only; 0230 and 0232 do not edit it) |
| `backend/app/config.py` | #649 (landed) → 0228-S1 → 0228-S2 → 0231-S2 → 0233-S1 → #670 (0230 and 0232 do not edit it) |
| `backend/app/api/settings.py` | #649 (landed) → 0231-S2 → 0233-S1 |
| `backend/app/db/models.py` | #649 (landed) → 0231-S2 → 0233-S3 (0230 and 0232 do not edit it) |
| `backend/app/api/tasks.py` | #649 (landed) → 0231-S5 → 0233-S3 → 0233-S4 (0230 and 0232 do not edit it) |
| `backend/app/main.py` | 0225-S2 → 0225-S3 → 0230-S0 → 0230-S5 → 0231-S0 → 0231-S5 → 0233-S4 → #670 (RFC-0211, supersedes #585; lands last; 0232 does not edit it) |
| `frontend/src/App.tsx` | 0225-S5 → 0225-S3 → #670 (0230-0233 do not edit it) |
| `backend/app/agent/tool_exposure.py` | 0232-S2 → 0233-S4 (0230 and 0231 do not edit it) |
| `backend/app/agent/task_workflow.py` | #649 (landed, created it) → 0231-S2. 0233 does not edit it |
| `backend/app/agent/large_prompt_queue.py` | 0231-S5 (creates it) → 0233-S4 |
| `backend/app/agent/development_worker.py`, `tests/test_rfc0211_development_scheduler.py` | #670 creates them. Whichever of 0233-S3 and #670 lands second adds the window bind and the dependency block plus their two tests (§3.4.1, §3.4.2); with #670 landing last, that is #670 |
| `backend/app/tools/registry.py` | 0233-S4 → 0233-S5 → #670 (+2: `self_development` registration) |
| `backend/app/tools/exposure.py` | 0233-S4 → #670 (+1) |
| `backend/app/policy/network_http.py` | 0233-S2 only |
| `backend/app/policy/approval_grant.py`, `backend/app/policy/computer_permissions.py`, `backend/app/tools/docker_tools.py`, `backend/app/mobile/service.py`, `backend/app/tools/capability.py`, `backend/app/agent/tooling.py` | 0233-S3 only (no open RFC edits them) |
| `frontend/src/api.ts` | 0218-S3 → 0231-S6 → 0233-S6 |
| `frontend/src/chat/OwnerChatTranscript.tsx`, `frontend/src/pages/Phone.tsx`, `frontend/src/pages/Tools.tsx` | 0233-S6 only (0230, 0231 and 0232 do not edit them) |
| `android/app/src/main/java/com/jarvis/companion/MainActivity.kt` | 0233-S7 only among the open RFCs in this batch |
| `frontend/package.json`, `.github/workflows/pr-tests.yml` | append-only, any order; on a conflict merge `development` in (merge commit) |

## Ticket cards

| ID | Title | Model | Depends |
| --- | --- | --- | --- |
| 0233-S1 | Catalog, capability index, gap rider | Grok 4.5 | 0232-S2, 0231-S1 |
| 0233-S2 | Sealed sandbox, evidence guard, input admission, broker fetch, audit chain | Grok 4.6 | S1, #661 (landed) |
| 0233-S3 | Proposals, owner approval gate, approval window, install guard, dependency gate, runtime trigger | Grok 4.6 | S1, S2, 0225-S3, 0231-S5 |
| 0233-S4 | Install child, registration, rollback/uninstall, resume, 27B release for part asks, recovery, API | Grok 4.6 | S3, 0231-S2, 0231-S4, 0231-S5, 0232-S2 |
| 0233-S5 | Build kind: spec model and fact-checks, workshop, build policy, code model, register gate | Grok 4.6 | S4, 0231-S0, 0231-S4 |
| 0233-S6 | Capability prompt (desktop and phone web) and Capabilities panel | Composer 2.5 | S4, S5, 0231-S6 |
| 0233-S7 | Android capability card | Composer 2.5 | S3, S5 |

All seven run with fast mode off. Each slice header above lists exactly the dependencies in its card.

## Overall acceptance

- [ ] A request that needs a missing catalog capability produces one spoken and shown ask on the task stream (`chat_tts` via `owner_line`) within 150 ms of the decision. The ask names what, from where (URL and hash on the card) and with which permissions.
- [ ] Nothing is downloaded, executed or registered without an `allow_once` grant from a tap on the hash-bound card (desktop or Android). `always` is impossible; voice, chat, API, physical and inbox channels can deny but never approve; a stale card is refused; and every non-allow-listed ANZU tool waits while an ask is open.
- [ ] No model tool can install a package, model, image or repository: every such command is refused and, for a catalog entry, turned into the same ask. #670 can't merge or build a new dependency without a card grant, and never in Away Mode.
- [ ] Build specs and prompts come from the 9B and pass the deterministic fact-check before any ask; the built tool's output is checked before it is offered; code runs on `anzu-coder-27b` or, when the VRAM gate refuses, on the 9B with an honest owner line; the 27B is released while the owner decides.
- [ ] Denial and timeout are final, spoken, audited, and the task finishes saying what it couldn't do.
- [ ] Installed and built tools run sealed: no network, files-only read-only inputs, no secrets, never a write to an evidence root, and before/after input hashes in the audit log.
- [ ] The audit log is append-only, hash-chained, verifiable and exportable. Rollback and uninstall work from the panel.
- [ ] With `capability_build.enabled=false`, behaviour is identical to today.

## Out of scope

- Persona, presence, WebGL, morph and voice choice (Astra).
- Network-using capabilities, MCP servers, installers (MSI/EXE), and packages from an index (the install guard refuses them; it never installs them).
- Directory inputs for capability tools.
- Voice approval (voice can deny only).
- Changes to ANZU's own source (RFC-0211).
- A catalog editor UI.

## Risks

- **AppContainer quirks with native binaries** (for example a DLL outside the granted dirs). Mitigation: the self-test runs sealed before registration, so a capability that can't run sealed is never registered, and the failure line names it. The catalog is curated with that in mind.
- **The approval window pauses other tasks' tools for up to 15 minutes**, and with the deny-by-default allow-list that includes RE and coding tools. Mitigation: asks are rare and throttled (3 per hour), the pause is visible on each held task, and it ends the moment the owner decides.
- **The install guard refuses installs the owner may have wanted the model to run.** Mitigation: the refusal is visible, catalog entries become a normal ask, and the owner can still install anything themselves outside ANZU.
- **An ask that outlasts `idle_unload_seconds` costs a reload after approval.** Mitigation: register needs no model, so a plain approval reloads nothing; only remaining work re-preloads, through the same gate; an ask answered within `idle_unload_seconds` reloads nothing.
- **Hashing very large case files is slow.** Mitigation: the > 4 GiB partial-hash rule, marked as partial in the audit row. Kernel read-only plus the share mode are the primary guarantee.
- **Catalog pins go stale.** Mitigation: updating a pin is a reviewed PR, and the S1 CI step verifies it. An installed older version keeps working.
- **Rollback and uninstall endpoints are reachable from loopback** like every other ANZU API. They only remove ANZU-owned files, are audited, and never install or run anything, so they don't weaken the approval gate.
- **Collisions in `loop.py`.** Mitigation: the strict ownership chain above.
