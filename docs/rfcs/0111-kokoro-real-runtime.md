# RFC-0111: Kokoro as a real runtime (not a selectable label)

**Status:** implemented
**Queue item:** (none — no new §58 checkbox; implement is a named follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent / living spec:** [`JARVIS_1.4_SPECS.md`](../../JARVIS_1.4_SPECS.md) work package **A** (§3) + TTS slices of §10–12 / DoD §14.  
**Related (do not rewrite; do not invent conflicting defaults):** [RFC-0070](0070-higher-quality-local-tts-engines.md) engine adapter + Kokoro-82M as default low-latency English. [RFC-0092](0092-neural-tts-default-no-silent-sapi.md) Sol handoff — default profile remains `butler_original_v1` (Kokoro `bm_daniel` at 0.96); neural failure must not silently return SAPI. RFC-0056 / RFC-0062 catalog. RFC-0081 / RFC-0089 TTS quality (0092 already owns the default/SAPI policy). RFC-0075 speak-filter (what is spoken, not which engine). [RFC-0112](0112-voice-preview-exact-profile.md) preview path consumes this runtime truth.

This PR is **specs-only**. Product code is a follow-up implement ticket. Full intent; **no stubs / soft-fail** (a picker that shows Kokoro READY because the package imported, or speak that `pip install`s mid-utterance, or SAPI audio while the profile is still Kokoro, is a fail). 1.4 **deepens runtime truth**; it does not reopen RFC-0092’s default speaker or RFC-0070’s ranking table.

**Recommended implement model:** Grok 4.5/4.6 or equivalent strong coding model (1.4 §2). Tests/installer validation may land as Composer 2.5 after the adapter exists.

## Problem

Jarvis treats five different facts as if they were one:

- Kokoro is selectable in the catalog.
- The Kokoro Python package is importable.
- Kokoro weights/assets exist on disk.
- The Kokoro pipeline can initialize.
- Kokoro can synthesize valid audio.

Those are not equivalent. Tip `backend/app/tts/engines.py` `is_kokoro_available()` returns **True** unless `JARVIS_DISABLE_KOKORO` is set — “selectable unless explicitly disabled,” with Python/weights staged lazily on first synthesis. The UI can therefore show a Kokoro profile as usable when synthesis later fails. Loading behavior is spread across `engines.py`, `synthesize.py`, `warm_start.py`, `pack_install.py`, `workers/voice.py`, and `voice_profiles/*`. Import success is treated as health.

RFC-0092 already forbids silent SAPI when a neural profile was requested. 1.3.x still does not **prove** which engine actually spoke, and ordinary speech can still attempt package install. 1.4 must make Kokoro a **verified runtime**, not a label.

## Decision

Ship an explicit TTS runtime-state model, a single Kokoro adapter pinned to a validated package version, a real synthesis health probe, and a status API that reports **requested vs actual** engine. Ordinary speak never installs packages and never silently substitutes SAPI.

### 1. Runtime state model

Introduce one object. Suggested home: `backend/app/tts/runtime_state.py` (or beside the adapter).

```python
from dataclasses import dataclass

@dataclass
class TtsRuntimeState:
    engine_id: str
    package_ready: bool
    assets_ready: bool
    pipeline_ready: bool
    synthesis_verified: bool
    model_id: str = ""
    speaker_ref: str = ""
    device: str = ""
    last_error: str = ""

    @property
    def ready(self) -> bool:
        return (
            self.package_ready
            and self.assets_ready
            and self.pipeline_ready
            and self.synthesis_verified
        )
```

For Kokoro, distinguish at least:

```python
def is_kokoro_installable() -> bool:
    """Can this installation attempt to install/repair Kokoro?"""
    ...

def kokoro_runtime_state() -> TtsRuntimeState:
    """What is actually usable right now?"""
    ...

def is_kokoro_available() -> bool:
    return kokoro_runtime_state().ready
```

Rule: **installable is not the same as ready.** `is_kokoro_available()` must mean `ready`, not “not disabled.” Callers that today use `is_kokoro_available()` for picker enablement must switch to `ready` vs `installable` explicitly.

### 2. Kokoro API adapter

Centralize Kokoro-specific load/synth in **one** adapter instead of spreading model-loading across modules.

Suggested file: `backend/app/tts/kokoro_adapter.py`

Suggested shape (exact `KPipeline` arguments must match the **pinned** package; do not pass a filesystem model directory unless that version documents it):

```python
class KokoroAdapter:
    def __init__(self):
        self._pipelines: dict[str, object] = {}

    def get_pipeline(self, lang: str):
        cached = self._pipelines.get(lang)
        if cached is not None:
            return cached
        from kokoro import KPipeline
        pipeline = KPipeline(lang_code=lang)
        self._pipelines[lang] = pipeline
        return pipeline

    def synthesize(self, text: str, *, voice: str, speed: float) -> bytes:
        lang = "b" if voice.startswith("b") else "a"
        pipeline = self.get_pipeline(lang)
        chunks: list[bytes] = []
        for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed):
            if audio is not None:
                chunks.append(_float32_to_pcm16(audio))
        if not chunks:
            raise RuntimeError("Kokoro produced no audio")
        return _pcm_to_wav(b"".join(chunks), sample_rate=24000)
```

If the pinned version requires an explicit model object or local asset loader, implement it **inside this adapter only**.

### 3. Pin Kokoro and validate that exact version

Jarvis must use a **known supported** Kokoro package, not an open-ended dependency that silently changes API.

Intent:

```text
kokoro==<validated version>
soundfile==<validated version>
```

The implement agent determines exact versions **after** a real synthesis integration test. Desktop Setup / installer provisions that validated runtime. Do not leave `kokoro` unpinned on the 1.4 ship path.

### 4. Do not install Python packages during ordinary speech

Normal synthesis must **not** execute `pip install` (or equivalent) as a side effect of speak/preview.

Install or repair may happen only in:

- initial Jarvis setup;
- explicit **Install household voice** action;
- explicit repair action;
- updater / migration step.

Normal synthesis fails clearly if the runtime is not ready:

```python
async def _synthesize_kokoro(...):
    state = kokoro_runtime_state()
    if not state.ready:
        raise TtsSynthesisError(
            "kokoro",
            profile.id,
            state.last_error or "Kokoro runtime is not ready",
        )
    return await asyncio.to_thread(...)
```

### 5. No silent SAPI substitution

This is the RFC-0092 policy, restated as runtime law for 1.4:

```text
If selected profile = Kokoro:
  Kokoro succeeds -> use Kokoro
  Kokoro fails    -> report Kokoro failure
```

Do **not** silently route the same request to SAPI/espeak/pyttsx3. Windows SAPI remains an **explicit selectable** baseline/fallback profile; fallback must be visible (`fallback_active=true`, `actual_engine` is SAPI, requested engine stays Kokoro). Optional owner-accepted degrade (RFC-0092) is allowed only after neural failure **and** the UI/API records that the owner accepted it — never while pretending Kokoro succeeded.

Do **not** change RFC-0092 defaults: active/default profile stays `butler_original_v1` / Kokoro `bm_daniel` at 0.96 (or a documented better in-tree neural). The health-probe example speaker `bm_george` is a **probe utterance**, not a new product default.

### 6. Runtime health probe

A successful import is insufficient. Probe with a **real short synthesis**.

```python
async def verify_kokoro_runtime() -> TtsRuntimeState:
    try:
        audio = await kokoro_adapter.synthesize_async(
            "Voice systems online.",
            voice="bm_george",  # probe speaker; default profile remains bm_daniel (RFC-0092)
            speed=0.96,
        )
        if len(audio) < 1024:
            raise RuntimeError("Generated WAV is unexpectedly small")
        return TtsRuntimeState(
            engine_id="kokoro",
            package_ready=True,
            assets_ready=True,
            pipeline_ready=True,
            synthesis_verified=True,
            model_id="kokoro-82m",
            speaker_ref="bm_george",
        )
    except Exception as exc:
        return TtsRuntimeState(
            engine_id="kokoro",
            package_ready=kokoro_python_ready(),
            assets_ready=kokoro_weights_ready(),
            pipeline_ready=False,
            synthesis_verified=False,
            last_error=str(exc),
        )
```

Cache the result. Refresh after install, repair, app restart, voice-pack change, or explicit retry. **Do not** health-synthesize on every speech request.

### 7. Status API: requested vs actual engine

Voice status must expose reality. Healthy:

```json
{
  "requested_engine": "kokoro",
  "actual_engine": "kokoro",
  "model": "kokoro-82m",
  "voice": "bm_george",
  "package_ready": true,
  "assets_ready": true,
  "pipeline_ready": true,
  "synthesis_verified": true,
  "ready": true,
  "fallback_active": false,
  "last_error": null
}
```

Broken:

```json
{
  "requested_engine": "kokoro",
  "actual_engine": null,
  "ready": false,
  "fallback_active": false,
  "last_error": "..."
}
```

The frontend must **not** infer readiness from `engine=kokoro` / `engine_id` alone. Spoken result metadata (RFC-0092) still includes `engine_id` and `profile_id`.

### 8. UI status text

| State | Copy |
| --- | --- |
| Good | `Kokoro 82M · bm_george · READY` (use the **actual** speaker/model; default butler still shows `bm_daniel` when that is the active profile) |
| Broken | `Kokoro · FAILED TO LOAD` plus the **actual** error |
| Explicit system | `Windows SAPI · SYSTEM VOICE` |

Never hide: package missing, model assets missing, pipeline initialization error, invalid speaker reference, empty waveform (browser playback failure is RFC-0112).

### 9. Observability

Structured events: `voice_runtime_probe` (plus preview events owned by RFC-0112). TTS log fields:

```json
{
  "profile_id": "butler_original_v1",
  "requested_engine": "kokoro",
  "actual_engine": "kokoro",
  "model_id": "kokoro-82m",
  "speaker_ref": "bm_daniel",
  "verified": true,
  "latency_ms": 412
}
```

**Will not:** change RFC-0092 default profile / SAPI-as-natural labeling / Chatterbox one-click Setup (those stay 0092). Cloud TTS default. OpenViking-as-TTS. Actor/Marvel clones. `pip` during speak. Silent SAPI. Reporting `ready=true` from import alone.

## Acceptance criteria

Specs-only in **this** PR:

- [x] Specs-only in this PR (no product code) — specs PR #286

Implement follow-up (landed):

- [x] `TtsRuntimeState` exists; `ready` requires package + assets + pipeline + **synthesis_verified** — #296 `backend/app/tts/runtime_state.py`
- [x] `is_kokoro_available()` is equivalent to `kokoro_runtime_state().ready`; installable ≠ ready — #296 `engines.py` / `is_kokoro_installable()`
- [x] Single `KokoroAdapter` owns pipeline/synth; other modules do not pass undocumented filesystem model dirs into `KPipeline` — #296 `kokoro_adapter.py` (bundled `KModel` + `KPipeline` constructed inside the adapter)
- [x] `kokoro` and `soundfile` are pinned to versions validated by a real synthesis test; Setup/installer provisions them — #296 `kokoro==0.9.4` / `soundfile==0.14.0` in `backend/requirements.txt` + `installer/windows/bootstrap.ps1`
- [x] Ordinary speak/preview **never** starts an implicit package install; missing runtime raises `TtsSynthesisError` (or equivalent) with `last_error` — #296 `synthesize.py` / adapter `synthesize()` refuses unverified runtime
- [x] Kokoro selected + healthy → `actual_engine` is `kokoro` — #296 `voice_status()` + `tests/test_rfc0111_kokoro_runtime.py`
- [x] Kokoro selected + broken → synthesis fails explicitly; **never** silently returns SAPI audio — #296 `TtsSynthesisError`; engine chain for Kokoro is `["kokoro"]` only
- [x] Status only reports `ready=true` after successful synthesis verification — #296 `KokoroAdapter.verify()` requires WAV ≥1024 bytes
- [x] Health probe runs real short WAV (≥1024 bytes); cached; refreshed on install/repair/restart/pack change/retry — not on every speak — #296 `verify()` cache + `pack_install.verify_kokoro_runtime(force=True)` + `warm_start`
- [x] Status API reports `requested_engine` vs `actual_engine`, readiness flags, `fallback_active`, `last_error` — #296 `workers/voice.py` `tts_runtime`
- [x] Settings/HUD copy matches READY / FAILED TO LOAD / SYSTEM VOICE; frontend does not infer ready from `engine=kokoro` alone — #296 `VoiceProfilePicker` uses `runtime.ready`; READY / FAILED TO LOAD copy landed. Explicit SAPI is a baseline/system voice (not a silent fallback). Full preview UX remains RFC-0112 HOLD
- [x] TTS errors listed in 1.4 §10 are never swallowed — #296 `TtsSynthesisError` + no silent SAPI
- [x] Tests (1.4 §12 TTS 1–4, 9–10): healthy actual engine; broken explicit fail; no silent SAPI; ready only after verify; install/repair refreshes health; no pip during speak — #296 `tests/test_rfc0111_kokoro_runtime.py` + `tests/test_rfc0070_tts.py` updates. Existing RFC-0092 tests remain (0092 files not rewritten in #296)
- [x] Implement follow-up: `python3 -m pytest` (`tests/test_rfc0070_tts.py` updates + new `tests/test_rfc0111_*.py`) — #296
- [ ] Windows desktop sign-off: live A/B listen quality after Setup rebuild. Cloud VMs cannot sign this off. (#296 recorded live WAV probes for `bm_george` / `bm_daniel`; human listen quality remains desktop)

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/tts/kokoro_adapter.py` (new), `runtime_state.py` (new), `engines.py`, `synthesize.py`, `warm_start.py`, `pack_install.py`; `backend/app/workers/voice.py`; `backend/app/voice_profiles/*`; `backend/app/api/voice_profiles.py`; requirements / installer seed of pinned `kokoro`/`soundfile` |
| Frontend | Settings/HUD voice status copy (readiness from status API, not `engine_id` alone) — full preview UX is RFC-0112 |
| Tests | `tests/test_rfc0111_*.py`, updates to `tests/test_rfc0070_tts.py`, `tests/test_rfc0092_*.py` |
| Docs | this RFC; `JARVIS_1.4_SPECS.md` path note; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. RFC-0112 preview playback / error-preservation UI. RFC-0113 Settings IA. Chatterbox as silent first-run default. Changing `butler_original_v1` / `bm_daniel` default (RFC-0092). Cloud TTS. OpenViking. HexStrike. Invented LE/Red/Purple/ATO gates. Exploit recipes.

## Notes

- 1.4 suggested implement order: **PR 4** after routing/context PRs (RFC-0115 / RFC-0114). Adapter+state may land first if CoS names this ticket.
- Linux cloud cannot sign off live Kokoro listen quality; unit-test routing/fallback/ready-contract. Desktop A/B listen after Setup rebuild.
- Implement launch: this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`; do not merge other PRs.

## Implementation note

Landed on `development` via specs **#286** @ `1f8320d` (Jarvis 1.4 RFC split) + implement **#296** @ `99a0463` (`TtsRuntimeState` + `KokoroAdapter`; pinned `kokoro==0.9.4` / `soundfile==0.14.0`; synthesis-backed READY; no pip during speak/preview; no silent SAPI; requested-vs-actual engine status). Deepens RFC-0070 / RFC-0092; does **not** change 0092 defaults (`butler_original_v1` / `bm_daniel`). **RFC-0112** voice preview remains HOLD (Sol/Taco). Live A/B listen quality after Setup rebuild remains Windows desktop sign-off. No new §58 checkbox.
