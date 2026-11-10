# RFC-0247: ANZU Model Manager

**Status:** accepted  
**Author:** Codex, owner request 2026-11-10  
**Date:** 2026-11-10

## Problem

The owner runs model servers beside ANZU. RFC-0210 can select some already-loaded
models, but the independent Manager cannot manage them, distinguish downloaded
models, or review memory before starting a model.

## Decision

Extend `RunningModels`, its owner-choice API and the existing external provider.
Keep the RFC-0210 per-model `servers` projection compatible and add per-server
`inventory`, loaded/available metadata, identity and ownership. Discover bounded
known ports and local listeners using GET metadata only. Recognize Ollama, LM
Studio, llama.cpp, vLLM, SGLang, koboldcpp, textgen/oobabooga and Colibri; unknown
listeners must expose OpenAI model metadata. Exclude editor/agent processes, internal
Ollama workers, and ANZU's managed worker/front seat. OS inspection and HTTP/TLS
initialization run off the health/chat event loop, with deadlines and a port cap.

Explicit Start shares RFC-0210's choice lock and `MANAGER._request_lease`. It
does not select ANZU's backend: Use attaches through the existing provider and
conversation-rebind path. Stop revalidates discovery, unloads a native model, or
terminates only a verified llama-server listener. Escalation to kill requires
another PID/name/create-time check after the graceful timeout. Other server kinds
are selectable but not process-termination targets. Owner choice/confirmation is
the existing approval mechanism. Actions use the Manager's structured redacted
control log, including failures.

Launch data comes from `model_launch.py` builtins, native downloaded inventories,
existing configured GGUF runtime profiles, and optional owner-local
`data/model-launch-profiles.json`. It is launch configuration, not a parallel
provider/placement/model registry. Local records require `id`, `label`, `backend`,
`model`, `port`, `context_size`, `context_ceiling`; llama.cpp additionally requires
an existing `binary` and GGUF `model` path. Optional fields: `weight_mib`,
`kv_mib_per_1k_f16`, `n_cpu_moe`, `notes`. HTTP bodies choose a profile ID and
bounded options, never executable/argv data. LM Studio CLI uses default port 1234.

Builtins preserve the owner's VRPC research: `qwen3.8:27b-q4_K_M` at 32K for
quality/overnight coding (partly CPU, approximately 8 tok/s); `anzu-coder-27b`
Q3_K_S at 48K for interactive coding (approximately 45 tok/s on 16 GB; 64K spills
to RAM, approximately 10 tok/s). These are supplied research notes, not benchmarks
validated here. No 9B default, 27B coder, CPU front-seat placement or saved model
choice changes. Qwen3.6-35B-A3B CPU expert offload is offered only when a binary
and weights are configured/found.

Start previews weights + KV + workspace against current NVIDIA free memory and
lists compute processes. Unknown/over-budget estimates require a separate explicit
confirmation. Full-weight estimates are conservative for CPU offload. WDDM may
hide process memory; GPU totals include graphics allocations. No competing model
is evicted by ANZU. Port occupancy blocks duplicate launches even with unhealthy
HTTP; multiple `ollama serve` processes produce a diagnostic.

Ollama cache/flash choices are server-level. An existing server must match explicit
options, otherwise Start refuses with owner-restart instructions. Server-default
choices reuse it unchanged. New ANZU-started Ollama receives only the two allowed
environment settings. Loading uses an empty prompt, explicit context and idle
keep-alive. No implicit pull or owner-server restart.

### Ollama tray app and the duplicate-server loop

Observed on the owner's Windows PC: ANZU's boot path started a bare `ollama serve`;
minutes later the tray app (`Startup\Ollama.lnk` -> `ollama app.exe`) started its
own server, found 11434 busy and retried every second (513k errors, 68 MB
`server.log`). The single Ollama start path (`ollama_runtime._start_server`, used
by boot, hot-swap, personas and Manager Start) therefore:

1. adopts any answering/occupied port, any `ollama serve` process, and a running
   tray app (its server may still be starting) — it never spawns a second server;
2. when the tray app is installed and the target is the default loopback port,
   launches `ollama app.exe` (which owns its server, so the login autostart finds
   a running instance) instead of a bare server; bare `ollama serve` only when no
   tray app exists or a non-default port is requested;
