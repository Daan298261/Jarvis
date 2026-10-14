# RFC-0214: Performance Compass

**Status:** accepted  
**Queue item:** backlog (no §58 checkbox; Architect may add one when Taco schedules it)  
**Author:** Chief of Staff (Taco-authorized spec exception: specs may be written in parallel with the Architect)  
**Date:** 2026-10-12

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md): one assistant, local-first, honest about what it is doing, meaningful owner control over consequential trade-offs, no stubs and nothing half-wired.  
**Builds on (does not edit):** [0206](0206-jev-laya-every-turn-arbitration.md), [0209](0209-autonomous-memory-capture.md), RFC-0107 vault binding, RFC-0117 front lane.  
**Numbering:** **0207** and **0208** are the Architect's reverse-engineering specs. 0210–0213 are taken. This ticket is **0214**.  
**Sequencing:** **backlog.** Do not schedule implementation. Implement only after the reverse-engineering queue clears and Taco schedules it.  
**Surface ownership:** ANZU **portal settings** only. Personas, WebGL and presence surfaces belong to Astra and are out of scope.

Product name in owner-facing text is **ANZU Superassistant**. The engineering tree stays Jarvis.

Verified against `development` at `8a63d44`.

## Problem

ANZU's inference trade-offs (speed vs. reasoning vs. context length) are spread across many raw fields. Taco has to know llama.cpp flags to move them. There is no single control that says "faster first answers" or "longer context" and then sets the right knobs for the detected GPU and RAM. There is no preview of VRAM before a change, so a wrong edit spills the model to system RAM and the next turn is slow with no warning.

### Where the knobs live today (real code paths)

| Knob | Setting / code path today | Default |
|---|---|---|
| KV cache type K/V | `InferenceSettings.cache_type_k` / `cache_type_v` in `backend/app/config.py` → `--cache-type-k` / `--cache-type-v` in `LlamaCppBackend.build_args` (`backend/app/inference/backends.py`) | `q8_0` / `q8_0` |
| Flash attention | `InferenceSettings.flash_attn` → `--flash-attn` (`backends.py`) | `auto` |
| Worker context (`n_ctx`) | `InferenceSettings.context_size`, overridden by `ModelProfile.context_size` (`backend/app/inference/profiles.py`) and the `context_size` argument → `--ctx-size`. Ceiling: `hardware_context_ceiling` / `ram_supported_context_ceiling` (`backend/app/inference/ram_policy.py`). Live value read back by `extract_loaded_n_ctx` (`backend/app/inference/context_window.py`) | 16384 (27B Heretic profile starts at 8192) |
| GPU layers / CPU offload | `build_args(n_gpu_layers=...)` → `--n-gpu-layers`; else `InferenceSettings.fit` + `fit_target_mib` → `--fit on --fit-target` via `effective_fit_target_mib` (`ram_policy.py`); else `--n-gpu-layers 99` | `fit=True`, `fit_target_mib=1024` |
| Reasoning / thinking | `ModelProfile.thinking` / `thinking_mode`; `build_args(reasoning=...)` → `--reasoning on/off`, `--reasoning-format deepseek`; `RuntimeProfile` thinking check in `backend/app/inference/runtime_profiles.py` | per profile (27B: on) |
| Temperature / top-p / top-k | `ModelProfile.temperature`, `top_p`, `top_k` → `--temp`, `--top-p`, `--top-k`; front lane `FrontResponderSettings.temperature` | 27B: 0.6 / 0.95 / 20; front 0.25 |
| Parallel lanes | `build_args(parallel=...)` → `--parallel`; front lane starts with `parallel=1` (`backend/app/inference/front_runtime.py`); `FrontResponderSettings.parallel_when_distinct_model` | unset (llama-server default) |
| Prompt cache | `build_args(prompt_cache=False)` → `--no-cache-prompt`; `FrontResponderSettings.prompt_cache` | on |
| Threads | `InferenceSettings.threads` (0 = detected cores) → `--threads` | 0 |
| Front responder model / device | `FrontResponderSettings.profile`, `model`, `device` (`auto`/`cpu`/`gpu`), `n_gpu_layers`, `context_size` (4096), `max_output_tokens` (128), `placement` (`backend/app/config.py`; resolved in `front_runtime.py`) | `front_2b` on CPU (`-ngl 0`) via `config/default.json` |
| Worker profile | `InferenceSettings.profile`; profiles in `profiles.py` (incl. `qwen38_27b_heretic_profile`, `backend/app/inference/qwen38_local.py`) | `fast` |
| Ollama runtime | `ensure_local_ollama` (`backend/app/inference/ollama_runtime.py`); GPU warm via `gpu_prefer.ensure_ollama_gpu` | n/a |

