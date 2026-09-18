# JARVIS 1.4 SPECS

Status: implementation specification for architect assignment  
Target release: 1.4  
Scope: TTS/Kokoro reliability, voice preview, Settings information architecture, context overflow recovery, and model-role routing.

**Path note (do not treat this file as the implement ticket):** living spec copied from `main` @ `6f6a633`. Implementable contracts are **RFC-0111–0115**. 1.4.0 also includes already-filed interesting integrations RFC-0107–0110 plus HexStrike/Daybreak/cyber in flight. Bulk Instagram/catalog RFCs **0095–0104** stay later — see [`INTEGRATION_SPECS.md`](INTEGRATION_SPECS.md).

---

## 1. Release intent

Jarvis 1.4 should fix two current user-visible reliability problems and turn them into architectural improvements rather than one-off patches.

1. Voice/TTS must reliably use the selected neural voice, especially Kokoro, and must prove which engine actually produced the audio.
2. Lightweight models such as Ornith 1.5 9B must act primarily as orchestration/router models rather than attempting difficult answers until they fail.
3. Context-window pressure must be detected before inference and recovered automatically instead of surfacing a fatal `Context size has been exceeded` error after only a few visible chat turns.
4. Voice and speech controls should move into a cleaner Admin > Settings submenu structure.

The result should feel like one continuous Jarvis system even when different models, workers, or TTS engines are used internally.

---

# 2. Recommended build-agent allocation

The architect should assign work by difficulty instead of sending the whole release to one model.

| Work package | Difficulty | Recommended implementation model | Notes |
|---|---:|---|---|
| Model-role architecture, escalation policy, context recovery | Very high | Grok 4.6 or strongest frontier reasoning/coding model available | Cross-cuts inference manager, routing, agent loop, context policy, persistence, UI events. Should be architected first. |
| Independent architecture review of routing/context design | Very high | Grok 4.6, or Grok 4.5 if 4.6 unavailable | Reviewer should be separate from primary implementer. |
| Kokoro runtime adapter and TTS health model | High | Grok 4.5/4.6 or equivalent strong coding model | Requires careful library/API integration and packaging/runtime behavior. |
| TTS backend tests and installer/runtime validation | High | Composer 2.5 or equivalent coding model, reviewed by stronger model | Good candidate for implementation after architecture is fixed. |
| Voice preview frontend/backend error propagation | Medium | Composer 2.5 | Narrow full-stack change with clear acceptance tests. |
| Admin > Settings submenu reorganization | Medium | Composer 2.5 or cheaper competent coding agent | Mostly routing/component composition and backwards-compatible redirects. |
| Regression tests for context overflow and escalation | High | Composer 2.5, reviewed by Grok 4.5/4.6 | Test design is important because the bug is cross-layer. |
| Final release integration review | Very high | Grok 4.6 or strongest available reviewer | Review only; do not let this model rewrite working code without a concrete defect. |

Guidance:

- Use the strongest model for architecture and cross-cutting recovery logic.
- Use Composer 2.5-style coding agents for bounded implementation tasks with clear interfaces and tests.
- Use a separate stronger reviewer for model-routing/context changes.
- Do not assign Ornith itself to implement or validate this release architecture.

---

# 3. Work package A — Kokoro must be a real runtime, not a selectable label

## 3.1 Current problem

Jarvis currently has multiple concepts that are treated as if they mean the same thing:

- Kokoro is selectable.
- Kokoro Python package is importable.
- Kokoro weights/assets exist.
- Kokoro pipeline can initialize.
- Kokoro can synthesize valid audio.

These are not equivalent.

The current implementation can report Kokoro as available before all runtime requirements are verified. This causes the UI to show a voice as usable even when synthesis later fails.

Relevant current files:

- `backend/app/tts/engines.py`
- `backend/app/tts/synthesize.py`
- `backend/app/tts/warm_start.py`
- `backend/app/tts/pack_install.py`
- `backend/app/workers/voice.py`
- `backend/app/voice_profiles/*`

