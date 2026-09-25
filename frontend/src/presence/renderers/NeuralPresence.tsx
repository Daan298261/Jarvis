import { lazy, Suspense, useCallback, useRef, type CSSProperties } from "react"
import { useNavigate } from "react-router-dom"
import type { ApexSelection } from "../../vendor/apex-ui/ReasoningWeb"
import ApexOrb, { type ApexOrbState } from "../../vendor/apex-ui/ApexOrb"
import { usePresenceAttentionLoop } from "../usePresenceAttentionLoop"
import { supportsHumanoidRuntime } from "./humanoidRuntime"
import { NeuralChrome, neuralSpecialistRoute, type NeuralPresenceProps } from "./neuralChrome"
import "../../vendor/apex-ui/apex-orb.css"
import "./apex-presence.css"

const NeuralCloudPresence = lazy(() => import("./NeuralCloudPresence"))

function orbState(phase: NeuralPresenceProps["snapshot"]["phase"]): ApexOrbState {
  switch (phase) {
    case "listening": return "listening"
    case "speaking": return "speaking"
    case "thinking":
    case "executing":
    case "alert": return "thinking"
    case "offline":
    case "waiting":
    case "idle":
    default: return "idle"
  }
}

function LegacyNeuralPresence({ snapshot, settings, size = 540 }: NeuralPresenceProps) {
  const navigate = useNavigate()
  const orbRef = useRef<HTMLDivElement>(null)
  const reduced = settings.reducedMotion === "reduce"
  usePresenceAttentionLoop({ settings, cssTargetRef: orbRef, cssScale: 1.35 })
  const onSelect = useCallback((selection: ApexSelection) => {
    const route = neuralSpecialistRoute(selection.key)
    if (route) navigate(route)
  }, [navigate])

  return (
    <div
      className={`jarvis-presence jarvis-presence-neural jarvis-apex-presence${reduced ? " reduced-motion" : ""}`}
      data-performance-preset={settings.performancePreset}
      data-attention-mode={settings.attentionMode}
      data-phase={snapshot.phase}
      data-lifecycle="off"
      aria-label={`Jarvis is ${snapshot.phase}`}
      style={{ "--jarvis-apex-size": `${size}px` } as CSSProperties}
    >
      <NeuralChrome snapshot={snapshot} settings={settings} onSelect={onSelect} />
      <div ref={orbRef} className="jarvis-apex-vendored-orb" aria-hidden="true">
        <ApexOrb state={orbState(snapshot.phase)} />
      </div>
    </div>
  )
}

function NeuralLoadingShell({ snapshot, settings, size = 540 }: NeuralPresenceProps) {
  const navigate = useNavigate()
  const reduced = settings.reducedMotion === "reduce"
  const onSelect = useCallback((selection: ApexSelection) => {
    const route = neuralSpecialistRoute(selection.key)
    if (route) navigate(route)
  }, [navigate])
  return (
    <div
      className={`jarvis-presence jarvis-presence-neural jarvis-apex-presence${reduced ? " reduced-motion" : ""}`}
      data-phase={snapshot.phase}
      data-lifecycle="loading"
      aria-label={`Jarvis is ${snapshot.phase}`}
      style={{ "--jarvis-apex-size": `${size}px` } as CSSProperties}
    >
      <NeuralChrome snapshot={snapshot} settings={settings} onSelect={onSelect} />
    </div>
  )
}

export function NeuralPresence(props: NeuralPresenceProps) {
  if (!supportsHumanoidRuntime()) return <LegacyNeuralPresence {...props} />
  return (
    <Suspense fallback={<NeuralLoadingShell {...props} />}>
      <NeuralCloudPresence {...props} />
    </Suspense>
  )
}

export type { NeuralPresenceProps }
