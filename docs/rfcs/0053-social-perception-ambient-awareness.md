# RFC-0053: Social perception and ambient awareness pipeline

**Status:** accepted  
**Queue item:** P1 — Social Perception / ambient awareness  
**Author:** ChatGPT design session  
**Date:** 2026-09-08

## Problem

Jarvis can listen, reason, speak, operate tools, and present a visual presence, but it has no durable abstraction for *seeing the local environment*. A camera-aware Jarvis should be able to notice mundane, useful, or humorous facts such as a person entering the room, a mug appearing, lighting changing, or the owner looking unusually dishevelled, without streaming video to an LLM, storing raw images, or producing repetitive/creepy commentary.

The key design requirement is to separate **high-frequency tracking** from **low-frequency semantic perception**. Face/head tracking is a rendering/input concern; semantic perception is an event-producing subsystem. This RFC defines the latter and the privacy boundary around it.

## Decision

Add a local-first `social_perception` subsystem that converts ephemeral camera frames or future sensor inputs into **structured observations**, then applies deterministic confidence, novelty, duplication and cooldown policy before making those observations available to Jarvis dialogue/orchestration.

This RFC deliberately does **not** implement face identity recognition, personality wording, or TTS. Those are separate RFCs so perception does not become coupled to biometrics or a specific voice.

### Architecture

```text
camera / sensor source
        |
        v
frame sampler (ephemeral)
        |
        +--> fast tracker (presence/head/gaze; UI concern)
        |
        v
semantic observer (small local VLM, sampled)
        |
        v
StructuredObservation
        |
        v
sanitizer + confidence gate
        |
        v
novelty / duplicate / cooldown policy
        |
        +--> transient observation feed
        +--> optional non-image baseline facts
        +--> social-comment candidate event
```

### Hard privacy boundary

1. Raw camera frames are transient inputs only.
2. Raw frames are not written to disk, logs, task history, memory, telemetry, database rows, prompts, or crash dumps.
3. Semantic observation records contain only bounded textual/enumerated facts and confidence scores.
4. Camera/VLM processing defaults to local execution.
5. Cloud escalation for camera frames is forbidden by default and cannot be inferred from general `BEST RESULT`/cloud routing settings.
6. Enabling perception or camera access is an owner action; an LLM/tool cannot silently enable it.
7. Disabling perception must stop frame capture promptly and clear queued frames.
8. The baseline store must contain no images and no raw face embeddings; identity embeddings belong only to RFC-0054.

### Structured observation contract

The semantic observer must emit a validated schema rather than prose. Initial canonical shape:

```json
{
  "source": "camera.frontend",
  "observed_at": "2026-09-08T12:00:00Z",
  "person_present": true,
  "person_count": 1,
  "appearance": {
    "hair_state": "dishevelled",
    "glasses": false,
    "clothing_summary": "dark T-shirt"
  },
  "activity": "sitting_at_computer",
  "objects": ["mug"],
  "environment": {
    "lighting": "dim"
  },
  "confidence": 0.86,
  "attributes": {
    "hair_state": 0.86,
    "activity": 0.78,
    "lighting": 0.93
  }
}
```

Free-form fields must be short and length-limited. Unknown values are omitted rather than guessed. The schema must never ask the observer to infer protected/sensitive traits, health conditions, intoxication, criminality, emotional diagnoses, attractiveness, political/religious identity, or other high-risk personal conclusions from appearance.

### Observation categories

Initial allowlisted semantic categories:

- person presence/count;
- coarse posture/activity: sitting, standing, walking, working at computer, reading, eating/drinking;
- visible objects relevant to the immediate room/task;
- coarse clothing description;
- glasses/headwear;
- coarse hair state such as tidy/dishevelled/wet only when confidence is sufficient;
- room lighting state;
- door/opening or obvious room-state change when a configured source can support it;
- interaction cues such as looking toward the display/camera, where produced by a tracker rather than guessed by a VLM.

