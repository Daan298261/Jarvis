# RFC-0232: FFS / APK path + question routes to the RE tool (no context overflow)

**Status:** accepted  
**Priority:** P0 (Taco bug, 2026-10-20 14:55 — "ANZU didn't call the reverse-engineering tool")  
**Author:** Jarvis Architect  
**Date:** 2026-10-20  
**Root-cause credit:** D1 (initial trace) + D2 (peer corrections). Every citation below was re-verified against `development` @ `11b264a7`.  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §6 (deterministic rule → reflex → tools → model), §8 (verify from evidence), §19 ("Do use fast deterministic mechanisms where they are superior to AI reasoning."), §20 Q1 / Q6 / Q7.  
**Extends (do not rewrite):** [RFC-0208 FFS dump self-ingest](0208-ffs-dump-self-ingest.md) (`store.prepare_ffs`, `ffs_ingest`, `ffs_query`, `POST /api/investigations/ffs`), [RFC-0207 APK reverse sidecar](0207-apk-reverse-sidecar.md) (`apk_sidecar.prepare_apk`), [RFC-0200 REA MCP](0200-rea-mcp-local-investigation.md), [RFC-0201 Reverse Engineer Anything](0201-reverse-engineer-anything.md), [RFC-0206 every-turn Jev/Laya](0206-jev-laya-every-turn-arbitration.md), [RFC-0122 ingress size-gate](0122-ingress-size-gate-spill-and-trajectory-cap.md), [RFC-0182 segmented input](0182-context-and-segmented-agentic-tasks.md).  
**Reconciles with (in progress):** [RFC-0218 S3b](0218-persona-surfaces-and-intent-switch.md) (#658, tasks-path persona switch — this RFC does not touch persona surfaces), RFC-0231 large-prompt pipeline (in flight; **path + question takes precedence** over prompt-splitting), RFC-0230 PC first-response latency (routing is pre-model / reflex, so it cuts the 9B turn rather than adding to it), [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) (#652 @ `916cf256`, specs only) for the no-task owner-line channel. RE prepare allow-list chain: **#660** (`24169e85`, `prepare_ffs`) and **#661** (`4b81ac11`, `store.prepare` / `prepare_apk`), both open onto `development`.  
**Reserved numbers:** 0230 and 0231 are parallel; **0233 is reserved** for another RFC. Touch only this RFC's README row (see S1 for how the row coexists with #652's next-free rewrite).  
**Taco 2026-10-09 ruling (binding):** RE extends and complements REA. No removal. Native `reverse_engineer` (ingest / prepare / ffs_query / apk) stays; `rea_investigate` stays available when REA roots are configured.

This PR is **specs + S1 xfail repro**. Application code lands in the implement slices below.

---

## Problem (what Taco saw)

Taco gave ANZU an Android FFS root path (Windows form such as `D:\cases\x\ffs`), a full FFS extraction, and a question. ANZU never called the reverse-engineering / FFS ingest tool. It tried to put the dump into context and overflowed.

Reproduced on the box against `development` @ `11b264a7` with a mocked 9B (`tests/test_rfc0232_ffs_path_routing.py`, run with `--runxfail`):

| Prompt shape | `route_request` today | Tools offered to the 9B | Outcome |
| --- | --- | --- | --- |
| `D:\cases\x\ffs what apps are installed…` | `managed_task` / **`shell`** | `filesystem`, `terminal`, `python`, `apps` — **no** `reverse_engineer` | Falls into list/search; never ingest |
| `Here is the Android FFS root D:\…` (path + question, no RE verb) | **`direct_reply` / `conversation`** | **none** (`needs_tools=False`) | Model gets the paste inline; overflow |
| `\\NAS\cases\x\ffs - which messaging…` / `//nas/…` | `direct_reply` / `conversation` | none | same |
| `/mnt/cases/x/ffs which apps…` | `managed_task` / **`shell`** | filesystem/terminal — no RE | same |
| `Analyze D:\cases\x\app.apk: what servers…` | `direct_reply` / `conversation` | none | same |
| `reverse engineer D:\cases\x\ffs` | `managed_task` / `reverse engineering` | `reverse_engineer` | Only this wording works today |

A 3 000-file fake FFS under `tmp` produced provider calls of 12k → 12k → **24k → 36k → 37k** chars with only `filesystem` offered; `store.list_rows(task_id)` never contained a `kind == "ffs"` row. That is the overflow.

---

## Root cause (D1 + D2, citations verified)

### A. Intent never fires for a path + dump wording (D2)

`skill.requested` is a single regex for the verbs `reverse[- ]?engineer|decompile|disassemble` (`backend/app/reverse_engineering/skill.py:6`, `:10–11`). A path plus "FFS" / "extraction" / "dump" / "fs" / "apk" never matches. `classify_task` and `requests_agent_tools` both gate on that helper (`agent/planning.py:418–420`, `:464–466`), so the task class stays `shell` (keyword hit on `install`) or falls through to `is_plain_conversation` → `conversation`.

The tool-exposure keyword hook also needs a **leading space** (`agent/tool_exposure.py:202–204`: `" reverse engineer"`, `"rea "`, `"investigate the extract"`). Path-first prompts never match it, so `rea_investigate` is not retrieved either.

When the baseline is not `managed_task`, a confidence-accepted `direct_reply` collapses the class to `conversation` (`decision/owner_turn.py:325–331`), and `infer_needs_tools` then returns `False` for conversation (`agent/tool_exposure.py:168–169`, `ingress_gate.py:100–103`). **No tools ship at all.** That is the dominant failure for Taco's pasted forms.

`is_explicit_action` (`owner_turn.py:174–181`) does not recognise an FFS/APK path + question, so the action floor never forces `managed_task` / `handoff`.

### B. Even when RE is selected, `prepare` never classifies a folder as FFS (D1)

