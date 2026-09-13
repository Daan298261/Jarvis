# Jarvis Household Vision — Always-On Camera, Context & Chore Guardian Specification

Status: **separate specification**. Not implemented. Architect-owned.

This specification extends `HOME_IOT.md` and `SWARM_ARCHITECTURE.md` with an always-on local vision subsystem that can observe multiple household camera streams, maintain lightweight scene state, infer routine context, and proactively remind the user about configurable chores or household tasks.

The intended first deployment is a separate low-end laptop with approximately **8 GB RAM**, running continuously as a Jarvis Node. The design must remain useful on stronger hardware and across multiple future camera/vision nodes.

The subsystem is called **Household Vision** in product/UI language. The primary long-running worker/service is referred to as **Vision Sentinel** in this document.

---

## 1. Product goal

Jarvis should be able to understand enough of the physical state of the home to assist proactively rather than only react to commands.

Example:

1. Jarvis observes that the user appears to be starting the bedtime routine.
2. The current household rules say the dining table and kitchen counter should be clear before bed.
3. Vision Sentinel determines that one or both areas are still not in their configured acceptable state.
4. Jarvis reminds the user through the selected surface, for example local voice, phone, or portal.
5. Jarvis continues reminding according to the configured escalation policy until:
   - the camera evidence verifies completion;
   - the user explicitly snoozes or skips the task;
   - the routine/trigger expires; or
   - a configured suppression condition becomes true.
6. Once the visual state is verified, Jarvis marks the chore complete automatically and stops reminders.

The system must support arbitrary future rules rather than hard-coding bedtime or kitchen cleaning.

---

## 2. Design principles

1. **Local-first.** Raw household video stays on user-controlled hardware by default.
2. **Always available, not always expensive.** Vision services remain resident, but expensive semantic inference is event-driven and rate-limited.
3. **Multi-camera by design.** A rule may depend on one camera, several cameras, or a logical zone seen by multiple cameras.
4. **Temporal state, not single-frame guesses.** Completion and intent require evidence across time.
5. **Configurable behavior.** Chores, acceptable states, triggers, reminder frequency, escalation, quiet periods, and verification confidence are user-defined.
6. **Automatic verification.** A reminder should normally clear because Jarvis observed the result, not because the user had to tick a box.
7. **Swarm-native.** The camera computer is a normal Jarvis Node with capabilities, telemetry, roles, and resource budgets.
8. **Graceful degradation.** If one camera or the semantic model is unavailable, unaffected rules continue to operate.
9. **No mandatory cloud vision.** Cloud VLMs may be optional providers under the normal Jarvis model/router policy, but Household Vision must work fully locally.
10. **Low-maintenance.** Installation should discover supported streams and propose useful zones/rules rather than require extensive manual computer-vision configuration.

---

## 3. Scope

### 3.1 In scope

- Multiple simultaneous camera streams.
- RTSP/ONVIF IP cameras where available.
- USB/webcam devices.
- Home Assistant camera entities and local snapshots where available.
- MJPEG/local HTTP streams where practical.
- Persistent small local vision model(s).
- Low-rate continuous visual scene monitoring.
- Motion/activity-driven burst analysis.
- Object/scene-state detection.
- Logical household zones such as `kitchen.counter`, `dining.table`, `hallway`, `front_door`, `bedroom.entry`.
- Temporal world-state memory.
- Configurable routines and chore rules.
- Routine/intent inference such as `bedtime_candidate`.
- Reminder, escalation, snooze, skip, and suppression policies.
- Automatic completion verification.
- Voice/phone/portal/Decision Inbox integration.
- Node health, load, camera health, and inference telemetry.

### 3.2 Explicitly not required for V1

- Continuous recording/NVR replacement.
- Full-resolution 24/7 video understanding.
- Cloud surveillance services.
- Mandatory facial recognition.
- Biometric identity as a prerequisite for reminders.
- Perfect natural-language understanding of every possible physical activity.
- Autonomous physical manipulation of household objects.

Household Vision may coexist with an NVR, Home Assistant, Frigate, Blue Iris, or another camera system, but should not require one unless a later implementation decision makes a particular adapter optional.

---

## 4. Swarm role and node placement

Household Vision must use the role/capability model from `SWARM_ARCHITECTURE.md`.

