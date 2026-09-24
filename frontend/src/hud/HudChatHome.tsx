import { useCallback, useEffect, useRef, useState } from "react"
import { usePendingApprovals } from "../chat/pendingApprovals"
import { HudChat } from "./HudChat"
import { HudHexStrikeSuite } from "./HudHexStrikeSuite"
import { useHexStrikeSuiteActive } from "./hexstrikeSuite"
import { useHudOverlay } from "./hudOverlayContext"
import { deriveOrbMood, type OrbMood } from "./orbMood"
import type { Task } from "../api"
import { parseConfirmationPayload } from "../chat/PermissionPrompt"
import { AppearancePresenceControls } from "../presence/AppearancePresenceControls"
import { getActiveCustomComposition, useCustomPresence } from "../presence/customPresence"
import { PresenceHost } from "../presence/PresenceHost"
import { personaCardSentence, useNamedPersonas } from "../persona/namedPersonas"
import { derivePresenceSnapshot } from "../presence/presenceState"
import { usePresentationSettings } from "../presence/presentationSettings"
import { galaxyFigureShapeId, isGalaxyPresenceEffective } from "../presence/galaxyPresence"
import { supportsHumanoidRuntime } from "../presence/renderers/humanoidRuntime"
import { resolvePresenceShapeId } from "../presence/resolvePresenceShapeId"
import type { PresencePhase } from "../presence/presenceTypes"

const MOOD_COPY: Record<OrbMood, { label: string; detail: string }> = {
  idle: { label: "Ready", detail: "Local intelligence standing by" },
  listening: { label: "Listening", detail: "Voice input active" },
  thinking: { label: "Thinking", detail: "Jarvis is working on the current task" },
  speaking: { label: "Speaking", detail: "Jarvis is responding" },
  alert: { label: "Attention", detail: "A decision is waiting for you" },
}

function taskHasPendingDecision(task: Task | null, queuePending: boolean): boolean {
  if (queuePending) return true
  if (!task?.waiting_for_confirmation) return false
  const payload = parseConfirmationPayload(task.confirmation_payload)
  return Boolean(payload?.pending_id || payload?.permission_id || payload?.kind === "permission")
}

function presenceLabel(phase: PresencePhase, fallback: string, hexStrike: boolean): string {
  if (hexStrike) return "Aegis"
  if (phase === "executing") return "Working"
  if (phase === "error") return "Error"
  if (phase === "approval") return "Waiting for approval"
  if (phase === "offline") return "Offline"
  return fallback
}

function taskDetail(
  task: Task | null,
  mood: OrbMood,
  threadActive: boolean,
  approvalWaiting: boolean,
): string {
  if (approvalWaiting) return "Review the approval popup to continue"
  if (threadActive) return MOOD_COPY[mood].detail
  if (!task) return MOOD_COPY[mood].detail
  if (task.status === "failed") return task.error || "The current task needs attention"
  const title = task.title || task.prompt?.slice(0, 72)
  if (title) return `${title} · ${task.status}`
  return MOOD_COPY[mood].detail
}