## 3.2 Required runtime state model

Introduce an explicit runtime state object.

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

Rule:

> Installable is not the same as ready.

## 3.3 Kokoro API adapter

Centralize Kokoro-specific behavior in one adapter instead of spreading model-loading behavior across multiple modules.

Suggested file:

`backend/app/tts/kokoro_adapter.py`

Suggested shape:

```python
class KokoroAdapter:
    def __init__(self):
        self._pipelines: dict[str, object] = {}

    def get_pipeline(self, lang: str):
        cached = self._pipelines.get(lang)
        if cached is not None:
            return cached

        from kokoro import KPipeline

        # IMPORTANT:
        # Use the exact API supported by the Kokoro version pinned by Jarvis.
        # Do not pass a filesystem model directory to an argument unless that
        # exact package version documents that behavior.
        pipeline = KPipeline(lang_code=lang)
        self._pipelines[lang] = pipeline
        return pipeline

    def synthesize(self, text: str, *, voice: str, speed: float) -> bytes:
        lang = "b" if voice.startswith("b") else "a"
        pipeline = self.get_pipeline(lang)
        chunks: list[bytes] = []

        for _graphemes, _phonemes, audio in pipeline(
            text,
            voice=voice,
            speed=speed,
        ):
            if audio is not None:
                chunks.append(_float32_to_pcm16(audio))

        if not chunks:
            raise RuntimeError("Kokoro produced no audio")

        return _pcm_to_wav(b"".join(chunks), sample_rate=24000)
```

If the pinned Kokoro version requires an explicit model object or local asset loader, implement it inside this adapter only.

## 3.4 Pin Kokoro and validate that exact version

Jarvis must use a known supported Kokoro package version, not an open-ended dependency that may silently change API behavior.

Example intent:

```text
kokoro==<validated version>
soundfile==<validated version>
```

The exact versions should be determined by the implementation agent after running the real synthesis integration test.

The installer/setup path should provision this validated runtime.

## 3.5 Do not install Python packages during ordinary speech

Normal speech synthesis must not unexpectedly execute `pip install`.

Installation or repair may happen in:

- initial Jarvis setup;
- explicit `Install household voice` action;
- explicit repair action;
- updater/migration step.

Normal synthesis should fail clearly if the runtime is not ready.

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

## 3.6 No silent SAPI substitution

This policy must remain strict.

If selected profile = Kokoro:

```text
Kokoro succeeds -> use Kokoro
Kokoro fails    -> report Kokoro failure
```

Do not silently route the same request to SAPI.

Windows SAPI remains an explicit selectable baseline/fallback profile, but fallback must be visible.

## 3.7 Runtime health probe

A successful import is insufficient.

Add a health probe that performs a real short synthesis.

