# RFC-0233: Capability-gap self-build (detect, propose, owner-approved install or build, sandboxed, audited)

**Status:** accepted
**Priority:** P1 (Taco ask, relayed by Chief of Staff 2026-10-20; queued after RFC-0231)
**Author:** Jarvis Architect
**Date:** 2026-10-20
**Traced on:** `development` @ `11b264a7`. Open PRs pinned: #585 (RFC-0211) @ `f412dad`, #652 (RFC-0225) @ `916cf25`, #663 (RFC-0218 delivery fix) @ `c5db314`, #664 (RFC-0232) @ `5cdd01f`, #665 (RFC-0231) @ `9084e7c`. Drafts #648 @ `b942bcd` and #649 @ `edb4685` touch none of the files this RFC edits for gap detection or registration (checked: no hunk in `tools/capability.py`, `tools/exposure.py`, `tools/registry.py`, `agent/tooling.py`, `policy/approval_grant.py`, `packs/`, `skills/`), so nothing is ported from them.

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
- [RFC-0231](0231-large-prompt-pipeline.md) (#665): child tasks through `AgentRuntime.create_task` with a keyword-only marker, `task_workflow.seed_workflow`, the terminal hook next to `advance_intake_chain`, `resolve_target` / `preload`, startup recovery.
- [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) (#652) S3: `engine_coexistence.owner_line(...)`, the only owner-line channel.
- [RFC-0031](0031-reversibility-first-action-gates.md): `policy/approval_grant.py`, the unforgeable human grant store.
- [RFC-0007](0007-domain-workspace-packs.md): `packs/manager.py` install / rollback / uninstall with the recovery journal.
- [RFC-0026](0026-execution-phase-and-verifier-observability.md) / [RFC-0029](0029-transactional-durable-execution.md): durable tasks.

**Reconciles with (in flight):** RFC-0211 / #585 (scheduler, `resource_hold`, Away Mode), RFC-0232 / #664 (FFS/APK path routing owns its turns), RFC-0230 (content unknown at time of writing; its slices go first on every shared file).

**Astra boundary:** persona, WebGL, presence, morph and appearance are out of scope. This RFC emits no persona events and edits no persona or presence file.

Some links point at RFC files that live only on their open PRs. They resolve once those PRs land. This PR is **specs-only**.

---

## Problem

Verified on `development` @ `11b264a7`.

1. **A missing capability is a silent dead end.**
   - The model's escape hatch is `request_capability` (`tools/capability.py:9-64`). When it names something that isn't a registered tool, `ToolExposure.grant` returns `Unknown capability … Known: …` (`tools/exposure.py:150-156`), and the loop's `apply_capability_request` returns the observation "No new tools were added. … Unknown capabilities: …" (`agent/tooling.py:57-90`). The model then improvises (usually a terminal or Python attempt) or gives up. The owner is never told what was missing and is never offered a way to get it.
   - Calling a tool that doesn't exist ends in `Unknown tool {name}` (`tools/registry.py:182-184`), also invisible to the owner.
2. **The decide never asks "can ANZU do this at all?"** `OWNER_TURN_QUESTIONS` (`decision/owner_turn.py:46-72`) has `request_route` and `reply_shape`. RFC-0218 adds the persona rider (`_decide_sync`, L399-449), RFC-0231 adds the large-prompt riders. Nothing compares the request against the capabilities ANZU actually has.
3. **The tool registry is static.** `ToolRegistry._init_tools` builds a fixed list (`tools/registry.py:59-101`). `NATIVE_TOOLS` is a fixed tuple (`tools/exposure.py:97`), and `ensure_named_tool` refuses anything outside it except `mcp_*` (L172-182). There is no path to add a tool at runtime other than an owner-configured MCP server, which runs unsandboxed (`tools/mcp_runtime.py:89 prepare_stdio_launch`).
4. **Pieces exist, but nothing joins them:**
   - **Grants:** `policy/approval_grant.py` (RFC-0031) gives trusted-channel grants (`TRUSTED_CHANNELS`, L22) with a pending store, expiry (L181-209) and `decide_approval_request` (L212-339). It also allows `always` (L236-237, L386-407), which must never apply to installing or running new code. Its audit is capped at 500 rows (`_MAX_AUDIT`, L30, trimmed in `_save` L78-83), which is not an evidence-grade log.
   - **Packs:** `packs/manager.py` (RFC-0007) installs, rolls back and uninstalls packs with a recovery journal (`install_pack` L336-394, `rollback_pack` L471-513, `uninstall_pack` L516-547), and `tool` is already a resource type (`packs/schema.py:10-21`). No tool is ever installed through it.
   - **Skill Forge:** `skills/` (RFC-0173) turns verified traces into skills: "No automatic publication" (`skills/approval.py:1`), effective permissions = declaration ∩ profile ∩ task ∩ node (`skills/permissions.py:1`). Skills compose existing tools. They can't supply a missing binary.
   - **Downloads:** `policy/network_http.gated_download_to` (L180) re-checks permissions on every redirect hop. `runtime_install.py` downloads llama.cpp from a pinned tag (L40-43) and has `_sha256` (L235). `modules/catalog_download.py` only clones allowlisted GitHub URLs (L25, L205-222).
   - **Sandbox:** `agent/local_harness.sandbox_available()` (L148) probes for Docker. `reflex_loop/sandbox.py` describes itself as "Minimal in-ticket sandbox posture … not a full port" (L1). Neither runs untrusted code.
   - **Evidence roots:** LE-gated folders (`modules/catalog_download.le_gated_roots`, L141-163), REA investigation roots (`security/rea_paths.configured_investigation_roots`, L55-72) and successful LTA extract dirs (`rea_paths.succeeded_lta_extract_dirs`, L100). No common "evidence path" notion protects them from a new tool.
5. **Anything running as the owner on this PC can approve.**
   - Loopback requests skip auth (`auth.is_auth_required_for_request`, `auth.py:163-191`: `is_local_owner_host` → no key).
   - `POST /api/auth/desktop-session` hands the owner key to any loopback caller (`api/auth.py:62-72`).
   - So the model's own `terminal`, `python`, `web_fetch`, browser or computer-use tools could post `grant_mode=allow_once` to `/api/tasks/{id}/continue` (`api/tasks.py:305-321`) or click an Approve button. For ordinary RFC-0031 confirmations that risk is already accepted. For "install and run new code" it is not acceptable.

## Decision

Ship **one RFC with six implement slices**, one named model per slice and fast mode off.

```
owner turn ─► decide_owner_turn (one decide, rider capability_gap)          model calls request_capability(unknown, missing=…)
   │ gap                                                                         │ (runtime trigger)
   └───────────────┬─────────────────────────────────────────────────────────────┘
                   ▼
         proposals.propose()  ── catalog match → kind "install" │ buildable spec → kind "build" │ else → not offered (visible)
                   ▼
   asking task → waiting_for_confirmation (payload kind "capability_build") + RFC-0031 parked request
               + owner_line(ask, task_id) → engine_notice + chat_tts on the task stream     [approval window open: model tools wait]
                   ▼
   Approve (UI / phone button only, allow_once) ─► build child task (create_task(capability_build=…))
   Deny / 15 min timeout ─► final, visible, audited; the asking task continues without it
                   ▼
   child: broker fetch (pinned URL + sha256) → unpack to ANZU-owned dir → sealed self-test → [build kind: gate 2 with code hash]
        → RFC-0007 pack "capability.<id>" + REGISTRY tool cap_<id> → audit → asking task resumes with the new tool
```

### Terms

| Term | Meaning |
| --- | --- |
| **Capability** | A catalog entry (install kind) or an owner-approved built tool (build kind), exposed as one registry tool `cap_<id>`. |
| **Proposal** | One `capability_proposals` row: what, from where, which permissions, and its status. |
| **Asking task** | The task that hit the gap. It waits while the owner decides. |
| **Build child** | The ordinary task created after approval that installs or builds the capability. |
| **Approval window** | The interval in which any capability ask is open. Model-driven tool calls wait during it (§3.4). |
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

**Capability index (in memory, never read on the decide path).** `capability_build/index.py::CAPABILITY_INDEX` holds `{id: available, version}` and the compiled trigger regexes. It is rebuilt at startup (`main.py`, after the tool-registry step at L241) and after every install, rollback or uninstall. `available` means installed, registered, and integrity OK (§5.4).

**Precheck (rules, sync, under 1 ms)** in `_decide_sync` (`owner_turn.py:399-449`), next to the persona precheck (L428-433) and RFC-0231's large precheck. It produces candidates only when **all** of these hold:
- `settings.capability_build.enabled` is true;
- `security_role == ""`;
- RFC-0232's `planning.ffs_or_apk_investigation(prompt)` did **not** match. That path belongs to the RE tool, which exists.
- at least one floor rule below fires.

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
- The deadline fallback (`_deadline_rules_result`, `OWNER_TURN_DEADLINE_MS = 50`, L39) is the rules answer.

**Output:** a new field `OwnerTurnDecision.capability_gap: CapabilityGapIntent | None` (next to `persona_intent`, L156), with fields:
- `verdict` (`none` | `gap`);
- `capability_id` (catalog id, or `""` for build);
- `kind`;
- `trigger`;
- `rules_fired`;
- `decision_source`;
- `confidence`.

`request_routing` passes it through unchanged. There is still exactly one decide per owner turn.

**Runtime trigger (S3).** `request_capability` gains an optional string argument `missing` ("describe the ability you lack when no listed tool fits"). This is an add-only schema field in `tools/capability.py:18-31`. In the loop's `request_capability` branch (`agent/loop.py:3377`), when `apply_capability_request` reports unknown names, `capability_build.proposals.runtime_gap(task_id, unknown, missing)` runs:
- an alias or trigger hit on an unavailable catalog entry gives an install proposal;
- otherwise, when `settings.capability_build.allow_build` is on and the build-eligibility rules pass (§5.6), a build proposal;
- otherwise no proposal. The observation tells the model "Not something ANZU can add safely: <reason>", and the task gets one parent event with the same text, so the owner can see why.

The existing observation lines from `tooling.py:83-89` are kept unchanged. The proposal outcome is appended after them.

**Ask throttle (no ask spam):**
- At most one open ask per task.
- At most 3 asks per rolling hour across ANZU. An ask over the limit isn't raised; the task gets the visible event "I need <title> for this, but I've asked about new tools several times this hour; ask me to install it when you're ready."
- A capability the owner denied isn't asked about again implicitly (G1 or runtime) for 24 h. An explicit request (G2 or G3) always asks.

### 2. Lifecycle and storage (S3, S4)

**Tables** (`db/models.py`; created by `create_all`, no ALTER needed).

`capability_proposals`:
- `id`;
- `task_id` (the asking task);
- `kind` (`install` | `build`);
- `capability_id`, `title`, `version`, `source_json`, `permissions_json`;
- `deps_json` (runtime entries pulled in);
- `trigger` (`rider` | `runtime` | `explicit`), `spec_text` (build only, ≤ 4000 chars);
- `status`: proposed | asking | approved | denied | timed_out | building | awaiting_register | installed | failed | register_denied | register_timed_out | cancelled;
- `pending_approval_id`, `grant_id`, `register_pending_id`, `register_grant_id`;
- `child_task_id` (unique, nullable);
- `artifact_sha256`;
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

### 3. The owner approval gate (S3)

#### 3.1 What the owner sees and hears

The asking task goes to `status="waiting"` with `waiting_for_confirmation=True`, the same mechanism as the existing tool pause (`loop.py:3341-3367`). It gets:
- `confirmation_payload = {"kind": "capability_build", "gate": "install" | "build" | "register", "proposal_id", "pending_approval_id", "title", "version", "source": {"url", "host", "project", "sha256", "size_bytes", "license"}, "deps": [...], "permissions": {...}, "sandbox": "sealed", "expires_at", "code": {"sha256", "files", "lines", "tests_passed"} (register gate only)}`.
- **No `spoken_prompt` key.** `PermissionPrompt` would otherwise speak it (`PermissionPrompt.tsx:115-130`) and the line would be spoken twice. **No `pending_id` key**, so the RFC-0110 modal store is not involved (`OwnerChatTranscript.tsx:107-108`).
- A parked RFC-0031 request: `park_approval_request(action_id=action_id_for("capability_build", gate, f"{capability_id}@{version}#{sha256}", task_id=…), tool_name="capability_build", ttl_seconds=settings.capability_build.ask_ttl_s, …)` (`approval_grant.py:94-153`). The target string binds the grant to the exact artifact hash.

**Spoken and shown on the task stream.** The ask is delivered with `engine_coexistence.owner_line(text, level="info", task_id=<asking task>, title="New capability")`. Per RFC-0225 S3 that publishes one `engine_notice` on the owner channel plus, because `task_id` is set, an `engine_notice` and a `chat_tts` titled "New capability" on the task stream (`useTaskSpeech.ts` speaks it; the title is not "Speak reply", so it never joins the reply prefix). It is **never** sent through `publish_owner_text`, whose channel has no client (#663). The ask is published ≤ 150 ms after `evaluate_request_route` returns (same budget and test style as RFC-0231 S4).

**Owner texts** (en, module constants in `capability_build/texts.py`; spoken text has no URLs or hashes, per North Star §4; the card shows them):

| Case | Spoken and shown |
| --- | --- |
| Install ask | "To do this I need {title}: {summary_spoken}. I can install version {version} from {project}'s official release, checked against a pinned fingerprint. It would run sealed off: no internet, read-only access to the files you give it, and it can never change your case folders. Approve or deny it on screen." |
| Install ask with runtime dependency | the same text, with "It also needs ANZU's sealed Python runtime, {rt_version}, from python.org." before "Approve or deny" |
| Build ask | "There's no tool for this yet. I can write one: {spec_summary ≤ 90}. I'd build and test it sealed off, with no internet and no access to your files, and I'll show you the finished code's fingerprint before I add it. Approve or deny it on screen." |
| Register ask (build gate 2) | "The {title} tool is built and passed {n} tests. Approve on screen to add it, or deny to throw it away." |
| Denied | "Okay, I won't install {title}. I'll do what I can without it." (level info) |
| Timed out | "I didn't get an answer, so I haven't installed {title}. Ask me again any time." (level error) |
| Installed | "{title} is installed and checked. Continuing." |
| Failed | "Installing {title} failed: {reason ≤ 160}. Nothing was added, and anything partly installed was removed." (level error) |

**The card** (S6, §7) shows title, version, source URL, host, sha256, size, license, every runtime dependency with its own URL and hash, the permission list in plain words, the sandbox name, the expiry time in the owner's local time, and for the register gate the code hash, file count, line count and test count. It has exactly two buttons: **Approve** and **Deny**.

#### 3.2 Decision rules (normative)

- **Only a human button decides.** The decision arrives on the existing `POST /api/tasks/{id}/continue` (`api/tasks.py:305-321`), with `grant_mode` `"allow_once"` or `"deny"` and a new optional `origin_channel` field on `ContinueBody` (L46). The field takes `"ui"` (default) or `"mobile"`, and must be in `TRUSTED_CHANNELS`. `confirm_task` (`loop.py:590-730`) gets one branch, taken first when `payload.kind == "capability_build"`:
  - `grant_mode` in `{"always", "allow_session"}` → HTTP 400 "This can only be approved once." Nothing changes.
  - `"allow_once"` → `decide_approval_request(pending, decision="allow_once", origin_channel=…, actor="owner", session_id=task_id)`.
  - `"deny"` → the same call with `decision="deny"`.
  - The existing `expected_payload` binding (`loop.py:603-611`) is required on this branch, so a stale card can't approve a replacement.
- **No `always`, anywhere.** `approval_grant.py` gets `ONCE_ONLY_TOOLS = frozenset({"capability_build"})`. `decide_approval_request` raises `PermissionError` for `always` on those tools, so the RFC-0031 API path `POST /api/reversibility/pending/{id}/decide` (`api/reversibility.py:88-113`) can't create one either.
- **No voice approval in v1.** An STT mishear must never authorize running new code. The spoken line says "on screen", and the card has no microphone. Saying "yes" in chat is an ordinary follow-up message, and a test proves it does not approve.
- **No silent auto-approve path.**
  - There is no setting, autonomy level, Away Mode or grant that approves a capability.
  - RFC-0211's Away Mode standing authorization (#585 RFC text, "Decision") explicitly does **not** cover capability installs. Asks raised in Away Mode wait for the owner and time out like any other ask.
  - A static test asserts that `decide_approval_request` is called with `tool_name == "capability_build"` only from `confirm_task`'s capability branch.
- **Denial and timeout are final.**
  - The proposal becomes `denied` or `timed_out`, and the pending row is terminal (`approval_grant.py:251-254` already refuses a second decision).
  - The owner line from the table is published, and an audit row is written.
  - The asking task resumes without the capability (§5.5).
  - The same proposal can't be approved later. A new explicit request creates a new proposal.
- **Timeout timer.** `capability_build/proposals.py` schedules `asyncio` expiry at `expires_at`. Startup recovery (§5.7) expires any ask whose time passed while ANZU was down, using the same text. `approval_grant._expire_pending_unlocked` (L181-209) marks the pending row `timeout`, and the proposal follows it.

#### 3.3 Gates per kind

| Kind | Gate | Covers | Bound to |
| --- | --- | --- | --- |
| install | one ask | download from the pinned URL(s), hash check, unpack into the ANZU-owned dir, sealed self-test, registration of `cap_<id>` | `capability_id@version#sha256` (+ each dependency's hash) |
| build | ask 1 (`gate="build"`) | ANZU writing code into an ANZU-owned build dir; running that code's tests sealed; fetching any listed pinned wheels | the spec hash + each dependency's hash |
| build | ask 2 (`gate="register"`) | registering the built tool | the built tree's sha256 |

Nothing is downloaded, executed or registered before the matching grant exists. `proposals.require_grant(proposal, gate)` calls `validate_grant_for_action` (`approval_grant.py:342-383`) and `consume_grant` (L386-422) at the start of each step, and a test proves each step refuses without a grant.

#### 3.4 Approval window: ANZU can't approve itself

While any capability ask is open, `capability_build.window.approval_window_open()` is true, and the marker file `data/capabilities/approval_window.json` exists (so other processes, such as #585's `development_worker`, can honour it once it lands).

In the window, the tool loop **waits** before executing any tool in `WINDOW_HELD_TOOLS`:
- `terminal`, `python`, `open_interpreter`, `code_worker`;
- `browser`, `browser_use`, `web_fetch`;
- `desktop`, `cua`, `ufo`, `reflex_computer_use`, `apps`, `mobile_apps`, `hexstrike_operator`;
- `docker`, `mcp_call` and every `mcp_*`.

The wait is `await window.wait_closed()` in `_run`, right before the side-effect decision (`loop.py:3297`). The task gets one event, "Paused while you decide about a new capability", and `current_action` is set to the same text.

These are the only tools that could reach the loopback API or click the card, so ANZU can't approve its own ask. Filesystem reads and the other tools continue. The longest pause is the ask TTL (default 15 min). A test runs a second task that tries `web_fetch` against `/api/tasks/{id}/continue` during an open ask and proves the call only runs after the ask is decided by the test's simulated owner click.

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
- `data/` itself (`config.data_dir`, `config.py:19-22`), `settings.json`, `private_key.sec` (`auth.py:16-17`) and the owner's profile are never ACL'd, so the container can't read them.
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

#### 4.2 Inputs: read-only, files only

- A capability tool call takes `inputs: list[str]` (file paths) and `args: list[str]` (validated against the tool schema).
- Every input goes through `tools/safety.resolve_allowed_path` (L194-225), the same admission every file tool uses.
- Directories are refused ("give me the files"). This keeps hashing and handle passing exact.
- **Windows:** the broker (ANZU, outside the container) opens each input with `GENERIC_READ` and share mode `FILE_SHARE_READ` only, which denies concurrent writers and deletion for the run. The handles are passed through `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`. The child gets `ANZU_INPUT_HANDLES=<json list>` and no path. The container itself can't open the original path.
- **docker:** `:ro` bind mounts.
- At most 64 inputs per call.

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

- Only the broker downloads, never the sandboxed tool and never the model. It uses `network_http.gated_download_to(url, dest, tool="capability_build")` (L180), which re-checks every redirect hop.
- Every hop's host must be in `ALLOWED_SOURCE_HOSTS` and follow the redirect rule in §1.
- After download: the size must equal `size_bytes` and the sha256 must equal the pinned value, or the file is deleted and the proposal fails. There are no retries with a different URL.
- Archives are unpacked with a path-traversal guard: no absolute paths, no `..`, no symlinks or reparse points. Afterwards `entry_sha256` is verified.
- Wheel sets install with `pip install --no-deps --no-index --only-binary=:all: --require-hashes --target <install_dir> <verified wheels>`, run by the broker with the sandbox runtime's interpreter. Wheels don't execute code at install time, and `--no-index` means pip can't fetch anything.
- The Linux image is pulled only as `docker pull <repo>@sha256:<digest>`.
- **Forbidden by construction:** `curl | sh`, PowerShell `iex`, MSI or EXE installers, `pip install` from an index, `npm`, `git clone`, and MCP servers. None of them is a catalog `kind`. `catalog.py` validation rejects unknown kinds, non-https URLs, hosts outside the allowlist, missing hashes, and `latest`-style tags.

**Network egress summary:** at install time, only the broker talks to the network, only to the allowlisted host of a pinned URL, with every redirect hop re-checked. At run time and build time, sandboxed code has **no** network (kernel-enforced on Windows, `--network none` on Docker). The model's own network tools are unchanged by this RFC (outside the approval window).

#### 4.5 Secrets isolation

- **Environment:** the sandboxed process gets only `SystemRoot`, `TEMP`/`TMP` (pointing at its out dir), `PATH` (its install and runtime dirs only), `ANZU_INPUT_HANDLES` and `ANZU_OUT`. No `JARVIS_*`, no `*_KEY`, `*_TOKEN` or `*_SECRET`, no proxy variables, and no inherited environment. A test enumerates the child's environment.
- **Files:** the AppContainer can't read `data/`, so `settings.json` (`api_key` and others, `config.py:82, 121, 153`) and `private_key.sec` are out of reach. Docker mounts nothing but the dirs above.
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
- the title is "Installing {title}" or "Building {title}";
- the request id is stable, so a re-dispatch after a crash reuses the child (`loop.py:492-499`).

The kill switch check at `create_task` entry (`loop.py:485-489`) applies unchanged.

#### 5.2 Install child (no model)

`_run` sees `capability_build` on the task and runs `capability_build.installer.run(proposal, publish)` instead of the model loop, the same deterministic pre-model branch shape as RFC-0232 S3. The steps are seeded with `task_workflow.seed_workflow` (RFC-0231 S2) as `fetch`, `verify`, `unpack`, `self_test`, `register`, so the existing prompt-steps UI shows progress without new UI. Each step:
1. calls `require_grant`;
2. does its work;
3. writes an audit row;
4. publishes a task event in plain text ("Downloading FFmpeg 7.1 (84 MB)", "Fingerprint matches", "Self-test passed").

#### 5.3 Build child (model, sealed tests): S5

- The target model comes from RFC-0231's `large_prompt.resolve_target` and `preload`, including the rewarm hold and compare-and-restore. There is no second loader.
- The exposed tools are exactly `{"capability_workshop"}`, a new registry tool that only:
  - writes files inside `data/capabilities/build/<proposal>/` (relative paths only, ≤ 40 files, ≤ 2000 lines total);
  - runs the build's own tests through `run_sealed` with build-dir inputs.
- The seeded workflow steps are `design`, `implement`, `test`, `verify`, with at most 3 implement/test rounds. After the third failed round the proposal fails with the "Failed" line.
- **Tool contract:** a Python 3.12 package with `tool.py::run(request: dict, inputs: list[BinaryIO], out_dir: Path) -> dict`, executed by a fixed ANZU-owned launcher `capability_build/launcher_template.py` that opens the inherited handles. Imports are limited to the stdlib minus `BUILD_FORBIDDEN_MODULES` (`socket`, `ssl`, `http`, `urllib`, `ftplib`, `smtplib`, `subprocess`, `multiprocessing`, `ctypes`, `winreg`, `_winapi`, `asyncio.subprocess`), plus catalog wheels named in the proposal.
- `build_policy.scan(tree)` (AST) rejects forbidden imports, `__import__` or `importlib` with non-literal names, `eval`/`exec`/`compile`, and `open()` outside `out_dir`. It also runs the secret scan (§4.5). The sandbox enforces all of this anyway; the scan gives a clear failure before the register gate.
- When the tests pass, the child computes `tree_sha256` and goes `waiting` with the **register** gate (§3.1, ask 2).
  - Approve → register (§5.4).
  - Deny or timeout → the build dir is deleted, the proposal becomes `register_denied` or `register_timed_out`, and an audit row is written.

#### 5.4 Registration

- `ToolRegistry` gains `register_capability(tool: SandboxedCapabilityTool)` and `unregister_capability(name)` (`tools/registry.py`, add-only methods). `_init_tools` (L59-101) is unchanged, and startup loads active `capability_installs` rows after it.
- `SandboxedCapabilityTool` (`tools/sandboxed_capability.py`, new):
  - `risk=RiskLevel.MEDIUM`, `effect_class="internal"`, `reversibility="REVERSIBLE"`, because it only writes its own out dir;
  - `execute` → `run_sealed`, with the output capped at 8000 chars plus a list of out files;
  - writes a `run` audit row.
- Before every run it re-hashes the entrypoint (`entry_sha256`). At startup it re-hashes the whole tree. A mismatch unregisters the tool and publishes an error owner line.
- `tools/exposure.py` accepts names that start with `cap_` **and** are currently registered capability tools, in `grant` (L150) and `ensure_named_tool` (L172). `NATIVE_TOOLS` is unchanged. `tool_names_for(task_class)` adds the registered `cap_` tools whose `task_classes` match, so ANZU just uses an installed capability without asking again.

#### 5.5 Resume the asking task

`capability_build.queue.on_child_terminal(child_id, status)` is called from `_update`'s terminal block, next to `advance_intake_chain` (`loop.py:~799`) and RFC-0231's `on_child_terminal`.
- **Decide-time ask** (the asking task never ran its model): `_start_runner(_run(task, continue_existing=False))`, with `cap_<id>` added to `exposed_tools` when installed.
- **Runtime ask** (paused inside `request_capability`): `_run(task, continue_existing=True, pending_tool=payload)`, where `payload` carries a synthetic observation for the paused call (the `loop.py:2871-2880` path):
  - "cap_<id> is now available. Use it."
  - or "The owner did not approve <title>; continue without it and say what you could not do."
  - or "Installing <title> failed: <reason>."
- **Denied or timed-out asks** resume the same way, with the "without it" observation. The final result therefore states what couldn't be done (North Star §8).
- **Cancel:** `AGENT.cancel(asking)` (`loop.py:732-737`) also cancels an open ask (status `cancelled`, pending row denied with actor `owner-cancel`) and the build child. `on_parent_cancel` is called from `cancel`, next to RFC-0231's hook.

#### 5.6 Build eligibility (rules, deterministic)

A build proposal is offered only when the spec (G3 prompt or runtime `missing`):
- names a local-file transformation or analysis (parse, convert, extract, decode, count, compare, summarise, or the nl equivalents);
- does **not** mention network, internet, download, upload, API, account, login, email, send, post, camera, microphone, screen, keyboard, registry, service, driver, or admin (en and nl lists in `capability_build/eligibility.py`);
- and fits the sealed profile.

Anything else gets the visible "not something ANZU can add safely" event with the matched word. A gap that needs a change to ANZU's own source is **not** a capability build. That is RFC-0211's self-development flow, and this RFC never edits the repository, creates branches or merges.

#### 5.7 Startup recovery

In `main.py`, after RFC-0231's `recover_on_startup` call:
1. `audit.verify_chain()`.
2. Rebuild `CAPABILITY_INDEX`, and re-register active installs after a tree re-hash.
3. Expire overdue asks (§3.2).
4. For proposals in `building`: if the child is terminal, run `on_child_terminal`; otherwise `continue_task(child)` (RFC-0029 durable resume). Partial download or unpack dirs are deleted and the step restarts from `fetch`. The grant check accepts the same `allow_once` grant, recorded as `resumed` in the audit log; it is never consumed twice and never re-minted.
5. Re-create the approval-window marker if an ask is still open, or remove a stale one.

#### 5.8 Interplay with the large-prompt pipeline (RFC-0231) and RFC-0232

- When one turn has both `large_prompt == "large"` and a gap: the large ack goes first (RFC-0231 §2), then the gap ask on the **parent**. `large_prompt_queue.dispatch_next` (0231-S5) does not dispatch part 1 while `capability_build.queue.blocking(parent)` is true. It shows the parent event "Waiting for your decision on {title}". When the ask resolves, dispatch continues, and each child's exposed tools include `cap_<id>` if it was installed.
- Part children never run the gap rider (they have no decide). A runtime gap inside a part asks on that part's own task stream, and the parent shows "Part n is waiting for your decision on {title}".
- RFC-0232's path + question router has precedence: the precheck skips the rider when it matches (§1).

### 6. Settings (S1 adds the block; owned in `config.py`)

```python
class CapabilityBuildSettings(BaseModel):
    enabled: bool = True
    allow_build: bool = True
    ask_ttl_s: int = Field(default=900, ge=120, le=3600)
    evidence_roots: list[str] = Field(default_factory=list)
```

- `AppSettings.capability_build` is added next to `decision` (`config.py:450-512`) and RFC-0231's `large_prompts`, and exposed on the existing settings GET and PUT.
- There is deliberately **no** auto-approve, allow-always or trusted-source setting.
- `enabled=false` restores today's behaviour exactly: no rider, the same `request_capability` observation, no new events. A test proves the decision and `create_task` are byte-identical in that case.

### 7. Owner UI (S6), add-alongside only

- **`frontend/src/chat/CapabilityPrompt.tsx` (new):** the card from §3.1, with Approve and Deny only. It posts `/api/tasks/{id}/continue` with `{grant_mode, origin_channel, expected_payload}`. On error it shows the server text. It has no microphone and no speech: the ask is spoken once, by `useTaskSpeech`, from the `chat_tts` event. Times are shown in the browser's local time.
- **Render sites:** one added conditional at each existing site, chosen before `PermissionPrompt` only when `parsed.kind === "capability_build"`:
  - `OwnerChatTranscript.tsx:198-200` (HUD and classic);
  - `pages/Phone.tsx:256` (phone; sends `origin_channel: "mobile"`).
- **`frontend/src/pages/CapabilitiesPanel.tsx` (new)**, mounted with one line in `pages/Tools.tsx` (`ToolsPage`, L31) under the existing tools list. It shows:
  - installed capabilities with version, source, tree hash, installed time and last run;
  - **Roll back** (shown when a previous version exists) and **Uninstall** buttons;
  - the audit-chain status ("Audit log verified, 214 entries" or the error);
  - an **Export audit log** link (`/api/capabilities/audit?format=jsonl`);
  - recent asks with their outcome.
- **`frontend/src/api.ts`:** add-only types `CapabilityPromptPayload`, `CapabilitySummary`, `CapabilityAuditStatus`.
- **API (S4):** `GET /api/capabilities`, `GET /api/capabilities/audit` (JSON status, or `?format=jsonl` for the raw file), `POST /api/capabilities/{id}/rollback`, `POST /api/capabilities/{id}/uninstall`, in `backend/app/api/capabilities.py` (new), registered in `main.py`.

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

Touched live UI: the task transcript (HUD and classic), Phone, the Tools page, task speech.

| Surface | Existing behaviour kept? | Addition |
| --- | --- | --- |
| `OwnerChatTranscript` confirm area (`:198-200`) | **Yes.** Every existing payload kind still renders `PermissionPrompt` with the same props. The new branch is taken only for `kind === "capability_build"`, a kind no backend emits today. | `<CapabilityPrompt …/>` for that kind |
| `PermissionPrompt.tsx` | **Yes, file not edited** | — |
| RFC-0110 modal (`PendingApprovalHost`, `App.tsx:145-148`) | **Yes, not edited.** Capability payloads carry no `pending_id`, so the modal never sees them. | — |
| Phone confirm (`Phone.tsx:256`) | **Yes.** Same rule as the transcript. | the same conditional |
| `useTaskSpeech` / `chat_tts` | **Yes, unchanged** | The ask is an ordinary `chat_tts` with title "New capability" (≠ "Speak reply") |
| RFC-0225 `EngineNotices` chip | **Yes, unchanged** | The ask appears as an `engine_notice` titled "New capability"; RFC-0225's controller renders any title |
| `ToolsPage` (L31) | **Yes.** The list, toggles and every row are untouched. | One mount line for `<CapabilitiesPanel />` below the list |
| Task activity / prompt steps (RFC-0231 S2/S6) | **Yes** | Install and build children appear as ordinary tasks with seeded steps |
| Persona, presence, WebGL | **Not touched** (Astra) | — |

Nothing existing is removed, renamed or re-styled. The only behaviour change for existing flows is the approval-window pause (§3.4), which runs only while a capability ask is open, and no capability ask exists today.

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
| **RFC-0211 / #585** (scheduler, `resource_hold`, Away Mode) | Build children are persisted `Task` rows before dispatch, so #585's upcoming-task list shows them when it lands, with no second queue. Build-kind children use the coder model, so while #585's `DevelopmentConfig.resource_hold` (`development_scheduler.py:28`, checked at L279-280 and L405) names Ollama, `start_build` defers with the event "Waiting for the scheduler's model hold" (the same rule as RFC-0231 §Reconciliation). Install children use no model and are not held. Away Mode's standing authorization never approves a capability (§3.2). #585's `development_worker` process must honour the approval-window marker file (§3.4): a one-line check before its own tool calls, made by whichever of 0233-S3 and #585 lands second. #585 also edits `tools/registry.py` (+2) and `tools/exposure.py` (+1), which is ordered in the chain below. |
| **RFC-0231 / #665** | Self-build children are ordinary `AgentRuntime.create_task` tasks with a keyword-only marker, exactly like `pipeline_section`. They reuse `seed_workflow` (0231-S2), the terminal-hook placement, `resolve_target`/`preload`/rewarm hold (0231-S4) for build kind, and the startup-recovery pattern (0231-S5). One hook goes into `large_prompt_queue.dispatch_next` (§5.8). There is no second pipeline. |
| **Decision lane** (`decision/*`) | One decide per owner turn, with one extra rider on `tool_selection`. The 50 ms deadline is unchanged, rules are the fallback, and the provider can't lower an explicit request. `decision/types.py`, `reflex.py` and `surfaces.py` are not edited. |
| **Tool registry** (`tools/registry.py`, `tools/exposure.py`, `tools/capability.py`, `agent/tooling.py`) | Existing tools, `NATIVE_TOOLS` and `_init_tools` are unchanged. Capabilities are added through two add-only registry methods and a `cap_` exposure rule. `request_capability` keeps its contract and gains the optional `missing` field. |
| **RFC-0031** (`policy/approval_grant.py`) | The only grant store. Additions: `ONCE_ONLY_TOOLS`, and the requirement that the capability branch passes `expected_payload`. The evidence-grade audit is a separate append-only file (§4.6). |
| **RFC-0007 packs** | Each capability is a pack with one `tool` resource. Install, upgrade, rollback and uninstall go through `packs/manager.py` and its recovery journal. |
| **RFC-0173 Skill Forge** / RFC-0105 skill packs (`agent/skill_packs.py`) | Different layer: skills compose registered tools, and SKILL.md packs register module connector skills (`skill_packs.register_module_pack`, L36). Once `cap_<id>` is registered, Skill Forge can extract skills that use it under its own approval (`skills/approval.py`). Skill Forge never installs a capability, and this RFC never publishes a skill. |
| **MCP** (`tools/mcp_runtime.py`) | Not a capability kind: MCP servers run unsandboxed with network. Owner-configured MCP stays exactly as it is. |
| **RFC-0225 S3** | The ask, outcome and failure lines go through `owner_line(..., title="New capability")`. RFC-0225's static title test (`test_rfc0225_and_rfc0228_lines_use_default_title`) scans only RFC-0225/0228 modules, so this caller doesn't collide with it. |
| **RFC-0232 / #664** | Its path + question router takes precedence: no gap rider on those turns. The RE tool and REA are capabilities that already exist and are never proposed. Built tools admit inputs through the same `resolve_allowed_path`. #661's allow-list-first gate in RE prepare is untouched. |
| **RFC-0230** (in flight) | Content unknown at time of writing. Its slices go **first** on every shared file below, and 0233 tickets rebase onto them. |
| **Drafts #648 / #649** | No overlapping hunks (see header). Nothing is ported, and nothing waits on them. |

---

## Slices (one ticket each, one developer each, fast off)

### S1: Catalog, capability index, gap rider

**Model:** Grok 4.5 · **Depends:** RFC-0231 S1 (merge order on `owner_turn.py` / `rules.py`), RFC-0232 S2 (provides `planning.ffs_or_apk_investigation`, which the precheck calls)

| File | Change |
| --- | --- |
| `backend/app/capability_build/__init__.py` (new) | package |
| `backend/app/capability_build/catalog.json` (new) | v1 entries (§1), real pins |
| `backend/app/capability_build/catalog.py` (new) | load and validate (kinds, https, host allowlist, 64-hex hashes, no `latest`), `ALLOWED_SOURCE_HOSTS`, alias and trigger lookup |
| `backend/app/capability_build/index.py` (new) | `CAPABILITY_INDEX`, `rebuild()` |
| `backend/app/decision/capability_gap.py` (new) | G1-G3, `CapabilityGapIntent`, precheck, `intent_from_result` |
| `backend/app/decision/owner_turn.py` | precheck and rider in `_decide_sync`, floor, `capability_gap` field |
| `backend/app/decision/adapters/rules.py` | `capability_gap` rider branch |
| `backend/app/agent/request_routing.py` | pass-through |
| `backend/app/config.py` | `CapabilityBuildSettings` |
| `backend/app/api/settings.py` | expose the block |
| `scripts/verify_capability_catalog.py` (new) | downloads every catalog source through `gated_download_to` and checks size and sha256 (and `docker manifest inspect` for the image digest); exits non-zero on any mismatch |
| `tests/test_rfc0233_gap_decision.py` (new) | below |
| `tests/test_rfc0233_catalog.py` (new) | below |
| `.github/workflows/pr-tests.yml` | append the step `Capability catalog pins (RFC-0233 S1)` to the `pytest` job after "Run full backend suite". It runs `python scripts/verify_capability_catalog.py` when `git diff --name-only origin/${{ github.base_ref }}...HEAD` lists `backend/app/capability_build/catalog.json`, and prints "catalog unchanged" otherwise. |

Tests (CI: `pytest` job, step "Run full backend suite", plus the new step):
- `test_g1_implicit_gap_fires_for_unavailable_entry`;
- `test_g1_silent_when_available`;
- `test_g2_explicit_install_any_route`;
- `test_g3_explicit_build_en_nl`;
- `test_provider_cannot_invent_id_or_lower_explicit`;
- `test_provider_switches_only_at_075`;
- `test_deadline_fallback_is_rules`;
- `test_one_decide_per_turn`;
- `test_ffs_path_question_never_gets_rider` (uses RFC-0232's fixture prompts);
- `test_security_role_excluded`;
- `test_disabled_is_byte_identical`;
- `test_precheck_reads_no_disk` (patches `open` / `Path.read_text` to raise during `_decide_sync`);
- `test_catalog_rejects_http_latest_unknown_host_missing_hash`;
- `test_every_entry_has_sealed_permissions_and_64hex`;
- `test_redirect_hosts_only_as_hops`.

### S2: Sealed sandbox, evidence guard, broker fetch, audit chain

**Model:** Grok 4.6 · **Depends:** S1

| File | Change |
| --- | --- |
| `backend/app/capability_build/sandbox.py` (new) | `run_sealed`, backend probe, `win_appcontainer` (ctypes: AppContainer profile, ACL grant, handle list, Job Object) and `docker` |
| `backend/app/capability_build/evidence.py` (new) | `evidence_roots`, `assert_not_evidence`, before/after hashing |
| `backend/app/capability_build/fetch.py` (new) | broker download, hop checks, size and sha256, safe unpack, wheel install with `--require-hashes --no-index`, digest-pinned image pull |
| `backend/app/capability_build/audit.py` (new) | append-only hash chain, `verify_chain`, export |
| `backend/app/capability_build/launcher_template.py` (new) | the fixed launcher that opens inherited handles and calls `run` |
| `tests/test_rfc0233_sandbox_docker.py` (new) | below (real Docker) |
| `tests/test_rfc0233_sandbox_windows.py` (new) | below (real AppContainer) |
| `tests/test_rfc0233_evidence_fetch_audit.py` (new) | below |
| `.github/workflows/pr-tests.yml` | append the step `RFC-0233 sealed sandbox (Docker, no skips)` to `pytest` (runs the Docker file with `-rs`, fails on `SKIPPED`, the same guard as the RFC-0198 LTA step); append a new job `capability-sandbox-windows` (`windows-latest`, Python 3.12, installs backend requirements and pytest, runs the Windows file with the same no-skip guard) |

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
- Windows file only: `test_clipboard_blocked`.
- `test_rfc0233_evidence_fetch_audit.py`:
  - `test_no_backend_refuses_never_runs_unsealed`;
  - `test_evidence_hash_before_after_and_violation_disables`;
  - `test_assert_not_evidence_refuses_data_dir_under_root`;
  - `test_fetch_rejects_wrong_hash_size_host_and_bad_hop`;
  - `test_unpack_rejects_traversal_and_links`;
  - `test_wheels_require_hashes_no_index`;
  - `test_audit_chain_append_verify_and_tamper_detect`;
  - `test_audit_never_truncated` (10 000 rows).

### S3: Proposals, the owner approval gate, approval window, runtime trigger

**Model:** Grok 4.6 · **Depends:** S1, S2, RFC-0225 S3 (`owner_line`), RFC-0231 S5 (`loop.py` order), RFC-0232 S4 (`loop.py` order)

| File | Change |
| --- | --- |
| `backend/app/db/models.py` | `CapabilityProposal`, `CapabilityInstall` |
| `backend/app/capability_build/proposals.py` (new) | `propose`, `runtime_gap`, throttle and 24 h dedupe, `open_ask`, `require_grant`, expiry timer |
| `backend/app/capability_build/texts.py` (new) | owner texts (§3.1) |
| `backend/app/capability_build/window.py` (new) | `approval_window_open`, `wait_closed`, marker file |
| `backend/app/capability_build/eligibility.py` (new) | build eligibility (§5.6) |
| `backend/app/policy/approval_grant.py` | `ONCE_ONLY_TOOLS`; refuse `always` for them |
| `backend/app/agent/loop.py` | the decide-time ask in `create_task` (after RFC-0231's large branch); the `confirm_task` capability branch; the window wait before `_side_effect_decision` (L3297); the runtime trigger in the `request_capability` branch (L3377) |
| `backend/app/api/tasks.py` | `ContinueBody.origin_channel` (validated against `TRUSTED_CHANNELS`) |
| `backend/app/tools/capability.py` | optional `missing` field and its description |
| `backend/app/agent/tooling.py` | return the unknown names in structured form for the loop (observation text unchanged) |
| `tests/test_rfc0233_approval_gate.py` (new) | below |

Tests:
- `test_ask_published_via_owner_line_chat_tts_within_150ms`;
- `test_ask_never_uses_publish_owner_text`;
- `test_ask_title_new_capability_not_speak_reply`;
- `test_payload_has_no_spoken_prompt_or_pending_id`;
- `test_ask_states_what_where_permissions` (the payload and spoken text contain title, version, project, and the no-internet / read-only / case-folder words; the payload holds url, sha256, size, license and deps);
- `test_approve_allow_once_creates_grant_ui_and_mobile`;
- `test_always_and_allow_session_refused_400`;
- `test_reversibility_api_cannot_mint_always`;
- `test_untrusted_channel_refused`;
- `test_chat_yes_does_not_approve`;
- `test_expected_payload_binding_required`;
- `test_deny_final_visible_audited_task_resumes_without`;
- `test_timeout_final_visible_audited` (fake clock);
- `test_timeout_survives_restart`;
- `test_no_step_runs_without_grant`;
- `test_no_auto_approve_path_static` (AST scan of `backend/app` for `decide_approval_request` calls with `capability_build`);
- `test_away_mode_does_not_approve`;
- `test_window_holds_listed_tools_and_releases` (a second task's `web_fetch` to `/continue` runs only after the simulated owner click);
- `test_window_marker_file_lifecycle`;
- `test_runtime_unknown_capability_creates_install_proposal`;
- `test_runtime_unbuildable_gives_visible_reason`;
- `test_throttle_and_24h_dedupe_explicit_bypasses`;
- `test_disabled_runtime_observation_unchanged`.

### S4: Install child, registration, rollback/uninstall, resume, recovery, API

**Model:** Grok 4.6 · **Depends:** S3, RFC-0231 S2 (`seed_workflow`) and S5 (`large_prompt_queue`)

| File | Change |
| --- | --- |
| `backend/app/capability_build/installer.py` (new) | the install child steps (§5.2) |
| `backend/app/capability_build/queue.py` (new) | `start_build`, `on_child_terminal`, `on_parent_cancel`, `blocking`, `resume_parent`, `recover_on_startup`, the #585 hold deferral |
| `backend/app/capability_build/packs.py` (new) | pack manifest for `capability.<id>`; install, upgrade, rollback and uninstall via `packs/manager.py` |
| `backend/app/tools/sandboxed_capability.py` (new) | `SandboxedCapabilityTool` |
| `backend/app/tools/registry.py` | `register_capability`, `unregister_capability` (add-only) |
| `backend/app/tools/exposure.py` | `cap_` acceptance in `grant` and `ensure_named_tool`; `tool_names_for` adds matching capability tools |
| `backend/app/agent/loop.py` | `capability_build` keyword in `create_task`; the deterministic child branch in `_run`; terminal and cancel hooks |
| `backend/app/agent/large_prompt_queue.py` | `dispatch_next` waits on `capability_build.queue.blocking(parent)` (§5.8) |
| `backend/app/api/capabilities.py` (new) | the endpoints in §7 |
| `backend/app/api/tasks.py` | `capability` object in `get_task` (L256): open proposal summary |
| `backend/app/main.py` | router registration; startup `recover_on_startup` after RFC-0231's |
| `tests/fixtures/rfc0233/` (new) | a fixture catalog: a 2 KB zip holding a `selftest` script, its real sha256 and size, and a local HTTP server fixture that serves it |
| `tests/test_rfc0233_install_lifecycle.py` (new) | below |

Tests:
- `test_install_end_to_end_fixture` (approve → fetch → verify → unpack → self-test → pack → registered → the asking task resumes with `cap_x` and calls it);
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
- `test_cancel_asking_cancels_ask_and_child`;
- `test_recovery_expire_resume_reregister`;
- `test_resource_hold_defers_build_kind_only`;
- `test_capability_payload_in_get_task`;
- `test_api_rollback_uninstall_audit_export`.

### S5: Build kind: workshop tool, build policy, register gate

**Model:** Grok 4.6 · **Depends:** S4, RFC-0231 S4 (`resolve_target` / `preload`)

| File | Change |
| --- | --- |
| `backend/app/capability_build/workshop.py` (new) | `CapabilityWorkshopTool` (write within the build dir; run tests sealed); exposed only to build children |
| `backend/app/capability_build/build_policy.py` (new) | AST scan, `BUILD_FORBIDDEN_MODULES`, secret scan, size caps |
| `backend/app/capability_build/builder.py` (new) | build-child workflow seeding (`design` / `implement` / `test` / `verify`), round cap, register gate, `tree_sha256` |
| `backend/app/tools/registry.py` | register the workshop tool (not in `NATIVE_TOOLS`, not in any task class) |
| `tests/test_rfc0233_build_kind.py` (new) | below |

Tests:
- `test_build_ask_then_register_ask_two_grants`;
- `test_workshop_cannot_write_outside_build_dir`;
- `test_build_child_tools_are_workshop_only`;
- `test_policy_rejects_socket_subprocess_ctypes_eval_dynamic_import`;
- `test_secret_in_code_fails_build`;
- `test_three_rounds_then_visible_failure`;
- `test_register_denied_deletes_build_dir`;
- `test_registered_built_tool_runs_sealed_with_handles`;
- `test_build_never_receives_evidence_paths`;
- `test_not_buildable_spec_refused_with_word`;
- `test_build_uses_0231_preload_and_restore`.

### S6: Capability prompt and Capabilities panel

**Model:** Composer 2.5 · **Depends:** S4 (API), S5 (register payload), RFC-0231 S6 (`api.ts` order)

| File | Change |
| --- | --- |
| `frontend/src/chat/CapabilityPrompt.tsx` (new) | the card (§3.1, §7) |
| `frontend/src/chat/capabilityPrompt.ts` (new) | plain-TS controller (payload parse, decide request, local-time formatting), imported by the node tests |
| `frontend/src/chat/OwnerChatTranscript.tsx` | one conditional at `:198-200` |
| `frontend/src/pages/Phone.tsx` | one conditional at `:256` |
| `frontend/src/pages/CapabilitiesPanel.tsx` (new) | the panel (§7) |
| `frontend/src/pages/Tools.tsx` | one mount line |
| `frontend/src/api.ts` | add-only types |
| `frontend/capability-prompt.test.mjs` (new) | below |
| `frontend/capabilities-panel.test.mjs` (new) | below |
| `frontend/package.json` | append `test:capabilities` (runs both files with `node --test`) |
| `.github/workflows/pr-tests.yml` | append the step `Capability prompt and panel tests (RFC-0233 S6)` → `npm run test:capabilities` in `frontend-build`, after RFC-0231 S6's step |

Tests (`frontend/capability-prompt.test.mjs`):
- `capability payload renders card not PermissionPrompt`;
- `other payloads still render PermissionPrompt` (static, on both render sites);
- `only approve and deny exist, no always, no microphone`;
- `approve posts allow_once with expected_payload and origin ui`;
- `phone posts origin mobile`;
- `card shows url sha256 size license deps permissions expiry in local time`;
- `register gate shows code hash files lines tests`;
- `server error text is shown`;
- `card does not speak` (no `speakChatReply` / `queueChatSpeech` import).

Tests (`frontend/capabilities-panel.test.mjs`):
- `lists installs with hash and version`;
- `rollback only when previous exists`;
- `uninstall posts endpoint`;
- `audit status ok and broken`;
- `export link points at jsonl`;
- `Tools page still renders its existing list` (static).

**Live audit** (on Taco's PC; numbers and screenshots recorded in the PR): ask "what's in this SQLite database: <case path>\msgstore.db" with `sqlite_cli` absent. Verify:
- the ask is heard, and the card shows source, hash and permissions;
- deny → the line is heard and the task finishes saying what it couldn't do;
- repeat and approve → installed, and the query answers;
- the audit log verifies, and the run row shows identical before/after hashes of `msgstore.db`;
- uninstall from the panel works.

## Ownership chains (handoff order on shared files)

Every listed RFC-0230 slice goes **first** on any file it claims, then RFC-0231, then RFC-0232, then 0233.

| File | Order |
| --- | --- |
| `backend/app/agent/loop.py` | 0218-S3b → (0230) → 0231-S2 → 0231-S4 → 0231-S5 → 0232-S3 → 0232-S4 → 0233-S3 → 0233-S4 |
| `backend/app/decision/owner_turn.py` | (0230) → 0231-S1 → 0232-S2 → 0233-S1 |
| `backend/app/decision/adapters/rules.py`, `backend/app/agent/request_routing.py` | (0230) → 0231-S1 → 0233-S1 |
| `backend/app/config.py` | 0228-S1 → 0228-S2 → (0230) → 0231-S2 → 0233-S1 |
| `backend/app/api/settings.py` | 0231-S2 → 0233-S1 |
| `backend/app/db/models.py` | (0230) → 0231-S2 → 0233-S3 |
| `backend/app/api/tasks.py` | (0230) → 0231-S2 → 0231-S5 → 0233-S3 → 0233-S4 |
| `backend/app/main.py` | 0225-S1 → S2 → S3 → 0231-S5 → 0233-S4 |
| `backend/app/agent/large_prompt_queue.py` | 0231-S5 (creates it) → 0233-S4 |
| `backend/app/tools/registry.py` | (#585 if it lands first) → 0233-S4 → 0233-S5 |
| `backend/app/tools/exposure.py` | (#585 if it lands first) → 0233-S4 |
| `backend/app/policy/approval_grant.py`, `backend/app/tools/capability.py`, `backend/app/agent/tooling.py` | 0233-S3 only |
| `frontend/src/api.ts` | 0218-S3 → 0231-S6 → 0233-S6 |
| `frontend/src/chat/OwnerChatTranscript.tsx`, `frontend/src/pages/Phone.tsx`, `frontend/src/pages/Tools.tsx` | 0233-S6 only (RFC-0231 does not edit them) |
| `frontend/package.json`, `.github/workflows/pr-tests.yml` | append-only, any order, rebase on conflict |

## Ticket cards

| ID | Title | Model | Depends |
| --- | --- | --- | --- |
| 0233-S1 | Catalog, capability index, gap rider | Grok 4.5 | 0231-S1, 0232-S2 |
| 0233-S2 | Sealed sandbox, evidence guard, broker fetch, audit chain | Grok 4.6 | S1 |
| 0233-S3 | Proposals, owner approval gate, approval window, runtime trigger | Grok 4.6 | S1, S2, 0225-S3, 0231-S5, 0232-S4 |
| 0233-S4 | Install child, registration, rollback/uninstall, resume, recovery, API | Grok 4.6 | S3, 0231-S2, 0231-S5 |
| 0233-S5 | Build kind: workshop, build policy, register gate | Grok 4.6 | S4, 0231-S4 |
| 0233-S6 | Capability prompt and Capabilities panel | Composer 2.5 | S4, S5, 0231-S6 |

All six run with fast mode off.

## Overall acceptance

- [ ] A request that needs a missing catalog capability produces one spoken and shown ask on the task stream (`chat_tts` via `owner_line`) within 150 ms of the decision. The ask names what, from where (URL and hash on the card) and with which permissions.
- [ ] Nothing is downloaded, executed or registered without an `allow_once` grant from a UI or phone button. `always` is impossible, voice and chat can't approve, and ANZU's own tools can't act while an ask is open.
- [ ] Denial and timeout are final, spoken, audited, and the task finishes saying what it couldn't do.
- [ ] Installed and built tools run sealed: no network, files-only read-only inputs, no secrets, never a write to an evidence root, and before/after input hashes in the audit log.
- [ ] The audit log is append-only, hash-chained, verifiable and exportable. Rollback and uninstall work from the panel.
- [ ] With `capability_build.enabled=false`, behaviour is identical to today.

## Out of scope

- Persona, presence, WebGL, morph and voice choice (Astra).
- Network-using capabilities, MCP servers, installers (MSI/EXE), and packages from an index.
- Directory inputs for capability tools.
- Voice approval.
- Changes to ANZU's own source (RFC-0211).
- A catalog editor UI.

## Risks

- **AppContainer quirks with native binaries** (for example a DLL outside the granted dirs). Mitigation: the self-test runs sealed before registration, so a capability that can't run sealed is never registered, and the failure line names it. The catalog is curated with that in mind.
- **The approval window pauses other tasks' tools for up to 15 minutes.** Mitigation: asks are rare and throttled (3 per hour), the pause is visible on each held task, and it ends the moment the owner decides.
- **Hashing very large case files is slow.** Mitigation: the > 4 GiB partial-hash rule, marked as partial in the audit row. Kernel read-only plus the share mode are the primary guarantee.
- **Catalog pins go stale.** Mitigation: updating a pin is a reviewed PR, and the S1 CI step verifies it. An installed older version keeps working.
- **Rollback and uninstall endpoints are reachable from loopback** like every other ANZU API. They only remove ANZU-owned files, are audited, and never install or run anything, so they don't weaken the approval gate.
- **Collisions in `loop.py`.** Mitigation: the strict ownership chain above.