The skill prompt steers the model to `action=prepare` (`agent/loop.py:2777–2779` appends `skill.prompt_block`; `skill.py:14–28` text is "Start with action=prepare, target=…"). `store.prepare` → `classify` returns `"javascript"` or `"source"` for any directory (`store.py:147–150`) — never `"ffs"`. It then **copies and fingerprints the whole tree** (`store.py:175–214`) and hits hard caps `MAX_FILES = 50000` / `MAX_BYTES = 8 GiB` (`store.py:19–20`). RFC-0208's `prepare_ffs` / background ingest / `ffs_query` (`store.py:216+`, `ffs_ingest.py`, `runtime.py:202–268`) are never reached.

Under the limit, `prepare` returns `kind=source` plus the workflow line *"Use normal repository tools…"* (`runtime.py:187–190`, also restated in `tools/reverse_engineer.py:24`). The completion check then loops the model back to prepare (`agent/loop.py:899–905`: no saved report → "Use reverse_engineer to prepare…"). The model is told to use ordinary file tools on a multi-gigabyte dump.

### C. Alias steers RE keywords to the REA MCP tool (D1; refined by D2)

`CAPABILITY_ALIASES` maps `"rea"`, `"reverse-engineer"`, `"reverse_engineer"` → `"rea_investigate"` (`agent/tool_exposure.py:84–86`). The keyword hook at `:202–204` then appends `rea_investigate`. With `settings.rea.investigation_roots` empty (the default — `config.py:349–356`, `Field(default_factory=list)`), every path is denied with `detail="roots_empty"` (`security/rea_paths.py:209–213`). The native `reverse_engineer` tool is never the one retrieved by those keywords.

`tool_retrieval.py:97` also lists `("rea", "reverse engineer", "reverse-engineer", "morluto")` under `rea_investigate`, so prompt retrieval can pull REA in preference to the native tool.

### D. Context flood is many capped results, not one uncapped read (D1 corrected by D2)

`ToolResult.text` already truncates each observation at **12 000** characters (`tools/base.py:24–31`). The flood is **many** of those results across the balanced policy's **28 steps** (`agent/planning.py:33`, `agent/loop.py:2603` / `:2899`). `filesystem.list` is uncapped (`tools/filesystem.py:516–524`); `filesystem.search` walks the **full tree before slicing** (`:527`: `list(path.rglob(pattern))[:400]`); `read` inlines up to 2 MB (`:529–533`). On the fallback path the 9B lists, searches and reads members; each call returns ≤12k, but 28 of them blow the context. Measured on the box: 37k chars mid-run with only `filesystem` exposed.

There is no hard per-turn context budget that refuses to inline a dump. Ingress spill (`agent/ingress_gate.py`, `HEURISTIC_BIG_CHARS = 12_000`) and segmented compression (`agent/segmented_input.py`, `agent/intake.py`) can shrink a *paste*, but they still leave the worker free to `filesystem.list` / `search` / `read` the on-disk dump afterwards.

### E. Taco's `allowed_directories` and REA roots are unverified (D1 item 4)

Defaults admit the home profile and, on Windows, every mounted drive (`config.py:987–1014`, `_windows_owner_drives` at `:622–640`). REA roots default to `[]`. Whether Taco's live values admit `D:\cases\…` or a UNC share is unknown; a missing root currently surfaces only as a tool error the model may narrate, not as an owner-visible diagnostic. Do **not** assume his values in this RFC — add a verification path.

### Discrepancies noted while verifying

- D1 said "filesystem.list is uncapped and read inlines up to 2 MB, which floods context". Verified for list/read; D2 is right that the flood is many 12k results over 28 steps, not a single uncapped observation. `search`'s full-tree walk (`filesystem.py:527`) is the expensive piece D1 did not name.
- D1's `rea_paths.py:209–213` citation is exact for `roots_empty`.
- D1's `store.py:147–150` / `:19–20` / `loop.py:2777` / `skill.py:14–28` citations are exact.
- D2's `runtime.py:187–190`, `loop.py:899–905`, `base.py:24–31`, `filesystem.py:527`, `skill.py:6`, `tool_exposure.py:202–204`, `owner_turn.py:325–331` citations are exact on this tip.

---

## Decision

Ship **one RFC, six implement slices**. Routing is **deterministic in the reflex / pre-model lane**, not "hope the 9B picks the tool". Large inputs never enter context. Answers are grounded in the ingested index with path citations. Progress and failures are owner-visible on the channels the portal actually consumes.

### Owner-visible channel (normative; do **not** use `publish_owner_text`)

