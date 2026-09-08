import { Component, type ErrorInfo, type ReactNode } from "react"
import { NeuralPresence } from "./renderers/NeuralPresence"
import { PresenceFallback } from "./PresenceFallback"
import type { EffectivePresence, PresenceSnapshot, PresentationSettings } from "./presenceTypes"

const HUMANOID_RUNTIME_AVAILABLE = false

function resolvePresence(settings: PresentationSettings): EffectivePresence {
  if (settings.requestedPresence === "humanoid" && !HUMANOID_RUNTIME_AVAILABLE) {
    return {
      requested: "humanoid",
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
}

export function PresenceHost({ snapshot, settings, size = 540 }: PresenceHostProps) {
  const resolved = resolvePresence(settings)
  const fallback = <PresenceFallback snapshot={snapshot} />

  return (
    <div
      className="jarvis-presence-host"
      data-requested-presence={resolved.requested}
      data-effective-presence={resolved.effective}
      data-fallback-reason={resolved.fallbackReason || ""}
    >
      <PresenceErrorBoundary fallback={fallback}>
        {resolved.effective === "none" ? fallback : (
          <NeuralPresence snapshot={snapshot} settings={settings} size={size} />
        )}
      </PresenceErrorBoundary>
      {resolved.fallbackReason === "renderer_unavailable" && (
        <span className="jarvis-presence-fallback-note" role="status">
          Humanoid selected · Neural active until the humanoid runtime is installed
        </span>
      )}
    </div>
  )
}