Explicitly disallowed inference categories include race/ethnicity, religion, political belief, sexual orientation, medical/mental state, disability inference, pregnancy, financial status, criminal propensity, or precise age estimation.

### Observer runtime interface

Define a provider-neutral interface so the policy layer is model-independent:

```py
class SemanticObserver(Protocol):
    async def observe(self, frame: EphemeralFrame, context: ObserverContext) -> StructuredObservation: ...
```

The first production candidate should be benchmarked rather than hardcoded. Candidate local VLMs include SmolVLM2 500M for low-footprint observation and SmolVLM2 2.2B for quality mode. The policy/API implementation must work with a fake observer and structured observations before any model dependency is added.

### Sampling policy

Semantic perception is intentionally sparse:

- idle room: 0.1–0.25 fps;
- active interaction: up to 0.5–1 fps;
- event-triggered burst: short bounded burst when fast tracking detects a new person/large scene change;
- never run semantic VLM inference at display frame rate;
- pause when the application is hidden unless an explicitly configured ambient-monitoring mode owns the camera;
- resource governor may reduce/stop semantic sampling before it affects primary inference tasks.

The observer should prefer a new sample when scene-change magnitude, person-presence transition, or elapsed-time threshold warrants it.

### Social perception settings

Add a dedicated settings object, defaulting to disabled:

```py
class SocialPerceptionSettings(BaseModel):
    enabled: bool = False
    semantic_observer: str = "none"
    sample_interval_seconds: float = 5.0
    min_confidence: float = 0.75
    novelty_threshold: float = 0.35
    comment_cooldown_seconds: int = 900
    duplicate_ttl_seconds: int = 3600
    baseline_enabled: bool = True
    retain_observation_summaries: bool = False
    max_summary_retention_hours: int = 24
```

Limits must be validated. `enabled=False` means no camera-frame semantic processing regardless of configured model.

### Deterministic novelty and duplicate policy

The first implementation must not depend on an LLM to decide whether an observation is new.

For each allowed observation key, compute a stable normalized fingerprint. Examples:

```text
appearance.hair_state=dishevelled
object=mug
activity=sitting_at_computer
environment.lighting=dim
person_presence=true
```

Each fact tracks:

- first seen;
- most recently seen;
- occurrence count;
- last confidence;
- last-commented time;
- current value / prior value where applicable.

A candidate is interesting when:

1. confidence >= configured threshold;
2. it represents a transition or sufficiently novel value;
3. it has not been emitted inside the duplicate TTL;
4. global and category cooldowns allow it;
5. perception is enabled;
6. the fact is on the safe allowlist.

Useful transitions outrank cosmetic ones. Example priority order:

1. person entered/left;
2. environment change relevant to safety/usability;
3. task-related object/activity change;
4. social/casual appearance change.

### Baseline facts

The baseline is a compact statistical summary of ordinary *non-biometric* observations, not a photo album.

Example:

```json
{
  "appearance.hair_state": {"tidy": 0.78, "dishevelled": 0.22},
  "environment.lighting": {"normal": 0.83, "dim": 0.17},
  "object.mug": {"presence_rate": 0.61}
}
```

Rules:

- require multiple observations before declaring a baseline;
- decay old counts;
- do not persist raw frames;
- do not include identity embeddings;
- allow owner to reset baseline independently from Jarvis memory;
- baseline comparisons produce `novelty_score`, not automatic commentary text.

### Candidate-event contract

Policy output is a machine-readable event:

```json
{
  "kind": "social_observation_candidate",
  "category": "appearance",
  "fact": "appearance.hair_state",
  "value": "dishevelled",
  "confidence": 0.86,
  "novelty": 0.71,
  "priority": "casual",
  "safe_to_comment": true,
  "reason": "changed_from_baseline",
  "observed_at": "..."
}
```

RFC-0055 decides whether/how to turn that candidate into dialogue. This subsystem never writes the joke itself.