Traced on `development` @ `11b264a7` and locked by RFC-0225 (#652 @ `916cf256`):

- **With a task** (every path+question turn creates one): publish on the **task stream** only.
  - Visible progress / failure: `BUS.publish(task_id, "<kind>", "<title>", "<detail>", stage=…)` — consumed by `frontend/src/chat/ownerChatView.ts:365` (`filterWorkEvents` keeps every kind except `assistant_delta` / `chat_tts` / `replace_previous_text`, `:40`, `:76–79`) and by Show work (`components/TaskActivity.tsx:296` renders `event.title`).
  - Spoken: `BUS.publish(task_id, "chat_tts", "<title>", "<text>", stage=…)` — consumed by `frontend/src/tts/useTaskSpeech.ts:64` / `:43`. Title must **not** be `"Speak reply"` (that joins the reply prefix at `:48–50`). Speech is skipped once the task status is `completed` (`:47`), so every spoken line is published **before** the task's terminal update.
- **Without a task** (settings / diagnostic probes): reuse RFC-0225's `engine_coexistence.owner_line(text, *, level, engine_id=None, task_id=None, title="Local engines")` (#652 @ `916cf256`, §Owner-line surfaces) with **`title="Reverse engineering"`**, shown and spoken by the owner-line surfaces #652 specifies (`frontend/src/hud/EngineNotices.tsx` and its classic-mode twin). That path publishes `engine_notice` on `OWNER_CHAT_CHANNEL` and, when a `task_id` is known, also mirrors onto the task stream. It does **not** call `publish_owner_text`.
  - **Dependency (not a gate):** `owner_line` is docs-only on #652 today; `backend/app/inference/engine_coexistence.py` does not exist on `development` @ `11b264a7`. The **with-task** path (`BUS.publish` on the task stream) works now and is what every path + question turn uses. Only S2's **no-task** `roots_empty` line needs `owner_line`, so that one call and its test (`test_roots_empty_without_task_uses_engine_owner_line`) land in S2 **after RFC-0225 S3's implement PR adds `engine_coexistence.owner_line`**. If S2 is ready first, it ships everything else and the no-task call follows as an S2 follow-up commit on the same branch once 0225-S3 is on `development`; S2 does not add its own owner channel or a placeholder.
- **Forbidden:** `persona/chat_delivery.py::publish_owner_text` / `enqueue_chat_tts` / polling `GET /api/owner/chat/tts/pending`. No client in `frontend/src`, `android/`, `extensions/` or the Manager listens (RFC-0225 @ `62001d9`, "What the portal actually consumes").

### Deterministic path + question router (normative)

A new helper `agent/planning.py::ffs_or_apk_investigation(prompt) -> tuple[str, str] | None` returns `(target, kind)` where `kind ∈ {"ffs", "apk"}`, or `None`.

Detection rules (all must hold):

1. The latest owner utterance (`latest_user_utterance`) contains a local path in one of these forms (reuse / extend `_PATH_OR_URL` at `planning.py:269–271`):
   - Windows drive: `D:\cases\x\ffs`, `D:/cases/x/ffs`
   - UNC: `\\NAS\cases\x\ffs`, `//nas/cases/x/ffs`
   - POSIX absolute: `/mnt/cases/x/ffs`
2. **And** either:
   - the path suffix is `.apk` / `.apks` / `.xapk` → `kind="apk"`, or
   - the surrounding text matches dump wording (case-insensitive, bounded): `\b(ffs|full[\s-]?file[\s-]?system|file[\s-]?system\s+dump|android\s+file[\s-]?system|forensic\s+(?:image|dump)|extraction|extract(?:ed|ion)?\s+(?:dump|image|folder)|android\s+dump|dump\s+root)\b` (D2 2026-10-20: `android\s+file[\s-]?system` covers Taco's "this is the root of an Android file system" / "an Android file system root"), **or**
   - a **bare** `file system` / `file-system` (a space or hyphen is required, so the single word "filesystem" never counts) **followed by** an absolute path in a rule-1 form within 40 characters: `\bfile[\s-]system\b[^\n]{0,40}?(?:[a-z]:[\\/]|\\\\|//|(?<!\w)/)` (e.g. "file system at D:\cases\x\phone", "file system root: /mnt/cases/x/phone"), **or** the path's final component is exactly `ffs` / `extraction` / `extract` / `dump` / ends with `_ffs` / `-ffs`, **or** the path points at a `.zip` / `.tar` / `.tar.gz` / `.tgz` / `.img` / `.raw` / `.dd` named like an extraction,
3. **And** there is a question or investigative ask (a `?`, or an interrogative / investigative stem: `what|which|where|when|how many|who|show|list|find|analyse|analyze|inspect|investigate|summarise|summarize`).

`route_request`, `classify_task`, `requests_agent_tools`, `is_explicit_action` and the owner-turn action floor all call this helper. When it returns non-`None`:

- `route_request` → `RequestRoute(MANAGED_TASK, "reverse engineering")`
- `classify_task` → `"reverse engineering"`
- `is_explicit_action` → `True` (forces `managed_task` / `handoff` even if Jev/Laya would have picked `direct_reply` — closes the `owner_turn.py:325–331` hole)
- `tool_names_for` always includes `reverse_engineer` (native)

**Precedence vs RFC-0231:** if this helper matches, the large-prompt pipeline does **not** split the turn. The RE path owns it.

**Not matched:** ordinary source trees without dump wording, bare "what's in this folder", weather, chat. Those keep today's classifiers.

### Pre-model / reflex dispatch (normative)

In `agent/loop.py::create_task` (and the managed-task entry of `_run`), when `ffs_or_apk_investigation(prompt)` matches **and** `task_class == "reverse engineering"`:

1. Publish task progress: title `"Starting reverse-engineering ingest"`, detail naming the target (redacted to the last two path components for the spoken `chat_tts` twin).
2. Call the existing service — **port, don't rewrite**:
   - `kind="ffs"` → `SERVICE.ingest(source=target, question=…, allowed=settings.allowed_directories, task_id=task.id, background=True)` (`runtime.py:202–252` → `store.prepare_ffs` → `ffs_ingest.FFSIngest`).
   - `kind="apk"` → `apk_sidecar.prepare_apk(...)` then the existing sidecar run (after #660's allow-list lands; see S5).
3. Bind the investigation id on the task working set. Subsequent model turns see `reverse_engineer` with `action=ingest_status` / `ffs_query` / `evidence` / `report` already primed by an updated skill prompt (S3).
4. On `PermissionError` / `FileNotFoundError` / `ValueError` from prepare/ingest: publish a task event with a **clear failure line** (examples below) **and** a `chat_tts` twin; do not hand the dump to the 9B.

This runs **before** the first worker `MANAGER.chat` call. The 9B never sees the dump bytes.

### RE completion check (normative; S3 rewrites `loop.py:899–910`)

Today, for any task where `skill.requested(prompt)` is true or `working.task_class == "reverse engineering"`, `agent/loop.py:899–905` accepts completion only if a row for the task has status `reported` / `partial` / `closed` **and** a saved `report.json`. Otherwise `:905–910` injects *"Reverse engineering requires a saved investigation report. Use reverse_engineer to prepare the supplied target, …"* and returns `False`. For an FFS task that is wrong twice:

- While RFC-0208's background ingest runs, the row is `prepared` → `ingesting` (`ffs_ingest.py:620`) and only becomes `completed` at `:783`. The check tells the model to **prepare** again, which is the prepare loop D1 traced.
- Simply accepting completion while ingest runs would kill the ingest: a terminal `_update` calls `investigations.release_task(task_id, …)` (`loop.py:786–788`), and `release_task` calls `ffs_ingest.cancel` and cancels the active ingest task for every row of the task (`runtime.py:487–493`).

**S3 replaces `:899–910`** with one helper, `AgentLoop._re_completion_gate(task_id, working) -> str | None` (`None` = complete; a string = the internal message to append before `return False`). It reads `store.list_rows(task_id)` and decides per row, in this order:

1. Any row with status `reported` / `partial` / `closed` and `report.json` → **complete** (unchanged rule).
2. A `kind == "ffs"` row whose ingest is still running (`ffs_ingest.running(id)` or `SERVICE.active[id]` not done) → **wait, no model call, no prepare text**. The loop awaits the active ingest task in 15 s slices (`asyncio.wait({SERVICE.active[id]}, timeout=15)`), and each slice calls `self._update(task_id, status="running", stage="understand", current_action="Indexing FFS …")` and publishes the `Indexing FFS` progress event from §Progress during ingest, so Show work and the task's `updated_at` keep moving. When it finishes the gate re-evaluates (case 3 or 4).
3. A `kind == "ffs"` row with status `completed` and no report → message *"The FFS index for <id> is complete (<N> files). Answer from reverse_engineer action=ffs_summary / ffs_query / ffs_read, record evidence, then report findings that cite index paths. Do not call prepare and do not use filesystem tools on the dump."*
4. A `kind == "ffs"` row with status `interrupted` → publish the `FFS ingest interrupted` failure line (task event + `chat_tts`), then message *"Call reverse_engineer action=ingest with investigation_id=<id> to resume from the checkpoint. Do not call prepare."*
5. A `kind == "ffs"` row the owner `cancelled` (no report) → publish the `FFS ingest cancelled` line (task event + `chat_tts`, before the terminal update) and **complete** with that line as the result. No loop.
6. No FFS row and no report (source / native / browser / APK targets) → today's message, byte-identical. Live behaviour for non-dump targets is preserved.

The same `max_steps` budget bounds cases 3 and 4; the wait in case 2 spends no steps. Owner cancel of the task still ends the wait through the existing cancel path (`release_task(..., cancelled=True)`).

### Alias and REA coexistence (normative; D2 refinement of fix b)

Per Taco 2026-10-09: RE extends REA; nothing is removed.

1. Change `CAPABILITY_ALIASES` (`agent/tool_exposure.py:84–86`) so `"rea"`, `"reverse-engineer"`, `"reverse_engineer"` resolve to the native **`reverse_engineer`**.
2. Keep `rea_investigate` registered. Append it in `tool_names_for` **only when** `configured_investigation_roots()` is non-empty **and** intersects `allowed_directories` (reuse `intersect_roots` from `rea_paths.py`). When roots are empty, do **not** append it.
3. Drop `rea_investigate`'s retrieval terms at `agent/tool_retrieval.py:97` (the tuple `("rea", "reverse engineer", "reverse-engineer", "morluto")`). Native `reverse_engineer` already owns those terms at `:77`. Leave `"morluto"` only if a future REA-specific ask needs it — default is drop the whole entry so keywords cannot pull REA over RE.
4. When a caller still hits `rea_investigate` with empty roots, surface `roots_empty` through the owner channel above (task stream if a task exists; otherwise `engine_coexistence.owner_line(..., level="error")`). Message (exact):

   > REA investigation roots are not set. Open Settings → Integrations → Reverse Engineering and add the folders that hold your dumps (or set `REA_INVESTIGATION_INPUT_ROOTS_JSON`). ANZU's built-in reverse-engineering ingest still works for FFS and APK paths without those roots.

### Context budget (normative)

Hard rule: **large inputs never enter the model context.**

| Cap | Value | Where |
| --- | --- | --- |
| Per-turn owner / tool text budget | **24 000 characters** total across the user turn + every tool observation in that turn | Enforced in `agent/loop.py` before appending a tool message; over-budget content is replaced with a stub pointing at `read_ingress` / `ffs_query` |
| Single tool observation | keep today's 12 000 (`tools/base.py:24`) | unchanged |
| `filesystem.list` in an RE task | first **200** entries + `"… and N more; use reverse_engineer action=ffs_query"` | `tools/filesystem.py` |
| `filesystem.search` | **stream / early-stop**: stop walking after 400 matches (do **not** materialise the full `rglob` list first — today's `:527` walks everything). Cap returned lines at 200 in RE tasks with the same redirect. | `tools/filesystem.py` |
| `filesystem.read` in an RE task | refuse files **> 64 KiB** with a redirect to `ffs_query` / `ffs_read` | `tools/filesystem.py` |
| Pasted extraction in the prompt | existing ingress gate (`HEURISTIC_BIG_CHARS = 12_000`) still spills; the new router also treats a paste that is itself an FFS listing / `tree` dump as over-budget and sends it through `store_ingress_blob` + chunked retrieval, never as the worker user message | `agent/ingress_gate.py` + new helper |

A pasted full extraction (no path, just the listing) triggers the budget path: spill → brief → `read_ingress` for exact slices. If a path is also present, the path router wins and ingest owns it.

### New / extended RE tool actions (port existing ingest; add summary + bounded read)

All live under the existing `reverse_engineer` tool (`tools/reverse_engineer.py`). Port `SERVICE.ingest` / `ffs_query` / `ingest_status` unchanged.

| Action | Behaviour |
| --- | --- |
| `ingest` / `ingest_status` / `ffs_query` | unchanged (RFC-0208). **`ffs_query` default `limit` becomes 50** (hard max stays `MAX_QUERY_LIMIT = 500` in `ffs_ingest.py:68`); pages of 25–50 are the documented norm. Response stays the compact index line (`path`, `bytes`, `sha256`, `mtime`, `magic_hex`, `type`) — never file bodies. When a requested page would exceed the 12 000-char observation cap (`tools/base.py:24–31`), `reverse_engineer` returns only whole NDJSON rows that fit, plus `truncated: true` and `next_offset`, so `ToolResult.text` never cuts a row mid-JSON. |
| `ffs_summary` **(new)** | Arguments: `investigation_id`, optional `path_contains`. Returns per-package (Android: under `data/data/<pkg>/`, `data/app/`, `system/…`) roll-ups: package name, file count, total bytes, top suffixes, whether a `databases/` or `shared_prefs/` tree exists. Built from the NDJSON index only — no member I/O beyond what ingest already did. Cap: 100 packages per call, with `offset`. |
| `ffs_read` **(new)** | Arguments: `investigation_id`, `path` (index-relative), `offset` (bytes, default 0), `limit` (bytes, default 4096, **max 16 KiB**). Serves a bounded slice of one indexed member by re-opening the dump read-only (same admit rules as ingest). Refuses paths not in the index. Returns `{path, offset, limit, bytes, sha256, text_or_hex, truncated}`. |
| `apk_prepare` **(new action name on the same tool)** | Thin wrapper over `apk_sidecar.prepare_apk` (RFC-0207). Sequenced **after** #660 (allow-list-first `prepare_ffs`) and **#661** (D1's stacked allow-list gate for `store.prepare` / `prepare_apk`, head `4b81ac11`). Same admit rules. |

### Skill prompt (S3)

Replace the prepare-first block (`skill.py:14–28` and the FFS branch of `guide` at `:44–55`) so the model is told, in this order:

1. For an FFS / extraction / dump path: `action=ingest` (background) → poll `ingest_status` → `ffs_query` / `ffs_summary` / `ffs_read` → `evidence` → `report` with findings that cite index paths.
2. For an `.apk`: `action=apk_prepare` → existing sidecar operations.
3. Never `filesystem.list` / `search` / `read` a dump. Never paste dump contents into the reply.
4. Keep the existing source / native / browser guidance for non-dump targets.

### Failure lines (exact owner-visible text)

Published as task events (kind `error` or `progress`) **and** `chat_tts` twins:

| Condition | Title | Detail |
| --- | --- | --- |
| Path outside `allowed_directories` | `FFS path not allowed` | `That folder is outside the folders ANZU may read. Add it under Settings → Workspace → Allowed folders (or allow the drive), then ask again.` |
| Path missing / unreadable | `FFS path not found` | `I can't open <last two components>. Check the path and that the drive is mounted.` |
| Ingest still running, owner asks again | `FFS ingest in progress` | `Still indexing <N> files so far. I'll answer from the index as soon as it finishes; you can ask me to cancel.` (The promise is kept by the completion check, case 2: the task waits for the ingest and then answers.) |
| Ingest interrupted | `FFS ingest interrupted` | `Indexing stopped at <path> (<reason>). Say "resume the ingest" and I'll continue from the checkpoint.` |
| Owner cancelled the ingest, no report | `FFS ingest cancelled` | `You stopped indexing <last two components> at <N> files. Ask again to start a fresh ingest.` |
| REA roots empty (when REA is the caller) | `REA roots not set` | the message under "Alias and REA coexistence" §4 |
| APK admit failure | `APK not admitted` | mirror the allow-list / missing-file wording above |

### Allowed-directories + REA-roots diagnostic (D1 item 4)

A new read-only probe, exposed both as `reverse_engineer action=status` fields and as `GET /api/investigations/diagnostics`:

```
{
  "allowed_directories": [...],          # as configured
  "allowed_directories_exist": [...],    # which of those paths exist on this machine
  "rea_investigation_roots": [...],
  "rea_roots_intersect_allowed": [...],
  "rea_roots_empty": true|false,
  "ffs_admit_probe": null | {"path": "...", "ok": true|false, "reason": "..."}
}
```

When `rea_roots_empty` is true, the Settings → Integrations → Reverse Engineering page (add-alongside: one status line only, no redesign) shows the same sentence as the owner-line above. No assumption about Taco's values — the probe reports what is configured.

### Progress during ingest

Reuse RFC-0208's row `progress` / `ffs` block. On every checkpoint (`ffs_ingest.py` already writes them), publish a task event:

- kind `progress`, title `Indexing FFS`, detail `\<files\> files · \<bytes\> · last \<path\>`, stage `understand`.
- Do **not** spam `chat_tts` per checkpoint; one spoken line at start, one at completion / failure.

Show work already renders `event.title` (`TaskActivity.tsx:296`); Phone and the ops rail keep working because they read the same task events / GET.

---

## Slices

One developer, one named model (**fast off**), one PR each. No stubs, soft-fails or orphans. Live UI changes are **add-alongside only**.

### Handoff order (no hard gates; port with citations)

Shared files and who goes first. Later slices merge `development` in (a merge commit; no rebase, no force-push) and port, citing the earlier PR's hunk:

| File | First owner → next |
| --- | --- |
| `backend/app/reverse_engineering/store.py` | **#660** (`24169e85`, allow-list-first `prepare_ffs`) → **#661** (`4b81ac11`, D1's stacked allow-list gate for `store.prepare` / `prepare_apk`) → **this RFC S3** (dump-shaped classifier inside `prepare` that delegates to `prepare_ffs`) → S5 |
| `backend/app/reverse_engineering/{runtime,skill,ffs_ingest}.py` | **#657** (tab container) → **this RFC S3 / S4** (skill text, `ffs_summary` / `ffs_read`, `ffs_query` default limit) |
| `backend/app/decision/owner_turn.py` | **#649** (RFC-0224) → **this RFC S2** (action floor). Port #649 hunks; do not wait for the draft to land. |
| `backend/app/agent/loop.py` | **#649** (RFC-0224) → **this RFC S3** (pre-model dispatch + RE completion check `:899–910`) → **S4** (24k per-turn budget hunk). Port #649 hunks; do not wait for the draft to land. |
| `backend/app/agent/planning.py`, `agent/tool_exposure.py`, `agent/tool_retrieval.py` | **this RFC S2** (sole owner for the new helper + alias fix) |
| `backend/app/tools/filesystem.py` | **this RFC S4** (list/search/read caps + early-stop search) |
| `backend/app/tools/reverse_engineer.py` | **this RFC S3** then S5 (`apk_prepare` action) |
| `.github/workflows/pr-tests.yml` | Architect owns the workflow file; S1 names the step, S6 may append a focused line only if the full-suite step is too slow — prefer relying on the existing "Run full backend suite" step. |

On a conflict, merge `development` into the slice branch (merge commit). No rebase, no force-push, no branch deletion.

---

### S1 — Repro xfail (this PR)

**Model:** Composer 2.5 · **fast off**  
**Owns:** `tests/test_rfc0232_ffs_path_routing.py` (new), `docs/rfcs/0232-ffs-path-routes-to-re-tool.md`, `docs/rfcs/README.md` (this RFC's row only), `/workspace/rfc/RFC-0232.md` mirror.

**Tests (concrete; all `pytest.mark.xfail(strict=True)` until the named fix slice removes the marker):**

| Test | Marker removed by |
| --- | --- |
| `test_path_plus_question_routes_to_reverse_engineering[D:\\cases\\x\\ffs what apps are installed and when was WhatsApp last used?]` | S2 |
| `test_path_plus_question_routes_to_reverse_engineering[Here is the Android FFS root D:\\cases\\x\\ffs and the full extraction D:\\cases\\x\\extraction.zip. Which accounts are on the phone?]` | S2 |
| `test_path_plus_question_routes_to_reverse_engineering[\\\\NAS\\cases\\x\\ffs - which messaging apps have databases?]` | S2 |
| `test_path_plus_question_routes_to_reverse_engineering[//nas/cases/x/ffs which messaging apps have databases?]` | S2 |
| `test_path_plus_question_routes_to_reverse_engineering[/mnt/cases/x/ffs which apps are installed?]` | S2 |
| `test_path_plus_question_routes_to_reverse_engineering[Analyze D:\\cases\\x\\app.apk: what servers does it talk to?]` | S2 |
| `test_dump_wordings_route_to_reverse_engineering[ffs]` | S2 |
| `test_dump_wordings_route_to_reverse_engineering[extraction]` | S2 |
| `test_dump_wordings_route_to_reverse_engineering[dump]` | S2 |
| `test_dump_wordings_route_to_reverse_engineering[full-file-system-dump]` | S2 |
| `test_dump_wordings_route_to_reverse_engineering[android-file-system]` — `D:\cases\x\phone this is the root of an Android file system - which accounts are on the phone?` (D2 2026-10-20) | S2 |
| `test_dump_wordings_route_to_reverse_engineering[file-system-abs-path]` — `Here is the file system at D:\cases\x\phone. What apps are installed?` (D2 2026-10-20) | S2 |
| `test_ffs_path_plus_question_calls_ingest_without_overflow` | S3 (+ S4 caps) |

Neither new wording's path ends in `ffs` / `dump` / `extraction`, so only the new rule-2 alternatives can route them.

**CI step:** existing `.github/workflows/pr-tests.yml:94–95` → "Run full backend suite" (`python -m pytest -q -rs`), which collects `tests/test_rfc0232_ffs_path_routing.py`. No workflow edit in S1. Architect owns `pr-tests.yml`.

**Acceptance:** all thirteen cases above (six Taco forms, six dump wordings, one overflow) xfail strictly on `development`; CI green.

**README row:** #652 (open) rewrites the last README paragraph and appends the 2026-10-17 batch paragraph with "Next free after **0229** is **0230**". So that a later merge resolves without a conflict, S1 leaves that paragraph untouched and adds one separate paragraph above it in #652's batch format (bold date label, linked number, status, PR number), which says 0230/0231 are parallel and 0233 is reserved. Once #652 lands, the Architect merges `development` into this branch (merge commit) or, if this PR landed first, makes a docs commit that moves that sentence into #652's single next-free line ("Next free after **0233** is **0234**" once 0230/0231/0233 exist) and drops the separate paragraph, so the README keeps one next-free line.

---

### S2 — Deterministic intent + alias + REA roots visibility

**Model:** Grok 4.6 · **fast off**  
**Owns:** `backend/app/agent/planning.py` (`ffs_or_apk_investigation`, wire into `route_request` / `classify_task` / `requests_agent_tools` / `is_explicit_action` via a thin re-export or direct call from `owner_turn.py`), `backend/app/decision/owner_turn.py` (action floor only — port around #649), `backend/app/agent/tool_exposure.py` (alias → `reverse_engineer`; conditional `rea_investigate`), `backend/app/agent/tool_retrieval.py` (drop `rea_investigate` terms), `backend/app/tools/rea_investigate.py` (surface `roots_empty` through the owner channel when hit), `tests/test_rfc0232_ffs_path_routing.py` (remove the xfail markers from `test_path_plus_question_routes_to_reverse_engineering` and `test_dump_wordings_route_to_reverse_engineering`, all twelve cases), `tests/test_rfc0232_intent_and_alias.py` (new).

**Named tests:**

- `test_dump_wordings_route_across_path_forms` — parametrize the six dump wordings of S1's `DUMP_WORDING_PROMPTS`: (1) path + `ffs`, (2) path + `extraction`, (3) path + `dump`, (4) path + `file-system dump` / `full file system`, (5) path + `Android file system` (`android-file-system`), (6) bare `file system` followed by an absolute path (`file-system-abs-path`); each with a question; Windows, UNC, POSIX.
- `test_bare_filesystem_word_does_not_route` — `D:\src\app what is the filesystem layout?` (one word, no dump wording) and `file system questions in general?` (no path) keep today's route; neither returns `reverse engineering`.
- `test_direct_reply_cannot_bypass_ffs_path` — baseline would be `direct_reply`; after the floor, route is `managed_task` / `reverse engineering` and `reverse_engineer` is exposed.
- `test_alias_maps_to_native_reverse_engineer` — `normalize_capabilities(["reverse_engineer","reverse-engineer","rea"])` → `["reverse_engineer"]`.
- `test_rea_investigate_only_when_roots_configured` — empty roots → not in `tool_names_for`; configured intersecting roots → present alongside `reverse_engineer`.
- `test_roots_empty_reaches_task_stream` — call `rea_investigate` with empty roots under a live task → one task event whose detail contains `Settings → Integrations → Reverse Engineering` **and** one `chat_tts` event; **zero** calls to `publish_owner_text`.
- `test_roots_empty_without_task_uses_engine_owner_line` — monkeypatch `engine_coexistence.owner_line`; assert it is called once with `level="error"` and `title="Reverse engineering"` (RFC-0225, #652 @ `916cf256`). Lands once RFC-0225 S3 adds `owner_line` (see §Owner-visible channel, Dependency).

**CI step:** `.github/workflows/pr-tests.yml:94–95` "Run full backend suite" collects `tests/test_rfc0232_ffs_path_routing.py` and `tests/test_rfc0232_intent_and_alias.py`; the slice is green only when every named test above passes there.

**Acceptance:** the twelve S1 route / wording xfails (including `[android-file-system]` and `[file-system-abs-path]`) are gone and pass; new tests pass; no soft-fail on empty roots.

---

### S3 — Pre-model ingest dispatch + skill + prepare classifier

**Model:** Grok 4.6 · **fast off**  
**Owns:** `backend/app/agent/loop.py` (pre-model dispatch in `create_task` / `_run` start, and the RE completion check rewrite at `:899–910` per §RE completion check — port around #649), `backend/app/reverse_engineering/skill.py`, `backend/app/reverse_engineering/store.py` (dump-shaped branch at the top of `prepare` that delegates to `prepare_ffs` when the classifier says FFS — **after #660 and #661**; cite their hunks), `backend/app/reverse_engineering/runtime.py` (workflow string for FFS no longer says "use normal repository tools"), `backend/app/tools/reverse_engineer.py` (document ingest-first), `tests/test_rfc0232_ffs_path_routing.py` (remove the overflow xfail), `tests/test_rfc0232_ingest_dispatch.py` (new).

**Named tests:**

- `test_ffs_path_plus_question_calls_ingest_without_overflow` — green; asserts a `kind=="ffs"` row for the task, every provider call ≤ 24 000 chars, and `reverse_engineer` was in the offered tools.
- `test_prepare_on_ffs_folder_delegates_to_prepare_ffs` — `store.prepare(<ffs folder>, …)` returns `kind=="ffs"` and does not copy the tree (no `workspace/target/…` tree whose size matches the dump).
- `test_ingest_progress_reaches_task_stream` — at least one `progress` event titled `Indexing FFS` or `Starting reverse-engineering ingest`, plus a start `chat_tts`.
- `test_bad_path_failure_line` — missing path → exact failure title/detail above; no provider call with dump contents.
- `test_pasted_extraction_uses_budget_path` — a 50 KB pasted `tree` listing with a question, no path → ingress spill + brief; worker user message does not contain the raw listing.
- `test_completion_accepts_ffs_ingest_without_prepare_loop` (D2 2026-10-20) — 3 000-file fake FFS, ingest dispatched in the background, scripted provider tries to finish while the row is `ingesting`: no internal message contains `Use reverse_engineer to prepare`, the ingest is **not** cancelled (row reaches `completed`), at least one `Indexing FFS` progress event is published during the wait with no provider call, then the model is told to answer from the index; after a scripted `report` the task completes; total provider calls ≤ 4.
- `test_completion_resumes_interrupted_ingest_not_prepare` — row forced to `interrupted` → one `FFS ingest interrupted` task event + `chat_tts`, and the injected message names `action=ingest` with the investigation id, never `prepare`.
- `test_completion_cancelled_ingest_completes_with_line` — owner cancels the row → task completes with the `FFS ingest cancelled` detail as result; the `chat_tts` twin is published before the `completed` update; no loop.
- `test_completion_keeps_prepare_text_for_source_targets` — a source-folder RE task with no report still gets today's message byte-identical (live behaviour preserved).

**CI step:** `.github/workflows/pr-tests.yml:94–95` "Run full backend suite" collects `tests/test_rfc0232_ffs_path_routing.py` and `tests/test_rfc0232_ingest_dispatch.py` (which holds `test_completion_accepts_ffs_ingest_without_prepare_loop` and the other completion tests); the slice is green only when every named test above passes there.

**Acceptance:** S1 overflow xfail removed and green; prepare no longer copies FFS trees; the RE completion check never sends an FFS task back to `prepare` and never ends a task while its ingest runs.

---

### S4 — Context caps + `ffs_summary` / `ffs_read` + compact `ffs_query`

**Model:** Composer 2.5 · **fast off**  
**Owns:** `backend/app/tools/filesystem.py` (list/search/read caps; **early-stop search** so `rglob` does not walk the full tree before slicing), `backend/app/reverse_engineering/ffs_ingest.py` (`query_index` default limit 50; new `summarise_index`, `read_indexed_member`), `backend/app/reverse_engineering/runtime.py` (`ffs_summary`, `ffs_read` methods), `backend/app/tools/reverse_engineer.py` (actions + schemas), `backend/app/agent/loop.py` (24k per-turn budget check when appending tool messages — small, cited hunk), `tests/test_rfc0232_context_caps.py` (new), `tests/test_rfc0232_ffs_summary_read.py` (new).

**Named tests:**

- `test_search_early_stops_before_full_walk` — a tree of 5 000 files; `search` returns ≤ 400 matches and the walk counter stops ≤ 400 + small constant (instrument with a monkeypatched `rglob` iterator).
- `test_list_capped_in_re_task` — RE task class → list returns ≤ 200 entries + redirect line naming `ffs_query`.
- `test_read_refuses_large_file_in_re_task` — 128 KiB file → refuse with redirect; no 12k observation of its body.
- `test_ffs_query_default_page_is_50` — default call returns `limit == 50`.
- `test_ffs_query_truncates_on_row_boundary` — `limit=500` over long paths that exceed 12 000 chars → the observation holds only whole NDJSON rows (each line `json.loads` cleanly), `truncated is True`, and `next_offset` equals the number of rows returned.
- `test_ffs_summary_per_package` — seeded index with three packages → summary names each with file count / bytes; no member bodies.
- `test_ffs_read_bounded` — `limit=16_384+1` refused; `limit=4096` returns exactly that many bytes from an indexed member.
- `test_per_turn_budget_redirects_over_24k` — a scripted tool that returns 12k three times in one turn → the third observation is replaced with the budget stub.

**CI step:** `.github/workflows/pr-tests.yml:94–95` "Run full backend suite" collects `tests/test_rfc0232_context_caps.py` and `tests/test_rfc0232_ffs_summary_read.py`.

**Acceptance:** all named tests green; today's non-RE filesystem behaviour unchanged (add-alongside caps apply only when `task_class == "reverse engineering"` or the tool context flag `re_task=True` is set).

---

### S5 — `apk_prepare` action + diagnostics

**Model:** Composer 2.5 · **fast off**  
**Owns:** `backend/app/tools/reverse_engineer.py` (`apk_prepare` action), `backend/app/reverse_engineering/runtime.py` (thin wrap of `apk_sidecar.prepare_apk`), `backend/app/api/investigations.py` (`GET /api/investigations/diagnostics`), Settings Integrations status line (add-alongside one `<p>` in the existing RE panel — file owned by whoever last touched it; cite), `tests/test_rfc0232_apk_prepare.py` (new), `tests/test_rfc0232_diagnostics.py` (new).

**Sequencing:** land **after** #660 (`24169e85`, allow-list-first `prepare_ffs`) **and #661** (`4b81ac11`, D1's stacked allow-list gate for `store.prepare` / `prepare_apk`). Merge `development` in (no rebase); port their admit helpers by citation. Do not reimplement admit.

**Named tests:**

- `test_apk_prepare_action_admits_under_allowlist` — in-list `.apk` → investigation row; out-of-list → same `PermissionError` message as #660 / #661 (`FFS_OUTSIDE_ALLOWED` / #661's APK twin).
- `test_apk_path_plus_question_routes_and_dispatches` — `Analyze D:\cases\x\app.apk: what servers…` → router `apk` + `apk_prepare` called in the pre-model dispatch (mock the sidecar).
- `test_diagnostics_reports_empty_rea_roots` — with defaults → `rea_roots_empty is True` and the owner-facing sentence is present in the payload.
- `test_diagnostics_probe_does_not_leak_outside_path_existence` — probe of an outside path returns the constant outside message whether or not it exists (#660 property).

**CI step:** `.github/workflows/pr-tests.yml:94–95` "Run full backend suite" collects `tests/test_rfc0232_apk_prepare.py` and `tests/test_rfc0232_diagnostics.py`.

**Acceptance:** all green; Settings page shows the empty-roots sentence without a redesign.

---

### S6 — End-to-end acceptance + CI pin

**Model:** Composer 2.5 · **fast off**  
**Owns:** `tests/test_rfc0232_e2e.py` (new), optional focused line in `.github/workflows/pr-tests.yml` (Architect is the CI-file owner — coordinate before editing).

**Named tests:**

- `test_e2e_windows_ffs_path_answers_from_index` — fake FFS → ingest → `ffs_summary` → report; final assistant message cites at least one index path; no provider call exceeds 24k chars; Show-work events include the ingest progress title.
- `test_e2e_unc_path_form` — `\\NAS\…` and `//nas/…` both admit under an allowed UNC root (use `LOCAL_NETWORK_SCOPE` / explicit UNC allow as in `tools/safety.py:194–216`).
- `test_e2e_pasted_extraction_no_overflow` — 100 KB paste + question → budget path; zero context-overflow recoveries.
- `test_e2e_apk_path` — `.apk` + question → `apk_prepare` dispatched; no filesystem walk of the APK as a zip via `filesystem.search`.

**CI:** prefer the existing "Run full backend suite" step. If that step's wall clock exceeds the job timeout after these tests land, Architect adds a focused step `Run RFC-0232 FFS routing tests` running `pytest -q tests/test_rfc0232_*.py` **before** the full suite; this slice only proposes the line, does not land it without Architect ack.

---

## Out of scope

- Persona surfaces / morph / auto-switch (RFC-0218 S3b).
- Large-prompt splitting for non-path turns (RFC-0231) — this RFC only claims precedence when the path helper matches.
- PC first-response latency budget (RFC-0230).
- Fixing the orphaned `publish_owner_text` callers for running-models / persona-switch (RFC-0225 S3 on #652 moves the running-models notice to `owner_line`; RFC-0218 on #663 moves the persona-switch line to the task `chat_tts`; not this bug).
- Rewriting `ffs_ingest.py` hashing / custody (RFC-0208 stands).
- Android companion UI.

---

## Acceptance (RFC-level)

1. Every prompt in the S1 table (Taco forms and the six dump wordings) routes to `managed_task` / `reverse engineering` and exposes `reverse_engineer`, including the forms that today return `direct_reply`.
2. A path + question on an FFS root or extraction calls `SERVICE.ingest` (or `apk_prepare` for `.apk`) before the first worker model call.
3. No provider call in the overflow repro exceeds 24 000 characters; `filesystem.search` does not walk a whole dump before slicing.
4. Answers cite index paths; Show work shows ingest progress titles; failures use the exact lines above on the task stream (+ `chat_tts`), never `publish_owner_text`.
5. Empty REA roots produce the actionable Settings sentence on the task stream or via `engine_coexistence.owner_line` + the owner-line surfaces (#652 @ `916cf256`).
6. #660 and #661 allow-list behaviour is preserved (constant outside-allow message; no existence leak).
7. An FFS task is never sent back to `prepare` by the completion check, and never completes while its ingest runs (`test_completion_accepts_ffs_ingest_without_prepare_loop`).
8. No stubs, soft-fails, or orphaned events.

---

## Live-UI add-alongside

| Live behaviour | Preserved? | Added alongside |
| --- | --- | --- |
| Show work / ops rail / Phone task events | Yes | New progress / failure titles only |
| `useTaskSpeech` on `chat_tts` | Yes | Start / failure spoken lines (title ≠ `"Speak reply"`) |
| Settings → Integrations → Reverse Engineering panel | Yes | One status line for empty REA roots |
| RFC-0225 owner-line surfaces (EngineNotices + classic twin) | Yes (land with #652) | Reused for the no-task `roots_empty` line, `title="Reverse engineering"` |
| RE completion check for non-dump targets (`loop.py:899–910`) | Yes, byte-identical message | FFS-only cases: wait for ingest, answer from index, resume, cancelled line |
| Persona switch / HUD morph (RFC-0218) | Untouched | — |