**Not wired today (gaps this RFC closes, not invents around):** batch / ubatch size (`--batch-size`, `--ubatch-size`), `--mlock` / `--no-mmap`, keep-alive for llama-server (only the orchestrator idle unload `InferenceSettings.orchestrator_idle_seconds` exists), Ollama `options.num_ctx` / `keep_alive` / `num_gpu` (not passed by `ollama_runtime.py`), speculative / draft decoding, rope scaling. Each is added to `build_args` (or the Ollama request options) by the implementation as a real argument with tests, or left out of the Compass. No knob appears in UI without a live code path.

## Decision

Add a **Performance Compass**: a circular dial in ANZU portal settings (Settings → Inference → Performance). A dot can be dragged anywhere inside the circle. ANZU blends three poles and writes concrete, hardware-checked values into the existing `InferenceSettings` / `FrontResponderSettings` / profile overrides. There is no second config system. The Compass is a front end on the settings that already exist, plus a small persisted `compass` block that records the dot position.

### Poles

- **Center: Balanced.** Exactly today's resolved defaults on this machine. Moving the dot back to center restores them byte-for-byte.
- **Top (90°): Speed.** Fast first answers. Trades context length and reasoning depth.
- **Bottom-left (210°): Quality.** More reasoning and accuracy.
- **Bottom-right (330°): Capacity.** Longer context; slower.

### Knob set per pole (hardware-aware)

`H` = detected hardware (`detect_hardware()`, `_vram_total_mib`, `_ram_total_gb` in `ram_policy.py`). Values are targets; the fit solver (below) clamps them.

| Knob | Speed | Balanced | Quality | Capacity | Kind |
|---|---|---|---|---|---|
| KV cache K/V | q8_0 | today (q8_0) | f16 if it fits, else q8_0 | q8_0 → q4_0 at extreme | discrete |
| Flash attention | on | auto | on | on (required for quantized V) | discrete |
| Worker `n_ctx` | max(4096, 0.5 × balanced) | today | today | up to `hardware_context_ceiling` | continuous, snapped to 1024 |
| GPU layers / offload | all on GPU (`--fit` target tight) | today (`--fit`) | all on GPU | allow CPU/RAM offload (larger `fit_target`) | continuous |
| Reasoning | off for front, off/short for worker | per profile | on, larger budget | per profile | discrete + continuous budget |
| Worker model / quant | smaller installed profile allowed (fallback chain) | today | largest installed that fits | today | discrete |
| Front model | `front_2b` CPU | today | `front_4b` GPU if VRAM headroom | `front_2b` CPU (frees VRAM for KV) | discrete |
| Temperature | profile − 0.1 | profile | profile − 0.1 (min 0.2) | profile | continuous |
| Parallel lanes | 1 | today | 1 | 1 | discrete |
| Batch / ubatch | larger ubatch (prompt speed) | llama default | default | smaller ubatch (VRAM) | discrete |
| mmap / mlock | mlock if RAM ≥ 2× model | default | default | mmap on, no mlock | discrete |
| Keep-alive | never idle-unload | today (`orchestrator_idle_seconds`) | today | today | continuous |

Worked example (Taco): a dot halfway between Quality and Capacity resolves to q8_0 KV, flash attention on, longer `n_ctx`, and some layers offloaded to CPU/RAM.

### Other llama.cpp / Ollama levers surveyed

- **Speculative / draft decoding** (`--model-draft`, `--draft-max`, `--draft-min`): exposed only under Advanced, only when a same-tokenizer draft GGUF is installed; Speed pole may enable it. Off by default.
- **MTP heads**: exposed only if the installed llama-server build and GGUF support it (probe `--help` at startup). Otherwise hidden, not greyed with a fake toggle.
- **Rope / YaRN scaling** (`--rope-scaling`, `--rope-scale`, `--yarn-orig-ctx`): Advanced only; Capacity may use it past the model's native context, with a quality warning.
- **Ollama**: `num_ctx`, `num_gpu`, `keep_alive`, `num_batch` passed as request options when the active backend is Ollama.
- Not exposed: `--prio` (keep 3), `--min-p` (keep 0), `--keep` (owned by `context_window.clamp_n_keep`).