### API surface

Owner-authenticated local endpoints:

- `GET /api/perception/status` — enabled/config state, observer availability, last observation timestamp, counts; no frame data.
- `POST /api/perception/observations` — accept a structured observation from an approved local frontend/runtime adapter; validate and evaluate it.
- `GET /api/perception/recent` — bounded recent structured summaries only when summary retention is enabled.
- `POST /api/perception/baseline/reset` — clear non-biometric baseline.
- `POST /api/perception/state/reset` — clear cooldown/fingerprint state.

The initial implementation may expose only the structured-observation ingestion/status/reset endpoints; raw image upload is specifically out of scope.

### Security model

- All perception endpoints use normal owner authentication.
- Guest portals cannot access perception state.
- Perception is not a general-purpose surveillance API.
- The observation-ingest endpoint does not accept image bytes in this RFC.
- Inputs are schema-validated and size-limited.
- The subsystem must not create new filesystem/network tool permissions.
- Logs contain policy decisions and category/fingerprint IDs, not raw camera frames.

### Resource policy

When local GPU/CPU resources are constrained:

1. primary user task inference wins;
2. voice/STT wins over ambient semantic perception;
3. fast gaze/presence tracking may continue if cheap;
4. semantic observation rate is reduced or paused;
5. no unbounded queue of camera frames is allowed (latest-frame wins).

## Acceptance criteria

- [ ] `SocialPerceptionSettings` exists with safe defaults and validated ranges.
- [ ] Structured observation models reject unsupported/sensitive inference fields and oversized free text.
- [ ] A deterministic policy accepts/rejects facts based on confidence, novelty, duplicate TTL and cooldown.
- [ ] Repeated identical observations do not repeatedly produce candidates.
- [ ] A changed observation can produce a candidate after passing thresholds.
- [ ] Candidate events contain no raw image/frame data.
- [ ] Baseline state stores only aggregate non-image facts and can be reset.
- [ ] Perception defaults to disabled.
- [ ] Owner-authenticated status/structured-ingest/reset API exists.
- [ ] No endpoint in this RFC accepts raw image bytes.
- [ ] Unit tests cover confidence rejection, duplicate suppression, cooldown, changed-state novelty, reset and schema limits.
- [ ] `python3 -m pytest` passes.

## First implementation ticket (this session)

Implement the **privacy-safe substrate** only:

1. settings model + settings API fields;
2. structured observation/candidate models;
3. in-memory/state-file novelty + cooldown policy with non-image aggregates only;
4. authenticated perception status/structured-ingest/reset API;
5. tests.

Do not add MediaPipe, camera capture, SmolVLM2 weights/runtime, identity recognition, dialogue generation, or TTS in this first ticket.

## Likely files

| Area | Paths |
| --- | --- |
| Config | `backend/app/config.py`, `backend/app/api/settings.py` |
| Perception | `backend/app/perception/models.py`, `backend/app/perception/policy.py`, `backend/app/perception/store.py` |
| API | `backend/app/api/perception.py`, `backend/app/main.py` |
| Tests | `tests/test_social_perception.py` |
| Future frontend adapter | `frontend/src/perception/**` |

## Out of scope

- Face identity recognition and household enrollment — RFC-0054.
- Social wording, sarcasm, interruption rules and personal-comment preference — RFC-0055.
- Expressive TTS / original British-butler voice runtime — RFC-0056.
- Humanoid renderer/gaze animation.
- General security-camera recording, NVR functionality, burglary detection or remote surveillance.

## Notes / implementation references

- MediaPipe Face Landmarker can provide high-frequency landmarks/blendshapes/transforms for the separate presence-tracking path; semantic observation should remain lower frequency.
- Hugging Face SmolVLM2 publishes 256M, 500M and 2.2B video-capable models; benchmark 500M vs 2.2B before selecting a default observer.
- The production observer model must have a license compatible with Jarvis distribution/commercial packaging.
