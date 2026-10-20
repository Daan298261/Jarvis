# RFC-0232: FFS / APK path + question routes to the RE tool (no context overflow)

**Status:** accepted  
**Priority:** P0 (Taco bug, 2026-10-20 14:55 — "ANZU didn't call the reverse-engineering tool")  
**Author:** Jarvis Architect  
**Date:** 2026-10-20  
**Root-cause credit:** D1 (initial trace) + D2 (peer corrections). Every citation below was re-verified against `development` @ `a44da353` (after #648, #649, #657 and #660 landed; `store.py` is the only cited file that moved after `d85c9d4c`).  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §6 (deterministic rule → reflex → tools → model), §8 (verify from evidence), §19 ("Do use fast deterministic mechanisms where they are superior to AI reasoning."), §20 Q1 / Q6 / Q7.  
**Extends (do not rewrite):** [RFC-0208 FFS dump self-ingest](0208-ffs-dump-self-ingest.md) (`store.prepare_ffs`, `ffs_ingest`, `ffs_query`, `POST /api/investigations/ffs`), [RFC-0207 APK reverse sidecar](0207-apk-reverse-sidecar.md) (`apk_sidecar.prepare_apk`), [RFC-0200 REA MCP](0200-rea-mcp-local-investigation.md), [RFC-0201 Reverse Engineer Anything](0201-reverse-engineer-anything.md), [RFC-0206 every-turn Jev/Laya](0206-jev-laya-every-turn-arbitration.md), [RFC-0122 ingress size-gate](0122-ingress-size-gate-spill-and-trajectory-cap.md), [RFC-0182 segmented input](0182-context-and-segmented-agentic-tasks.md).  
**Reconciles with (in progress):** [RFC-0218 S3b](0218-persona-surfaces-and-intent-switch.md) (#658, tasks-path persona switch — this RFC does not touch persona surfaces), RFC-0231 large-prompt pipeline (#665 @ `57106ba5`; **RE path + intent takes precedence** over prompt-splitting, see §Precedence vs RFC-0231), RFC-0230 PC first-response latency (#666 @ `99aef631`; routing is pre-model / reflex, so it cuts the 9B turn rather than adding to it; 0230 goes first on shared files per the CoS ruling), [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) (#652 @ `60573c62`, specs only) for the no-task owner-line channel. RE prepare allow-list chain: **#660** (`prepare_ffs`, landed `90a0010`) and **#661** (`4b81ac11`, `store.prepare` / `prepare_apk`, open onto `development`).  
**Reserved numbers:** 0230 and 0231 are parallel; **0233 is reserved** for another RFC. Touch only this RFC's README row (see S1 for how the row coexists with #652's next-free rewrite).  
**Taco 2026-10-09 ruling (binding):** RE extends and complements REA. No removal. Native `reverse_engineer` (ingest / prepare / ffs_query / apk) stays; `rea_investigate` stays available when REA roots are configured.

This PR is **specs + S1 xfail repro**. Application code lands in the implement slices below.

---

## Problem (what Taco saw)

Taco gave ANZU an Android FFS root path (Windows form such as `D:\cases\x\ffs`), a full FFS extraction, and a question. ANZU never called the reverse-engineering / FFS ingest tool. It tried to put the dump into context and overflowed.

Reproduced on the box against `development` @ `11b264a7` (re-run on `d85c9d4c`: same results) with a mocked 9B (`tests/test_rfc0232_ffs_path_routing.py`, run with `--runxfail`):

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

When the baseline is not `managed_task`, a confidence-accepted `direct_reply` collapses the class to `conversation` (`decision/owner_turn.py:347–353`), and `infer_needs_tools` then returns `False` for conversation (`agent/tool_exposure.py:168–169`, `ingress_gate.py:100–103`). **No tools ship at all.** That is the dominant failure for Taco's pasted forms.

`is_explicit_action` (`owner_turn.py:175–181`) does not recognise an FFS/APK path + question, so the action floor never forces `managed_task` / `handoff`.

### B. Even when RE is selected, `prepare` never classifies a folder as FFS (D1)

The skill prompt steers the model to `action=prepare` (`agent/loop.py:2851` appends `skill.prompt_block`; `skill.py:14–28` text is "Start with action=prepare, target=…"). `store.prepare` → `classify` returns `"javascript"` or `"source"` for any directory (`store.py:147–150`) — never `"ffs"`. It then **copies and fingerprints the whole tree** (`store.py:175–214`) and hits hard caps `MAX_FILES = 50000` / `MAX_BYTES = 8 GiB` (`store.py:19–20`). RFC-0208's `prepare_ffs` / background ingest / `ffs_query` (`store.py:292+`, `ffs_ingest.py`, `runtime.py:202–268`) are never reached.

Under the limit, `prepare` returns `kind=source` plus the workflow line *"Use normal repository tools…"* (`runtime.py:187–194`, source workflow string at `:190`; `catalog` repeats it at `:275`; also restated in `tools/reverse_engineer.py:24`). The completion check then loops the model back to prepare (`agent/loop.py:913–924`: no saved report → "Use reverse_engineer to prepare…"). The model is told to use ordinary file tools on a multi-gigabyte dump.

### C. Alias steers RE keywords to the REA MCP tool (D1; refined by D2)

`CAPABILITY_ALIASES` maps `"rea"`, `"reverse-engineer"`, `"reverse_engineer"` → `"rea_investigate"` (`agent/tool_exposure.py:84–86`). The keyword hook at `:202–204` then appends `rea_investigate`. With `settings.rea.investigation_roots` empty (the default — `config.py:355–362`, `ReaSettings.investigation_roots`, `Field(default_factory=list)` at `:362`), every path is denied with `detail="roots_empty"` (`security/rea_paths.py:209–213`). The native `reverse_engineer` tool is never the one retrieved by those keywords.

`tool_retrieval.py:97` also lists `("rea", "reverse engineer", "reverse-engineer", "morluto")` under `rea_investigate`, so prompt retrieval can pull REA in preference to the native tool.

### D. Context flood is many capped results, not one uncapped read (D1 corrected by D2)

`ToolResult.text` already truncates each observation at **12 000** characters (`tools/base.py:24–31`). The flood is **many** of those results across the balanced policy's **28 steps** (`agent/planning.py:33`, `agent/loop.py:2623` / `:2981`). `filesystem.list` is uncapped (`tools/filesystem.py:516–524`); `filesystem.search` walks the **full tree before slicing** (`:527`: `list(path.rglob(pattern))[:400]`); `read` inlines up to 2 MB (`:529–533`). On the fallback path the 9B lists, searches and reads members; each call returns ≤12k, but 28 of them blow the context. Measured on the box: 37k chars mid-run with only `filesystem` exposed.

There is no hard per-turn context budget that refuses to inline a dump. Ingress spill (`agent/ingress_gate.py`, `HEURISTIC_BIG_CHARS = 12_000`) and segmented compression (`agent/segmented_input.py`, `agent/intake.py`) can shrink a *paste*, but they still leave the worker free to `filesystem.list` / `search` / `read` the on-disk dump afterwards.

### E. Taco's `allowed_directories` and REA roots are unverified (D1 item 4)

Defaults admit the home profile and, on Windows, every mounted drive (`default_allowed_directories`, `config.py:1040–1067`; `_windows_owner_drives` at `:675–693`). REA roots default to `[]`. Whether Taco's live values admit `D:\cases\…` or a UNC share is unknown; a missing root currently surfaces only as a tool error the model may narrate, not as an owner-visible diagnostic. Do **not** assume his values in this RFC — add a verification path.

### Discrepancies noted while verifying

- D1 said "filesystem.list is uncapped and read inlines up to 2 MB, which floods context". Verified for list/read; D2 is right that the flood is many 12k results over 28 steps, not a single uncapped observation. `search`'s full-tree walk (`filesystem.py:527`) is the expensive piece D1 did not name.
- D1's `rea_paths.py:209–213` citation is exact for `roots_empty`.
- D1's `store.py:147–150` / `:19–20` / `skill.py:14–28` citations are exact on `d85c9d4c`; the skill-block line moved from `loop.py:2777` to `:2851` when #648/#649 landed.
- D2's `base.py:24–31`, `filesystem.py:527`, `skill.py:6`, `tool_exposure.py:202–204` citations are exact on `d85c9d4c`. Moved by #648/#649/#657 and updated here: completion check `loop.py:899–905` → `:913–924`, `owner_turn.py:325–331` → `:347–353`, `runtime.py:187–190` → `:187–194`.

---

## Decision

Ship **one RFC, six implement slices**. Routing is **deterministic in the reflex / pre-model lane**, not "hope the 9B picks the tool". Large inputs never enter context. Answers are grounded in the ingested index with path citations. Progress and failures are owner-visible on the channels the portal actually consumes.

### Owner-visible channel (normative; do **not** use `publish_owner_text`)

Traced on `development` @ `d85c9d4c` and locked by RFC-0225 (#652 @ `60573c62`):

- **With a task** (every path+question turn creates one): publish on the **task stream** only.
  - Visible progress / failure: `BUS.publish(task_id, "<kind>", "<title>", "<detail>", stage=…)` — consumed by `frontend/src/chat/ownerChatView.ts:365` (`filterWorkEvents` keeps every kind except `assistant_delta` / `chat_tts` / `replace_previous_text`, `:40`, `:76–79`) and by Show work (`components/TaskActivity.tsx:296` renders `event.title`).
  - Spoken: `BUS.publish(task_id, "chat_tts", "<title>", "<text>", stage=…)` — consumed by `frontend/src/tts/useTaskSpeech.ts:64` / `:43`. Title must **not** be `"Speak reply"` (that joins the reply prefix at `:48–50`). Speech is skipped once the task status is `completed` (`:47`), so every spoken line is published **before** the task's terminal update.
- **Without a task** (settings / diagnostic probes): reuse RFC-0225's `engine_coexistence.owner_line(text, *, level, engine_id=None, task_id=None, title="Local engines")` (#652 @ `60573c62`, §Owner-line surfaces) with **`title="Reverse engineering"`**, shown and spoken by the owner-line surfaces #652 specifies (`frontend/src/hud/EngineNotices.tsx` and its classic-mode twin). That path publishes `engine_notice` on `OWNER_CHAT_CHANNEL` and, when a `task_id` is known, also mirrors onto the task stream. It does **not** call `publish_owner_text`.
  - **Dependency (not a gate):** `owner_line` is docs-only on #652 today; `backend/app/inference/engine_coexistence.py` does not exist on `development` @ `d85c9d4c`. The **with-task** path (`BUS.publish` on the task stream) works now and is what every path + question turn uses. Only S2's **no-task** `roots_empty` line needs `owner_line`, so that one call and its test (`test_roots_empty_without_task_uses_engine_owner_line`) land in S2 **after RFC-0225 S3's implement PR adds `engine_coexistence.owner_line`**. If S2 is ready first, it ships everything else and the no-task call follows as an S2 follow-up commit on the same branch once 0225-S3 is on `development`; S2 does not add its own owner channel or a placeholder.
- **Forbidden:** `persona/chat_delivery.py::publish_owner_text` / `enqueue_chat_tts` / polling `GET /api/owner/chat/tts/pending`. No client in `frontend/src`, `android/`, `extensions/` or the Manager listens (RFC-0225, #652 @ `60573c62`, "What the portal actually consumes").

### Deterministic path + RE-intent router (normative; two stages)

D2 round 3 showed that growing one regex either misses Taco's wording or routes coding questions on source trees to RE. Detection is therefore **two-stage**: (a) a cheap wording-plus-path prefilter, then (b) for weak matches only, a bounded, allow-list-first on-disk probe. Explicit owner wording needs no probe (CoS amendment A, from D2); the probe never touches a path outside the allowed folders (CoS amendment B, from D1).

**Stable helper (S2, `backend/app/agent/planning.py`):**

```python
@dataclass(frozen=True)
class ReIntent:
    target: str                            # the path as typed
    kind: Literal["ffs", "apk"]
    basis: Literal["explicit", "probed"]   # explicit wording, or a weak match the probe confirmed
    evidence: str                          # e.g. "wording:full ffs", "marker:data/data", "ext:.zip"

def re_intent_match(prompt: str, *, allowed: Sequence[str] | None = None) -> ReIntent | None: ...
```

`allowed=None` means `load_settings().allowed_directories`. It reads `latest_user_utterance(prompt)`. Results are memoised per `(utterance, tuple(allowed))` in an LRU of 64 entries with a 5 s TTL, so the baseline `route_request`, `classify_task`, `requests_agent_tools`, `is_explicit_action`, the S2 floor in `_apply_floors`, and RFC-0231-S1's precheck share **one** probe per turn. RFC-0231 calls exactly this name. The on-disk probe is a separate S2 function, `planning.probe_dump_target(target: str, allowed: Sequence[str] | None = None) -> DumpProbe` (`DumpProbe.verdict ∈ {"dump", "source", "absent", "outside", "timeout"}`, plus `DumpProbe.evidence`). S1's tests stand it in by that name.

**Rule 1: a path.** The latest owner utterance contains a local path in one of these forms (reuse / extend `_PATH_OR_URL` at `planning.py:269–271`):
- Windows drive: `D:\cases\x\ffs`, `D:/cases/x/ffs`
- UNC: `\\NAS\cases\x\ffs`, `//nas/cases/x/ffs`
- POSIX absolute: `/mnt/cases/x/ffs`

No path means no match.

**Stage (a): prefilter (no I/O; every pattern compiled with `re.IGNORECASE`).**

*Explicit* routes with no probe and no question required. Any one of these:
- a path ending in `.apk` / `.apks` / `.xapk` → `kind="apk"`;
- the RE verbs of `skill._INTENT` (`skill.py:6`, reused, not copied): `reverse engineer(ing)`, `decompile`, `disassemble`;
- `full FFS`, and `FFS of my/the/this/a/his/her …`: `\bfull\s+ffs\b`, `\bffs\s+of\s+(?:my|the|this|a|his|her)\b`;
- `full file system extraction / dump / image`: `\bfull\s+file[\s-]?system\s+(?:extraction|dump|image)\b`;
- `extraction of my phone` and close variants: `\b(?:full\s+|forensic\s+)?extraction\s+of\s+(?:my|the|this|a|his|her)\s+(?:phone|device|pixel|iphone|galaxy|android|handset|mobile)\b`, and `\b(?:my|the|this)\s+(?:phone|device|pixel|iphone)(?:'s)?\s+(?:full\s+)?(?:ffs|extraction)\b` ("my phone's extraction", "the Pixel FFS");
- `forensic extraction` / `forensic image`: `\bforensic\s+(?:extraction|image)\b`.

*Weak* matches go to stage (b). They also need a question or investigative ask: a `?`, or one of `what|which|where|when|how many|who|show|list|find|analyse|analyze|inspect|investigate|summarise|summarize`. Any one of these:
- **Path component** (path split on `\` and `/`, compared on the stem with the extension removed): exactly `ffs`, `fullfs`, `extraction`, `extract` or `dump`, or ending in `_ffs` / `-ffs` / `_dump` / `-dump` / `_extraction` / `-extraction` (so `p1_ffs.tar` is weak).
- **Forensic-only layout** in the path, component-aligned: `data/data`, `data/user/0`, `data/media/0`, `data/system_ce`, `data/system_de`, `storage/emulated/0`, `private/var/mobile`. D2 round 3 dropped `system/app`, `system/priv-app`, `system/framework`, `data/app` and `sdcard`, which are common in AOSP and app source trees.
- **Forensic image extension** on the path: `.img`, `.dd`, `.raw`, `.e01`, `.ex01`, `.ufd`, `.ufdr`, `.aff4`. Generic `.zip` / `.tar` / `.bin` need a component signal.
- **Wording:** `\b(?:android\s+file[\s-]system|(?:android|phone|device)\s+ffs|ffs\s+(?:root|dump|image|extraction|folder|tree)|(?:full|phone|device|android|forensic)\s+extraction|file[\s-]system\s+(?:image|extraction)|dump\s+root)\b`. "Android" needs a separated `file system` / `file-system`, so "Android filesystem API" never matches. `phone|device` + `image|dump` and `file system dump` are dropped. This covers Taco's "this is the root of an Android file system".
- **Bare "file system" + absolute path:** `\bfile[\s-]system\b[^\n]{0,40}?(?:[a-z]:[\\/]|\\\\|//|(?<!\w)/)`. The probe target is the first path in the utterance.

**Stage (b): on-disk probe (weak matches only).**
1. **Allow-list first.** `store.admit_allowed_target(target, allowed)` (#661 @ `4b81ac11`, `store.py:295`) runs before any `stat` of the target or of any marker. On `development` @ `a44da353` the same two gates exist under #660's names, `_ffs_admit_lexically` (`store.py:219–248`, lexical, no stat) then `_ffs_admit_real_parent` (`:251–289`). #661 folds them into `admit_allowed_target`. S2 calls `admit_allowed_target` if #661 has landed when S2 is cut. Otherwise it calls the two #660 functions in that order and switches to the #661 name in the same PR when #661 lands first; no third gate is written. `PermissionError` → verdict `outside`. **Zero** filesystem calls on the target, so routing is never an existence oracle (the leak #660 closed). A weak match on an outside path routes normally; explicit wording on an outside path still routes, and S3's ingest admission then returns the constant `FFS path not allowed` line.
2. **One `stat` of the target.** Missing → `absent`.
3. **File:** an image or container extension → `dump` (evidence `ext:<ext>`). The list is `.img .bin .dd .raw .e01 .E01 .ex01 .ufd .ufdr .aff4 .tar .tgz .tar.gz .zip .7z .ab .dar .dmg`; matching is case-insensitive. Any other file → `absent`.
4. **Directory, source veto first:** a `stat` of each of `.git`, `.repo`, `.hg`, `Android.bp`, `Android.mk`, `build/make`, `build/soong`, `settings.gradle`, `build.gradle`, `package.json`, `pyproject.toml`, `CMakeLists.txt`, `Cargo.toml`, `go.mod` under the target root. Any hit → `source`, routes normally. A dump marker never overrides it: an AOSP checkout has `.repo` / `build/make` / `Android.bp`.
5. **Directory, dump markers (any one is enough):** Android: `data/data/` (dir), `system/build.prop` (file), `data/user/0/`, `storage/emulated/0/`, `sdcard/Android/` (sdcard-only pulls). iOS (Architect's discretion, same any-one rule): `private/var/mobile/` (dir), `System/Library/CoreServices/SystemVersion.plist` (file). Hit → `dump` (evidence `marker:<rel>`). No hit → `absent`.

**Probe budget (it must fit the 50 ms decide, `OWNER_TURN_DEADLINE_MS`, `owner_turn.py:39`):**
- Only `os.stat` / `os.lstat` calls. No `listdir`, `open`, `read` or recursion.
- At most **22** stat calls per probe (1 target + 14 veto + 7 markers), plus the realpath of the parent inside the admit gate. The test's hard cap is **24**.
- It runs on a dedicated single-thread executor (`thread_name_prefix="re-probe"`). The caller waits at most **10 ms** (`future.result(timeout=0.010)`). On timeout, or while a previous probe still holds the executor (e.g. a hung SMB share), the verdict is `timeout` and a weak match routes normally. The abandoned stat finishes in the background, and its result is cached for the next turn.
- The probe runs once per turn: the memo above, filled by the first caller, which is the baseline `route_request` before `decide_owner_turn`.

**Kind.** `apk` when the matched path ends in `.apk` / `.apks` / `.xapk`, else `ffs`.

When `re_intent_match` returns non-`None`:

- `route_request` → `RequestRoute(MANAGED_TASK, "reverse engineering")`
- `classify_task` → `"reverse engineering"`
- `is_explicit_action` → `True` (forces `managed_task` / `handoff` even if Jev/Laya would have picked `direct_reply`; closes the `owner_turn.py:347–353` hole)
- `tool_names_for` always includes `reverse_engineer` (native)
- the S2 floor in `_apply_floors` (below) forces `managed_task` / `reverse engineering`

**Not matched:** ordinary source trees, bare "what's in this folder", weather, chat, and a path with a plain or coding question. These keep today's classifiers. Named negatives live in S1 and must stay green in every slice: `C:\code\etl what does the extraction step do?`, `C:\Users\taco\proj ffs why does the build fail?`, D2's round-3 set (Android filesystem API, phone image, device image, device dump handler, file system dump command, `aosp\system\framework`, `launcher\data\app`), an on-disk fake AOSP tree, and an outside path with markers that is never stat'd.

### Precedence vs RFC-0231 (normative; owned by S2)

> A turn whose prompt contains an absolute filesystem path together with RE intent (RFC-0232's narrowed dump/extraction detection) routes to reverse engineering and is never split by RFC-0231; a path with a plain or coding question routes normally.

"RE intent" means `planning.re_intent_match(prompt)` returns non-`None` (both stages above). This line is to appear verbatim in #665 (RFC-0231) as well. At #665 @ `57106ba5` it does not yet; see §Handoff order.

**Mechanism: a floor in `_apply_floors`, not an early return.** Every turn keeps `_decide_sync` unchanged: the RFC-0218 `persona_intent_precheck` (`owner_turn.py:448`) and exactly **one** `decide()` (`:453–460`), carrying the RFC-0206 every-turn arbitration and audit. S2 adds one floor inside `_apply_floors` (`owner_turn.py:296+`), right after the `task_class` block (`:347–356`) and before `covers` (`:358`): if `re_intent_match(user_message)` (memo hit) is non-`None` and there is no `literal`, then `route_kind = MANAGED_TASK`, `reply_shape = "handoff"`, `task_class = "reverse engineering"`. Because `_apply_floors` is also the deadline-fallback path (`:600`, `:623`), the floor holds there too. `persona_intent` is still attached afterwards (`:467–469`; `_with_deadline_persona` on the fallback paths). RFC-0231-S1's precheck in `_decide_sync` calls `planning.re_intent_match(user_message)` and appends no `large_prompt` / `large_prompt_split` riders when it matches. In `create_task`, the RFC-0231 large-prompt branch keys off `decision.large_prompt`, which stays `None`.

Named test: `test_path_plus_re_intent_routes_to_re_before_large_prompt_split` (S2, `tests/test_rfc0232_intent_and_alias.py`). It asserts all of the following:
- the route and class above;
- `getattr(decision, "large_prompt", None) is None` and no `large_prompt*` rider;
- `decision.persona_intent` is set;
- a spy on `owner_turn.decide` sees **exactly one** call with `decision_class == "request_routing"`.

The existing `test_one_decide_per_turn_carries_persona_question` (`tests/test_decision_persona_intent.py:70`) stays green unmodified, and S2 cites it.

### Pre-model / reflex dispatch (normative)

In `agent/loop.py::create_task` (`loop.py:479+`; and the managed-task entry of `_run`, `:2226+`), when `re_intent_match(prompt)` matches **and** `task_class == "reverse engineering"`.

**Position in `create_task`:** after RFC-0230-S3's `prewarm_worker("turn")` (started before the reflex decision; it warms the worker that will answer from the index, so it stays) and after `evaluate_request_route` (`:503–505`) returns; **before** RFC-0231's large-prompt branch (preload / spoken ack / split). A matching turn never reaches that branch, because its decision carries no `large_prompt` (§Precedence vs RFC-0231).

S3 owns the **FFS** branch below. The **APK** branch is owned by S5 (it calls S5's `apk_prepare` wrapper), as the next `loop.py` owner after S3 → S4; until S5 lands, an APK path + question still routes to RE (S2) with `reverse_engineer` exposed and the model uses the existing `prepare` for the `.apk`, behind #661's gate.


1. Publish task progress: title `"Starting reverse-engineering ingest"`, detail naming the target (redacted to the last two path components for the spoken `chat_tts` twin).
2. Call the existing service — **port, don't rewrite**:
   - `kind="ffs"` → `SERVICE.ingest(source=target, question=…, allowed=settings.allowed_directories, task_id=task.id, background=True)` (`runtime.py:202–252` → `store.prepare_ffs` → `ffs_ingest.FFSIngest`).
   - `kind="apk"` (S5) → `SERVICE.apk_prepare(...)` (S5's thin wrapper over `apk_sidecar.prepare_apk`), then the existing sidecar run. The admit gate is **#661**'s allow-list check in `prepare_apk` (`4b81ac11`).
3. Bind the investigation id on the task working set. Subsequent model turns see `reverse_engineer` with `action=ingest_status` / `ffs_query` / `evidence` / `report` already primed by an updated skill prompt (S3).
4. On `PermissionError` / `FileNotFoundError` / `ValueError` from prepare/ingest: publish a task event with a **clear failure line** (examples below) **and** a `chat_tts` twin; do not hand the dump to the 9B.

This runs **before** the first worker `MANAGER.chat` call. The 9B never sees the dump bytes.

### RE completion check (normative; S3 rewrites `loop.py:913–924`)

Today, for any task where `skill.requested(prompt)` is true or `working.task_class == "reverse engineering"`, `agent/loop.py:913–918` accepts completion only if a row for the task has status `reported` / `partial` / `closed` **and** a saved `report.json`. Otherwise `:918–924` injects *"Reverse engineering requires a saved investigation report. Use reverse_engineer to prepare the supplied target, …"* and returns `False`. For an FFS task that is wrong in two ways:

- An FFS row goes `prepared` → `ingesting` (`ffs_ingest.py:622`) and becomes `completed` only at `:790` (`interrupted` at `:827`). The check tells the model to **prepare** again, which is the prepare loop D1 traced.
- Simply accepting completion while an ingest runs would kill it: a terminal `_update` calls `investigations.release_task(task_id, …)` (`loop.py:800–802`), and `release_task` calls `ffs_ingest.cancel` and cancels the active ingest task for every row of the task (`runtime.py:488–502`).

**S3 replaces `:913–924`** with one helper, `AgentRuntime._re_completion_gate(task_id, working) -> str | None | Complete | Failed`. The return values mean:
- `None`: complete with the model's content.
- `Complete(line)`: complete with that line as the result.
- `Failed(line)`: the existing fail path, `self._fail_task(task_id, line, working, metrics)`. The line and its `chat_tts` twin are published first, because speech is skipped once the task is terminal.
- a string: the internal message to append before `return False`.

`Complete` and `Failed` are frozen one-field dataclasses in `agent/loop.py`. Only S3 touches this block.

**Row states.** For each row of `store.list_rows(task_id)`, sorted by `created_at` then `id` (deterministic), the gate assigns exactly one state:

| State | Condition (checked in this order) |
| --- | --- |
| `REPORTED` | status `reported` / `partial` / `closed` **and** `report.json` exists (today's rule) |
| `RUNNING` | `kind == "ffs"` and `ffs_ingest.running(id)` (`ffs_ingest.py:496`) is true. This covers both ingest modes: `running()` reads `_RUNNING`, which `FFSIngest.run_sync` fills for foreground and background ingests alike |
| `PREPARED` | `kind == "ffs"`, status `prepared`, not running (what S3's own `store.prepare` → `prepare_ffs` delegation creates) |
| `INDEXED` | `kind == "ffs"`, status `completed`, no report |
| `INTERRUPTED` | `kind == "ffs"` and either status `interrupted`, **or** status `ingesting` with no live ingest: `ffs_ingest.running(id)` is false **and** `SERVICE.active.get(id)` is `None` or done. A backend kill or restart mid-ingest leaves such a stale row: only `ffs_ingest.py:622` writes `ingesting`, only an in-process stop rewrites it (`:827`), and nothing on `development` clears a stale one. Resume is safe: `prepare_ffs` re-admits any non-`completed` row as `prepared` (`store.py:351–353`), and the NDJSON checkpoint carries the progress |
| `CANCELLED` | `kind == "ffs"`, status `cancelled`, no report |
| `CLOSED` | `kind == "ffs"`, status `closed`, no report (`closed` is in `TERMINAL_STATUSES`, `store.py:22`) |
| `OTHER` | any non-FFS row without a report (source / native / browser / APK) |

**Foreground vs background ingest.**
- **Background** (`SERVICE.ingest(..., background=True)`, the S3 dispatch and the gate itself): the handle is `SERVICE.active.get(id)`, always read with **`.get()`**, never `[id]`. The gate waits with `asyncio.wait({handle}, timeout=15)`.
- **Foreground** (`POST /api/investigations/ffs`, or `reverse_engineer action=ingest` with `background=False`): `SERVICE.active.get(id)` is `None` while `running(id)` is true, because the ingest is owned by another caller (an API request or another task's tool call). The gate never cancels it and never awaits a handle; it polls `ffs_ingest.running(id)` with `await asyncio.sleep(15)` between checks, then re-reads the persisted row (`store.load(id)`) for the resulting status.
- In both modes each 15 s slice calls `self._update(task_id, status="running", stage="understand", current_action="Indexing FFS …")` and publishes the `Indexing FFS` progress event (§Progress during ingest), with no model call and no step spent.

**Combining several rows (deterministic):**
1. Every `PREPARED` row is started by the gate itself, with no model step: `SERVICE.ingest(source=row["target"], question=row["question"], allowed=settings.allowed_directories, task_id=task_id, investigation_id=row["id"], background=True)`. It is then `RUNNING`. If admission raises `PermissionError` / `FileNotFoundError` / `ValueError`, the gate publishes the matching failure line (§Failure lines, task event + `chat_tts`) and returns `Failed(<that line>)`.
2. If **any** row is `RUNNING` → wait (one slice), then re-evaluate from step 1. A report on another row does not end the wait, because completing would cancel the running ingest through `release_task`.
3. Otherwise, if any row is `REPORTED` → **complete** (today's rule).
4. Otherwise, if any row is `INTERRUPTED` → publish one `FFS ingest interrupted` line per interrupted row (task event + `chat_tts`), then the message *"Call reverse_engineer action=ingest with investigation_id=<id> to resume from the checkpoint. Do not call prepare."* (one sentence per row, in row order).
5. Otherwise, if any row is `INDEXED` → the message *"The FFS index for <id> is complete (<N> files). Answer from reverse_engineer action=ffs_summary / ffs_query / ffs_read, record evidence, then report findings that cite index paths. Do not call prepare and do not use filesystem tools on the dump."* (one per row, in row order).
6. Otherwise, if any row is `OTHER`, or there are no rows → today's message, byte-identical. Live behaviour for non-dump targets is preserved.
7. Otherwise every remaining row is `CANCELLED` or `CLOSED` → publish the `FFS ingest cancelled` or `FFS investigation closed` line per row (task event + `chat_tts`, before the terminal update, because speech is skipped once the task is `completed`) and return `Complete(<those lines joined>)`. No loop.

Precedence, in short: prepared-admit failure (`Failed`) > running > reported > interrupted (incl. stale `ingesting`) > indexed > other / none > cancelled / closed. The same `max_steps` budget bounds steps 4–6; waiting in step 2 spends no steps. Owner cancel of the task still ends the wait through the existing cancel path (`release_task(..., cancelled=True)`).

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
| `ingest` / `ingest_status` / `ffs_query` | unchanged (RFC-0208). **`ffs_query` default `limit` becomes 50** (hard max stays `MAX_QUERY_LIMIT = 500` in `ffs_ingest.py:70`); pages of 25–50 are the documented norm. Response stays the compact index line (`path`, `bytes`, `sha256`, `mtime`, `magic_hex`, `type`) — never file bodies. When a requested page would exceed the 12 000-char observation cap (`tools/base.py:24–31`), `reverse_engineer` returns only whole NDJSON rows that fit, plus `truncated: true` and `next_offset`, so `ToolResult.text` never cuts a row mid-JSON. |
| `ffs_summary` **(new)** | Arguments: `investigation_id`, optional `path_contains`. Returns per-package (Android: under `data/data/<pkg>/`, `data/app/`, `system/…`) roll-ups: package name, file count, total bytes, top suffixes, whether a `databases/` or `shared_prefs/` tree exists. Built from the NDJSON index only — no member I/O beyond what ingest already did. Cap: 100 packages per call, with `offset`. |
| `ffs_read` **(new)** | Arguments: `investigation_id`, `path` (index-relative), `offset` (bytes, default 0), `limit` (bytes, default 4096, **max 16 KiB**). Serves a bounded slice of one indexed member by re-opening the dump read-only (same admit rules as ingest). Refuses paths not in the index. Returns `{path, offset, limit, bytes, sha256, text_or_hex, truncated}`. |
| `apk_prepare` **(new action name on the same tool)** | Thin wrapper over `apk_sidecar.prepare_apk` (RFC-0207). Sequenced **after #661** (D1's allow-list gate for `store.prepare` / `prepare_apk`, head `4b81ac11`), which is the admit gate for APKs (#660, landed `90a0010`, covers only `prepare_ffs`). Same admit rules. |

### Skill prompt (S3)

Replace the prepare-first block (`skill.py:14–28` and the FFS branch of `guide` at `:44–59`; #657 extended that branch with the `.tab` container census, which S3 keeps verbatim) so the model is told, in this order:

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
| Ingest still running, owner asks again | `FFS ingest in progress` | `Still indexing <N> files so far. I'll answer from the index as soon as it finishes; you can ask me to cancel.` (The promise is kept by the completion check, step 2: the task waits for the ingest and then answers.) |
| Ingest interrupted | `FFS ingest interrupted` | `Indexing stopped at <path> (<reason>). Say "resume the ingest" and I'll continue from the checkpoint.` |
| Owner cancelled the ingest, no report | `FFS ingest cancelled` | `You stopped indexing <last two components> at <N> files. Ask again to start a fresh ingest.` |
| Owner closed the FFS investigation, no report | `FFS investigation closed` | `You closed the investigation of <last two components> before a report was saved. Ask again to start a new one.` |
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
| `backend/app/reverse_engineering/store.py` | **#660** (allow-list-first `prepare_ffs`, landed `90a0010`) → **#661** (`4b81ac11`, D1's stacked allow-list gate for `store.prepare` / `prepare_apk`) → **this RFC S3** (dump-shaped classifier inside `prepare` that delegates to `prepare_ffs`) → S5 |
| `backend/app/reverse_engineering/{runtime,skill,ffs_ingest}.py` | **#657** (tab container, landed `d85c9d4c`) → **this RFC S3 / S4** (skill text, `ffs_summary` / `ffs_read`, `ffs_query` default limit) → **S5** (`runtime.py` `apk_prepare` wrapper) |
| `backend/app/decision/owner_turn.py` | #649 (landed `ee786dc1`) → **RFC-0218-S3b** (`basic_qa` stay guard; not landed: `tests/test_rfc0218_s3b_lock_and_tasks_switch.py` is absent on `development` @ `a44da353`) → **RFC-0230-S5** (#666; reflex executor) → **this RFC S2** (RE floor in `_apply_floors` after the `task_class` block + action floor) → **RFC-0231-S1** (#665; large-prompt precheck + riders, which call `planning.re_intent_match` and skip when it matches) |
| `backend/app/agent/loop.py` | #649 (landed `ee786dc1`) → **RFC-0218-S3b** (`create_task` / `_run` persona switch; not landed) → **RFC-0230-S0 → S2 → S3** (#666; latency marks, first-sentence wiring, `prewarm_worker` in `create_task`) → **this RFC S3** (FFS pre-model dispatch in `create_task` + RE completion check `:913–924`) → **S4** (24k per-turn budget hunk) → **S5** (APK branch of the dispatch) → **RFC-0231-S4 → S5** (#665; `create_task` large-prompt branch and `pipeline_section`) |

Order on `loop.py` / `owner_turn.py` follows the CoS ruling (2026-10-20): 0218-S3b (already queued after #649), then RFC-0230, then RFC-0232, then RFC-0231. 0232 goes before 0231 because the RE bug is one of Taco's top asks. Cross-spec alignment still open on the current heads:
- **#665 @ `57106ba5`:** its `loop.py` row omits 0232-S5. Its `owner_turn.py` row omits 0218-S3b. It does not yet carry the precedence line or the two CoS negatives (`C:\code\etl …`, `C:\Users\taco\proj ffs …`).
- **#666 @ `99aef631`:** it still lists RFC-0231 ahead of RFC-0232 on both files (its L239, L241) and names only 0232-S2 on `loop.py`.

Both must match this table before #664 lands.
| `backend/app/agent/planning.py`, `agent/tool_exposure.py`, `agent/tool_retrieval.py` | **this RFC S2** (sole owner for the new helper + alias fix) |
| `backend/app/tools/filesystem.py` | **this RFC S4** (list/search/read caps + early-stop search) |
| `backend/app/tools/reverse_engineer.py` | **this RFC S3** then S5 (`apk_prepare` action) |
| `.github/workflows/pr-tests.yml` | Architect owns the workflow file; S1 names the step, S6 may append a focused line only if the full-suite step is too slow — prefer relying on the existing "Run full backend suite" step. |

On a conflict, merge `development` into the slice branch (merge commit). No rebase, no force-push, no branch deletion.

---

### S1 — Repro xfail (this PR)

**Model:** Composer 2.5 · **fast off**  
**Owns:** `tests/test_rfc0232_ffs_path_routing.py` (new), `docs/rfcs/0232-ffs-path-routes-to-re-tool.md`, `docs/rfcs/README.md` (this RFC's row only), `/workspace/rfc/RFC-0232.md` mirror.

**Tests (concrete; all `pytest.mark.xfail(strict=True)` until the named fix slice removes the marker).** Path-form and wording cases whose paths cannot exist on the CI runner stand the S2 probe in by name (`planning.probe_dump_target` → verdict `dump`, `raising=False`). Explicit cases replace it with a function that raises, proving no probe runs. On-disk cases use `jarvis_env`'s `tmp_path`, which is the allowed folder, and the real probe.

| Test | Stage | Marker removed by |
| --- | --- | --- |
| `test_path_plus_question_routes_to_reverse_engineering[…]`: the six Taco forms (Windows `D:\cases\x\ffs …`, "Android FFS root … full extraction …", UNC `\\NAS\…`, `//nas/…`, POSIX `/mnt/…`, `Analyze D:\cases\x\app.apk …`) | weak (component) / explicit (`.apk`) | S2 |
| `test_dump_wordings_route_to_reverse_engineering[ffs]`, `[extraction]`, `[dump]` | weak (component) | S2 |
| `test_dump_wordings_route_to_reverse_engineering[full-file-system-dump]` | explicit | S2 |
| `test_dump_wordings_route_to_reverse_engineering[android-file-system]`, `[file-system-abs-path]` (Taco's wording, D2 2026-10-20) | weak (wording / bare file system) | S2 |
| `test_explicit_wording_routes_without_probe[full-ffs]`: `D:\cases\x\p1 is a full FFS of my Pixel, which apps?` (D2 round 3) | explicit, probe forbidden | S2 |
| `test_explicit_wording_routes_without_probe[full-file-system-extraction]`, `[extraction-of-my-phone]` | explicit, probe forbidden | S2 |
| `test_on_disk_dump_routes_after_probe[android-full]` (`data/data` + `system/build.prop`) | weak → probe `dump` | S2 |
| `test_on_disk_dump_routes_after_probe[data-only]` (partial dump, `data/data` only) | weak → probe `dump` | S2 |
| `test_on_disk_dump_routes_after_probe[sdcard-only]` (partial dump, `sdcard/Android` only) | weak → probe `dump` | S2 |
| `test_on_disk_dump_routes_after_probe[ffs-tar]`, `[ffs-zip]` (`p1_ffs.tar` / `p1_ffs.zip` archives) | weak (component) → probe `ext:` | S2 |
| `test_ffs_path_plus_question_calls_ingest_without_overflow` | weak → probe `dump` → dispatch | S3 (+ S4 caps) |

That is 21 xfail cases.

**Live tests (not xfail; they pass on `development` today, and every slice must keep them green, S2 most of all because it adds the detector):**

| Test | Guards |
| --- | --- |
| `test_path_with_plain_or_coding_question_does_not_route_to_re[etl-extraction-step]` (`C:\code\etl what does the extraction step do?`) and `[ffs-interjection]` (`C:\Users\taco\proj ffs why does the build fail?`) | CoS negatives |
| `test_path_with_plain_or_coding_question_does_not_route_to_re[android-filesystem-api]`, `[phone-image]`, `[device-image]`, `[device-dump-handler]`, `[file-system-dump-command]`, `[aosp-system-framework]`, `[launcher-data-app]` | D2 round-3 negatives |
| `test_reverse_engineer_wording_still_routes` (`reverse engineer D:\cases\x\ffs`) | today's only working wording stays explicit |
| `test_aosp_source_tree_routes_normally`: fake AOSP tree (`.repo/manifests`, `build/make`, `Android.bp`, plus `data/data` and `system/build.prop`) with weak wording | source veto beats dump markers |
| `test_outside_path_with_markers_is_never_probed`: a fake dump outside the allowed folder; spies on `os.stat` / `Path.exists` record **no** call under that path, and the route is not RE | allow-list first (#660 / #661); no existence oracle |

That is 12 live tests.

**CI step:** existing `.github/workflows/pr-tests.yml:94–95` → "Run full backend suite" (`python -m pytest -q -rs`), which collects `tests/test_rfc0232_ffs_path_routing.py`. No workflow edit in S1. Architect owns `pr-tests.yml`.

**Acceptance:** all 21 xfail cases above xfail strictly on `development`; the 12 live tests pass; CI green.

**README row:** #652 (open) rewrites the last README paragraph and appends the 2026-10-17 batch paragraph with "Next free after **0229** is **0230**". So that a later merge resolves without a conflict, S1 leaves that paragraph untouched and adds one separate paragraph before the "Memory recall follow-up" paragraph (so an unchanged paragraph sits between the two hunks; `git merge-tree` against #652's head is clean) in #652's batch format (bold date label, linked number, status, PR number), which says 0230/0231 are parallel and 0233 is reserved. Once #652 lands, the Architect merges `development` into this branch (merge commit) or, if this PR landed first, makes a docs commit that moves that sentence into #652's single next-free line ("Next free after **0233** is **0234**" once 0230/0231/0233 exist) and drops the separate paragraph, so the README keeps one next-free line.

---

### S2 — Deterministic intent + alias + REA roots visibility

**Model:** Grok 4.6 · **fast off**  
**Owns:** `backend/app/agent/planning.py` (`ReIntent`, `re_intent_match`, `probe_dump_target` + its `re-probe` executor and memo; wire into `route_request` / `classify_task` / `requests_agent_tools` / `is_explicit_action` via a thin re-export or direct call from `owner_turn.py`), `backend/app/decision/owner_turn.py` (RE floor in `_apply_floors` after the `task_class` block per §Precedence vs RFC-0231, plus the action floor; `_decide_sync` untouched; after RFC-0218-S3b and RFC-0230-S5, before RFC-0231-S1), `backend/app/agent/tool_exposure.py` (alias → `reverse_engineer`; conditional `rea_investigate`), `backend/app/agent/tool_retrieval.py` (drop `rea_investigate` terms), `backend/app/tools/rea_investigate.py` (surface `roots_empty` through the owner channel when hit), `tests/test_rfc0232_ffs_path_routing.py` (remove the xfail markers from `test_path_plus_question_routes_to_reverse_engineering`, `test_dump_wordings_route_to_reverse_engineering`, `test_explicit_wording_routes_without_probe` and `test_on_disk_dump_routes_after_probe`, all 20 cases; the 12 live tests stay unmodified and green), `tests/test_rfc0232_intent_and_alias.py` (new).

**Named tests:**

- `test_dump_wordings_route_across_path_forms`: S1's six dump wordings × Windows / UNC / POSIX, probe stood in as `dump`; each routes.
- `test_bare_filesystem_word_does_not_route`: `D:\src\app what is the filesystem layout?` (one word) and `file system questions in general?` (no path) keep today's route.
- `test_narrowed_rule_does_not_route_plain_paths`: stage (a) returns no match for `C:\code\etl what does the extraction step do?`, `C:\Users\taco\proj ffs why does the build fail?`, `C:\code\data\x what is in data?`, `C:\code\app what does the dump() function do?` and D2's round-3 set (`D:\src\app how does the Android filesystem API work here?`, `C:\code\shop which phone image is shown on the product page?`, `C:\code\cam what does the device image upload do?`, `C:\code\kernel where is the device dump handler?`, `C:\code\aosp\system\framework what does this module do?`, `C:\code\launcher\data\app which class handles install?`). `C:\code\fs what does the file system dump command in /usr/bin do?` is a weak match whose probe returns `absent` / `source`, so it routes normally. `re_intent_match` is `None` for all of them, and `reverse_engineer` is not forced.
- `test_probe_is_allow_list_first` (CoS amendment B): with `store.admit_allowed_target` (or #660's pair) spied, it runs before the first `os.stat`. For an outside target it raises, and the stat spy records zero calls.
- `test_probe_markers_any_one_is_enough`: tmp trees with only `data/data`, only `system/build.prop`, only `storage/emulated/0`, only `sdcard/Android`, only `private/var/mobile`, and only `System/Library/CoreServices/SystemVersion.plist` each give verdict `dump` with the matching `evidence`.
- `test_probe_container_extensions`: tmp files `x.img`, `x.bin`, `x.dd`, `x.E01`, `x.ufd`, `x.tar`, `x.tar.gz`, `x.zip`, `x.raw` give `dump`; `x.txt` gives `absent`.
- `test_probe_source_tree_veto`: a tmp tree with `data/data` plus any one of `.git`, `.repo`, `Android.bp`, `build/make` gives `source`.
- `test_probe_budget_stat_only_and_timeout`: a stat spy counts ≤ 24 calls and sees no `listdir` / `open`. A stat patched to block makes `re_intent_match` return within 15 ms with verdict `timeout`, and the weak match routes normally. A second call while the first still blocks also returns `timeout` without queueing.
- `test_probe_runs_once_per_turn`: `route_request` + `decide_owner_turn` + `classify_task` on one utterance run the probe once (memo).
- `test_extraction_layout_paths_route`: `D:\cases\x\phone\data\data which apps are installed?` and `/mnt/x/storage/emulated/0 what photos are there?` are weak (layout) matches; with the probe stood in as `dump`, they route.
- `test_path_plus_re_intent_routes_to_re_before_large_prompt_split`: a 40 KB prompt (`D:\cases\x\p1 is a full FFS of my Pixel, which accounts are on it?` plus a pasted 40 KB listing) gives `decide_owner_turn` → `managed_task` / `reverse engineering`, `getattr(decision, "large_prompt", None) is None`, no `large_prompt*` rider, `decision.persona_intent` set, and a spy on `owner_turn.decide` that sees exactly one call. The same 40 KB prompt with `C:\code\etl what does the extraction step do?` is not routed to RE. `test_one_decide_per_turn_carries_persona_question` (`tests/test_decision_persona_intent.py:70`) stays green unmodified.
- `test_direct_reply_cannot_bypass_ffs_path` — baseline would be `direct_reply`; after the floor, route is `managed_task` / `reverse engineering` and `reverse_engineer` is exposed.
- `test_alias_maps_to_native_reverse_engineer` — `normalize_capabilities(["reverse_engineer","reverse-engineer","rea"])` → `["reverse_engineer"]`.
- `test_rea_investigate_only_when_roots_configured` — empty roots → not in `tool_names_for`; configured intersecting roots → present alongside `reverse_engineer`.
- `test_roots_empty_reaches_task_stream` — call `rea_investigate` with empty roots under a live task → one task event whose detail contains `Settings → Integrations → Reverse Engineering` **and** one `chat_tts` event; **zero** calls to `publish_owner_text`.
- `test_roots_empty_without_task_uses_engine_owner_line` — monkeypatch `engine_coexistence.owner_line`; assert it is called once with `level="error"` and `title="Reverse engineering"` (RFC-0225, #652 @ `60573c62`). Lands once RFC-0225 S3 adds `owner_line` (see §Owner-visible channel, Dependency).

**CI step:** `.github/workflows/pr-tests.yml:94–95` "Run full backend suite" collects `tests/test_rfc0232_ffs_path_routing.py` (including the 12 live tests), `tests/test_rfc0232_intent_and_alias.py` and `tests/test_decision_persona_intent.py`; the slice is green only when every named test above passes there.

**Acceptance:** the 20 S1 routing xfails (path forms, dump wordings, explicit wording, on-disk dumps) are gone and pass; the 12 live tests and `test_one_decide_per_turn_carries_persona_question` stay green; every probe is allow-list first, stat-only, ≤ 24 stats and ≤ 10 ms; no soft-fail on empty roots.

---

### S3 — Pre-model ingest dispatch + skill + prepare classifier

**Model:** Grok 4.6 · **fast off**  
**Owns:** `backend/app/agent/loop.py` (FFS branch of the pre-model dispatch in `create_task` / `_run` start, after RFC-0230-S3's `prewarm_worker`, and the RE completion check rewrite at `:913–924` per §RE completion check; next `loop.py` owner after RFC-0230-S3), `backend/app/reverse_engineering/skill.py`, `backend/app/reverse_engineering/store.py` (dump-shaped branch at the top of `prepare` that delegates to `prepare_ffs` when the classifier says FFS — **after #660 and #661**; cite their hunks), `backend/app/reverse_engineering/runtime.py` (workflow string for FFS no longer says "use normal repository tools"), `backend/app/tools/reverse_engineer.py` (document ingest-first), `tests/test_rfc0232_ffs_path_routing.py` (remove the overflow xfail), `tests/test_rfc0232_ingest_dispatch.py` (new).

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
- `test_completion_starts_ingest_for_prepared_row` (D2 round 2 a) — a `prepared` FFS row with no ingest running → the gate calls `SERVICE.ingest(..., investigation_id=<id>, background=True)` once with no provider call in between, then waits; the row reaches `completed`; no message contains `prepare`.
- `test_completion_closed_row_completes_with_line` (D2 round 2 b) — an owner-`closed` FFS row with no report → the task completes with the `FFS investigation closed` detail as its result, the `chat_tts` twin is published before the `completed` update, and there is no loop.
- `test_completion_waits_on_foreground_ingest_without_keyerror` (D2 round 2 c) — a foreground ingest (`SERVICE.ingest(..., background=False)` started from a separate coroutine, so `SERVICE.active.get(id)` is `None` while `ffs_ingest.running(id)` is true) → the gate polls without `KeyError`, does not cancel the foreground ingest, and resolves from the persisted row once it finishes (`asyncio.sleep` patched to make the slices instant).
- `test_completion_resumes_stale_ingesting_row_after_restart` (D2 round 3 1a): a row persisted as `ingesting` with `ffs_ingest.running(id)` false and no `SERVICE.active` entry (simulated restart) is classed `INTERRUPTED`. One `FFS ingest interrupted` task event + `chat_tts` is published, and the message names `action=ingest` with the id, never `prepare`. After the scripted resume the row reaches `completed`.
- `test_completion_prepared_row_admit_failure_fails_task` (D2 round 3 1b): a `prepared` row whose target was removed, or moved outside `allowed_directories`, makes the gate's `SERVICE.ingest` raise. The task ends `failed` through `_fail_task` with the exact `FFS path not found` / `FFS path not allowed` line, and the `chat_tts` twin is published before the terminal update.
- `test_completion_combines_rows_deterministically` (D2 round 2 d) — one task with rows {running FFS, reported source} → waits; then {interrupted FFS, indexed FFS} → the resume message only; then {indexed FFS, other source} → the index message; then {cancelled FFS, closed FFS} → completes with both lines in row order. Each combination gives the same result on repeated runs.

**CI step:** `.github/workflows/pr-tests.yml:94–95` "Run full backend suite" collects `tests/test_rfc0232_ffs_path_routing.py` and `tests/test_rfc0232_ingest_dispatch.py` (which holds `test_completion_accepts_ffs_ingest_without_prepare_loop` and the other completion tests); the slice is green only when every named test above passes there.

**Acceptance:** S1 overflow xfail removed and green; prepare no longer copies FFS trees; the RE completion check never sends an FFS task back to `prepare`, never ends a task while any of its ingests runs (foreground or background), and resolves several rows by the stated precedence.

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
**Owns:** `backend/app/tools/reverse_engineer.py` (`apk_prepare` action), `backend/app/reverse_engineering/runtime.py` (thin wrap of `apk_sidecar.prepare_apk`), `backend/app/agent/loop.py` (APK branch of the pre-model dispatch in `create_task`, next to S3's FFS branch; `loop.py` owner after S3 → S4), `backend/app/api/investigations.py` (`GET /api/investigations/diagnostics`), Settings Integrations status line (add-alongside one `<p>` in the existing RE panel — file owned by whoever last touched it; cite), `tests/test_rfc0232_apk_prepare.py` (new), `tests/test_rfc0232_diagnostics.py` (new).

**Sequencing:** land **after #661** (`4b81ac11`, D1's allow-list gate for `store.prepare` / `prepare_apk`; this is the APK admit gate) and after S3 / S4 on `loop.py`. #660 (landed `90a0010`) covers only `prepare_ffs`. Merge `development` in (no rebase); port #661's admit helpers by citation. Do not reimplement admit.

**Named tests:**

- `test_apk_prepare_action_admits_under_allowlist` — in-list `.apk` → investigation row; out-of-list → the same constant `PermissionError` message #661 gives for `prepare_apk`.
- `test_apk_path_plus_question_routes_and_dispatches` — `Analyze D:\cases\x\app.apk: what servers…` → router `apk` + `apk_prepare` called in the `loop.py` APK branch S5 owns, before the first provider call (mock the sidecar).
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

1. Every xfail prompt in the S1 table (Taco forms and the six dump wordings) routes to `managed_task` / `reverse engineering` and exposes `reverse_engineer`, including the forms that today return `direct_reply`.
2. A path + question on an FFS root or extraction calls `SERVICE.ingest` (or `apk_prepare` for `.apk`) before the first worker model call.
3. No provider call in the overflow repro exceeds 24 000 characters; `filesystem.search` does not walk a whole dump before slicing.
4. Answers cite index paths; Show work shows ingest progress titles; failures use the exact lines above on the task stream (+ `chat_tts`), never `publish_owner_text`.
5. Empty REA roots produce the actionable Settings sentence on the task stream or via `engine_coexistence.owner_line` + the owner-line surfaces (#652 @ `60573c62`).
6. #660 (`prepare_ffs`) and #661 (`store.prepare` / `prepare_apk`) allow-list behaviour is preserved (constant outside-allow message; no existence leak).
7. An FFS task is never sent back to `prepare` by the completion check, and never completes while its ingest runs (`test_completion_accepts_ffs_ingest_without_prepare_loop`, `test_completion_waits_on_foreground_ingest_without_keyerror`).
8. A path with a plain or coding question does not route to RE (`test_path_with_plain_or_coding_question_does_not_route_to_re`, `test_aosp_source_tree_routes_normally`). A path with RE intent is never split by RFC-0231 and still gets its persona check and one `decide()` (`test_path_plus_re_intent_routes_to_re_before_large_prompt_split`). The probe never stats an outside path (`test_outside_path_with_markers_is_never_probed`).
9. No stubs, soft-fails, or orphaned events.

---

## Live-UI add-alongside

| Live behaviour | Preserved? | Added alongside |
| --- | --- | --- |
| Show work / ops rail / Phone task events | Yes | New progress / failure titles only |
| `useTaskSpeech` on `chat_tts` | Yes | Start / failure spoken lines (title ≠ `"Speak reply"`) |
| Settings → Integrations → Reverse Engineering panel | Yes | One status line for empty REA roots |
| RFC-0225 owner-line surfaces (EngineNotices + classic twin) | Yes (land with #652) | Reused for the no-task `roots_empty` line, `title="Reverse engineering"` |
| RE completion check for non-dump targets (`loop.py:913–924`) | Yes, byte-identical message | FFS-only states: start a prepared ingest, wait (foreground or background), answer from index, resume, cancelled / closed line |
| Persona switch / HUD morph (RFC-0218) | Untouched | — |