A camera laptop is a **Node**, not a special hard-coded appliance.

Recommended advertised capabilities:

```text
vision.stream.ingest
vision.motion
vision.object_detect
vision.scene_state
vision.temporal_state
vision.vlm
vision.rule_eval
vision.camera_health
```

Recommended product-facing role:

```text
HOUSEHOLD_VISION
```

The role may be assigned using the normal role policy:

- `AUTO`
- `PREFERRED`
- `FORCED`
- `AVOID`
- `DISABLED`

For the intended dedicated 8 GB laptop deployment, the user should be able to set `HOUSEHOLD_VISION = FORCED` so Jarvis keeps the service there unless the node is unavailable.

The node may simultaneously hold another lightweight role if its resource budget allows it. Household Vision must reserve sufficient CPU/RAM capacity to avoid being evicted by unrelated workloads when configured as always-on.

---

## 5. Runtime architecture

```text
Camera streams
   │
   ├─ RTSP / ONVIF
   ├─ USB camera
   ├─ Home Assistant
   └─ local HTTP/MJPEG
   │
   ▼
Stream Registry + Health Monitor
   │
   ▼
Frame Sampler / Motion Gate
   │
   ├─────────────── low-cost path ─────────────────┐
   │                                               │
   ▼                                               ▼
Fast Perception                               Zone State Cache
(detector / motion /                          + Temporal History
basic embeddings)                                  │
   │                                               │
   └──────────── event / ambiguity ────────────────┘
                           │
                           ▼
                 Persistent Micro-VLM
                 semantic snapshot analysis
                           │
                           ▼
                 Household World State
                           │
               ┌───────────┴───────────┐
               ▼                       ▼
        Routine/Intent Engine       Chore Rule Engine
               │                       │
               └───────────┬───────────┘
                           ▼
                  Reminder Controller
                           │
                 Voice / Phone / Portal
                           │
                           ▼
                  Verification Loop
```

The important constraint is that **full semantic VLM inference is not run on every frame**.

The model remains loaded and warm, while sampling, motion gating, object detection, change detection, and cached scene state prevent unnecessary expensive inference.

---

## 6. Multi-stream ingestion

Each stream must have a canonical camera record:

```yaml
camera_id: kitchen_wide
name: Kitchen wide camera
source_type: rtsp
source_uri_secret_ref: secrets://cameras/kitchen_wide
room: kitchen
enabled: true
priority: normal
idle_sample_fps: 0.2
active_sample_fps: 1.5
max_analysis_fps: 2.0
zones:
  - kitchen.counter
  - kitchen.sink
  - kitchen.floor
```

Requirements:

- Streams reconnect automatically with exponential backoff.
- Camera credentials never enter git, chat, or normal logs.
- Decode at the minimum resolution needed for the current task.
- Allow separate analysis and archival streams when a camera exposes both.
- Maintain per-camera latency, dropped-frame, reconnect, and last-good-frame telemetry.
- If two cameras see the same logical zone, Jarvis may fuse evidence rather than duplicate the zone.
- Rules depend on logical zones, not camera IDs wherever possible. This allows cameras to be moved/replaced without rewriting every chore.

---

## 7. Persistent small-model strategy

The dedicated vision node must keep its primary small vision model loaded continuously while Household Vision is enabled.

### 7.1 Baseline model class

The implementation must use a model-provider interface rather than hard-code one checkpoint.

Target baseline for an 8 GB RAM laptop:

- approximately **0.5B–2.5B multimodal/VLM class** where practical;
- quantized local inference, preferably 4-bit or similarly memory-efficient;
- configurable image resolution;
- single-image or short multi-image semantic reasoning;
- model resident after startup;
- no repeated model load/unload between household events.

Larger models are optional when hardware permits.

The exact default checkpoint may change as local VLMs improve. The architecture must therefore expose:

```text
VisionModelProvider
  ├─ load()
  ├─ warmup()
  ├─ analyze_snapshot()
  ├─ compare_snapshots()
  ├─ describe_zone_state()
  ├─ health()
  └─ unload()
```

### 7.2 Fast perception tier

A separate very lightweight detector/change model SHOULD handle frequent work such as:

- person present/not present;
- motion/change score;
- coarse object presence;
- door/open-state where detectable;
- table/counter clutter heuristics;
- scene embeddings for change detection.

This can be an ONNX/OpenVINO/DirectML/CUDA-compatible detector depending on the node.

The fast tier can run much more frequently than the semantic model.

### 7.3 Semantic VLM tier

The persistent micro-VLM is called when:

- a tracked zone changes materially;
- the cheap detector is uncertain;
- a rule's trigger approaches;
- a chore needs semantic verification;
- a routine/intent state changes;
- the user asks a direct visual question;
- periodic confidence refresh is due.

Example semantic tasks:

- "Is the dining table clear enough to be considered cleaned?"
- "Are there dirty dishes visible in the sink or on the counter?"
- "Does this room appear occupied?"
- "Compared with the previous accepted-clean snapshot, is the counter materially more cluttered?"

The model output must be structured, not free-form prose only.

Example:

```json
{
  "zone": "dining.table",
  "state": "needs_attention",
  "confidence": 0.91,
  "observations": ["plates", "mug", "paper"],
  "changed_since_last": true
}
```

---

## 8. Resource target for the 8 GB laptop

The first implementation should aim for the following operating envelope on an 8 GB system:

```text
OS + base services:           leave >= 2 GB practical headroom
Household Vision target RAM:  <= 5.5 GB steady state
Normal CPU target:            <= 35% average over 15 min
Burst CPU:                    configurable up to node budget
Idle GPU/iGPU:                no requirement
Disk writes:                  event/state oriented, not continuous video
```

These are targets, not hard guarantees across every model/backend.

Resource controls must integrate with the swarm's normal host resource budget. When pressure occurs, degradation order should be:

1. lower active analysis FPS;
2. lower idle analysis FPS;
3. reduce image resolution;
4. defer non-urgent semantic refreshes;
5. disable low-priority cameras temporarily;
6. migrate eligible semantic work to another node if policy allows;
7. preserve trigger evaluation and critical configured rules as long as possible.

The model should remain resident unless memory pressure makes continued operation impossible.

---

## 9. Household world-state model

Jarvis must not reason directly from isolated image descriptions. Vision Sentinel maintains a compact world-state database.

Example:

```yaml
zone: dining.table
state: needs_attention
confidence: 0.92
first_seen_at: 2026-09-09T20:11:32+02:00
last_seen_at: 2026-09-09T23:18:05+02:00
stable_for_seconds: 10953
observations:
  plates: 2
  cups: 1
  papers: true
source_cameras:
  - dining_wide
verification_samples: 4
```

State must be temporal and confidence-weighted.

A visual state is considered stable only after configurable repeated evidence, for example:

```text
3 agreeing checks within 10 seconds
minimum confidence 0.80
```

World state is exposed to the Jarvis event bus and normal agent context as structured facts rather than raw video wherever possible.

---

## 10. Routine and intent detection

Chores may be triggered by explicit schedules or inferred context.

Routine/intent states include examples such as:

```text
user_arrived_home
leaving_home_candidate
meal_finished_candidate
bedtime_candidate
morning_routine_candidate
cleaning_activity
cooking_activity
house_quiet
```

These must be probabilistic states with supporting signals, not irreversible classifications.

Example `bedtime_candidate` signals may include:

- configured local time window;
- sustained movement toward bedroom/bathroom areas;
- living-room occupancy ending;
- lights/TV/device states from Home IoT when available;
- phone charging or presence signals when explicitly integrated;
- user language such as "I'm going to bed";
- historical routine patterns if routine learning is enabled.

No single signal is mandatory.

Example:

```yaml
intent: bedtime_candidate
confidence: 0.84
signals:
  local_time_window: 0.90
  hallway_to_bedroom_transition: 0.82
  living_room_vacated: 0.88
  tv_off: 1.00
```

A rule defines what confidence is sufficient to act.

---

## 11. Chore/rule definition

Rules are data, not application code.

Example:

```yaml
id: bedtime_kitchen_reset
name: Clear kitchen before bed
enabled: true
priority: normal

trigger:
  type: intent
  intent: bedtime_candidate
  min_confidence: 0.75
  active_window: "21:00-02:30"

conditions:
  all:
    - household.user_home == true
  any:
    - zone.kitchen.counter.state == needs_attention
    - zone.kitchen.sink.state == needs_attention
    - zone.dining.table.state == needs_attention

reminder:
  channels: [voice, phone]
  initial_delay_seconds: 0
  repeat_seconds: [120, 300, 600]
  then_repeat_seconds: 600
  style: persistent
  max_duration_minutes: 90

verification:
  required_zones:
    - kitchen.counter
    - kitchen.sink
    - dining.table
  pass_state: acceptable
  min_confidence: 0.82
  samples_required: 3
  sample_window_seconds: 15

overrides:
  allow_snooze: true
  allow_skip: true
  skip_phrase_examples:
    - "skip it tonight"
    - "leave it for tomorrow"

suppress_when:
  - privacy_mode == true
  - emergency_mode == true
  - guests_sleeping == true
```

Rules must be editable through the future Jarvis Settings/UI and may also be authored from natural language.

Example user instruction:

> Every night when it looks like I'm going to bed, keep reminding me until the dining table and kitchen counter are clear.

Jarvis should translate that into a draft rule, show the important behavior in human-readable form, and store the structured rule.

---

## 12. Reminder controller and "pester until done"

Reminder persistence is configurable per rule.

Supported modes:

- `once`
- `gentle`
- `persistent`
- `critical`

`persistent` is appropriate for chores the user explicitly wants Jarvis to keep surfacing.

Behavior:

1. Trigger becomes active.
2. Rule engine checks current visual state.
3. If already acceptable, do nothing.
4. If action is needed, issue the first reminder.
5. Begin verification loop.
6. If not complete, repeat according to policy.
7. If activity consistent with doing the chore is detected, optionally delay the next reminder while work is in progress.
8. Stop immediately when completion is verified or the user uses a valid override.
9. Record the outcome as `completed`, `snoozed`, `skipped`, `expired`, or `unverifiable`.

Voice examples should be concise and state-specific:

```text
"The table still needs clearing before bed."
"The table is done; there are still dishes on the kitchen counter."
"Kitchen reset complete."
```

Jarvis should avoid repeating an identical long message every cycle.

---

## 13. Automatic completion verification

Completion must be based on evidence over time.

For each chore, verification can use:

- object absence/presence;
- semantic state from VLM;
- comparison with an accepted reference image/state;
- user-defined zone occupancy;
- IoT state;
- a combination of signals.

A rule must not clear from one ambiguous frame.

Recommended default:

```text
minimum confidence: 0.82
samples required: 3
window: 10-20 seconds
```

If a zone is occluded or camera quality is insufficient, state becomes `unknown`, not falsely `complete`.

The user may always say "mark it done" if visual verification is impossible. The event should then be stored as manual completion rather than visual completion.

---

## 14. Zones and acceptable-state learning

Jarvis must support two ways to define "clean enough" or another desired physical state.

### 14.1 Natural-language criteria

Examples:

```text
Dining table: no plates, cups, loose packaging, or piles of papers.
Kitchen counter: dishes may be drying beside the sink, but food packaging and dirty plates are not acceptable.
```

### 14.2 Reference-state learning

The user may clean a zone and say:

```text
"Jarvis, this is what I mean by a clean table."
```

Jarvis stores:

- semantic target description;
- scene embedding/reference features;
- optional low-resolution reference snapshot if retention is allowed;
- zone geometry;
- confidence thresholds.

The learned target is used as supporting evidence, not a brittle pixel-perfect template.

---

## 15. Person identity and household members

Household Vision should work without mandatory face recognition.

Default V1 behavior may use:

- person present;
- anonymous short-lived track IDs;
- device presence;
- room transitions;
- user interaction with Jarvis;
- configured household context.

Optional household identity may later use local-only recognition/embeddings if explicitly enabled.

If multiple people are present and a rule specifically targets one person, the system should prefer certainty from linked device/voice/explicit context over guessing identity from appearance.

Reminder routing can be configured per household member once identity support exists.

---

## 16. Privacy, retention and security

Household cameras expose unusually sensitive data. Defaults must therefore be conservative while preserving functionality.

Default retention policy:

- raw video: **not retained by Household Vision**;
- analysis frames: memory only, discarded after inference;
- structured scene state/events: retained according to Jarvis event-store policy;
- reference snapshots: opt-in per zone;
- debug/evidence snapshots: opt-in and time-limited;
- cloud upload: off by default.

Controls:

```text
Privacy Mode        -> stop semantic analysis and reminders for selected cameras/zones
Camera Pause        -> stop one camera
Room Privacy        -> suppress selected room(s)
Guest Mode          -> apply configured household/identity restrictions
Retention Debug     -> temporary diagnostic snapshots with explicit expiry
```

Secrets follow existing Jarvis secret-storage rules.

The portal must show when Household Vision is active, which cameras are being analyzed, and whether any visual data retention is enabled.

---

## 17. Home IoT integration

Household Vision extends, but does not replace, `HOME_IOT.md`.

Useful combined signals include:

- lights on/off;
- TV/media state;
- door sensors;
- motion sensors;
- smart plugs;
- appliance state;
- lock/garage state where allowed;
- room climate/occupancy sensors.

Example bedtime logic can become more reliable by combining camera state with lights/TV/device signals.

Vision is treated as another sensor source in Jarvis world state.

Household Vision must not silently disable alarms, cameras, or safety sensors.

---

## 18. Jarvis event/API integration

Recommended event topics:

```text
vision.camera.online
vision.camera.offline
vision.zone.changed
vision.zone.verified
vision.person.entered_zone
vision.person.left_zone
vision.intent.changed
vision.chore.triggered
vision.chore.reminder_sent
vision.chore.completed
vision.chore.snoozed
vision.chore.skipped
vision.model.degraded
```

Recommended internal services:

```text
CameraRegistry
StreamSupervisor
FrameScheduler
FastPerceptionWorker
VisionModelProvider
ZoneStateStore
TemporalStateEngine
RoutineIntentEngine
HouseholdRuleEngine
ReminderController
VisionHealthService
```

Other agents should request structured facts first. Raw frame access is reserved for explicit vision work and must obey retention/privacy policy.

---

## 19. Failure modes

### Camera unavailable

- Mark dependent zones `unknown` after timeout.
- Do not falsely clear chores.
- Continue rules based on unaffected cameras.
- Surface camera failure once according to health policy.

### Model unavailable

- Continue motion/basic detector pipeline.
- Preserve last-known state with timestamp and stale marker.
- Retry model service.
- Optionally route a semantic check to another local eligible node.

### Node unavailable

- Swarm marks HOUSEHOLD_VISION capability unavailable.
- If another capable node is eligible, migrate the role unless it is strictly forced to the offline node.
- On restart, reconstruct live state from cameras rather than assuming previous state remains true.

### Ambiguous visual state

- Return `unknown`/`uncertain`.
- Re-sample at a higher temporary rate.
- Do not nag based solely on a low-confidence ambiguous observation unless the rule explicitly permits it.

### User is actively doing the chore

- Detect relevant activity where possible.
- Enter `in_progress` state.
- Temporarily suppress repeated reminders for the configured work grace interval.
- Resume if the task remains incomplete after activity stops.

---

## 20. Configuration UX

Household Vision should have a dedicated settings surface with:

1. Cameras
2. Rooms/zones
3. Household rules
4. Routines/intents
5. Reminder behavior
6. Privacy/retention
7. Model/runtime
8. Node placement/resource budget
9. Health/debug

A rule card should show plain language first:

```text
BEFORE BED
When Jarvis is >=75% confident you are going to bed:
  Require: dining table + kitchen counter + sink acceptable
  Remind: voice + phone
  Repeat: after 2m, 5m, then every 10m
  Stop: visually verified, skipped, or after 90m
```

Advanced YAML/JSON remains optional.

The user should be able to temporarily disable any rule without deleting it.

---

## 21. Initial implementation phases

### HV-P0 — Skeleton and camera health

- [ ] `HOUSEHOLD_VISION` capability/role definition
- [ ] dedicated service lifecycle
- [ ] camera registry
- [ ] one USB/RTSP stream adapter
- [ ] health/reconnect telemetry
- [ ] low-rate frame sampler
- [ ] no persistent recording

### HV-P1 — Fast perception and zones

- [ ] motion/change detection
- [ ] person presence
- [ ] configurable logical zones
- [ ] temporal zone state store
- [ ] event bus integration
- [ ] multi-camera ingestion

