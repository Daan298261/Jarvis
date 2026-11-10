import { Component, useEffect, useState, type ReactNode } from "react"
import { createRoot } from "react-dom/client"
import { MorphablePresenceStage } from "./renderers/MorphablePresenceStage"
import { preparePortraitCloud } from "./renderers/shapes/portraitCloud"
import { DEFAULT_PRESENTATION_SETTINGS, type PresencePhase, type PresenceSnapshot } from "./presenceTypes"

type MobileState = { phase: PresencePhase; audioLevel: number; reducedMotion: boolean }
declare global { interface Window { updateAnzuPresence?: (state: MobileState) => void } }

class NativeFallback extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch() { document.title = "anzu-presence-fallback" }
  render() { return this.state.failed ? null : this.props.children }
}

function MobilePresence() {
  const [state, update] = useState<MobileState>({ phase: "idle", audioLevel: 0, reducedMotion: false })
  const [shape, setShape] = useState("humanoid_bust")
  useEffect(() => {
    let mounted = true
    preparePortraitCloud(new URL("presence/jarvis-original/humanoid.webp", document.baseURI).href, "humanoid")
      .then(id => { if (mounted) setShape(id) })
      .catch(() => { document.title = "anzu-presence-fallback" })
    return () => { mounted = false }
  }, [])
  useEffect(() => { window.updateAnzuPresence = update; return () => { delete window.updateAnzuPresence } }, [])
  const snapshot: PresenceSnapshot = {
    phase: state.phase, intensity: 0.7, audioLevel: state.audioLevel,
    connected: state.phase !== "offline", runningTaskCount: 0, decisionCount: 0, systemDegraded: false,
  }
  return <MorphablePresenceStage snapshot={snapshot}
    settings={{ ...DEFAULT_PRESENTATION_SETTINGS, requestedPresence: "humanoid", performancePreset: "auto", attentionMode: "pointer", reducedMotion: state.reducedMotion ? "reduce" : "system" }}
    shapeId={shape} personaVisual={{ glow: 0.82, detail: 0.68, animation: 0.72, scale: 1, pointScale: 1, depthSoftness: 0 }}
    className="jarvis-presence jarvis-presence-stage jarvis-presence-humanoid"
    ariaLabel={`ANZU is ${state.phase}`} style={{ width: "100vw", height: "100vh", minHeight: 0 }} />
}

createRoot(document.getElementById("root")!).render(<NativeFallback><MobilePresence /></NativeFallback>)