```python
async def verify_kokoro_runtime() -> TtsRuntimeState:
    try:
        audio = await kokoro_adapter.synthesize_async(
            "Voice systems online.",
            voice="bm_george",
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

Cache the result and refresh it after:

- install;
- repair;
- app restart;
- voice pack change;
- explicit retry.

Do not perform a health synthesis on every speech request.

## 3.8 Status API must report requested vs actual engine

Voice status should expose reality, for example:

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

If broken:

```json
{
  "requested_engine": "kokoro",
  "actual_engine": null,
  "ready": false,
  "fallback_active": false,
  "last_error": "..."
}
```

The frontend must not infer readiness from `engine=kokoro` alone.

## 3.9 UI status text

Good state:

```text
Kokoro 82M · bm_george · READY
```

Broken state:

```text
Kokoro · FAILED TO LOAD
<actual error>
```

Explicit system voice:

```text
Windows SAPI · SYSTEM VOICE
```

---

# 4. Work package B — Voice preview must use the exact selected profile

## 4.1 Current problem

The backend already has a useful profile-specific preview endpoint, but the frontend currently collapses nearly every failure into:

`Preview is not available for this voice yet.`

That hides the real problem.

Relevant files:

- `backend/app/api/voice_profiles.py`
- `frontend/src/tts/voiceProfiles.ts`
- `frontend/src/tts/VoiceProfilePicker.tsx`

## 4.2 Canonical preview route

Use one canonical endpoint:

```text
POST /api/voice-profiles/{profile_id}/preview
```

The preview must:

1. load the exact requested voice profile;
2. synthesize the profile's sample utterance;
3. return WAV audio;
4. identify actual engine and profile in headers or metadata;
5. return a meaningful backend error when synthesis fails.

Suggested response headers:

```text
X-Jarvis-TTS-Engine: kokoro
X-Jarvis-Voice-Profile: butler_original_v1
X-Jarvis-TTS-Model: kokoro-82m
X-Jarvis-TTS-Voice: bm_george
```

## 4.3 Frontend must preserve backend errors

Do not broadly swallow every fetch error.

Compatibility fallback may only occur for route-not-found style failures.

Example:

```typescript
catch (err) {
  if (isHttpStatus(err, 404) || isHttpStatus(err, 405)) {
    continue
  }

  throw err
}
```

A 503 from Kokoro initialization must remain a 503 Kokoro error.

## 4.4 Preview result type

```typescript
export type VoicePreviewResult = {
  ok: boolean
  engineId?: string
  profileId?: string
  modelId?: string
  voiceId?: string
  error?: string
  status?: number
}
```

## 4.5 Playback failure must be a failure

Do not treat `audio.onerror` as successful completion.

```typescript
await new Promise<void>((resolve, reject) => {
  audio.onended = () => resolve()
  audio.onerror = () => reject(new Error("Browser could not decode preview audio"))
  audio.play().catch(reject)
})
```

Always revoke the object URL in `finally`.

## 4.6 Preview UI examples

Success:

```text
Preview: Kokoro 82M · bm_george
```

Backend failure:

```text
Kokoro preview failed: model assets could not be loaded.
```

Playback failure:

```text
Preview audio was generated, but this client could not play the WAV.
```

Never replace a known concrete error with `Preview is not available for this voice yet.`

---

# 5. Work package C — Admin > Settings submenu structure

## 5.1 Desired structure

```text
Admin
└── Settings
    ├── Appearance & Voice
    ├── Phone Pairing
    ├── Models & Inference
    ├── Network & Swarm
    ├── Integrations
    └── Advanced
```

The current Settings submenu infrastructure should be reused rather than replaced.

Relevant files:

- `frontend/src/pages/Settings.tsx`
- `frontend/src/settings/settingsSubmenus.ts`
- `frontend/src/settings/AppearanceSettingsPane.tsx`
- `frontend/src/settings/VoiceSettingsPane.tsx`
- `frontend/src/pages/CompanionPairing.tsx`
- `frontend/src/App.tsx`

## 5.2 Canonical routes

Preferred canonical routes:

```text
/admin/settings/appearance-voice
/admin/settings/phone-pairing
/admin/settings/models
/admin/settings/network
/admin/settings/integrations
/admin/settings/advanced
```

If the existing app routing makes `/admin/...` disproportionately invasive, the minimum acceptable canonical structure is:

```text
/settings/appearance-voice
/settings/phone-pairing
/settings/models
/settings/network
/settings/integrations
/settings/advanced
```

The architect should choose one routing convention and use it consistently.

## 5.3 Backwards-compatible redirects

Existing routes must keep working.

```text
/settings/voice
  -> /settings/appearance-voice

/settings/appearance
  -> /settings/appearance-voice

/companion-pairing
  -> /settings/phone-pairing

/settings/network
  -> canonical network route