### HV-P2 — Persistent micro-VLM

- [ ] provider abstraction
- [ ] memory-efficient local default
- [ ] model stays loaded/warm
- [ ] structured semantic snapshot output
- [ ] event-driven VLM calls
- [ ] resource-pressure degradation

### HV-P3 — Chore rules and verification

- [ ] structured chore schema
- [ ] natural-language rule creation
- [ ] zone acceptance criteria
- [ ] reference-state learning
- [ ] reminder controller
- [ ] visual completion verification
- [ ] snooze/skip/manual complete

### HV-P4 — Routine/intent engine

- [ ] configurable time/routine signals
- [ ] `bedtime_candidate`
- [ ] multi-signal confidence fusion
- [ ] in-progress activity suppression
- [ ] learnable routine patterns opt-in

### HV-P5 — Productization

- [ ] portal settings/UI
- [ ] voice + phone integration
- [ ] Decision Inbox integration
- [ ] privacy/retention controls
- [ ] health dashboard
- [ ] swarm placement UI
- [ ] installer/onboarding support

---

## 22. Acceptance criteria for first useful release

The feature is considered minimally useful when all of the following work on one local vision node:

- [ ] Runs continuously for 24 hours without manual restart.
- [ ] Uses <= approximately 5.5 GB RAM steady-state on the intended 8 GB reference laptop with its selected baseline models/settings.
- [ ] Connects to at least two simultaneous local camera streams.
- [ ] Keeps a small local vision model loaded rather than loading it for every event.
- [ ] Does not run semantic VLM inference on every video frame.
- [ ] Maintains logical zone state over time.
- [ ] Can distinguish `acceptable`, `needs_attention`, and `unknown` for one configured household zone with useful reliability.
- [ ] Implements one configurable `bedtime_candidate` routine.
- [ ] Triggers a chore reminder only when both routine context and visual state require it.
- [ ] Repeats reminders according to the stored policy.
- [ ] Automatically stops reminders after visual completion is verified.
- [ ] Supports "snooze", "skip tonight", and manual completion.
- [ ] Raw video is not retained by default.
- [ ] Camera/model failures do not crash the wider Jarvis system.
- [ ] Node CPU/RAM usage is visible in the normal swarm UI.

---

## 23. Canonical bedtime example

This is the reference behavior for development and testing, not a permanent hard-coded rule.

```text
23:08 — Kitchen camera: counter = needs_attention (0.91)
23:11 — Dining camera: table = needs_attention (0.94)
23:36 — Living room becomes unoccupied
23:38 — Hallway -> bedroom movement observed
23:38 — Home IoT reports TV off
23:39 — bedtime_candidate confidence = 0.86

RULE bedtime_kitchen_reset fires

Jarvis:
"Before bed: the dining table and kitchen counter still need clearing."

23:41 — user enters kitchen
23:41 — cleaning_activity = true
          reminder grace timer starts
23:45 — table = acceptable (3/3 checks)
23:47 — counter = acceptable (3/3 checks)
23:47 — all required zones verified

Jarvis:
"Kitchen reset complete."

Rule outcome: completed / visually verified
No further reminder is sent.
```

---

## 24. Future extensions

The same architecture can later support:

- "Remind me if I leave the house and the back door looks open."
- "Tell me if packages are still in the hallway tomorrow morning."
- "If I start cooking and the kitchen is already cluttered, remind me to clear workspace first."
- "If the cat food bowls look empty around feeding time, prompt me."
- "If laundry is still on the drying rack after two days, remind me when I walk past it."
- "When I arrive home, tell me which physical household tasks are visibly still open."
- non-camera sensors fused into the same household world model.

These are rule/configuration additions, not architectural redesigns.

---

## 25. Architectural decision

Household Vision is an **always-on, local, swarm-native perception service**. It is not implemented as repeated user-initiated image prompts and not as full-rate VLM video reasoning.

The dedicated node keeps a small model warm, continuously maintains cheap scene state across multiple streams, escalates selected events to semantic vision, and exposes a temporal physical-world model to Jarvis.

That world model powers configurable proactive behaviors such as the bedtime chore guardian while remaining usable on low-resource always-on hardware.