### Interpolation math

Dot position `(x, y)` in the unit disc, center `(0,0)`. Polar `r = min(1, √(x²+y²))`, `θ = atan2(y, x)`.

Pole unit vectors `p_S = (0,1)`, `p_Q = (cos210°, sin210°)`, `p_C = (cos330°, sin330°)`.
Raw weights `w_i = max(0, (x,y)·p_i)`. Normalise `ŵ_i = w_i / Σw` (0 when Σw = 0). Pole strength `s_i = r · ŵ_i`, Balanced weight `s_B = 1 − r`.

For each continuous knob `k`: `k = s_B·k_B + Σ s_i·k_i` (log-space for `n_ctx` and `fit_target_mib`, then snap `n_ctx` to 1024).
For each discrete knob: take the value of the pole with the largest `s_i` if `s_i ≥ 0.35`, else Balanced. KV type uses an ordered ladder `f16 > q8_0 > q4_0`: map the blended "KV compression" scalar (Speed 0.5, Balanced = today, Quality 0, Capacity 1.0) to the ladder with thresholds 0.33 / 0.75. The UI shows snap rings where a discrete knob changes.

Then run the **fit solver**: if the estimated VRAM exceeds `VRAM − headroom` (headroom = `fit_target_mib`, min 768 MiB), reduce in order: `n_ctx` (down to the pole minimum), KV one step down the ladder, GPU layers (Capacity side only; Speed/Quality reject offload and show a warning instead). The resolved values, not the raw blend, are what gets applied and shown.

### Live preview and estimator

Shown under the dial, updated on drag (debounced 100 ms, computed in-process, no model load):

- **VRAM**: `weights_on_gpu + kv_bytes + compute_buffer + front_lane_vram`.
- `kv_bytes = n_ctx × 2 × n_layer × n_head_kv × head_dim × bytes(kv_type)` from GGUF metadata (f16 = 2, q8_0 ≈ 1.0625, q4_0 ≈ 0.5625 bytes/elem).
- `weights_on_gpu = gguf_size × (gpu_layers / n_layer)`.
- **Calibration anchor:** RTX 5070 Ti 16 GB, Qwen3.8-27B Q3_K_S ≈ 12 GB at ≈ 9k ctx with f16 KV. The compute-buffer term is solved from this anchor and then re-calibrated per machine from the live `/props` `n_ctx` and `nvidia-smi` used-VRAM after each load (stored in `data_dir()`). Taco accepted q8_0 KV as a quality trade; on this card the estimator must show that q8_0 roughly halves the KV term and lets `n_ctx` grow accordingly.
- **Context**: resolved `n_ctx` for worker and front.
- **Speed**: relative first-token and tokens/s bands from the latest `hardware_gate` / benchmark samples for the profile (`backend/app/inference/benchmarks.py`), scaled by offload fraction. Labelled as an estimate.
- **Spill warning**: an amber banner before apply whenever the estimate exceeds VRAM headroom or any layer leaves the GPU ("Part of the model will run from system RAM. Answers will be slower."). Apply still requires an explicit confirm.

### Safe apply

1. Write resolved values to settings (`save_settings`) with the previous snapshot kept as `compass.last_good`.
2. Reload the worker (and front lane only if its knobs changed) through the existing hotswap path (`backend/app/inference/hotswap.py` / manager). No reload when nothing in `build_args` changed.
3. Verify: health, `/props` `n_ctx` equals requested, VRAM within estimate + 10 %. On failure or OOM: restore `last_good`, reload, show the reason. The owner is never left with no model loaded.
4. Reload is refused while a turn is streaming; it is queued until the request lease (`request_lease.py`) is free.
5. **Swarm nodes:** the Compass is per node. The leader's dial applies to the leader only. Each node resolves the same dot position against its own hardware when the owner chooses "apply to all nodes"; a node whose fit fails keeps its own `last_good` and reports it. Remote/front `placement=remote` endpoints are not reconfigured.
6. Persisted in `settings.json` (`compass: {x, y, applied_at, last_good}`); restored at startup before auto-load.