```

## 5.4 Appearance + Voice composition

Create a composed pane, e.g.:

`frontend/src/settings/AppearanceVoiceSettingsPane.tsx`

```tsx
export function AppearanceVoiceSettingsPane(...) {
  return (
    <>
      <AppearanceSettingsPane ... />

      <section className="settings-section">
        <h2>Voice & Speech</h2>
        <VoiceSettingsPane />
      </section>
    </>
  )
}
```

## 5.5 Phone Pairing

Reuse the existing pairing component/page logic. Do not duplicate pairing state or APIs.

---

# 6. Work package D — Context overflow must be recoverable

## 6.1 User-visible failure to eliminate

Observed flow:

```text
Understanding the request
Context 16384 · vision lazy · thinking selective
Inference failed
Inference server error (400): Context size has been exceeded.
```

This happened with only a few visible chat messages.

Jarvis 1.4 must not expose this as the normal outcome of a recoverable context problem.

## 6.2 Current architectural issues

The current system has multiple context calculations and inconsistent heuristics.

Examples of areas to reconcile:

- `backend/app/agent/model_policy.py`
- `backend/app/agent/context_policy.py`
- `backend/app/agent/compaction.py`
- `backend/app/inference/manager.py`
- `backend/app/agent/loop.py`

Important issues:

1. Jarvis calculates recommended/wanted context separately from the initial server context actually applied.
2. Different layers use different character-to-token assumptions.
3. The server may expose a smaller live context than the model's nominal profile cap.
4. A 400 context error is currently treated as fatal instead of a recovery signal.

## 6.3 One canonical prompt-budget system

Introduce a shared structure:

```python
@dataclass
class PromptBudget:
    prompt_tokens: int
    tool_tokens: int
    output_reserve: int
    system_reserve: int
    required_context: int
    active_context: int
    profile_cap: int
    pressure: float
```

All inference paths should use the same budgeting implementation.

## 6.4 Token counting priority

Preferred order:

1. backend-native tokenizer / tokenizer endpoint if supported;
2. model tokenizer bundled with the runtime;
3. conservative fallback estimate.

Only use a character heuristic when no tokenizer is available.

Do not let one module assume 4 chars/token while another independently assumes 2 chars/token for the same request.

## 6.5 Central inference preflight

Every inference call should run through one preflight path.

Pseudo-code:

```python
async def prepare_inference(messages, tools, profile, max_tokens):
    budget = await calculate_prompt_budget(
        messages,
        tools,
        profile=profile,
        max_tokens=max_tokens,
    )

    if budget.pressure < 0.70:
        return PreparedInference(messages, tools, profile)

    messages = compact_history(messages)
    budget = await calculate_prompt_budget(...)

    if budget.pressure < 0.70:
        return PreparedInference(messages, tools, profile)

    if MANAGER.state.context_size < profile.context_size:
        target = choose_context_window(
            required=budget.required_context,
            cap=profile.context_size,
        )

        await MANAGER.apply_context(
            settings,
            target,
            allow_shrink=False,
        )

        budget = await calculate_prompt_budget(...)
        if budget.pressure < 0.85:
            return PreparedInference(messages, tools, profile)

    raise ModelCapacityExceeded(budget)
```

## 6.6 Context growth tiers

Keep existing practical tiers unless a model/backend supports another verified size:

```text
8K -> 16K -> 32K
```

Rules:

- do not shrink mid-turn;
- expand before sending a request that is already near the active limit;
- respect actual server context, not just profile metadata;
- reserve output tokens before deciding the prompt fits.

## 6.7 Detect context overflow errors

Add one shared detector.

```python
def is_context_overflow(exc: Exception) -> bool:
    text = str(exc).lower()

    markers = (
        "context size has been exceeded",
        "context length exceeded",
        "maximum context length",
        "too many tokens",
        "prompt is too long",
    )

    return any(marker in text for marker in markers)
```

## 6.8 Automatic recovery flow

When a context error occurs:

```text
1. Do not mark task failed.
2. Compact older history.
3. Recalculate prompt budget.
4. Expand active context if possible.
5. Retry the same inference turn.
6. If the current model cannot satisfy required context/capability:
      escalate to another model.
