# RFC-0050 — UI v3 Presence Architecture and Selectable Presentation Modes

Status: Accepted  
Priority: P1 / High  
Target: Jarvis desktop frontend (React + Vite + Tauri)  
Depends on: existing HUD v2, NeuralOrb, settings API  
Related: RFC-0051 (Humanoid Runtime), RFC-0052 (Premium Presence Entitlements)

## Summary

Jarvis should evolve from a UI that contains an animated orb into a UI with a first-class presence layer. The presence layer is the visual embodiment of Jarvis and is independent from the surrounding task/chat/system shell.

Users choose the presentation they prefer:

- Classic — current legacy application UI.
- Neural HUD — current HUD with the neural core.
- Humanoid HUD — requested UI v3 mode, implemented by RFC-0051.
- Future renderers may include minimal, accessibility, themed, or third-party avatar packs without changing core Jarvis behavior.

The architectural decision is to avoid creating a giant frontend fork. Existing navigation, chat, tasks, drawers, administration and backend APIs stay shared. Only the central presence renderer and optional effects vary.

## Goals

1. Separate shell selection from presence renderer selection.
2. Keep one shared functional UI and business-logic path.
3. Make presence react to truthful Jarvis state.
4. Make heavy renderers lazy-loadable.
5. Persist user presentation preference centrally while retaining a local bootstrap cache.
6. Support per-device performance policy and deterministic fallback.
7. Respect reduced motion and accessibility.
8. Keep camera/biometric data outside Jarvis memory, logs and normal backend data.

## Non-goals

- Rewriting task/chat/admin pages.
- Replacing Tauri.
- Implementing the rigged humanoid runtime in this RFC.
- Sending webcam frames to the backend, an LLM or cloud service.
- Requiring a camera.
- Recreating another product's branding or exact trade dress.
- Making a visual renderer responsible for agent reasoning.

## Presentation model

```ts
export type ShellMode = "classic" | "hud"
export type PresenceMode = "none" | "neural" | "humanoid"
export type PresencePerformancePreset = "auto" | "efficient" | "balanced" | "cinematic"
export type AttentionMode = "off" | "pointer" | "camera"
export type ReducedMotionMode = "system" | "reduce" | "full"

export interface PresentationSettings {
  shell: ShellMode
  requestedPresence: PresenceMode
  performancePreset: PresencePerformancePreset
  attentionMode: AttentionMode
  reducedMotion: ReducedMotionMode
  avatarId: string
}
```

User-facing mode cards may still show Classic, Neural HUD and Humanoid HUD. Internally these map onto shell + presence.

## Canonical presence state

Renderers do not inspect arbitrary app objects directly. They receive a normalized snapshot:

```ts
export type PresencePhase =
  | "offline"
  | "idle"
  | "listening"
  | "thinking"
  | "executing"
  | "speaking"
  | "waiting"
  | "alert"

export interface PresenceSnapshot {
  phase: PresencePhase
  intensity: number
  connected: boolean
  activeTaskId?: string
  activeTaskLabel?: string
  runningTaskCount: number
  decisionCount: number
  systemDegraded: boolean
  audioLevel: number
  attention?: {
    x: number
    y: number
    z?: number
    confidence: number
    source: "pointer" | "camera"
  }
}
```

Deterministic phase priority:

1. offline
2. alert
3. speaking
4. listening
5. executing
6. thinking
7. waiting
8. idle

Ordinary transitions should use a short hold/hysteresis; alert and active voice transitions may interrupt immediately.

## PresenceHost

`PresenceHost` is the sole renderer-selection point.

Responsibilities:

- resolve requested vs effective presence;
- check whether a renderer is currently implemented/supported;
- lazy-load heavy renderers;
- pass normalized state;
- enforce reduced motion;
- provide error boundaries/fallbacks;
- never grant tools or reasoning capability.

Fallback order:

```text
humanoid -> neural -> CSS/static -> none
```