export function HudChatHome() {
  const { hasPending: approvalQueuePending } = usePendingApprovals()
  const presentation = usePresentationSettings()
  const { active: hexStrikeActive } = useHexStrikeSuiteActive()
  const namedPersonas = useNamedPersonas()
  const customPresence = useCustomPresence()
  const { hexSuiteExpanded, setHexSuiteExpanded } = useHudOverlay()
  const wasHexStrike = useRef(false)
  const [moodState, setMoodState] = useState<{ recording: boolean; speaking: boolean; task: Task | null }>({
    recording: false,
    speaking: false,
    task: null,
  })

  const onMoodChange = useCallback(
    (opts: { recording: boolean; speaking: boolean; task: Task | null }) => setMoodState(opts),
    [],
  )

  useEffect(() => {
    if (hexStrikeActive && !wasHexStrike.current) {
      setHexSuiteExpanded(true)
    }
    wasHexStrike.current = hexStrikeActive
  }, [hexStrikeActive, setHexSuiteExpanded])

  const showHexSuite = hexStrikeActive && hexSuiteExpanded

  const approvalWaiting = taskHasPendingDecision(moodState.task, approvalQueuePending)
  const mood = deriveOrbMood(moodState.task, {
    recording: moodState.recording,
    speaking: moodState.speaking,
    systemDegraded: moodState.task?.status === "failed" || approvalWaiting,
    pendingApproval: approvalWaiting,
  })
  const snapshot = derivePresenceSnapshot({
    task: moodState.task,
    recording: moodState.recording,
    speaking: moodState.speaking,
    pendingApproval: approvalWaiting,
    systemDegraded: false,
  })
  const activePersona = namedPersonas?.active
  const personaShape = activePersona?.presence_shape_id || undefined
  const resolvedShapeId = resolvePresenceShapeId(
    hexStrikeActive,
    customPresence.activeShapeId,
    namedPersonas ? personaShape : "stormbird",
  )
  const cardSentence = moodState.task
    ? (moodState.task.persona_card_sentence
      || personaCardSentence(activePersona?.id || "anzu", moodState.task.specialist_persona_ids || []))
    : ""
  const presenceSettings = hexStrikeActive
    ? { ...presentation, requestedPresence: "humanoid" as const }
    : presentation
  const shapeId = galaxyFigureShapeId({
    requestedPresence: presenceSettings.requestedPresence,
    resolvedShapeId,
    suiteActive: hexStrikeActive,
    customPresetActive: Boolean(customPresence.activeShapeId),
    personaId: activePersona?.id,
  })
  const galaxyEffective = isGalaxyPresenceEffective({
    requestedPresence: presentation.requestedPresence,
    suiteOverride: hexStrikeActive,
    webglAvailable: supportsHumanoidRuntime(),
  })
  const customComposition = !hexStrikeActive && shapeId.startsWith("custom_ui_")
    ? getActiveCustomComposition()
    : null
  const personaVisual = !hexStrikeActive
    ? customComposition
      ? {
          orbColor: customComposition.orb_color,
          accentColor: customComposition.accent_color,
          glow: activePersona?.appearance?.glow ?? 0.7,
          animation: activePersona?.appearance?.animation ?? 0.7,
          scale: activePersona?.appearance?.scale ?? 1,
        }
      : activePersona?.appearance
        ? {
            orbColor: activePersona.appearance.orb_color,
            accentColor: activePersona.appearance.accent_color,
            glow: activePersona.appearance.glow,
            animation: activePersona.appearance.animation,
            scale: activePersona.appearance.scale,
          }
        : undefined
    : undefined
  const threadActive = Boolean(moodState.task?.messages?.length)
  const copy = MOOD_COPY[mood]

  return (
    <div
      className={`hud-home${hexStrikeActive ? " hexstrike-active" : ""}${hexStrikeActive && !showHexSuite ? " hex-suite-collapsed" : ""}${galaxyEffective ? " galaxy-effective" : ""}`}
    >
      <AppearancePresenceControls settings={presentation} />
      <section className="hud-orb-zone" aria-label="Jarvis state">
        <PresenceHost
          snapshot={snapshot}
          settings={presenceSettings}
          size={760}
          shapeId={shapeId}
          personaVisual={personaVisual}
        />
        <div className="hud-orb-caption" aria-live="polite">
          <span className={`hud-orb-state${snapshot.phase === "alert" || snapshot.phase === "error" || snapshot.phase === "approval" ? " alert" : ""}`}>
            {presenceLabel(snapshot.phase, copy.label, hexStrikeActive)}
          </span>
          <span className="hud-orb-detail">
            {hexStrikeActive
              ? "HexStrike cybersecurity suite"
              : taskDetail(moodState.task, mood, threadActive, approvalWaiting)}
          </span>
          {cardSentence && <span className="hud-orb-detail hud-persona-sentence">{cardSentence}</span>}
        </div>
      </section>
      {showHexSuite && <HudHexStrikeSuite />}
      <HudChat onMoodChange={onMoodChange} />
    </div>
  )
}