7. Retry on the stronger model.
8. Limit retries to prevent loops.
9. Only surface failure after recovery paths are exhausted.
```

Suggested maximum:

```text
context-only retry: 1
model escalation retry: 1
absolute inference recovery attempts per turn: 2
```

## 6.9 Agent-loop pattern

```python
except APIStatusError as exc:
    if is_context_overflow(exc):
        recovered = await self._recover_context_pressure(
            task_id=task_id,
            messages=messages,
            working=working,
            profile=profile,
            settings=settings,
        )

        if recovered:
            continue

    await fail_task(...)
```

---

# 7. Work package E — Ornith 9B becomes the orchestrator/router

## 7.1 Intent

Ornith 1.5 9B should be optimized for:

- intent classification;
- task classification;
- deciding whether tools are required;
- selecting workers/models;
- detecting vision requirements;
- deciding whether a stronger model is required;
- basic short answers when confidence/capability is sufficient.

It should not be expected to answer arbitrary complex reasoning, architecture, coding, long-context, or deep analysis requests simply because it is the currently loaded model.

## 7.2 Jarvis is the orchestration layer

Core principle:

> The currently loaded model is not Jarvis. Jarvis is the orchestration layer that selects models and workers.

The same conversation may use:

- Ornith for routing;
- Qwen 9B or equivalent for ordinary answers;
- a reasoning model for complex questions;
- a 27B/expert model for difficult work;
- a specialist for coding/security/vision;
- another model for verification.

The user should still experience one Jarvis conversation.

## 7.3 Extend runtime profiles with role and answer tier

Suggested fields:

```python
@dataclass
class RuntimeProfile:
    ...
    runtime_role: str = "general"
    answer_tier: int = 2
```

Roles:

```text
orchestrator
general
reasoner
expert
specialist
```

Answer tiers:

```text
0 = route only, no direct owner answer
1 = basic/trivial answers
2 = ordinary general answers
3 = complex/reasoning answers
4 = expert/high-consequence/very difficult work
```

Suggested defaults:

```text
Ornith 1.5 9B / bootstrap:
    runtime_role = orchestrator
    answer_tier = 1

General local 9B:
    runtime_role = general
    answer_tier = 2

Quality/reasoning model:
    runtime_role = reasoner
    answer_tier = 3

27B expert:
    runtime_role = expert
    answer_tier = 4
```

Ornith 35B may be evaluated separately as a Senior Worker/Leader candidate; do not automatically inherit the 9B restriction.

## 7.4 Router input should be small

Do not send the full conversation to Ornith merely to decide routing.

Use a routing envelope such as:

```json
{
  "latest_user_message": "...",
  "conversation_summary": "...",
  "recent_turn_count": 4,
  "current_model": "ornith_9b",
  "available_models": [
    {
      "id": "qwen38_9b",
      "role": "general",
      "answer_tier": 2,
      "context": 32768
    },
    {
      "id": "expert",
      "role": "expert",
      "answer_tier": 4,
      "context": 32768
    }
  ],
  "tools_available": true,
  "vision_requested": false
}
```

Expected structured router output:

```json
{
  "action": "switch_model",
  "required_answer_tier": 3,
  "required_capabilities": ["reasoning"],
  "preferred_context": 32768,
  "reason": "The request needs broader reasoning than the orchestration model should perform."
}
```

Allowed actions:

```text
answer_basic
use_tool
switch_model
delegate
ask_clarification
```

## 7.5 Capability gates happen before scoring

Current weighted routing should not allow a warm lightweight model to win merely because it is already loaded.

Extend preferences:

```python
@dataclass
class AgentRoutingPreferences:
    ...
    minimum_answer_tier: int = 0
    required_runtime_role: str | None = None
```

Filter first:

```python
if profile.answer_tier < prefs.minimum_answer_tier:
    continue

