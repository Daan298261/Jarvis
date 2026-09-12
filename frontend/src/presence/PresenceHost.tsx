import { Component, lazy, Suspense, type ErrorInfo, type ReactNode } from "react"
import { NeuralPresence } from "./renderers/NeuralPresence"
import { supportsHumanoidRuntime } from "./renderers/humanoidRuntime"
import { PresenceFallback } from "./PresenceFallback"
import type { EffectivePresence, PresenceSnapshot, PresentationSettings } from "./presenceTypes"

const HumanoidPresence = lazy(() => import("./renderers/HumanoidPresence"))
const ParticleBustPresence = lazy(() => import("./renderers/ParticleBustPresence"))

function resolvePresence(settings: PresentationSettings): EffectivePresence {
  if ((settings.requestedPresence === "humanoid" || settings.requestedPresence === "particle_bust") && !supportsHumanoidRuntime()) {
    return {
      requested: settings.requestedPresence,
      effective: "neural",
      fallbackReason: "renderer_unavailable",
    }
  }
  return {
    requested: settings.requestedPresence,
    effective: settings.requestedPresence,
  }
}

type PresenceErrorBoundaryProps = {
  children: ReactNode
  fallback: ReactNode
}

type PresenceErrorBoundaryState = {
  failed: boolean
}

class PresenceErrorBoundary extends Component<PresenceErrorBoundaryProps, PresenceErrorBoundaryState> {
  state: PresenceErrorBoundaryState = { failed: false }

  static getDerivedStateFromError(): PresenceErrorBoundaryState {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn("Presence renderer failed; using static fallback.", error, info.componentStack)
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}

type PresenceHostProps = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  size?: number
  shapeId?: string
}

export function PresenceHost({ snapshot, settings, size = 540, shapeId }: PresenceHostProps) {
  const resolved = resolvePresence(settings)
  const staticFallback = <PresenceFallback snapshot={snapshot} />
  const neuralFallback = (
    <PresenceErrorBoundary fallback={staticFallback}>
      <NeuralPresence snapshot={snapshot} settings={settings} size={size} />
    </PresenceErrorBoundary>
  )

  return (
    <div
      className="jarvis-presence-host"
      data-requested-presence={resolved.requested}
      data-effective-presence={resolved.effective}
      data-fallback-reason={resolved.fallbackReason || ""}
    >
      {resolved.effective === "none" && staticFallback}
      {resolved.effective === "neural" && neuralFallback}
      {resolved.effective === "humanoid" && (
        <PresenceErrorBoundary key="humanoid" fallback={neuralFallback}>
          <Suspense fallback={neuralFallback}>
            <HumanoidPresence snapshot={snapshot} settings={settings} size={size} shapeId={shapeId} />
          </Suspense>
        </PresenceErrorBoundary>
      )}
      {resolved.effective === "particle_bust" && (
        <PresenceErrorBoundary key="particle-bust" fallback={neuralFallback}>
          <Suspense fallback={neuralFallback}>
            <ParticleBustPresence snapshot={snapshot} settings={settings} size={size} />
          </Suspense>
        </PresenceErrorBoundary>
      )}
      {resolved.fallbackReason && (
        <span className="jarvis-presence-fallback-note" role="status">
          {resolved.requested === "particle_bust" ? "Particle bust" : "Humanoid"} selected · Neural active because WebGL is unavailable
        </span>
      )}
    </div>
  )
}