3. never modifies the owner's Startup shortcut or HKCU Run entry (read-only
   detection is shown in diagnostics);
4. reports the bind-retry loop (bounded 64 KB tail of `server.log`, only when the
   log is recent) with the log size and the fix (quit/restart Ollama from the tray).

### Keep-alive and Unload

The owner sets `OLLAMA_KEEP_ALIVE=-1`, which pins models. ANZU never overrides that
globally. Start offers `keep_alive`: `idle` (ANZU's idle-unload policy, default) or
`server` (omit keep_alive so the server default, e.g. the pin, applies). Loaded
Ollama models whose `/api/ps` expiry is years ahead are labelled *pinned*, and the
panel's per-model **Unload** (`keep_alive: 0`, verified via `/api/ps`) lets GPU jobs
free VRAM without stopping the server. Model loads and llama-server readiness allow
up to 600 s (27B/35B weights from disk).

The Manager adds a Models panel and fixed-path core proxies. Loopback middleware
and the session token protect mutations. On refused core connections, shared
discovery is available. Only native Ollama/LM Studio unload can fall back, when
the core process/port/control action is absent. Timeouts and unhealthy cores fail
closed because their request lease is unknown. Offline fallback never launches,
attaches providers or terminates processes.

## Acceptance criteria

- [x] Broader bounded discovery, loaded/available separation and process diagnostics tested.
- [x] RFC-0210 attachment, owner choices and managed-seat exclusions remain compatible.
- [x] Profiles, context/cache/flash/MoE options and VRAM confirmation tested.
- [x] Ollama, LM Studio and llama.cpp lifecycle paths tested (mocked backends; live small Ollama separately below).
- [x] Manager panel, proxy, offline native stop, loopback/token and confirmation gates tested.
- [x] Focused inference/API/Manager regressions and `git diff --check` pass (366 tests; no full-suite claim).
- [x] Live discovery JSON, small-model start/stop log and duplicate-server refusal saved.
- [x] Tray-app preference, adopt-existing/pending server, no second spawn, read-only autostart detection and retry-loop diagnostic tested.
- [x] Pinned (keep_alive -1) detection, `server` keep-alive option and Unload (keep_alive 0) tested.
- [x] Manager panel inspected, including narrow layout and error feedback (temporary source instance, not installed-app acceptance).

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `inference/{running_models.py,model_launch.py,ollama_runtime.py}`, `api/model.py` |
| Manager | `manager/main.py`, `manager/static/{index.html,app.js,models.js,style.css}` |
| Tests | `tests/test_rfc0247_model_manager.py`, existing RFC-0210/Manager/inference tests |
| Evidence | `CODEX_REPORT.md`, `LIVE_DISCOVERY.json`, `LIVE_STARTSTOP.log` |

## Out of scope

Scheduler/self-development, unattended launches, new providers, persona/WebGL/HUD
presence changes, downloads, large-model performance certification and publication.

## Notes

Compatibility with reviewed open PRs:

- **#690** owns Keep warm/idle release. Start calls its
  `keep_alive.ollama_keep_alive()` when present; the minimal fallback here uses
  the same 300-second default without another timer. On rebase, register successful
  explicit Start in its loaded-model ledger and owner-load hook. The LM Studio
  load already uses its TTL helper when available. Never apply that policy to
  externally owned models.
- **#686/#682 (RFC-0242)** own dropdown Load/Pin/Unload and identity. Start loads;
  Use selects. Their explicit-owner-load scope can wrap this explicit Start route.
- **#652 (RFC-0225)** specifies coexistence/resilience. No competing engine
  release/reacquire controller is added; overcommit stays an owner decision.
- **#585/#670 (RFC-0211)** own native Ollama worker transport/scheduler. No
  discovery prompts, editor/agent delegation or schedule changes here.

References: [Ollama generate](https://docs.ollama.com/api/generate),
[Ollama server/cache settings](https://docs.ollama.com/faq),
[LM Studio CLI](https://lmstudio.ai/docs/cli/local-models/load),
[llama.cpp flags](https://github.com/ggml-org/llama.cpp/tree/master/tools/cli).
Preserve all pre-existing live workloads. Commit locally; supervisor publishes
one coherent PR against `development` after review.