if (
    prefs.required_runtime_role
    and profile.runtime_role != prefs.required_runtime_role
):
    continue
```

Only then score eligible candidates for latency, cost, warmth, privacy, load, specialization, etc.

Warm-model bonus must never override a hard capability requirement.

## 7.6 User-visible model switching

When Jarvis determines that Ornith is insufficient, it should state this naturally and continue automatically.

Canonical wording:

```text
I'm switching to a more capable model so I can answer that properly.
```

Alternative wording may be shorter, but must communicate that Jarvis is escalating rather than failing.

No Continue button should be required.

## 7.7 Model-switch event

Example:

```python
await BUS.publish(
    task_id,
    "model_switch",
    "Switching model",
    {
        "from": current_profile.name,
        "to": target_profile.name,
        "reason": decision.reason,
        "user_message": (
            "I'm switching to a more capable model so I can answer that properly."
        ),
    },
    stage="model",
)
```

Suggested UI rendering:

```text
Jarvis
I'm switching to a more capable model so I can answer that properly.

ORNITH 1.5 9B
        ↓
QWEN / REASONING MODEL
```

Do not expose internal stack traces or routing score dumps in normal chat.

## 7.8 Model handoff package

A model switch must preserve conversation continuity without copying hidden reasoning.

```python
@dataclass
class ModelHandoff:
    user_request: str
    conversation_summary: str
    recent_turns: list[ChatMessage]
    working_state: str
    relevant_observations: list[str]
    failed_attempts: list[str]
```

Recommended handoff contents:

- current user request verbatim;
- last 6-10 relevant turns verbatim when they fit;
- older conversation as compact summary;
- relevant tool results;
- current task/working state;
- failed approaches needed to avoid repetition;
- no hidden chain-of-thought.

Reuse existing compaction infrastructure where possible.

## 7.9 Do not immediately downgrade mid-turn

Once a user turn escalates:

```python
working.model_escalation_count += 1
working.active_answer_profile = target.name
```

Keep that model for the remainder of the current user turn unless a further specialist handoff is required.

After completion, Jarvis may return to the lightweight orchestrator after an idle timeout.

Suggested behavior:

```text
heavy model idle 60-180 seconds
    -> unload heavy model
    -> restore warm orchestrator
```

The exact timeout should remain configurable.

---

# 8. Work package F — Question complexity classification

The router needs a deterministic baseline so it does not depend only on a small model's self-assessment.

Create a lightweight complexity scorer using both rules and model output.

Example signals:

## Tier 1 — basic

- short factual chat;
- simple UI command;
- simple file lookup;
- simple scheduling intent;
- deterministic tool routing.

Ornith may answer directly.

## Tier 2 — general

- normal explanatory questions;
- moderate comparisons;
- multi-step but straightforward tasks;
- ordinary tool synthesis.

Use a general answer model.

## Tier 3 — complex

- architecture;
- debugging spanning subsystems;
- coding plans;
- long-context synthesis;
- reasoning across multiple sources;
- ambiguous technical diagnosis;
- important recommendations requiring qualification.

Use a reasoning-capable model.

## Tier 4 — expert

- complex software architecture changes;
- repeated failure recovery;
- difficult security analysis;
- large refactors;
- tasks explicitly requesting highest quality/expert model;
- tasks where lower-tier model confidence is low after an attempted plan.

Use an expert/leader model or specialist.

The router may override upward. It should almost never override downward when hard rules require a tier.

---

# 9. Work package G — Example screenshot regression scenario

Input:

```text
Can you tell me about your current capabilities, e.g. how much of it is fully implemented and working and how much is only half baked?
```

Expected flow:

```text
Understanding request
Routing with Ornith 1.5 9B

I'm switching to a more capable model so I can answer that properly.