### Advanced panel

Collapsed by default. Shows every resolved raw value (the exact `llama-server` argument list from `build_args`, redacted paths) and lets the owner override any single value; an override pins that knob and the dial shows a pin marker. Also under Advanced:

**(a) Context precompression.** Toggle and threshold for compacting older turns before the prompt hits `n_ctx` (existing `backend/app/agent/compaction.py`, prompt budget in `backend/app/inference/prompt_budget.py`). Capacity lowers aggressiveness; Speed raises it.

**(b) Retrieval instead of stuffing.** Threshold (tokens, default = 40 % of `n_ctx`) above which large inputs go to DB/vector retrieval (`backend/app/inference/large_input.py`, context repo) instead of the prompt. Top-k and min-score fields.

**(c) Obsidian vault usage.** Auto-retrieve on/off, scope (whole vault / jarvis-managed folders / named folders), write-back on/off per kind (session mirror, corrections, facts). **Current behaviour, stated factually (development @ `8a63d44`):**
- *Auto-retrieve: yes, on worker turns when a vault is bound.* `compose_turn_working_set` in `backend/app/agent/turn_working_set.py` runs a vault search. Catch: front-only turns skip the vault unless vault words match.
- *Auto write-back: yes for chat.* `mirror_owner_chat_turn` (`backend/app/memory/obsidian_vault.py`) appends every owner turn to `_Temporal/Sessions/`. *Yes for corrections* via `persist_verified_correction`. *No for facts* except the remember-phrase gate, until RFC-0209 is implemented.
- *Default: on.* The vault is bound at startup by `ensure_default_vault` in `backend/app/main.py`. The only off-switch today is unbinding. `KnowledgeVaultSettings` (`vault_path`, `jarvis_managed_layout`, `watch_enabled`) has **no toggle** for auto-retrieve or write-back. This RFC adds those toggles as real settings consumed by `turn_working_set.py` and `mirror_owner_chat_turn`; defaults keep today's behaviour.

**(d) Jev/Laya reflex-lane tuning.** Per decision class thresholds in `REFLEX_DECISION_CLASSES` (`backend/app/decision/types.py`), the reflex latency budget (RFC-0206, < 50 ms default), arbitration tie-break margin, and `memory_capture` sensitivity (RFC-0209). Case-material confirmation from RFC-0209 cannot be disabled here.

## Out of scope

Persona, WebGL, presence and avatar surfaces (Astra). Cloud model selection. Editing `JARVIS_MASTER_PLAN.md`.

## Tests and acceptance

Real-path tests; do not mock the resolver, `build_args`, or settings persistence.

1. **Center = today:** dot `(0,0)` resolves to a `build_args` list byte-identical to current defaults on a fixture hardware profile.
2. **Pole tests:** each pole on fixture hardware (16 GB / 64 GB RAM; 8 GB / 32 GB; CPU-only) produces the table's values after fit.
3. **Interpolation:** weights sum to 1; continuity on drag for continuous knobs; discrete knobs only change at the documented snap thresholds; halfway Quality↔Capacity on the 16 GB fixture gives q8_0 KV + partial offload.
4. **Estimator:** reproduces the 5070 Ti anchor (27B Q3_K_S, ~9k ctx, f16) within ±0.5 GB; q8_0 at the same ctx is lower by the KV delta.
5. **Spill warning** appears exactly when estimate > headroom or `gpu_layers < n_layer`.
6. **Safe apply:** forced load failure restores `last_good` and a model is loaded afterwards; no reload during a streaming turn.
7. **Every exposed knob has a code path:** a test enumerates Compass knobs and asserts each changes `build_args` or the Ollama request options.
8. **Vault toggles:** with auto-retrieve off, `compose_turn_working_set` performs no vault search; with session write-back off, `mirror_owner_chat_turn` writes nothing.
9. **Swarm:** "apply to all" resolves per node hardware; a failing node keeps `last_good`.
10. **Live check on Taco's PC:** Speed, Balanced, Quality, Capacity and the halfway Quality↔Capacity point each load, answer a turn, and match the preview's VRAM within 10 %.
11. `pytest` and frontend build green; north-star review: no dead UI, no unwired knob.