Until RFC-0051 lands, requested `humanoid` must deterministically resolve to `neural` with a renderer-unavailable fallback reason. The requested value remains persisted so the humanoid activates automatically once its runtime becomes available.

## Persistence

Backend settings are authoritative after load. LocalStorage remains a bootstrap/migration cache only.

Backend model:

```py
class PresentationSettings(BaseModel):
    shell: Literal["classic", "hud"] = "hud"
    requested_presence: Literal["none", "neural", "humanoid"] = "neural"
    performance_preset: Literal["auto", "efficient", "balanced", "cinematic"] = "auto"
    attention_mode: Literal["off", "pointer", "camera"] = "pointer"
    reduced_motion: Literal["system", "reduce", "full"] = "system"
    avatar_id: str = "jarvis_base"
```

Existing UI preference migration:

```text
classic -> shell=classic, presence=none
hud     -> shell=hud, presence=neural
```

Persist requested rather than effective presence.

## User experience

Settings adds an Appearance & Presence card:

- Interface: Classic / Neural HUD / Humanoid HUD.
- Jarvis attention: Off / Follow pointer / Camera.
- Rendering: Auto / Efficient / Balanced / Cinematic.
- Motion: System / Reduce / Full.
- Avatar: base Jarvis avatar identifier, with room for future packs.

Switching is hot: no frontend restart, backend restart, task reset or conversation loss.

Camera attention may be selectable as a preference but RFC-0050 must not acquire a MediaStream. Camera implementation is later and requires explicit activation at the point of use.

## Performance and lifecycle

- Neural remains available without humanoid dependencies.
- Humanoid code is lazy loaded by RFC-0051.
- Hidden windows should not consume heavy render loops where practical.
- WebGL resources are disposed on unmount.
- `prefers-reduced-motion` is respected unless explicitly overridden.
- Renderer failure must not take down chat/admin controls.

Quality presets form a stable contract for later renderers:

- Efficient: lower DPR/frame target/effects.
- Balanced: normal desktop target.
- Cinematic: richer effects on capable hardware.
- Auto: runtime chooses and may step down if frame budget is missed.

## Accessibility

- HTML/CSS shell remains primary for controls/content.
- 3D presence is never required to operate Jarvis.
- No essential state is conveyed only through color/motion.
- Screen-reader labels expose concise current phase.
- Decorative geometry is not keyboard-focusable.

## Security and privacy

- Presence renderer has no tool permissions.
- LLM/tool calls cannot enable camera capture.
- No camera capture is implemented in RFC-0050.
- Future camera frames must stay local and ephemeral.
- No face data, landmarks or embeddings enter prompts, memory, logs, telemetry, task history or licensing.
- If future camera attention loses permission, effective attention must fall back safely.

## Acceptance criteria

- Classic and Neural HUD can hot switch without restart.
- Humanoid can be selected as the requested mode and cleanly falls back to Neural until RFC-0051 exists.
- Existing v2 UI preference migrates correctly.
- `PresenceHost` is the sole presence renderer-selection point.
- Existing NeuralOrb is wrapped behind `NeuralPresence`.
- Backend persists validated presentation settings.
- Invalid shell/presence/performance/attention/motion values are rejected.
- Requested presence survives restart independently of effective presence.
- Camera is never acquired by this RFC.
- Reduced-motion behavior is respected.
- Renderer failure falls back without crashing chat/admin.
- Frontend production build passes.
- Backend tests cover defaults, persistence and invalid values.

## Delivery order

1. Presence types/state selector.
2. NeuralPresence adapter.
3. Backend presentation settings and localStorage migration.
4. Settings controls and hot switching.
5. PresenceHost/fallback boundary.
6. RFC-0051 humanoid runtime.
7. RFC-0052 entitlement gating.

This refactor is useful before the humanoid exists: it modularizes Jarvis presentation while keeping the current neural UI fully functional.