Loading general/reasoning model
Inspecting current Jarvis implementation if required
Answering...
```

Forbidden flow:

```text
Context 16384
Inference failed
Context size has been exceeded
```

If answering accurately requires inspecting Jarvis source/status, the router should select a system-inspection/tool path rather than allowing Ornith to hallucinate its own implementation state.

Example router output:

```json
{
  "action": "use_tool",
  "required_answer_tier": 2,
  "task_class": "system-inspection",
  "reason": "The question asks about current implementation state and should be grounded in repository/runtime evidence."
}
```

---

# 10. Error-handling requirements

## TTS

Never hide:

- package missing;
- model assets missing;
- pipeline initialization error;
- invalid speaker reference;
- empty waveform;
- browser playback failure.

## Inference

Classify at minimum:

```text
context_overflow       -> recover
server_unreachable     -> retry/recover according to policy
model_missing          -> reroute if another eligible model exists
model_load_failed      -> reroute if possible
output_empty           -> retry once, then reroute if appropriate
timeout                -> recover or reroute according to task state
unrecoverable_error    -> fail visibly
```

A recoverable error must not immediately set the task to `failed`.

---

# 11. Observability requirements

Add structured events/logging for:

```text
voice_runtime_probe
voice_preview_requested
voice_preview_succeeded
voice_preview_failed
model_route_decision
model_switch_started
model_switch_completed
context_pressure_detected
context_compaction_started
context_expanded
context_retry
context_recovery_failed
```

Recommended model routing log fields:

```json
{
  "request_id": "...",
  "from_model": "ornith_9b",
  "to_model": "qwen38_9b",
  "required_answer_tier": 3,
  "required_context": 24500,
  "active_context": 16384,
  "reason": "complex reasoning + context pressure",
  "automatic": true
}
```

Recommended TTS log fields:

```json
{
  "profile_id": "butler_original_v1",
  "requested_engine": "kokoro",
  "actual_engine": "kokoro",
  "model_id": "kokoro-82m",
  "speaker_ref": "bm_george",
  "verified": true,
  "latency_ms": 412
}
```

---

# 12. Test requirements

The release is not complete unless these regressions are covered.

## TTS tests

1. Kokoro selected + healthy -> actual engine returned is `kokoro`.
2. Kokoro selected + broken -> synthesis fails explicitly.
3. Broken Kokoro never silently returns SAPI audio.
4. Kokoro status only reports `ready=true` after successful synthesis verification.
5. Each enabled Kokoro profile can synthesize a valid WAV preview.
6. Preview headers identify actual engine/profile/model/voice.
7. Backend preview error reaches frontend unchanged enough to be actionable.
8. Browser playback failure is reported as failure.
9. Installing/repairing Kokoro refreshes runtime health.
10. Ordinary speech never starts an implicit package install.

## Settings tests

11. Legacy `/settings/voice` route redirects to Appearance & Voice.
12. Legacy appearance route redirects correctly.
13. Phone Pairing is reachable under Settings.
14. Existing companion-pairing deep links remain functional.
15. Last-selected submenu persistence still works.

## Model-routing tests

16. Ornith 9B cannot directly satisfy a request with `minimum_answer_tier >= 2`.
17. Warm-model bonus cannot bypass the tier gate.
18. A trivial request may remain on Ornith.
19. A complex architecture question escalates automatically.
20. Model switch emits a visible user-facing event.
21. Model switch preserves current user request and recent conversation.
22. Hidden reasoning is not transferred between models.
23. The escalated model stays active for the remainder of the current user turn.

## Context tests

24. 16K pressure expands to 32K when profile/server allow it.
25. Compaction occurs before unnecessary model failure.
26. A simulated 400 `Context size has been exceeded` is treated as recoverable.
27. One context error does not immediately mark the task failed.
28. Same model turn is retried after successful recovery.
29. If the current model cannot satisfy required context, routing escalates to an eligible model.
30. Recovery retry limits prevent infinite loops.
31. Tool schemas are included in prompt budgeting.
32. Completion/output token reserve is included in prompt budgeting.

## End-to-end regression

33. Reproduce the reported screenshot scenario with only a few visible messages and verify that Jarvis either answers or visibly switches models; it must not fail with a raw context-overflow message.
34. Select `butler_original_v1`, press Preview, and verify that the WAV is generated by Kokoro and audibly plays.

---

# 13. Suggested implementation order

The architect should split the release into bounded work packages/PRs.

## PR 1 — Model roles and routing contract

Owner: strongest architecture model.  
Recommended: Grok 4.6 / strongest available equivalent.

Deliver:

- `runtime_role` and `answer_tier`;
- complexity/tier contract;
- capability gate before routing score;
- structured router result;
- unit tests.

No UI changes yet.

## PR 2 — Context preflight and recovery

Owner: strongest reasoning/coding model.  
Recommended: Grok 4.6 or Grok 4.5.

Deliver:

- canonical prompt-budget implementation;
- consistent token estimation;
- context-pressure detection;
- context expansion;
- 400 overflow classification;
- retry/recovery;
- model escalation hook;
- tests.

## PR 3 — Visible model switching + handoff continuity

Owner: strong coding model.  
Recommended: Composer 2.5, reviewed by Grok 4.5/4.6.

Deliver:

- model-switch event;
- user-facing status message;
- handoff package;
- no Continue button requirement;
- same conversation continuity;
- idle downgrade policy.

## PR 4 — Kokoro runtime correction

Owner: strong full-stack/backend model.  
Recommended: Grok 4.5/4.6 or equivalent.

Deliver:

- pinned validated Kokoro runtime;
- `KokoroAdapter`;
- explicit runtime state;
- no install-during-speech;
- synthesis health probe;
- status API;
- tests.

## PR 5 — Voice preview

Owner: Composer 2.5.

Deliver:

- canonical preview behavior;
- useful backend error propagation;
- actual playback failure handling;
- exact engine/profile metadata;
- frontend tests.

## PR 6 — Settings reorganization

Owner: Composer 2.5 or lower-cost competent coding model.

Deliver:

- Appearance & Voice;
- Phone Pairing;
- Models & Inference;
- Network & Swarm;
- Integrations;
- Advanced;
- redirects;
- navigation tests.

## PR 7 — Integrated regression pass

Owner: separate reviewer.  
Recommended: Grok 4.6 / strongest available reviewer.

Review:

- no hidden SAPI fallback;
- no raw context failures in recoverable cases;
- no routing loops;
- Ornith remains lightweight;
- model switching preserves continuity;
- all compatibility routes still work;
- release installer contains the validated TTS runtime.

---

# 14. Definition of done

Jarvis 1.4 is ready when all of the following are true:

- Selecting a Kokoro profile demonstrably produces Kokoro audio.
- Settings shows which engine/model/voice is actually active.
- Voice preview plays for usable profiles and reports concrete errors for broken profiles.
- SAPI is explicit and never masquerades as Kokoro.
- Voice/speech lives under Appearance & Voice.
- Phone Pairing lives under Settings.
- Ornith 9B primarily routes/orchestrates and only answers basic requests directly.
- Complex requests automatically move to an appropriately capable model.
- Jarvis tells the user when it is switching models.
- Switching models does not require resubmitting the question or pressing Continue.
- Context pressure is handled before inference whenever possible.
- A context overflow triggers compaction/context expansion/model escalation rather than immediate task failure.
- The reported `Context size has been exceeded` screenshot scenario passes as an automated regression test.
- The release contains tests that prove the above behavior.

---

# 15. Architectural principle for future work

This release should establish a rule for all later Jarvis development:

> Jarvis is not a single model. Jarvis is the persistent orchestration, memory, routing, tooling, persona, and UI layer that selects the right model or worker for each part of the task.

The lightweight always-on model should optimize for responsiveness and correct delegation. Stronger models should be invoked only when the task justifies them. The user should experience this as one continuous assistant rather than manually managing model limitations.
