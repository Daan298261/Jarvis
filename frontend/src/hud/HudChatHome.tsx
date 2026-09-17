import { useCallback, useEffect, useRef, useState } from "react"
import { usePendingApprovals } from "../chat/pendingApprovals"
import { HudChat } from "./HudChat"
import { HudHexStrikeSuite } from "./HudHexStrikeSuite"
import { HEXSTRIKE_SHAPE_ID, useHexStrikeSuiteActive } from "./hexstrikeSuite"
import { useHudOverlay } from "./hudOverlayContext"
import { deriveOrbMood, type OrbMood } from "./orbMood"
import type { Task } from "../api"
import { parseConfirmationPayload } from "../chat/PermissionPrompt"
import { AppearancePresenceControls } from "../presence/AppearancePresenceControls"
import { PresenceHost } from "../presence/PresenceHost"
import { derivePresenceSnapshot } from "../presence/presenceState"
import { usePresentationSettings } from "../presence/presentationSettings"

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
    systemDegraded: moodState.task?.status === "failed" || approvalWaiting,
  })
  const threadActive = Boolean(moodState.task?.messages?.length)
  const copy = MOOD_COPY[mood]
  const presenceSettings = hexStrikeActive
    ? { ...presentation, requestedPresence: "humanoid" as const }
    : presentation

  return (
    <div
      className={`hud-home${hexStrikeActive ? " hexstrike-active" : ""}${hexStrikeActive && !showHexSuite ? " hex-suite-collapsed" : ""}`}
    >
      <AppearancePresenceControls settings={presentation} />
      <section className="hud-orb-zone" aria-label="Jarvis state">
        <PresenceHost
          snapshot={snapshot}
          settings={presenceSettings}
          size={760}
          shapeId={hexStrikeActive ? HEXSTRIKE_SHAPE_ID : undefined}
        />
        <div className="hud-orb-caption" aria-live="polite">
          <span className={`hud-orb-state${mood === "alert" ? " alert" : ""}`}>
            {hexStrikeActive ? "Aegis" : copy.label}
          </span>
          <span className="hud-orb-detail">
            {hexStrikeActive
              ? "HexStrike cybersecurity suite"
              : taskDetail(moodState.task, mood, threadActive, approvalWaiting)}
          </span>
        </div>
      </section>
      {showHexSuite && <HudHexStrikeSuite />}
      <HudChat onMoodChange={onMoodChange} />
    </div>
  )
}
